# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Base class for coding assistant strategies."""

import base64
import json
import os
import re
from abc import ABC, abstractmethod

from pipeline import execute_command

# The failure-mode-A probe (issue #34) reconciles resolved decisions #5 and #6:
#   * `LocalOnlyBranchError` — divergence CONFIRMED: the branch is absent from origin
#     (`git ls-remote` empty) AND `git log origin/main..HEAD` shows local commits not
#     in origin/main. This is the headline failure-mode-A case.
#   * `BranchProbeError` — the probe command itself failed or was ambiguous: a non-zero
#     exit, a `git log` failure, OR an `exitCode == 0` empty `git log` that cannot be
#     distinguished from AgentCore dropped output (issue #37). Fail-closed.
try:
    from errors import (
        BranchProbeError,
        LocalOnlyBranchError,
        WorkspaceSetupError,
    )
    from log import get_logger
except ImportError:  # pragma: no cover - test path
    from shared.errors import (
        BranchProbeError,
        LocalOnlyBranchError,
        WorkspaceSetupError,
    )
    from shared.log import get_logger

logger = get_logger(__name__)

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_BRANCH_RE = re.compile(r"^(?!/)(?!.*//)(?!.*\.\.)[a-zA-Z0-9._/-]+(?<!/)$")

# Conservative per-command chunk size for `_write_file_chunked`. Each chunk's
# base64 expands to ~4/3 the raw size; with the `echo … | base64 -d >> path`
# wrapping plus AgentCore JSON request envelope, 6 KB raw stays well under the
# `commands` API request-size limit (failure observed for issue.json ~43 KB raw
# → ~58 KB base64 in a single command, see PR for #23 hot fix).
_CHUNK_BYTES = 6 * 1024


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


def _write_file_chunked(session_id: str, abs_path: str, content: bytes) -> None:
    """Write `content` to `abs_path` in the runtime via chunked base64 commands.

    The naive `echo <base64> | base64 -d > path` pattern fails for large
    payloads because AgentCore's commands API has a per-request size limit.
    Issue #23's re-invocation hit this when issue.json grew to ~43 KB
    (~58 KB base64) — AgentCore returned HTTP 400 for the single oversized
    command.

    This helper splits the raw bytes into 3-byte-aligned chunks (so each
    chunk's base64 is independently decodable; no partial 4-char groups to
    reassemble across chunks), then writes the first chunk with `>` and
    remaining chunks with `>>`.

    Caller is responsible for passing a fixed / pre-validated `abs_path`.
    """
    if not content:
        execute_command(session_id, f"sh -c ': > {abs_path}'", timeout=10)
        return

    # 3-byte alignment so each chunk's base64 is self-contained.
    aligned = (_CHUNK_BYTES // 3) * 3
    first = True
    for i in range(0, len(content), aligned):
        chunk = content[i : i + aligned]
        chunk_b64 = base64.b64encode(chunk).decode()
        redir = ">" if first else ">>"
        execute_command(
            session_id,
            f"sh -c 'echo {chunk_b64} | base64 -d {redir} {abs_path}'",
            timeout=15,
        )
        first = False


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
        logger.info(
            "plugin_mount_check",
            extra={"stdout": mount_check.get("stdout", "")},
        )

        result = execute_command(
            session_id,
            f"sh -c 'mkdir -p /mnt/workplace/gitproject/.dev-claude /mnt/workplace/gitproject/.claude && "
            f"cd {self.plugin_path} && "
            f"cp -r skills hooks gateway-iam-proxy settings.json /mnt/workplace/gitproject/ 2>/dev/null; "
            f"cp -r .claude-plugin .mcp.json /mnt/workplace/gitproject/ 2>/dev/null; "
            f"cp /mnt/workplace/gitproject/settings.json /mnt/workplace/gitproject/.claude/settings.json && "
            f"chmod +x /mnt/workplace/gitproject/hooks/*.sh && echo OK'",
        )
        logger.info(
            "plugin_copy_result",
            extra={
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
            },
        )

        if "OK" not in result.get("stdout", ""):
            raise WorkspaceSetupError(
                f"Plugin copy failed — /mnt/plugins may not be mounted. "
                f"Mount contents: {mount_check.get('stdout', '')} | "
                f"Copy output: {result.get('stdout', '')}"
            )

        # Chunked write to survive large issue.json payloads — see _write_file_chunked.
        _write_file_chunked(
            session_id,
            "/mnt/workplace/gitproject/.dev-claude/issue.json",
            json.dumps(issue).encode(),
        )

        project_context = json.dumps(
            {
                "owner": issue.get("repo_owner", ""),
                "repo": issue.get("repo_name", ""),
                "issue_number": issue.get("issue_number", 0),
            }
        )
        _write_file_chunked(
            session_id,
            "/mnt/workplace/gitproject/.dev-claude/project.json",
            project_context.encode(),
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

        Order (locked by issue #17, extended by issue #34):
          1. `git config --global --add safe.directory /mnt/workplace/gitproject` (idempotent).
          2. Probe for `.git` directory — fail fast with `WorkspaceSetupError` if missing,
             since downstream `git rev-parse` would exit 128 with empty stdout and
             `_validate_branch("")` would raise a misleading "Invalid branch" error.
          3. Read current branch via `git rev-parse --abbrev-ref HEAD`, validate with `_validate_branch`.
          4. Fetch + reset (public path: plain; private path: credential-helper-wrapped, mirrors
             `clone_private_repo` exactly — base64-decoded creds written to `/tmp/.git-creds`,
             cleanup on both success AND failure via `EXIT=$?; rm -f ...; --unset credential.helper`).
          5. Failure-mode-A local-only-branch probe (issue #34) — AFTER fetch+reset, BEFORE rotate.
             Skipped when `branch == "main"` (main never diverges this way). Reconciles resolved
             decisions #5 and #6:
               a. `git ls-remote origin <branch>`, reading BOTH `exitCode` and `stdout`:
                  - `exitCode != 0` -> `BranchProbeError` (probe command failed).
                  - `exitCode == 0` AND non-empty stdout -> branch exists on origin; SHORT-CIRCUIT
                    (no `git log` probe, proceed to rotate — keeps the 7-call happy path).
                  - `exitCode == 0` AND empty stdout -> branch may be absent from origin; run the
                    divergence probe (step b).
               b. `git log --oneline origin/main..HEAD`:
                  - `exitCode != 0` -> `BranchProbeError` (probe command failed).
                  - non-empty stdout (local commits exist beyond origin/main) -> `LocalOnlyBranchError`
                    (divergence CONFIRMED — the real failure-mode-A case).
                  - empty stdout (`exitCode == 0`) -> ambiguous: cannot distinguish "branch absent +
                    no extra commits" from AgentCore dropped `ls-remote` output (issue #37), so
                    `BranchProbeError` (fail-closed per decision #6).
             Fail-closed — a push of a stale local-only branch is impossible past this gate.
          6. Existing rotation + `issue.json` refresh.

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
        logger.info("safe_directory_configured")

        # 2. Probe for `.git` before assuming this is a true re-invocation. The Setup Lambda
        #    classifies "re-invocation" purely by the presence of `.dev-claude/invocation-1/` on
        #    NFS, which can survive a microVM recycle while `.git/` is missing (e.g., partial
        #    cleanup, manual workspace surgery). Without this probe `git rev-parse` exits 128
        #    with empty stdout, `_validate_branch("")` raises `ValueError("Invalid branch")`, and
        #    the operator gets a misleading error. Fail fast with a clear message instead.
        git_probe = execute_command(
            session_id,
            "sh -c 'test -d /mnt/workplace/gitproject/.git && echo OK || echo MISSING'",
            timeout=10,
        )
        if "OK" not in git_probe.get("stdout", ""):
            raise WorkspaceSetupError(
                "workspace .git missing — corrupted state, expected re-invocation but found "
                "no repo. Wipe /mnt/workplace/gitproject and retrigger to recover."
            )

        # 3. Read current branch from the workspace and validate before shell interpolation.
        branch_result = execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject && git rev-parse --abbrev-ref HEAD'",
            timeout=10,
        )
        branch = _validate_branch(branch_result.get("stdout", "").strip())
        logger.info("branch_resolved", extra={"branch": branch})

        # 4. Fetch + reset to track origin/<branch>.
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
        logger.info(
            "fetch_reset_complete",
            extra={"exit_code": fetch_result.get("exitCode")},
        )

        # 5. Failure-mode-A probe (issue #34): detect a local-only branch — one that
        #    exists in the workspace with commits beyond origin/main but is absent from
        #    origin. Pushing such a branch would be unreviewable, so this is a fail-closed
        #    gate that runs AFTER fetch+reset and BEFORE rotate. `main` never diverges this
        #    way, so the probe is skipped entirely for it (keeps the call count at 6).
        if branch != "main":
            # a. `git ls-remote origin <branch>` lists the remote ref if it exists. Per
            #    resolved decision #6 the probe is exitCode-aware: a non-zero exit means
            #    the probe command itself failed and branch state is unknown.
            lsremote_result = execute_command(
                session_id,
                f"sh -c 'cd /mnt/workplace/gitproject && git ls-remote origin {branch}'",
                timeout=30,
            )
            lsremote_exit = lsremote_result.get("exitCode")
            lsremote_stdout = lsremote_result.get("stdout", "").strip()
            if lsremote_exit != 0:
                logger.error(
                    "branch_probe_failed",
                    extra={
                        "branch": branch,
                        "exit_code": lsremote_exit,
                        "reason": "ls_remote_nonzero_exit",
                    },
                )
                raise BranchProbeError(
                    f"git ls-remote origin {branch} exited {lsremote_exit} — branch "
                    f"state on origin could not be determined; refusing to proceed "
                    f"(fail-closed)."
                )
            if lsremote_stdout:
                # exitCode == 0 AND non-empty: the branch is on origin, so there is no
                # local-only divergence to detect — short-circuit (resolved decision #5).
                logger.info(
                    "branch_on_origin",
                    extra={"branch": branch},
                )
            else:
                # exitCode == 0 AND empty stdout: the branch MAY be absent from origin, but
                # per issue #37 a successful command can drop its stdout. Do NOT guess
                # divergence yet — run the `git log origin/main..HEAD` divergence probe and
                # decide from its output (resolved decisions #5 + #6).
                gitlog_result = execute_command(
                    session_id,
                    "sh -c 'cd /mnt/workplace/gitproject && "
                    "git log --oneline origin/main..HEAD'",
                    timeout=30,
                )
                gitlog_exit = gitlog_result.get("exitCode")
                gitlog_stdout = gitlog_result.get("stdout", "").strip()
                if gitlog_exit != 0:
                    logger.error(
                        "branch_probe_failed",
                        extra={
                            "branch": branch,
                            "exit_code": gitlog_exit,
                            "reason": "git_log_nonzero_exit",
                        },
                    )
                    raise BranchProbeError(
                        f"git log origin/main..HEAD exited {gitlog_exit} for branch "
                        f"{branch} — divergence could not be determined; refusing to "
                        f"proceed (fail-closed)."
                    )
                if gitlog_stdout:
                    # Positive evidence of divergence: the branch is absent from origin
                    # AND has local commits not in origin/main. This is failure-mode-A.
                    logger.error(
                        "local_only_branch_detected",
                        extra={
                            "branch": branch,
                            "local_commits": gitlog_stdout,
                            "reason": "commits_beyond_origin_main",
                        },
                    )
                    raise LocalOnlyBranchError(
                        f"branch {branch} is absent from origin yet has local commits not "
                        f"in origin/main — pushing it would be unreviewable; refusing to "
                        f"proceed (fail-closed). Local commits:\n{gitlog_stdout}"
                    )
                # exitCode == 0 AND empty git log: either the branch is genuinely absent
                # with no extra commits, OR the ls-remote stdout was dropped (issue #37).
                # We cannot distinguish the two, so fail closed rather than guess
                # (resolved decision #6's ambiguous-empty caution).
                logger.error(
                    "branch_probe_ambiguous",
                    extra={
                        "branch": branch,
                        "exit_code": gitlog_exit,
                        "reason": "ls_remote_empty_and_no_local_commits",
                    },
                )
                raise BranchProbeError(
                    f"git ls-remote origin {branch} returned empty stdout and "
                    f"git log origin/main..HEAD found no local commits — cannot "
                    f"distinguish 'branch absent with no extra commits' from dropped "
                    f"output (issue #37); refusing to guess (fail-closed)."
                )

        # 6. Rotate: create next invocation-N directory and update 'current' symlink.
        rotate_result = execute_command(
            session_id,
            "sh -c 'cd /mnt/workplace/gitproject/.dev-claude && "
            "N=$(ls -d invocation-* 2>/dev/null | wc -l); N=$((N + 1)); "
            "mkdir -p invocation-$N && "
            "ln -sfn invocation-$N current && "
            "echo invocation-$N'",
        )
        logger.info(
            "invocation_rotated",
            extra={"target": rotate_result.get("stdout", "").strip()},
        )

        # Refresh issue.json with latest event data (includes new comments).
        # Chunked write — issue.json grows past AgentCore's per-command size
        # limit on heavy-comment re-invocations (issue #23 hit this at ~43 KB).
        _write_file_chunked(
            session_id,
            "/mnt/workplace/gitproject/.dev-claude/issue.json",
            json.dumps(issue).encode(),
        )
        logger.info("issue_json_refreshed")

        return rotate_result

    @abstractmethod
    def run_pipeline(
        self, session_id: str, issue: dict, is_reinvocation: bool = False
    ) -> dict:
        """Execute the full SDLC pipeline. Returns execute_command result."""
        ...
