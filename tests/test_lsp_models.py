import pickle
from swecli.core.context_engineering.tools.lsp.ls_models import DocumentSymbols, LSPFileBuffer, ReferenceInSymbol
from swecli.core.context_engineering.tools.lsp import ls_types

def test_lsp_file_buffer_hash():
    content = "hello world"
    buffer = LSPFileBuffer(
        uri="file:///test.py",
        contents=content,
        version=1,
        language_id="python",
        ref_count=1
    )
    assert buffer.content_hash is not None
    assert len(buffer.content_hash) > 0
    assert buffer.split_lines() == ["hello world"]

def test_document_symbols_serialization():
    root_symbols = [
        ls_types.UnifiedSymbolInformation(
            name="test",
            kind=ls_types.SymbolKind.Function,
            children=[]
        )
    ]
    doc_symbols = DocumentSymbols(root_symbols)

    # Check _all_symbols is None initially
    assert doc_symbols._all_symbols is None

    # Populate _all_symbols
    all_syms, roots = doc_symbols.get_all_symbols_and_roots()
    assert len(all_syms) == 1
    assert doc_symbols._all_symbols is not None

    # Pickle
    dumped = pickle.dumps(doc_symbols)

    # Unpickle
    loaded = pickle.loads(dumped)

    # Check _all_symbols is None after unpickle (transient)
    assert loaded._all_symbols is None
    assert len(loaded.root_symbols) == 1
    assert loaded.root_symbols[0]["name"] == "test"

    # Check we can re-populate
    all_syms_loaded, _ = loaded.get_all_symbols_and_roots()
    assert len(all_syms_loaded) == 1

def test_reference_in_symbol():
    symbol = ls_types.UnifiedSymbolInformation(
        name="test",
        kind=ls_types.SymbolKind.Function,
        children=[]
    )
    ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)
    assert ref.symbol == symbol
    assert ref.line == 10
    assert ref.character == 5
