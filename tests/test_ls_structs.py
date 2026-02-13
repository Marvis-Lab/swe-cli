
import dataclasses
import pytest
from swecli.core.context_engineering.tools.lsp import ls_structs, ls_types

def test_reference_in_symbol():
    symbol = ls_types.UnifiedSymbolInformation(
        name="test_symbol",
        kind=ls_types.SymbolKind.Function,
        location=ls_types.Location(
            uri="file:///test.py",
            range=ls_types.Range(
                start=ls_types.Position(line=0, character=0),
                end=ls_types.Position(line=1, character=0)
            ),
            absolutePath="/test.py",
            relativePath="test.py"
        ),
        children=[]
    )
    ref = ls_structs.ReferenceInSymbol(symbol=symbol, line=10, character=5)
    assert ref.symbol == symbol
    assert ref.line == 10
    assert ref.character == 5

def test_lsp_file_buffer():
    content = "line1\nline2"
    buffer = ls_structs.LSPFileBuffer(
        uri="file:///test.txt",
        contents=content,
        version=1,
        language_id="plaintext",
        ref_count=1
    )
    assert buffer.uri == "file:///test.txt"
    assert buffer.contents == content
    assert buffer.version == 1
    assert buffer.language_id == "plaintext"
    assert buffer.ref_count == 1
    assert buffer.content_hash is not None
    assert buffer.split_lines() == ["line1", "line2"]

def test_document_symbols():
    root_symbol = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=ls_types.SymbolKind.Class,
        location=ls_types.Location(
            uri="file:///test.py",
            range=ls_types.Range(
                start=ls_types.Position(line=0, character=0),
                end=ls_types.Position(line=10, character=0)
            ),
            absolutePath="/test.py",
            relativePath="test.py"
        ),
        children=[]
    )
    docs = ls_structs.DocumentSymbols(root_symbols=[root_symbol])

    assert docs.root_symbols == [root_symbol]

    symbols = list(docs.iter_symbols())
    assert len(symbols) == 1
    assert symbols[0] == root_symbol

    all_symbols, roots = docs.get_all_symbols_and_roots()
    assert all_symbols == symbols
    assert roots == [root_symbol]

def test_document_symbols_pickling():
    import pickle

    root_symbol = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=ls_types.SymbolKind.Class,
        location=ls_types.Location(
            uri="file:///test.py",
            range=ls_types.Range(
                start=ls_types.Position(line=0, character=0),
                end=ls_types.Position(line=10, character=0)
            ),
            absolutePath="/test.py",
            relativePath="test.py"
        ),
        children=[]
    )
    docs = ls_structs.DocumentSymbols(root_symbols=[root_symbol])
    # Force _all_symbols population
    docs.get_all_symbols_and_roots()
    assert docs._all_symbols is not None

    pickled = pickle.dumps(docs)
    unpickled = pickle.loads(pickled)

    # Check that transient property is None after unpickling
    assert unpickled._all_symbols is None
    assert unpickled.root_symbols == [root_symbol]

    # Check that it repopulates correctly
    all_syms, roots = unpickled.get_all_symbols_and_roots()
    assert len(all_syms) == 1
    assert roots == [root_symbol]
