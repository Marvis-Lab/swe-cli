"""Status bar and footer widgets for the SWE-CLI Textual UI."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Mapping

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Footer, Static


def _get_git_branch_in_thread(working_dir: str) -> str | None:
    """Get git branch in a separate thread to avoid Textual FD issues.

    Returns:
        Branch name or None if not a git repo
    """
    import os

    kwargs: dict = {
        "cwd": working_dir,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "close_fds": True,
    }

    if os.name != "nt":
        kwargs["start_new_session"] = True

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            timeout=2,
            **kwargs,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch and branch != "HEAD":
                return branch

        # Try symbolic-ref as fallback
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            timeout=2,
            **kwargs,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None

    except Exception:
        # Catch ALL exceptions including ValueError for FD issues
        pass

    return None


def _get_git_branch_safe(working_dir: str) -> str | None:
    """Get git branch using thread pool to avoid Textual FD issues.

    This function is designed to be safe to call from Textual's event loop.
    It runs subprocess in a separate thread with isolated file descriptors.
    If anything goes wrong, it returns None rather than raising.
    """
    import asyncio

    # Check if we're in an async context
    try:
        asyncio.get_running_loop()
        # We're in an async context (Textual) - subprocess may cause FD errors
        # Skip git branch detection entirely to avoid issues
        return None
    except RuntimeError:
        # No running loop - safe to call subprocess
        pass

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_get_git_branch_in_thread, working_dir)
            return future.result(timeout=3)
    except Exception:
        # Catch ANY error - git branch display is not critical
        return None


class StatusBar(Static):
    """Custom status bar showing mode, repo info, and hints."""

    def __init__(self, model: str = "claude-sonnet-4", working_dir: str = "", **kwargs):
        super().__init__(**kwargs)
        self.mode = "normal"
        self.model = model
        self.autonomy = "Manual"  # Autonomy level: Manual, Semi-Auto, Auto
        self.spinner_text: str | None = None
        self.spinner_tip: str | None = None
        self.working_dir = working_dir or ""
        self._git_branch = None

    def on_mount(self) -> None:
        """Update status on mount."""
        self.update_status()

    def set_mode(self, mode: str) -> None:
        """Update mode display."""
        self.mode = mode
        self.update_status()

    def set_model_name(self, model: str) -> None:
        """Update the displayed model name."""
        self.model = model
        self.update_status()

    def set_autonomy(self, level: str) -> None:
        """Update autonomy level display.

        Args:
            level: One of "Manual", "Semi-Auto", or "Auto"
        """
        self.autonomy = level
        self.update_status()

    def set_spinner(self, text: str, tip: str | None = None) -> None:
        """Display spinner status."""
        self.spinner_text = text
        if tip is not None:
            self.spinner_tip = tip
        self.update_status()

    def clear_spinner(self) -> None:
        """Clear spinner status."""
        self.spinner_text = None
        self.spinner_tip = None
        self.update_status()

    def update_status(self) -> None:
        """Update status bar text with mode hint, autonomy level, repo info, and spinner."""
        mode_color = "#ff8c00" if self.mode == "normal" else "#89d185"  # Orange for NORMAL
        status = Text()

        # Mode with cycling hint
        status.append("Mode: ", style="#6a6a6a")
        status.append(f"{self.mode.upper()}", style=f"bold {mode_color}")
        status.append(" (Shift+Tab)", style="#6a6a6a")

        # Autonomy level with color coding
        status.append("  │  ", style="#6a6a6a")
        status.append("Autonomy: ", style="#6a6a6a")
        autonomy_colors = {
            "Manual": "#ffa500",    # Orange - caution, needs attention
            "Semi-Auto": "#00bfff",  # Cyan - partial automation
            "Auto": "#00ff00",       # Green - fully automated
        }
        autonomy_color = autonomy_colors.get(self.autonomy, "#6a6a6a")
        status.append(self.autonomy, style=f"bold {autonomy_color}")
        status.append(" (Ctrl+Shift+A)", style="#6a6a6a")

        # Repo info
        repo_display = self._get_repo_display()
        if repo_display:
            status.append("  │  ", style="#6a6a6a")
            status.append(repo_display, style="#4a9eff")

        if self.spinner_text:
            status.append("  │  ", style="#6a6a6a")
            status.append(self.spinner_text, style="#4a9eff")

        self.update(status)

    def _get_repo_display(self) -> str:
        """Get a formatted repo display with path and git branch."""
        if not self.working_dir:
            return ""

        try:
            from pathlib import Path

            # Convert to Path for easier manipulation
            work_dir = Path(self.working_dir)

            # Get relative path from home directory
            home_dir = Path.home()
            if work_dir.is_relative_to(home_dir):
                # Show as ~/relative/path
                rel_path = work_dir.relative_to(home_dir)
                path_display = f"~/{rel_path}"
            else:
                # Use absolute path but shorten if too long
                path_display = str(work_dir)
                if len(path_display) > 30:
                    parts = path_display.split("/")
                    if len(parts) > 2:
                        # Show .../last/two/parts
                        path_display = f".../{'/'.join(parts[-2:])}"

            # Get git branch info using thread-safe helper
            branch = _get_git_branch_safe(self.working_dir)
            if branch:
                return f"{path_display} ({branch})"

            # Return just path if no git branch found
            return path_display

        except Exception:
            # Fallback to just showing the working directory
            return str(self.working_dir) if self.working_dir else ""

    def _get_short_model_name(self) -> str:
        """Get a very short model name for display."""
        if not self.model:
            return ""

        # If model contains a slash, take the last part
        if "/" in self.model:
            parts = self.model.split("/")
            model_part = parts[-1]
        else:
            model_part = self.model

        # If it's too long, truncate intelligently
        if len(model_part) > 15:
            # Remove common prefixes/suffixes
            model_part = model_part.replace("accounts/", "").replace("-instruct", "").replace("-latest", "")

            # Still too long? Take first 15 chars
            if len(model_part) > 15:
                model_part = model_part[:15] + "..."

        return model_part

    def _smart_truncate_model(self, model: str, max_len: int) -> str:
        """Smart model name truncation that preserves important parts."""
        if len(model) <= max_len:
            return model

        if "/" in model:
            parts = model.split("/")
            if len(parts) >= 2:
                provider = parts[0]
                model_name = parts[-1]
                simplified = f"{provider}/{model_name}"
                if len(simplified) <= max_len:
                    return simplified
                available = max_len - len(provider) - 1
                if available > 10:
                    return f"{provider}/{model_name[: available - 3]}..."

        return model[: max_len - 3] + "..."


class ModelFooter(Footer):
    """Footer variant that shows configured model slots alongside key hints."""

    def __init__(
        self,
        model_slots: Mapping[str, tuple[str, str]] | None = None,
        normal_model: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model_slots: dict[str, tuple[str, str]] = dict(model_slots or {})
        self._normal_model = normal_model
        self._models_label: Static | None = None

    def compose(self) -> ComposeResult:
        """Compose footer with model display prefix and inherited key hints."""
        self._models_label = Static(
            self._build_model_text(),
            classes="footer--models",
            expand=True,
        )
        yield self._models_label

        parent_compose = super().compose()
        if parent_compose is not None:
            yield from parent_compose

    def update_models(self, model_slots: Mapping[str, tuple[str, str]] | None) -> None:
        """Refresh displayed models."""
        self._model_slots = dict(model_slots or {})
        if self._models_label is not None:
            self._models_label.update(self._build_model_text())

    def set_normal_model(self, model: str) -> None:
        """Update normal model display."""
        self._normal_model = model
        if self._models_label is not None:
            self._models_label.update(self._build_model_text())

    def _build_model_text(self) -> Text:
        """Create comprehensive Rich text showing all models with providers."""
        base_style = "#6a6a6a"
        normal_style = "#00ff00"  # Green for normal
        thinking_style = "#FFD700"  # Gold for thinking
        vision_style = "#00CED1"  # Cyan for vision

        text = Text(no_wrap=True)

        def format_model_display(model_str: str, style: str) -> None:
            """Format a model with provider and name in a compact way."""
            if not model_str:
                text.append("Not set", style="italic #5a5a5a")
                return

            # Extract provider and model name
            if "/" in model_str:
                parts = model_str.split("/")
                if len(parts) >= 2:
                    provider = parts[0]
                    model_name = "/".join(parts[1:])  # Keep the full model path after provider
                else:
                    provider = parts[0]
                    model_name = ""
            else:
                provider = model_str
                model_name = ""

            # Format: provider/model (smartly shortened)
            if model_name:
                # Remove common prefixes
                model_name = model_name.replace("accounts/", "").replace("models/", "")
                # If model name is still too long, keep last part
                if len(model_name) > 30:
                    if "/" in model_name:
                        model_name = model_name.split("/")[-1]
                    else:
                        model_name = model_name[:27] + "..."

                display = f"{provider}/{model_name}"
            else:
                display = provider

            # If total display is too long, abbreviate
            if len(display) > 40:
                display = display[:37] + "..."

            text.append(display, style=style)

        # Show all three models on one line
        text.append("N: ", style=base_style)
        format_model_display(self._normal_model, normal_style)

        text.append("  │  ", style=base_style)
        text.append("T: ", style=base_style)

        thinking_slot = self._model_slots.get("thinking")
        if thinking_slot:
            provider, model = thinking_slot
            thinking_model = f"{provider}/{model}" if model else provider
        else:
            thinking_model = ""

        format_model_display(thinking_model, thinking_style)

        text.append("  │  ", style=base_style)
        text.append("V: ", style=base_style)

        vision_slot = self._model_slots.get("vision")
        if vision_slot:
            provider, model = vision_slot
            vision_model = f"{provider}/{model}" if model else provider
        else:
            vision_model = ""

        format_model_display(vision_model, vision_style)

        return text


__all__ = ["StatusBar", "ModelFooter"]
