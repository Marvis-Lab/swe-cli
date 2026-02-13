import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from swecli.core.context_engineering.tools.lsp.components.caching import SymbolCacheManager
from swecli.core.context_engineering.tools.lsp.ls_models import DocumentSymbols
from swecli.core.context_engineering.tools.lsp import ls_types

@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"

def test_symbol_cache_manager_init(cache_dir):
    manager = SymbolCacheManager(cache_dir)
    assert manager.cache_dir == cache_dir
    assert cache_dir.exists()

def test_raw_document_symbols_cache(cache_dir):
    manager = SymbolCacheManager(cache_dir)
    rel_path = "test.py"
    file_hash = "hash123"
    symbols = [{"name": "test", "kind": 1}] # Mock symbol

    # Initially empty
    assert manager.get_raw_document_symbols(rel_path, file_hash) is None

    # Update
    manager.update_raw_document_symbols(rel_path, file_hash, symbols)
    assert manager._raw_document_symbols_cache_is_modified is True

    # Retrieve
    retrieved = manager.get_raw_document_symbols(rel_path, file_hash)
    assert retrieved == symbols

    # Retrieve with different hash
    assert manager.get_raw_document_symbols(rel_path, "other_hash") is None

    # Save
    manager.save()
    assert manager._raw_document_symbols_cache_is_modified is False
    assert (cache_dir / SymbolCacheManager.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME).exists()

    # Load new manager
    new_manager = SymbolCacheManager(cache_dir)
    retrieved_new = new_manager.get_raw_document_symbols(rel_path, file_hash)
    assert retrieved_new == symbols

def test_document_symbols_cache(cache_dir):
    manager = SymbolCacheManager(cache_dir)
    rel_path = "test.py"
    file_hash = "hash123"

    root_symbols = [
        ls_types.UnifiedSymbolInformation(
            name="test",
            kind=ls_types.SymbolKind.Function,
            children=[]
        )
    ]
    doc_symbols = DocumentSymbols(root_symbols)

    # Update
    manager.update_document_symbols(rel_path, file_hash, doc_symbols)
    assert manager._document_symbols_cache_is_modified is True

    # Retrieve
    retrieved = manager.get_document_symbols(rel_path, file_hash)
    assert retrieved is not None
    assert retrieved.root_symbols[0]["name"] == "test"

    # Save
    manager.save()
    assert (cache_dir / SymbolCacheManager.DOCUMENT_SYMBOL_CACHE_FILENAME).exists()

    # Load new manager
    new_manager = SymbolCacheManager(cache_dir)
    retrieved_new = new_manager.get_document_symbols(rel_path, file_hash)
    assert retrieved_new is not None
    assert retrieved_new.root_symbols[0]["name"] == "test"
