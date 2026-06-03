# GitHub MCP Toolsets

How each GitHub MCP runtime is scoped, how those scopes map to gateway target names, and which layers enforce that mapping. Read this before adding a new GitHub tool or broadening a runtime's toolset.

## Mapping table

| MCP runtime | CDK file (line) | `GITHUB_TOOLSETS` value | Gateway target name | Effective tool prefix the agent sees |
|---|---|---|---|---|
| project-management | [`lib/nested/project-management-stack.ts:44`](../lib/nested/project-management-stack.ts) | `issues` (default) | `github-issues` | `mcp__gateway__github-issues___*` |
| source-control | [`lib/nested/source-control-stack.ts:33,51`](../lib/nested/source-control-stack.ts) | `repos,pull_requests,context` (default) | `github-code` | `mcp__gateway__github-code___*` |

The gateway target names are registered in [`lib/sdlc-stack.ts:71`](../lib/sdlc-stack.ts) (`github-code`) and [`lib/sdlc-stack.ts:91`](../lib/sdlc-stack.ts) (`github-issues`), then handed to [`registerGatewayTarget()`](../lib/utils.ts) by [`lib/nested/gateway-stack.ts:44`](../lib/nested/gateway-stack.ts). The `mcp__gateway__<target>___*` prefix is the AgentCore Gateway naming convention — Claude Code sees one flat tool namespace and the gateway routes by prefix.

## Rationale per toolset assignment

### `issues` for project-management

The project-management runtime is the surface the orchestrator uses to triage work: read the issue body, post comments, set the `agent:*` label, transition state. None of that requires repo or pull-request access, and giving the runtime broader scope would let a prompt-injected comment escalate from the issues plane into branch creation or pushes. Scoping to `issues` keeps issue/comment/label/assignee operations on a runtime whose blast radius is one issue.

### `repos,pull_requests,context` for source-control

The source-control runtime does the actual code work: create branches, push files, open PRs, review diffs. `repos` covers branch and file operations, `pull_requests` covers PR creation and review, and `context` exposes identity tools that [`hooks/label-governance.sh`](../coding-assistants/claude-code/plugin/hooks/label-governance.sh) needs to know which principal triggered the run. These three are the minimum that lets the implement and PR stages do their jobs.

### Why neither runtime advertises `users` today

The agent never assigns issues to specific reviewers, never looks up team membership, and never resolves a username to an email — so `users` would be unused surface area. If a future use case (e.g., auto-assigning a PR to a CODEOWNERS reviewer) needed it, the cleanest place to add it is the source-control runtime via `sourceControl.github.toolsets: repos,pull_requests,context,users` in `sdlc-config.yaml`. The project-management runtime should stay scoped to `issues` even then — assignees are written through the issues toolset's `update_issue` call, not the users toolset.

## Enforcement chain

What blocks an unintended GitHub tool call, in the order the call traverses:

1. **CDK env var (`GITHUB_TOOLSETS`)** — Set per-runtime in [`lib/nested/project-management-stack.ts:44`](../lib/nested/project-management-stack.ts) and [`lib/nested/source-control-stack.ts:51`](../lib/nested/source-control-stack.ts), with the config-level default in [`sdlc-config.template.yaml`](../sdlc-config.template.yaml). The runtime container starts with this in its environment and never advertises a tool outside the scoped toolset.
2. **`github-mcp-server --toolsets`** — The Go binary reads `$GITHUB_TOOLSETS` in [`source-control/github/mcp/entrypoint.sh:18`](../source-control/github/mcp/entrypoint.sh) and [`project-management/github/mcp/entrypoint.sh:18`](../project-management/github/mcp/entrypoint.sh) and only registers MCP methods for the listed toolsets. Tools outside the list don't exist on the wire.
3. **Gateway target name routing** — Targets are registered with the names `github-code` and `github-issues` in [`lib/sdlc-stack.ts:71,91`](../lib/sdlc-stack.ts). The gateway routes a call by its name prefix (`mcp__gateway__github-code___*` → source-control runtime, `mcp__gateway__github-issues___*` → project-management runtime). A call whose prefix doesn't match a registered target is rejected before it hits any runtime.
4. **Plugin `permissions.deny`** — [`coding-assistants/claude-code/plugin/settings.json`](../coding-assistants/claude-code/plugin/settings.json) keeps a denylist for tools that the toolset advertises but the agent should never call (repo creation, force-merge, identity lookups, full-text issue search). Defense in depth — if a future toolset broadening accidentally advertises one of these, the plugin still blocks it.
5. **Runtime hooks** — [`hooks/scope-guard.sh`](../coding-assistants/claude-code/plugin/hooks/scope-guard.sh) and [`hooks/label-governance.sh`](../coding-assistants/claude-code/plugin/hooks/label-governance.sh) run as `PreToolUse` hooks (wired in [`coding-assistants/claude-code/plugin/settings.json`](../coding-assistants/claude-code/plugin/settings.json)) and enforce per-issue scoping (the call must target the owner/repo/issue/branch in `project.json`) and label rules (the agent cannot set `agent:start`). These fail closed: if `project.json` is missing, every MCP call is blocked.

## How to add a new tool or broaden a toolset

1. Decide which runtime owns the new tool — issue/comment/label/assignee work belongs on project-management; everything else on source-control.
2. Add the toolset name to that runtime's default in the CDK file ([`lib/nested/project-management-stack.ts:44`](../lib/nested/project-management-stack.ts) or [`lib/nested/source-control-stack.ts:51`](../lib/nested/source-control-stack.ts)) and to [`sdlc-config.template.yaml`](../sdlc-config.template.yaml).
3. Confirm the [`github-mcp-server`](https://github.com/github/github-mcp-server) version pinned in the runtime's Dockerfile actually advertises the toolset.
4. If the new toolset advertises tools the agent should not call, add their `mcp__gateway__<target>___<tool>` names to the `permissions.deny` array in [`coding-assistants/claude-code/plugin/settings.json`](../coding-assistants/claude-code/plugin/settings.json).
5. If the new tool needs per-issue scoping or other guardrails, extend [`hooks/scope-guard.sh`](../coding-assistants/claude-code/plugin/hooks/scope-guard.sh) — add tests in `test/hooks/test_hooks.sh`.
6. Run `npx cdk synth --quiet` and `bash test/hooks/test_hooks.sh` before deploying.
7. Deploy the affected runtime stack (`npx cdk deploy <project>-source-control` or `<project>-project-management`) followed by `<project>-gateway` to re-sync the target's tool list.

## Source-of-truth files

- [`lib/nested/project-management-stack.ts`](../lib/nested/project-management-stack.ts) — sets `GITHUB_TOOLSETS=issues` on the project-management runtime.
- [`lib/nested/source-control-stack.ts`](../lib/nested/source-control-stack.ts) — sets `GITHUB_TOOLSETS=repos,pull_requests,context` on the source-control runtime, both as the runtime env var and on the GitHub connector.
- [`lib/sdlc-stack.ts`](../lib/sdlc-stack.ts) — declares the `github-code` and `github-issues` gateway target names that produce the agent-facing tool prefixes.
- [`lib/nested/gateway-stack.ts`](../lib/nested/gateway-stack.ts) — registers each target on the gateway via `registerGatewayTarget()`.
- [`lib/utils.ts`](../lib/utils.ts) — defines `registerGatewayTarget()` and `buildRuntimeEndpoint()`.
- [`sdlc-config.template.yaml`](../sdlc-config.template.yaml) — config-level defaults for `sourceControl.github.toolsets` and `projectManagement.github.toolsets`.
- [`source-control/github/mcp/entrypoint.sh`](../source-control/github/mcp/entrypoint.sh), [`project-management/github/mcp/entrypoint.sh`](../project-management/github/mcp/entrypoint.sh) — pass `$GITHUB_TOOLSETS` through to `github-mcp-server --toolsets`.
- [`coding-assistants/claude-code/plugin/settings.json`](../coding-assistants/claude-code/plugin/settings.json) — `permissions.deny` blocklist and `PreToolUse` hook wiring for `mcp__gateway__github-*___*` matchers.
- [`coding-assistants/claude-code/plugin/hooks/scope-guard.sh`](../coding-assistants/claude-code/plugin/hooks/scope-guard.sh), [`coding-assistants/claude-code/plugin/hooks/label-governance.sh`](../coding-assistants/claude-code/plugin/hooks/label-governance.sh) — runtime enforcement of per-issue scope and label rules.
