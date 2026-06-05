---
name: pr
description: Pushes the branch and creates the pull request
model: sonnet
permissionMode: dontAsk
---

Read:
- ./.dev-claude/project.json (owner, repo, issue_number)
- ./.dev-claude/issue.json (issue title + number)
- ./.dev-claude/current/critique.md (was there a critique?)
- Run `git log main..HEAD --oneline` (commits made on this branch)

STEP 1: Push the branch via the MCP gateway (NOT direct `git push`).

The runtime container has no HTTPS credentials for the remote, so direct
`git push` fails. Instead, enumerate the files this branch changed
relative to `main` and push their contents through
`mcp__gateway__github-code___push_files` (which uses the GitHub App token).

  1. Run `git diff --name-status main..HEAD` to list every changed path
     with its status (A=added, M=modified, D=deleted, R=renamed).
  2. Run `git status --short` to confirm the working tree is clean
     (everything is committed). If it is not, STOP — the implement-agent
     left work uncommitted; do not push partial state.
  3. For every A/M/R path, read the file content (`Read` tool) and add it
     to the `files` array in the push_files call. For D paths, delete via
     `mcp__gateway__github-code___delete_file` per path.
  4. Call `mcp__gateway__github-code___push_files`:
       owner, repo, branch=feat/issue-{number}
       message: "feat: {issue title} (#{number})" (or "fix: ..." on
                second pass / re-invocation, matching the commit message
                style implement-agent used)
       files: array of {path, content} for every A/M/R path
  5. If push_files reports 422 "branch does not exist", first call
     `mcp__gateway__github-code___create_branch` with branch=feat/issue-{number}
     and ref="main", then retry push_files.

STEP 2: Write ./.dev-claude/current/pr.md summarising what was built. Then post pr.md content
as a comment on the issue via mcp__gateway__github-issues___add_issue_comment.
Prefix with `### PR Summary\n\n`.

Follow the formatting skill for all markdown output.

STEP 2b: PR-existence verification (defense-in-depth, late gate).
Follow the pr-verification skill procedure.
If open PR exists → skip STEP 3, proceed to STEP 4. If no PR → STEP 3.

STEP 3: Call mcp__gateway__github-code___create_pull_request:
  owner and repo from project.json
  title: "feat: {issue title} (#{number})"
  head: feat/issue-{number}
  base: main
  draft: false
  body:
    ## What
    One paragraph describing what was built.

    ## Why
    Closes #{number}

    ## How
    Key implementation decisions and patterns used.

    ## Testing
    How to verify the change works.

  CRITICAL — the body must be a plain markdown string. Do NOT use:
    - shell substitution like $(...) or $(cat <<EOF ... EOF)
    - heredoc syntax (<<EOF, <<'EOF')
    - command chaining (&&, ;)
  WAF blocks these patterns with HTML 403. If you see that, simplify and retry.

STEP 4: Set labels: ["agent:pr-completed"] via mcp__gateway__github-issues___issue_write.

STEP 5: Post invocation summary as a comment on the issue:
```
### Invocation Summary

| Metric | Value |
|--------|-------|
| Model | claude-opus-4-7 |
| Stages completed | explore → implement → critique → PR |

_Closes #{number}_
```

On push/PR failure: retry once. On second failure, set labels: ["agent:error"]
and post an error comment via mcp__gateway__github-issues___add_issue_comment.

Exit cleanly. `agent:pr-completed` is the terminal success state.
