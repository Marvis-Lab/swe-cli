import pytest
from swecli.core.context_engineering.tools.lsp.ls_structs import LSPFileBuffer, DocumentSymbols, ReferenceInSymbol
from swecli.core.context_engineering.tools.lsp import ls_types

class TestLSPFileBuffer:
    def test_initialization(self):
        content = "hello\nworld"
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents=content,
            version=1,
            language_id="python",
            ref_count=1
        )
        assert buffer.content_hash == "9195d0beb2a889e1be05ed6bb1954837"
        assert buffer.uri == "file:///test.py"

    def test_split_lines(self):
        content = "line1\nline2\nline3"
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents=content,
            version=1,
            language_id="python",
            ref_count=1
        )
        assert buffer.split_lines() == ["line1", "line2", "line3"]

class TestDocumentSymbols:
    def test_iter_symbols(self):
        # Create a hierarchy: root -> child -> grandchild
        grandchild = ls_types.UnifiedSymbolInformation(
            name="grandchild",
            kind=1,
            children=[]
        )
        child = ls_types.UnifiedSymbolInformation(
            name="child",
            kind=2,
            children=[grandchild]
        )
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=3,
            children=[child]
        )

        ds = DocumentSymbols([root])

        symbols = list(ds.iter_symbols())
        assert len(symbols) == 3
        assert symbols[0]["name"] == "root"
        assert symbols[1]["name"] == "child"
        assert symbols[2]["name"] == "grandchild"

    def test_get_all_symbols_and_roots(self):
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=3,
            children=[]
        )
        ds = DocumentSymbols([root])

        all_syms, roots = ds.get_all_symbols_and_roots()
        assert len(all_syms) == 1
        assert len(roots) == 1
        assert all_syms[0] == root
        assert roots[0] == root

class TestReferenceInSymbol:
    def test_creation(self):
        symbol = ls_types.UnifiedSymbolInformation(
            name="test",
            kind=1,
            children=[]
        )
        ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)
        assert ref.symbol == symbol
        assert ref.line == 10
        assert ref.character == 5
