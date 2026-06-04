# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for shared/log.py — idempotency, JSON shape, level, redaction."""

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from log import SECRET_KEYS, get_logger, redact  # noqa: E402

_ISO_8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _reset_logger(name: str) -> None:
    """Detach handlers and clear the sentinel so tests can re-configure."""
    logger = logging.getLogger(name)
    logger.handlers = []
    if hasattr(logger, "_sdlc_log_configured"):
        delattr(logger, "_sdlc_log_configured")
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


class TestGetLogger:
    def test_get_logger_idempotent_same_name(self):
        _reset_logger("idempotent_test")
        first = get_logger("idempotent_test")
        second = get_logger("idempotent_test")
        assert first is second
        assert len(first.handlers) == 1

    def test_log_level_respects_env(self, monkeypatch):
        _reset_logger("level_test")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        logger = get_logger("level_test")
        assert logger.level == logging.WARNING

    def test_log_level_default_info(self, monkeypatch):
        _reset_logger("level_default_test")
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        logger = get_logger("level_default_test")
        assert logger.level == logging.INFO

    def test_propagate_disabled(self):
        _reset_logger("propagate_test")
        logger = get_logger("propagate_test")
        assert logger.propagate is False


class TestJsonFormatter:
    def test_json_formatter_shape(self, capsys):
        _reset_logger("shape_test")
        logger = get_logger("shape_test")
        logger.info("hello %s", "world", extra={"event": "boot", "request_id": "r1"})

        captured = capsys.readouterr().out.strip().splitlines()
        assert len(captured) == 1
        record = json.loads(captured[0])

        assert _ISO_8601_RE.match(record["timestamp"]), record["timestamp"]
        assert record["level"] == "INFO"
        assert record["logger"] == "shape_test"
        assert record["message"] == "hello world"
        assert record["event"] == "boot"
        assert record["request_id"] == "r1"

    def test_json_formatter_includes_exc_info(self, capsys):
        _reset_logger("exc_test")
        logger = get_logger("exc_test")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.exception("caught")

        captured = capsys.readouterr().out.strip().splitlines()
        record = json.loads(captured[0])
        assert record["level"] == "ERROR"
        assert "boom" in record["exc_info"]
        assert "Traceback" in record["exc_info"]


class TestRedact:
    def test_redact_case_insensitive_strips_secret_keys(self):
        payload = {
            "token": "x",
            "Token": "y",
            "TOKEN": "z",
            "Authorization": "a",
            "authorization": "b",
            "password": "c",
            "api_key": "d",
            "ok": "e",
        }
        result = redact(payload)
        assert result["ok"] == "e"
        for key in ("token", "Token", "TOKEN", "Authorization", "authorization", "password", "api_key"):
            assert result[key] == "***REDACTED***"

    def test_redact_preserves_non_secret_values(self):
        payload = {"repo": "myorg/myrepo", "issue_number": 42, "ok": True}
        result = redact(payload)
        assert result == payload
        assert result is not payload  # shallow copy

    def test_secret_keys_lowercase(self):
        # SECRET_KEYS is the source-of-truth; assert it's lowercased so
        # the redact() comparison invariant holds.
        for key in SECRET_KEYS:
            assert key == key.lower()
