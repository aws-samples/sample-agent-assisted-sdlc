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
_BRANCH_RE = re.compile(r"^(?!/)(?!.*//)(?!.*\.\.)[a-zA-Z0-9._/-]+(?<!/)$")


def _validate_identifier(value: str, field_name: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid {field_name}: {value!r} — must match [a-zA-Z0-9._-]+"
        )
    return value


def _validate_branch(value: str) -> str:
    """Validate a git branch name read from `git rev-parse --abbrev-ref HEAD`.

    Permits `/` (e.g. `feat/issue-17`) but blocks shell-injection metachars,
    `..` traversal, double `//`, and leading/trailing `/`.
    """
    if not value or not _BRANCH_RE.match(value):
        raise ValueError(f"Invalid branch name: {value!r}")
    return value


class AssistantStrategy(ABC):
    """Each coding assistant implements this to define how it runs the SDLC pipeline."""

    plugin_path: str = "/mnt/plugins"

    @property
    def runtime_arn(self) -> str:
        return os.environ.get("AGENT_RUNTIME_ARN", "")

    def get_session_id(self, owner: str, repo: str, issue_number: int) -> str:
        session_id = f"sdlc-{owner}-{repo}-issue-{issue_number:05d}-run"
        return session_id.ljust(33, "0")

    def setup_workspace(self, session_id: str, issue: dict) -> dict:
        """Copy plugin to workspace, write issue/project context, fix permissions."""
        # Debug: check what's actually at the plugin mount point
        mount_check = execute_command(
            session_id,
            f"sh -c 'echo MOUNT: && ls -la {self.plugin_path}/ 2>&1'",
        )
        print(f"[setup_workspace] Plugin mount check: {mount_check.get('stdout', '')}")

        result = execute_command(
            session_id,
            f"sh -c 'mkdir -p /mnt/workplace/gitproject/.dev-claude /mnt/workplace/gitproject/.claude && "
            f"cd {self.plugin_path} && "
            f"cp -r skills hooks gateway-iam-proxy settings.json /mnt/workplace/gitproject/ 2>/dev/null; "
            f"cp -r .claude-plugin .mcp.json /mnt/workplace/gitproject/ 2>/dev/null; "
            f"cp /mnt/workplace/gitproject/settings.json /mnt/workplace/gitproject/.claude/settings.json && "
            f"chmod +x /mnt/workplace/gitproject/hooks/*.sh && echo OK'",
        )
        print(
            f"[setup_workspace] Copy result: {result.get('stdout', '')} | stderr: {result.get('stderr', '')}"
        )

        if "OK" not in result.get("stdout", ""):
            raise RuntimeError(
                f"Plugin copy failed — /mnt/plugins may not be mounted. "
                f"Mount contents: {mount_check.get('stdout', '')} | "
                f"Copy output: {result.get('stdout', '')}"
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

    def refresh_for_reinvocation(
        self, session_id: str, issue: dict, token: str | None = None
    ) -> dict:
        """Re-invocation: fetch latest commits, reset workspace, rotate invocation dir, refresh issue.json.

        Order (locked by issue #17):
          1. `git config --global --add safe.directory /mnt/workplace/gitproject` (idempotent).
          2. Read current branch via `git rev-parse --abbrev-ref HEAD`, validate with `_validate_branch`.
          3. Fetch + reset (public path: plain; private path: credential-helper-wrapped, mirrors
             `clone_private_repo` exactly — base64-decoded creds written to `/tmp/.git-creds`,
             cleanup on both success AND failure via `EXIT=$?; rm -f ...; --unset credential.helper`).
          4. Existing rotation + `issue.json` refresh.

        Untracked files (`.dev-claude/`, `hooks/`, `skills/`, `.claude-plugin/`, `.mcp.json`,
        `settings.json`, `gateway-iam-proxy/`) survive `git reset --hard` provided they remain
        untracked (i.e. listed in `.gitignore`).
        """
        # 1. Silence "dubious ownership" — runtime workspace is owned by root but git runs as
        #    a non-root uid in some container configurations. Idempotent, hardcoded path.
        execute_command(
            session_id,
            "sh -c 'git config --global --add safe.directory /mnt/workplace/gitproject'",
            timeout=10,
        )
        print("[refresh_for_reinvocation] Configured safe.directory")

        # 2. Read current branch from the workspace and validate before shell interpolation.
        branch_result = execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject && git rev-parse --abbrev-ref HEAD'",
            timeout=10,
        )
        branch = _validate_branch(branch_result.get("stdout", "").strip())
        print(f"[refresh_for_reinvocation] Branch: {branch}")

        # 3. Fetch + reset to track origin/<branch>.
        if token is None:
            # Public path: unauthenticated fetch.
            fetch_result = execute_command(
                session_id,
                f"sh -c 'cd /mnt/workplace/gitproject && "
                f"git fetch origin && git reset --hard origin/{branch}'",
                timeout=120,
            )
        else:
            # Private path: mirror `clone_private_repo` exactly — base64 creds written via
            # `base64 -d` to `/tmp/.git-creds`, credential helper points at the file, fetch
            # runs, then `EXIT=$?` captures the fetch exit code and shell-level cleanup
            # runs unconditionally (success OR failure).
            cred = f"https://x-access-token:{token}@github.com"
            cred_b64 = base64.b64encode(cred.encode()).decode()
            fetch_result = execute_command(
                session_id,
                f"sh -c 'echo {cred_b64} | base64 -d > /tmp/.git-creds && "
                f'git config --global credential.helper "store --file=/tmp/.git-creds" && '
                f"cd /mnt/workplace/gitproject && "
                f"git fetch origin && git reset --hard origin/{branch} 2>&1; "
                f"EXIT=$?; rm -f /tmp/.git-creds; "
                f"git config --global --unset credential.helper 2>/dev/null; "
                f"[ $EXIT -eq 0 ] && echo OK || echo FAILED'",
                timeout=120,
            )
        print(
            f"[refresh_for_reinvocation] Fetch+reset exitCode={fetch_result.get('exitCode')}"
        )

        # 4. Rotate: create next invocation-N directory and update 'current' symlink.
        rotate_result = execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject/.dev-claude && "
            "N=$(ls -d invocation-* 2>/dev/null | wc -l); N=$((N + 1)); "
            "mkdir -p invocation-$N && "
            "ln -sfn invocation-$N current && "
            "echo invocation-$N'",
        )
        print(
            f"[refresh_for_reinvocation] Rotated to: {rotate_result.get('stdout', '').strip()}"
        )

        # Refresh issue.json with latest event data (includes new comments)
        issue_b64 = base64.b64encode(json.dumps(issue).encode()).decode()
        execute_command(
            session_id,
            f"sh -c 'echo {issue_b64} | base64 -d > /mnt/workplace/gitproject/.dev-claude/issue.json'",
        )
        print("[refresh_for_reinvocation] Refreshed issue.json")

        return rotate_result

    @abstractmethod
    def run_pipeline(
        self, session_id: str, issue: dict, is_reinvocation: bool = False
    ) -> dict:
        """Execute the full SDLC pipeline. Returns execute_command result."""
        ...
