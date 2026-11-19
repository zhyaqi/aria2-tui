from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import termios
import tty
from dataclasses import asdict, dataclass
from typing import Literal

from textual.theme import Theme

ColorMode = Literal["dark", "light"]
ThemeMode = Literal["auto", "dark", "light"]


@dataclass(frozen=True, slots=True)
class Palette:
    background: str
    panel: str
    card: str
    selected: str
    border: str
    text: str
    body: str
    muted: str
    dim: str
    faint: str
    divider: str
    accent: str
    accent_foreground: str
    active: str
    waiting: str
    paused: str
    complete: str
    error: str
    removed: str
    input: str
    button: str
    veil: str


DARK_PALETTE = Palette(
    background="#090c11",
    panel="#0c1017",
    card="#10151e",
    selected="#172131",
    border="#252d3a",
    text="#edf2f7",
    body="#cbd5e1",
    muted="#8290a5",
    dim="#627083",
    faint="#4b5768",
    divider="#3f4a5a",
    accent="#5eead4",
    accent_foreground="#06221f",
    active="#5eead4",
    waiting="#93c5fd",
    paused="#fbbf24",
    complete="#86efac",
    error="#fb7185",
    removed="#64748b",
    input="#090d13",
    button="#111822",
    veil="#000000 65%",
)

LIGHT_PALETTE = Palette(
    background="#f4f7f9",
    panel="#ffffff",
    card="#ffffff",
    selected="#e2f3f0",
    border="#d8e1e8",
    text="#172033",
    body="#344054",
    muted="#667085",
    dim="#7b8798",
    faint="#98a2b3",
    divider="#cbd5e1",
    accent="#0f766e",
    accent_foreground="#ffffff",
    active="#0f766e",
    waiting="#2563eb",
    paused="#b45309",
    complete="#15803d",
    error="#dc2626",
    removed="#667085",
    input="#f8fafc",
    button="#eef2f6",
    veil="#0f172a 30%",
)

PALETTES: dict[ColorMode, Palette] = {
    "dark": DARK_PALETTE,
    "light": LIGHT_PALETTE,
}


def _theme(name: str, palette: Palette, *, dark: bool) -> Theme:
    variables = {
        f"aria-{key.replace('_', '-')}": value for key, value in asdict(palette).items()
    }
    return Theme(
        name=name,
        primary=palette.accent,
        secondary=palette.waiting,
        warning=palette.paused,
        error=palette.error,
        success=palette.complete,
        accent=palette.accent,
        foreground=palette.body,
        background=palette.background,
        surface=palette.card,
        panel=palette.panel,
        dark=dark,
        variables=variables,
    )


ARIA2_DARK_THEME = _theme("aria2-dark", DARK_PALETTE, dark=True)
ARIA2_LIGHT_THEME = _theme("aria2-light", LIGHT_PALETTE, dark=False)


_BACKGROUND_RESPONSE = re.compile(
    r"\x1b\]11;rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})(?:\x07|\x1b\\)"
)


def parse_background_response(response: str) -> ColorMode | None:
    match = _BACKGROUND_RESPONSE.search(response)
    if match is None:
        return None
    channels = [int(value, 16) / ((16 ** len(value)) - 1) for value in match.groups()]
    luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    return "light" if luminance >= 0.5 else "dark"


def color_mode_from_colorfgbg(value: str) -> ColorMode | None:
    try:
        background_index = int(value.rsplit(";", 1)[-1])
    except (AttributeError, ValueError):
        return None
    return "light" if background_index == 7 or background_index >= 9 else "dark"


def macos_system_color_mode() -> ColorMode | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return "dark" if result.stdout.strip() == "Dark" else "light"
    if "does not exist" in result.stderr:
        return "light"
    return None


def query_terminal_background(timeout: float = 0.25) -> ColorMode | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    if os.environ.get("TERM") == "dumb":
        return None

    fd = sys.stdin.fileno()
    try:
        previous = termios.tcgetattr(fd)
    except (OSError, termios.error):
        return None

    response = ""
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b]11;?\x1b\\")
        sys.stdout.flush()
        while "\x07" not in response and "\x1b\\" not in response:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                break
            chunk = os.read(fd, 1024)
            if not chunk:
                break
            response += chunk.decode("utf-8", errors="replace")
    except OSError:
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
    return parse_background_response(response)


def resolve_color_mode(mode: ThemeMode) -> ColorMode:
    if mode != "auto":
        return mode
    detected = query_terminal_background()
    if detected is not None:
        return detected
    from_env = color_mode_from_colorfgbg(os.environ.get("COLORFGBG", ""))
    return from_env or macos_system_color_mode() or "dark"
