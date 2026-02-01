import hashlib
import pickle
from swecli.core.context_engineering.tools.lsp.ls_models import LSPFileBuffer, DocumentSymbols
from swecli.core.context_engineering.tools.lsp import ls_types

def test_lsp_file_buffer_hash():
    content = "Hello\nWorld"
    buffer = LSPFileBuffer(
        uri="file:///test.txt",
        contents=content,
        version=1,
        language_id="text",
        ref_count=1
    )
    expected_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
    assert buffer.content_hash == expected_hash

def test_lsp_file_buffer_split_lines():
    content = "Hello\nWorld"
    buffer = LSPFileBuffer(
        uri="file:///test.txt",
        contents=content,
        version=1,
        language_id="text",
        ref_count=1
    )
    assert buffer.split_lines() == ["Hello", "World"]

def test_document_symbols_iteration():
    # Mock data
    child = ls_types.UnifiedSymbolInformation(
        name="child",
        kind=6, # Method
        location={"uri": "file", "range": {}, "absolutePath": "file", "relativePath": "file"},
        children=[]
    )
    root = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=5, # Class
        location={"uri": "file", "range": {}, "absolutePath": "file", "relativePath": "file"},
        children=[child]
    )

    ds = DocumentSymbols(root_symbols=[root])

    symbols = list(ds.iter_symbols())
    assert len(symbols) == 2
    assert symbols[0] == root
    assert symbols[1] == child

def test_document_symbols_pickling():
    child = ls_types.UnifiedSymbolInformation(
        name="child",
        kind=6,
        location={"uri": "file", "range": {}, "absolutePath": "file", "relativePath": "file"},
        children=[]
    )
    root = ls_types.UnifiedSymbolInformation(
        name="root",
        kind=5,
        location={"uri": "file", "range": {}, "absolutePath": "file", "relativePath": "file"},
        children=[child]
    )

    ds = DocumentSymbols(root_symbols=[root])

    # Populate cache
    all_syms, _ = ds.get_all_symbols_and_roots()
    assert ds._all_symbols is not None
    assert len(all_syms) == 2

    # Pickle
    pickled = pickle.dumps(ds)

    # Unpickle
    restored = pickle.loads(pickled)

    # Verify transient property is None
    assert restored._all_symbols is None
    assert restored.root_symbols == [root]

    # Verify we can regenerate
    all_syms_restored, roots_restored = restored.get_all_symbols_and_roots()
    assert len(all_syms_restored) == 2
    assert roots_restored == [root]
