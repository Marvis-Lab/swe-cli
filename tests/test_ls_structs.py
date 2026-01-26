
import pickle
import pytest
from swecli.core.context_engineering.tools.lsp.ls_structs import (
    DocumentSymbols,
    LSPFileBuffer,
    ReferenceInSymbol,
)
from swecli.core.context_engineering.tools.lsp import ls_types


class TestLSPFileBuffer:
    def test_initialization(self):
        buf = LSPFileBuffer(
            uri="file:///test.py",
            contents="hello\nworld",
            version=1,
            language_id="python",
            ref_count=1,
        )
        assert buf.uri == "file:///test.py"
        assert buf.contents == "hello\nworld"
        assert buf.version == 1
        assert buf.language_id == "python"
        assert buf.ref_count == 1
        # Check that hash is computed in post_init
        assert buf.content_hash != ""

    def test_split_lines(self):
        buf = LSPFileBuffer(
            uri="file:///test.py",
            contents="hello\nworld",
            version=1,
            language_id="python",
            ref_count=1,
        )
        assert buf.split_lines() == ["hello", "world"]


class TestReferenceInSymbol:
    def test_initialization(self):
        # minimal mock of UnifiedSymbolInformation
        symbol = {"name": "test"}
        ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)
        assert ref.symbol == symbol
        assert ref.line == 10
        assert ref.character == 5


class TestDocumentSymbols:
    def test_iter_symbols(self):
        child = ls_types.UnifiedSymbolInformation(name="child", kind=1, location={}, children=[])
        root = ls_types.UnifiedSymbolInformation(name="root", kind=1, location={}, children=[child])

        ds = DocumentSymbols([root])

        symbols = list(ds.iter_symbols())
        assert len(symbols) == 2
        assert symbols[0]["name"] == "root"
        assert symbols[1]["name"] == "child"

    def test_get_all_symbols_and_roots(self):
        child = ls_types.UnifiedSymbolInformation(name="child", kind=1, location={}, children=[])
        root = ls_types.UnifiedSymbolInformation(name="root", kind=1, location={}, children=[child])

        ds = DocumentSymbols([root])

        all_symbols, roots = ds.get_all_symbols_and_roots()

        assert len(roots) == 1
        assert roots[0]["name"] == "root"

        assert len(all_symbols) == 2
        assert all_symbols[0]["name"] == "root"
        assert all_symbols[1]["name"] == "child"

        # Verify cache population
        assert ds._all_symbols is not None

    def test_pickling(self):
        """Test that DocumentSymbols can be pickled and unpickled, and transient properties are handled correctly."""
        child = ls_types.UnifiedSymbolInformation(name="child", kind=1, location={}, children=[])
        root = ls_types.UnifiedSymbolInformation(name="root", kind=1, location={}, children=[child])

        ds = DocumentSymbols([root])

        # Populate cache
        ds.get_all_symbols_and_roots()
        assert ds._all_symbols is not None

        # Pickle
        pickled_data = pickle.dumps(ds)

        # Unpickle
        ds_restored = pickle.loads(pickled_data)

        # Check that transient property is None
        assert ds_restored._all_symbols is None
        assert len(ds_restored.root_symbols) == 1
        assert ds_restored.root_symbols[0]["name"] == "root"

        # Check that we can re-populate cache
        all_symbols, _ = ds_restored.get_all_symbols_and_roots()
        assert len(all_symbols) == 2
