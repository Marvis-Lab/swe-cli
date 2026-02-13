from rich.text import Text
from rich.console import Console
from textual.strip import Strip

# Tree connector characters
TREE_BRANCH = "├─"
TREE_LAST = "└─"
TREE_VERTICAL = "│"
TREE_CONTINUATION = "⎿"

def text_to_strip(text: Text) -> Strip:
    """Convert Text to Strip for line replacement.

    Args:
        text: Rich Text object to convert

    Returns:
        Strip object for use in log.lines
    """
    # Use a wide console to prevent premature wrapping
    console = Console(width=1000, force_terminal=True, no_color=False)
    segments = list(text.render(console))
    return Strip(segments)
