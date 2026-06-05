# dev-claude pipeline — plugin architecture

This directory configures the `dev-claude` autonomous agent that turns a
well-specified GitHub issue into a pull request.

## Pipeline Flow

```mermaid
flowchart TD
    %% Entry
    START([GitHub issue gets agent:start label]) --> ORCH[Orchestrator fires<br/>model: sonnet]
    ORCH --> READ_CTX[Read .dev-claude/issue.json<br/>Read .dev-claude/project.json]
    READ_CTX --> LABEL_EXPLORE[Set label: agent:explore<br/>removes agent:start]

    %% Re-invocation detection
    LABEL_EXPLORE --> REINVOKE_CHECK{invocation-1/<br/>directory exists?}

    %% PR Verification gate (both paths)
    REINVOKE_CHECK -->|Yes: re-invocation| PR_VERIFY[PR-VERIFICATION GATE<br/>skill: pr-verification]
    REINVOKE_CHECK -->|No: first invocation| COMPLEXITY

    PR_VERIFY --> PR_VERIFY_DECISION{PR state?}
    PR_VERIFY_DECISION -->|mergedAt not null| EXIT_MERGED[label: agent:pr-completed<br/>EXIT]
    PR_VERIFY_DECISION -->|state=CLOSED, not merged| EXIT_ERROR_CLOSED[label: agent:error<br/>EXIT]
    PR_VERIFY_DECISION -->|state=OPEN| COMPLEXITY
    PR_VERIFY_DECISION -->|No PR found| COMPLEXITY

    %% Complexity decision
    COMPLEXITY{COMPLEXITY CHECK<br/>Simple vs Complex?}

    %% ===== PATH A — SIMPLE =====
    COMPLEXITY -->|SIMPLE| A_IMPL[Implement inline<br/>test, commit]
    A_IMPL --> A_PUSH[Push via MCP gateway]
    A_PUSH --> A_PR_CHECK{PR exists?}
    A_PR_CHECK -->|Yes: open| A_SKIP[Skip create]
    A_PR_CHECK -->|No| A_CREATE[create_pull_request]
    A_SKIP --> A_DONE[label: agent:pr-completed<br/>EXIT]
    A_CREATE --> A_DONE

    %% ===== PATH B — COMPLEX =====
    COMPLEXITY -->|COMPLEX| B1

    subgraph PathB [PATH B — Subagent Pipeline]
        B1[1. explore subagent<br/>→ explore.md, feedback.md]
        B1 --> B2[2. clarification skill<br/>→ questions.md]
        B2 --> B2_CHECK{ANSWERED?}
        B2_CHECK -->|No| B_HALT[label: agent:need-clarification<br/>HALT]
        B2_CHECK -->|Yes| B3[3. implement subagent<br/>→ commits code]
        B3 --> B4[4. critique subagent<br/>→ critique.md]
        B4 --> B4_CHECK{LGTM?}
        B4_CHECK -->|No| B5[5. implement subagent<br/>applies fixes]
        B4_CHECK -->|Yes| B6
        B5 --> B6[6. pr skill<br/>→ pushes, creates PR]
    end
    B6 --> EXIT_SUCCESS([label: agent:pr-completed<br/>EXIT])

    %% Error path
    A_IMPL -->|Fatal error| EXIT_ERROR[label: agent:error<br/>EXIT]
    B1 -->|Fatal error| EXIT_ERROR
    B3 -->|Fatal error| EXIT_ERROR

    classDef halt fill:#f9d71c,stroke:#333
    classDef error fill:#ff6b6b,stroke:#333
    classDef success fill:#6bff6b,stroke:#333
    class B_HALT halt
    class EXIT_ERROR,EXIT_ERROR_CLOSED error
    class EXIT_SUCCESS,EXIT_MERGED,A_DONE success
```

## Component Summary

| Name | Type | Tools | Model | Produces |
|------|------|-------|-------|----------|
| **orchestrator** | Skill (main thread) | All (Path A) or Agent-only (Path B) | sonnet | Labels, routing decisions |
| **explore** | Subagent | Read, Grep, Glob, Bash, Write, MCP issues | sonnet | `explore.md`, `feedback.md` |
| **clarification** | Skill (via Agent) | Write, MCP issues | sonnet | `questions.md` |
| **implement** | Subagent | Read, Write, Edit, Grep, Glob, Bash, MCP issues | sonnet | Source code, git commits |
| **critique** | Subagent | Read, Grep, Glob, Bash, Write, MCP issues | sonnet | `critique.md` |
| **pr** | Skill (via Agent) | Read, Bash, MCP code + issues | sonnet | `pr.md`, branch push, PR |
| **formatting** | Skill (reference) | — | — | Style rules (preloaded) |
| **git-staging** | Skill (reference) | — | — | Staging rules (preloaded) |
| **pr-verification** | Skill (reference) | — | — | Gate logic |

## Label State Machine

```
agent:start → agent:explore → agent:need-clarification (HALT, await human)
                   │                       │
                   │                 (re-invocation)
                   ▼                       ▼
             agent:implement → agent:critique → agent:pr-completed (terminal)

Any failure → agent:error (terminal)
```

Labels are always replace-all (only one active at a time). `agent:start` is user-only
and blocked by the `label-governance.sh` hook from being set by the agent.

## Artifacts

All artifacts live in `.dev-claude/current/` (symlinked to the latest `invocation-N/`).

| File | Written by | Read by |
|------|-----------|---------|
| `explore.md` | explore | clarification, implement, critique |
| `feedback.md` | explore (re-invocation) | implement |
| `questions.md` | clarification | orchestrator (ANSWERED check), implement |
| `critique.md` | critique | orchestrator (LGTM check), implement |
| `pr.md` | pr | (posted as issue comment) |

## Security Hooks

| Hook | Guards | Blocks |
|------|--------|--------|
| `label-governance.sh` | `issue_write` | Agent setting `agent:start` |
| `scope-guard.sh` | All MCP github calls | Wrong repo/issue/branch |
| `secret-guard.sh` | Write, Edit, push_files | Secrets in file content |
| `bash-guard.sh` | Bash | rm -rf, force push, exfil |
| `comment-guard.sh` | Comments, PR body | Content sanitization |

## MCP

`.mcp.json` connects Claude Code to the AgentCore Gateway which exposes
`github-code___*` and `github-issues___*` tool families. Bearer token is
injected by the Setup Lambda at runtime.

## Directory Layout

```
plugin/
├── agents/                 # Custom subagent definitions (context-isolated)
│   ├── explore.md
│   ├── implement.md
│   └── critique.md
├── skills/                 # Skills (loaded into agent context on demand)
│   ├── orchestrator/       # Main entry point — PATH A/B routing
│   ├── clarification/      # Binary halt gate
│   ├── pr/                 # Push branch + create PR
│   ├── formatting/         # Markdown rules (preloaded by subagents)
│   ├── git-staging/        # Staging rules (preloaded by implement)
│   └── pr-verification/    # PR existence check procedure
├── hooks/                  # PreToolUse security hooks
├── settings.json           # Model, denied tools, hook config
├── .claude-plugin/         # Plugin metadata
└── .mcp.json.template      # Gateway MCP connection
```
