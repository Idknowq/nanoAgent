"""Tests for MCP client and protocol module."""

from __future__ import annotations

import json

import pytest

from nano_agent.mcp.client import (
    MCPClient,
    MCPProtocolError,
    MCPTransport,
    MCPTransportError,
    StdioTransport,
)
from nano_agent.mcp.protocol import (
    InitializeParams,
    InitializeResult,
    ImplementationInfo,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    MCPTool,
    ServerCapabilities,
    ToolCallResult,
)


# ---- JSON-RPC model tests ----


class TestJsonRpcRequest:
    def test_serialize_minimal(self):
        req = JsonRpcRequest(id=1, method="ping")
        data = req.model_dump(mode="json")
        assert data == {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": None}

    def test_serialize_with_params(self):
        req = JsonRpcRequest(id=2, method="tools/list", params={"cursor": None})
        data = req.model_dump(mode="json")
        assert data["params"] == {"cursor": None}


class TestJsonRpcResponse:
    def test_success_response(self):
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})
        resp = JsonRpcResponse.model_validate_json(raw)
        assert resp.success is True
        assert resp.result == {"tools": []}

    def test_error_response(self):
        raw = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        )
        resp = JsonRpcResponse.model_validate_json(raw)
        assert resp.success is False
        assert resp.error is not None
        assert resp.error.code == -32600

    def test_notification_no_id(self):
        raw = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        notif = JsonRpcNotification.model_validate_json(raw)
        assert notif.method == "notifications/initialized"


# ---- MCP initialize types ----


class TestInitializeParams:
    def test_defaults(self):
        params = InitializeParams()
        assert params.protocol_version == "2024-11-05"
        assert params.client_info["name"] == "nanoAgent"
        assert params.client_info["version"] == "0.1.0"


class TestInitializeResult:
    def test_deserialize(self):
        raw = json.dumps(
            {
                "protocol_version": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "server_info": {"name": "test-server", "version": "1.0.0"},
            }
        )
        result = InitializeResult.model_validate_json(raw)
        assert result.server_info.name == "test-server"
        assert result.capabilities.tools == {}


# ---- MCP Tool types ----


class TestMCPTool:
    def test_deserialize(self):
        raw = {
            "name": "search",
            "description": "Search documents",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
        tool = MCPTool.model_validate(raw)
        assert tool.name == "search"
        assert tool.input_schema["required"] == ["query"]


class TestToolCallResult:
    def test_success_result(self):
        result = ToolCallResult(
            content=[{"type": "text", "text": "42 results found"}]
        )
        assert result.is_error is False
        assert len(result.content) == 1


# ---- Transport ----

DUMMY_TEXT = json.dumps(
    {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
)


class FakeTransport(MCPTransport):
    """In-memory transport for testing MCPClient."""

    def __init__(self, responses: list[bytes] | None = None):
        self.sent: list[bytes] = []
        self._responses = responses or [DUMMY_TEXT.encode()]
        self._recv_idx = 0

    def send(self, message: bytes) -> None:
        self.sent.append(message)

    def receive(self) -> bytes:
        if self._recv_idx >= len(self._responses):
            raise MCPTransportError("No more responses")
        resp = self._responses[self._recv_idx]
        self._recv_idx += 1
        return resp

    def close(self) -> None:
        pass


# ---- MCPClient ----


class TestMCPClient:
    def _make_initialize_response(self) -> bytes:
        resp = JsonRpcResponse(
            id=1,
            result=InitializeResult(
                protocol_version="2024-11-05",
                capabilities=ServerCapabilities(tools={}),
                server_info=ImplementationInfo(name="test", version="1.0"),
            ).model_dump(mode="json"),
        )
        return json.dumps(resp.model_dump(mode="json")).encode()

    def _make_list_tools_response(self, id_val: int, tools: list[dict]) -> bytes:
        resp = JsonRpcResponse(id=id_val, result={"tools": tools})
        return json.dumps(resp.model_dump(mode="json")).encode()

    def test_initialize_handshake(self):
        transport = FakeTransport(responses=[self._make_initialize_response()])
        client = MCPClient(transport)
        result = client.start()
        assert client.initialized is True
        assert result.server_info.name == "test"
        assert len(transport.sent) == 2  # initialize + initialized notification
        # Verify notification
        notif_raw = json.loads(transport.sent[1])
        assert notif_raw["method"] == "notifications/initialized"

    def test_list_tools(self):
        transport = FakeTransport(
            responses=[
                self._make_initialize_response(),
                self._make_list_tools_response(
                    2,
                    [
                        {
                            "name": "search",
                            "description": "search docs",
                            "input_schema": {"type": "object", "properties": {}},
                        }
                    ],
                ),
            ]
        )
        client = MCPClient(transport)
        client.start()
        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "search"

    def test_call_tool(self):
        call_result = {"content": [{"type": "text", "text": "ok"}], "is_error": False}
        transport = FakeTransport(
            responses=[
                self._make_initialize_response(),
                json.dumps(
                    JsonRpcResponse(id=2, result=call_result).model_dump(mode="json")
                ).encode(),
            ]
        )
        client = MCPClient(transport)
        client.start()
        result = client.call_tool("search", {"query": "x"})
        assert result.is_error is False
        assert result.content[0]["text"] == "ok"

    def test_error_response(self):
        from nano_agent.mcp.protocol import JsonRpcError

        error_resp = JsonRpcResponse(
            id=1,
            error=JsonRpcError(code=-32601, message="Method not found"),
            result=None,
        )
        transport = FakeTransport(
            responses=[json.dumps(error_resp.model_dump(mode="json")).encode()]
        )
        client = MCPClient(transport)
        with pytest.raises(MCPProtocolError, match="Method not found"):
            client.start()

    def test_close_marks_uninitialized(self):
        transport = FakeTransport(responses=[self._make_initialize_response()])
        client = MCPClient(transport)
        client.start()
        assert client.initialized is True
        client.close()
        assert client.initialized is False

    def test_server_capabilities_exposed(self):
        transport = FakeTransport(responses=[self._make_initialize_response()])
        client = MCPClient(transport)
        client.start()
        assert client.server_capabilities is not None
        assert "tools" in client.server_capabilities


class TestStdioTransport:
    def test_start_launches_process(self):
        transport = StdioTransport(["echo", "test"])
        transport.start()
        try:
            assert transport._process is not None
            assert transport._process.poll() is None  # process is alive
            transport.close()
        except MCPTransportError:
            # echo exits immediately so receive may fail - that's fine
            transport.close()

    def test_send_receive_roundtrip(self):
        """Use a simple cat-like Python process for roundtrip test."""
        script = (
            "import sys, json; "
            "req = json.loads(sys.stdin.readline()); "
            "resp = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'echo': req['params']}}; "
            "sys.stdout.write(json.dumps(resp) + '\\n'); "
            "sys.stdout.flush()"
        )
        transport = StdioTransport(["python3", "-c", script])
        transport.start()
        try:
            req = json.dumps(
                JsonRpcRequest(id=1, method="echo", params={"msg": "hi"}).model_dump(
                    mode="json"
                )
            )
            transport.send(req.encode())
            raw = transport.receive()
            resp = JsonRpcResponse.model_validate_json(raw)
            assert resp.success
            assert resp.result == {"echo": {"msg": "hi"}}
        finally:
            transport.close()

    def test_close_terminates_process(self):
        transport = StdioTransport(["sleep", "10"])
        transport.start()
        assert transport._process is not None
        transport.close()
        # Process should be terminated
        assert transport._process is None
        # After close, the process should no longer be running
