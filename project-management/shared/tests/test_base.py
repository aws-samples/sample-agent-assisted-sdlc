# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for assistants/base.py — validation, session ID, clone logic."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from assistants.base import AssistantStrategy, _validate_branch, _validate_identifier

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
        assert _validate_branch("bugfix/PROJ-42_quick-fix") == "bugfix/PROJ-42_quick-fix"

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
      2. git rev-parse --abbrev-ref   → return {"stdout": "<branch>\n"}
      3. fetch + reset                → return OK
      4. rotate                       → return invocation-2
      5. issue.json write             → return OK
    """
    responses = [
        {"exitCode": 0, "stdout": "", "stderr": ""},
        {"exitCode": 0, "stdout": f"{branch}\n", "stderr": ""},
        {"exitCode": 0, "stdout": "OK", "stderr": ""},
        {"exitCode": 0, "stdout": "invocation-2", "stderr": ""},
        {"exitCode": 0, "stdout": "OK", "stderr": ""},
    ]
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
        """Public path (token=None): safe.directory → rev-parse → fetch+reset → rotate → issue.json."""
        mock_exec.side_effect = _branch_stdout_then_ok("feat/issue-17")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        assert len(calls) == 5

        # 1. safe.directory
        assert "safe.directory" in calls[0]
        assert "/mnt/workplace/gitproject" in calls[0]

        # 2. rev-parse
        assert "git rev-parse --abbrev-ref HEAD" in calls[1]

        # 3. fetch + reset (plain — no credential helper, no /tmp/.git-creds)
        assert "git fetch origin" in calls[2]
        assert "git reset --hard origin/feat/issue-17" in calls[2]
        assert "credential.helper" not in calls[2]
        assert "/tmp/.git-creds" not in calls[2]
        assert "base64 -d" not in calls[2]

        # 4. rotate happens AFTER fetch+reset
        assert "ln -sfn" in calls[3]
        assert "invocation-" in calls[3]

        # 5. issue.json write
        assert "issue.json" in calls[4]
        assert "base64 -d" in calls[4]

    @patch("assistants.base.execute_command")
    def test_private_path_uses_credential_helper(self, mock_exec):
        """Private path: credential-helper-wrapped fetch with token NEVER in argv."""
        mock_exec.side_effect = _branch_stdout_then_ok("main")

        self.strategy.refresh_for_reinvocation(
            "session-1", self.issue, token="t_test"
        )

        calls = [c[0][1] for c in mock_exec.call_args_list]
        # Fetch+reset is the third call (after safe.directory, rev-parse).
        fetch_cmd = calls[2]

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
        # 5-step sequence, but the fetch step (index 2) returns FAILED (exit 128).
        responses = [
            {"exitCode": 0, "stdout": "", "stderr": ""},  # safe.directory
            {"exitCode": 0, "stdout": "main\n", "stderr": ""},  # rev-parse
            {"exitCode": 128, "stdout": "FAILED", "stderr": "auth"},  # fetch+reset fails
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
        fetch_cmd = calls[2]

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
            {"exitCode": 0, "stdout": "feat;rm -rf /\n", "stderr": ""},  # injection
        ]
        mock_exec.side_effect = responses

        with pytest.raises(ValueError, match="Invalid branch"):
            self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        # Only the first two calls should have happened — no fetch, no rotate.
        assert mock_exec.call_count == 2

    @patch("assistants.base.execute_command")
    def test_rotation_and_issue_json_run_after_fetch(self, mock_exec):
        """Rotation + issue.json refresh happen AFTER fetch+reset (positional ordering)."""
        mock_exec.side_effect = _branch_stdout_then_ok("main")

        self.strategy.refresh_for_reinvocation("session-1", self.issue, token=None)

        calls = [c[0][1] for c in mock_exec.call_args_list]
        # Positional check: rev-parse < fetch+reset < rotate < issue.json
        rev_parse_idx = next(
            i for i, c in enumerate(calls) if "git rev-parse" in c
        )
        fetch_idx = next(i for i, c in enumerate(calls) if "git fetch origin" in c)
        rotate_idx = next(i for i, c in enumerate(calls) if "ln -sfn" in c)
        issue_idx = next(i for i, c in enumerate(calls) if "issue.json" in c)

        assert rev_parse_idx < fetch_idx < rotate_idx < issue_idx
