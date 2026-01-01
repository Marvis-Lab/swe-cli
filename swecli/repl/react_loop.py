"""ReAct loop control flow and safety mechanisms."""


class ReActController:
    """Controls ReAct loop flow with safety limits and nudging."""

    def __init__(self, console):
        """Initialize ReAct controller.

        Args:
            console: Rich console for output
        """
        self.console = console

    def handle_safety_limit(self, agent, messages: list):
        """Handle safety limit reached by requesting summary.

        Args:
            agent: Agent to use
            messages: Message history
        """
        self.console.print("\n[yellow]⚠ Safety limit reached. Requesting summary...[/yellow]")
        messages.append({
            "role": "user",
            "content": "Please provide a summary of what you've found and what needs to be done."
        })
        response = agent.call_llm(messages)
        if response.get("content"):
            self.console.print()
            self._print_markdown_message(response["content"])

    def should_nudge_agent(self, consecutive_reads: int, messages: list) -> bool:
        """Check if agent should be nudged to conclude.

        Args:
            consecutive_reads: Number of consecutive read operations
            messages: Message history

        Returns:
            True if nudge was added
        """
        if consecutive_reads >= 5:
            # Silently nudge the agent without displaying a message
            messages.append({
                "role": "user",
                "content": "Based on what you've seen, please summarize your findings and explain what needs to be done next."
            })
            return True
        return False

    def _print_markdown_message(self, content: str):
        """Print a markdown-formatted message.

        Args:
            content: Message content to print
        """
        from rich.markdown import Markdown
        self.console.print(Markdown(content))
