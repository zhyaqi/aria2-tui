from aria2_tui.models import Download, human_bytes, human_duration, status_meta


def test_download_from_rpc_and_progress() -> None:
    download = Download.from_rpc(
        {
            "gid": "abc123",
            "status": "active",
            "totalLength": "2048",
            "completedLength": "512",
            "downloadSpeed": "128",
            "uploadSpeed": "0",
            "connections": "3",
            "dir": "/Users/test/Downloads",
            "files": [
                {
                    "path": "/Users/test/Downloads/example.zip",
                    "uris": [{"uri": "https://example.com/example.zip"}],
                }
            ],
        }
    )

    assert download.gid == "abc123"
    assert download.name == "example.zip"
    assert download.progress == 0.25
    assert download.remaining_seconds == 12
    assert download.connections == 3
    assert download.uri == "https://example.com/example.zip"


def test_metadata_download_uses_torrent_name() -> None:
    download = Download.from_rpc(
        {
            "gid": "torrent",
            "status": "waiting",
            "totalLength": "0",
            "completedLength": "0",
            "files": [],
            "bittorrent": {"info": {"name": "Example Torrent"}},
        }
    )

    assert download.name == "Example Torrent"
    assert download.progress == 0
    assert download.remaining_seconds is None


def test_format_helpers() -> None:
    assert human_bytes(0) == "0 B"
    assert human_bytes(1024) == "1.0 KiB"
    assert human_bytes(1024**2) == "1.0 MiB"
    assert human_duration(None) == "--"
    assert human_duration(42) == "42s"
    assert human_duration(125) == "2m 05s"
    assert human_duration(7260) == "2h 01m"
    assert status_meta("active") == ("↓", "ACTIVE")
