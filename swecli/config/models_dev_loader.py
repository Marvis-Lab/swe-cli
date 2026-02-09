"""Helpers for loading the Models.dev catalog used by OpenCode."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from swecli.core.paths import get_paths

_LOG = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
DEFAULT_CACHE_TTL = 60 * 60 * 24  # 24 hours


def _load_from_path(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _fetch_models_dev(url: str = MODELS_DEV_URL, timeout: int = 10) -> Optional[Dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": os.getenv("OPENDEV_HTTP_USER_AGENT", "swecli/unknown"),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOG.debug("Failed to fetch models.dev catalog: %s", exc)
    except Exception as exc:  # pragma: no cover - safeguard
        _LOG.warning("Unexpected error fetching models.dev catalog: %s", exc)
    return None


def load_models_dev_catalog(
    *,
    cache_dir: Optional[Path] = None,
    cache_ttl: int = DEFAULT_CACHE_TTL,
    disable_network: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Load the Models.dev provider catalog, respecting cache and overrides.

    Precedence:
        1. OPENDEV_MODELS_DEV_PATH environment variable (JSON file path)
        2. Cached response under ~/.opendev/cache/models.dev.json (if fresh)
        3. Live fetch from https://models.dev/api.json (unless disabled)

    Args:
        cache_dir: Optional directory to use for cache writes.
        cache_ttl: Maximum age (seconds) before cached data is considered stale.
        disable_network: Force skipping live fetch attempts.

    Returns:
        Parsed JSON structure from Models.dev or None if unavailable.
    """

    override_path = os.getenv("OPENDEV_MODELS_DEV_PATH")
    if override_path:
        override = Path(override_path).expanduser()
        if override.exists():
            try:
                return _load_from_path(override)
            except Exception as exc:
                _LOG.warning("Failed to load Models.dev catalog override from %s: %s", override, exc)
        else:
            _LOG.warning("OPENDEV_MODELS_DEV_PATH %s does not exist", override)

    if cache_dir is None:
        cache_dir = get_paths().global_cache_dir
    cache_path: Optional[Path] = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "models.dev.json"
    except PermissionError:
        _LOG.debug("Cannot create cache directory %s; caching disabled", cache_dir)

    disable_fetch = disable_network
    if disable_fetch is None:
        disable_fetch = os.getenv("OPENDEV_DISABLE_REMOTE_MODELS", "").lower() in {"1", "true", "yes"}

    now = time.time()
    if cache_path and cache_path.exists():
        try:
            cache_mtime = cache_path.stat().st_mtime
        except OSError:
            cache_mtime = 0
        if now - cache_mtime <= cache_ttl:
            try:
                return _load_from_path(cache_path)
            except Exception as exc:
                _LOG.debug("Failed to read cached Models.dev catalog: %s", exc)
        elif disable_fetch:
            try:
                return _load_from_path(cache_path)
            except Exception:
                pass

    if disable_fetch:
        return None

    data = _fetch_models_dev()
    if data is not None:
        if cache_path:
            try:
                cache_path.write_text(json.dumps(data), encoding="utf-8")
            except Exception as exc:  # pragma: no cover - cache is best-effort
                _LOG.debug("Unable to write Models.dev cache: %s", exc)
        return data

    # As a fallback, try returning whatever stale cache we might have
    if cache_path and cache_path.exists():
        try:
            return _load_from_path(cache_path)
        except Exception:
            pass

    return None
