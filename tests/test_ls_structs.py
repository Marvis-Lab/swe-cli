from swecli.core.context_engineering.tools.lsp.ls_structs import LSPFileBuffer, DocumentSymbols, ReferenceInSymbol, GenericDocumentSymbol
from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler import lsp_types as LSPTypes

def test_imports():
    assert LSPFileBuffer
    assert DocumentSymbols
    assert ReferenceInSymbol
    assert GenericDocumentSymbol

def test_lsp_file_buffer():
    buf = LSPFileBuffer(uri="file://test", contents="hello\nworld", version=1, language_id="python", ref_count=1)
    assert buf.content_hash is not None
    assert len(buf.split_lines()) == 2

def test_document_symbols():
    # Mocking UnifiedSymbolInformation
    symbol = ls_types.UnifiedSymbolInformation(
        name="test",
        kind=ls_types.SymbolKind.Class,
        location=ls_types.Location(
            uri="file://test",
            range={"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 0}},
            absolutePath="/test",
            relativePath="test"
        ),
        children=[]
    )

    ds = DocumentSymbols([symbol])
    assert list(ds.iter_symbols()) == [symbol]
