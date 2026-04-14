from datetime import timedelta
from decimal import Decimal
from collections import defaultdict
from django.db.models import F, Sum
from django.utils import timezone
from .models import Sale


def ai_item_suggestions():
    base = (
        Sale.objects.values(name=F("item__name"))
        .annotate(total_qty=Sum("quantity"), revenue=Sum("total_amount"))
        .order_by("-total_qty")
    )
    top_selling = list(base[:3])
    least_selling = list(base.order_by("total_qty")[:3])

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    previous = {
        x["item__name"]: x["qty"]
        for x in Sale.objects.filter(sold_at__gte=fourteen_days_ago, sold_at__lt=seven_days_ago)
        .values("item__name")
        .annotate(qty=Sum("quantity"))
    }
    current = (
        Sale.objects.filter(sold_at__gte=seven_days_ago)
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


def sales_summary(period="daily"):
    now = timezone.now()
    start = now.date()
    if period == "weekly":
        start = (now - timedelta(days=7)).date()
    elif period == "monthly":
        start = (now - timedelta(days=30)).date()

    sales = Sale.objects.filter(sold_at__date__gte=start).select_related("item", "sold_by")
    total_revenue = sales.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    total_units = sales.aggregate(total=Sum("quantity"))["total"] or 0
    return sales, total_revenue, total_units


def ml_sales_analysis_table(period="daily"):
    """
    Lightweight ML-style analysis using linear trend + normalized ranking metrics.
    Returns per-item demand/risk/opportunity insights for the selected period.
    """
    now = timezone.now()
    start = now.date()
    window_days = 1
    if period == "weekly":
        start = (now - timedelta(days=7)).date()
        window_days = 7
    elif period == "monthly":
        start = (now - timedelta(days=30)).date()
        window_days = 30

    qs = Sale.objects.filter(sold_at__date__gte=start).values(
        "item__id", "item__name", "sold_at__date"
    ).annotate(
        qty=Sum("quantity"), revenue=Sum("total_amount")
    )

    if not qs:
        return []

    # Build day-index vectors per item for trend learning.
    daily_item_qty = defaultdict(lambda: defaultdict(float))
    item_name = {}
    item_revenue = defaultdict(float)
    for row in qs:
        item_id = row["item__id"]
        item_name[item_id] = row["item__name"]
        item_revenue[item_id] += float(row["revenue"] or 0)
        date_key = row["sold_at__date"]
        day_idx = (date_key - start).days
        daily_item_qty[item_id][day_idx] += float(row["qty"] or 0)

    rows = []
    totals = []
    slopes = []
    for item_id, by_day in daily_item_qty.items():
        y = [float(by_day.get(i, 0.0)) for i in range(window_days)]
        total_qty = float(sum(y))
        # Linear trend coefficient using pure-Python least squares.
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
