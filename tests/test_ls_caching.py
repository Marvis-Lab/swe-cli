from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swecli.core.context_engineering.tools.lsp.components.caching import SymbolCacheManager
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def cache_manager(cache_dir: Path) -> SymbolCacheManager:
    return SymbolCacheManager(cache_dir, cache_version_raw_document_symbols="v1")


class TestSymbolCacheManager:
    def test_initialization(self, cache_dir: Path) -> None:
        manager = SymbolCacheManager(cache_dir, "v1")
        assert manager.cache_dir == cache_dir
        assert manager.cache_dir.exists()
        assert manager._ls_specific_raw_document_symbols_cache_version == "v1"

    def test_raw_document_symbols_cache(self, cache_manager: SymbolCacheManager) -> None:
        cache_key = "test_file.py"
        content_hash = "hash123"
        symbols = [MagicMock()]

        # Initial get should return None
        assert cache_manager.get_raw_document_symbols(cache_key, content_hash) is None

        # Update cache
        cache_manager.update_raw_document_symbols(cache_key, content_hash, symbols)
        assert cache_manager._raw_document_symbols_cache_is_modified is True

        # Get with correct hash
        assert cache_manager.get_raw_document_symbols(cache_key, content_hash) == symbols

        # Get with incorrect hash
        assert cache_manager.get_raw_document_symbols(cache_key, "wrong_hash") is None

    def test_document_symbols_cache(self, cache_manager: SymbolCacheManager) -> None:
        cache_key = "test_file.py"
        content_hash = "hash123"
        symbols = DocumentSymbols([])

        # Initial get should return None
        assert cache_manager.get_document_symbols(cache_key, content_hash) is None

        # Update cache
        cache_manager.update_document_symbols(cache_key, content_hash, symbols)
        assert cache_manager._document_symbols_cache_is_modified is True

        # Get with correct hash
        assert cache_manager.get_document_symbols(cache_key, content_hash) == symbols

        # Get with incorrect hash
        assert cache_manager.get_document_symbols(cache_key, "wrong_hash") is None

    @patch("swecli.core.context_engineering.tools.lsp.components.caching.save_cache")
    def test_save_cache(self, mock_save_cache: MagicMock, cache_manager: SymbolCacheManager) -> None:
        cache_manager._raw_document_symbols_cache_is_modified = True
        cache_manager._document_symbols_cache_is_modified = True

        cache_manager.save_cache()

        assert mock_save_cache.call_count == 2
        assert cache_manager._raw_document_symbols_cache_is_modified is False
        assert cache_manager._document_symbols_cache_is_modified is False

    @patch("swecli.core.context_engineering.tools.lsp.components.caching.save_cache")
    def test_save_cache_no_changes(self, mock_save_cache: MagicMock, cache_manager: SymbolCacheManager) -> None:
        cache_manager._raw_document_symbols_cache_is_modified = False
        cache_manager._document_symbols_cache_is_modified = False

        cache_manager.save_cache()

        mock_save_cache.assert_not_called()

    @patch("swecli.core.context_engineering.tools.lsp.components.caching.load_cache")
    def test_load_cache(self, mock_load_cache: MagicMock, cache_dir: Path) -> None:
        # Mock cached data
        mock_load_cache.return_value = {"file": ("hash", "data")}

        # Create dummy cache files
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / SymbolCacheManager.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME).touch()
        (cache_dir / SymbolCacheManager.DOCUMENT_SYMBOL_CACHE_FILENAME).touch()

        manager = SymbolCacheManager(cache_dir, "v1")

        assert manager._raw_document_symbols_cache == {"file": ("hash", "data")}
        assert manager._document_symbols_cache == {"file": ("hash", "data")}
        assert mock_load_cache.call_count == 2
