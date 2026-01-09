"""Markdown-to-rich rendering helpers used by the conversation log."""

from __future__ import annotations

import re
from typing import List, Tuple

from rich.console import RenderableType
from rich.text import Text

from swecli.ui_textual.style_tokens import SUBTLE, PRIMARY, GREEN_BRIGHT, ACCENT


def render_markdown_text_segment(content: str, *, leading: bool = False) -> Tuple[List[RenderableType], bool]:
    """Convert markdown text into Rich renderables.

    Args:
        content: The text segment to render (code fences already stripped).
        leading: If True, the first non-empty block will be prefixed with ``⏺``.

    Returns:
        A tuple of (renderables, wrote_any) where ``wrote_any`` indicates whether
        any non-empty content was emitted (used to manage leading bullets).
    """

    lines = content.splitlines()
    total_lines = len(lines)
    index = 0
    renderables: List[RenderableType] = []
    wrote_any = False
    leading_consumed = not leading
    indent = "   "  # 3-space indentation for readability

    def emit(renderable: RenderableType, allow_leading: bool = True) -> None:
        nonlocal wrote_any, leading_consumed
        if isinstance(renderable, str):
            renderable = Text(renderable)
        if leading and not leading_consumed and allow_leading and getattr(renderable, "plain", str(renderable)).strip():
            bullet = Text("⏺ ")
            bullet.append_text(renderable if isinstance(renderable, Text) else Text(str(renderable)))
            renderables.append(bullet)
            leading_consumed = True
        else:
            # Add indentation to non-leading lines
            if isinstance(renderable, Text):
                indented = Text(indent)
                indented.append_text(renderable)
                renderables.append(indented)
            else:
                renderables.append(renderable)
            if leading and allow_leading and not leading_consumed:
                text_value = getattr(renderable, "plain", str(renderable))
                if text_value.strip():
                    leading_consumed = True
        text_plain = getattr(renderable, "plain", str(renderable))
        if text_plain.strip():
            wrote_any = True

    def blank_line() -> None:
        if wrote_any:
            emit(Text(""), allow_leading=False)

    def is_heading(line: str) -> bool:
        return bool(re.match(r"^(#{1,6})\s+", line.strip()))

    def is_bullet(line: str) -> bool:
        return bool(re.match(r"^\s*[-*+]\s+", line))

    def is_ordered(line: str) -> bool:
        return bool(re.match(r"^\s*\d+\.\s+", line))

    while index < total_lines:
        raw_line = lines[index]
        stripped = raw_line.strip()

        if not stripped:
            blank_line()
            index += 1
            continue

        if re.fullmatch(r"^[\-\*_]{3,}$", stripped):
            hr = Text("─" * 40, style=SUBTLE)
            emit(hr, allow_leading=False)
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            rendered = _render_inline_markdown(title)
            style = "bold underline" if level == 1 else "bold"
            rendered.stylize(style)
            emit(rendered)
            index += 1
            continue

        if stripped.startswith(">"):
            quote_lines: List[str] = []
            while index < total_lines and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].lstrip("> ").rstrip())
                index += 1
            quote_text = " ".join(quote_lines).strip()
            if quote_text:
                rendered = _render_inline_markdown(quote_text)
                quote_line = Text("❝ ", style=SUBTLE)
                rendered.stylize("dim italic")
                quote_line.append_text(rendered)
                emit(quote_line, allow_leading=False)
            continue

        bullet_match = re.match(r"^(\s*)[-*+]\s+(.*)", raw_line)
        if bullet_match:
            bullet_indent = bullet_match.group(1) or ""
            bullet_text = bullet_match.group(2).strip()
            rendered = _render_inline_markdown(bullet_text)
            indent_level = max(0, len(bullet_indent) // 2)
            bullet_line = Text()
            # emit() adds base indent, so just add dash here
            symbol = "- " if indent_level == 0 else "  - "
            bullet_line.append("  " * indent_level + symbol)
            bullet_line.append_text(rendered)
            emit(bullet_line, allow_leading=False)
            index += 1
            continue

        ordered_match = re.match(r"^(\s*)(\d+)\.\s+(.*)", raw_line)
        if ordered_match:
            ordered_indent = ordered_match.group(1) or ""
            number = ordered_match.group(2)
            item_text = ordered_match.group(3).strip()
            rendered = _render_inline_markdown(item_text)
            indent_level = max(0, len(ordered_indent) // 2)
            ordered_line = Text()
            # emit() adds base indent, so just add number here
            if indent_level == 0:
                ordered_line.append(f"{number}. ")
            else:
                ordered_line.append("  " * indent_level + "– ")
            ordered_line.append_text(rendered)
            emit(ordered_line, allow_leading=False)
            index += 1
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < total_lines:
            probe = lines[index]
            probe_stripped = probe.strip()
            if not probe_stripped:
                break
            if (
                is_heading(probe)
                or is_bullet(probe)
                or is_ordered(probe)
                or probe_stripped.startswith(">")
            ):
                break
            paragraph_lines.append(probe_stripped)
            index += 1

        paragraph = " ".join(paragraph_lines).strip()
        if paragraph:
            rendered = _render_inline_markdown(paragraph)
            emit(rendered)

        while index < total_lines and not lines[index].strip():
            blank_line()
            index += 1

    return renderables, wrote_any


def _render_inline_markdown(text: str) -> Text:
    """Render inline markdown markers within a single line."""

    result = Text()
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    inline_pattern = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`)")

    def append_with_style(fragment: str) -> None:
        cursor = 0
        for token_match in inline_pattern.finditer(fragment):
            if token_match.start() > cursor:
                result.append(fragment[cursor : token_match.start()])
            token = token_match.group(0)
            inner = token.strip("*`_")
            if token.startswith(("**", "__")):
                result.append(inner, style="bold")
            elif token.startswith(("*", "_")):
                result.append(inner, style="italic")
            elif token.startswith("`"):
                result.append(inner, style=GREEN_BRIGHT)
            else:
                result.append(inner)
            cursor = token_match.end()
        if cursor < len(fragment):
            result.append(fragment[cursor:])

    cursor = 0
    for match in link_pattern.finditer(text):
        if match.start() > cursor:
            append_with_style(text[cursor : match.start()])
        label, url = match.group(1), match.group(2)
        result.append(label, style=f"bold {ACCENT}")
        if url:
            result.append(f" ({url})", style=SUBTLE)
        cursor = match.end()

    if cursor < len(text):
        append_with_style(text[cursor:])

    if not result:
        append_with_style(text)

    return result
