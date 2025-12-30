import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from swecli.core.context_engineering.tools.lsp.ls_cache import LanguageServerCache
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols


@pytest.fixture
def temp_cache_dir(tmp_path):
    cache_dir = tmp_path / "lsp_cache"
    return cache_dir


class TestLanguageServerCache:
    def test_init_creates_dir(self, temp_cache_dir):
        cache = LanguageServerCache(temp_cache_dir)
        assert temp_cache_dir.exists()
        assert cache.cache_dir == temp_cache_dir

    def test_raw_document_symbols_cache(self, temp_cache_dir):
        cache = LanguageServerCache(temp_cache_dir)
        key = "test_file.py"
        value = ("hash123", [{"name": "test", "kind": 1}])

        cache.set_raw_document_symbols(key, value)
        assert cache._raw_document_symbols_cache_is_modified is True

        cached_value = cache.get_raw_document_symbols(key)
        assert cached_value == value

    def test_document_symbols_cache(self, temp_cache_dir):
        cache = LanguageServerCache(temp_cache_dir)
        key = "test_file.py"
        doc_symbols = MagicMock(spec=DocumentSymbols)
        value = ("hash123", doc_symbols)

        cache.set_document_symbols(key, value)
        assert cache._document_symbols_cache_is_modified is True

        cached_value = cache.get_document_symbols(key)
        assert cached_value == value

    @patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache")
    def test_save_cache(self, mock_save_cache, temp_cache_dir):
        cache = LanguageServerCache(temp_cache_dir)
        cache.set_raw_document_symbols("k", ("h", []))
        cache.set_document_symbols("k", ("h", MagicMock()))

        cache.save_cache()

        assert mock_save_cache.call_count == 2
        assert cache._raw_document_symbols_cache_is_modified is False
        assert cache._document_symbols_cache_is_modified is False

    @patch("swecli.core.context_engineering.tools.lsp.ls_cache.load_cache")
    def test_load_cache(self, mock_load_cache, temp_cache_dir):
        # Create dummy cache files
        temp_cache_dir.mkdir(parents=True, exist_ok=True)
        (temp_cache_dir / LanguageServerCache.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME).touch()
        (temp_cache_dir / LanguageServerCache.DOCUMENT_SYMBOL_CACHE_FILENAME).touch()

        mock_load_cache.return_value = {"loaded": "data"}

        cache = LanguageServerCache(temp_cache_dir)

        assert cache._raw_document_symbols_cache == {"loaded": "data"}
        assert cache._document_symbols_cache == {"loaded": "data"}

    @patch("swecli.core.context_engineering.tools.lsp.ls_cache.load_pickle")
    def test_legacy_migration(self, mock_load_pickle, temp_cache_dir):
        # Create legacy cache file
        temp_cache_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = temp_cache_dir / LanguageServerCache.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK
        legacy_file.touch()

        # Mock legacy data: key -> (hash, (all_symbols, root_symbols))
        legacy_data = {
            "file.py-True": ("hash", ([], ["root_symbol"]))
        }
        mock_load_pickle.return_value = legacy_data

        cache = LanguageServerCache(temp_cache_dir)

        assert "file.py" in cache._raw_document_symbols_cache
        assert cache._raw_document_symbols_cache["file.py"] == ("hash", ["root_symbol"])
        assert not legacy_file.exists()  # Should be deleted
