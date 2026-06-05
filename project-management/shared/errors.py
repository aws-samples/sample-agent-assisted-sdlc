# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Named exception classes for the SDLC pipeline.

Five narrow categories, each raised at exactly one layer:

* ``WorkspaceSetupError`` — assistant workspace setup (plugin copy,
  workspace materialisation) failed.
* ``RuntimeCommandError`` — the AgentCore HTTP layer raised. Scoped to
  ``requests.RequestException`` propagation only; a non-zero command
  exit code is still surfaced as a returned dict, not as an exception.
* ``TokenError`` — GitHub App installation token minting failed
  (Secrets Manager / JWT / GitHub API).
* ``LocalOnlyBranchError`` — re-invocation failure mode A: the working
  branch exists locally with commits beyond ``origin/main`` but is
  absent from origin (divergence CONFIRMED). Fail-closed: a push of a
  branch in this state would be unreviewable, so the refresh aborts.
* ``BranchProbeError`` — the branch-state probe itself failed or was
  ambiguous (non-zero exit on ``git ls-remote`` or ``git log``, or an
  ``exitCode == 0`` empty result that cannot be distinguished from
  AgentCore dropped output per issue #37). Branch state could not be
  determined; fail-closed.

Callsites that wrap an underlying transport/JWT failure use
``raise X(...) from e`` so the original cause is preserved on the
exception chain. The branch-probe categories (``LocalOnlyBranchError``,
``BranchProbeError``) are raised standalone from inspected command
results, not from a caught exception.
"""


class WorkspaceSetupError(Exception):
    """Raised when assistant workspace setup fails."""


class RuntimeCommandError(Exception):
    """Raised when the AgentCore HTTP transport raises a ``RequestException``."""


class TokenError(Exception):
    """Raised when GitHub App installation token minting fails."""


class LocalOnlyBranchError(Exception):
    """Raised when the working branch has local-only commits absent from origin."""


class BranchProbeError(Exception):
    """Raised when the branch-state probe failed or returned ambiguous output."""
