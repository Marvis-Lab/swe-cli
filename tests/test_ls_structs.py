"""Tests for extracted LSP structures."""

import pytest
from swecli.core.context_engineering.tools.lsp.ls_structs import (
    DocumentSymbols,
    LSPFileBuffer,
    ReferenceInSymbol,
)
from swecli.core.context_engineering.tools.lsp import ls_types


class TestLSPFileBuffer:
    """Tests for LSPFileBuffer."""

    def test_hashing(self):
        """Test that content hash is calculated correctly."""
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents="hello world",
            version=1,
            language_id="python",
            ref_count=1,
        )
        assert buffer.content_hash == "5eb63bbbe01eeed093cb22bb8f5acdc3"  # md5("hello world")

    def test_split_lines(self):
        """Test split_lines method."""
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents="hello\nworld",
            version=1,
            language_id="python",
            ref_count=1,
        )
        assert buffer.split_lines() == ["hello", "world"]


class TestDocumentSymbols:
    """Tests for DocumentSymbols."""

    def test_iter_symbols(self):
        """Test iterating over symbols."""
        # Create a simple tree
        child = ls_types.UnifiedSymbolInformation(
            name="child",
            kind=ls_types.SymbolKind.Function,
            location=ls_types.Location(
                uri="file:///test.py",
                range={"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 0}},
                absolutePath="/test.py",
                relativePath="test.py",
            ),
            children=[],
        )
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=ls_types.SymbolKind.Class,
            location=ls_types.Location(
                uri="file:///test.py",
                range={"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}},
                absolutePath="/test.py",
                relativePath="test.py",
            ),
            children=[child],
        )

        doc_symbols = DocumentSymbols([root])

        symbols = list(doc_symbols.iter_symbols())
        assert len(symbols) == 2
        assert symbols[0] == root
        assert symbols[1] == child

    def test_get_all_symbols_and_roots(self):
        """Test getting all symbols and roots."""
        child = ls_types.UnifiedSymbolInformation(
            name="child",
            kind=ls_types.SymbolKind.Function,
            location=ls_types.Location(
                uri="file:///test.py",
                range={"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 0}},
                absolutePath="/test.py",
                relativePath="test.py",
            ),
            children=[],
        )
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=ls_types.SymbolKind.Class,
            location=ls_types.Location(
                uri="file:///test.py",
                range={"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}},
                absolutePath="/test.py",
                relativePath="test.py",
            ),
            children=[child],
        )

        doc_symbols = DocumentSymbols([root])

        all_syms, roots = doc_symbols.get_all_symbols_and_roots()
        assert len(all_syms) == 2
        assert len(roots) == 1
        assert roots[0] == root

    def test_pickling(self):
        """Test pickling behavior (excluding _all_symbols)."""
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=ls_types.SymbolKind.Class,
            location=ls_types.Location(
                uri="file:///test.py",
                range={"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}},
                absolutePath="/test.py",
                relativePath="test.py",
            ),
            children=[],
        )

        doc_symbols = DocumentSymbols([root])
        # Populate _all_symbols
        doc_symbols.get_all_symbols_and_roots()
        assert doc_symbols._all_symbols is not None

        # Get state for pickling
        state = doc_symbols.__getstate__()

        assert "_all_symbols" not in state
        assert "root_symbols" in state
