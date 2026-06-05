# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Amazon Bedrock AgentCore Runtime health server for Claude Code.
Spawns the OTel collector sidecar so Node.js OTel telemetry from Claude
Code reaches AgentCore Observability via SigV4-signed OTLP.
"""

import os
import socket
import subprocess
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from log import get_logger

# Process-name prefixes that mean "claude is actively working in this microVM".
# The coding-assistant pipeline launches `claude --continue` as a DETACHED
# background process via a separate `execute_command` call (see
# project-management/shared/assistants/claude.py), so this health server cannot
# observe it in-process. We inspect /proc instead — the claude process shares
# this microVM's PID namespace with the health server.
_CLAUDE_PROC_NAMES = ("claude",)

logger = get_logger(__name__)

COLLECTOR_BIN = "/usr/bin/otelcol-contrib"
COLLECTOR_CFG = "/app/otel-collector-config.yaml"


def _wire_log_headers() -> None:
    """Parse OTEL_EXPORTER_OTLP_LOGS_HEADERS (AgentCore-injected, comma-
    separated key=value pairs) and re-export the two values the collector
    config references via ${env:AWS_OTEL_LOG_GROUP} / ${env:AWS_OTEL_LOG_STREAM}.
    """
    raw = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "")
    for kv in raw.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        if k.strip() == "x-aws-log-group":
            os.environ["AWS_OTEL_LOG_GROUP"] = v.strip()
        elif k.strip() == "x-aws-log-stream":
            os.environ["AWS_OTEL_LOG_STREAM"] = v.strip()


def _wait_for_collector(
    host: str = "127.0.0.1", port: int = 4318, timeout: float = 10.0
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _start_collector() -> subprocess.Popen:
    logger.info("otel_collector_starting", extra={"config": COLLECTOR_CFG})
    return subprocess.Popen(
        [COLLECTOR_BIN, "--config", COLLECTOR_CFG],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _bootstrap_collector() -> None:
    """Wire log headers and start the OTel collector sidecar.

    Invoked from the ``__main__`` entrypoint only (the container runs
    ``python -m main``). Keeping it out of module import means the module can
    be imported in unit tests without spawning the collector subprocess.
    """
    _wire_log_headers()
    collector_proc = _start_collector()
    if _wait_for_collector():
        logger.info("otel_collector_ready", extra={"endpoint": "127.0.0.1:4318"})
    else:
        logger.warning(
            "otel_collector_bind_timeout",
            extra={"endpoint": "127.0.0.1:4318", "timeout_s": 10},
        )
        if collector_proc.poll() is not None:
            out = (
                collector_proc.stdout.read().decode(errors="replace")
                if collector_proc.stdout
                else ""
            )
            logger.error(
                "otel_collector_exited",
                extra={
                    "returncode": collector_proc.returncode,
                    "output_head": out[:2000],
                },
            )


app = FastAPI()


def _claude_is_running(proc_root: str = "/proc") -> bool:
    """True if a ``claude`` process is alive in this microVM.

    Walks ``proc_root`` and matches the executable name (argv[0] of each
    process's cmdline, allowing an absolute path like ``/usr/local/bin/claude``).
    Substring matches such as ``claude-code-foo`` are intentionally NOT counted.
    Skips PIDs that exit mid-walk (the listdir/open race) rather than failing.

    ``proc_root`` is injectable only so the walk can be unit-tested against a
    fake proc tree; production always uses ``/proc``.
    """
    try:
        pids = os.listdir(proc_root)
    except OSError:
        return False
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, pid, "cmdline"), "rb") as f:
                raw = f.read()
        except OSError:
            continue  # process exited between listdir and open — benign race
        if not raw:
            continue
        # cmdline is NUL-delimited; argv[0] is the executable.
        argv0 = raw.split(b"\x00", 1)[0].decode(errors="replace")
        exe = argv0.rsplit("/", 1)[-1]  # strip any leading path
        if exe in _CLAUDE_PROC_NAMES:
            return True
    return False


@app.get("/ping")
@app.get("/health")
async def health():
    """AgentCore Runtime health endpoint.

    Reports ``HealthyBusy`` while a claude process is running so AgentCore does
    NOT reap the session at the 15-minute idle timeout mid-run, and ``Healthy``
    when idle so the session still idles out normally once work completes. The
    ``time_of_last_update`` field is REQUIRED — without it AgentCore fires the
    idle timeout even when the status is ``HealthyBusy``.

    Contract: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html
    """
    status = "HealthyBusy" if _claude_is_running() else "Healthy"
    return JSONResponse({"status": status, "time_of_last_update": int(time.time())})


@app.post("/invocations")
async def invocations():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    _bootstrap_collector()
    logger.info("health_server_starting", extra={"port": 8080})
    uvicorn.run(app, host="0.0.0.0", port=8080)
