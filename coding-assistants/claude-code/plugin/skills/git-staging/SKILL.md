---
name: git-staging
description: Git staging rules that prevent committing orchestrator infrastructure files
---

NEVER run `git add -A` or `git add .`. The working tree contains orchestrator infrastructure that MUST NOT be committed:
`.dev-claude/`, `hooks/`, `skills/`, `.claude/`, `.claude-plugin/`, `settings.json`, `.mcp.json`, `agentcore-test.txt`

Stage explicitly using only the file paths you created or modified for the issue.

Before each commit:
1. `git status --short` — confirm only in-scope files are listed
2. `git diff --cached --stat` — confirm the staged set matches the issue scope
3. If anything outside scope is staged, `git restore --staged <path>` before committing
