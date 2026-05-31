## What

<!-- One-line summary of what this PR does -->

## Why

<!-- Link to issue or explain the motivation -->
Closes #

## How

<!-- Key implementation decisions, patterns used, or trade-offs made -->

## Testing

<!-- How you verified this works -->
- [ ] `npx cdk synth --quiet` passes
- [ ] Existing tests pass (`npm test`)
- [ ] Tested against a live deployment (if applicable, AI agent should not test against live)

## Security Checklist

<!-- Check all that apply -->
- [ ] No secrets, API keys, or credentials in code
- [ ] No new `shell=True` or unsanitized user input in shell commands
- [ ] Dependencies pinned to exact versions (if added/updated)
- [ ] IAM policies follow least privilege (if modified)
- [ ] New MCP tools are scope-guarded (if added)

## Scope

<!-- What files/areas does this touch? Helps reviewers focus. -->
- [ ] CDK infrastructure (`lib/`)
- [ ] Coding assistant (plugin, skills, hooks)
- [ ] MCP servers (gateway, source-control, project-management)
- [ ] Lambda handlers
- [ ] Documentation only
- [ ] CI/config only
