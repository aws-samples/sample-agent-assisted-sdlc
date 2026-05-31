# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""AgentCore entrypoint for GitHub MCP Server.

Runs the Go GitHub MCP server in HTTP mode on port 8082, with a reverse proxy
on port 8000 (AgentCore service contract) that injects the GitHub token into
every request.

Token is generated directly from the GitHub App private key (stored in Secrets Manager)
— no external Lambda needed.
"""

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import jwt

GITHUB_TOKEN = None
GO_SERVER_URL = "http://127.0.0.1:8082/mcp"


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


class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        req = urllib.request.Request(GO_SERVER_URL, data=body)
        req.add_header(
            "Content-Type", self.headers.get("Content-Type", "application/json")
        )
        req.add_header(
            "Accept", self.headers.get("Accept", "application/json, text/event-stream")
        )
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")

        session_id = self.headers.get("mcp-session-id")
        if session_id:
            req.add_header("mcp-session-id", session_id)

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())

    def do_GET(self):
        req = urllib.request.Request(f"{GO_SERVER_URL}{self.path}")
        req.add_header("Accept", "text/event-stream")
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")

        session_id = self.headers.get("mcp-session-id")
        if session_id:
            req.add_header("mcp-session-id", session_id)

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())

    def do_DELETE(self):
        req = urllib.request.Request(GO_SERVER_URL, method="DELETE")
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")

        session_id = self.headers.get("mcp-session-id")
        if session_id:
            req.add_header("mcp-session-id", session_id)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())

    def log_message(self, format, *args):
        pass


def start_go_server():
    toolsets = os.environ.get(
        "GITHUB_TOOLSETS", "repos,issues,pull_requests,context,users"
    )
    env = {**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": GITHUB_TOKEN}
    subprocess.run(
        [
            "/usr/local/bin/github-mcp-server",
            "http",
            "--port",
            "8082",
            "--toolsets",
            toolsets,
        ],
        env=env,
    )


if __name__ == "__main__":
    GITHUB_TOKEN = get_github_token()
    print("[githubmcp] Token generated from GitHub App, starting Go server...")

    go_thread = threading.Thread(target=start_go_server, daemon=True)
    go_thread.start()

    time.sleep(2)

    print("[githubmcp] Proxy listening on :8000")
    server = HTTPServer(("0.0.0.0", 8000), ProxyHandler)
    server.serve_forever()
