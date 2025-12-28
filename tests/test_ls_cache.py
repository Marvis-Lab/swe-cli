import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from swecli.core.context_engineering.tools.lsp.ls_cache import LSCacheMixin
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols


class TestLSCacheMixin:
    @pytest.fixture
    def cache_mixin(self, tmp_path):
        mixin = LSCacheMixin()
        mixin.cache_dir = tmp_path
        mixin._ls_specific_raw_document_symbols_cache_version = 1
        mixin._raw_document_symbols_cache = {}
        mixin._raw_document_symbols_cache_is_modified = False
        mixin._document_symbols_cache = {}
        mixin._document_symbols_cache_is_modified = False
        return mixin

    def test_init_cache(self, tmp_path):
        mixin = LSCacheMixin()
        mixin._init_cache(tmp_path, 1)
        assert mixin.cache_dir == tmp_path
        assert mixin._ls_specific_raw_document_symbols_cache_version == 1
        assert mixin._raw_document_symbols_cache == {}
        assert mixin._document_symbols_cache == {}

    def test_save_raw_document_symbols_cache_no_changes(self, cache_mixin):
        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache") as mock_save:
            cache_mixin._save_raw_document_symbols_cache()
            mock_save.assert_not_called()

    def test_save_raw_document_symbols_cache_with_changes(self, cache_mixin):
        cache_mixin._raw_document_symbols_cache = {"file.py": ("hash", [])}
        cache_mixin._raw_document_symbols_cache_is_modified = True

        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache") as mock_save:
            cache_mixin._save_raw_document_symbols_cache()
            mock_save.assert_called_once()
            assert cache_mixin._raw_document_symbols_cache_is_modified is False

    def test_save_document_symbols_cache_no_changes(self, cache_mixin):
        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache") as mock_save:
            cache_mixin._save_document_symbols_cache()
            mock_save.assert_not_called()

    def test_save_document_symbols_cache_with_changes(self, cache_mixin):
        cache_mixin._document_symbols_cache = {"file.py": ("hash", DocumentSymbols([]))}
        cache_mixin._document_symbols_cache_is_modified = True

        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache") as mock_save:
            cache_mixin._save_document_symbols_cache()
            mock_save.assert_called_once()
            assert cache_mixin._document_symbols_cache_is_modified is False

    def test_load_raw_document_symbols_cache_exists(self, cache_mixin, tmp_path):
        cache_file = tmp_path / LSCacheMixin.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME
        # Creating a dummy file to simulate existence
        cache_file.touch()

        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.load_cache") as mock_load:
            mock_load.return_value = {"file.py": ("hash", [])}
            cache_mixin._load_raw_document_symbols_cache()
            mock_load.assert_called_once()
            assert cache_mixin._raw_document_symbols_cache == {"file.py": ("hash", [])}

    def test_load_document_symbols_cache_exists(self, cache_mixin, tmp_path):
        cache_file = tmp_path / LSCacheMixin.DOCUMENT_SYMBOL_CACHE_FILENAME
        # Creating a dummy file to simulate existence
        cache_file.touch()

        expected_symbols = DocumentSymbols([])
        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.load_cache") as mock_load:
            mock_load.return_value = {"file.py": ("hash", expected_symbols)}
            cache_mixin._load_document_symbols_cache()
            mock_load.assert_called_once()
            assert cache_mixin._document_symbols_cache["file.py"][0] == "hash"
            assert cache_mixin._document_symbols_cache["file.py"][1] is expected_symbols

    def test_save_cache_calls_both(self, cache_mixin):
        with patch.object(cache_mixin, "_save_raw_document_symbols_cache") as mock_save_raw, \
             patch.object(cache_mixin, "_save_document_symbols_cache") as mock_save_doc:
            cache_mixin.save_cache()
            mock_save_raw.assert_called_once()
            mock_save_doc.assert_called_once()
