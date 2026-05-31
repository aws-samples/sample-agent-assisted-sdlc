# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Kiro assistant strategy."""

import base64

from pipeline import execute_command

from assistants.base import AssistantStrategy, _validate_identifier


class KiroStrategy(AssistantStrategy):
    plugin_path = "/mnt/plugins/kiro"

    def run_pipeline(self, session_id: str, issue: dict) -> dict:
        owner = _validate_identifier(issue["repo_owner"], "repo_owner")
        repo = _validate_identifier(issue["repo_name"], "repo_name")
        number = issue["issue_number"]
        title = issue["issue_title"]

        execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject && "
            "mkdir -p .kiro/steering .kiro/settings && "
            "cp steering/agent.md .kiro/steering/agent.md && "
            "cp .mcp.json .kiro/settings/mcp.json && "
            "echo OK'",
            timeout=30,
        )

        mcp_check = execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject && kiro-cli mcp list 2>&1'",
            timeout=60,
        )
        if mcp_check.get("exitCode", 1) != 0:
            return {
                "error": "MCP gateway not reachable",
                "stdout": mcp_check.get("stdout", ""),
                "stderr": mcp_check.get("stderr", ""),
                "exitCode": 1,
            }

        prompt = (
            f"Follow the orchestrator instructions in .kiro/steering/agent.md "
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
            "kiro-cli chat --no-interactive --trust-all-tools "
            '--require-mcp-startup "$(cat /tmp/prompt.txt)" < /dev/null 2>&1\'',
            timeout=2400,
            blocking=False,
        )
