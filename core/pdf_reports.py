from io import BytesIO

from django.template.loader import render_to_string
from xhtml2pdf import pisa


class PDFGenerationError(Exception):
    pass


def build_daily_sales_pdf(context):
    html = render_to_string("pdf/daily_sales.html", context)
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise PDFGenerationError("Failed to generate daily sales PDF.")
    return buffer.getvalue()
