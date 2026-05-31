# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""CloudFormation / CDK Documentation MCP Server.

Provides search + read tools against AWS CloudFormation + CDK docs, plus a
cfn-lint-based template validator. Patterned after awslabs/aws-iac-mcp-server
but trimmed to what this project needs.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CfnDocsMCP")
from typing import List, Optional

import httpx
import markdownify
from bs4 import BeautifulSoup
from fastmcp import FastMCP
from pydantic import BaseModel

SEARCH_API_URL = "https://proxy.search.docs.aws.com/search"
SESSION_UUID = str(uuid.uuid4())
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 "
    "ModelContextProtocol/0.1.0 (AWS IaC Documentation Server)"
)
DOCS_DOMAIN_RE = re.compile(r"^https?://docs\.aws\.amazon\.com/.+\.html$")

# Domain hints — CFN lives under docs.aws.amazon.com/AWSCloudFormation and
# the CDK API reference under docs.aws.amazon.com/cdk/api.
CFN_DOMAINS = [
    {"key": "aws-docs-search-product", "value": "AWS CloudFormation"},
]
CDK_DOMAINS: list = []  # product taxonomy doesn't have a CDK entry; search broadly

mcp = FastMCP("CfnDocsMCP")


class SearchResult(BaseModel):
    rank_order: int
    url: str
    title: str
    context: Optional[str] = None


def _html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return markdownify.markdownify(str(main), heading_style="ATX").strip()


async def _search(phrase: str, limit: int, filters: list) -> List[SearchResult]:
    body = {
        "textQuery": {"input": phrase},
        "contextAttributes": [
            {"key": "domain", "value": "docs.aws.amazon.com"},
            *filters,
        ],
        "acceptSuggestionBody": "RawText",
        "locales": ["en_us"],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{SEARCH_API_URL}?session={SESSION_UUID}",
            json=body,
            headers={"User-Agent": USER_AGENT, "X-MCP-Session-Id": SESSION_UUID},
        )
        r.raise_for_status()
        data = r.json()

    out: List[SearchResult] = []
    for i, s in enumerate(data.get("suggestions", [])[:limit]):
        t = s.get("textExcerptSuggestion") or {}
        meta = t.get("metadata", {}) or {}
        ctx = (
            meta.get("seo_abstract")
            or meta.get("abstract")
            or t.get("summary")
            or t.get("suggestionBody")
        )
        out.append(
            SearchResult(
                rank_order=i + 1,
                url=t.get("link", ""),
                title=t.get("title", ""),
                context=ctx,
            )
        )
    return out


@mcp.tool()
async def search_cloudformation_documentation(
    query: str, limit: int = 10
) -> List[SearchResult]:
    """Search AWS CloudFormation docs (resource types, template syntax, properties)."""
    return await _search(query, limit, CFN_DOMAINS)


@mcp.tool()
async def search_cdk_documentation(query: str, limit: int = 10) -> List[SearchResult]:
    """Search AWS CDK docs (constructs, APIs, best practices).

    CDK isn't a distinct product in the docs search taxonomy, so we search broadly
    and prepend "AWS CDK" to the query to improve recall.
    """
    return await _search(f"AWS CDK {query}", limit, CDK_DOMAINS)


@mcp.tool()
async def read_iac_documentation_page(
    url: str, max_length: int = 5000, start_index: int = 0
) -> str:
    """Fetch a CloudFormation or CDK docs page (docs.aws.amazon.com/...html) as markdown."""
    if not DOCS_DOMAIN_RE.match(url):
        raise ValueError("URL must be on docs.aws.amazon.com and end with .html")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        md = _html_to_markdown(r.text)

    chunk = md[start_index : start_index + max_length]
    truncated = start_index + max_length < len(md)
    suffix = (
        f"\n\n---\n[truncated — total {len(md)} chars, "
        f"call again with start_index={start_index + max_length}]"
        if truncated
        else ""
    )
    return chunk + suffix


@mcp.tool()
def validate_cloudformation_template(
    template_content: str,
    regions: Optional[List[str]] = None,
    ignore_checks: Optional[List[str]] = None,
) -> str:
    """Validate a CloudFormation template (YAML or JSON) with cfn-lint.

    Returns JSON { valid, error_count, warning_count, info_count, issues:[...] }.
    """
    import os
    import subprocess
    import tempfile

    suffix = ".json" if template_content.lstrip().startswith("{") else ".yaml"
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
        f.write(template_content)
        path = f.name

    try:
        cmd = ["cfn-lint", "--format", "json", path]
        if regions:
            for reg in regions:
                cmd += ["--regions", reg]
        if ignore_checks:
            for c in ignore_checks:
                cmd += ["--ignore-checks", c]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        raw = proc.stdout.strip() or "[]"
        try:
            issues = json.loads(raw)
        except json.JSONDecodeError:
            issues = []
        errors = [i for i in issues if i.get("Level") == "Error"]
        warnings = [i for i in issues if i.get("Level") == "Warning"]
        infos = [i for i in issues if i.get("Level") == "Informational"]
        return json.dumps(
            {
                "valid": len(errors) == 0,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "info_count": len(infos),
                "issues": issues,
                "stderr": proc.stderr,
            },
            indent=2,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    from starlette.middleware.base import BaseHTTPMiddleware

    app = mcp.http_app(stateless_http=False)

    class LogHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            logger.info(
                f"[{request.method} {request.url.path}] Headers: {dict(request.headers)}"
            )
            return await call_next(request)

    app.add_middleware(LogHeadersMiddleware)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
