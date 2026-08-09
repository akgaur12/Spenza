"""Jinja2 rendering for Phase 11B's notification/report emails.

Separate environment from `src.shared.email.service` (OTP/welcome emails) —
different template directory, different callers (`EmailChannel` and
`notifications.jobs.report_jobs`) — but the same render-then-hand-to-a-
backend shape.
"""

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


def render_template(template_name: str, **context: object) -> str:
    template = _jinja_env.get_template(template_name)
    return template.render(current_year=datetime.now(UTC).year, **context)
