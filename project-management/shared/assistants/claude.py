# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Claude Code assistant strategy."""

import base64
import uuid

from pipeline import execute_command

from assistants.base import AssistantStrategy, _validate_identifier

try:
    from log import get_logger
except ImportError:  # pragma: no cover - test path
    from shared.log import get_logger

logger = get_logger(__name__)

# Persistent location for Claude Code's per-conversation state.
#
# By default Claude Code writes `~/.claude/projects/<encoded-cwd>/<conv-id>.jsonl`
# files containing the full conversation transcript. `claude --continue` reads
# these to resume a prior conversation. The default `~/` path resolves to
# `/home/bedrock_agentcore/` on the AgentCore microVM rootfs (containerd
# overlay), which is reaped whenever the runtime session is stopped or
# `maxLifetime` expires — that would lose all re-invocation continuity.
#
# `/mnt/workplace/` is the AgentCore session-storage NFS mount and persists
# across microVM rebuilds for the same session ID. Setting `CLAUDE_CONFIG_DIR`
# to a path under it relocates the entire `~/.claude/` tree there: settings,
# `.claude.json`, `projects/`, plugins, debug logs. `claude --continue` then
# resumes from the persistent transcript regardless of microVM lifecycle.
#
# Reference: https://code.claude.com/docs/en/sessions.md (Export and locate
# session data) — `CLAUDE_CONFIG_DIR` is the documented knob for this.
_CLAUDE_DATA_DIR = "/mnt/workplace/.claude-data"


def _otel_attrs_prefix(session_id: str) -> str:
    return (
        f"mkdir -p {_CLAUDE_DATA_DIR} && "
        f"export CLAUDE_CONFIG_DIR={_CLAUDE_DATA_DIR} && "
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
                f'("{title}").'
                f" Owner: {owner}, Repo: {repo}."
                f" Read .dev-claude/issue.json for the latest issue state including new comments."
                f" Continue where you left off — the issue has new activity that needs your attention."
                f" Follow the orchestrator skill."
                f" Files have been updated since your last run; re-read before editing."
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

        claude_session_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))

        return execute_command(
            session_id,
            f"sh -c 'cd /mnt/workplace/gitproject && {otel}"
            f"claude --session-id {claude_session_uuid} --continue --fork-session "
            f"--dangerously-skip-permissions "
            f"--plugin-dir /mnt/workplace/gitproject "
            f'-p "$(cat /tmp/prompt.txt)" '
            f'--allowedTools "mcp__gateway__*,Read,Write,Edit,Bash,Task,ToolSearch" < /dev/null 2>&1\'',
            timeout=2400,
            blocking=False,
        )
