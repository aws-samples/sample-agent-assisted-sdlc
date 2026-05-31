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
    resp = requests.post(
        url, data=body, headers=signed_headers, timeout=timeout + 30, stream=True
    )
    resp.raise_for_status()

    if not blocking:
        resp.close()
        return {"stdout": "", "stderr": "", "exitCode": 0, "status": "STARTED"}

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_code = -1

    buf = EventStreamBuffer()
    for chunk in resp.iter_content(chunk_size=4096):
        if not chunk:
            continue
        buf.add_data(chunk)
        for ev in buf:
            if not ev.payload:
                continue
            try:
                decoded = json.loads(ev.payload)
                inner = decoded.get("chunk") if isinstance(decoded, dict) else None
                if not isinstance(inner, dict):
                    continue
                if "contentDelta" in inner:
                    d = inner["contentDelta"]
                    if "stdout" in d:
                        stdout_parts.append(d["stdout"])
                    if "stderr" in d:
                        stderr_parts.append(d["stderr"])
                elif "contentStop" in inner:
                    exit_code = int(inner["contentStop"].get("exitCode", -1))
            except (json.JSONDecodeError, KeyError):
                continue

    return {
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
        "exitCode": exit_code,
    }
