"""Tests for web_search tool."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.web_search import WebSearchInput, WebSearchTool


def _mock_urlopen(body: dict, status: int = 200):
    """Create a mock for urlopen that returns the given JSON body."""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps(body).encode("utf-8")

    return lambda *args, **kwargs: FakeResponse()


class TestWebSearchInput:
    def test_defaults(self):
        inp = WebSearchInput(query="test")
        assert inp.query == "test"
        assert inp.max_results == 10


class TestWebSearchTool:
    def test_unconfigured_returns_placeholder(self, tmp_path: Path):
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )
        tool = WebSearchTool(api_url=None)
        result = tool.invoke({"query": "hello"}, context)
        assert result.success
        assert "not configured" in result.summary

    def test_search_returns_results(self, tmp_path: Path):
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )
        tool = WebSearchTool(api_url="http://fake/api?q={query}")
        with patch(
            "urllib.request.urlopen",
            _mock_urlopen(
                {
                    "results": [
                        {"title": "T1", "url": "http://a", "snippet": "S1"},
                        {"title": "T2", "url": "http://b", "snippet": "S2"},
                    ]
                }
            ),
        ):
            result = tool.invoke({"query": "test"}, context)
        assert result.success
        assert len(result.data["results"]) == 2
        assert result.data["results"][0]["title"] == "T1"

    def test_empty_results(self, tmp_path: Path):
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )
        tool = WebSearchTool(api_url="http://fake/api?q={query}")
        with patch("urllib.request.urlopen", _mock_urlopen({"results": []})):
            result = tool.invoke({"query": "nothing"}, context)
        assert result.success
        assert "No results" in result.summary

    def test_parse_items_shape(self, tmp_path: Path):
        """Parser should handle 'items' key as well as 'results'."""
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )
        tool = WebSearchTool(api_url="http://fake/api?q={query}")
        with patch(
            "urllib.request.urlopen",
            _mock_urlopen({"items": [{"title": "X", "url": "http://x", "snippet": "y"}]}),
        ):
            result = tool.invoke({"query": "x"}, context)
        assert len(result.data["results"]) == 1

    def test_network_error(self, tmp_path: Path):
        config = AgentConfig()
        context = ToolContext(
            run_id="t",
            repo_url="https://github.com/x/y",
            workspace_path=tmp_path,
            run_dir=tmp_path,
            config=config,
        )
        tool = WebSearchTool(api_url="http://fake/api?q={query}")
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            result = tool.invoke({"query": "x"}, context)
        assert not result.success
        assert "Search" in result.summary
