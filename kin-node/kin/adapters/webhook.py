"""Webhook adapter implementation per §9.3 and §2.1."""

from __future__ import annotations

import concurrent.futures

import httpx

from kin.adapters.base import (
    AdapterActivityEvent,
    AdapterMessage,
    AdapterRequest,
    AdapterResponse,
)
from kin.identity.storage import get_agent_credential_service
from kin.schemas import AgentCard, MessageKind


class WebhookAdapter:
    def __init__(self, card: AgentCard):
        self.card = card

    def invoke(self, request: AdapterRequest, vault_key: bytes | None = None) -> AdapterResponse:
        """Invoke remote webhook endpoint bounded by card max_runtime_seconds."""
        timeout_seconds = self.card.boundaries.max_runtime_seconds or 30.0

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._execute_webhook_call, request, vault_key)
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                return AdapterResponse(
                    events=[
                        AdapterActivityEvent(label=f"Webhook call timed out after {timeout_seconds} seconds")
                    ],
                    error={
                        "code": "ADAPTER_TIMEOUT",
                        "message": f"Webhook adapter call timed out after {timeout_seconds}s.",
                    },
                )
            except Exception as e:
                return AdapterResponse(
                    events=[AdapterActivityEvent(label=f"Webhook call failed: {e}")],
                    error={"code": "ADAPTER_EXECUTION_ERROR", "message": str(e)},
                )

    def _execute_webhook_call(self, request: AdapterRequest, vault_key: bytes | None) -> AdapterResponse:
        adapter_cfg = self.card.adapter
        endpoint_url = adapter_cfg.endpoint_url

        headers = {"Content-Type": "application/json"}

        # Load credential from OS keyring service via credential_ref if present
        if hasattr(adapter_cfg, "credential_ref") and adapter_cfg.credential_ref:
            try:
                service = get_agent_credential_service(self.card.id)
                cred_val = service.get_credential(adapter_cfg.credential_ref)
                if cred_val:
                    headers["Authorization"] = f"Bearer {cred_val}"
            except Exception:
                pass

        payload_data = request.model_dump(mode="json")

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(endpoint_url, json=payload_data, headers=headers)
            resp.raise_for_status()

            res_json = resp.json()
            # If response matches AdapterResponse schema directly
            if isinstance(res_json, dict) and "message" in res_json:
                return AdapterResponse.model_validate(res_json)
            else:
                # Wrap text response into AdapterResponse
                out_text = str(res_json.get("output", res_json)) if isinstance(res_json, dict) else str(res_json)
                return AdapterResponse(
                    events=[AdapterActivityEvent(label="Webhook response received")],
                    message=AdapterMessage(kind=MessageKind.PROPOSAL, content=out_text),
                )
