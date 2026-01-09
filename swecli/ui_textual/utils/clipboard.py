"""Clipboard utilities for text selection in Textual TUI.

Ported from mistral-vibe with support for:
- OSC52 (works in SSH, tmux, remote sessions)
- X11 clipboard (xclip)
- Wayland clipboard (wl-copy)
- pyperclip fallback
- Textual's native copy_to_clipboard
"""

from __future__ import annotations

import base64
from collections.abc import Callable
import os
import platform
import shutil
import subprocess

from textual.app import App

_PREVIEW_MAX_LENGTH = 40


def _copy_osc52(text: str) -> None:
    """Copy text using OSC52 escape sequence (works over SSH/tmux)."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    osc52_seq = f"\033]52;c;{encoded}\a"
    if os.environ.get("TMUX"):
        osc52_seq = f"\033Ptmux;\033{osc52_seq}\033\\"

    with open("/dev/tty", "w") as tty:
        tty.write(osc52_seq)
        tty.flush()


def _copy_x11_clipboard(text: str) -> None:
    """Copy text using xclip (X11 systems)."""
    subprocess.run(
        ["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True
    )


def _copy_wayland_clipboard(text: str) -> None:
    """Copy text using wl-copy (Wayland systems)."""
    subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True)


def _has_cmd(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def _get_copy_fns(app: App) -> list[Callable[[str], None]]:
    """Get list of clipboard copy functions in priority order."""
    try:
        import pyperclip
        copy_fns: list[Callable[[str], None]] = [
            _copy_osc52,
            pyperclip.copy,
            app.copy_to_clipboard,
        ]
    except ImportError:
        copy_fns = [
            _copy_osc52,
            app.copy_to_clipboard,
        ]

    if platform.system() == "Linux" and _has_cmd("wl-copy"):
        copy_fns = [_copy_wayland_clipboard, *copy_fns]
    if platform.system() == "Linux" and _has_cmd("xclip"):
        copy_fns = [_copy_x11_clipboard, *copy_fns]
    return copy_fns


def _shorten_preview(texts: list[str]) -> str:
    """Create a shortened preview of selected text for notification."""
    dense_text = " ".join(texts).replace("\n", " ")
    if len(dense_text) > _PREVIEW_MAX_LENGTH:
        return f"{dense_text[: _PREVIEW_MAX_LENGTH - 1]}..."
    return dense_text


def copy_selection_to_clipboard(app: App) -> None:
    """Copy selected text from any widget to clipboard.

    Iterates through all widgets looking for text_selection,
    combines selected text, and copies using multiple fallback methods.
    Shows notification on success/failure.
    """
    selected_texts = []

    for widget in app.query("*"):
        if not hasattr(widget, "text_selection") or not widget.text_selection:
            continue

        selection = widget.text_selection

        try:
            result = widget.get_selection(selection)
        except Exception:
            continue

        if not result:
            continue

        selected_text, _ = result
        if selected_text.strip():
            selected_texts.append(selected_text)

    if not selected_texts:
        return

    combined_text = "\n".join(selected_texts)

    success = False
    copy_fns = _get_copy_fns(app)

    for copy_fn in copy_fns:
        try:
            copy_fn(combined_text)
        except Exception:
            pass
        else:
            success = True

    if success:
        app.notify(
            f'"{_shorten_preview(selected_texts)}" copied to clipboard',
            severity="information",
            timeout=2,
        )
    else:
        app.notify(
            "Failed to copy - no clipboard method available",
            severity="warning",
            timeout=3,
        )
