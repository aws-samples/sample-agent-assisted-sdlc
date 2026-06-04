# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Named exception classes for the SDLC pipeline.

Three narrow categories, each raised at exactly one layer:

* ``WorkspaceSetupError`` — assistant workspace setup (plugin copy,
  workspace materialisation) failed.
* ``RuntimeCommandError`` — the AgentCore HTTP layer raised. Scoped to
  ``requests.RequestException`` propagation only; a non-zero command
  exit code is still surfaced as a returned dict, not as an exception.
* ``TokenError`` — GitHub App installation token minting failed
  (Secrets Manager / JWT / GitHub API).

Each callsite uses ``raise X(...) from e`` so the original cause is
preserved on the exception chain.
"""


class WorkspaceSetupError(Exception):
    """Raised when assistant workspace setup fails."""


class RuntimeCommandError(Exception):
    """Raised when the AgentCore HTTP transport raises a ``RequestException``."""


class TokenError(Exception):
    """Raised when GitHub App installation token minting fails."""
