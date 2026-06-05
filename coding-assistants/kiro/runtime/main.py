# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""AgentCore Runtime health server for Kiro.

Reports HealthyBusy while the kiro-cli process is running so AgentCore does NOT
reap the session at the 15-minute idle timeout mid-run.

DUPLICATE OF coding-assistants/claude-code/runtime/main.py /ping logic — keep in sync.
"""

import os
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from log import get_logger

_KIRO_PROC_NAMES = ("kiro-cli", "kiro")

logger = get_logger(__name__)

app = FastAPI()


def _kiro_is_running(proc_root: str = "/proc") -> bool:
    """True if a ``kiro-cli`` or ``kiro`` process is alive in this microVM.

    Walks ``proc_root`` and matches the executable name (argv[0] basename).
    Skips PIDs that exit mid-walk rather than failing.
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
            continue
        if not raw:
            continue
        argv0 = raw.split(b"\x00", 1)[0].decode(errors="replace")
        exe = argv0.rsplit("/", 1)[-1]
        if exe in _KIRO_PROC_NAMES:
            return True
    return False


@app.get("/ping")
@app.get("/health")
async def health():
    """AgentCore Runtime health endpoint.

    Contract: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html
    """
    status = "HealthyBusy" if _kiro_is_running() else "Healthy"
    return JSONResponse({"status": status, "time_of_last_update": int(time.time())})


@app.post("/invocations")
async def invocations():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    logger.info("health_server_starting", extra={"port": 8080})
    uvicorn.run(app, host="0.0.0.0", port=8080)
