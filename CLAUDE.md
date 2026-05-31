# Agent-Assisted SDLC

Agentic SDLC platform on Amazon Bedrock AgentCore. GitHub issues → autonomous coding → pull requests.

## Commands

```bash
npm install                          # Install CDK dependencies
npx cdk synth --quiet                # Validate TypeScript + cdk-nag (run before every commit)
npx cdk deploy --all                 # Deploy all stacks
npx cdk deploy {project}-assistant   # Deploy just the coding assistant stack
npx cdk ls                           # List stacks
npm test                             # Jest snapshot tests
```


## Architecture

6 CDK stacks deployed in order: Infra → SourceControl → ProjectManagement → DeveloperMcp → Gateway → Assistant. Config in `sdlc-config.yaml` (copy from `sdlc-config.template.yaml`). Stack names prefixed with `project:` field from config.

Key paths:
- `lib/nested/*-stack.ts` — stack definitions
- `lib/constructs/` — reusable CDK constructs
- `lib/config.ts` — config schema + `getAssistantDir()` mapping
- `coding-assistants/{claude-code,kiro,codex}/` — container images + plugins
- `project-management/shared/assistants/` — per-assistant invocation strategies
- `gateway/developer-mcp-servers/` — developer tool MCP servers (FastMCP)

## Languages by Directory

| Directory | Language | Package Manager |
|-----------|----------|-----------------|
| `lib/`, `bin/` | TypeScript (strict, NodeNext) | npm |
| `gateway/gateway-iam-proxy/` | Node.js (ESM) | npm |
| `project-management/shared/` | Python 3.12 | pip (requirements.txt) |
| `project-management/github/mcp/` | Python 3.12 + Go (github-mcp-server binary) | uv |
| `source-control/github/mcp/` | Python 3.12 + Go | uv |
| `gateway/developer-mcp-servers/` | Python 3.12 (FastMCP) | uv |
| `coding-assistants/*/runtime/` | Python 3.12 (FastAPI health server) | uv or pip |
| `coding-assistants/claude-code/plugin/hooks/` | Bash | — |
| `test-scripts/` | Bash | — |

## Conventions

- License: Apache-2.0. All Python files have `# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.` + `# SPDX-License-Identifier: Apache-2.0` header.
- CDK constructs use cdk-nag (AWS Solutions checks). Suppress with `NagSuppressions.addResourceSuppressions()` and a justification string.
- Python formatting: no specific formatter enforced. Follow existing style in each file.
- TypeScript: strict mode, no implicit any.
- Dockerfiles: pin all dependencies (`pip install pkg==x.y.z`, `npm install -g pkg@x.y.z`, `git clone --branch vX.Y.Z`).
- MCP servers use FastMCP with streamable-http transport on port 8000.
- Health servers use FastAPI on port 8080 (`/ping`, `/health`, `/invocations`).

## Security Rules

- Never use `git add -A` in skills or scripts — explicitly stage files to avoid committing orchestrator infrastructure (`.dev-claude/`, `hooks/`, `skills/`, `.claude/`, `.mcp.json`, `settings.json`).
- Never set the `agent:start` label from code — it triggers infinite re-invocation.
- All user-controlled input (issue titles, repo names) must be base64-encoded before passing through shell commands. See `assistants/base.py` for the pattern.
- Validate `owner`/`repo` with `_validate_identifier()` before use in any command.
- Scope guard blocks operations on wrong repo/issue/branch. If `project.json` is missing, all MCP calls are blocked (fail-closed).
- Secrets (AWS keys, private keys, GitHub/OpenAI/Slack tokens) in file writes are blocked by `secret-guard.sh`.

## Anti-Patterns (Do NOT)

- Do not put secrets in code (`.pem` files, API keys). Use Secrets Manager.
- Do not use `shell=True` in Python subprocess calls.
- Do not hardcode AWS account IDs or region — read from config or environment.
- Do not add `cdk.out*/`, `cdk.context.json`, `.threatmodel/`, or `security-scans/` to git.
- Do not use `curl ... | bash` without downloading to a file first (supply chain risk).
- Do not expose tokens in process arguments — use credential helpers or temp files.
- Do not deploy with `authorizerType: NONE` on the gateway in production.
- Do not make the OIDC trust policy `repo:*` — always set `allowedRepos` in config.

## Adding a Developer MCP Server (simplest extension)

1. Create `gateway/developer-mcp-servers/<name>/` with `main.py`, `Dockerfile`, `pyproject.toml`, `uv.lock`
2. Add to `sdlc-config.yaml` under `gateway.developerMcpServers`
3. `npx cdk deploy {project}-developer-mcp`

## Adding a Coding Assistant

1. Create `coding-assistants/<name>/runtime/` (Dockerfile + main.py) and `plugin/` (instruction file + `.mcp.json.template`)
2. Add to `ASSISTANT_TO_DIR` in `lib/config.ts`
3. Create `project-management/shared/assistants/<name>.py` with `run_pipeline()`
4. Register in `project-management/shared/assistants/__init__.py`

## Key Config Fields

```yaml
codingAssistant.type: claude-code | kiro | codex
sourceControl.github.allowedRepos: "myorg/*"  # CRITICAL: restricts OIDC trust
gateway.authorizerType: AWS_IAM               # Never use NONE in production
codingAssistant.maxLifetime: 2400             # Must be < GitHub token expiry (3600)
```

## Tests

```bash
npm test                                              # TypeScript (12 tests): config loading, getAssistantDir
cd project-management/shared && python3 -m pytest tests/ -v  # Python (29 tests): validation, session ID, clone, workspace
bash test/hooks/test_hooks.sh                          # Bash hooks (43 tests): all 4 security hooks
```

**Coverage:**
- `_validate_identifier`: 14 cases (valid, empty, special chars, path traversal, unicode, injection)
- `get_session_id`: 6 cases (normal, short/long names, padding, zero, overflow)
- `clone_repo`/`clone_private_repo`: 6 cases (public, private, token cleanup, validation)
- `setup_workspace`: 3 cases (base64 encoding, invocation dir)
- `label-governance.sh`: 7 cases (default/custom prefix, exact match)
- `bash-guard.sh`: 17 cases (rm, force push, env dumps, exfil, redirects)
- `secret-guard.sh`: 10 cases (AWS keys, PEM, GitHub/OpenAI/Slack tokens)
- `scope-guard.sh`: 8 cases (owner/repo/issue/branch validation, fail-closed)
- Config TypeScript: 12 cases (loadConfig, getAssistantDir, type validation)

**Known bug:** `bash-guard.sh` redirect guard uses `(?!)` negative lookahead unsupported by `grep -E`. The write-outside-workspace check never fires. Tracked for fix.

## Important Files & Documentation

| File | Purpose |
|------|---------|
| `README.md` | Architecture, quick start, deployment guide |
| `CONTRIBUTING.md` | Development setup, extension points, CDK architecture, PR guidelines |
| `SECURITY-PRACTICES.md` | Threat model (12 threats), security hooks, shared responsibility |
| `SCAN-FINDINGS.md` | Security scan justifications and remediation tracking |
| `CODE_OF_CONDUCT.md` | Amazon Open Source Code of Conduct |
| `sdlc-config.template.yaml` | Full config reference with inline docs |
| `coding-assistants/README.md` | How each assistant works, security model |
| `coding-assistants/claude-code/obs.md` | Observability: OTel events, CloudWatch queries, dashboard |
| `coding-assistants/claude-code/plugin/README.md` | Plugin pipeline documentation |
| `coding-assistants/claude-code/plugin/skills/orchestrator/SKILL.md` | Main orchestrator logic (complexity routing) |
| `gateway/README.md` | Gateway architecture, IAM proxy, MCP routing |
| `project-management/github/connector/README.md` | GitHub connector: workflow, Lambda, token generation |
| `source-control/github/README.md` | GitHub MCP server: code operations, credential brokering |
| `test-scripts/README.md` | Test script usage and prerequisites |

## AWS Documentation Reference

### Amazon Bedrock AgentCore Runtime
- [Overview: Host agents with AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
- [How it works (microVM, protocols, auth)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
- [Isolated sessions for agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)
- [Lifecycle settings (idle timeout, max lifetime)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [Filesystem configurations (S3 Files, session storage, EFS)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html)
- [Execute shell commands in sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-execute-command.html)
- [Stop a running session](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-stop-session.html)
- [MCP protocol contract (container requirements)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html)
- [VPC configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [Security best practices](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html)
- [Troubleshooting](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html)

### Amazon Bedrock AgentCore Gateway
- [Core concepts (targets, tool types, routing)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-core-concepts.html)
- [Gateway features (semantic search, streaming, encryption)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-features.html)
- [Set up a gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building.html)
- [MCP targets (aggregation, tool sync, OAuth)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-targets-mcp.html)
- [MCP server targets (SigV4, listing modes)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- [Runtime targets (path routing, SSE)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html)
- [Supported target types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-supported-targets.html)
- [List available tools](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-list.html)

### Observability
- [Add observability to AgentCore resources](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [AgentCore and AWS X-Ray](https://docs.aws.amazon.com/xray/latest/devguide/xray-services-agentcore.html)

### API Reference
- [S3FilesAccessPointConfiguration](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_S3FilesAccessPointConfiguration.html)
- [FilesystemConfiguration](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_FilesystemConfiguration.html)
- [StopRuntimeSession](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_StopRuntimeSession.html)
