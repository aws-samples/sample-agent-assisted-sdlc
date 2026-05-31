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
    print(f"Starting OTel collector with config {COLLECTOR_CFG}", flush=True)
    return subprocess.Popen(
        [COLLECTOR_BIN, "--config", COLLECTOR_CFG],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


_wire_log_headers()
_collector_proc = _start_collector()
if _wait_for_collector():
    print("OTel collector ready on 127.0.0.1:4318", flush=True)
else:
    print("WARN: OTel collector did not bind 127.0.0.1:4318 within 10s", flush=True)
    if _collector_proc.poll() is not None:
        out = (
            _collector_proc.stdout.read().decode(errors="replace")
            if _collector_proc.stdout
            else ""
        )
        print(
            f"Collector exited {_collector_proc.returncode}:\n{out[:2000]}", flush=True
        )

app = FastAPI()


@app.get("/ping")
@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


@app.post("/invocations")
async def invocations():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    print("Agent health server starting on port 8080", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8080)
