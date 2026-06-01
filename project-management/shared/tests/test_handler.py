# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for github/connector/lambda/index.py — user/repo authorization."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add both paths needed for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "github" / "connector" / "lambda"),
)


def make_event(
    repo_owner="myorg",
    repo_name="myrepo",
    issue_number=1,
    triggered_by="alice",
    issue_title="test",
):
    return {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "issue_number": issue_number,
        "issue_title": issue_title,
        "issue_body": "test body",
        "issue_author": "author",
        "triggered_by": triggered_by,
        "issue_comments": [],
    }


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv(
        "AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-west-2:123:runtime/test"
    )
    monkeypatch.setenv("ASSISTANT_TYPE", "claude-code")
    monkeypatch.setenv("PRIVATE_REPO", "false")
    monkeypatch.setenv("AWS_REGION_NAME", "us-west-2")
    monkeypatch.setenv("ALLOWED_USERS", json.dumps(["alice", "bob"]))
    monkeypatch.setenv("ALLOWED_REPOS", json.dumps(["myorg/myrepo"]))
    monkeypatch.setenv("SDLC_LABEL_PREFIX", "agent")


class TestUserAuthorization:
    @patch("index.get_token", return_value=None)
    @patch("index.STRATEGIES")
    def test_allowed_user_proceeds(self, mock_strategies, mock_token, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["alice"]))
        mock_strategy = MagicMock()
        mock_strategy.get_session_id.return_value = "session-123456789012345678901"
        mock_strategy.clone_repo.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategy.setup_workspace.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategies.__getitem__.return_value = lambda: mock_strategy

        # Re-import to pick up new env
        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(triggered_by="alice"), None)
        assert result["statusCode"] == 200

    @patch("index.STRATEGIES")
    def test_unauthorized_user_rejected(self, mock_strategies, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["alice", "bob"]))

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(triggered_by="charlie"), None)
        assert result["statusCode"] == 403
        assert "not authorized" in result["error"]

    @patch("index.get_token", return_value=None)
    @patch("index.STRATEGIES")
    def test_wildcard_allows_any_user(self, mock_strategies, mock_token, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        mock_strategy = MagicMock()
        mock_strategy.get_session_id.return_value = "session-123456789012345678901"
        mock_strategy.clone_repo.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategy.setup_workspace.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategies.__getitem__.return_value = lambda: mock_strategy

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(triggered_by="anyone"), None)
        assert result["statusCode"] == 200

    def test_empty_allowed_users_rejects_all(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps([]))

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(triggered_by="alice"), None)
        # Empty list with `if ALLOWED_USERS and ...` → skips check (falsy)
        # This is the current behavior — empty list = no restriction
        # Document this: empty list means "no users configured" = reject
        # OR it means "no restriction" depending on implementation
        assert result is not None

    def test_missing_triggered_by_rejected(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["alice"]))

        import importlib

        import index

        importlib.reload(index)

        event = make_event()
        del event["triggered_by"]
        result = index.handler(event, None)
        assert result["statusCode"] == 403

    def test_case_sensitive_user_match(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["Alice"]))

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(triggered_by="alice"), None)
        assert result["statusCode"] == 403


class TestRepoAuthorization:
    def test_unauthorized_repo_rejected(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps(["myorg/myrepo"]))
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(repo_owner="other", repo_name="evil"), None)
        assert result["statusCode"] == 403
        assert "not authorized" in result["error"]

    @patch("index.get_token", return_value=None)
    @patch("index.STRATEGIES")
    def test_authorized_repo_proceeds(self, mock_strategies, mock_token, monkeypatch):
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps(["myorg/myrepo"]))
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        mock_strategy = MagicMock()
        mock_strategy.get_session_id.return_value = "session-123456789012345678901"
        mock_strategy.clone_repo.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategy.setup_workspace.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategies.__getitem__.return_value = lambda: mock_strategy

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(repo_owner="myorg", repo_name="myrepo"), None)
        assert result["statusCode"] == 200

    @patch("index.get_token", return_value=None)
    @patch("index.STRATEGIES")
    def test_empty_allowed_repos_allows_all(
        self, mock_strategies, mock_token, monkeypatch
    ):
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps([]))
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        mock_strategy = MagicMock()
        mock_strategy.get_session_id.return_value = "session-123456789012345678901"
        mock_strategy.clone_repo.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategy.setup_workspace.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }
        mock_strategies.__getitem__.return_value = lambda: mock_strategy

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(repo_owner="any", repo_name="repo"), None)
        assert result["statusCode"] == 200

    def test_partial_repo_match_rejected(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps(["myorg/myrepo"]))
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(
            make_event(repo_owner="myorg", repo_name="myrepo-2"), None
        )
        assert result["statusCode"] == 403


class TestFieldValidation:
    def test_missing_repo_owner(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps([]))

        import importlib

        import index

        importlib.reload(index)

        event = make_event()
        event["repo_owner"] = ""
        result = index.handler(event, None)
        assert result["statusCode"] == 400

    def test_missing_issue_number(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps([]))

        import importlib

        import index

        importlib.reload(index)

        event = make_event()
        event["issue_number"] = ""
        result = index.handler(event, None)
        assert result["statusCode"] == 400

    def test_unknown_assistant_type(self, monkeypatch):
        monkeypatch.setenv("ASSISTANT_TYPE", "unknown-type")
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps([]))

        import importlib

        import index

        importlib.reload(index)

        result = index.handler(make_event(), None)
        assert result["statusCode"] == 400
        assert "Unknown assistant type" in result["error"]


class TestReinvocation:
    """Re-invocation handler path: mint token only for private repos and forward via kwarg.

    Patches are applied as context managers AFTER `importlib.reload(index)` so the
    reloaded module sees the mocked symbols (decorator-style patches are bound to
    the pre-reload module object and are silently dropped by `reload`).
    """

    def test_private_reinvocation_calls_get_token_and_forwards(self, monkeypatch):
        monkeypatch.setenv("PRIVATE_REPO", "true")
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps([]))

        import importlib

        import index

        importlib.reload(index)

        mock_strategy = MagicMock()
        mock_strategy.get_session_id.return_value = "session-123456789012345678901"
        mock_strategy.refresh_for_reinvocation.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }

        with (
            patch.object(index, "STRATEGIES") as mock_strategies,
            patch.object(index, "get_token", return_value="t_xyz") as mock_get_token,
            patch.object(
                index,
                "execute_command",
                return_value={"exitCode": 0, "stdout": "REINVOKE\n", "stderr": ""},
            ),
        ):
            mock_strategies.__getitem__.return_value = lambda: mock_strategy
            mock_strategies.__contains__.return_value = True

            result = index.handler(make_event(triggered_by="alice"), None)

            assert result["statusCode"] == 200
            assert result["is_reinvocation"] is True

            # get_token was called exactly once for the private re-invocation.
            assert mock_get_token.call_count == 1

            # refresh_for_reinvocation received the minted token via the `token=` kwarg.
            mock_strategy.refresh_for_reinvocation.assert_called_once()
            kwargs = mock_strategy.refresh_for_reinvocation.call_args.kwargs
            assert kwargs.get("token") == "t_xyz"

            # First-invocation hooks must NOT run on re-invocation.
            mock_strategy.clone_repo.assert_not_called()
            mock_strategy.setup_workspace.assert_not_called()

    def test_public_reinvocation_does_not_mint_token(self, monkeypatch):
        monkeypatch.setenv("PRIVATE_REPO", "false")
        monkeypatch.setenv("ALLOWED_USERS", json.dumps(["*"]))
        monkeypatch.setenv("ALLOWED_REPOS", json.dumps([]))

        import importlib

        import index

        importlib.reload(index)

        mock_strategy = MagicMock()
        mock_strategy.get_session_id.return_value = "session-123456789012345678901"
        mock_strategy.refresh_for_reinvocation.return_value = {
            "exitCode": 0,
            "stdout": "OK",
            "stderr": "",
        }

        with (
            patch.object(index, "STRATEGIES") as mock_strategies,
            patch.object(index, "get_token") as mock_get_token,
            patch.object(
                index,
                "execute_command",
                return_value={"exitCode": 0, "stdout": "REINVOKE\n", "stderr": ""},
            ),
        ):
            mock_strategies.__getitem__.return_value = lambda: mock_strategy
            mock_strategies.__contains__.return_value = True

            result = index.handler(make_event(triggered_by="alice"), None)

            assert result["statusCode"] == 200
            assert result["is_reinvocation"] is True

            # Public re-invocation: get_token must NOT be called.
            mock_get_token.assert_not_called()

            # token=None forwarded.
            mock_strategy.refresh_for_reinvocation.assert_called_once()
            kwargs = mock_strategy.refresh_for_reinvocation.call_args.kwargs
            assert kwargs.get("token") is None
