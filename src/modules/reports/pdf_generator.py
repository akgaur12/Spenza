"""Renders a `ReportData` into PDF bytes via Jinja2 -> HTML -> WeasyPrint.

Kept deliberately dumb: it owns template loading and HTML -> PDF conversion
only. It has no knowledge of dashboards, analytics, or expenses — every
number it renders was already computed by `ReportBuilder`. Templates are
pure presentation (see `templates/base.html`); this class never branches on
report *data*, only on which template file matches the report *type*.
"""

from decimal import Decimal
from pathlib import Path
from typing import cast

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from src.modules.import_export.export_formatters import format_export_date
from src.modules.reports.schemas import ReportData, ReportType

MODULE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = MODULE_DIR / "templates"

_TEMPLATE_NAMES: dict[ReportType, str] = {
    ReportType.MONTHLY: "monthly.html",
    ReportType.QUARTERLY: "quarterly.html",
    ReportType.YEARLY: "yearly.html",
    ReportType.CUSTOM: "custom.html",
}

# Unlike `export_formatters.CURRENCY_FALLBACK` (ReportLab's built-in fonts
# can't render "₹" without shipping a Unicode TTF), WeasyPrint shapes text
# through Pango/Cairo with real system fonts, so the actual symbol renders
# correctly here.
_CURRENCY_SYMBOL = "₹"


def _money(value: Decimal) -> str:
    return f"{_CURRENCY_SYMBOL}{value:,.2f}"


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)
_env.filters["money"] = _money
_env.filters["fdate"] = format_export_date


class PDFGenerator:
    def generate(self, report_type: ReportType, data: ReportData) -> bytes:
        template = _env.get_template(_TEMPLATE_NAMES[report_type])
        html = template.render(report=data)
        # `base_url` anchors the templates' relative asset paths (e.g.
        # "assets/logo.svg") to the module directory rather than the
        # process's current working directory. WeasyPrint ships no type
        # stubs, so its return is `Any` to mypy — cast to the true type.
        return cast(bytes, HTML(string=html, base_url=str(MODULE_DIR)).write_pdf())
