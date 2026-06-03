# dev-claude pipeline — target repo configuration

This directory configures the `dev-claude` autonomous agent that turns a
well-specified GitHub issue into a pull request. See
`dev-claude-v1-proposal.md` in the orchestrator repo for the full design.

## Pipeline (5 subagents, spawned by Claude Code on a `claude -p` run)

1. `explore-agent`   → writes `./.dev-claude/explore.md`
2. `qa-agent`        → writes `./.dev-claude/questions.md` (halts if ambiguous)
3. `implement-agent` → creates `feat/issue-{N}`, commits implementation
4. `critique-agent`  → writes `./.dev-claude/critique.md`
5. `implement-agent` (second pass) → applies critique
6. `pr-agent`        → pushes branch, opens PR, sets `state:pr-created`

Stages are skipped when their artifact already exists (artifact-based resume).
Artifact directory `./.dev-claude/` is gitignored.

## MCP

`.mcp.json` points Claude Code at the AgentCore Gateway. The Gateway exposes
`GitHub___*` tools which Claude Code addresses as `mcp__gateway__GitHub___*`.
Bearer token is injected by Lambda at invoke time via `${GATEWAY_BEARER}`.

For the runtime → toolset → gateway target → tool-prefix mapping and its enforcement chain, see [`SECURITY-PRACTICES.md` § GitHub MCP toolset scoping](../../../SECURITY-PRACTICES.md#github-mcp-toolset-scoping).

## Labels (set by subagents via MCP, never by humans)

- `stage:exploring` / `stage:implementing`
- `state:awaiting-input` / `state:pr-created` / `state:failed`

Invariant: always `set_labels` (replace-all), never `add_labels`.
