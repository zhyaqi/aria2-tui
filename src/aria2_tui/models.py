from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOWNLOAD_KEYS = [
    "gid",
    "status",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "uploadSpeed",
    "connections",
    "numPieces",
    "pieceLength",
    "errorMessage",
    "files",
    "bittorrent",
    "dir",
]


@dataclass(frozen=True, slots=True)
class Download:
    gid: str
    status: str
    total_length: int
    completed_length: int
    download_speed: int
    upload_speed: int
    connections: int
    name: str
    directory: str
    uri: str
    file_count: int
    error_message: str

    @classmethod
    def from_rpc(cls, data: dict[str, Any]) -> Download:
        files = data.get("files") or []
        first_file = files[0] if files and isinstance(files[0], dict) else {}
        path = _clean_text(first_file.get("path", ""))
        uris = first_file.get("uris") or []
        uri = ""
        if uris and isinstance(uris[0], dict):
            uri = _clean_text(uris[0].get("uri", ""))

        bittorrent = data.get("bittorrent") or {}
        torrent_info = bittorrent.get("info") or {}
        name = _clean_text(torrent_info.get("name", ""))
        if not name and path:
            name = Path(path).name or Path(path).parent.name
        if not name and uri:
            name = uri.split("?", 1)[0].rsplit("/", 1)[-1]
        if not name:
            name = "Untitled download"

        return cls(
            gid=str(data.get("gid", "")),
            status=str(data.get("status", "unknown")),
            total_length=_as_int(data.get("totalLength")),
            completed_length=_as_int(data.get("completedLength")),
            download_speed=_as_int(data.get("downloadSpeed")),
            upload_speed=_as_int(data.get("uploadSpeed")),
            connections=_as_int(data.get("connections")),
            name=name,
            directory=_clean_text(data.get("dir", "")),
            uri=uri,
            file_count=len(files),
            error_message=_clean_text(data.get("errorMessage", "")),
        )

    @property
    def progress(self) -> float:
        if self.status == "complete":
            return 1.0
        if self.total_length <= 0:
            return 0.0
        return min(1.0, max(0.0, self.completed_length / self.total_length))

    @property
    def remaining_seconds(self) -> int | None:
        if self.download_speed <= 0 or self.total_length <= self.completed_length:
            return None
        return round((self.total_length - self.completed_length) / self.download_speed)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def human_bytes(value: int) -> str:
    size = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{size:.0f} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def human_duration(seconds: int | None) -> str:
    if seconds is None:
        return "--"
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"


STATUS_META: dict[str, tuple[str, str]] = {
    "active": ("↓", "ACTIVE"),
    "waiting": ("◷", "QUEUED"),
    "paused": ("Ⅱ", "PAUSED"),
    "complete": ("✓", "DONE"),
    "error": ("×", "ERROR"),
    "removed": ("−", "REMOVED"),
}


def status_meta(status: str) -> tuple[str, str]:
    return STATUS_META.get(status, ("·", status.upper()))
