# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the AgentCore Runtime health server.

Focus: the /ping HealthyBusy contract that keeps a long-running claude session
alive past the 15-minute idle timeout (see runtime-long-run.html). Importing
``main`` is side-effect-free because the OTel collector startup lives under the
``__main__`` entrypoint, not at module import.
"""


import main
from fastapi.testclient import TestClient


def _write_proc(tmp_path, pid, cmdline_bytes):
    """Create a fake /proc/<pid>/cmdline file with NUL-delimited argv."""
    d = tmp_path / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(cmdline_bytes)


# --- _claude_is_running ---


def test_detects_claude_bare(tmp_path):
    _write_proc(tmp_path, 100, b"claude\x00--continue\x00-p\x00prompt\x00")
    assert main._claude_is_running(str(tmp_path)) is True


def test_detects_claude_absolute_path(tmp_path):
    _write_proc(tmp_path, 101, b"/usr/local/bin/claude\x00--continue\x00")
    assert main._claude_is_running(str(tmp_path)) is True


def test_no_claude_returns_false(tmp_path):
    _write_proc(tmp_path, 1, b"/sbin/init\x00")
    _write_proc(tmp_path, 42, b"node\x00/mnt/plugins/gateway-iam-proxy/index.js\x00")
    assert main._claude_is_running(str(tmp_path)) is False


def test_substring_not_matched(tmp_path):
    # A process whose name merely contains "claude" must NOT count.
    _write_proc(tmp_path, 200, b"claude-code-helper\x00--flag\x00")
    _write_proc(tmp_path, 201, b"notclaude\x00")
    assert main._claude_is_running(str(tmp_path)) is False


def test_empty_cmdline_skipped(tmp_path):
    # Kernel threads have empty cmdline; must not crash or match.
    _write_proc(tmp_path, 2, b"")
    assert main._claude_is_running(str(tmp_path)) is False


def test_non_pid_entries_ignored(tmp_path):
    # /proc has non-numeric entries (cpuinfo, meminfo, ...); skip them.
    (tmp_path / "cpuinfo").write_text("...")
    (tmp_path / "self").mkdir()
    _write_proc(tmp_path, 300, b"claude\x00")
    assert main._claude_is_running(str(tmp_path)) is True


def test_missing_cmdline_is_benign(tmp_path):
    # PID dir with no cmdline (process exited mid-walk) must be skipped.
    (tmp_path / "400").mkdir()  # no cmdline file
    _write_proc(tmp_path, 401, b"claude\x00")
    assert main._claude_is_running(str(tmp_path)) is True


def test_missing_proc_root_returns_false(tmp_path):
    assert main._claude_is_running(str(tmp_path / "does-not-exist")) is False


# --- /ping payload contract ---


def test_ping_healthy_when_idle(monkeypatch):
    monkeypatch.setattr(main, "_claude_is_running", lambda *a, **k: False)
    client = TestClient(main.app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "Healthy"
    assert isinstance(body["time_of_last_update"], int)
    assert body["time_of_last_update"] > 0


def test_ping_healthybusy_when_claude_running(monkeypatch):
    monkeypatch.setattr(main, "_claude_is_running", lambda *a, **k: True)
    client = TestClient(main.app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    body = resp.json()
    # Exact casing matters — AgentCore matches "HealthyBusy", not "healthybusy".
    assert body["status"] == "HealthyBusy"
    assert "time_of_last_update" in body


def test_health_alias_matches_ping(monkeypatch):
    monkeypatch.setattr(main, "_claude_is_running", lambda *a, **k: True)
    client = TestClient(main.app)
    assert client.get("/health").json()["status"] == "HealthyBusy"


def test_time_of_last_update_is_current(monkeypatch):
    monkeypatch.setattr(main, "_claude_is_running", lambda *a, **k: False)
    before = int(__import__("time").time())
    client = TestClient(main.app)
    ts = client.get("/ping").json()["time_of_last_update"]
    after = int(__import__("time").time())
    assert before <= ts <= after
