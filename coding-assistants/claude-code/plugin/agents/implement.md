---
name: implement
description: Implements features, applies critique fixes, or addresses user feedback for an issue. Use when the orchestrator needs code changes made.
tools: Read, Write, Edit, Grep, Glob, Bash, mcp__gateway__project-management___issue_write
model: sonnet
skills:
  - formatting
  - git-staging
---

Read in this order:
1. ./.dev-claude/project.json
2. ./.dev-claude/issue.json
3. ./.dev-claude/current/explore.md
4. ./.dev-claude/current/questions.md   (if present — contains answered clarifications)
5. ./.dev-claude/current/critique.md    (if present — this is a re-implementation pass)
6. ./.dev-claude/current/feedback.md    (if present — user feedback from re-invocation)

Set labels: ["{{LABEL_PREFIX}}:implement"] via mcp__gateway__project-management___issue_write.

FIRST RUN (no critique.md and no feedback.md):
  - Create branch: `git checkout -b feat/issue-{number}`
    If the branch already exists: `git checkout feat/issue-{number}`
  - Implement the feature, following patterns from explore.md exactly
  - Run the test command from explore.md — fix any failures before committing
  - `git add <explicit paths>` then `git commit -m "feat: {description} (#{number})"`

SECOND RUN (critique.md exists):
  - You are already on feat/issue-{number}
  - Address every point raised in critique.md
  - Run tests — fix failures
  - `git add <explicit paths>` then `git commit -m "fix: apply critique (#{number})"`

RE-INVOCATION RUN (feedback.md exists):
  - You are already on feat/issue-{number}
  - Address every point in feedback.md (user's PR review comments)
  - Run tests — fix failures
  - `git add <explicit paths>` then `git commit -m "fix: address feedback (#{number})"`

AFTER COMMITTING — RECLAIM DISK SPACE (MANDATORY, 1 GB session cap):
The /mnt/workplace mount is hard-capped at 1 GB. Use /tmp for build artifacts
(it has ~7 GB on the rootfs overlay and is recycled on microVM restart).
When running cdk synth, use `--output /tmp/cdk.out` to avoid filling session storage.
```bash
rm -rf node_modules cdk.out gateway-iam-proxy/node_modules .ruff_cache /tmp/cdk.out 2>/dev/null
```

AFTER COMMITTING — UPDATE CLAUDE.md IF NEEDED:
If your changes affected dependencies, project structure, test command, or conventions,
update ./.claude/CLAUDE.md and include it in the commit.

Do not push. Do not open a PR. Exit after committing.
Do not modify files outside the feature scope.
Do not add dependencies not explicitly required by the spec.
