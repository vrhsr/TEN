"""
shared/logging.py ─ Production-grade structured JSON logging for the Demographics Agent.

All logs are written as newline-delimited JSON to logs/{service_name}.log with automatic
10 MB / 5-backup rotation.  A plain-text stream goes to stdout for developer convenience.

PHI Policy
----------
Only these fields are allowed in log output:
  case_id, patient_id, task_id, charge_id, clinic_id, facility_id,
  correlation_id, node, event, handler_key, service,
  state_before, state_after, next_state, routing_decision, outcome_code,
  duration_ms, total_duration_ms, confidence_score,
  insurance_count, attempt_count, candidate_count, node_count,
  has_demographics, has_insurance, is_self_pay, duplicate_found,
  first_name_present, phone_present,          ← booleans only
  error, reason, tools_invoked, facts_considered
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from typing import Any

# ── Directory bootstrap ────────────────────────────────────────────────────────
LOGS_DIR = os.environ.get("LOG_DIR", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# ── PHI whitelist ─────────────────────────────────────────────────────────────
_ALLOWED_EXTRA: frozenset[str] = frozenset({
    "case_id", "patient_id", "task_id", "charge_id", "clinic_id", "facility_id",
    "correlation_id", "node", "event", "handler_key", "service",
    "state_before", "state_after", "next_state",
    "routing_decision", "outcome_code", "decision",
    "duration_ms", "total_duration_ms", "confidence_score",
    "insurance_count", "attempt_count", "candidate_count", "node_count",
    "has_demographics", "has_insurance", "is_self_pay", "duplicate_found",
    "first_name_present", "phone_present",
    "error", "reason", "tools_invoked", "facts_considered",
})


# ── Custom formatter ──────────────────────────────────────────────────────────
class StructuredFormatter(logging.Formatter):
    """Output every log record as a single JSON line."""

    _service: str = "app"

    def formatTime(self, record: logging.LogRecord, datefmt=None) -> str:  # noqa: N802
        t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
        return f"{t}.{int(record.msecs):03d}Z"

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _ALLOWED_EXTRA:
            val = getattr(record, key, None)
            if val is not None:
                data[key] = val
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


# ── Public configure function ─────────────────────────────────────────────────
def configure_logging(service_name: str = "app") -> None:
    """
    Call once at application startup (e.g. in FastAPI lifespan or main.py).
    Sets up rotating JSON file handler + plain console handler, then silences
    all noisy third-party loggers.
    """
    from shared.config import get_settings  # local import to avoid circular deps

    settings = get_settings()
    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)

    StructuredFormatter._service = service_name

    formatter = StructuredFormatter()
    log_file = os.path.join(LOGS_DIR, f"{service_name}.log")

    # JSON → file
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Plain text → console  (JSON in terminal is unreadable during development)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")
    )
    console_handler.setLevel(level)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []          # clear uvicorn's default handlers
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # ── Silence noisy libraries ───────────────────────────────────────────────
    _silence = {
        "sqlalchemy.engine": logging.WARNING,
        "sqlalchemy.pool":   logging.WARNING,
        "sqlalchemy.orm":    logging.WARNING,
        "httpx":             logging.WARNING,
        "httpcore":          logging.WARNING,
        "uvicorn.access":    logging.INFO,
    }
    for name, lvl in _silence.items():
        lg = logging.getLogger(name)
        lg.setLevel(lvl)
        lg.propagate = False    # don't bubble SQL/http noise to root


# ── WrappedLogger ─────────────────────────────────────────────────────────────
class WrappedLogger:
    """
    Thin wrapper that exposes a structlog-style keyword API while using
    standard logging under the hood.

    Usage:
        log = get_logger(__name__)
        log.info("node.init.start", case_id=1000, node="initialize")
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        # NOTE: Do NOT set propagate=False here.
        # Child loggers must propagate to the root logger so the
        # RotatingFileHandler (added in configure_logging) receives records.
        # Duplicate lines are prevented by root.handlers = [] in configure_logging.

    def _log(self, level: int, event: str, **kw: Any) -> None:
        # Strip any PHI that slipped through; only send whitelisted fields
        extra = {k: v for k, v in kw.items() if k in _ALLOWED_EXTRA}
        self._logger.log(level, event, extra=extra)

    def info(self, event: str, **kw: Any) -> None:
        self._log(logging.INFO, event, **kw)

    def warning(self, event: str, **kw: Any) -> None:
        self._log(logging.WARNING, event, **kw)

    def error(self, event: str, **kw: Any) -> None:
        self._log(logging.ERROR, event, **kw)

    def debug(self, event: str, **kw: Any) -> None:
        self._log(logging.DEBUG, event, **kw)

    def pretty(self, node: str, case_id: Any, summary: str, icon: str = "✅", **ctx: Any) -> None:
        """Legacy helper — maps to structured info for backward compatibility."""
        self.info(f"{icon} [{node}] — {summary}", case_id=case_id, node=node, **ctx)


def get_logger(name: str) -> WrappedLogger:
    return WrappedLogger(logging.getLogger(name))
