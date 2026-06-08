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
import uuid

from assistants import STRATEGIES
from github_token import get_token
from pipeline import execute_command, stop_runtime_session

# Lambda flattens shared/ into the asset root, so the import is `log`.
# pytest sees the package layout, so the import is `shared.log`. Try the
# flat layout first (the production Lambda case).
try:
    from log import get_logger, redact
except ImportError:  # pragma: no cover - test path
    from shared.log import get_logger, redact

logger = get_logger(__name__)

ALLOWED_USERS = json.loads(os.environ.get("ALLOWED_USERS", "[]"))
ALLOWED_REPOS = json.loads(os.environ.get("ALLOWED_REPOS", "[]"))


def handler(event, context):
    """GitHub Setup Lambda — prepares workspace or refreshes for re-invocation."""
    logger.info("event_received", extra={"event": redact(event)})

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
        logger.warning(
            "unauthorized_user",
            extra={"triggered_by": triggered_by, "allowed_users": ALLOWED_USERS},
        )
        return {
            "statusCode": 403,
            "error": f"User '{triggered_by}' is not authorized to trigger the pipeline.",
        }

    repo_full = f"{repo_owner}/{repo_name}"
    if ALLOWED_REPOS and repo_full not in ALLOWED_REPOS:
        logger.warning(
            "unauthorized_repo",
            extra={"repo": repo_full, "allowed_repos": ALLOWED_REPOS},
        )
        return {
            "statusCode": 403,
            "error": f"Repository '{repo_full}' is not authorized.",
        }

    session_id = strategy.get_session_id(repo_owner, repo_name, issue_number)
    logger.info(
        "session_resolved",
        extra={
            "assistant": assistant_type,
            "session_id": session_id,
            "repo": repo_full,
        },
    )

    claude_session_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))

    # Detect re-invocation: check if invocation-1/ already exists in this session.
    # This runs FIRST because the claude-running probe only makes sense on re-invocations
    # (first invocations can't have Claude already running).
    check = execute_command(
        session_id,
        "sh -c 'test -d /mnt/workplace/gitproject/.dev-claude/invocation-1 && echo REINVOKE || echo FIRST'",
        timeout=10,
    )
    is_reinvocation = "REINVOKE" in check.get("stdout", "")
    logger.info(
        "invocation_mode_detected",
        extra={
            "mode": "RE-INVOCATION" if is_reinvocation else "FIRST INVOCATION",
            "session_id": session_id,
        },
    )

    # Check if Claude is already running BEFORE stopping the session.
    # Only on re-invocations — first invocations can't have a prior Claude process.
    claude_already_running = False
    if is_reinvocation:
        probe_cmd = (
            'sh -c \'for p in $(ls /proc/ 2>/dev/null | grep -E "^[0-9]+$"); do '
            "[ -r /proc/$p/cmdline ] || continue; "
            'cmd=$(tr "\\0" " " < /proc/$p/cmdline); '
            'case "$cmd" in '
            "claude\\ *|claude) echo RUNNING; exit 0 ;; "
            "esac; done; echo NOT_RUNNING'"
        )
        try:
            probe_result = execute_command(session_id, probe_cmd, timeout=10)
            probe_stdout = probe_result.get("stdout", "").strip()
            if probe_stdout == "RUNNING":
                claude_already_running = True
                logger.info(
                    "claude_already_running",
                    extra={
                        "session_id": session_id,
                        "claude_session_uuid": claude_session_uuid,
                    },
                )
        except Exception:
            logger.exception(
                "claude_running_check_failed", extra={"session_id": session_id}
            )

    # Only stop the session if Claude is NOT running. The stop refreshes the
    # maxLifetime budget (40 min) for the upcoming invocation. If Claude is
    # running, we skip entirely (no stop = don't kill the in-flight work).
    if not claude_already_running:
        try:
            stop_runtime_session(session_id)
            logger.info("session_stopped", extra={"session_id": session_id})
        except Exception:
            logger.exception(
                "stop_runtime_session_non_fatal",
                extra={"session_id": session_id},
            )

    # Write session record to DynamoDB (non-blocking: log and continue on failure)
    try:
        import sessions

        repo_url = event.get("repo_url", "")
        issue_url = f"{repo_url}/issues/{issue_number}" if repo_url else ""
        sessions.write_session_record(
            table_name=os.environ.get("SESSIONS_TABLE_NAME", ""),
            session_id=session_id,
            runtime_arn=strategy.runtime_arn,
            assistant_type=assistant_type,
            repo_owner=repo_owner,
            repo_name=repo_name,
            issue_number=issue_number,
            issue_title=event.get("issue_title", ""),
            triggered_by=triggered_by if triggered_by else "unknown",
            is_reinvocation=is_reinvocation,
            claude_session_uuid=claude_session_uuid,
            issue_url=issue_url,
            status="skipped_already_running" if claude_already_running else "started",
        )
        logger.info("session_record_written", extra={"session_id": session_id})
    except Exception:
        logger.exception("session_write_failed", extra={"session_id": session_id})

    # If Claude is already running, skip the invocation entirely
    if claude_already_running:
        return {
            "statusCode": 200,
            "session_id": session_id,
            "runtime_arn": strategy.runtime_arn,
            "assistant_type": assistant_type,
            "is_reinvocation": is_reinvocation,
            "skipped": True,
            "reason": "claude_already_running",
            "issue": {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "issue_number": issue_number,
                "issue_title": event.get("issue_title", ""),
            },
        }

    if is_reinvocation:
        # Re-invocation: fetch latest commits, refresh issue.json, rotate invocation dir.
        # Mint a fresh GitHub App installation token for private repos — never cache across
        # invocations (tokens expire in <=1 hour). For public repos, no token is needed.
        logger.info("refreshing_for_reinvocation", extra={"session_id": session_id})
        token = get_token() if is_private else None
        strategy.refresh_for_reinvocation(session_id, event, token=token)
    else:
        # First invocation: clone + full setup
        token = get_token() if is_private else None
        logger.info("clone_repo_start", extra={"private": is_private})
        result = strategy.clone_repo(
            session_id, repo_owner, repo_name, private=is_private, token=token
        )
        logger.info(
            "clone_repo_done",
            extra={"stdout_tail": result.get("stdout", "").strip()[-100:]},
        )

        logger.info("setup_workspace_start")
        result = strategy.setup_workspace(session_id, event)
        logger.info(
            "setup_workspace_done",
            extra={"stdout": result.get("stdout", "")},
        )

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
