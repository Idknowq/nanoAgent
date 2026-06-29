from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from nano_agent.mcp import (
    MCPProtocolError,
    MCPServerConfig,
    MCPTransportClosedError,
    MCPTransportNotStartedError,
    MCPTransportTimeoutError,
    StdioMCPTransport,
)
from nano_agent.mcp.jsonrpc import JSONRPCRequest


def write_mock_server(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "mock_mcp_server.py"
    path.write_text(source, encoding="utf-8")
    return path


def make_transport(script: Path, timeout_seconds: float = 1.0) -> StdioMCPTransport:
    config = MCPServerConfig(
        name="mock",
        transport="stdio",
        command=sys.executable,
        args=(str(script),),
    )
    return StdioMCPTransport(config=config, timeout_seconds=timeout_seconds)


async def test_stdio_transport_sends_request_and_reads_response(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {"method": request["method"]},
    }), flush=True)
""".strip(),
    )
    transport = make_transport(script)

    await transport.start()
    try:
        response = await transport.request(JSONRPCRequest(id=1, method="ping"))
    finally:
        await transport.shutdown()

    assert response.result == {"method": "ping"}


async def test_stdio_transport_serializes_concurrent_requests(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    time.sleep(0.05)
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {"method": request["method"]},
    }), flush=True)
""".strip(),
    )
    transport = make_transport(script)

    await transport.start()
    try:
        first, second = await asyncio.gather(
            transport.request(JSONRPCRequest(id=1, method="first")),
            transport.request(JSONRPCRequest(id=2, method="second")),
        )
    finally:
        await transport.shutdown()

    assert first.result == {"method": "first"}
    assert second.result == {"method": "second"}


async def test_stdio_transport_requires_start(tmp_path: Path) -> None:
    script = write_mock_server(tmp_path, "print('unused')")
    transport = make_transport(script)

    with pytest.raises(MCPTransportNotStartedError):
        await transport.request(JSONRPCRequest(id=1, method="ping"))


async def test_stdio_transport_rejects_invalid_json(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import sys

for line in sys.stdin:
    print("not-json", flush=True)
""".strip(),
    )
    transport = make_transport(script)

    await transport.start()
    try:
        with pytest.raises(MCPProtocolError, match="invalid JSON"):
            await transport.request(JSONRPCRequest(id=1, method="ping"))
    finally:
        await transport.shutdown()


async def test_stdio_transport_rejects_mismatched_response_id(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import json
import sys

for line in sys.stdin:
    print(json.dumps({"jsonrpc": "2.0", "id": 999, "result": {}}), flush=True)
""".strip(),
    )
    transport = make_transport(script)

    await transport.start()
    try:
        with pytest.raises(MCPProtocolError, match="did not match request id"):
            await transport.request(JSONRPCRequest(id=1, method="ping"))
    finally:
        await transport.shutdown()


async def test_stdio_transport_times_out_when_server_does_not_respond(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import time
import sys

for line in sys.stdin:
    time.sleep(5)
""".strip(),
    )
    transport = make_transport(script, timeout_seconds=0.05)

    await transport.start()
    try:
        with pytest.raises(MCPTransportTimeoutError):
            await transport.request(JSONRPCRequest(id=1, method="ping"))
    finally:
        await transport.shutdown()


async def test_stdio_transport_reports_closed_server(tmp_path: Path) -> None:
    script = write_mock_server(tmp_path, "raise SystemExit(0)")
    transport = make_transport(script)

    await transport.start()
    try:
        with pytest.raises(MCPTransportClosedError):
            await transport.request(JSONRPCRequest(id=1, method="ping"))
    finally:
        await transport.shutdown()


async def test_stdio_transport_shutdown_is_idempotent(tmp_path: Path) -> None:
    script = write_mock_server(
        tmp_path,
        """
import sys

for line in sys.stdin:
    pass
""".strip(),
    )
    transport = make_transport(script)

    await transport.start()
    await transport.shutdown()
    await transport.shutdown()
