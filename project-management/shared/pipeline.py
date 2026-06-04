# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared pipeline utilities — execute_command via AgentCore InvokeAgentRuntimeCommand."""

import json
import os
import urllib.parse

import botocore.session
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.eventstream import EventStreamBuffer

try:
    from errors import RuntimeCommandError
    from log import get_logger
except ImportError:  # pragma: no cover - test path
    from shared.errors import RuntimeCommandError
    from shared.log import get_logger

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-west-2")
SERVICE = "bedrock-agentcore"


def _get_runtime_arn() -> str:
    return os.environ.get("AGENT_RUNTIME_ARN", "")


def sign_request(method: str, url: str, body: bytes, headers: dict) -> dict:
    session = botocore.session.get_session()
    creds = session.get_credentials().get_frozen_credentials()
    req = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(creds, SERVICE, REGION).add_auth(req)
    return dict(req.headers)


def execute_command(
    session_id: str, command: str, timeout: int = 600, blocking: bool = True
) -> dict:
    """Run a shell command in the AgentCore runtime session.

    If blocking=True (default), streams output until the command completes.
    If blocking=False, sends the command and returns immediately without waiting.
    The command continues executing in the runtime regardless.

    Raises:
        RuntimeCommandError: When the AgentCore HTTP transport raises a
            ``requests.RequestException`` (network error, non-2xx status).
            A non-zero command exit code is *not* raised — it is surfaced
            via the returned dict's ``exitCode`` key, preserving the
            existing contract for callers that branch on exit code.
    """
    runtime_arn = _get_runtime_arn()
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com"
        f"/runtimes/{encoded_arn}/commands?qualifier=DEFAULT"
    )

    body = json.dumps({"command": command, "timeout": timeout})
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/vnd.amazon.eventstream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        "Host": f"bedrock-agentcore.{REGION}.amazonaws.com",
    }

    signed_headers = sign_request("POST", url, body.encode(), headers)
    try:
        resp = requests.post(
            url, data=body, headers=signed_headers, timeout=timeout + 30, stream=True
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeCommandError("AgentCore execute_command HTTP failure") from e

    if not blocking:
        resp.close()
        return {"stdout": "", "stderr": "", "exitCode": 0, "status": "STARTED"}

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_code = -1

    buf = EventStreamBuffer()
    raw_events = []
    for chunk in resp.iter_content(chunk_size=4096):
        if not chunk:
            continue
        buf.add_data(chunk)
        for ev in buf:
            if not ev.payload:
                continue
            try:
                decoded = json.loads(ev.payload)
                raw_events.append(str(decoded)[:200])
                inner = decoded.get("chunk") if isinstance(decoded, dict) else None
                event = inner if isinstance(inner, dict) else decoded
                if "contentDelta" in event:
                    d = event["contentDelta"]
                    if "stdout" in d:
                        stdout_parts.append(d["stdout"])
                    if "stderr" in d:
                        stderr_parts.append(d["stderr"])
                elif "contentStop" in event:
                    exit_code = int(event["contentStop"].get("exitCode", -1))
            except (json.JSONDecodeError, KeyError):
                # Expected and benign: stream chunks may straddle event
                # frame boundaries or carry non-JSON keep-alive payloads.
                # Per the issue #23 swallow rule: log at DEBUG with a
                # structured field naming the cause, then continue.
                logger.debug(
                    "event_decode_failed",
                    extra={"raw_chunk_len": len(chunk)},
                )
                continue

    if not stdout_parts and not stderr_parts:
        logger.warning(
            "no_output_captured",
            extra={
                "raw_event_count": len(raw_events),
                "raw_events_head": raw_events[:3],
            },
        )

    return {
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
        "exitCode": exit_code,
    }


def stop_runtime_session(session_id: str) -> dict:
    """Stop the AgentCore runtime microVM for `session_id`.

    The session ID itself remains valid — a subsequent `execute_command` will
    spin up a fresh microVM. Persistent state on `/mnt/workplace/` (including
    `CLAUDE_CONFIG_DIR=/mnt/workplace/.claude-data`) survives the stop. State on
    the rootfs (`/tmp/`, `/home/`, in-flight processes) is lost.

    Used by the Setup Lambda before each pipeline run to refresh the session's
    `maxLifetime` budget. Best-effort: caller should wrap in try/except and
    continue on failure — the next `execute_command` succeeds regardless.

    Returns: `{"status": "STOPPED", "http_status": <int>}` on success.
    Raises: `requests.HTTPError` on non-2xx response (caller is expected to
    catch and continue — see Setup Lambda's handler).

    AWS API: `POST /runtimes/{agentRuntimeArn}/stopruntimesession`
    IAM action: `bedrock-agentcore:StopRuntimeSession`
    """
    runtime_arn = _get_runtime_arn()
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com"
        f"/runtimes/{encoded_arn}/stopruntimesession?qualifier=DEFAULT"
    )

    body = "{}"
    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        "Host": f"bedrock-agentcore.{REGION}.amazonaws.com",
    }

    signed_headers = sign_request("POST", url, body.encode(), headers)
    resp = requests.post(url, data=body, headers=signed_headers, timeout=30)
    resp.raise_for_status()

    return {"status": "STOPPED", "http_status": resp.status_code}
