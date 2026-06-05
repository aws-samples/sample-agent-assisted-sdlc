# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for assistants/base.py — validation, session ID, clone logic."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from assistants.base import (  # noqa: E402
    _CHUNK_BYTES,
    AssistantStrategy,
    _validate_branch,
    _validate_identifier,
    _write_file_chunked,
)
from errors import (  # noqa: E402
    BranchProbeError,
    LocalOnlyBranchError,
    WorkspaceSetupError,
)

# --- _validate_identifier tests ---


class TestValidateIdentifier:
    def test_valid_alphanumeric(self):
        assert _validate_identifier("my-repo", "repo") == "my-repo"

    def test_valid_with_dots_underscores_dashes(self):
        assert _validate_identifier("my.repo_name-123", "repo") == "my.repo_name-123"

    def test_valid_uppercase(self):
        assert _validate_identifier("MyOrg", "owner") == "MyOrg"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("", "owner")

    def test_none_raises(self):
        with pytest.raises((ValueError, TypeError)):
            _validate_identifier(None, "owner")  # type: ignore

    def test_space_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("my repo", "repo")

    def test_at_sign_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("user@org", "owner")

    def test_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("owner/repo", "repo")

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("../../etc", "repo")

    def test_newline_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("repo\ninjected", "repo")

    def test_backtick_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("repo`cmd`", "repo")

    def test_dollar_sign_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("$(whoami)", "repo")

    def test_unicode_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("repoñame", "repo")

    def test_semicolon_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_identifier("repo;rm -rf /", "repo")


# --- get_session_id tests ---


class ConcreteStrategy(AssistantStrategy):
    """Concrete subclass for testing abstract base."""

    plugin_path = "/mnt/plugins/test"

    def run_pipeline(self, session_id, issue):
        return {"exitCode": 0, "stdout": "", "stderr": ""}


class TestGetSessionId:
    def setup_method(self):
        self.strategy = ConcreteStrategy()

    def test_normal_case(self):
        sid = self.strategy.get_session_id("myorg", "myrepo", 42)
        assert "myorg" in sid
        assert "myrepo" in sid
        assert "00042" in sid
        assert len(sid) >= 33

    def test_short_names_pad_to_33(self):
        sid = self.strategy.get_session_id("a", "b", 1)
        assert len(sid) >= 33

    def test_long_names_exceed_33(self):
        sid = self.strategy.get_session_id("verylongorgname", "verylongreponame", 99999)
        assert len(sid) >= 33
        assert "verylongorgname" in sid

    def test_issue_zero(self):
        sid = self.strategy.get_session_id("org", "repo", 0)
        assert "00000" in sid
        assert len(sid) >= 33

    def test_issue_overflow_six_digits(self):
        sid = self.strategy.get_session_id("org", "repo", 100000)
        assert "100000" in sid
        assert len(sid) >= 33

    def test_starts_with_sdlc_prefix(self):
        sid = self.strategy.get_session_id("org", "repo", 1)
        assert sid.startswith("sdlc-")


# --- clone_repo tests ---


class TestCloneRepo:
    def setup_method(self):
        self.strategy = ConcreteStrategy()

    @patch("assistants.base.execute_command")
    def test_public_clone(self, mock_exec):
        mock_exec.return_value = {"exitCode": 0, "stdout": "OK", "stderr": ""}
        result = self.strategy.clone_repo("session-1", "myorg", "myrepo")
        assert result["exitCode"] == 0
        cmd = mock_exec.call_args[0][1]
        assert "https://github.com/myorg/myrepo.git" in cmd

    def test_invalid_owner_raises(self):
        with pytest.raises(ValueError, match="Invalid repo_owner"):
            self.strategy.clone_repo("s", "invalid@owner", "repo")

    def test_invalid_repo_raises(self):
        with pytest.raises(ValueError, match="Invalid repo_name"):
            self.strategy.clone_repo("s", "owner", "../evil")

    def test_private_without_token_raises(self):
        with pytest.raises(ValueError, match="Token required"):
            self.strategy.clone_repo("s", "owner", "repo", private=True, token=None)

    @patch("assistants.base.execute_command")
    def test_private_with_token_calls_credential_helper(self, mock_exec):
        mock_exec.return_value = {"exitCode": 0, "stdout": "OK", "stderr": ""}
        self.strategy.clone_repo(
            "s", "owner", "repo", private=True, token="ghp_test123"
        )
        cmd = mock_exec.call_args[0][1]
        assert "base64 -d" in cmd
        assert "credential.helper" in cmd
        assert "ghp_test123" not in cmd  # Token must NOT appear in plain text

    @patch("assistants.base.execute_command")
    def test_private_clone_cleans_up_creds(self, mock_exec):
        mock_exec.return_value = {"exitCode": 0, "stdout": "OK", "stderr": ""}
        self.strategy.clone_repo("s", "owner", "repo", private=True, token="tok")
        cmd = mock_exec.call_args[0][1]
        assert "rm -f /tmp/.git-creds" in cmd
        assert "--unset credential.helper" in cmd


# --- setup_workspace tests ---


class TestSetupWorkspace:
    def setup_method(self):
        self.strategy = ConcreteStrategy()

    @patch("assistants.base.execute_command")
    def test_writes_issue_json_base64(self, mock_exec):
        mock_exec.return_value = {"exitCode": 0, "stdout": "OK", "stderr": ""}
        issue = {"repo_owner": "org", "repo_name": "repo", "issue_number": 1}
        self.strategy.setup_workspace("session-1", issue)
        calls = [c[0][1] for c in mock_exec.call_args_list]
        issue_write_cmd = next(c for c in calls if "issue.json" in c)
        assert "base64 -d" in issue_write_cmd

    @patch("assistants.base.execute_command")
    def test_writes_project_json_base64(self, mock_exec):
        mock_exec.return_value = {"exitCode": 0, "stdout": "OK", "stderr": ""}
        issue = {"repo_owner": "org", "repo_name": "repo", "issue_number": 5}
        self.strategy.setup_workspace("session-1", issue)
        calls = [c[0][1] for c in mock_exec.call_args_list]
        project_write_cmd = next(c for c in calls if "project.json" in c)
        assert "base64 -d" in project_write_cmd

    @patch("assistants.base.execute_command")
    def test_creates_invocation_directory(self, mock_exec):
        mock_exec.return_value = {"exitCode": 0, "stdout": "OK", "stderr": ""}
        issue = {"repo_owner": "org", "repo_name": "repo", "issue_number": 1}
        self.strategy.setup_workspace("session-1", issue)
        calls = [c[0][1] for c in mock_exec.call_args_list]
        invocation_cmd = next(c for c in calls if "invocation" in c)
        assert "ln -sfn" in invocation_cmd


# --- _validate_branch tests ---


class TestValidateBranch:
    def test_simple_main(self):
        assert _validate_branch("main") == "main"

    def test_feat_slash_issue(self):
        assert _validate_branch("feat/issue-17") == "feat/issue-17"

    def test_release_with_dots(self):
        assert _validate_branch("release/v1.2.3") == "release/v1.2.3"

    def test_bugfix_with_underscore_and_dash(self):
        assert (
            _validate_branch("bugfix/PROJ-42_quick-fix") == "bugfix/PROJ-42_quick-fix"
        )

    def test_dotted_segment(self):
        assert _validate_branch("hotfix.urgent") == "hotfix.urgent"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("")

    def test_leading_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("/feat/x")

    def test_trailing_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat/x/")

    def test_double_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat//x")

    def test_dot_dot_traversal_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat/../etc")

    def test_whitespace_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat issue")

    def test_semicolon_injection_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat;rm -rf /")

    def test_backtick_injection_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat`whoami`")

    def test_dollar_injection_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("$(whoami)")

    def test_newline_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat\ninjected")

    def test_unicode_raises(self):
        with pytest.raises(ValueError, match="Invalid branch"):
            _validate_branch("feat/ñame")


# --- refresh_for_reinvocation tests ---


def _branch_stdout_then_ok(branch: str = "feat/issue-17"):
    """Build a side_effect callable that returns the branch on rev-parse and OK otherwise.

    Order of execute_command calls inside refresh_for_reinvocation:
      1. safe.directory config        → return generic OK
      2. .git probe                   → return {"stdout": "OK\n"} (repo present)
      3. git rev-parse --abbrev-ref   → return {"stdout": "<branch>\n"}
      4. fetch + reset                → return OK
      4a. ls-remote probe             → ONLY when branch != "main"; returns a
                                        non-empty ref line so the probe short-circuits
                                        (branch is on origin, no divergence).
      5. rotate                       → return invocation-2
      6. issue.json write             → return OK

    For `main` the probe step is skipped entirely (6 calls). For any non-`main`
    branch the ls-remote probe is inserted between fetch+reset and rotate (7 calls),
    and this helper supplies a non-empty stdout so the branch is treated as present
    on origin (resolved decision #5 short-circuit).
    """
    responses = [
        {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
        {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
        {"exitCode": 0, "stdout": f"{branch}\n", "stderr": ""},  # rev-parse
        {"exitCode": 0, "stdout": "OK", "stderr": ""},  # fetch + reset
    ]
    if branch != "main":
        # ls-remote probe — non-empty stdout => branch exists on origin, short-circuit.
        responses.append(
            {
                "exitCode": 0,
                "stdout": f"abc123\trefs/heads/{branch}\n",
                "stderr": "",
            }
        )
    responses.extend(
        [
            {"exitCode": 0, "stdout": "invocation-2", "stderr": ""},  # rotate
            {"exitCode": 0, "stdout": "OK", "stderr": ""},  # issue.json
        ]
    )
    iterator = iter(responses)

    def side_effect(*args, **kwargs):
        return next(iterator)

    return side_effect


class TestRefreshForReinvocation:
    def setup_method(self):
        self.strategy = ConcreteStrategy()
        self.issue = {
            "repo_owner": "org",
            "repo_name": "repo",
            "issue_number": 17,
            "issue_title": "test",
        }

    @patch("assistants.base.execute_command")
    def test_public_path_command_order(self, mock_exec):
        """Public non-`main` path: safe.directory → .git probe → rev-parse → fetch+reset → ls-remote → rotate → issue.json.

        Resolved decision #5: a non-`main` branch inserts the ls-remote probe between
        fetch+reset and rotate, bumping the call count from 6 to 7. The helper returns a
        non-empty ref so the probe short-circuits (branch present on origin).
        """
        mock_exec.side_effect = _branch_stdout_then_ok("feat/issue-17")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) == 7

        # 1. safe.directory
        assert "safe.directory" in calls[0]
        assert "/mnt/workplace/gitproject" in calls[0]

        # 2. .git probe
        assert "test -d /mnt/workplace/gitproject/.git" in calls[1]

        # 3. rev-parse
        assert "git rev-parse --abbrev-ref HEAD" in calls[2]

        # 4. fetch + reset (plain — no credential helper, no /tmp/.git-creds)
        assert "git fetch origin" in calls[3]
        assert "git reset --hard origin/feat/issue-17" in calls[3]
        assert "credential.helper" not in calls[3]
        assert "/tmp/.git-creds" not in calls[3]
        assert "base64 -d" not in calls[3]

        # 4a. ls-remote probe (non-`main` only) — runs AFTER fetch+reset, BEFORE rotate
        assert "git ls-remote origin feat/issue-17" in calls[4]

        # 5. rotate happens AFTER the ls-remote probe
        assert "ln -sfn" in calls[5]
        assert "invocation-" in calls[5]

        # 6. issue.json write
        assert "issue.json" in calls[6]
        assert "base64 -d" in calls[6]

    @patch("assistants.base.execute_command")
    def test_private_path_uses_credential_helper(self, mock_exec):
        """Private path: credential-helper-wrapped fetch with token NEVER in argv."""
        mock_exec.side_effect = _branch_stdout_then_ok("main")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token="t_test")

        calls = [c[0][1] for c in mock_exec.call_args_list]
        # Fetch+reset is the fourth call (after safe.directory, .git probe, rev-parse).
        fetch_cmd = calls[3]

        # credential-helper pattern present
        assert "base64 -d" in fetch_cmd
        assert "/tmp/.git-creds" in fetch_cmd
        assert "credential.helper" in fetch_cmd
        assert "git fetch origin" in fetch_cmd
        assert "git reset --hard origin/main" in fetch_cmd

        # Cleanup encoded in the same shell invocation
        assert "EXIT=$?" in fetch_cmd
        assert "rm -f /tmp/.git-creds" in fetch_cmd
        assert "--unset credential.helper" in fetch_cmd

        # Token must NEVER appear literally in any recorded command string
        for cmd in calls:
            assert "t_test" not in cmd

    @patch("assistants.base.execute_command")
    def test_private_path_cleanup_on_fetch_failure(self, mock_exec):
        """Cleanup commands are present in the same `sh -c` regardless of fetch outcome.

        The cleanup is shell-level (`EXIT=$?; rm -f ...; --unset ...`) so it runs
        unconditionally inside the same `sh -c`. We verify both that the shape encodes
        the cleanup AND that a non-zero fetch exit code does not prevent cleanup
        substrings from being present in the command string we recorded.
        """
        # 6-step sequence, but the fetch step (index 3) returns FAILED (exit 128).
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
            {"exitCode": 0, "stdout": "main\n", "stderr": ""},  # rev-parse
            {
                "exitCode": 128,
                "stdout": "FAILED",
                "stderr": "auth",
            },  # fetch+reset fails
            {"exitCode": 0, "stdout": "invocation-2", "stderr": ""},  # rotate
            {"exitCode": 0, "stdout": "OK", "stderr": ""},  # issue.json
        ]
        mock_exec.side_effect = responses

        # The function does not raise on non-zero exit — execute_command surfaces it via
        # the result dict. This mirrors clone_private_repo's behavior. The test asserts
        # the cleanup is encoded in the shell command.
        self.strategy.refresh_for_reinvocation(
            "session-1", self.issue, token="secret_tok_123"
        )

        calls = [c[0][1] for c in mock_exec.call_args_list]
        fetch_cmd = calls[3]

        # Cleanup substrings present in the failing-fetch command
        assert "EXIT=$?" in fetch_cmd
        assert "rm -f /tmp/.git-creds" in fetch_cmd
        assert "--unset credential.helper" in fetch_cmd

        # Token never appears in any recorded command, even on failure path
        for cmd in calls:
            assert "secret_tok_123" not in cmd

    @patch("assistants.base.execute_command")
    def test_invalid_branch_raises_before_fetch(self, mock_exec):
        """If `git rev-parse` returns a malicious branch name, refresh aborts before fetch."""
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
            {"exitCode": 0, "stdout": "feat;rm -rf /\n", "stderr": ""},  # injection
        ]
        mock_exec.side_effect = responses

        with pytest.raises(ValueError, match="Invalid branch"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        # Only safe.directory + .git probe + rev-parse should have happened — no fetch, no rotate.
        assert mock_exec.call_count == 3

    @patch("assistants.base.execute_command")
    def test_rotation_and_issue_json_run_after_fetch(self, mock_exec):
        """Rotation + issue.json refresh happen AFTER fetch+reset (positional ordering)."""
        mock_exec.side_effect = _branch_stdout_then_ok("main")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        # Positional check: rev-parse < fetch+reset < rotate < issue.json
        rev_parse_idx = next(i for i, c in enumerate(calls) if "git rev-parse" in c)
        fetch_idx = next(i for i, c in enumerate(calls) if "git fetch origin" in c)
        rotate_idx = next(i for i, c in enumerate(calls) if "ln -sfn" in c)
        issue_idx = next(i for i, c in enumerate(calls) if "issue.json" in c)

        assert rev_parse_idx < fetch_idx < rotate_idx < issue_idx

    @patch("assistants.base.execute_command")
    def test_missing_git_raises_workspace_setup_error(self, mock_exec):
        """If `.git` is missing on disk, refresh aborts before rev-parse with a clear error.

        Reproduces the failure observed live on issue #33 (2026-06-04 SFN execution
        `issue-33-1780611770`): `.dev-claude/invocation-1/` survived a microVM recycle while
        `.git/` did not, so the Setup Lambda classified the run as a re-invocation but
        `git rev-parse --abbrev-ref HEAD` exited 128 with empty stdout, and
        `_validate_branch("")` raised a misleading `ValueError("Invalid branch: ''")`.
        The probe added in this fix must catch the missing-`.git` state and raise
        `WorkspaceSetupError` with a clear remediation message.
        """
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {
                "exitCode": 0,
                "stdout": "MISSING\n",
                "stderr": "",
            },  # .git probe — repo missing
        ]
        mock_exec.side_effect = responses

        with pytest.raises(WorkspaceSetupError, match=".git missing"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        # Only safe.directory + .git probe ran — no rev-parse, no fetch, no rotate.
        assert mock_exec.call_count == 2

    # --- failure-mode-A local-only-branch probe (issue #34) ---

    @patch("assistants.base.execute_command")
    def test_main_branch_skips_local_only_probe(self, mock_exec):
        """`main` never diverges local-only — the ls-remote probe is skipped entirely.

        Resolved decision #5: the whole probe block is skipped for `main`, so the call
        count stays at the original 6 (no ls-remote inserted) and no `git ls-remote`
        command is ever recorded.
        """
        mock_exec.side_effect = _branch_stdout_then_ok("main")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) == 6
        assert not any("git ls-remote" in c for c in calls)

    @patch("assistants.base.execute_command")
    def test_branch_on_origin_short_circuits(self, mock_exec):
        """Non-`main` branch present on origin: ls-remote returns a ref, probe short-circuits.

        Resolved decision #5/#6: `exitCode == 0` AND non-empty stdout means the branch
        exists on origin — no divergence, no raise, and no extra `git log` probe. The
        call sequence is exactly 7 (ls-remote inserted) and execution continues to rotate.
        """
        mock_exec.side_effect = _branch_stdout_then_ok("feat/issue-34")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) == 7
        # ls-remote ran exactly once and no git-log divergence probe was needed.
        assert sum("git ls-remote origin feat/issue-34" in c for c in calls) == 1
        assert not any("git log" in c for c in calls)
        # Rotate + issue.json still ran after the short-circuit.
        assert "ln -sfn" in calls[5]
        assert "issue.json" in calls[6]

    @patch("assistants.base.execute_command")
    def test_probe_nonzero_exit_raises_branch_probe_error(self, mock_exec):
        """`git ls-remote` exiting non-zero -> BranchProbeError (fail-closed).

        Resolved decision #6: the probe is exitCode-aware. A non-zero exit means the
        branch state on origin could not be determined, so refresh aborts BEFORE rotate
        and issue.json — no push can follow.
        """
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
            {"exitCode": 0, "stdout": "feat/issue-34\n", "stderr": ""},  # rev-parse
            {"exitCode": 0, "stdout": "OK", "stderr": ""},  # fetch + reset
            {
                "exitCode": 2,
                "stdout": "",
                "stderr": "fatal: unable to access origin",
            },  # ls-remote errors
        ]
        mock_exec.side_effect = responses

        with pytest.raises(BranchProbeError, match="could not be determined"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        # safe.directory + .git probe + rev-parse + fetch + ls-remote ran; rotate/issue.json did NOT.
        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert mock_exec.call_count == 5
        assert "git ls-remote origin feat/issue-34" in calls[4]
        assert not any("ln -sfn" in c for c in calls)
        assert not any("issue.json" in c for c in calls)

    @patch("assistants.base.execute_command")
    def test_local_only_branch_raises_local_only_branch_error(self, mock_exec):
        """AC failure-mode-A: ls-remote empty + git log shows local commits -> LocalOnlyBranchError.

        This is the issue #34 acceptance-criteria test. `execute_command` returns: a
        successful `git fetch`, an `exitCode == 0` empty `git ls-remote` (branch may be
        absent from origin), and `git log origin/main..HEAD` returning commits. Divergence
        is CONFIRMED, so `refresh_for_reinvocation` raises `LocalOnlyBranchError` and never
        reaches the rotate or issue.json-write commands (fail-closed — no push can follow).
        """
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
            {"exitCode": 0, "stdout": "feat/issue-34\n", "stderr": ""},  # rev-parse
            {"exitCode": 0, "stdout": "OK", "stderr": ""},  # fetch + reset (success)
            {"exitCode": 0, "stdout": "", "stderr": ""},  # ls-remote: exit 0, empty
            {
                "exitCode": 0,
                "stdout": "c9ce0dd add stale base commit\ndeadbee wip\n",
                "stderr": "",
            },  # git log origin/main..HEAD: local commits exist
        ]
        mock_exec.side_effect = responses

        with pytest.raises(LocalOnlyBranchError, match="feat/issue-34"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        # safe.directory + .git probe + rev-parse + fetch + ls-remote + git log ran.
        assert mock_exec.call_count == 6
        assert "git ls-remote origin feat/issue-34" in calls[4]
        assert "git log --oneline origin/main..HEAD" in calls[5]
        # The divergence summary is surfaced in the exception message for diagnosis.
        # Rotate + issue.json write were NEVER issued.
        assert not any("ln -sfn" in c for c in calls)
        assert not any("issue.json" in c for c in calls)

    @patch("assistants.base.execute_command")
    def test_git_log_probe_nonzero_exit_raises_branch_probe_error(self, mock_exec):
        """`git log origin/main..HEAD` exiting non-zero -> BranchProbeError (fail-closed).

        Resolved decision #6: the divergence probe is also exitCode-aware. If `git log`
        itself fails (e.g. `origin/main` unresolvable), divergence cannot be determined,
        so refresh aborts before rotate and issue.json.
        """
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
            {"exitCode": 0, "stdout": "feat/issue-34\n", "stderr": ""},  # rev-parse
            {"exitCode": 0, "stdout": "OK", "stderr": ""},  # fetch + reset
            {"exitCode": 0, "stdout": "", "stderr": ""},  # ls-remote: exit 0, empty
            {
                "exitCode": 128,
                "stdout": "",
                "stderr": "fatal: bad revision 'origin/main..HEAD'",
            },  # git log fails
        ]
        mock_exec.side_effect = responses

        with pytest.raises(BranchProbeError, match="could not be determined"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert mock_exec.call_count == 6
        assert "git ls-remote origin feat/issue-34" in calls[4]
        assert "git log --oneline origin/main..HEAD" in calls[5]
        assert not any("ln -sfn" in c for c in calls)
        assert not any("issue.json" in c for c in calls)

    @patch("assistants.base.execute_command")
    def test_probe_ambiguous_empty_stdout_raises_branch_probe_error(self, mock_exec):
        """ls-remote empty + git log empty (exit 0) is ambiguous -> BranchProbeError (fail-closed).

        Resolved decision #6 (critical): per issue #37 a successful command can return
        exitCode=0 with NO stdout (dropped output). When `git ls-remote` is empty we run
        the `git log origin/main..HEAD` divergence probe; if it ALSO returns empty (exit 0)
        we cannot distinguish "branch absent with no extra commits" from a dropped
        ls-remote result, so this ambiguous case raises BranchProbeError rather than
        guessing divergence.
        """
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "OK\n", "stderr": ""},  # .git probe
            {"exitCode": 0, "stdout": "feat/issue-34\n", "stderr": ""},  # rev-parse
            {"exitCode": 0, "stdout": "OK", "stderr": ""},  # fetch + reset
            {"exitCode": 0, "stdout": "", "stderr": ""},  # ls-remote: exit 0, empty
            {"exitCode": 0, "stdout": "", "stderr": ""},  # git log: exit 0, empty
        ]
        mock_exec.side_effect = responses

        with pytest.raises(BranchProbeError, match="dropped output"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert mock_exec.call_count == 6
        assert "git ls-remote origin feat/issue-34" in calls[4]
        assert "git log --oneline origin/main..HEAD" in calls[5]
        assert not any("ln -sfn" in c for c in calls)
        assert not any("issue.json" in c for c in calls)

    @patch("assistants.base.execute_command")
    def test_probe_does_not_leak_token(self, mock_exec):
        """The ls-remote probe command must never embed the GitHub token literally."""
        mock_exec.side_effect = _branch_stdout_then_ok("feat/issue-34")

        self.strategy.refresh_for_reinvocation(
            "session-1", self.issue, token="secret_tok_123"
        )

        calls = [c[0][1] for c in mock_exec.call_args_list]
        probe_cmd = next(c for c in calls if "git ls-remote" in c)
        assert "secret_tok_123" not in probe_cmd
        for cmd in calls:
            assert "secret_tok_123" not in cmd

    def test_local_only_branch_error_is_distinct_exception(self):
        """`LocalOnlyBranchError` and `BranchProbeError` are distinct Exception subclasses.

        `LocalOnlyBranchError` is the divergence-confirmed category (branch absent from
        origin AND local commits beyond origin/main); `BranchProbeError` is the
        probe-failed/ambiguous category. They must be distinct so callers can react
        differently (e.g. surface divergence vs. retry the probe).
        """
        assert issubclass(LocalOnlyBranchError, Exception)
        assert issubclass(BranchProbeError, Exception)
        assert LocalOnlyBranchError is not BranchProbeError


# --- _write_file_chunked tests ---


class TestWriteFileChunked:
    """Verify the chunked-write helper splits large payloads correctly.

    Issue #23 hot fix: AgentCore's commands API rejects single commands whose
    base64 payload is too large; the helper splits raw bytes on 3-byte
    boundaries so each chunk's base64 is independently decodable, then writes
    the first chunk with `>` and the rest with `>>`.
    """

    @patch("assistants.base.execute_command")
    def test_empty_content_truncates(self, mock_exec):
        """Empty content writes a single `: > path` truncate command, no base64."""
        _write_file_chunked("session-1", "/mnt/test/empty.json", b"")
        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) == 1
        assert ": > /mnt/test/empty.json" in calls[0]
        assert "base64" not in calls[0]

    @patch("assistants.base.execute_command")
    def test_small_content_single_chunk_truncating_redirect(self, mock_exec):
        """Content < CHUNK_BYTES fits in one command using `>` (truncate)."""
        content = b'{"k": "v"}'  # 10 bytes
        _write_file_chunked("session-1", "/mnt/test/small.json", content)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) == 1
        assert " > /mnt/test/small.json" in calls[0]
        assert " >> " not in calls[0]
        assert "base64 -d" in calls[0]

    @patch("assistants.base.execute_command")
    def test_large_content_multiple_chunks_with_append(self, mock_exec):
        """Content > CHUNK_BYTES splits into N commands: first `>`, rest `>>`."""
        # 3x the chunk size → at least 3 commands.
        content = b"x" * (_CHUNK_BYTES * 3 + 100)
        _write_file_chunked("session-1", "/mnt/test/large.json", content)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) >= 3, f"Expected ≥3 chunks, got {len(calls)}"

        # First chunk truncates with `>`.
        assert " > /mnt/test/large.json" in calls[0]
        assert " >> " not in calls[0]

        # Remaining chunks append with `>>`.
        for i, call in enumerate(calls[1:], start=1):
            assert (
                " >> /mnt/test/large.json" in call
            ), f"chunk {i} missing append redirect"
            assert " > /mnt/test/large.json" not in call.replace(
                " >> /mnt/test/large.json", ""
            ), f"chunk {i} has unexpected truncate redirect"

    @patch("assistants.base.execute_command")
    def test_chunks_decode_and_concatenate_to_original(self, mock_exec):
        """Each chunk's base64 is independently decodable; concatenating decoded
        bytes reproduces the original content. This is the property that makes
        the chunked-write safe across the AgentCore command boundary."""
        import base64 as _b64
        import re

        # Use a payload at a non-3-aligned size (12345 bytes) to catch any
        # partial-chunk handling bugs.
        original = bytes(range(256)) * 50  # 12,800 bytes — not a multiple of anything
        original = original[:12345]

        _write_file_chunked("session-1", "/mnt/test/payload.bin", original)

        # Extract the base64 token from each `echo <b64> | base64 -d` call.
        calls = [c[0][1] for c in mock_exec.call_args_list]
        b64_re = re.compile(r"echo ([A-Za-z0-9+/=]+) \| base64")
        decoded_chunks = []
        for c in calls:
            m = b64_re.search(c)
            assert m, f"could not extract base64 from: {c[:100]}"
            decoded_chunks.append(_b64.b64decode(m.group(1)))

        # Concatenation of independently-decoded chunks must equal the original.
        assert b"".join(decoded_chunks) == original

    @patch("assistants.base.execute_command")
    def test_chunk_size_alignment(self, mock_exec):
        """All chunks except the last are aligned to 3 bytes (so each chunk's
        base64 has no `=` padding except possibly the final chunk)."""
        import base64 as _b64
        import re

        content = b"a" * (_CHUNK_BYTES * 2 + 5)  # 2 full chunks + a 5-byte remainder
        _write_file_chunked("session-1", "/mnt/test/p.json", content)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        b64_re = re.compile(r"echo ([A-Za-z0-9+/=]+) \| base64")
        chunks = []
        for c in calls:
            m = b64_re.search(c)
            chunks.append(_b64.b64decode(m.group(1)))

        # Every chunk except possibly the last must be a multiple of 3 bytes.
        for i, ch in enumerate(chunks[:-1]):
            assert len(ch) % 3 == 0, f"chunk {i} length {len(ch)} not 3-byte aligned"

    @patch("assistants.base.execute_command")
    def test_path_appears_in_every_command(self, mock_exec):
        """All chunk commands target the same path — the helper does not split
        writes across paths or accidentally write to a different file."""
        content = b"y" * (_CHUNK_BYTES * 3)
        path = "/mnt/workplace/gitproject/.dev-claude/issue.json"
        _write_file_chunked("session-1", path, content)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        for c in calls:
            assert path in c, f"command missing target path: {c[:120]}"
