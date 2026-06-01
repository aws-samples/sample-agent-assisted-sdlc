# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Claude Code assistant strategy."""

import base64

from pipeline import execute_command

from assistants.base import AssistantStrategy, _validate_identifier


def _otel_attrs_prefix(session_id: str) -> str:
    return (
        "export OTEL_RESOURCE_ATTRIBUTES="
        '"${OTEL_RESOURCE_ATTRIBUTES:+$OTEL_RESOURCE_ATTRIBUTES,}'
        f'session.id={session_id},gen_ai.conversation.id={session_id}" && '
    )


class ClaudeStrategy(AssistantStrategy):
    plugin_path = "/mnt/plugins"

    def run_pipeline(
        self, session_id: str, issue: dict, is_reinvocation: bool = False
    ) -> dict:
        owner = _validate_identifier(issue["repo_owner"], "repo_owner")
        repo = _validate_identifier(issue["repo_name"], "repo_name")
        number = issue["issue_number"]
        title = issue["issue_title"]

        otel = _otel_attrs_prefix(session_id)

        if is_reinvocation:
            prompt = (
                f"You are being re-invoked on issue #{number} "
                f'("{title}"). Owner: {owner}, Repo: {repo}. '
                f"Read .dev-claude/issue.json for the latest issue state including new comments. "
                f"Continue where you left off — the issue has new activity that needs your attention. "
                f"Follow the orchestrator skill."
            )
        else:
            prompt = (
                f"Follow the orchestrator skill for issue #{number} "
                f'("{title}"). Owner: {owner}, Repo: {repo}.'
            )

        prompt_b64 = base64.b64encode(prompt.encode()).decode()

        execute_command(
            session_id,
            f"sh -c 'echo {prompt_b64} | base64 -d > /tmp/prompt.txt'",
            timeout=10,
        )

        return execute_command(
            session_id,
            f"sh -c 'cd /mnt/workplace/gitproject && {otel}"
            f"claude --continue --dangerously-skip-permissions "
            f"--plugin-dir /mnt/workplace/gitproject "
            f'-p "$(cat /tmp/prompt.txt)" '
            f'--allowedTools "mcp__gateway__*,Read,Write,Edit,Bash,Task,ToolSearch" < /dev/null 2>&1\'',
            timeout=2400,
            blocking=False,
        )
