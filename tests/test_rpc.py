import json
from typing import Any

import httpx
import pytest

from aria2_tui.rpc import Aria2Client, Aria2RPCError


@pytest.mark.asyncio
async def test_rpc_secret_and_add_uri_contract() -> None:
    calls: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": "gid1"}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = Aria2Client(
        "http://127.0.0.1:6800/jsonrpc",
        "secret-value",
        http_client=http,
    )

    gid = await client.add_uri("https://example.com/file.zip", "/tmp/downloads")

    assert gid == "gid1"
    assert calls[0]["method"] == "aria2.addUri"
    assert calls[0]["params"] == [
        "token:secret-value",
        ["https://example.com/file.zip"],
        {"dir": "/tmp/downloads"},
    ]
    await http.aclose()


@pytest.mark.asyncio
async def test_rpc_parses_downloads() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        result = (
            [
                {
                    "gid": "active1",
                    "status": "active",
                    "totalLength": "100",
                    "completedLength": "50",
                    "downloadSpeed": "10",
                    "connections": "2",
                    "files": [{"path": "/tmp/report.pdf", "uris": []}],
                }
            ]
            if payload["method"] == "aria2.tellActive"
            else []
        )
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = Aria2Client(http_client=http)

    downloads = await client.tell_active()

    assert len(downloads) == 1
    assert downloads[0].name == "report.pdf"
    assert downloads[0].progress == 0.5
    await http.aclose()


@pytest.mark.asyncio
async def test_rpc_error_is_raised_with_qr_code_message() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "error": {"code": 1, "message": "Unauthorized"},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = Aria2Client(http_client=http)

    with pytest.raises(Aria2RPCError, match="Unauthorized") as error:
        await client.get_version()

    assert error.value.code == 1
    await http.aclose()
