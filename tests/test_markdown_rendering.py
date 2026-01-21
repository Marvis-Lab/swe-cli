"""Tests for markdown rendering helpers used by Textual and CLI output."""

from rich.text import Text

from swecli.ui_textual.renderers.markdown import render_markdown_text_segment
from swecli.ui_textual.formatters_internal.markdown_formatter import markdown_to_plain_text


def _render_plain(content: str, leading: bool = False) -> list[str]:
    renderables, _ = render_markdown_text_segment(content, leading=leading)
    plains: list[str] = []
    for renderable in renderables:
        if isinstance(renderable, Text):
            plains.append(renderable.plain)
        else:
            plains.append(str(renderable))
    return plains


def test_heading_rendering():
    plains = _render_plain("# Title")
    # Headings now have 4 spaces of indentation (2 extra + 2 standard)
    assert plains == ["    Title"]


def test_nested_bullet_rendering():
    plains = _render_plain("- item\n  - sub item")
    # Bullets now have standard 2-space indent plus bullet prefix
    # Root: "  " + "  - " = "    - " (but leading bullet removes 2 spaces) = "  - item"
    # Nested: "  " + "    - " = "        - sub item" (8 spaces before dash)
    assert plains == ["  - item", "        - sub item"]


def test_blockquote_rendering():
    plains = _render_plain("> quoted text")
    # Blockquotes now have standard 2-space indent
    assert plains == ["  ❝ quoted text"]


def test_horizontal_rule_rendering():
    plains = _render_plain("---")
    # Horizontal rules now have standard 2-space indent
    assert plains == ["  ────────────────────────────────────────"]


def test_ordered_list_rendering():
    plains = _render_plain("1. first\n   1. nested")
    # Ordered lists have standard 2-space indent
    # Nested: "  " + "  " * 1 + "– " = "     – nested" (5 spaces before dash)
    assert plains == ["1. first", "     – nested"]


def test_markdown_to_plain_text_alignment():
    content = """# Heading

- First
  - Nested
> Quote here
"""
    result = markdown_to_plain_text(content)
    lines = [line for line in result.splitlines() if line]
    assert "HEADING" in lines[0]
    assert "• First" in lines[1]
    assert "  – Nested" in lines[2]
    assert lines[-1].startswith(" ❝ Quote")


def test_leading_bullet_with_response_starting_with_bullets():
    """Test that the leading bullet (⏺) appears on the first bullet when response starts with bullets."""
    plains = _render_plain("- First item\n- Second item\n- Third item", leading=True)
    # First bullet should have the leading bullet
    assert plains[0].startswith("⏺")
    assert "First item" in plains[0]
    # Subsequent bullets should NOT have the leading bullet
    assert not plains[1].startswith("⏺")
    assert "Second item" in plains[1]
    assert not plains[2].startswith("⏺")
    assert "Third item" in plains[2]


def test_leading_bullet_with_paragraph_then_bullets():
    """Test that the leading bullet (⏺) appears on the paragraph, not on bullets."""
    plains = _render_plain("Some paragraph\n- First item\n- Second item", leading=True)
    # First paragraph should have the leading bullet
    assert plains[0].startswith("⏺")
    assert "Some paragraph" in plains[0]
    # Bullets should NOT have the leading bullet
    assert not plains[1].startswith("⏺")
    assert "First item" in plains[1]


def test_leading_bullet_with_ordered_list():
    """Test that the leading bullet (⏺) appears on the first ordered item when response starts with list."""
    plains = _render_plain("1. First item\n2. Second item\n3. Third item", leading=True)
    # First item should have the leading bullet
    assert plains[0].startswith("⏺")
    assert "First item" in plains[0]
    # Subsequent items should NOT have the leading bullet
    assert not plains[1].startswith("⏺")
    assert "Second item" in plains[1]


def test_leading_bullet_not_on_nested_bullets():
    """Test that the leading bullet only appears on root-level bullets, not nested ones."""
    plains = _render_plain("  - Nested item\n- Root item", leading=True)
    # First bullet is nested (indent_level > 0), should NOT get leading bullet
    assert not plains[0].startswith("⏺")
    # Root level bullet should get the leading bullet
    assert plains[1].startswith("⏺")
    assert "Root item" in plains[1]
