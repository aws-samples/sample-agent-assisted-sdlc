# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Codex assistant strategy."""

import base64

from pipeline import execute_command

from assistants.base import AssistantStrategy, _validate_identifier


class CodexStrategy(AssistantStrategy):
    plugin_path = "/mnt/plugins/codex"

    def run_pipeline(self, session_id: str, issue: dict) -> dict:
        owner = _validate_identifier(issue["repo_owner"], "repo_owner")
        repo = _validate_identifier(issue["repo_name"], "repo_name")
        number = issue["issue_number"]
        title = issue["issue_title"]

        execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject && "
            "mkdir -p .codex && "
            "cp .mcp.json .codex/mcp.json && "
            "echo OK'",
            timeout=30,
        )

        prompt = (
            f"Follow the orchestrator instructions in AGENTS.md "
            f"for issue #{number} "
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
            "sh -c 'cd /mnt/workplace/gitproject && "
            "codex -q --approval-mode full-auto "
            '"$(cat /tmp/prompt.txt)" < /dev/null 2>&1\'',
            timeout=2400,
            blocking=False,
        )
