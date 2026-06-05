# PR-Existence Verification

Run this procedure before any action that reports "already merged" or creates a PR.
Uses ONLY `state` + `mergedAt` for control flow; `mergeStateStatus` is diagnostic-only.

1. Resolve the branch name `feat/issue-{number}` from project.json.
2. Call `mcp__gateway__github-code___list_pull_requests` with `head={owner}:feat/issue-{number}` (REST-filtered fast path). If empty or errors, list open PRs and match `headRefName == feat/issue-{number}` client-side (fallback).
3. If a PR is found, call `mcp__gateway__github-code___pull_request_read` and read `state`, `mergedAt`, `mergeStateStatus`. Log `mergeStateStatus` as diagnostic context only — it MUST NOT drive any branching decision.
4. Four-way decision using ONLY `state` + `mergedAt`:
   - `mergedAt` not null → already merged. Set labels `["agent:pr-completed"]`, post comment, exit.
   - `state == OPEN` AND `mergedAt` null → open PR exists. Do NOT create a duplicate. Fall through to existing flow.
   - `state == CLOSED` AND `mergedAt` null → closed without merge. Set labels `["agent:error"]`, post comment, exit.
   - No PR found → MUST NOT report success. Continue to implement+pr flow.
