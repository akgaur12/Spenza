"""Application logging: structlog + stdlib `logging`, wired for both
interactive development and production.

`logging.yaml` declares every handler/formatter/filter that could exist;
`_load_dict_config()` decides *which* of them are active for the current
`APP_ENV`, then hands the result to `dictConfig`. Two concerns drove this
design over a naive single-mode setup:

1. Non-blocking I/O. A handler that talks to the network or disk (SMTP
   alerts, file writes) must never run on the thread handling an async
   request — the root logger has exactly one handler, a `QueueHandler`;
   the real handlers run on a background `QueueListener` thread instead
   (stdlib's documented pattern for this; Python 3.12+ lets `dictConfig`
   build the listener declaratively — see `setup_logging()`).
2. Environment-appropriate handlers. Local rotating files are useful on a
   dev machine and pointless inside a container (an ephemeral filesystem
   nobody tails) — development gets a colored console plus two rotating
   files (`app.log` everything, `error.log` errors-only); production gets
   only a console stream by default, since there's nowhere durable to put
   a file — override with `settings.LOG_TO_FILE` if that's not true for
   your deployment (see `_file_logging_enabled()`). Every destination
   renders the same plain `LOG_FORMAT` line shape; only the development
   console adds color.

Never log passwords, OTPs, or raw tokens — only hashes, IDs, or booleans.
"""

import atexit
import logging
import logging.config
import logging.handlers
import os
from pathlib import Path
from typing import Any

import structlog
import yaml

from src.core.app_config import ROOT_DIR, settings

LOGGING_CONFIG_PATH = ROOT_DIR / "src" / "config" / "logging.yaml"


class PassthroughQueueHandler(logging.handlers.QueueHandler):
    """A `QueueHandler` that skips the default eager `record.msg`
    stringification `prepare()` does for pickling safety across process
    boundaries.

    This queue never leaves the process — it only decouples the thread
    emitting a log call from the background thread that does the real I/O
    — so that safety net isn't needed, and it actively breaks
    `structlog.stdlib.ProcessorFormatter`: that formatter expects
    `record.msg` to still be the original event dict when the listener
    thread renders it, not a pre-stringified `str(dict)`.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record


class ExactLevelFilter(logging.Filter):
    """Only lets records at exactly `level` through.

    Used solely to isolate CRITICAL for the email alert handler, so a plain
    ERROR doesn't also page someone.
    """

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_ANSI_RESET = "\x1b[0m"
_ANSI_DIM = "\x1b[2m"
_ANSI_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\x1b[36m",  # cyan
    logging.INFO: "\x1b[32m",  # green
    logging.WARNING: "\x1b[33m",  # yellow
    logging.ERROR: "\x1b[31m",  # red
    logging.CRITICAL: "\x1b[1;41m",  # bold, white-on-red
}

# `%(asctime)s` is dimmed unconditionally (a static wrap baked into the
# format string); `%(levelname)s` is colored per severity at render time —
# see `_ColoredLevelProcessorFormatter`, since that depends on each record's
# actual level and can't be expressed as a static fmt string.
CONSOLE_LOG_FORMAT = f"{_ANSI_DIM}%(asctime)s{_ANSI_RESET} [%(levelname)s] %(name)s: %(message)s"


class _ColoredLevelProcessorFormatter(structlog.stdlib.ProcessorFormatter):
    """Colors `%(levelname)s` by severity (DEBUG=cyan, INFO=green, ...).

    structlog's `ConsoleRenderer` only colors the `%(message)s` portion it
    renders; the stdlib prefix (`%(asctime)s [%(levelname)s] %(name)s:`) is
    plain `logging.Formatter` substitution, so this fills that gap. Console
    only — a rotating file handler has no terminal to render ANSI codes.
    """

    def format(self, record: logging.LogRecord) -> str:
        color = _ANSI_LEVEL_COLORS.get(record.levelno, "")
        original_levelname = record.levelname
        if color:
            record.levelname = f"{color}{record.levelname}{_ANSI_RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def _shared_processors() -> list[Any]:
    """Processors applied to every record — ours and third-party (uvicorn,
    etc.) alike — before a final renderer turns it into a message.

    Deliberately excludes level/timestamp processors — `LOG_FORMAT` above
    already supplies both (`%(levelname)s`, `%(asctime)s`) straight from the
    stdlib `LogRecord`, so adding them here would just duplicate them inside
    the rendered `%(message)s` body.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def build_console_formatter() -> structlog.stdlib.ProcessorFormatter:
    """Factory referenced from `logging.yaml`'s `formatters.console_structlog`.

    Colored, human-friendly, `LOG_FORMAT`-shaped — development only.
    """
    return _ColoredLevelProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        fmt=CONSOLE_LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )


def build_plain_formatter() -> structlog.stdlib.ProcessorFormatter:
    """Factory referenced from `logging.yaml`'s `formatters.file_structlog`.

    Plain, uncolored, `LOG_FORMAT`-shaped — used by development's rotating
    files (no terminal to render ANSI codes) and by production's console
    (no color, since a bare-text stream is what was asked for there too).
    """
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        fmt=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )


def _file_logging_enabled() -> bool:
    """Whether the rotating file handlers (`app_file`, `error_file`) should
    be active. `settings.LOG_TO_FILE` overrides the per-environment default
    (files on in dev/test, off in prod) when explicitly set either way.
    """
    if settings.LOG_TO_FILE is not None:
        return settings.LOG_TO_FILE
    return not settings.is_production


def _load_dict_config(config_path: Path) -> dict[str, Any]:
    """Parse `logging.yaml` and decide, for the current environment, which
    declared handlers are actually wired up — then fill in the queue
    handler's `handlers` list with exactly those.
    """
    with config_path.open(encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)

    handlers = config["handlers"]

    if settings.is_production:
        active = ["console_prod"]
        handlers.pop("console_dev", None)
    else:
        active = ["console_dev"]
        handlers.pop("console_prod", None)

    if _file_logging_enabled():
        os.makedirs("logs", exist_ok=True)
        active += ["app_file", "error_file"]
    else:
        handlers.pop("app_file", None)
        handlers.pop("error_file", None)

    email_configured = bool(settings.SENDER_EMAIL and settings.SENDER_PASSWORD)
    if email_configured:
        handlers["email"]["credentials"] = [settings.SENDER_EMAIL, settings.SENDER_PASSWORD]
        handlers["email"]["fromaddr"] = settings.SENDER_EMAIL
        handlers["email"]["toaddrs"] = [settings.SENDER_EMAIL]
        handlers["email"]["mailhost"] = [settings.SMTP_SERVER, settings.SMTP_PORT]
        active.append("email")
    else:
        handlers.pop("email", None)

    handlers["queue_handler"]["handlers"] = active
    return config


def setup_logging() -> None:
    """Configure structlog + stdlib logging for the current environment.

    Every handler is fronted by a single `QueueHandler` on the root logger;
    the real handlers (console, files, SMTP) run on a background
    `QueueListener` thread — `dictConfig` builds that listener (Python
    3.12+) but does not start it, so that happens here, with `atexit`
    registered to flush and stop it on shutdown.
    """
    config = _load_dict_config(LOGGING_CONFIG_PATH)
    root_level = getattr(logging, config.get("root", {}).get("level", "INFO"))

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(root_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.config.dictConfig(config)

    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.QueueHandler) and handler.listener:
            handler.listener.start()
            atexit.register(handler.listener.stop)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to request-scoped context vars."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
