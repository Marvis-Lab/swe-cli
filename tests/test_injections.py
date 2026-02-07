"""Tests for the prompt injections module."""

import pytest

from swecli.core.agents.prompts.injections import get_injection, _parse_sections


class TestParseSections:
    """Tests for section parsing from injections.txt."""

    def test_all_expected_sections_present(self):
        """Every expected section name is parsed."""
        sections = _parse_sections()
        expected = [
            "thinking_analysis_prompt",
            "thinking_trace_injection",
            "subagent_complete_signal",
            "failed_tool_nudge",
            "consecutive_reads_nudge",
            "safety_limit_summary",
            "episodic_memory_header",
            "short_term_memory_header",
            "thinking_on_instruction",
            "thinking_off_instruction",
            "incomplete_todos_nudge",
        ]
        for name in expected:
            assert name in sections, f"Missing section: {name}"

    def test_sections_are_non_empty(self):
        """No section should be empty after parsing."""
        sections = _parse_sections()
        for name, content in sections.items():
            assert content.strip(), f"Section {name!r} is empty"


class TestGetInjection:
    """Tests for get_injection() accessor."""

    # --- Simple lookups (no placeholders) ---

    def test_thinking_analysis_prompt(self):
        result = get_injection("thinking_analysis_prompt")
        assert "Analyze the context" in result

    def test_failed_tool_nudge(self):
        result = get_injection("failed_tool_nudge")
        assert "failed" in result.lower()
        assert "task_complete" in result

    def test_consecutive_reads_nudge(self):
        result = get_injection("consecutive_reads_nudge")
        assert "summarize" in result.lower()

    def test_safety_limit_summary(self):
        result = get_injection("safety_limit_summary")
        assert "summary" in result.lower()

    def test_subagent_complete_signal(self):
        result = get_injection("subagent_complete_signal")
        assert "<subagent_complete>" in result
        assert "DO NOT" in result

    def test_thinking_on_instruction(self):
        result = get_injection("thinking_on_instruction")
        assert "THINKING MODE IS ON" in result
        assert "think" in result.lower()

    def test_thinking_off_instruction(self):
        result = get_injection("thinking_off_instruction")
        assert "simple tasks" in result.lower()

    # --- Placeholder substitution ---

    def test_episodic_memory_header(self):
        result = get_injection("episodic_memory_header", summary="Test summary here")
        assert "Test summary here" in result
        assert "episodic memory" in result.lower()

    def test_short_term_memory_header(self):
        result = get_injection("short_term_memory_header", short_term="recent messages")
        assert "recent messages" in result
        assert "short-term memory" in result.lower()

    def test_thinking_trace_injection(self):
        trace = "Step 1: analyze. Step 2: act."
        result = get_injection("thinking_trace_injection", thinking_trace=trace)
        assert trace in result
        assert "<thinking_trace>" in result

    def test_incomplete_todos_nudge(self):
        result = get_injection(
            "incomplete_todos_nudge",
            count="3",
            todo_list="  \u2022 task A\n  \u2022 task B\n  \u2022 task C",
        )
        assert "3 incomplete todo(s)" in result
        assert "task A" in result
        assert "Please complete" in result

    # --- File fallback (standalone .txt files) ---

    def test_docker_preamble(self):
        result = get_injection("docker_preamble", working_dir="/workspace")
        assert "/workspace" in result
        assert "DOCKER CONTAINER" in result

    def test_docker_context(self):
        result = get_injection("docker_context", workspace_dir="/testbed")
        assert "/testbed" in result
        assert "DOCKER CONTAINER" in result

    def test_custom_agent_default(self):
        result = get_injection("custom_agent_default", name="MyAgent", description="Does things")
        assert "MyAgent" in result
        assert "Does things" in result

    # --- Error handling ---

    def test_unknown_injection_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown injection"):
            get_injection("nonexistent_injection_name")

    def test_no_kwargs_returns_raw_template(self):
        """Calling without kwargs returns the raw template with placeholders."""
        result = get_injection("episodic_memory_header")
        assert "{summary}" in result
