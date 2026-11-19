from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlparse, urlsplit, urlunsplit

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

from .models import Download, human_bytes, human_duration, status_meta
from .rpc import Aria2Client, Aria2RPCError
from .theme import (
    ARIA2_DARK_THEME,
    ARIA2_LIGHT_THEME,
    PALETTES,
    ColorMode,
    Palette,
    resolve_color_mode,
)


@dataclass(frozen=True, slots=True)
class AddRequest:
    uri: str
    directory: str


class DownloadCard(Static):
    def __init__(self, download: Download, palette: Palette) -> None:
        super().__init__(markup=False, classes="download-card")
        self.download = download
        self.palette = palette
        self.update(self._render_download(download, palette))

    def update_download(self, download: Download, palette: Palette) -> None:
        self.download = download
        self.palette = palette
        self.update(self._render_download(download, palette))

    @staticmethod
    def _render_download(download: Download, palette: Palette) -> Text:
        icon, label = status_meta(download.status)
        color = _status_color(download.status, palette)
        percent = download.progress * 100
        width = 22
        filled = width if percent >= 100 else round(width * download.progress)
        bar = "━" * filled + (
            "╺" + "─" * (width - filled - 1) if filled < width else ""
        )

        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f"{icon} ", style=f"bold {color}")
        text.append(download.name, style=f"bold {palette.text}")
        text.append("\n")
        text.append(bar, style=color)
        text.append(f"  {percent:5.1f}%", style=f"bold {color}")
        text.append("\n")
        text.append(f"{label:<8}", style=f"bold {color}")
        text.append(" · ", style=palette.divider)
        if download.error_message:
            text.append(download.error_message, style=palette.error)
        else:
            if download.status == "active":
                text.append(
                    f"{human_bytes(download.download_speed)}/s", style=palette.muted
                )
                text.append(" · ", style=palette.divider)
            completed = human_bytes(download.completed_length).removesuffix(" B")
            total = human_bytes(download.total_length)
            text.append(
                f"{completed}/{total}",
                style=palette.muted,
            )
            text.append(" · ", style=palette.divider)
            text.append(
                f"ETA {human_duration(download.remaining_seconds)}", style=palette.muted
            )
            text.append(" · ", style=palette.divider)
            text.append(f"{download.connections} conn", style=palette.muted)
        return text


class DownloadItem(ListItem):
    def __init__(self, download: Download, palette: Palette) -> None:
        super().__init__(
            DownloadCard(download, palette),
            id=f"download-{download.gid}",
        )
        self.download = download

    def update_download(self, download: Download, palette: Palette) -> None:
        self.download = download
        self.query_one(DownloadCard).update_download(download, palette)


class DetailPanel(Static):
    def __init__(self, palette: Palette, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.palette = palette

    def update_download(
        self,
        download: Download | None,
        *,
        connected: bool,
        error: str = "",
    ) -> None:
        palette = self.palette
        if download is None:
            text = Text()
            if not connected:
                text.append("ARIA2 IS OFFLINE\n\n", style=f"bold {palette.error}")
                text.append(
                    error or "Waiting for the local RPC service…", style=palette.muted
                )
            else:
                text.append("No download selected.\n", style=palette.body)
                text.append("\nPress ", style=palette.dim)
                text.append("a", style=f"bold {palette.accent}")
                text.append(" to start a new download.", style=palette.dim)
            self.update(text)
            return

        icon, label = status_meta(download.status)
        color = _status_color(download.status, palette)
        text = Text()
        text.append(f"{icon} ", style=f"bold {color}")
        text.append(download.name, style=f"bold {palette.text}")
        text.append("\n\n")
        text.append(f"{label}\n", style=f"bold {color}")

        width = 24
        filled = width if download.progress >= 1 else round(width * download.progress)
        bar = "━" * filled + (
            "╺" + "─" * (width - filled - 1) if filled < width else ""
        )
        text.append(bar, style=color)
        text.append(f"  {download.progress * 100:.1f}%\n\n", style=f"bold {color}")

        text.append("TRANSFER\n", style=f"bold {color}")
        _detail_line(
            text, "Downloaded", human_bytes(download.completed_length), palette
        )
        _detail_line(text, "Total", human_bytes(download.total_length), palette)
        _detail_line(
            text, "Speed", f"{human_bytes(download.download_speed)}/s", palette
        )
        _detail_line(text, "ETA", human_duration(download.remaining_seconds), palette)
        _detail_line(text, "Connections", str(download.connections), palette)
        _detail_line(text, "Files", str(download.file_count), palette)
        text.append("\n")
        text.append("LOCATION\n", style=f"bold {palette.dim}")
        text.append(f"{download.directory or 'Unknown'}\n", style=palette.body)
        text.append("\n")
        text.append("GID\n", style=f"bold {palette.dim}")
        text.append(f"{download.gid}\n", style=palette.muted)

        if download.uri:
            text.append("\n")
            text.append("SOURCE\n", style=f"bold {palette.dim}")
            text.append(_display_uri(download.uri), style=palette.muted)
        if download.error_message:
            text.append("\n\n")
            text.append("ERROR\n", style=f"bold {palette.error}")
            text.append(download.error_message, style=palette.error)
        if not connected:
            text.append("\n\n")
            text.append("RPC OFFLINE", style=f"bold {palette.error}")
            text.append(f"\n{error}", style=palette.muted)
        self.update(text)


def _detail_line(text: Text, label: str, value: str, palette: Palette) -> None:
    text.append(f"{label:<12}", style=palette.dim)
    text.append(f"{value}\n", style=palette.body)


class AddDownloadScreen(ModalScreen[AddRequest | None]):
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, default_directory: str = "") -> None:
        super().__init__()
        self.default_directory = default_directory

    def compose(self) -> ComposeResult:
        with Vertical(id="add-dialog"):
            yield Static("ADD DOWNLOAD", id="add-title")
            yield Label("SOURCE URL OR MAGNET", classes="field-label")
            yield Input(
                placeholder="https://example.com/file.zip",
                id="add-uri",
            )
            yield Label("DIRECTORY", classes="field-label")
            yield Input(
                value=self.default_directory,
                placeholder="aria2 default directory",
                id="add-directory",
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("CANCEL", id="cancel")
                yield Button("DOWNLOAD", id="submit", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#add-uri", Input).focus()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        uri = self.query_one("#add-uri", Input).value.strip()
        directory = self.query_one("#add-directory", Input).value.strip()
        if not uri:
            self.app.notify("Enter a URL or magnet link.", severity="warning")
            return
        self.dismiss(AddRequest(uri=uri, directory=directory))


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.dialog_title, id="confirm-title", markup=False)
            yield Static(self.message, id="confirm-message", markup=False)
            with Horizontal(classes="dialog-buttons"):
                yield Button("CANCEL", id="cancel")
                yield Button("REMOVE", id="confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class Aria2App(App[None]):
    TITLE = "aria2"
    SUB_TITLE = "download console"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen {
        background: $aria-background;
        color: $aria-body;
    }

    #topbar {
        height: 1;
        margin: 1 2 0 2;
    }

    #brand {
        width: 18;
        color: $aria-accent;
        text-style: bold;
    }

    #endpoint {
        width: 1fr;
        color: $aria-faint;
        text-align: right;
    }

    #connection {
        width: auto;
        margin-left: 2;
    }

    #summary {
        height: 1;
        margin: 0 2 1 2;
        color: $aria-muted;
    }

    #workspace {
        height: 1fr;
        margin: 0 2;
    }

    #downloads {
        width: 2fr;
        border: round $aria-border;
        border-title-color: $aria-accent;
        border-title-style: bold;
        padding: 0 1;
        background: $aria-panel;
    }

    #details {
        width: 1fr;
        min-width: 32;
        margin-left: 1;
        padding: 1 1;
        border: round $aria-border;
        border-title-color: $aria-accent;
        border-title-style: bold;
        background: $aria-panel;
        overflow-y: auto;
    }

    ListItem {
        height: auto;
        padding: 0;
        margin-bottom: 1;
        background: $aria-card;
    }

    ListItem.-highlight {
        background: $aria-selected;
    }

    .download-card {
        height: 3;
        padding: 0 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    #empty-state {
        height: 4;
        padding: 1 1;
        color: $aria-dim;
    }

    Footer {
        background: $aria-background;
        color: $aria-dim;
    }

    AddDownloadScreen, ConfirmScreen {
        align: center middle;
        background: $aria-veil;
    }

    #add-dialog {
        width: 72;
        height: auto;
        padding: 1 2 2 2;
        border: round $aria-accent;
        background: $aria-panel;
    }

    #confirm-dialog {
        width: 58;
        height: auto;
        padding: 1 2 2 2;
        border: round $aria-error;
        background: $aria-panel;
    }

    #add-title, #confirm-title {
        height: 2;
        color: $aria-accent;
        text-style: bold;
    }

    #confirm-title {
        color: $aria-error;
    }

    #confirm-message {
        height: auto;
        margin: 1 0 1 0;
        color: $aria-body;
    }

    .field-label {
        height: 1;
        margin-top: 1;
        color: $aria-dim;
        text-style: bold;
    }

    Input {
        margin-top: 1;
        border: round $aria-border;
        background: $aria-input;
    }

    Input:focus {
        border: round $aria-accent;
    }

    .dialog-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 2;
    }

    .dialog-buttons Button {
        margin-left: 1;
    }

    Button {
        min-width: 11;
        border: round $aria-border;
        background: $aria-button;
        color: $aria-text;
    }

    Button.-primary {
        background: $aria-accent;
        border: round $aria-accent;
        color: $aria-accent-foreground;
    }

    Button.-error {
        background: $aria-error;
        border: round $aria-error;
        color: #ffffff;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "quit"),
        Binding("a", "add_download", "add"),
        Binding("space", "toggle_pause", "pause / resume"),
        Binding("d", "remove_download", "remove"),
        Binding("r", "refresh_now", "refresh"),
    ]

    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:6800/jsonrpc",
        secret: str = "",
        interval: float = 1.0,
        color_mode: ColorMode = "dark",
    ) -> None:
        super().__init__()
        self.color_mode = color_mode
        self.palette = PALETTES[color_mode]
        self.register_theme(ARIA2_DARK_THEME)
        self.register_theme(ARIA2_LIGHT_THEME)
        self.theme = f"aria2-{color_mode}"
        self.rpc_url = url
        self.rpc = Aria2Client(url, secret)
        self.interval = interval
        self.connected = False
        self.version = ""
        self.last_error = ""
        self.default_directory = ""
        self.downloads: dict[str, Download] = {}
        self.selected_gid = ""
        self.list_signature: tuple[tuple[str, str], ...] | None = None
        self.pending_remove_gid = ""
        self.refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        theme_icon = "☾" if self.color_mode == "dark" else "☀"
        with Horizontal(id="topbar"):
            yield Static(f"ARIA2  /  DESK  {theme_icon}", id="brand")
            yield Static(id="endpoint")
            yield Static(id="connection")
        yield Static(id="summary")
        with Horizontal(id="workspace"):
            yield ListView(id="downloads")
            yield DetailPanel(self.palette, id="details")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#downloads", ListView).border_title = "DOWNLOADS"
        self.query_one("#details", DetailPanel).border_title = "DETAIL"
        parsed = urlparse(self.rpc_url)
        self.query_one("#endpoint", Static).update(
            Text(parsed.netloc or self.rpc_url, style=self.palette.faint)
        )
        self._update_connection()
        self.poll()

    async def on_unmount(self) -> None:
        await self.rpc.close()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (
            len(self.screen_stack) > 1
            and action in {"quit", "add_download", "toggle_pause", "remove_download"}
        )

    @work(exclusive=True, group="poll")
    async def poll(self) -> None:
        while True:
            await self.refresh_downloads()
            await asyncio.sleep(self.interval)

    async def refresh_downloads(self) -> None:
        async with self.refresh_lock:
            try:
                if not self.version:
                    version = await self.rpc.get_version()
                    self.version = str(version.get("version", ""))
                if not self.default_directory:
                    options = await self.rpc.get_global_option()
                    self.default_directory = str(options.get("dir", ""))

                active, waiting, stopped = await asyncio.gather(
                    self.rpc.tell_active(),
                    self.rpc.tell_waiting(),
                    self.rpc.tell_stopped(),
                )
                ordered = [*active, *waiting, *stopped]
                self.downloads = {download.gid: download for download in ordered}
                self.connected = True
                self.last_error = ""
                await self._sync_list(ordered)
            except (Aria2RPCError, OSError) as exc:
                self.connected = False
                self.last_error = str(exc)
                self.version = ""
                await self._show_offline()
            finally:
                self._update_chrome()
                self._update_detail()

    async def _sync_list(self, downloads: list[Download]) -> None:
        list_view = self.query_one("#downloads", ListView)
        signature = tuple((download.gid, download.status) for download in downloads)
        if signature != self.list_signature:
            selected = self.selected_gid
            await list_view.remove_children()
            if downloads:
                await list_view.mount_all(
                    DownloadItem(download, self.palette) for download in downloads
                )
                gids = [download.gid for download in downloads]
                index = gids.index(selected) if selected in gids else 0
                list_view.index = index
                self.selected_gid = gids[index]
            else:
                await list_view.mount(
                    ListItem(
                        Static(
                            Text(
                                "No downloads yet.\nPress a to add a URL or magnet.",
                                style=self.palette.dim,
                            ),
                            id="empty-state",
                        )
                    )
                )
                self.selected_gid = ""
            self.list_signature = signature
            if list_view.children:
                list_view.focus()
        else:
            for download in downloads:
                try:
                    item = list_view.query_one(
                        f"#download-{download.gid}", DownloadItem
                    )
                except NoMatches:
                    continue
                item.update_download(download, self.palette)

    async def _show_offline(self) -> None:
        if self.downloads:
            return
        list_view = self.query_one("#downloads", ListView)
        if self.list_signature == ():
            return
        await list_view.remove_children()
        await list_view.mount(
            ListItem(
                Static(
                    Text(
                        "Cannot reach aria2.\n"
                        "Check that the RPC service is running and try again.",
                        style=self.palette.error,
                    ),
                    id="empty-state",
                )
            )
        )
        self.list_signature = ()
        self.selected_gid = ""

    def _update_connection(self) -> None:
        widget = self.query_one("#connection", Static)
        if self.connected:
            widget.update(
                Text.assemble(
                    ("● ", self.palette.active),
                    ("CONNECTED", f"bold {self.palette.active}"),
                )
            )
        elif self.last_error:
            widget.update(
                Text.assemble(
                    ("● ", self.palette.error),
                    ("OFFLINE", f"bold {self.palette.error}"),
                )
            )
        else:
            widget.update(
                Text.assemble(
                    ("● ", self.palette.paused),
                    ("CONNECTING", f"bold {self.palette.paused}"),
                )
            )

    def _update_chrome(self) -> None:
        self._update_connection()
        active = sum(d.status == "active" for d in self.downloads.values())
        waiting = sum(
            d.status in {"waiting", "paused"} for d in self.downloads.values()
        )
        done = sum(d.status == "complete" for d in self.downloads.values())
        failed = sum(d.status == "error" for d in self.downloads.values())
        speed = sum(
            d.download_speed for d in self.downloads.values() if d.status == "active"
        )

        summary = Text(no_wrap=True, overflow="ellipsis")
        if not self.connected and self.last_error:
            summary.append("  ! ", style=f"bold {self.palette.error}")
            summary.append(self.last_error, style=self.palette.error)
        else:
            summary.append("  v", style=f"bold {self.palette.accent}")
            summary.append(self.version or "--", style=self.palette.dim)
            summary.append("     ")
            _summary_metric(
                summary,
                "●",
                active,
                "ACTIVE",
                self.palette.active,
                self.palette.dim,
            )
            _summary_metric(
                summary,
                "◷",
                waiting,
                "QUEUED",
                self.palette.waiting,
                self.palette.dim,
            )
            _summary_metric(
                summary,
                "✓",
                done,
                "DONE",
                self.palette.complete,
                self.palette.dim,
            )
            if failed:
                _summary_metric(
                    summary,
                    "×",
                    failed,
                    "ERROR",
                    self.palette.error,
                    self.palette.dim,
                )
            summary.append("     ↓ ", style=f"bold {self.palette.accent}")
            summary.append(f"{human_bytes(speed)}/s", style=f"bold {self.palette.text}")
        self.query_one("#summary", Static).update(summary)

    def _update_detail(self) -> None:
        download = self.downloads.get(self.selected_gid)
        self.query_one("#details", DetailPanel).update_download(
            download,
            connected=self.connected,
            error=self.last_error,
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if isinstance(item, DownloadItem):
            self.selected_gid = item.download.gid
            self._update_detail()

    def selected_download(self) -> Download | None:
        return self.downloads.get(self.selected_gid)

    def action_add_download(self) -> None:
        default_dir = self.default_directory
        if not default_dir and self.downloads:
            default_dir = next(iter(self.downloads.values())).directory
        self.push_screen(
            AddDownloadScreen(default_dir),
            callback=self._on_add_result,
        )

    def _on_add_result(self, request: AddRequest | None) -> None:
        if request is not None:
            self.run_worker(
                self._add_download(request),
                exclusive=True,
                group="action",
            )

    async def _add_download(self, request: AddRequest) -> None:
        try:
            await self.rpc.add_uri(request.uri, request.directory)
            self.notify("Download added.", title="aria2")
        except Aria2RPCError as exc:
            self.notify(str(exc), title="Could not add download", severity="error")
        await self.refresh_downloads()

    async def action_toggle_pause(self) -> None:
        download = self.selected_download()
        if download is None:
            return
        try:
            if download.status == "paused":
                await self.rpc.unpause(download.gid)
                self.notify(f"Resumed {download.name}", title="aria2")
            elif download.status in {"active", "waiting"}:
                await self.rpc.pause(download.gid)
                self.notify(f"Paused {download.name}", title="aria2")
            else:
                self.notify("Only active, queued, or paused tasks can be toggled.")
        except Aria2RPCError as exc:
            self.notify(str(exc), title="aria2 error", severity="error")
        await self.refresh_downloads()

    def action_remove_download(self) -> None:
        download = self.selected_download()
        if download is None:
            return
        self.pending_remove_gid = download.gid
        if download.status in {"complete", "error", "removed"}:
            message = (
                f"Remove “{download.name}” from aria2 history?\n\n"
                "Files already downloaded will stay on disk."
            )
        else:
            message = (
                f"Stop and remove “{download.name}”?\n\n"
                "Files already downloaded will stay on disk."
            )
        self.push_screen(
            ConfirmScreen("REMOVE DOWNLOAD", message),
            callback=self._on_remove_result,
        )

    def _on_remove_result(self, confirmed: bool | None) -> None:
        if confirmed and self.pending_remove_gid:
            self.run_worker(
                self._remove_download(self.pending_remove_gid),
                exclusive=True,
                group="action",
            )
        self.pending_remove_gid = ""

    async def _remove_download(self, gid: str) -> None:
        download = self.downloads.get(gid)
        try:
            if download and download.status in {"complete", "error", "removed"}:
                await self.rpc.remove_download_result(gid)
            else:
                await self.rpc.remove(gid)
            self.notify("Task removed.", title="aria2")
        except Aria2RPCError as exc:
            self.notify(str(exc), title="aria2 error", severity="error")
        await self.refresh_downloads()

    async def action_refresh_now(self) -> None:
        await self.refresh_downloads()


def _summary_metric(
    text: Text,
    icon: str,
    value: int,
    label: str,
    color: str,
    label_color: str,
) -> None:
    text.append(f"{icon} ", style=f"bold {color}")
    text.append(str(value), style=f"bold {color}")
    text.append(f" {label}   ", style=label_color)


def _status_color(status: str, palette: Palette) -> str:
    if status == "active":
        return palette.active
    if status == "waiting":
        return palette.waiting
    if status == "paused":
        return palette.paused
    if status == "complete":
        return palette.complete
    if status == "error":
        return palette.error
    if status == "removed":
        return palette.removed
    return palette.muted


def _display_uri(uri: str) -> str:
    if uri.startswith("magnet:"):
        return "magnet link"
    parts = urlsplit(uri)
    try:
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        host = ""
        port = None
    if parts.scheme and host:
        if port:
            host = f"{host}:{port}"
        filename = parts.path.rstrip("/").rsplit("/", 1)[-1]
        path = f"/…/{filename}" if filename else "/"
        return urlunsplit((parts.scheme, host, path, "", ""))
    return uri.split("?", 1)[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aria2-tui",
        description="Minimal terminal UI for aria2 JSON-RPC.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("ARIA2_RPC_URL", "http://127.0.0.1:6800/jsonrpc"),
        help="aria2 JSON-RPC URL (env: ARIA2_RPC_URL)",
    )
    parser.add_argument(
        "--secret",
        default=os.environ.get("ARIA2_RPC_SECRET", ""),
        help="aria2 RPC secret (env: ARIA2_RPC_SECRET)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="refresh interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--theme",
        choices=("auto", "dark", "light"),
        default=os.environ.get("ARIA2_TUI_THEME", "auto"),
        help="color mode: auto, dark, or light (env: ARIA2_TUI_THEME)",
    )
    parser.add_argument("--version", action="version", version="aria2-tui 0.2.0")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.interval < 0.25:
        parser.error("--interval must be at least 0.25 seconds")
    if args.theme not in {"auto", "dark", "light"}:
        parser.error("ARIA2_TUI_THEME must be auto, dark, or light")
    color_mode = resolve_color_mode(args.theme)
    Aria2App(
        url=args.url,
        secret=args.secret,
        interval=args.interval,
        color_mode=color_mode,
    ).run()


if __name__ == "__main__":
    main()
