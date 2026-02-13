"""
OpenClaw Distro — Web Search Client

Pluggable search backend for agents with web access (Investigator, Verifier).

Supported backends (in priority order):
1. Brave Search API  — best privacy, 2000 free req/month
2. Tavily            — purpose-built for AI agents, returns pre-parsed content
3. SerpAPI           — Google results, most comprehensive, paid

Configuration via environment variables:
    SEARCH_BACKEND=brave|tavily|serpapi|none
    BRAVE_API_KEY=...
    TAVILY_API_KEY=...
    SERPAPI_API_KEY=...

Falls back gracefully to "none" (LLM-only) if no keys are configured.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Data Types ───────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    source_type: str = "web"  # web, news, docs, forum
    relevance: float = 0.5
    raw: dict = field(default_factory=dict)


@dataclass
class SearchResponse:
    """Aggregated search response."""
    query: str
    results: list[SearchResult]
    backend: str
    total_results: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.results) > 0


# ─── Backend Implementations ─────────────────────────────────────────────────


class BraveBackend:
    """Brave Search API — https://brave.com/search/api/"""

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
        )

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        try:
            resp = await self._client.get(
                self.BASE_URL,
                params={"q": query, "count": min(max_results, 20)},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("web", {}).get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    source_type=_classify_source(item.get("url", "")),
                    raw=item,
                ))

            return SearchResponse(
                query=query,
                results=results[:max_results],
                backend="brave",
                total_results=data.get("web", {}).get("totalResults", len(results)),
            )

        except Exception as e:
            logger.warning(f"Brave search failed: {e}")
            return SearchResponse(
                query=query, results=[], backend="brave", error=str(e)
            )

    async def close(self):
        await self._client.aclose()


class TavilyBackend:
    """Tavily Search API — https://tavily.com/ (built for AI agents)"""

    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=20.0)

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        try:
            resp = await self._client.post(
                self.BASE_URL,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": min(max_results, 10),
                    "include_answer": True,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    source_type=_classify_source(item.get("url", "")),
                    relevance=item.get("score", 0.5),
                    raw=item,
                ))

            # If Tavily provided a direct answer, prepend it
            answer = data.get("answer")
            if answer:
                results.insert(0, SearchResult(
                    title="AI-Generated Answer",
                    url="",
                    snippet=answer,
                    source_type="ai_summary",
                    relevance=0.9,
                ))

            return SearchResponse(
                query=query,
                results=results[:max_results],
                backend="tavily",
                total_results=len(results),
            )

        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")
            return SearchResponse(
                query=query, results=[], backend="tavily", error=str(e)
            )

    async def close(self):
        await self._client.aclose()


class SerpAPIBackend:
    """SerpAPI — https://serpapi.com/ (Google results)"""

    BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        try:
            resp = await self._client.get(
                self.BASE_URL,
                params={
                    "q": query,
                    "api_key": self.api_key,
                    "engine": "google",
                    "num": min(max_results, 10),
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("organic_results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source_type=_classify_source(item.get("link", "")),
                    relevance=1.0 - (item.get("position", 5) / 10),
                    raw=item,
                ))

            return SearchResponse(
                query=query,
                results=results[:max_results],
                backend="serpapi",
                total_results=data.get("search_information", {}).get(
                    "total_results", len(results)
                ),
            )

        except Exception as e:
            logger.warning(f"SerpAPI search failed: {e}")
            return SearchResponse(
                query=query, results=[], backend="serpapi", error=str(e)
            )

    async def close(self):
        await self._client.aclose()


class NoneBackend:
    """No-op backend when web search is disabled."""

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        return SearchResponse(
            query=query,
            results=[],
            backend="none",
            error="Web search disabled (no API key configured)",
        )

    async def close(self):
        pass


# ─── Web Search Client ───────────────────────────────────────────────────────


class WebSearchClient:
    """
    Unified web search client with pluggable backends.

    Usage:
        client = WebSearchClient.from_env()
        response = await client.search("OpenClaw multi-agent framework")
        for result in response.results:
            print(result.title, result.url)
    """

    def __init__(self, backend):
        self.backend = backend
        self.total_searches = 0

    @classmethod
    def from_env(cls) -> "WebSearchClient":
        """
        Create a WebSearchClient from environment variables.
        Auto-detects which backend to use based on available API keys.
        """
        preferred = os.environ.get("SEARCH_BACKEND", "auto").lower()

        if preferred == "brave" or (preferred == "auto" and os.environ.get("BRAVE_API_KEY")):
            key = os.environ.get("BRAVE_API_KEY", "")
            if key:
                logger.info("Web search backend: Brave")
                return cls(BraveBackend(key))

        if preferred == "tavily" or (preferred == "auto" and os.environ.get("TAVILY_API_KEY")):
            key = os.environ.get("TAVILY_API_KEY", "")
            if key:
                logger.info("Web search backend: Tavily")
                return cls(TavilyBackend(key))

        if preferred == "serpapi" or (preferred == "auto" and os.environ.get("SERPAPI_API_KEY")):
            key = os.environ.get("SERPAPI_API_KEY", "")
            if key:
                logger.info("Web search backend: SerpAPI")
                return cls(SerpAPIBackend(key))

        logger.info("Web search backend: none (no API keys configured)")
        return cls(NoneBackend())

    async def search(
        self, query: str, max_results: int = 5
    ) -> SearchResponse:
        """Run a search query."""
        self.total_searches += 1
        logger.debug(f"Web search [{self.backend_name}]: {query[:80]}")
        return await self.backend.search(query, max_results)

    async def multi_search(
        self, queries: list[str], max_results_per: int = 3
    ) -> list[SearchResponse]:
        """Run multiple search queries (sequentially to respect rate limits)."""
        responses = []
        for query in queries:
            resp = await self.search(query, max_results_per)
            responses.append(resp)
        return responses

    @property
    def backend_name(self) -> str:
        return type(self.backend).__name__.replace("Backend", "").lower()

    @property
    def is_available(self) -> bool:
        return not isinstance(self.backend, NoneBackend)

    def get_metrics(self) -> dict:
        return {
            "backend": self.backend_name,
            "available": self.is_available,
            "total_searches": self.total_searches,
        }

    async def close(self):
        await self.backend.close()


# ─── Utilities ────────────────────────────────────────────────────────────────


def _classify_source(url: str) -> str:
    """Classify a URL into a source type for quality scoring."""
    url_lower = url.lower()

    # Official docs
    doc_domains = [
        "docs.", "documentation.", "developer.", "devdocs.",
        ".readthedocs.io", "doc.rust-lang.org",
    ]
    if any(d in url_lower for d in doc_domains):
        return "official_docs"

    # Academic / papers
    academic = [
        "arxiv.org", "scholar.google", "pubmed", "doi.org",
        "ieee.org", "acm.org", "nature.com", "science.org",
    ]
    if any(d in url_lower for d in academic):
        return "peer_reviewed"

    # Official blogs / org sites
    official = [
        "blog.", ".gov", "github.com/", "openai.com", "anthropic.com",
        "google.dev", "microsoft.com", "aws.amazon.com",
    ]
    if any(d in url_lower for d in official):
        return "official_blog"

    # Reputable news
    news = [
        "reuters.com", "bbc.com", "nytimes.com", "wsj.com",
        "techcrunch.com", "arstechnica.com", "theverge.com",
        "wired.com", "bloomberg.com",
    ]
    if any(d in url_lower for d in news):
        return "news_reputable"

    # Community docs
    community = [
        "stackoverflow.com", "stackexchange.com", "github.com/issues",
        "wiki", "medium.com", "dev.to",
    ]
    if any(d in url_lower for d in community):
        return "community_docs"

    # Forums / social
    forums = [
        "reddit.com", "twitter.com", "x.com", "discord",
        "telegram", "forum", "discuss",
    ]
    if any(d in url_lower for d in forums):
        return "forum_social"

    return "web"


def format_results_for_prompt(response: SearchResponse, max_chars: int = 3000) -> str:
    """Format search results for injection into an LLM prompt."""
    if not response.success:
        return f"(Web search failed: {response.error})"

    lines = [f"Web search results for: \"{response.query}\"", ""]
    total_chars = 0

    for i, r in enumerate(response.results, 1):
        entry = (
            f"{i}. [{r.source_type}] {r.title}\n"
            f"   URL: {r.url}\n"
            f"   {r.snippet}\n"
        )
        if total_chars + len(entry) > max_chars:
            lines.append(f"... ({len(response.results) - i + 1} more results truncated)")
            break
        lines.append(entry)
        total_chars += len(entry)

    return "\n".join(lines)
