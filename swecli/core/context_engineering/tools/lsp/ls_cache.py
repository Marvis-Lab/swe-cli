import logging
from collections.abc import Hashable
from pathlib import Path

from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler.lsp_types import (
    DocumentSymbol,
    SymbolInformation,
)
from swecli.core.context_engineering.tools.lsp.util.cache import load_cache, save_cache
from swecli.core.context_engineering.tools.lsp.util.compat import load_pickle

log = logging.getLogger(__name__)


class LanguageServerCache:
    """
    Manages caching for the Language Server.
    Handles both raw document symbols (from LS) and high-level document symbols (processed).
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

    def __init__(self, cache_dir: Path, ls_specific_raw_cache_version: Hashable):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._ls_specific_raw_document_symbols_cache_version = ls_specific_raw_cache_version

        # * raw document symbols cache
        self._raw_document_symbols_cache: dict[str, tuple[str, list[DocumentSymbol] | list[SymbolInformation] | None]] = {}
        """maps relative file paths to a tuple of (file_content_hash, raw_root_symbols)"""
        self._raw_document_symbols_cache_is_modified: bool = False

        # * high-level document symbols cache
        self._document_symbols_cache: dict[str, tuple[str, DocumentSymbols]] = {}
        """maps relative file paths to a tuple of (file_content_hash, document_symbols)"""
        self._document_symbols_cache_is_modified: bool = False

        self._load_raw_document_symbols_cache()
        self._load_document_symbols_cache()

    def get_raw_document_symbols(self, cache_key: str, file_hash: str) -> list[SymbolInformation] | list[DocumentSymbol] | None:
        """
        Retrieve raw document symbols from cache if available and hash matches.
        """
        file_hash_and_result = self._raw_document_symbols_cache.get(cache_key)
        if file_hash_and_result is not None:
            cached_hash, result = file_hash_and_result
            if cached_hash == file_hash:
                log.debug("Returning cached raw document symbols for %s", cache_key)
                return result
            else:
                log.debug("Document content for %s has changed (raw symbol cache is not up-to-date)", cache_key)
        else:
            log.debug("No cache hit for raw document symbols symbols in %s", cache_key)
        return None

    def update_raw_document_symbols(self, cache_key: str, file_hash: str, symbols: list[SymbolInformation] | list[DocumentSymbol] | None) -> None:
        """Update raw document symbols cache."""
        self._raw_document_symbols_cache[cache_key] = (file_hash, symbols)
        self._raw_document_symbols_cache_is_modified = True

    def get_document_symbols(self, cache_key: str, file_hash: str) -> DocumentSymbols | None:
        """
        Retrieve processed document symbols from cache if available and hash matches.
        """
        file_hash_and_result = self._document_symbols_cache.get(cache_key)
        if file_hash_and_result is not None:
            cached_hash, document_symbols = file_hash_and_result
            if cached_hash == file_hash:
                log.debug("Returning cached document symbols for %s", cache_key)
                return document_symbols
            else:
                log.debug("Cached document symbol content for %s has changed", cache_key)
        else:
            log.debug("No cache hit for document symbols in %s", cache_key)
        return None

    def update_document_symbols(self, cache_key: str, file_hash: str, symbols: DocumentSymbols) -> None:
        """Update processed document symbols cache."""
        log.debug("Updating cached document symbols for %s", cache_key)
        self._document_symbols_cache[cache_key] = (file_hash, symbols)
        self._document_symbols_cache_is_modified = True

    def save(self) -> None:
        """Save all caches to disk."""
        self._save_raw_document_symbols_cache()
        self._save_document_symbols_cache()

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
