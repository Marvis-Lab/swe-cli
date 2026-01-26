import dataclasses
import hashlib
from collections.abc import Iterator
from typing import Union

from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler import lsp_types as LSPTypes

GenericDocumentSymbol = Union[LSPTypes.DocumentSymbol, LSPTypes.SymbolInformation, ls_types.UnifiedSymbolInformation]


@dataclasses.dataclass(kw_only=True)
class ReferenceInSymbol:
    """A symbol retrieved when requesting reference to a symbol, together with the location of the reference"""

    symbol: ls_types.UnifiedSymbolInformation
    line: int
    character: int


@dataclasses.dataclass
class LSPFileBuffer:
    """
    This class is used to store the contents of an open LSP file in memory.
    """

    # uri of the file
    uri: str

    # The contents of the file
    contents: str

    # The version of the file
    version: int

    # The language id of the file
    language_id: str

    # reference count of the file
    ref_count: int

    content_hash: str = ""

    def __post_init__(self) -> None:
        self.content_hash = hashlib.md5(self.contents.encode("utf-8")).hexdigest()

    def split_lines(self) -> list[str]:
        """Splits the contents of the file into lines."""
        return self.contents.split("\n")


class DocumentSymbols:
    # IMPORTANT: Instances of this class are persisted in the high-level document symbol cache

    def __init__(self, root_symbols: list[ls_types.UnifiedSymbolInformation]):
        self.root_symbols = root_symbols
        self._all_symbols: list[ls_types.UnifiedSymbolInformation] | None = None

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        if "_all_symbols" in state:
            del state["_all_symbols"]
        return state

    def __setstate__(self, state: dict):
        self.__dict__.update(state)
        self._all_symbols = None

    def iter_symbols(self) -> Iterator[ls_types.UnifiedSymbolInformation]:
        """
        Iterate over all symbols in the document symbol tree.
        Yields symbols in a depth-first manner.
        """
        if self._all_symbols is not None:
            yield from self._all_symbols
            return

        def traverse(s: ls_types.UnifiedSymbolInformation) -> Iterator[ls_types.UnifiedSymbolInformation]:
            yield s
            for child in s.get("children", []):
                yield from traverse(child)

        for root_symbol in self.root_symbols:
            yield from traverse(root_symbol)

    def get_all_symbols_and_roots(
        self,
    ) -> tuple[list[ls_types.UnifiedSymbolInformation], list[ls_types.UnifiedSymbolInformation]]:
        """
        This function returns all symbols in the document as a flat list and the root symbols.
        It exists to facilitate migration from previous versions, where this was the return interface of
        the LS method that obtained document symbols.

        :return: A tuple containing a list of all symbols in the document and a list of root symbols.
        """
        if self._all_symbols is None:
            self._all_symbols = list(self.iter_symbols())
        return self._all_symbols, self.root_symbols
