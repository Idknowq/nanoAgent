"""Web fetch tool for retrieving URL content as text."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any, ClassVar

from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolInput, ToolResult


class WebFetchInput(ToolInput):
    url: str
    max_chars: int = 100_000


class WebFetchTool(RuntimeTool):
    name: ClassVar[str] = "web_fetch"
    description: ClassVar[str] = (
        "Fetch the content of a URL and return it as plain text. "
        "Strips HTML tags when the response looks like HTML. "
        "HTTP URLs are upgraded to HTTPS."
    )
    approval_level: ClassVar[ApprovalLevel] = ApprovalLevel.NETWORK
    input_model: ClassVar[type[WebFetchInput]] = WebFetchInput

    def __init__(self, timeout: int = 30, max_bytes: int = 1_000_000) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def run(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        parsed = WebFetchInput.model_validate(input_data)
        url = self._normalize_url(parsed.url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nanoAgent/0.1"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                ct = resp.headers.get("Content-Type", "")
                raw = resp.read(self._max_bytes + 1)
                if len(raw) > self._max_bytes:
                    raw = raw[: self._max_bytes]
                text = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return ToolResult.failure(
                code="fetch_http_error",
                message=f"HTTP {exc.code}: {exc.reason}",
            )
        except urllib.error.URLError as exc:
            return ToolResult.failure(
                code="fetch_network_error",
                message=f"Failed to fetch URL: {exc.reason}",
            )
        except Exception as exc:
            return ToolResult.failure(
                code="fetch_error",
                message=f"Fetch failed: {exc}",
            )

        if "text/html" in ct or text.strip().startswith("<!") or "<html" in text[:200].lower():
            text = self._strip_html(text)

        text = text.strip()[: parsed.max_chars]
        return ToolResult(
            success=True,
            summary=f"Fetched {url}: {len(text)} chars",
            data={"url": url, "content_type": ct, "text": text, "length": len(text)},
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith("http://"):
            url = "https://" + url[7:]
        elif not url.startswith("https://"):
            url = "https://" + url
        return url

    @staticmethod
    def _strip_html(html: str) -> str:
        # Remove scripts and styles
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Replace common block elements with newlines
        for tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br"):
            html = re.sub(f"<{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"</?[a-z][a-z0-9]*[^>]*>", "", html, flags=re.IGNORECASE)
        # Collapse whitespace
        html = re.sub(r"\n\s*\n", "\n\n", html)
        html = re.sub(r" {2,}", " ", html)
        return html
