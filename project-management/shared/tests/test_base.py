# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for assistants/base.py — validation, session ID, clone logic."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from assistants.base import AssistantStrategy, _validate_identifier

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
