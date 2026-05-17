from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import F, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone

from .models import Sale


def _local_now():
    return timezone.localtime(timezone.now())


def _local_today():
    return _local_now().date()


def _aware_start_of_day(day):
    start = datetime.combine(day, datetime.min.time())
    if timezone.is_naive(start):
        return timezone.make_aware(start, timezone.get_current_timezone())
    return start


def _decimal_sum(values):
    return sum((value or Decimal("0.00") for value in values), Decimal("0.00"))


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    return value


def ai_item_suggestions(business):
    base = (
        Sale.objects.for_business(business)
        .values(name=F("item__name"))
        .annotate(total_qty=Sum("quantity"), revenue=Sum("total_amount"))
        .order_by("-total_qty")
    )
    top_selling = list(base[:3])
    least_selling = list(base.order_by("total_qty")[:3])

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    sales_qs = Sale.objects.for_business(business)
    previous = {
        x["item__name"]: x["qty"]
        for x in sales_qs.filter(sold_at__gte=fourteen_days_ago, sold_at__lt=seven_days_ago)
        .values("item__name")
        .annotate(qty=Sum("quantity"))
    }
    current = (
        sales_qs.filter(sold_at__gte=seven_days_ago)
        .values("item__name")
        .annotate(qty=Sum("quantity"))
    )

    growth_items = []
    for row in current:
        name = row["item__name"]
        curr = row["qty"] or 0
        prev = previous.get(name, 0)
        if curr > prev and curr > 0:
            pct = Decimal(100) if prev == 0 else ((curr - prev) / Decimal(prev)) * Decimal(100)
            growth_items.append({"name": name, "growth_pct": round(pct, 2), "current_qty": curr})
    growth_items.sort(key=lambda x: x["growth_pct"], reverse=True)

    return {
        "top_selling": top_selling,
        "least_selling": least_selling,
        "growth_items": growth_items[:3],
    }


def sales_summary(business, period="daily"):
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
    total_revenue = sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    total_units = sales.aggregate(total=Sum("quantity"))["total"] or 0
    return sales, total_revenue, total_units


def ml_sales_analysis_table(business, period="daily"):
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


def weekly_revenue_report(business):
    """Revenue per day for the last 7 days (including today)."""
    today = _local_today()
    start_day = today - timedelta(days=6)
    start_dt = _aware_start_of_day(start_day)

    daily_totals = {
        _as_date(row["day"]): row["revenue"] or Decimal("0.00")
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


def monthly_revenue_report(business):
    """Revenue per calendar week for the last 30 days."""
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
        weekly_totals[_as_date(row["week"])] = row["revenue"] or Decimal("0.00")

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


def yearly_revenue_report(business):
    """Revenue per month for the last 12 months (including current month)."""
    today = _local_today()
    month_cursor = today.replace(day=1)
    month_starts = []
    for _ in range(12):
        month_starts.append(month_cursor)
        if month_cursor.month == 1:
            month_cursor = month_cursor.replace(year=month_cursor.year - 1, month=12)
        else:
            month_cursor = month_cursor.replace(month=month_cursor.month - 1)
    month_starts.reverse()
    start_dt = _aware_start_of_day(month_starts[0])

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
            monthly_totals[month_start] = row["revenue"] or Decimal("0.00")

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
    }


def period_revenue_report(business, period):
    if period == "weekly":
        return weekly_revenue_report(business)
    if period == "monthly":
        return monthly_revenue_report(business)
    if period == "yearly":
        return yearly_revenue_report(business)
    return None
