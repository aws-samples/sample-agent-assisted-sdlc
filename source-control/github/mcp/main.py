# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""AgentCore entrypoint for GitHub MCP Server (source-control).

Generates a GitHub App installation token from Secrets Manager, then exec's
the Go github-mcp-server binary directly on port 8000.

Previous versions ran a Python HTTP reverse proxy between port 8000 and the
Go binary on 8082, but that proxy could not stream SSE responses — it called
resp.read() which closed the connection immediately, killing every MCP session
within milliseconds. The fix is to remove the proxy entirely and let the Go
binary handle Streamable HTTP MCP natively.
"""

import json
import os
import time
import urllib.error
import urllib.request

import boto3
import jwt
from log import get_logger

logger = get_logger(__name__)


def get_github_token():
    """Generate a GitHub App installation token from the private key in Secrets Manager."""
    region = os.environ.get("AWS_REGION", "us-west-2")
    client_id = os.environ["GITHUB_APP_CLIENT_ID"]
    installation_id = os.environ["GITHUB_INSTALLATION_ID"]
    secret_arn = os.environ["PRIVATE_KEY_SECRET_ARN"]

    sm = boto3.client("secretsmanager", region_name=region)
    secret = sm.get_secret_value(SecretId=secret_arn)
    private_key = secret["SecretString"].encode()

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": client_id}
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        return data["token"]


def _required_toolsets() -> str:
    """Read and validate GITHUB_TOOLSETS. Raise RuntimeError on unset/empty."""
    toolsets = os.environ.get("GITHUB_TOOLSETS", "")
    if not toolsets:
        raise RuntimeError(
            "GITHUB_TOOLSETS env var is unset or empty. "
            "Expected to be set by SourceControlStack "
            "(lib/nested/source-control-stack.ts), e.g. 'repos,pull_requests,context'."
        )
    return toolsets


if __name__ == "__main__":
    toolsets = _required_toolsets()
    token = get_github_token()
    logger.info("token_generated_starting_go_server")

    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
    os.execv(
        "/usr/local/bin/github-mcp-server",
        [
            "github-mcp-server",
            "http",
            "--port",
            "8000",
            "--toolsets",
            toolsets,
        ],
    )
