from datetime import timedelta
from io import BytesIO

from django.template.loader import render_to_string
from django.utils import timezone
from xhtml2pdf import pisa


class PDFGenerationError(Exception):
    pass


PERIOD_PDF_META = {
    "weekly": {
        "period_label": "Weekly",
        "row_heading": "Day",
        "expenses_heading": "Expenses This Week",
    },
    "monthly": {
        "period_label": "Monthly",
        "row_heading": "Week",
        "expenses_heading": "Expenses This Month",
    },
    "yearly": {
        "period_label": "Yearly",
        "row_heading": "Month",
        "expenses_heading": "Expenses This Year",
    },
}


def _render_pdf(template_name, context, error_message):
    html = render_to_string(template_name, context)
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise PDFGenerationError(error_message)
    return buffer.getvalue()


def period_range_label(period, profit_report):
    today = timezone.localdate()
    if period == "weekly":
        start_day = today - timedelta(days=6)
        return f"{start_day.strftime('%d %b %Y')} – {today.strftime('%d %b %Y')}"
    if period == "monthly":
        start_day = today - timedelta(days=29)
        return f"{start_day.strftime('%d %b %Y')} – {today.strftime('%d %b %Y')}"
    if period == "yearly":
        if profit_report.get("awaiting_first_sale"):
            return "Awaiting first sale"
        start = profit_report.get("year_start_date")
        end = profit_report.get("year_end_date")
        if start and end:
            return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
        return "Business year not set"
    return today.strftime("%d %b %Y")


def build_daily_sales_pdf(context):
    return _render_pdf(
        "pdf/daily_sales.html",
        context,
        "Failed to generate daily sales PDF.",
    )


def build_period_summary_pdf(period, context):
    meta = PERIOD_PDF_META[period]
    profit_report = context["revenue_report"]
    full_context = {
        **context,
        **meta,
        "period": period,
        "report_title": profit_report.get("title", f"{meta['period_label']} Report"),
        "period_range": period_range_label(period, profit_report),
    }
    return _render_pdf(
        "pdf/period_summary.html",
        full_context,
        f"Failed to generate {period} report PDF.",
    )
