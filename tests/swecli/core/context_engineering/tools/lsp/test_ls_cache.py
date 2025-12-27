import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swecli.core.context_engineering.tools.lsp.ls_cache import LSCacheMixin, DocumentSymbols
from swecli.core.context_engineering.tools.lsp import ls_types


class TestLSCacheMixin:
    @pytest.fixture
    def mock_mixin(self):
        class MockServer(LSCacheMixin):
            def __init__(self, repo_root, language_id):
                self.repository_root_path = repo_root
                self.language_id = language_id
                self._solidlsp_settings = MagicMock()
                self._solidlsp_settings.project_data_relative_path = ".swecli"
                self._init_caches()

        return MockServer

    @pytest.fixture
    def repo_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    def test_init_caches(self, mock_mixin, repo_root):
        server = mock_mixin(repo_root, "python")
        assert server.cache_dir == Path(repo_root) / ".swecli" / "cache" / "python"
        assert server.cache_dir.exists()
        assert server._raw_document_symbols_cache == {}
        assert server._document_symbols_cache == {}

    def test_save_and_load_raw_document_symbols_cache(self, mock_mixin, repo_root):
        server = mock_mixin(repo_root, "python")

        # Add entry to cache
        cache_key = "test_file.py"
        file_hash = "abc123hash"
        symbols = [{"name": "test_symbol", "kind": 1}]
        server._raw_document_symbols_cache[cache_key] = (file_hash, symbols)
        server._raw_document_symbols_cache_is_modified = True

        # Save cache
        server._save_raw_document_symbols_cache()
        assert not server._raw_document_symbols_cache_is_modified
        assert (server.cache_dir / "raw_document_symbols.pkl").exists()

        # Create new server instance to test loading
        new_server = mock_mixin(repo_root, "python")
        assert cache_key in new_server._raw_document_symbols_cache
        loaded_hash, loaded_symbols = new_server._raw_document_symbols_cache[cache_key]
        assert loaded_hash == file_hash
        assert loaded_symbols == symbols

    def test_save_and_load_document_symbols_cache(self, mock_mixin, repo_root):
        server = mock_mixin(repo_root, "python")

        # Add entry to cache
        cache_key = "test_file.py"
        file_hash = "abc123hash"

        # Create a DocumentSymbols object
        root_symbols = [
            ls_types.UnifiedSymbolInformation(
                name="test_symbol",
                kind=ls_types.SymbolKind.Function,
                location=ls_types.Location(
                    uri="file:///test_file.py",
                    range={"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 0}},
                    absolutePath="/test_file.py",
                    relativePath="test_file.py"
                )
            )
        ]
        doc_symbols = DocumentSymbols(root_symbols)

        server._document_symbols_cache[cache_key] = (file_hash, doc_symbols)
        server._document_symbols_cache_is_modified = True

        # Save cache
        server._save_document_symbols_cache()
        assert not server._document_symbols_cache_is_modified
        assert (server.cache_dir / "document_symbols.pkl").exists()

        # Create new server instance to test loading
        new_server = mock_mixin(repo_root, "python")
        assert cache_key in new_server._document_symbols_cache
        loaded_hash, loaded_doc_symbols = new_server._document_symbols_cache[cache_key]
        assert loaded_hash == file_hash
        assert loaded_doc_symbols.root_symbols == root_symbols

    def test_save_cache_calls_both_saves(self, mock_mixin, repo_root):
        server = mock_mixin(repo_root, "python")

        with patch.object(server, '_save_raw_document_symbols_cache') as mock_save_raw, \
             patch.object(server, '_save_document_symbols_cache') as mock_save_doc:

            server.save_cache()

            mock_save_raw.assert_called_once()
            mock_save_doc.assert_called_once()


class TestDocumentSymbols:
    def test_iter_symbols(self):
        child = ls_types.UnifiedSymbolInformation(
            name="child",
            kind=ls_types.SymbolKind.Variable
        )
        parent = ls_types.UnifiedSymbolInformation(
            name="parent",
            kind=ls_types.SymbolKind.Function,
            children=[child]
        )

        doc_symbols = DocumentSymbols([parent])
        symbols = list(doc_symbols.iter_symbols())

        assert len(symbols) == 2
        assert parent in symbols
        assert child in symbols

    def test_get_all_symbols_and_roots(self):
        child = ls_types.UnifiedSymbolInformation(
            name="child",
            kind=ls_types.SymbolKind.Variable
        )
        parent = ls_types.UnifiedSymbolInformation(
            name="parent",
            kind=ls_types.SymbolKind.Function,
            children=[child]
        )

        doc_symbols = DocumentSymbols([parent])
        all_symbols, roots = doc_symbols.get_all_symbols_and_roots()

        assert len(all_symbols) == 2
        assert len(roots) == 1
        assert roots[0] == parent
