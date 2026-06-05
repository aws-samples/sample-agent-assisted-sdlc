# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Kiro AgentCore Runtime health server.

DUPLICATE OF coding-assistants/claude-code/runtime/test_main.py structure — keep in sync.
"""

import main
from fastapi.testclient import TestClient


def _write_proc(tmp_path, pid, cmdline_bytes):
    """Create a fake /proc/<pid>/cmdline file with NUL-delimited argv."""
    d = tmp_path / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(cmdline_bytes)


# --- _kiro_is_running ---


def test_detects_kiro_cli_bare(tmp_path):
    _write_proc(tmp_path, 100, b"kiro-cli\x00chat\x00--no-interactive\x00")
    assert main._kiro_is_running(str(tmp_path)) is True


def test_detects_kiro_bare(tmp_path):
    _write_proc(tmp_path, 100, b"kiro\x00chat\x00")
    assert main._kiro_is_running(str(tmp_path)) is True


def test_detects_kiro_absolute_path(tmp_path):
    _write_proc(tmp_path, 101, b"/usr/local/bin/kiro-cli\x00chat\x00")
    assert main._kiro_is_running(str(tmp_path)) is True


def test_no_kiro_returns_false(tmp_path):
    _write_proc(tmp_path, 1, b"/sbin/init\x00")
    _write_proc(tmp_path, 42, b"node\x00/mnt/plugins/gateway-iam-proxy/index.js\x00")
    assert main._kiro_is_running(str(tmp_path)) is False


def test_substring_not_matched(tmp_path):
    _write_proc(tmp_path, 200, b"kiro-cli-helper\x00--flag\x00")
    _write_proc(tmp_path, 201, b"notkiro\x00")
    assert main._kiro_is_running(str(tmp_path)) is False


def test_empty_cmdline_skipped(tmp_path):
    _write_proc(tmp_path, 2, b"")
    assert main._kiro_is_running(str(tmp_path)) is False


def test_non_pid_entries_ignored(tmp_path):
    (tmp_path / "cpuinfo").write_text("...")
    (tmp_path / "self").mkdir()
    _write_proc(tmp_path, 300, b"kiro-cli\x00")
    assert main._kiro_is_running(str(tmp_path)) is True


def test_missing_cmdline_is_benign(tmp_path):
    (tmp_path / "400").mkdir()
    _write_proc(tmp_path, 401, b"kiro-cli\x00")
    assert main._kiro_is_running(str(tmp_path)) is True


def test_missing_proc_root_returns_false(tmp_path):
    assert main._kiro_is_running(str(tmp_path / "does-not-exist")) is False


# --- /ping payload contract ---


def test_ping_healthy_when_idle(monkeypatch):
    monkeypatch.setattr(main, "_kiro_is_running", lambda *a, **k: False)
    client = TestClient(main.app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "Healthy"
    assert isinstance(body["time_of_last_update"], int)
    assert body["time_of_last_update"] > 0


def test_ping_healthybusy_when_kiro_running(monkeypatch):
    monkeypatch.setattr(main, "_kiro_is_running", lambda *a, **k: True)
    client = TestClient(main.app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "HealthyBusy"
    assert "time_of_last_update" in body


def test_health_alias_matches_ping(monkeypatch):
    monkeypatch.setattr(main, "_kiro_is_running", lambda *a, **k: True)
    client = TestClient(main.app)
    assert client.get("/health").json()["status"] == "HealthyBusy"


def test_time_of_last_update_is_current(monkeypatch):
    monkeypatch.setattr(main, "_kiro_is_running", lambda *a, **k: False)
    before = int(__import__("time").time())
    client = TestClient(main.app)
    ts = client.get("/ping").json()["time_of_last_update"]
    after = int(__import__("time").time())
    assert before <= ts <= after
