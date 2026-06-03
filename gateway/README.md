# Gateway

> [!IMPORTANT]
> This sample is in preview and under active development.

Contains the AgentCore Gateway IAM proxy and developer MCP servers.

For the GitHub MCP runtime → toolset → gateway target mapping and its enforcement chain, see [`SECURITY-PRACTICES.md` § GitHub MCP toolset scoping](../SECURITY-PRACTICES.md#github-mcp-toolset-scoping).

## Components

| Directory | Purpose | Extension Point? |
|-----------|---------|:---:|
| [`gateway-iam-proxy/`](./gateway-iam-proxy/) | Node.js stdio-to-StreamableHTTP bridge with SigV4 signing | No |
| [`developer-mcp-servers/`](./developer-mcp-servers/) | Additional tool servers registered on the gateway | **Yes** |

## Developer MCP Servers

Extra tools the coding assistant can use during execution. These are the simplest extension point in the project — a single Python file, a Dockerfile, and a config entry.

### Existing Servers

| Server | Directory | Tools |
|--------|-----------|-------|
| AWS Docs | [`developer-mcp-servers/aws-docs/`](./developer-mcp-servers/aws-docs/) | `search_documentation`, `read_documentation`, `recommend` |
| CFN Docs | [`developer-mcp-servers/cfn-docs/`](./developer-mcp-servers/cfn-docs/) | `search_cfn_docs`, `validate_template`, `read_cdk_docs` |

### Adding a New Developer MCP Server

#### Step 1: Create the directory

```
gateway/developer-mcp-servers/<name>/
├── main.py              # FastMCP server (all tools in one file)
├── Dockerfile           # Container image
├── pyproject.toml       # Dependencies
└── uv.lock              # Locked versions (run: uv lock)
```

#### Step 2: Implement tools with FastMCP

Here's how [`aws-docs/main.py`](./developer-mcp-servers/aws-docs/main.py) defines tools:

```python
from fastmcp import FastMCP

mcp = FastMCP("MyServer")


@mcp.tool()
async def search_docs(query: str, limit: int = 10) -> list[dict]:
    """Search documentation by keyword."""
    # Your implementation here
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.example.com/search", params={"q": query})
        return resp.json()["results"][:limit]


@mcp.tool()
async def read_page(url: str) -> str:
    """Fetch and return a documentation page as markdown."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return convert_html_to_markdown(resp.text)


if __name__ == "__main__":
    import uvicorn
    app = mcp.http_app(stateless_http=False)
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

#### Step 3: Use the standard Dockerfile

All developer MCP servers use the same Dockerfile pattern:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 1000 bedrock_agentcore

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=bedrock_agentcore:bedrock_agentcore . .
RUN uv sync --frozen --no-dev

USER bedrock_agentcore

# AgentCore Runtime service contract ports
EXPOSE 8080 8000 9000

CMD ["opentelemetry-instrument", "python", "-m", "main"]
```

#### Step 4: Register in config

Add your server to `sdlc-config.yaml`:

```yaml
gateway:
  developerMcpServers:
    - name: aws-docs
      source: ./gateway/developer-mcp-servers/aws-docs
    - name: cfn-docs
      source: ./gateway/developer-mcp-servers/cfn-docs
    - name: my-server                                    # Add here
      source: ./gateway/developer-mcp-servers/my-server
```

**That's it.** No CDK changes needed. The developer MCP stack reads from config and auto-deploys all listed servers as gateway targets.

#### Step 5: Deploy

```bash
npx cdk deploy <project>-developer-mcp
```

### Local Development

```bash
cd gateway/developer-mcp-servers/my-server
uv sync
uv run python main.py
# Server runs on http://localhost:8000
# Test with: curl -X POST http://localhost:8000/mcp -d '{"method":"tools/list"}'
```

## Gateway IAM Proxy

The [`gateway-iam-proxy/`](./gateway-iam-proxy/) is a Node.js process that runs inside the coding assistant container. It bridges Claude Code's stdio MCP transport to the gateway's StreamableHTTP endpoint, signing all requests with SigV4 using the container's IAM role. This is **not** an extension point — it's internal infrastructure.
