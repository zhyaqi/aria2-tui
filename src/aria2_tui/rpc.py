from __future__ import annotations

import itertools
from typing import Any, Self

import httpx

from .models import DOWNLOAD_KEYS, Download


class Aria2RPCError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class Aria2Client:
    def __init__(
        self,
        url: str = "http://127.0.0.1:6800/jsonrpc",
        secret: str = "",
        *,
        timeout: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url
        self._secret = secret
        self._ids = itertools.count(1)
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"Content-Type": "application/json"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def call(self, method: str, *params: Any) -> Any:
        if self._secret:
            params = (f"token:{self._secret}", *params)
        payload = {
            "jsonrpc": "2.0",
            "id": f"aria2-tui-{next(self._ids)}",
            "method": method,
            "params": list(params),
        }
        try:
            response = await self._http.post(self.url, json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise Aria2RPCError(f"Cannot reach aria2 at {self.url}") from exc
        except ValueError as exc:
            raise Aria2RPCError("aria2 returned an invalid JSON response") from exc

        if "error" in body:
            error = body["error"] or {}
            raise Aria2RPCError(
                str(error.get("message", "Unknown aria2 RPC error")),
                code=error.get("code"),
                data=error.get("data"),
            )
        if "result" not in body:
            raise Aria2RPCError("aria2 returned a response without a result")
        return body["result"]

    async def get_version(self) -> dict[str, Any]:
        return await self.call("aria2.getVersion")

    async def get_global_option(self) -> dict[str, Any]:
        return await self.call("aria2.getGlobalOption")

    async def tell_active(self) -> list[Download]:
        result = await self.call("aria2.tellActive", DOWNLOAD_KEYS)
        return [_download(item) for item in result]

    async def tell_waiting(self, offset: int = 0, count: int = 100) -> list[Download]:
        result = await self.call("aria2.tellWaiting", offset, count, DOWNLOAD_KEYS)
        return [_download(item) for item in result]

    async def tell_stopped(self, offset: int = 0, count: int = 100) -> list[Download]:
        result = await self.call("aria2.tellStopped", offset, count, DOWNLOAD_KEYS)
        return [_download(item) for item in result]

    async def add_uri(self, uri: str, directory: str = "") -> str:
        options = {"dir": directory} if directory else {}
        result = await self.call("aria2.addUri", [uri], options)
        return str(result)

    async def pause(self, gid: str) -> str:
        return str(await self.call("aria2.pause", gid))

    async def unpause(self, gid: str) -> str:
        return str(await self.call("aria2.unpause", gid))

    async def remove(self, gid: str) -> str:
        return str(await self.call("aria2.remove", gid))

    async def remove_download_result(self, gid: str) -> str:
        return str(await self.call("aria2.removeDownloadResult", gid))


def _download(data: Any) -> Download:
    if not isinstance(data, dict):
        raise Aria2RPCError("aria2 returned an invalid download object")
    return Download.from_rpc(data)
