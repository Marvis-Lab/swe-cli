from typing import Any, Protocol, runtime_checkable
from rich.text import Text
from textual.strip import Strip
from textual.geometry import Size

@runtime_checkable
class RichLogInterface(Protocol):
    """Interface for RichLog with line and timer access."""
    lines: list[Strip]
    virtual_size: Size
    auto_scroll: bool
    
    def write(self, renderable: Any, *args, **kwargs) -> None: ...
    def refresh_line(self, y: int) -> None: ...
    def scroll_end(self, animate: bool = True) -> None: ...
    def set_timer(self, delay: float, callback: Any, name: str | None = None) -> Any: ...

