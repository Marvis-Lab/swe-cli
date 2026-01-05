import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from swecli.core.context_engineering.tools.lsp.ls_cache import LanguageServerCache
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols
from swecli.core.context_engineering.tools.lsp.ls_types import UnifiedSymbolInformation
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler.lsp_types import DocumentSymbol


class TestLanguageServerCache(unittest.TestCase):
    def setUp(self):
        self.cache_dir = Path("test_cache")
        self.cache_dir.mkdir(exist_ok=True)
        self.cache = LanguageServerCache(self.cache_dir, ls_specific_raw_document_symbols_cache_version=1)

    def tearDown(self):
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_raw_document_symbols_cache(self):
        cache_key = "test_file.py"
        content_hash = "hash123"
        symbols = [MagicMock(spec=DocumentSymbol)]

        # Test update
        self.cache.update_raw_document_symbols(cache_key, content_hash, symbols)
        self.assertTrue(self.cache._raw_document_symbols_cache_is_modified)

        # Test get (hit)
        result = self.cache.get_raw_document_symbols(cache_key, content_hash)
        self.assertEqual(result, symbols)

        # Test get (miss - content changed)
        result = self.cache.get_raw_document_symbols(cache_key, "different_hash")
        self.assertIsNone(result)

        # Test get (miss - key not found)
        result = self.cache.get_raw_document_symbols("nonexistent.py", content_hash)
        self.assertIsNone(result)

    def test_document_symbols_cache(self):
        cache_key = "test_file.py"
        content_hash = "hash123"
        symbols = DocumentSymbols(root_symbols=[])

        # Test update
        self.cache.update_document_symbols(cache_key, content_hash, symbols)
        self.assertTrue(self.cache._document_symbols_cache_is_modified)

        # Test get (hit)
        result = self.cache.get_document_symbols(cache_key, content_hash)
        self.assertEqual(result, symbols)

        # Test get (miss - content changed)
        result = self.cache.get_document_symbols(cache_key, "different_hash")
        self.assertIsNone(result)

        # Test get (miss - key not found)
        result = self.cache.get_document_symbols("nonexistent.py", content_hash)
        self.assertIsNone(result)

    @patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache")
    @patch("swecli.core.context_engineering.tools.lsp.ls_cache.load_cache")
    def test_save_and_load_caches(self, mock_load_cache, mock_save_cache):
        # Setup mock data
        raw_symbols = [MagicMock(spec=DocumentSymbol)]
        doc_symbols = DocumentSymbols(root_symbols=[])

        self.cache.update_raw_document_symbols("file1.py", "hash1", raw_symbols)
        self.cache.update_document_symbols("file2.py", "hash2", doc_symbols)

        # Test save
        self.cache.save_cache()
        self.assertEqual(mock_save_cache.call_count, 2)
        self.assertFalse(self.cache._raw_document_symbols_cache_is_modified)
        self.assertFalse(self.cache._document_symbols_cache_is_modified)

        # Test load
        mock_load_cache.side_effect = [
            {"file1.py": ("hash1", raw_symbols)},  # raw cache
            {"file2.py": ("hash2", doc_symbols)}   # doc cache
        ]

        new_cache = LanguageServerCache(self.cache_dir)
        new_cache.load_caches()

        # We need to ensure that the cache methods return exactly what was loaded.
        # However, LanguageServerCache.get_raw_document_symbols calls _raw_document_symbols_cache.get(cache_key)
        # which returns (hash, symbols).
        # We mocked load_cache to return {"file1.py": ("hash1", raw_symbols)}.

        self.assertEqual(new_cache.get_raw_document_symbols("file1.py", "hash1"), raw_symbols)
        self.assertEqual(new_cache.get_document_symbols("file2.py", "hash2"), doc_symbols)

    def test_legacy_cache_migration(self):
        legacy_cache_file = self.cache_dir / self.cache.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK
        legacy_data = {
            "test_file.py-True": ("hash123", ([], [])) # (hash, (all_symbols, root_symbols))
        }

        with patch("swecli.core.context_engineering.tools.lsp.ls_cache.load_pickle", return_value=legacy_data):
            # Create a dummy legacy file
            legacy_cache_file.touch()

            # We also need to patch save_cache because migration saves the cache
            with patch("swecli.core.context_engineering.tools.lsp.ls_cache.save_cache") as mock_save:
                # This should trigger migration
                self.cache._load_raw_document_symbols_cache()

                # Check if migrated
                self.assertIn("test_file.py", self.cache._raw_document_symbols_cache)
                self.assertTrue(self.cache._raw_document_symbols_cache_is_modified)
                self.assertFalse(legacy_cache_file.exists())
