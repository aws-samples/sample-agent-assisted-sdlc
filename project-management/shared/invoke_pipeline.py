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

import json

from assistants import STRATEGIES


def handler(event, context):
    """Pipeline Lambda — runs the full SDLC pipeline inside the runtime."""
    safe_event = {
        k: v for k, v in event.items() if k not in ("token", "private_key", "secret")
    }
    print(f"[sdlc-pipeline] Event: {json.dumps(safe_event)}")

    session_id = event["session_id"]
    assistant_type = event.get("assistant_type", "claude-code")
    issue = event["issue"]
    is_reinvocation = event.get("is_reinvocation", False)

    strategy = STRATEGIES[assistant_type]()

    mode = "RE-INVOCATION" if is_reinvocation else "FIRST"
    print(
        f"[sdlc-pipeline] Running pipeline ({mode}): session={session_id} assistant={assistant_type}"
    )
    print(f"[sdlc-pipeline] Issue #{issue['issue_number']}: {issue['issue_title']}")

    result = strategy.run_pipeline(session_id, issue, is_reinvocation=is_reinvocation)

    print(f"[sdlc-pipeline] Exit code: {result['exitCode']}")
    print(f"[sdlc-pipeline] Output (last 500 chars): {result['stdout'][-500:]}")

    return {
        "statusCode": 200,
        "session_id": session_id,
        "exit_code": result["exitCode"],
        "output_tail": result["stdout"][-2000:],
        "stderr_tail": result["stderr"][-500:] if result["stderr"] else "",
    }
