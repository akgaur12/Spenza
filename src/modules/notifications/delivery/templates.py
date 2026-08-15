"""Jinja2 rendering for Phase 11B's notification/report emails.

Separate environment from `src.shared.email.service` (OTP/welcome emails) —
different template directory, different callers (`EmailChannel` and
`notifications.jobs.report_jobs`) — but the same render-then-hand-to-a-
backend shape.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)

_BLANK_LINE_RE = re.compile(r"\n\s*\n")


def render_template(template_name: str, **context: object) -> str:
    template = _jinja_env.get_template(template_name)
    return template.render(current_year=datetime.now(UTC).year, **context)


def format_message_html(message: str) -> Markup:
    """Render a plain-text message as HTML paragraphs, so blank-line breaks
    become separate `<p>` blocks and single newlines become `<br>` — lets
    admin-composed emails (and any other free-text message) use ordinary
    paragraph formatting instead of collapsing to one run-on line.
    """
    paragraphs = [p for p in _BLANK_LINE_RE.split(message.strip()) if p.strip()]
    return Markup("").join(
        Markup("<p>{}</p>").format(
            Markup("<br>").join(escape(line) for line in paragraph.splitlines())
        )
        for paragraph in paragraphs
    )
