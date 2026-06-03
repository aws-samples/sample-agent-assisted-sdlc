# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for source-control GitHub MCP wrapper — fail-closed GITHUB_TOOLSETS check."""

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    """Load main.py via importlib to avoid triggering heavy imports at collection time."""
    spec = importlib.util.spec_from_file_location(
        "sc_mcp_main",
        Path(__file__).parent.parent / "main.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRequiredToolsets:
    def test_unset_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOOLSETS", raising=False)
        module = _load_module()
        with pytest.raises(RuntimeError, match="GITHUB_TOOLSETS env var is unset or empty"):
            module._required_toolsets()

    def test_empty_string_raises(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOOLSETS", "")
        module = _load_module()
        with pytest.raises(RuntimeError, match="GITHUB_TOOLSETS env var is unset or empty"):
            module._required_toolsets()
