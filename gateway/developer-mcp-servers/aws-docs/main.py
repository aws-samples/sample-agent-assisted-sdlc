# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""AWS Documentation MCP Server.

Self-contained MCP server that wraps the public AWS docs search, read, and
recommendation APIs. Patterned after awslabs/aws-documentation-mcp-server but
reduced to a single file so it fits the AgentCore Runtime container layout.
"""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

import httpx
import markdownify
from bs4 import BeautifulSoup
from fastmcp import FastMCP
from log import get_logger
from pydantic import BaseModel

logger = get_logger("AWSDocsMCP")

SEARCH_API_URL = "https://proxy.search.docs.aws.com/search"
RECOMMENDATIONS_API_URL = (
    "https://contentrecs-api.docs.aws.amazon.com/v1/recommendations"
)
SESSION_UUID = str(uuid.uuid4())
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 "
    "ModelContextProtocol/0.1.0 (AWS Documentation Server)"
)
DOCS_DOMAIN_RE = re.compile(r"^https?://docs\.aws\.amazon\.com/.+\.html$")

mcp = FastMCP("AWSDocsMCP")


class SearchResult(BaseModel):
    rank_order: int
    url: str
    title: str
    context: Optional[str] = None


class RecommendResult(BaseModel):
    url: str
    title: str
    context: Optional[str] = None


def _html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return markdownify.markdownify(str(main), heading_style="ATX").strip()


@mcp.tool()
async def search_documentation(
    search_phrase: str,
    limit: int = 10,
) -> List[SearchResult]:
    """Search AWS documentation. Returns ranked results with URL + title + context."""
    body = {
        "textQuery": {"input": search_phrase},
        "contextAttributes": [{"key": "domain", "value": "docs.aws.amazon.com"}],
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

    results: List[SearchResult] = []
    for i, s in enumerate(data.get("suggestions", [])[:limit]):
        t = s.get("textExcerptSuggestion") or {}
        meta = t.get("metadata", {}) or {}
        ctx = (
            meta.get("seo_abstract")
            or meta.get("abstract")
            or t.get("summary")
            or t.get("suggestionBody")
        )
        results.append(
            SearchResult(
                rank_order=i + 1,
                url=t.get("link", ""),
                title=t.get("title", ""),
                context=ctx,
            )
        )
    return results


@mcp.tool()
async def read_documentation(
    url: str,
    max_length: int = 5000,
    start_index: int = 0,
) -> str:
    """Fetch an AWS docs page (must be docs.aws.amazon.com/....html) and return markdown.

    Supports pagination via start_index for long pages.
    """
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
async def recommend(url: str) -> List[RecommendResult]:
    """Get related/new/similar/journey AWS docs recommendations for a given doc URL."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{RECOMMENDATIONS_API_URL}?path={url}&session={SESSION_UUID}",
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()

    out: List[RecommendResult] = []
    for bucket in ("highlyRated", "new", "similar", "journey"):
        for item in (data.get(bucket) or {}).get("items", []) or []:
            out.append(
                RecommendResult(
                    url=item.get("url", ""),
                    title=item.get("assetTitle") or item.get("title", ""),
                    context=item.get("abstract") or item.get("context"),
                )
            )
    return out


if __name__ == "__main__":
    from starlette.middleware.base import BaseHTTPMiddleware

    app = mcp.http_app(stateless_http=False)

    class LogHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            logger.info(
                "request_headers",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "headers": dict(request.headers),
                },
            )
            return await call_next(request)

    app.add_middleware(LogHeadersMiddleware)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
