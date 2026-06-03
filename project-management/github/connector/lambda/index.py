# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""GitHub Setup Lambda — connector-specific setup for the SDLC pipeline.

Handles first invocation (clone + setup) and re-invocation (refresh issue + continue).
Detects re-invocation by checking if .dev-claude/invocation-1/ exists in the session.

Environment variables:
  AGENT_RUNTIME_ARN: ARN of the coding assistant AgentCore runtime
  ASSISTANT_TYPE: Which assistant strategy to use (default: claude-code)
  PRIVATE_REPO: "true" if target repos are private (default: "false")
  GITHUB_APP_CLIENT_ID: GitHub App client ID (for private repos)
  GITHUB_INSTALLATION_ID: GitHub App installation ID (for private repos)
  PRIVATE_KEY_SECRET_ARN: Secrets Manager ARN for GitHub App private key (for private repos)
  AWS_REGION: AWS region (default: us-west-2)
"""

import json
import os

from assistants import STRATEGIES
from github_token import get_token
from pipeline import execute_command

ALLOWED_USERS = json.loads(os.environ.get("ALLOWED_USERS", "[]"))
ALLOWED_REPOS = json.loads(os.environ.get("ALLOWED_REPOS", "[]"))


def handler(event, context):
    """GitHub Setup Lambda — prepares workspace or refreshes for re-invocation."""
    safe_event = {
        k: v for k, v in event.items() if k not in ("token", "private_key", "secret")
    }
    print(f"[github-setup] Event: {json.dumps(safe_event)}")

    assistant_type = os.environ.get("ASSISTANT_TYPE", "claude-code")
    is_private = os.environ.get("PRIVATE_REPO", "false").lower() == "true"

    if assistant_type not in STRATEGIES:
        return {
            "statusCode": 400,
            "error": f"Unknown assistant type: {assistant_type}. Available: {list(STRATEGIES.keys())}",
        }

    strategy = STRATEGIES[assistant_type]()

    repo_owner = event.get("repo_owner", "")
    repo_name = event.get("repo_name", "")
    issue_number = event.get("issue_number", "")

    if not repo_owner or not repo_name or not issue_number:
        return {
            "statusCode": 400,
            "error": "Missing required fields: repo_owner, repo_name, issue_number",
        }

    triggered_by = event.get("triggered_by", "")
    if ALLOWED_USERS and ALLOWED_USERS != ["*"] and triggered_by not in ALLOWED_USERS:
        print(f"[github-setup] REJECTED: user '{triggered_by}' not in allowedUsers")
        return {
            "statusCode": 403,
            "error": f"User '{triggered_by}' is not authorized to trigger the pipeline.",
        }

    repo_full = f"{repo_owner}/{repo_name}"
    if ALLOWED_REPOS and repo_full not in ALLOWED_REPOS:
        print(f"[github-setup] REJECTED: repo '{repo_full}' not in allowedRepos")
        return {
            "statusCode": 403,
            "error": f"Repository '{repo_full}' is not authorized.",
        }

    session_id = strategy.get_session_id(repo_owner, repo_name, issue_number)
    print(
        f"[github-setup] assistant={assistant_type} session={session_id} repo={repo_full}"
    )

    # Detect re-invocation: check if invocation-1/ already exists in this session
    check = execute_command(
        session_id,
        "sh -c 'test -d /mnt/workplace/gitproject/.dev-claude/invocation-1 && echo REINVOKE || echo FIRST'",
        timeout=10,
    )
    # stdout may be empty due to API event format — fall back to FIRST
    is_reinvocation = "REINVOKE" in check.get("stdout", "")
    print(
        f"[github-setup] Mode: {'RE-INVOCATION' if is_reinvocation else 'FIRST INVOCATION'}"
    )

    if is_reinvocation:
        # Re-invocation: fetch latest commits, refresh issue.json, rotate invocation dir.
        # Mint a fresh GitHub App installation token for private repos — never cache across
        # invocations (tokens expire in ≤1 hour). For public repos, no token is needed.
        print("[github-setup] Refreshing issue.json and rotating invocation...")
        token = get_token() if is_private else None
        strategy.refresh_for_reinvocation(session_id, event, token=token)
    else:
        # First invocation: clone + full setup
        token = get_token() if is_private else None
        print(f"[github-setup] Cloning repo (private={is_private})...")
        result = strategy.clone_repo(
            session_id, repo_owner, repo_name, private=is_private, token=token
        )
        print(f"[github-setup] Clone: {result.get('stdout', '').strip()[-100:]}")

        print("[github-setup] Setting up workspace...")
        result = strategy.setup_workspace(session_id, event)
        print(f"[github-setup] Workspace: {result.get('stdout', '')}")

    return {
        "statusCode": 200,
        "session_id": session_id,
        "runtime_arn": strategy.runtime_arn,
        "assistant_type": assistant_type,
        "is_reinvocation": is_reinvocation,
        "issue": {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "issue_number": issue_number,
            "issue_title": event.get("issue_title", ""),
        },
    }
