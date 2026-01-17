import hashlib
from swecli.core.context_engineering.tools.lsp.ls_structs import LSPFileBuffer, DocumentSymbols, ReferenceInSymbol
from swecli.core.context_engineering.tools.lsp import ls_types

def test_lsp_file_buffer_initialization():
    uri = "file:///test.py"
    contents = "def foo():\n    pass"
    version = 1
    language_id = "python"
    ref_count = 1

    buffer = LSPFileBuffer(uri=uri, contents=contents, version=version, language_id=language_id, ref_count=ref_count)

    assert buffer.uri == uri
    assert buffer.contents == contents
    assert buffer.version == version
    assert buffer.language_id == language_id
    assert buffer.ref_count == ref_count
    assert buffer.content_hash == hashlib.md5(contents.encode("utf-8")).hexdigest()

def test_lsp_file_buffer_split_lines():
    contents = "line1\nline2\nline3"
    buffer = LSPFileBuffer(uri="file:///test.txt", contents=contents, version=1, language_id="plaintext", ref_count=1)

    lines = buffer.split_lines()
    assert lines == ["line1", "line2", "line3"]

def test_document_symbols_iteration():
    # Setup some dummy symbols
    child_symbol = ls_types.UnifiedSymbolInformation(
        name="child",
        kind=ls_types.SymbolKind.Function,
        location=ls_types.Location(uri="file:///test.py", range={"start": {"line": 1, "character": 0}, "end": {"line": 2, "character": 0}}, absolutePath="/test.py", relativePath="test.py"),
        children=[]
    )

    root_symbol = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=ls_types.SymbolKind.Class,
        location=ls_types.Location(uri="file:///test.py", range={"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}}, absolutePath="/test.py", relativePath="test.py"),
        children=[child_symbol]
    )

    doc_symbols = DocumentSymbols(root_symbols=[root_symbol])

    # Test iteration (depth-first)
    symbols = list(doc_symbols.iter_symbols())
    assert len(symbols) == 2
    assert symbols[0] == root_symbol
    assert symbols[1] == child_symbol

def test_document_symbols_getstate():
    root_symbol = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=ls_types.SymbolKind.Class,
        location=ls_types.Location(uri="file:///test.py", range={"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}}, absolutePath="/test.py", relativePath="test.py"),
        children=[]
    )
    doc_symbols = DocumentSymbols(root_symbols=[root_symbol])

    # Force _all_symbols to be populated via get_all_symbols_and_roots
    doc_symbols.get_all_symbols_and_roots()
    assert doc_symbols._all_symbols is not None

    # Check that _all_symbols is excluded from state (transient)
    state = doc_symbols.__getstate__()
    assert "_all_symbols" not in state
    assert "root_symbols" in state
    assert state["root_symbols"] == [root_symbol]

def test_reference_in_symbol_initialization():
    symbol = ls_types.UnifiedSymbolInformation(
        name="ref",
        kind=ls_types.SymbolKind.Variable,
        location=ls_types.Location(uri="file:///test.py", range={"start": {"line": 5, "character": 0}, "end": {"line": 5, "character": 10}}, absolutePath="/test.py", relativePath="test.py"),
        children=[]
    )
    ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)

    assert ref.symbol == symbol
    assert ref.line == 10
    assert ref.character == 5
