from rich.text import Text
from textual.strip import Strip
from rich.console import Console

# Tree connector characters
TREE_BRANCH = "├─"
TREE_LAST = "└─"
TREE_VERTICAL = "│"
TREE_CONTINUATION = "⎿"

def text_to_strip(text: Text) -> Strip:
    """Convert Rich Text to Textual Strip."""
    console = Console(width=1000, force_terminal=True, no_color=False)
    segments = list(text.render(console))
    return Strip(segments)
