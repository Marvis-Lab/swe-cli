import pytest
from swecli.core.context_engineering.tools.lsp.ls_structs import (
    DocumentSymbols,
    LSPFileBuffer,
    ReferenceInSymbol,
)
from swecli.core.context_engineering.tools.lsp.ls_types import UnifiedSymbolInformation, SymbolKind, Location, Range, Position


def test_lsp_file_buffer_initialization():
    uri = "file:///path/to/file.py"
    contents = "line 1\nline 2"
    version = 1
    language_id = "python"
    ref_count = 1

    buffer = LSPFileBuffer(uri, contents, version, language_id, ref_count)

    assert buffer.uri == uri
    assert buffer.contents == contents
    assert buffer.version == version
    assert buffer.language_id == language_id
    assert buffer.ref_count == ref_count
    assert buffer.content_hash  # Should be computed in post_init


def test_lsp_file_buffer_split_lines():
    uri = "file:///path/to/file.py"
    contents = "line 1\nline 2"
    buffer = LSPFileBuffer(uri, contents, 1, "python", 1)

    lines = buffer.split_lines()
    assert lines == ["line 1", "line 2"]


def test_reference_in_symbol():
    loc = Location(uri="uri", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="/path", relativePath="path")
    symbol = UnifiedSymbolInformation(
        name="test_symbol",
        kind=SymbolKind.Function,
        location=loc,
        children=[]
    )

    ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)

    assert ref.symbol == symbol
    assert ref.line == 10
    assert ref.character == 5


def test_document_symbols_iterator():
    loc = Location(uri="uri", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="/path", relativePath="path")
    child = UnifiedSymbolInformation(
        name="child",
        kind=SymbolKind.Variable,
        location=loc,
        children=[]
    )
    root = UnifiedSymbolInformation(
        name="root",
        kind=SymbolKind.Class,
        location=loc,
        children=[child]
    )

    doc_symbols = DocumentSymbols([root])

    symbols_list = list(doc_symbols.iter_symbols())
    assert len(symbols_list) == 2
    assert symbols_list[0] == root
    assert symbols_list[1] == child


def test_document_symbols_get_all_symbols_and_roots():
    loc = Location(uri="uri", range=Range(start=Position(line=0, character=0), end=Position(line=1, character=0)), absolutePath="/path", relativePath="path")
    child = UnifiedSymbolInformation(
        name="child",
        kind=SymbolKind.Variable,
        location=loc,
        children=[]
    )
    root = UnifiedSymbolInformation(
        name="root",
        kind=SymbolKind.Class,
        location=loc,
        children=[child]
    )

    doc_symbols = DocumentSymbols([root])

    all_symbols, roots = doc_symbols.get_all_symbols_and_roots()

    assert len(all_symbols) == 2
    assert len(roots) == 1
    assert roots[0] == root
