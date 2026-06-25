"""Web search tool for the Agent using a configurable search API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, ClassVar

from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolInput, ToolResult


class WebSearchInput(ToolInput):
    query: str
    max_results: int = 10


class WebSearchTool(RuntimeTool):
    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the web using a configurable search API. "
        "Returns title, URL, and snippet for each result."
    )
    approval_level: ClassVar[ApprovalLevel] = ApprovalLevel.NETWORK
    input_model: ClassVar[type[WebSearchInput]] = WebSearchInput

    def __init__(self, api_url: str | None = None, timeout: int = 15) -> None:
        self._api_url = api_url
        self._timeout = timeout

    def run(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        parsed = WebSearchInput.model_validate(input_data)
        api_url = self._api_url or getattr(
            context.config, "web_search_url", None
        )
        if api_url is None:
            return ToolResult(
                success=True,
                summary=(
                    "Web search is not configured. Set web_search_url in config or "
                    "provide an api_url when constructing the tool. "
                    f"Would search for: '{parsed.query}'"
                ),
                data={"query": parsed.query, "configured": False},
            )

        try:
            results = self._fetch(api_url, parsed.query, parsed.max_results)
        except urllib.error.URLError as exc:
            return ToolResult.failure(
                code="search_network_error",
                message=f"Search request failed: {exc}",
            )
        except Exception as exc:
            return ToolResult.failure(
                code="search_error",
                message=f"Search failed: {exc}",
            )

        if not results:
            return ToolResult(
                success=True,
                summary=f"No results found for '{parsed.query}'",
                data={"query": parsed.query, "results": []},
            )

        summary_parts = [f"{r['title']}: {r['snippet'][:80]}" for r in results[:3]]
        return ToolResult(
            success=True,
            summary=f"Search '{parsed.query}': {len(results)} results. {'; '.join(summary_parts)}",
            data={"query": parsed.query, "results": results},
        )

    def _fetch(
        self, api_url: str, query: str, max_results: int
    ) -> list[dict[str, str]]:
        url = api_url.replace("{query}", urllib.request.quote(query)).replace(
            "{max_results}", str(max_results)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "nanoAgent/0.1"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            body = resp.read().decode("utf-8")
        return self._parse(body)

    @staticmethod
    def _parse(raw: str) -> list[dict[str, str]]:
        """Parse search API response. Override for specific APIs."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        # Try common response shapes
        for key in ("results", "items", "data"):
            if isinstance(data, dict) and key in data:
                items = data[key]
                if isinstance(items, list):
                    return [
                        {
                            "title": str(item.get("title", "")),
                            "url": str(item.get("url", item.get("link", ""))),
                            "snippet": str(item.get("snippet", item.get("description", ""))),
                        }
                        for item in items[:20]
                        if isinstance(item, dict)
                    ]
        return []
