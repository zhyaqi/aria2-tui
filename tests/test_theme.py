from aria2_tui.theme import (
    color_mode_from_colorfgbg,
    parse_background_response,
    resolve_color_mode,
)


def test_parse_terminal_background_response() -> None:
    assert parse_background_response("\x1b]11;rgb:0000/0000/0000\x07") == "dark"
    assert parse_background_response("\x1b]11;rgb:ffff/ffff/ffff\x1b\\") == "light"
    assert parse_background_response("\x1b]11;rgb:f5f5/f5f5/f5f5\x07") == "light"
    assert parse_background_response("not a color response") is None


def test_colorfgbg_background_detection() -> None:
    assert color_mode_from_colorfgbg("15;0") == "dark"
    assert color_mode_from_colorfgbg("0;15") == "light"
    assert color_mode_from_colorfgbg("0;7") == "light"
    assert color_mode_from_colorfgbg("0;8") == "dark"
    assert color_mode_from_colorfgbg("invalid") is None


def test_auto_theme_uses_detected_color_mode(monkeypatch) -> None:
    monkeypatch.setattr("aria2_tui.theme.query_terminal_background", lambda: "light")
    assert resolve_color_mode("auto") == "light"
    assert resolve_color_mode("dark") == "dark"


def test_auto_theme_uses_system_fallback(monkeypatch) -> None:
    monkeypatch.setattr("aria2_tui.theme.query_terminal_background", lambda: None)
    monkeypatch.setattr("aria2_tui.theme.macos_system_color_mode", lambda: "light")
    monkeypatch.delenv("COLORFGBG", raising=False)
    assert resolve_color_mode("auto") == "light"
