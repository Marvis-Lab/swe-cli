import hashlib
from typing import cast

import pytest
from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols, LSPFileBuffer, ReferenceInSymbol


class TestLSPFileBuffer:
    def test_init_and_hash(self):
        """Test initialization and content hashing."""
        content = "hello\nworld"
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents=content,
            version=1,
            language_id="python",
            ref_count=1
        )

        expected_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        assert buffer.content_hash == expected_hash
        assert buffer.uri == "file:///test.py"
        assert buffer.version == 1
        assert buffer.language_id == "python"

    def test_split_lines(self):
        """Test splitting content into lines."""
        content = "line1\nline2\nline3"
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents=content,
            version=1,
            language_id="python",
            ref_count=1
        )

        lines = buffer.split_lines()
        assert lines == ["line1", "line2", "line3"]


class TestReferenceInSymbol:
    def test_init(self):
        """Test ReferenceInSymbol initialization."""
        symbol = cast(ls_types.UnifiedSymbolInformation, {"name": "test", "kind": 1})
        ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)

        assert ref.symbol == symbol
        assert ref.line == 10
        assert ref.character == 5


class TestDocumentSymbols:
    def test_iter_symbols(self):
        """Test iterating over symbols including nested ones."""
        child_symbol = cast(ls_types.UnifiedSymbolInformation, {"name": "child", "children": []})
        root_symbol = cast(ls_types.UnifiedSymbolInformation, {"name": "root", "children": [child_symbol]})

        doc_symbols = DocumentSymbols([root_symbol])

        symbols = list(doc_symbols.iter_symbols())
        assert len(symbols) == 2
        assert symbols[0] == root_symbol
        assert symbols[1] == child_symbol

    def test_get_all_symbols_and_roots(self):
        """Test getting all symbols and roots."""
        child_symbol = cast(ls_types.UnifiedSymbolInformation, {"name": "child", "children": []})
        root_symbol = cast(ls_types.UnifiedSymbolInformation, {"name": "root", "children": [child_symbol]})

        doc_symbols = DocumentSymbols([root_symbol])

        all_symbols, roots = doc_symbols.get_all_symbols_and_roots()

        assert len(roots) == 1
        assert roots[0] == root_symbol

        assert len(all_symbols) == 2
        assert all_symbols[0] == root_symbol
        assert all_symbols[1] == child_symbol
