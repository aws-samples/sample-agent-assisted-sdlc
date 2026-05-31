# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Base class for coding assistant strategies."""

import base64
import json
import os
import re
from abc import ABC, abstractmethod

from pipeline import execute_command

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_identifier(value: str, field_name: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid {field_name}: {value!r} — must match [a-zA-Z0-9._-]+"
        )
    return value


class AssistantStrategy(ABC):
    """Each coding assistant implements this to define how it runs the SDLC pipeline."""

    plugin_path: str = "/mnt/plugins/claude"

    @property
    def runtime_arn(self) -> str:
        return os.environ.get("AGENT_RUNTIME_ARN", "")

    def get_session_id(self, owner: str, repo: str, issue_number: int) -> str:
        session_id = f"sdlc-{owner}-{repo}-issue-{issue_number:05d}-run"
        return session_id.ljust(33, "0")

    def setup_workspace(self, session_id: str, issue: dict) -> dict:
        """Copy plugin to workspace, write issue/project context, fix permissions."""
        result = execute_command(
            session_id,
            f"sh -c 'mkdir -p /mnt/workplace/gitproject/.dev-claude /mnt/workplace/gitproject/.claude && "
            f"cp -a {self.plugin_path}/. /mnt/workplace/gitproject/ && "
            f"cp /mnt/workplace/gitproject/settings.json /mnt/workplace/gitproject/.claude/settings.json && "
            f"chmod +x /mnt/workplace/gitproject/hooks/*.sh && echo OK'",
        )

        issue_b64 = base64.b64encode(json.dumps(issue).encode()).decode()
        execute_command(
            session_id,
            f"sh -c 'echo {issue_b64} | base64 -d > /mnt/workplace/gitproject/.dev-claude/issue.json'",
        )

        project_context = json.dumps(
            {
                "owner": issue.get("repo_owner", ""),
                "repo": issue.get("repo_name", ""),
                "issue_number": issue.get("issue_number", 0),
            }
        )
        project_b64 = base64.b64encode(project_context.encode()).decode()
        execute_command(
            session_id,
            f"sh -c 'echo {project_b64} | base64 -d > /mnt/workplace/gitproject/.dev-claude/project.json'",
        )

        # Create numbered invocation directory and symlink 'current' to it
        execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject/.dev-claude && "
            "N=$(ls -d invocation-* 2>/dev/null | wc -l); N=$((N + 1)); "
            "mkdir -p invocation-$N && "
            "ln -sfn invocation-$N current && "
            "echo invocation-$N'",
        )

        return result

    def clone_repo(
        self,
        session_id: str,
        owner: str,
        repo: str,
        private: bool = False,
        token: str | None = None,
    ) -> dict:
        """Clone repo. If private, token must be provided by the connector."""
        _validate_identifier(owner, "repo_owner")
        _validate_identifier(repo, "repo_name")
        if private:
            if not token:
                raise ValueError(
                    "Token required for private repo clone. Connector must provide it."
                )
            return self.clone_private_repo(session_id, owner, repo, token)
        url = f"https://github.com/{owner}/{repo}.git"
        return execute_command(
            session_id,
            f"sh -c 'git clone {url} /mnt/workplace/gitproject 2>&1 && echo OK || echo FAILED'",
        )

    def clone_private_repo(
        self, session_id: str, owner: str, repo: str, token: str
    ) -> dict:
        """Clone using credential helper to avoid exposing token in process args."""
        import base64

        cred = f"https://x-access-token:{token}@github.com"
        cred_b64 = base64.b64encode(cred.encode()).decode()
        return execute_command(
            session_id,
            f"sh -c 'echo {cred_b64} | base64 -d > /tmp/.git-creds && "
            f'git config --global credential.helper "store --file=/tmp/.git-creds" && '
            f"git clone https://github.com/{owner}/{repo}.git /mnt/workplace/gitproject 2>&1; "
            f"EXIT=$?; rm -f /tmp/.git-creds; "
            f"git config --global --unset credential.helper 2>/dev/null; "
            f"[ $EXIT -eq 0 ] && echo OK || echo FAILED'",
        )

    @abstractmethod
    def run_pipeline(self, session_id: str, issue: dict) -> dict:
        """Execute the full SDLC pipeline. Returns execute_command result."""
        ...
