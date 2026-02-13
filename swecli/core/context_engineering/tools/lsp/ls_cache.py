import logging
import pathlib
from collections.abc import Hashable
from typing import Union

from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler import lsp_types as LSPTypes
from swecli.core.context_engineering.tools.lsp.util.cache import load_cache, save_cache
from swecli.core.context_engineering.tools.lsp.util.compat import load_pickle
from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols

log = logging.getLogger(__name__)


class LanguageServerCache:
    """
    Handles caching for Language Server symbols.
    """

    RAW_DOCUMENT_SYMBOLS_CACHE_VERSION = 1
    """
    global version identifier for raw symbol caches; an LS-specific version is defined separately and combined with this.
    This should be incremented whenever there is a change in the way raw document symbols are stored.
    If the result of a language server changes in a way that affects the raw document symbols,
    the LS-specific version should be incremented instead.
    """
    RAW_DOCUMENT_SYMBOL_CACHE_FILENAME = "raw_document_symbols.pkl"
    RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK = "document_symbols_cache_v23-06-25.pkl"
    DOCUMENT_SYMBOL_CACHE_VERSION = 3
    DOCUMENT_SYMBOL_CACHE_FILENAME = "document_symbols.pkl"

    def __init__(self, cache_dir: pathlib.Path, ls_specific_raw_document_symbols_cache_version: Hashable):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._ls_specific_raw_document_symbols_cache_version = ls_specific_raw_document_symbols_cache_version

        # * raw document symbols cache
        self._raw_document_symbols_cache: dict[str, tuple[str, list[LSPTypes.DocumentSymbol] | list[LSPTypes.SymbolInformation] | None]] = {}
        """maps relative file paths to a tuple of (file_content_hash, raw_root_symbols)"""
        self._raw_document_symbols_cache_is_modified: bool = False
        self._load_raw_document_symbols_cache()

        # * high-level document symbols cache
        self._document_symbols_cache: dict[str, tuple[str, DocumentSymbols]] = {}
        """maps relative file paths to a tuple of (file_content_hash, document_symbols)"""
        self._document_symbols_cache_is_modified: bool = False
        self._load_document_symbols_cache()

    def get_raw_document_symbols(self, cache_key: str, file_content_hash: str) -> list[LSPTypes.DocumentSymbol] | list[LSPTypes.SymbolInformation] | None:
        file_hash_and_result = self._raw_document_symbols_cache.get(cache_key)
        if file_hash_and_result is not None:
            file_hash, result = file_hash_and_result
            if file_hash == file_content_hash:
                return result
        return None

    def update_raw_document_symbols(self, cache_key: str, file_content_hash: str, symbols: list[LSPTypes.DocumentSymbol] | list[LSPTypes.SymbolInformation] | None) -> None:
        self._raw_document_symbols_cache[cache_key] = (file_content_hash, symbols)
        self._raw_document_symbols_cache_is_modified = True

    def get_document_symbols(self, cache_key: str, file_content_hash: str) -> DocumentSymbols | None:
        file_hash_and_result = self._document_symbols_cache.get(cache_key)
        if file_hash_and_result is not None:
            file_hash, document_symbols = file_hash_and_result
            if file_hash == file_content_hash:
                return document_symbols
        return None

    def update_document_symbols(self, cache_key: str, file_content_hash: str, symbols: DocumentSymbols) -> None:
        self._document_symbols_cache[cache_key] = (file_content_hash, symbols)
        self._document_symbols_cache_is_modified = True

    def _save_raw_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME

        if not self._raw_document_symbols_cache_is_modified:
            log.debug("No changes to raw document symbols cache, skipping save")
            return

        log.info("Saving updated raw document symbols cache to %s", cache_file)
        try:
            save_cache(str(cache_file), self._raw_document_symbols_cache_version(), self._raw_document_symbols_cache)
            self._raw_document_symbols_cache_is_modified = False
        except Exception as e:
            log.error(
                "Failed to save raw document symbols cache to %s: %s. Note: this may have resulted in a corrupted cache file.",
                cache_file,
                e,
            )

    def _raw_document_symbols_cache_version(self) -> tuple[int, Hashable]:
        return (self.RAW_DOCUMENT_SYMBOLS_CACHE_VERSION, self._ls_specific_raw_document_symbols_cache_version)

    def _load_raw_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME

        if not cache_file.exists():
            # check for legacy cache to load to migrate
            legacy_cache_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK
            if legacy_cache_file.exists():
                try:
                    legacy_cache: dict[
                        str, tuple[str, tuple[list[ls_types.UnifiedSymbolInformation], list[ls_types.UnifiedSymbolInformation]]]
                    ] = load_pickle(legacy_cache_file)
                    log.info("Migrating legacy document symbols cache with %d entries", len(legacy_cache))
                    num_symbols_migrated = 0
                    migrated_cache = {}
                    for cache_key, (file_hash, (all_symbols, root_symbols)) in legacy_cache.items():
                        if cache_key.endswith("-True"):  # include_body=True
                            new_cache_key = cache_key[:-5]
                            migrated_cache[new_cache_key] = (file_hash, root_symbols)
                            num_symbols_migrated += len(all_symbols)
                    log.info("Migrated %d document symbols from legacy cache", num_symbols_migrated)
                    self._raw_document_symbols_cache = migrated_cache  # type: ignore
                    self._raw_document_symbols_cache_is_modified = True
                    self._save_raw_document_symbols_cache()
                    legacy_cache_file.unlink()
                    return
                except Exception as e:
                    log.error("Error during cache migration: %s", e)
                    return

        # load existing cache (if any)
        if cache_file.exists():
            log.info("Loading document symbols cache from %s", cache_file)
            try:
                saved_cache = load_cache(str(cache_file), self._raw_document_symbols_cache_version())
                if saved_cache is not None:
                    self._raw_document_symbols_cache = saved_cache
                    log.info(f"Loaded {len(self._raw_document_symbols_cache)} entries from raw document symbols cache.")
            except Exception as e:
                # cache can become corrupt, so just skip loading it
                log.warning(
                    "Failed to load raw document symbols cache from %s (%s); Ignoring cache.",
                    cache_file,
                    e,
                )

    def _save_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME

        if not self._document_symbols_cache_is_modified:
            log.debug("No changes to document symbols cache, skipping save")
            return

        log.info("Saving updated document symbols cache to %s", cache_file)
        try:
            save_cache(str(cache_file), self.DOCUMENT_SYMBOL_CACHE_VERSION, self._document_symbols_cache)
            self._document_symbols_cache_is_modified = False
        except Exception as e:
            log.error(
                "Failed to save document symbols cache to %s: %s. Note: this may have resulted in a corrupted cache file.",
                cache_file,
                e,
            )

    def _load_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME
        if cache_file.exists():
            log.info("Loading document symbols cache from %s", cache_file)
            try:
                saved_cache = load_cache(str(cache_file), self.DOCUMENT_SYMBOL_CACHE_VERSION)
                if saved_cache is not None:
                    self._document_symbols_cache = saved_cache
                    log.info(f"Loaded {len(self._document_symbols_cache)} entries from document symbols cache.")
            except Exception as e:
                # cache can become corrupt, so just skip loading it
                log.warning(
                    "Failed to load document symbols cache from %s (%s); Ignoring cache.",
                    cache_file,
                    e,
                )

    def save(self) -> None:
        self._save_raw_document_symbols_cache()
        self._save_document_symbols_cache()
