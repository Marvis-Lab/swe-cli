import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols, LSPFileBuffer, ReferenceInSymbol
from swecli.core.context_engineering.tools.lsp.ls_cache import LanguageServerCache
from swecli.core.context_engineering.tools.lsp.ls_types import UnifiedSymbolInformation, SymbolKind, Location, Range, Position

class TestLSStructs:
    def test_document_symbols_initialization(self):
        root_symbol = UnifiedSymbolInformation(
            name="test",
            kind=SymbolKind.Class,
            location=Location(uri="test", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="test", relativePath="test"),
            children=[],
            range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)),
            selectionRange=Range(start=Position(line=0, character=0), end=Position(line=1, character=0))
        )
        ds = DocumentSymbols([root_symbol])
        assert ds.root_symbols == [root_symbol]
        assert ds._all_symbols is None

    def test_document_symbols_iteration(self):
        child_symbol = UnifiedSymbolInformation(
            name="child",
            kind=SymbolKind.Method,
            location=Location(uri="test", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="test", relativePath="test"),
            children=[],
            range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)),
            selectionRange=Range(start=Position(line=0, character=0), end=Position(line=1, character=0))
        )
        root_symbol = UnifiedSymbolInformation(
            name="root",
            kind=SymbolKind.Class,
            location=Location(uri="test", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="test", relativePath="test"),
            children=[child_symbol],
            range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)),
            selectionRange=Range(start=Position(line=0, character=0), end=Position(line=1, character=0))
        )
        ds = DocumentSymbols([root_symbol])
        symbols = list(ds.iter_symbols())
        assert len(symbols) == 2
        assert symbols[0] == root_symbol
        assert symbols[1] == child_symbol

    def test_lsp_file_buffer(self):
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents="line1\nline2",
            version=1,
            language_id="python",
            ref_count=1
        )
        assert buffer.split_lines() == ["line1", "line2"]
        assert buffer.content_hash  # Check hash is generated

class TestLSCache:
    @pytest.fixture
    def cache(self, tmp_path):
        return LanguageServerCache(tmp_path / "cache", "v1")

    def test_cache_save_load_raw_symbols(self, cache):
        symbols = [{"name": "test", "kind": 1}]
        cache.set_raw_document_symbols("file.py", "hash1", symbols)
        assert cache.get_raw_document_symbols("file.py", "hash1") == symbols
        assert cache.get_raw_document_symbols("file.py", "hash2") is None

    def test_cache_save_load_document_symbols(self, cache):
        root_symbol = UnifiedSymbolInformation(
            name="test",
            kind=SymbolKind.Class,
            location=Location(uri="test", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="test", relativePath="test"),
            children=[],
            range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)),
            selectionRange=Range(start=Position(line=0, character=0), end=Position(line=1, character=0))
        )
        ds = DocumentSymbols([root_symbol])
        cache.set_document_symbols("file.py", "hash1", ds)
        loaded_ds = cache.get_document_symbols("file.py", "hash1")
        assert loaded_ds is not None
        assert loaded_ds.root_symbols[0]["name"] == "test"
