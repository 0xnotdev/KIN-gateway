"""Owner-configured Python SDK adapter behind the normalized V1.1 contract."""

from __future__ import annotations

import concurrent.futures
import importlib
import inspect
from typing import Any

from kin.adapters.base import AdapterActivityEvent, AdapterRequest, AdapterResponse
from kin.schemas import AgentCard


class SdkAdapter:
    """Load one explicit ``module:callable`` and normalize its response."""

    def __init__(self, card: AgentCard):
        self.card = card

    def invoke(self, request: AdapterRequest, vault_key: bytes | None = None) -> AdapterResponse:
        timeout_seconds = self.card.boundaries.max_runtime_seconds or 30.0
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._invoke_entry_point, request, vault_key)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                return AdapterResponse(
                    events=[AdapterActivityEvent(label=f"SDK adapter timed out after {timeout_seconds} seconds")],
                    error={"code": "ADAPTER_TIMEOUT", "message": f"SDK adapter timed out after {timeout_seconds}s."},
                )
            except Exception as exc:
                return AdapterResponse(
                    events=[AdapterActivityEvent(label="SDK adapter invocation failed")],
                    error={"code": "ADAPTER_EXECUTION_ERROR", "message": str(exc)},
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _invoke_entry_point(self, request: AdapterRequest, vault_key: bytes | None) -> AdapterResponse:
        module_name, attribute_name = self.card.adapter.entry_point.split(":", 1)
        target: Any = getattr(importlib.import_module(module_name), attribute_name)
        if inspect.isclass(target):
            target = target(self.card) if inspect.signature(target).parameters else target()
        callable_target = target.invoke if hasattr(target, "invoke") else target
        if not callable(callable_target):
            raise TypeError(f"SDK entry point '{self.card.adapter.entry_point}' is not callable.")
        parameters = inspect.signature(callable_target).parameters
        result = callable_target(request, vault_key) if len(parameters) >= 2 else callable_target(request)
        return result if isinstance(result, AdapterResponse) else AdapterResponse.model_validate(result)
