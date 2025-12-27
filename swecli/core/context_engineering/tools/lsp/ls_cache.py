from collections.abc import Hashable, Iterator
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Union

from swecli.core.context_engineering.tools.lsp import ls_types
from swecli.core.context_engineering.tools.lsp.lsp_protocol_handler import lsp_types as LSPTypes
from swecli.core.context_engineering.tools.lsp.util.cache import load_cache, save_cache
from swecli.core.context_engineering.tools.lsp.util.compat import getstate

if TYPE_CHECKING:
    from swecli.core.context_engineering.tools.lsp.ls import SolidLanguageServer

GenericDocumentSymbol = Union[LSPTypes.DocumentSymbol, LSPTypes.SymbolInformation, ls_types.UnifiedSymbolInformation]
log = logging.getLogger(__name__)


class DocumentSymbols:
    # IMPORTANT: Instances of this class are persisted in the high-level document symbol cache

    def __init__(self, root_symbols: list[ls_types.UnifiedSymbolInformation]):
        self.root_symbols = root_symbols
        self._all_symbols: list[ls_types.UnifiedSymbolInformation] | None = None

    def __getstate__(self) -> dict:
        return getstate(DocumentSymbols, self, transient_properties=["_all_symbols"])

    def iter_symbols(self) -> Iterator[ls_types.UnifiedSymbolInformation]:
        """
        Iterate over all symbols in the document symbol tree.
        Yields symbols in a depth-first manner.
        """
        if self._all_symbols is not None:
            yield from self._all_symbols
            return

        def traverse(s: ls_types.UnifiedSymbolInformation) -> Iterator[ls_types.UnifiedSymbolInformation]:
            yield s
            for child in s.get("children", []):
                yield from traverse(child)

        for root_symbol in self.root_symbols:
            yield from traverse(root_symbol)

    def get_all_symbols_and_roots(self) -> tuple[list[ls_types.UnifiedSymbolInformation], list[ls_types.UnifiedSymbolInformation]]:
        """
        This function returns all symbols in the document as a flat list and the root symbols.
        It exists to facilitate migration from previous versions, where this was the return interface of
        the LS method that obtained document symbols.

        :return: A tuple containing a list of all symbols in the document and a list of root symbols.
        """
        if self._all_symbols is None:
            self._all_symbols = list(self.iter_symbols())
        return self._all_symbols, self.root_symbols


class LSCacheMixin:
    """
    Mixin class for SolidLanguageServer to handle caching of document symbols.
    """
    CACHE_FOLDER_NAME = "cache"
    RAW_DOCUMENT_SYMBOLS_CACHE_VERSION = 1
    RAW_DOCUMENT_SYMBOL_CACHE_FILENAME = "raw_document_symbols.pkl"
    RAW_DOCUMENT_SYMBOL_CACHE_FILENAME_LEGACY_FALLBACK = "document_symbols_cache_v23-06-25.pkl"
    DOCUMENT_SYMBOL_CACHE_VERSION = 3
    DOCUMENT_SYMBOL_CACHE_FILENAME = "document_symbols.pkl"

    def __init__(self, *args, **kwargs):
        # These are expected to be initialized by the main class or other mixins
        # but we declare them here for type checking
        pass

    def _init_caches(self, cache_version_raw_document_symbols: Hashable = 1) -> None:
        """Initialize the caches. Should be called from __init__ of the main class."""
        # initialise symbol caches
        self.cache_dir = (
            Path(self.repository_root_path) / self._solidlsp_settings.project_data_relative_path / self.CACHE_FOLDER_NAME / self.language_id
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # * raw document symbols cache
        self._ls_specific_raw_document_symbols_cache_version = cache_version_raw_document_symbols
        self._raw_document_symbols_cache: dict[str, tuple[str, list[LSPTypes.DocumentSymbol] | list[LSPTypes.SymbolInformation] | None]] = {}
        """maps relative file paths to a tuple of (file_content_hash, raw_root_symbols)"""
        self._raw_document_symbols_cache_is_modified: bool = False
        self._load_raw_document_symbols_cache()
        # * high-level document symbols cache
        self._document_symbols_cache: dict[str, tuple[str, DocumentSymbols]] = {}
        """maps relative file paths to a tuple of (file_content_hash, document_symbols)"""
        self._document_symbols_cache_is_modified: bool = False
        self._load_document_symbols_cache()

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
                    # Circular import avoidance
                    from swecli.core.context_engineering.tools.lsp.util.compat import load_pickle

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

    def save_cache(self) -> None:
        self._save_raw_document_symbols_cache()
        self._save_document_symbols_cache()
