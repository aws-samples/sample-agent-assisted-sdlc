# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Step Functions invoke step — runs the coding assistant pipeline.

Called by Step Functions after the setup Lambda completes.
This Lambda runs the actual SDLC pipeline (can take up to 40 min).
Designed to be invoked asynchronously by Step Functions with a long timeout.

Input (from setup Lambda output):
  session_id: AgentCore runtime session ID
  assistant_type: Which strategy to use
  issue: {repo_owner, repo_name, issue_number, issue_title}
"""

from assistants import STRATEGIES

try:
    from log import get_logger, redact
except ImportError:  # pragma: no cover - test path
    from shared.log import get_logger, redact

logger = get_logger(__name__)


def handler(event, context):
    """Pipeline Lambda — runs the full SDLC pipeline inside the runtime."""
    logger.info("event_received", extra={"event": redact(event)})

    # Skip if Setup Lambda determined Claude is already running
    if event.get("skipped"):
        logger.info(
            "pipeline_skipped",
            extra={
                "reason": event.get("reason", "unknown"),
                "session_id": event.get("session_id"),
            },
        )
        return {
            "statusCode": 200,
            "session_id": event.get("session_id", ""),
            "skipped": True,
            "reason": event.get("reason", "unknown"),
        }

    session_id = event["session_id"]
    assistant_type = event.get("assistant_type", "claude-code")
    issue = event["issue"]
    is_reinvocation = event.get("is_reinvocation", False)

    strategy = STRATEGIES[assistant_type]()

    mode = "RE-INVOCATION" if is_reinvocation else "FIRST"
    logger.info(
        "pipeline_start",
        extra={
            "mode": mode,
            "session_id": session_id,
            "assistant": assistant_type,
            "issue_number": issue["issue_number"],
            "issue_title": issue["issue_title"],
        },
    )

    result = strategy.run_pipeline(session_id, issue, is_reinvocation=is_reinvocation)

    logger.info(
        "pipeline_complete",
        extra={
            "exit_code": result["exitCode"],
            "stdout_tail": result["stdout"][-500:],
        },
    )

    return {
        "statusCode": 200,
        "session_id": session_id,
        "exit_code": result["exitCode"],
        "output_tail": result["stdout"][-2000:],
        "stderr_tail": result["stderr"][-500:] if result["stderr"] else "",
    }
