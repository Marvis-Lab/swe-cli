from pathlib import Path
from unittest.mock import MagicMock, patch

from swecli.core.context_engineering.tools.lsp.ls_cache import LanguageServerCache
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler.lsp_types import DocumentSymbol


def test_ls_cache_init(tmp_path):
    """Test initialization of LanguageServerCache."""
    cache_dir = tmp_path / "cache"
    cache = LanguageServerCache(cache_dir, "v1")

    assert cache.cache_dir == cache_dir
    assert cache._ls_specific_raw_document_symbols_cache_version == "v1"
    assert cache_dir.exists()


def test_ls_cache_raw_document_symbols(tmp_path):
    """Test caching of raw document symbols."""
    cache = LanguageServerCache(tmp_path, "v1")
    cache_key = "test.py"
    file_hash = "hash123"
    symbols = [DocumentSymbol(name="test", kind=1, range={}, selectionRange={})]  # type: ignore

    # Test update
    cache.update_raw_document_symbols(cache_key, file_hash, symbols)
    assert cache._raw_document_symbols_cache[cache_key] == (file_hash, symbols)
    assert cache._raw_document_symbols_cache_is_modified is True

    # Test get hit
    assert cache.get_raw_document_symbols(cache_key, file_hash) == symbols

    # Test get miss (wrong hash)
    assert cache.get_raw_document_symbols(cache_key, "wrong_hash") is None

    # Test get miss (not in cache)
    assert cache.get_raw_document_symbols("other.py", file_hash) is None


def test_ls_cache_document_symbols(tmp_path):
    """Test caching of processed document symbols."""
    cache = LanguageServerCache(tmp_path, "v1")
    cache_key = "test.py"
    file_hash = "hash123"
    symbols = DocumentSymbols([])

    # Test update
    cache.update_document_symbols(cache_key, file_hash, symbols)
    assert cache._document_symbols_cache[cache_key] == (file_hash, symbols)
    assert cache._document_symbols_cache_is_modified is True

    # Test get hit
    assert cache.get_document_symbols(cache_key, file_hash) == symbols

    # Test get miss (wrong hash)
    assert cache.get_document_symbols(cache_key, "wrong_hash") is None

    # Test get miss (not in cache)
    assert cache.get_document_symbols("other.py", file_hash) is None


@patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache")
def test_ls_cache_save(mock_save_cache, tmp_path):
    """Test saving cache to disk."""
    cache = LanguageServerCache(tmp_path, "v1")
    cache.update_raw_document_symbols("test.py", "hash1", [])
    cache.update_document_symbols("test.py", "hash1", DocumentSymbols([]))

    cache.save()

    assert mock_save_cache.call_count == 2
    assert cache._raw_document_symbols_cache_is_modified is False
    assert cache._document_symbols_cache_is_modified is False
