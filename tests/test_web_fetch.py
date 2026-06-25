"""Tests for web_fetch tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.web_fetch import WebFetchInput, WebFetchTool


class FakeResponse:
    def __init__(self, body: str, content_type: str = "text/html", status: int = 200):
        self._body = body.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size: int = -1):
        if size < 0:
            return self._body
        return self._body[:size]


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="t",
        repo_url="https://github.com/x/y",
        workspace_path=tmp_path,
        run_dir=tmp_path,
        config=AgentConfig(),
    )


class TestWebFetchInput:
    def test_defaults(self):
        inp = WebFetchInput(url="https://example.com")
        assert inp.url == "https://example.com"
        assert inp.max_chars == 100_000


class TestWebFetchTool:
    def test_fetch_html_strips_tags(self, tmp_path: Path):
        tool = WebFetchTool()
        html = "<html><body><p>Hello World</p></body></html>"
        with patch("urllib.request.urlopen", return_value=FakeResponse(html)):
            result = tool.invoke({"url": "https://example.com"}, _context(tmp_path))
        assert result.success
        assert "Hello World" in result.data["text"]

    def test_fetch_plain_text_passthrough(self, tmp_path: Path):
        tool = WebFetchTool()
        text = '{"key": "value"}'
        with patch(
            "urllib.request.urlopen",
            return_value=FakeResponse(text, content_type="application/json"),
        ):
            result = tool.invoke({"url": "https://api.example.com"}, _context(tmp_path))
        assert result.success
        assert '"key"' in result.data["text"]

    def test_fetch_truncates_to_max_chars(self, tmp_path: Path):
        tool = WebFetchTool()
        long_text = "A" * 500
        with patch(
            "urllib.request.urlopen",
            return_value=FakeResponse(long_text, content_type="text/plain"),
        ):
            result = tool.invoke({"url": "https://x.com", "max_chars": 100}, _context(tmp_path))
        assert result.success
        assert len(result.data["text"]) == 100

    def test_fetch_http_upgraded_to_https(self, tmp_path: Path):
        tool = WebFetchTool()
        with patch("urllib.request.urlopen", return_value=FakeResponse("ok")) as mock_open:
            tool.invoke({"url": "http://example.com"}, _context(tmp_path))
            req = mock_open.call_args[0][0]
            assert req.full_url.startswith("https://")

    def test_fetch_no_scheme_adds_https(self, tmp_path: Path):
        tool = WebFetchTool()
        with patch("urllib.request.urlopen", return_value=FakeResponse("ok")) as mock_open:
            tool.invoke({"url": "example.com/path"}, _context(tmp_path))
            req = mock_open.call_args[0][0]
            assert req.full_url == "https://example.com/path"

    def test_fetch_network_error(self, tmp_path: Path):
        from urllib.error import URLError

        tool = WebFetchTool()
        with patch("urllib.request.urlopen", side_effect=URLError("no route")):
            result = tool.invoke({"url": "https://invalid.test"}, _context(tmp_path))
        assert not result.success
        assert result.error_code == "fetch_network_error"

    def test_strip_html_removes_scripts(self, tmp_path: Path):
        tool = WebFetchTool()
        html = "<html><script>alert('xss')</script><p>safe</p></html>"
        with patch("urllib.request.urlopen", return_value=FakeResponse(html)):
            result = tool.invoke({"url": "https://x.com"}, _context(tmp_path))
        assert "alert" not in result.data["text"]
        assert "safe" in result.data["text"]
