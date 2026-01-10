import dataclasses
import hashlib
from typing import Iterator

from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols, LSPFileBuffer, ReferenceInSymbol


def test_reference_in_symbol():
    """Test the ReferenceInSymbol dataclass."""
    symbol = ls_types.UnifiedSymbolInformation(
        name="test_symbol",
        kind=1,
        location=ls_types.Location(
            uri="file:///test/file.py",
            range=ls_types.Range(
                start=ls_types.Position(line=0, character=0),
                end=ls_types.Position(line=1, character=1),
            ),
            absolutePath="/test/file.py",
            relativePath="file.py",
        ),
        children=[],
    )
    ref = ReferenceInSymbol(symbol=symbol, line=10, character=5)

    assert ref.symbol == symbol
    assert ref.line == 10
    assert ref.character == 5
    assert dataclasses.is_dataclass(ref)


def test_lsp_file_buffer():
    """Test the LSPFileBuffer dataclass."""
    content = "line1\nline2\nline3"
    buffer = LSPFileBuffer(
        uri="file:///test/file.py",
        contents=content,
        version=1,
        language_id="python",
        ref_count=1,
    )

    assert buffer.uri == "file:///test/file.py"
    assert buffer.contents == content
    assert buffer.version == 1
    assert buffer.language_id == "python"
    assert buffer.ref_count == 1

    # Check post_init hash generation
    expected_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
    assert buffer.content_hash == expected_hash

    # Check split_lines
    assert buffer.split_lines() == ["line1", "line2", "line3"]


def test_document_symbols():
    """Test the DocumentSymbols class."""
    root_symbol = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=1,
        location=ls_types.Location(
            uri="file:///test/file.py",
            range=ls_types.Range(
                start=ls_types.Position(line=0, character=0),
                end=ls_types.Position(line=10, character=0),
            ),
            absolutePath="/test/file.py",
            relativePath="file.py",
        ),
        children=[],
    )

    child_symbol = ls_types.UnifiedSymbolInformation(
        name="child",
        kind=2,
        location=ls_types.Location(
            uri="file:///test/file.py",
            range=ls_types.Range(
                start=ls_types.Position(line=1, character=0),
                end=ls_types.Position(line=5, character=0),
            ),
            absolutePath="/test/file.py",
            relativePath="file.py",
        ),
        children=[],
    )

    root_symbol["children"].append(child_symbol)

    doc_symbols = DocumentSymbols([root_symbol])

    # Test __init__
    assert doc_symbols.root_symbols == [root_symbol]
    assert doc_symbols._all_symbols is None

    # Test iter_symbols
    symbols = list(doc_symbols.iter_symbols())
    assert len(symbols) == 2
    assert symbols[0] == root_symbol
    assert symbols[1] == child_symbol

    # Test get_all_symbols_and_roots (and implicit caching)
    all_syms, roots = doc_symbols.get_all_symbols_and_roots()
    assert roots == [root_symbol]
    assert len(all_syms) == 2
    assert doc_symbols._all_symbols is not None

    # Test __getstate__
    state = doc_symbols.__getstate__()
    assert "root_symbols" in state
    assert "_all_symbols" not in state
