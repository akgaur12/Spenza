"""FastAPI application factory and process entry points."""

import logging
import subprocess
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from slowapi.middleware import SlowAPIMiddleware

from src.core.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

from src.core.app_config import settings  # noqa: E402
from src.core.exception_handlers import register_exception_handlers  # noqa: E402
from src.core.middleware import RequestIDMiddleware, SecurityHeadersMiddleware  # noqa: E402
from src.core.rate_limit import limiter  # noqa: E402
from src.lifespan import lifespan  # noqa: E402
from src.modules.analytics.router import analytics_router  # noqa: E402
from src.modules.categories.admin_router import admin_category_router  # noqa: E402
from src.modules.categories.router import category_router  # noqa: E402
from src.modules.dashboard.router import dashboard_router  # noqa: E402
from src.modules.expenses.router import expense_router  # noqa: E402
from src.modules.health.router import health_router  # noqa: E402
from src.modules.import_export.router import export_router, import_router  # noqa: E402
from src.modules.recurring_expenses.router import recurring_expense_router  # noqa: E402
from src.modules.reports.router import reports_router  # noqa: E402
from src.modules.users.admin_router import admin_router  # noqa: E402
from src.modules.users.user_router import user_router  # noqa: E402

API_DESCRIPTION = """
Production-ready Expense Tracker REST API.

Authentication uses a dual-token scheme delivered via HttpOnly cookies:
an **access token** (15 min JWT) and a **refresh token** (30 day, rotated on every
use, hashed at rest). Sessions stay valid indefinitely until logout, revocation,
or password change — mirroring the "stay signed in" behavior of ChatGPT/Claude.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.state.limiter = limiter

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # `Content-Disposition` isn't in the browser's CORS-safelisted
        # response headers, so without this a cross-origin frontend can
        # never read it via `response.headers.get(...)` — needed for the
        # export endpoints' filenames — no matter what `Origin` is sent.
        expose_headers=["Content-Disposition"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SlowAPIMiddleware)

    register_exception_handlers(app)

    app.include_router(user_router)
    app.include_router(admin_router)
    app.include_router(category_router)
    app.include_router(admin_category_router)
    app.include_router(expense_router)
    app.include_router(recurring_expense_router)
    app.include_router(dashboard_router)
    app.include_router(analytics_router)
    app.include_router(import_router)
    app.include_router(export_router)
    app.include_router(reports_router)
    app.include_router(health_router)

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()


def main_prod() -> None:
    cmd = [
        "gunicorn",
        "-w",
        str(settings.WORKERS),
        "-k",
        "uvicorn.workers.UvicornWorker",
        "--timeout",
        str(settings.TIMEOUT),
        "--graceful-timeout",
        str(settings.GRACEFUL_TIMEOUT),
        "-b",
        f"{settings.HOST}:{settings.PORT}",
        "src.app:app",
    ]
    subprocess.run(cmd, check=True)  # noqa: S603 — fixed args from trusted settings, not user input


def main_dev() -> None:
    cmd = [
        "uvicorn",
        "src.app:app",
        "--host",
        settings.HOST,
        "--port",
        str(settings.PORT),
        "--reload",
        "--log-level",
        settings.LOG_LEVEL,
    ]
    subprocess.run(cmd, check=True)  # noqa: S603 — fixed args from trusted settings, not user input


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        logger.info("Starting in development mode")
        main_dev()
    else:
        logger.info("Starting in production mode")
        main_prod()


if __name__ == "__main__":
    main()
