import logging
from collections.abc import Hashable
from pathlib import Path

from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler.lsp_types import DocumentSymbol, SymbolInformation
from swecli.core.context_engineering.tools.lsp.ls_structs import DocumentSymbols
from swecli.core.context_engineering.tools.lsp.util.cache import load_cache, save_cache
from swecli.core.context_engineering.tools.lsp.util.compat import load_pickle

log = logging.getLogger(__name__)


class LanguageServerCache:
    CACHE_FOLDER_NAME = "cache"
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

    def __init__(
        self,
        repository_root_path: str,
        project_data_relative_path: str,
        language_id: str,
        ls_specific_raw_document_symbols_cache_version: Hashable,
    ):
        self.repository_root_path = repository_root_path
        self.language_id = language_id
        self.cache_dir = (
            Path(self.repository_root_path) / project_data_relative_path / self.CACHE_FOLDER_NAME / self.language_id
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # * raw document symbols cache
        self.ls_specific_raw_document_symbols_cache_version = ls_specific_raw_document_symbols_cache_version
        self.raw_document_symbols_cache: dict[str, tuple[str, list[DocumentSymbol] | list[SymbolInformation] | None]] = {}
        """maps relative file paths to a tuple of (file_content_hash, raw_root_symbols)"""
        self.raw_document_symbols_cache_is_modified: bool = False
        self.load_raw_document_symbols_cache()

        # * high-level document symbols cache
        self.document_symbols_cache: dict[str, tuple[str, DocumentSymbols]] = {}
        """maps relative file paths to a tuple of (file_content_hash, document_symbols)"""
        self.document_symbols_cache_is_modified: bool = False
        self.load_document_symbols_cache()

    def save_raw_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.RAW_DOCUMENT_SYMBOL_CACHE_FILENAME

        if not self.raw_document_symbols_cache_is_modified:
            log.debug("No changes to raw document symbols cache, skipping save")
            return

        log.info("Saving updated raw document symbols cache to %s", cache_file)
        try:
            save_cache(str(cache_file), self._raw_document_symbols_cache_version(), self.raw_document_symbols_cache)
            self.raw_document_symbols_cache_is_modified = False
        except Exception as e:
            log.error(
                "Failed to save raw document symbols cache to %s: %s. Note: this may have resulted in a corrupted cache file.",
                cache_file,
                e,
            )

    def _raw_document_symbols_cache_version(self) -> tuple[int, Hashable]:
        return (self.RAW_DOCUMENT_SYMBOLS_CACHE_VERSION, self.ls_specific_raw_document_symbols_cache_version)

    def load_raw_document_symbols_cache(self) -> None:
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
                    self.raw_document_symbols_cache = migrated_cache  # type: ignore
                    self.raw_document_symbols_cache_is_modified = True
                    self.save_raw_document_symbols_cache()
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
                    self.raw_document_symbols_cache = saved_cache
                    log.info(f"Loaded {len(self.raw_document_symbols_cache)} entries from raw document symbols cache.")
            except Exception as e:
                # cache can become corrupt, so just skip loading it
                log.warning(
                    "Failed to load raw document symbols cache from %s (%s); Ignoring cache.",
                    cache_file,
                    e,
                )

    def save_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME

        if not self.document_symbols_cache_is_modified:
            log.debug("No changes to document symbols cache, skipping save")
            return

        log.info("Saving updated document symbols cache to %s", cache_file)
        try:
            save_cache(str(cache_file), self.DOCUMENT_SYMBOL_CACHE_VERSION, self.document_symbols_cache)
            self.document_symbols_cache_is_modified = False
        except Exception as e:
            log.error(
                "Failed to save document symbols cache to %s: %s. Note: this may have resulted in a corrupted cache file.",
                cache_file,
                e,
            )

    def load_document_symbols_cache(self) -> None:
        cache_file = self.cache_dir / self.DOCUMENT_SYMBOL_CACHE_FILENAME
        if cache_file.exists():
            log.info("Loading document symbols cache from %s", cache_file)
            try:
                saved_cache = load_cache(str(cache_file), self.DOCUMENT_SYMBOL_CACHE_VERSION)
                if saved_cache is not None:
                    self.document_symbols_cache = saved_cache
                    log.info(f"Loaded {len(self.document_symbols_cache)} entries from document symbols cache.")
            except Exception as e:
                # cache can become corrupt, so just skip loading it
                log.warning(
                    "Failed to load document symbols cache from %s (%s); Ignoring cache.",
                    cache_file,
                    e,
                )

    def save_cache(self) -> None:
        self.save_raw_document_symbols_cache()
        self.save_document_symbols_cache()
