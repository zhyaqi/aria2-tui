from __future__ import annotations

import pytest
from textual.widgets import Input, ListView

from aria2_tui.app import Aria2App, _display_uri
from aria2_tui.models import Download


class FakeRPC:
    def __init__(self) -> None:
        self.paused: list[str] = []
        self.added: list[tuple[str, str]] = []
        self.download = Download.from_rpc(
            {
                "gid": "active1",
                "status": "active",
                "totalLength": "1000",
                "completedLength": "250",
                "downloadSpeed": "50",
                "connections": "2",
                "dir": "/tmp/downloads",
                "files": [
                    {
                        "path": "/tmp/downloads/example.zip",
                        "uris": [{"uri": "https://example.com/example.zip"}],
                    }
                ],
            }
        )

    async def get_version(self) -> dict[str, str]:
        return {"version": "1.37.0"}

    async def get_global_option(self) -> dict[str, str]:
        return {"dir": "/tmp/downloads"}

    async def tell_active(self) -> list[Download]:
        return [self.download]

    async def tell_waiting(self) -> list[Download]:
        return []

    async def tell_stopped(self) -> list[Download]:
        return []

    async def pause(self, gid: str) -> str:
        self.paused.append(gid)
        return gid

    async def unpause(self, gid: str) -> str:
        return gid

    async def remove(self, gid: str) -> str:
        return gid

    async def remove_download_result(self, gid: str) -> str:
        return gid

    async def add_uri(self, uri: str, directory: str) -> str:
        self.added.append((uri, directory))
        return "new"

    async def close(self) -> None:
        return None


def test_display_uri_removes_sensitive_query_and_magnet_details() -> None:
    assert (
        _display_uri("https://example.com/file.zip?sign=secret&token=hidden")
        == "https://example.com/…/file.zip"
    )
    assert (
        _display_uri("https://user:password@example.com:8443/a/b/file.zip")
        == "https://example.com:8443/…/file.zip"
    )
    assert _display_uri("magnet:?xt=urn:btih:secret&dn=example") == "magnet link"


@pytest.mark.asyncio
async def test_app_renders_and_toggles_active_download() -> None:
    app = Aria2App(interval=10)
    fake = FakeRPC()
    app.rpc = fake  # type: ignore[assignment]

    async with app.run_test(size=(120, 36)) as pilot:
        await app.refresh_downloads()
        await pilot.pause()

        assert app.connected
        assert len(app.query_one("#downloads", ListView).children) == 1
        assert app.selected_gid == "active1"

        await pilot.press("space")
        await pilot.pause()
        assert fake.paused == ["active1"]


@pytest.mark.asyncio
async def test_add_dialog_submits_uri_and_directory() -> None:
    app = Aria2App(interval=10)
    fake = FakeRPC()
    app.rpc = fake  # type: ignore[assignment]

    async with app.run_test(size=(120, 36)) as pilot:
        await app.refresh_downloads()
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        app.screen.query_one("#add-uri", Input).value = "https://example.com/new.zip"
        app.screen.query_one("#add-directory", Input).value = "/tmp/custom"
        await pilot.press("enter")
        await pilot.pause()

        assert fake.added == [
            ("https://example.com/new.zip", "/tmp/custom"),
        ]


@pytest.mark.asyncio
async def test_light_theme_is_applied() -> None:
    app = Aria2App(interval=10, color_mode="light")
    fake = FakeRPC()
    app.rpc = fake  # type: ignore[assignment]

    async with app.run_test(size=(120, 36)) as pilot:
        await app.refresh_downloads()
        await pilot.pause()

        assert app.theme == "aria2-light"
        assert app.current_theme.dark is False
        assert app.palette.background == "#f4f7f9"
