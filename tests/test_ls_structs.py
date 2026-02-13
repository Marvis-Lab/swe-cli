import pickle
import pytest
from swecli.core.context_engineering.tools.lsp.ls_structs import (
    LSPFileBuffer,
    DocumentSymbols,
    ReferenceInSymbol,
)
from swecli.core.context_engineering.tools.lsp import ls_types

class TestLSPFileBuffer:
    def test_initialization(self):
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents="hello\nworld",
            version=1,
            language_id="python",
            ref_count=1
        )
        assert buffer.uri == "file:///test.py"
        assert buffer.contents == "hello\nworld"
        assert buffer.content_hash is not None
        assert len(buffer.content_hash) > 0

    def test_split_lines(self):
        buffer = LSPFileBuffer(
            uri="file:///test.py",
            contents="hello\nworld\n",
            version=1,
            language_id="python",
            ref_count=1
        )
        lines = buffer.split_lines()
        assert lines == ["hello", "world", ""]

class TestDocumentSymbols:
    def test_iter_symbols(self):
        # Create a tree of symbols
        # root -> child1
        #      -> child2 -> grandchild

        grandchild = ls_types.UnifiedSymbolInformation(
            name="grandchild",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[]
        )
        child2 = ls_types.UnifiedSymbolInformation(
            name="child2",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[grandchild]
        )
        child1 = ls_types.UnifiedSymbolInformation(
            name="child1",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[]
        )
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[child1, child2]
        )

        doc_symbols = DocumentSymbols([root])

        symbols = list(doc_symbols.iter_symbols())
        names = [s["name"] for s in symbols]

        # Expect depth-first traversal: root, child1, child2, grandchild
        expected_names = ["root", "child1", "child2", "grandchild"]
        assert names == expected_names

    def test_get_all_symbols_and_roots(self):
         root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[]
         )
         doc_symbols = DocumentSymbols([root])
         all_syms, roots = doc_symbols.get_all_symbols_and_roots()

         assert len(roots) == 1
         assert roots[0] == root
         assert len(all_syms) == 1
         assert all_syms[0] == root

    def test_pickle(self):
        root = ls_types.UnifiedSymbolInformation(
            name="root",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[]
        )
        doc_symbols = DocumentSymbols([root])

        # Populate _all_symbols
        doc_symbols.get_all_symbols_and_roots()
        assert doc_symbols._all_symbols is not None

        # Pickle
        dumped = pickle.dumps(doc_symbols)

        # Unpickle
        loaded = pickle.loads(dumped)

        # _all_symbols should be transient and None after loading
        assert loaded._all_symbols is None
        assert len(loaded.root_symbols) == 1
        assert loaded.root_symbols[0]["name"] == "root"

class TestReferenceInSymbol:
    def test_initialization(self):
        symbol = ls_types.UnifiedSymbolInformation(
            name="test",
            kind=1,
            location={"uri": "file:///test.py", "range": {}, "absolutePath": "/test.py", "relativePath": "test.py"},
            children=[]
        )
        ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)
        assert ref.symbol == symbol
        assert ref.line == 10
        assert ref.character == 5
