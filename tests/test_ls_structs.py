import dataclasses
import hashlib
from typing import Generator
from unittest.mock import MagicMock

import pytest

from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.ls_structs import (
    DocumentSymbols,
    LSPFileBuffer,
    ReferenceInSymbol,
)
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler import lsp_types as LSPTypes


class TestLSPFileBuffer:
    def test_lsp_file_buffer_initialization(self) -> None:
        uri = "file:///path/to/file.py"
        contents = "def foo():\n    pass"
        version = 1
        language_id = "python"
        ref_count = 1

        buffer = LSPFileBuffer(
            uri=uri,
            contents=contents,
            version=version,
            language_id=language_id,
            ref_count=ref_count,
        )

        assert buffer.uri == uri
        assert buffer.contents == contents
        assert buffer.version == version
        assert buffer.language_id == language_id
        assert buffer.ref_count == ref_count
        assert buffer.content_hash == hashlib.md5(contents.encode("utf-8")).hexdigest()

    def test_split_lines(self) -> None:
        contents = "line1\nline2\nline3"
        buffer = LSPFileBuffer(
            uri="file:///file",
            contents=contents,
            version=1,
            language_id="python",
            ref_count=1,
        )
        assert buffer.split_lines() == ["line1", "line2", "line3"]


class TestReferenceInSymbol:
    def test_reference_in_symbol(self) -> None:
        symbol = MagicMock(spec=dict)
        line = 10
        character = 5

        ref = ReferenceInSymbol(symbol=symbol, line=line, character=character)

        assert ref.symbol == symbol
        assert ref.line == line
        assert ref.character == character


class TestDocumentSymbols:
    def test_document_symbols_initialization(self) -> None:
        root_symbols: list[ls_types.UnifiedSymbolInformation] = []
        doc_symbols = DocumentSymbols(root_symbols)
        assert doc_symbols.root_symbols == root_symbols
        assert doc_symbols._all_symbols is None

    def test_iter_symbols(self) -> None:
        # Create a mock symbol structure
        # Root -> Child1
        #      -> Child2 -> GrandChild

        grand_child = ls_types.UnifiedSymbolInformation(
            name="GrandChild",
            kind=1,
            location=MagicMock(),
            children=[]
        )
        child1 = ls_types.UnifiedSymbolInformation(
            name="Child1",
            kind=1,
            location=MagicMock(),
            children=[]
        )
        child2 = ls_types.UnifiedSymbolInformation(
            name="Child2",
            kind=1,
            location=MagicMock(),
            children=[grand_child]
        )
        root = ls_types.UnifiedSymbolInformation(
            name="Root",
            kind=1,
            location=MagicMock(),
            children=[child1, child2]
        )

        doc_symbols = DocumentSymbols([root])

        # Test iteration
        symbols = list(doc_symbols.iter_symbols())
        assert len(symbols) == 4
        assert symbols[0] == root
        assert symbols[1] == child1
        assert symbols[2] == child2
        assert symbols[3] == grand_child

    def test_get_all_symbols_and_roots(self) -> None:
        root = ls_types.UnifiedSymbolInformation(
            name="Root",
            kind=1,
            location=MagicMock(),
            children=[]
        )
        doc_symbols = DocumentSymbols([root])

        all_symbols, roots = doc_symbols.get_all_symbols_and_roots()

        assert roots == [root]
        assert all_symbols == [root]
        assert doc_symbols._all_symbols == all_symbols

    def test_getstate(self) -> None:
        root = ls_types.UnifiedSymbolInformation(
            name="Root",
            kind=1,
            location=MagicMock(),
            children=[]
        )
        doc_symbols = DocumentSymbols([root])
        # Populate _all_symbols
        doc_symbols.get_all_symbols_and_roots()
        assert doc_symbols._all_symbols is not None

        state = doc_symbols.__getstate__()

        # _all_symbols should be transient (not in state or reset)
        # Based on implementation of getstate helper, it might exclude it.
        # Let's check what getstate does.
        # If it uses default pickling behavior but excludes transient, then _all_symbols shouldn't be in state if we want to ignore it,
        # OR it should be set to None in state if we want it reset on load.

        # The getstate helper usually returns a dict.
        assert "_all_symbols" not in state or state["_all_symbols"] is None
