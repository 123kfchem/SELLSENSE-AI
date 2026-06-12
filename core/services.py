from collections import defaultdict
import calendar
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import F, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone

from .models import Business, Expense, Sale
from .tenancy import get_user_business

VALID_PERIODS = frozenset({"daily", "weekly", "monthly", "yearly"})


def _tenant_business(user):
    return get_user_business(user)


def _normalize_period(period):
    if period not in VALID_PERIODS:
        raise ValueError(f"Invalid period: {period!r}")
    return period


def _local_now():
    return timezone.localtime(timezone.now())


def _local_today():
    return _local_now().date()


def _aware_start_of_day(day):
    start = datetime.combine(day, datetime.min.time())
    if timezone.is_naive(start):
        return timezone.make_aware(start, timezone.get_current_timezone())
    return start


MONEY_QUANTIZE = Decimal("0.01")


def _quantize_money(value):
    if value is None:
        return Decimal("0.00")
    return Decimal(value).quantize(MONEY_QUANTIZE)


def _decimal_sum(values):
    return _quantize_money(
        sum((value or Decimal("0.00") for value in values), Decimal("0.00"))
    )


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    return value


def _take_tiers_from_sorted(rows, limit):
    """Take full quantity tiers from an ordered list until the next tier would exceed limit."""
    selected = []
    index = 0
    while index < len(rows):
        tier_qty = rows[index]["total_qty"]
        tier = [row for row in rows if row["total_qty"] == tier_qty]
        if len(selected) + len(tier) <= limit:
            selected.extend(tier)
            index += len(tier)
        else:
            break
    return selected


def _split_top_and_least_selling(product_rows, top_limit=3):
    """Partition sales rows into top and least lists with no overlap."""
    sorted_desc = list(product_rows)
    count = len(sorted_desc)
    if count == 0:
        return [], []

    if count <= top_limit:
        max_qty = sorted_desc[0]["total_qty"]
        top_selling = [row for row in sorted_desc if row["total_qty"] == max_qty]
        top_names = {row["name"] for row in top_selling}
        least_selling = sorted(
            (row for row in sorted_desc if row["name"] not in top_names),
            key=lambda row: (row["total_qty"], row["name"]),
        )
        return top_selling, least_selling

    top_selling = _take_tiers_from_sorted(sorted_desc, top_limit)
    top_names = {row["name"] for row in top_selling}
    remaining = sorted(
        (row for row in sorted_desc if row["name"] not in top_names),
        key=lambda row: (row["total_qty"], row["name"]),
    )
    least_selling = _take_tiers_from_sorted(remaining, top_limit)
    return top_selling, least_selling


def ai_item_suggestions(user):
    business = _tenant_business(user)
    product_rows = list(
        Sale.objects.for_business(business)
        .values(name=F("item__name"))
        .annotate(total_qty=Sum("quantity"), revenue=Sum("total_amount"))
        .order_by("-total_qty", "name")
    )
    top_selling, least_selling = _split_top_and_least_selling(product_rows)

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    sales_qs = Sale.objects.for_business(business)
    previous_period = sales_qs.filter(
        sold_at__gte=fourteen_days_ago,
        sold_at__lt=seven_days_ago,
    )
    if not previous_period.exists():
        return {
            "top_selling": top_selling,
            "least_selling": least_selling,
            "growth_items": [],
            "growth_message": (
                "Not enough historical sales data to calculate growth trends."
            ),
        }

    previous = {
        row["item__name"]: row["qty"] or 0
        for row in previous_period.values("item__name").annotate(qty=Sum("quantity"))
    }
    current = {
        row["item__name"]: row["qty"] or 0
        for row in sales_qs.filter(sold_at__gte=seven_days_ago)
        .values("item__name")
        .annotate(qty=Sum("quantity"))
    }

    growth_items = []
    for name, prev in previous.items():
        curr = current.get(name, 0)
        pct = ((Decimal(curr) - Decimal(prev)) / Decimal(prev)) * Decimal(100)
        growth_items.append(
            {
                "name": name,
                "growth_pct": round(pct, 2),
                "current_qty": curr,
                "previous_qty": prev,
            }
        )
    growth_items.sort(key=lambda row: row["growth_pct"], reverse=True)

    return {
        "top_selling": top_selling,
        "least_selling": least_selling,
        "growth_items": growth_items[:3],
        "growth_message": None,
    }


def sales_summary(user, period="daily"):
    business = _tenant_business(user)
    period = _normalize_period(period)
    now = timezone.now()
    local_now = timezone.localtime(now)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "weekly":
        start_local = start_local - timedelta(days=7)
    elif period == "monthly":
        start_local = start_local - timedelta(days=30)

    sales = (
        Sale.objects.for_business(business)
        .filter(sold_at__gte=start_local)
        .select_related("item", "sold_by")
    )
    total_revenue = _quantize_money(sales.aggregate(total=Sum("total_amount"))["total"])
    total_units = sales.aggregate(total=Sum("quantity"))["total"] or 0
    return sales, total_revenue, total_units


def ml_sales_analysis_table(user, period="daily"):
    business = _tenant_business(user)
    period = _normalize_period(period)
    now = timezone.now()
    local_now = timezone.localtime(now)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_days = 1
    if period == "weekly":
        start_local = start_local - timedelta(days=7)
        window_days = 7
    elif period == "monthly":
        start_local = start_local - timedelta(days=30)
        window_days = 30
    start = start_local.date()
    start_dt = start_local

    qs = (
        Sale.objects.for_business(business)
        .filter(sold_at__gte=start_dt)
        .values("item__id", "item__name", "sold_at__date")
        .annotate(qty=Sum("quantity"), revenue=Sum("total_amount"))
    )

    if not qs:
        return []

    daily_item_qty = defaultdict(lambda: defaultdict(float))
    item_name = {}
    item_revenue = defaultdict(float)
    for row in qs:
        item_id = row["item__id"]
        item_name[item_id] = row["item__name"]
        item_revenue[item_id] += float(row["revenue"] or 0)
        date_key = row["sold_at__date"]
        if date_key is None:
            continue
        day_idx = (date_key - start).days
        if day_idx < 0 or day_idx >= window_days:
            continue
        daily_item_qty[item_id][day_idx] += float(row["qty"] or 0)

    rows = []
    totals = []
    slopes = []
    for item_id, by_day in daily_item_qty.items():
        y = [float(by_day.get(i, 0.0)) for i in range(window_days)]
        total_qty = float(sum(y))
        if window_days > 1:
            n = float(window_days)
            x_sum = sum(range(window_days))
            y_sum = sum(y)
            xy_sum = sum(i * y[i] for i in range(window_days))
            x2_sum = sum(i * i for i in range(window_days))
            denom = (n * x2_sum) - (x_sum * x_sum)
            slope = ((n * xy_sum) - (x_sum * y_sum)) / denom if denom else 0.0
        else:
            slope = 0.0
        avg_daily = total_qty / float(max(window_days, 1))
        rows.append(
            {
                "item": item_name[item_id],
                "total_qty": int(total_qty),
                "avg_daily_qty": round(avg_daily, 2),
                "revenue": round(item_revenue[item_id], 2),
                "trend_slope": round(slope, 4),
            }
        )
        totals.append(total_qty)
        slopes.append(slope)

    max_total = max(totals) if totals else 1.0
    max_slope = max(slopes) if slopes else 0.0
    min_slope = min(slopes) if slopes else 0.0
    slope_span = (max_slope - min_slope) if (max_slope - min_slope) != 0 else 1.0

    for row in rows:
        demand_score = (row["total_qty"] / max_total) * 100.0 if max_total else 0.0
        trend_score = ((row["trend_slope"] - min_slope) / slope_span) * 100.0
        risk_score = max(0.0, 100.0 - demand_score) * 0.6 + max(0.0, 50.0 - trend_score) * 0.4
        opportunity_score = demand_score * 0.55 + trend_score * 0.45

        if trend_score > 60 and demand_score > 60:
            recommendation = "Scale stock and promote"
        elif trend_score < 35 and demand_score < 40:
            recommendation = "Discount or bundle"
        else:
            recommendation = "Monitor and optimize pricing"

        row["demand_score"] = round(demand_score, 2)
        row["trend_score"] = round(trend_score, 2)
        row["risk_score"] = round(min(risk_score, 100.0), 2)
        row["opportunity_score"] = round(min(opportunity_score, 100.0), 2)
        row["recommendation"] = recommendation

    rows.sort(key=lambda r: r["opportunity_score"], reverse=True)
    return rows


def weekly_revenue_report(user):
    """Revenue per day for the last 7 days (including today)."""
    business = _tenant_business(user)
    today = _local_today()
    start_day = today - timedelta(days=6)
    start_dt = _aware_start_of_day(start_day)

    daily_totals = {
        _as_date(row["day"]): _quantize_money(row["revenue"])
        for row in (
            Sale.objects.for_business(business)
            .filter(sold_at__gte=start_dt)
            .annotate(day=TruncDate("sold_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(revenue=Sum("total_amount"))
        )
    }

    rows = []
    for offset in range(7):
        day = start_day + timedelta(days=offset)
        rows.append(
            {
                "label": day.strftime("%A"),
                "sub_label": day.strftime("%d %b %Y"),
                "revenue": daily_totals.get(_as_date(day), Decimal("0.00")),
            }
        )
    total_revenue = _decimal_sum(row["revenue"] for row in rows)
    return {
        "rows": rows,
        "total_revenue": total_revenue,
        "title": "Weekly Revenue Report",
        "summary_label": "Total Weekly Revenue",
    }


def monthly_revenue_report(user):
    """Revenue per calendar week for the last 30 days."""
    business = _tenant_business(user)
    today = _local_today()
    start_day = today - timedelta(days=29)
    start_dt = _aware_start_of_day(start_day)

    weekly_totals = {}
    for row in (
        Sale.objects.for_business(business)
        .filter(sold_at__gte=start_dt)
        .annotate(week=TruncWeek("sold_at", tzinfo=timezone.get_current_timezone()))
        .values("week")
        .annotate(revenue=Sum("total_amount"))
        .order_by("week")
    ):
        weekly_totals[_as_date(row["week"])] = _quantize_money(row["revenue"])

    rows = []
    week_start = start_day - timedelta(days=start_day.weekday())
    while week_start <= today:
        week_end = min(week_start + timedelta(days=6), today)
        rows.append(
            {
                "label": f"Week of {week_start.strftime('%d %b %Y')}",
                "sub_label": f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}",
                "revenue": weekly_totals.get(_as_date(week_start), Decimal("0.00")),
            }
        )
        week_start += timedelta(days=7)

    total_revenue = _decimal_sum(row["revenue"] for row in rows)
    return {
        "rows": rows,
        "total_revenue": total_revenue,
        "title": "Monthly Revenue Report",
        "summary_label": "Total Monthly Revenue",
    }


def _add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    return day.replace(year=year, month=month, day=min(day.day, max_day))


def _business_year_end(month_start):
    last_month = _add_months(month_start.replace(day=1), 11)
    return last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])


def _current_business_year_start(year_start_date, today):
    period_start = year_start_date.replace(day=1)
    while _business_year_end(period_start) < today:
        period_start = _add_months(period_start, 12)
    return period_start


def _business_year_bounds(business):
    if not business.year_start_date:
        return [], None, None

    today = _local_today()
    period_start = _current_business_year_start(business.year_start_date, today)
    month_starts = [_add_months(period_start, offset) for offset in range(12)]
    return month_starts, period_start, _business_year_end(period_start)


def ensure_business_year_start(user, sale_datetime):
    business = _tenant_business(user)
    if business.year_start_date:
        return business.year_start_date

    local_date = timezone.localtime(sale_datetime).date()
    updated = Business.objects.filter(
        pk=business.pk,
        year_start_date__isnull=True,
    ).update(year_start_date=local_date)
    if updated:
        business.year_start_date = local_date
    return business.year_start_date


def _empty_business_year_report(title, summary_label):
    return {
        "rows": [],
        "total_revenue": Decimal("0.00"),
        "title": title,
        "summary_label": summary_label,
        "year_start_date": None,
        "year_end_date": None,
        "awaiting_first_sale": True,
    }


def yearly_revenue_report(user):
    """Revenue per month for the current business year (12 months from first sale)."""
    business = _tenant_business(user)
    month_starts, period_start, period_end = _business_year_bounds(business)
    if not month_starts:
        return _empty_business_year_report(
            "Yearly Revenue Report",
            "Total Yearly Revenue",
        )

    start_dt = _aware_start_of_day(period_start)
    monthly_totals = {}
    for row in (
        Sale.objects.for_business(business)
        .filter(sold_at__gte=start_dt)
        .annotate(month=TruncMonth("sold_at", tzinfo=timezone.get_current_timezone()))
        .values("month")
        .annotate(revenue=Sum("total_amount"))
        .order_by("month")
    ):
        month_start = _as_date(row["month"])
        if month_start is not None:
            month_start = month_start.replace(day=1)
            monthly_totals[month_start] = _quantize_money(row["revenue"])

    rows = []
    for month_start in month_starts:
        rows.append(
            {
                "label": month_start.strftime("%B %Y"),
                "sub_label": month_start.strftime("%Y"),
                "revenue": monthly_totals.get(month_start, Decimal("0.00")),
            }
        )

    total_revenue = _decimal_sum(row["revenue"] for row in rows)
    return {
        "rows": rows,
        "total_revenue": total_revenue,
        "title": "Yearly Revenue Report",
        "summary_label": "Total Yearly Revenue",
        "year_start_date": period_start,
        "year_end_date": period_end,
        "awaiting_first_sale": False,
    }


def period_revenue_report(user, period):
    period = _normalize_period(period)
    if period == "weekly":
        return weekly_revenue_report(user)
    if period == "monthly":
        return monthly_revenue_report(user)
    if period == "yearly":
        return yearly_revenue_report(user)
    return None


def _period_start_day(business, period="daily"):
    if period == "yearly":
        month_starts, _, _ = _business_year_bounds(business)
        if not month_starts:
            return _local_today()
        return month_starts[0]

    local_now = timezone.localtime(timezone.now())
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "weekly":
        start_local = start_local - timedelta(days=7)
    elif period == "monthly":
        start_local = start_local - timedelta(days=30)
    return start_local.date()


def expenses_summary(user, period="daily"):
    business = _tenant_business(user)
    period = _normalize_period(period)
    if period == "yearly" and not business.year_start_date:
        return Expense.objects.for_business(business).none(), Decimal("0.00")

    start_day = _period_start_day(business, period)
    expenses = Expense.objects.for_business(business).filter(
        expense_date__gte=start_day
    )
    if period == "yearly":
        _, _, period_end = _business_year_bounds(business)
        expenses = expenses.filter(expense_date__lte=period_end)
    expenses = expenses.select_related("recorded_by")
    total_expenses = _quantize_money(expenses.aggregate(total=Sum("amount"))["total"])
    return expenses, total_expenses


def profit_summary(user, period="daily"):
    _, total_revenue, total_units = sales_summary(user, period)
    _, total_expenses = expenses_summary(user, period)
    return {
        "revenue": total_revenue,
        "expenses": total_expenses,
        "net_profit": _quantize_money(total_revenue - total_expenses),
        "units": total_units,
    }


def _expense_totals_by_day(business, start_day, end_day):
    return {
        row["expense_date"]: _quantize_money(row["total"])
        for row in (
            Expense.objects.for_business(business)
            .filter(expense_date__gte=start_day, expense_date__lte=end_day)
            .values("expense_date")
            .annotate(total=Sum("amount"))
        )
    }


def weekly_profit_report(user):
    business = _tenant_business(user)
    revenue_report = weekly_revenue_report(user)
    today = _local_today()
    start_day = today - timedelta(days=6)
    daily_expenses = _expense_totals_by_day(business, start_day, today)

    enriched_rows = []
    for offset, row in enumerate(revenue_report["rows"]):
        day = start_day + timedelta(days=offset)
        expenses = daily_expenses.get(day, Decimal("0.00"))
        enriched_rows.append(
            {
                **row,
                "expenses": expenses,
                "net_profit": _quantize_money(row["revenue"] - expenses),
            }
        )
    total_expenses = _decimal_sum(row["expenses"] for row in enriched_rows)
    return {
        **revenue_report,
        "rows": enriched_rows,
        "total_expenses": total_expenses,
        "net_profit": _quantize_money(revenue_report["total_revenue"] - total_expenses),
    }


def monthly_profit_report(user):
    business = _tenant_business(user)
    revenue_report = monthly_revenue_report(user)
    today = _local_today()
    start_day = today - timedelta(days=29)

    weekly_expenses = {}
    for row in (
        Expense.objects.for_business(business)
        .filter(expense_date__gte=start_day, expense_date__lte=today)
        .annotate(week=TruncWeek("expense_date"))
        .values("week")
        .annotate(total=Sum("amount"))
        .order_by("week")
    ):
        weekly_expenses[_as_date(row["week"])] = _quantize_money(row["total"])

    enriched_rows = []
    week_start = start_day - timedelta(days=start_day.weekday())
    for row in revenue_report["rows"]:
        expenses = weekly_expenses.get(_as_date(week_start), Decimal("0.00"))
        enriched_rows.append(
            {
                **row,
                "expenses": expenses,
                "net_profit": _quantize_money(row["revenue"] - expenses),
            }
        )
        week_start += timedelta(days=7)

    total_expenses = _decimal_sum(row["expenses"] for row in enriched_rows)
    return {
        **revenue_report,
        "rows": enriched_rows,
        "total_expenses": total_expenses,
        "net_profit": _quantize_money(revenue_report["total_revenue"] - total_expenses),
    }


def yearly_profit_report(user):
    business = _tenant_business(user)
    revenue_report = yearly_revenue_report(user)
    month_starts, _, period_end = _business_year_bounds(business)
    if not month_starts:
        return {
            **revenue_report,
            "total_expenses": Decimal("0.00"),
            "net_profit": Decimal("0.00"),
        }

    monthly_expenses = {}
    for row in (
        Expense.objects.for_business(business)
        .filter(expense_date__gte=month_starts[0], expense_date__lte=period_end)
        .annotate(month=TruncMonth("expense_date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    ):
        month_start = _as_date(row["month"])
        if month_start is not None:
            monthly_expenses[month_start.replace(day=1)] = _quantize_money(row["total"])

    enriched_rows = []
    for month_start, row in zip(month_starts, revenue_report["rows"]):
        expenses = monthly_expenses.get(month_start, Decimal("0.00"))
        enriched_rows.append(
            {
                **row,
                "expenses": expenses,
                "net_profit": _quantize_money(row["revenue"] - expenses),
            }
        )

    total_expenses = _decimal_sum(row["expenses"] for row in enriched_rows)
    return {
        **revenue_report,
        "rows": enriched_rows,
        "total_expenses": total_expenses,
        "net_profit": _quantize_money(revenue_report["total_revenue"] - total_expenses),
    }


def period_profit_report(user, period):
    period = _normalize_period(period)
    if period == "weekly":
        return weekly_profit_report(user)
    if period == "monthly":
        return monthly_profit_report(user)
    if period == "yearly":
        return yearly_profit_report(user)
    return None
