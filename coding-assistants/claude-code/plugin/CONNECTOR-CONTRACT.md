# Connector Contract

Every project-management and source-control connector must expose these tools through the AgentCore Gateway. The gateway target name determines the agent-facing tool prefix: `mcp__gateway__<target>___<tool_name>`.

## Target: `project-management`

Agent-facing prefix: `mcp__gateway__project-management___`

| Tool | Purpose |
|------|---------|
| `issue_read` | Read issue metadata (title, body, labels, state) |
| `add_issue_comment` | Post a comment on an issue |
| `issue_write` | Set labels (replace-all semantics) |
| `get_authenticated_user` | Return the authenticated app/user identity |

## Target: `source-control`

Agent-facing prefix: `mcp__gateway__source-control___`

| Tool | Purpose |
|------|---------|
| `create_branch` | Create a branch from a ref |
| `push_files` | Push file contents to a branch (create commit) |
| `delete_file` | Delete a file on a branch |
| `create_pull_request` | Open a pull/merge request |
| `list_pull_requests` | List PRs (filterable by head branch) |
| `pull_request_read` | Read PR state, mergedAt, mergeStateStatus |
| `list_workflow_runs` | List CI workflow runs for a branch |
| `get_job_logs` | Fetch CI job logs |

## Adding a new connector

1. Create `project-management/<type>/mcp/` or `source-control/<type>/mcp/` with a Dockerfile + MCP server that exposes the tools above.
2. Add the `type` value to `sdlc-config.template.yaml` under `projectManagement.type` or `sourceControl.type`.
3. Add a CDK sub-construct in the corresponding `lib/nested/*-stack.ts` (behind the `type` guard).
4. The gateway registers the runtime under the same target name (`project-management` or `source-control`) regardless of which connector backs it — skills never change.

## v1: GitHub implementation

The GitHub connector uses `github-mcp-server` v1.1.1 which exposes tools with GitHub's native naming (`add_issue_comment`, `push_files`, etc.). These happen to match the contract above — no translation layer is needed. If a future connector's upstream uses different names, it must include a translation layer in its MCP wrapper.

The gateway target name is platform-agnostic (`source-control`, `project-management`). The connector's internal runtime name remains platform-specific (`github_code`, `github_issues`) for deployment uniqueness.
