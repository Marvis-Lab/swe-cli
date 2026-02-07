"""HTTP client helpers for agent chat completions."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Union, Any

import requests


@dataclass
class HttpResult:
    """Container describing the outcome of an HTTP request."""

    success: bool
    response: Union[requests.Response, None] = None
    error: Union[str, None] = None
    interrupted: bool = False


class AgentHttpClient:
    """Thin wrapper around requests with interrupt support."""

    # Timeout configuration: (connect_timeout, read_timeout)
    # connect_timeout: how long to wait to establish connection (10s)
    # read_timeout: how long to wait for response (300s = 5 minutes for long LLM responses)
    TIMEOUT = (10, 300)

    def __init__(self, api_url: str, headers: dict[str, str]) -> None:
        self._api_url = api_url
        self._headers = headers

    def post_json(self, payload: dict[str, Any], *, task_monitor: Union[Any, None] = None) -> HttpResult:
        """Execute a POST request while honoring interrupt signals."""
        # Fast path when no monitor is provided
        if task_monitor is None:
            try:
                response = requests.post(
                    self._api_url,
                    headers=self._headers,
                    json=payload,
                    timeout=self.TIMEOUT,
                )
                return HttpResult(success=True, response=response)
            except Exception as exc:  # pragma: no cover - propagation handled by caller
                return HttpResult(success=False, error=str(exc))

        # Interrupt-aware execution path
        session = requests.Session()
        response_container: dict[str, Any] = {"response": None, "error": None}

        def make_request() -> None:
            try:
                response_container["response"] = session.post(
                    self._api_url,
                    headers=self._headers,
                    json=payload,
                    timeout=self.TIMEOUT,
                )
            except Exception as exc:  # pragma: no cover - captured for caller
                response_container["error"] = exc

        request_thread = threading.Thread(target=make_request, daemon=True)
        request_thread.start()

        from swecli.ui_textual.debug_logger import debug_log
        poll_count = 0
        while request_thread.is_alive():
            poll_count += 1
            should_interrupt = False
            if task_monitor is not None:
                if hasattr(task_monitor, "should_interrupt"):
                    should_interrupt = task_monitor.should_interrupt()
                elif hasattr(task_monitor, "is_interrupted"):
                    should_interrupt = task_monitor.is_interrupted()

            # Log every 10th poll (every ~1 second)
            if poll_count % 10 == 1:
                debug_log("HttpClient", f"poll #{poll_count}, should_interrupt={should_interrupt}, task_monitor={task_monitor}")

            if should_interrupt:
                debug_log("HttpClient", f"INTERRUPT DETECTED at poll #{poll_count}, closing session")
                session.close()
                return HttpResult(success=False, error="Interrupted by user", interrupted=True)
            request_thread.join(timeout=0.01)  # 10ms - 10x more responsive for ESC interrupt

        if response_container["error"]:
            return HttpResult(success=False, error=str(response_container["error"]))

        return HttpResult(success=True, response=response_container["response"])
