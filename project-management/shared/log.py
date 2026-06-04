# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Structured JSON logging utilities for the SDLC pipeline.

Provides a single ``get_logger`` factory that attaches one stdout
``StreamHandler`` per logger name (idempotent), a ``JsonFormatter`` that
emits a stable, whitelisted JSON shape, and a ``redact`` helper that
masks secret-bearing keys before they enter a log record.

Stdlib only. No project imports. The module is duplicated verbatim into
each runtime container directory whose Dockerfile uses a build context
scoped to that directory; the canonical copy lives here.
"""

from __future__ import annotations

import datetime as _datetime
import json
import logging
import os
import sys
from typing import Any, Mapping

# Keys whose values must never appear in a log record. Comparison is
# case-insensitive: callers should not have to worry about the exact
# casing used by the upstream payload.
SECRET_KEYS = frozenset(
    {"token", "private_key", "secret", "password", "api_key", "authorization"}
)

# Standard ``LogRecord`` attributes we deliberately do not surface as
# extras. Anything in ``record.__dict__`` outside this set (and the
# whitelist below) is treated as a caller-supplied extra and copied
# through verbatim.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "asctime",
        "taskName",
        "message",
    }
)

_HANDLER_SENTINEL = "_sdlc_log_configured"


def redact(d: Mapping[str, Any]) -> dict:
    """Return a shallow copy of ``d`` with secret-bearing keys masked.

    Comparison is case-insensitive against ``SECRET_KEYS``. Non-secret
    values pass through untouched (the copy is shallow on purpose — the
    caller is expected to have already coerced any nested AWS event
    shapes before logging).
    """
    out: dict = {}
    for key, value in d.items():
        if isinstance(key, str) and key.lower() in SECRET_KEYS:
            out[key] = "***REDACTED***"
        else:
            out[key] = value
    return out


class JsonFormatter(logging.Formatter):
    """Format log records as a single-line JSON object on stdout.

    Emits a fixed top-level shape::

        {"timestamp": "<ISO 8601 UTC, ms precision>",
         "level": "...",
         "logger": "...",
         "message": "...",
         <...caller-supplied extras...>,
         "exc_info": "<traceback>"}     # only when present

    ``LogRecord`` fields outside the whitelist are dropped. Caller
    extras (anything attached via ``logger.x("msg", extra={...})``)
    flow through with their original keys.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = _datetime.datetime.fromtimestamp(
            record.created, tz=_datetime.timezone.utc
        )
        # ISO 8601, millisecond precision, trailing 'Z'.
        timestamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"

        payload: dict = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for ``name``.

    Idempotent: subsequent calls with the same ``name`` return the same
    underlying ``Logger`` object and do not attach additional handlers.
    The logger gets a single ``StreamHandler(sys.stdout)`` with
    ``JsonFormatter``; its level is read from ``LOG_LEVEL`` (default
    ``INFO``); ``propagate`` is disabled so the root logger is left
    untouched.
    """
    logger = logging.getLogger(name)
    if getattr(logger, _HANDLER_SENTINEL, False):
        return logger

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    setattr(logger, _HANDLER_SENTINEL, True)
    return logger
