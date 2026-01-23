import pickle
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols, LSPFileBuffer
from swecli.core.context_engineering.tools.lsp.ls_types import UnifiedSymbolInformation, Location, Range, Position, SymbolKind

def test_document_symbols_pickling():
    # Create a dummy symbol
    location = Location(
        uri="file:///test.py",
        range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)),
        absolutePath="/test.py",
        relativePath="test.py"
    )
    symbol = UnifiedSymbolInformation(
        name="test_symbol",
        kind=SymbolKind.Function,
        location=location,
        children=[]
    )

    doc_symbols = DocumentSymbols([symbol])

    # Check initial state
    assert doc_symbols.root_symbols == [symbol]
    assert doc_symbols._all_symbols is None

    # Populate _all_symbols
    all_symbols, roots = doc_symbols.get_all_symbols_and_roots()
    assert doc_symbols._all_symbols is not None
    assert len(all_symbols) == 1

    # Pickle
    pickled = pickle.dumps(doc_symbols)

    # Unpickle
    unpickled = pickle.loads(pickled)

    # Check unpickled state
    assert unpickled.root_symbols == [symbol]
    assert unpickled._all_symbols is None # Should be None because it's transient

def test_lsp_file_buffer():
    buffer = LSPFileBuffer(
        uri="file:///test.py",
        contents="line1\nline2",
        version=1,
        language_id="python",
        ref_count=1
    )

    assert buffer.content_hash is not None
    assert buffer.split_lines() == ["line1", "line2"]
