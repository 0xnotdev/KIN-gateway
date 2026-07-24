"""Agent backend implementation utilising HTTP webhooks."""

from __future__ import annotations

import asyncio
import time
from typing import Any
import httpx

from kin.agent_backend.base import BaseAgentBackend, AgentBackendRequest, AgentBackendResponse


class WebhookAgentBackend(BaseAgentBackend):
    """Webhook-based agent backend implementing BaseAgentBackend interface."""

    def __init__(self, webhook_url: str, webhook_secret: str):
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret

    def _prepare_request(self, request: AgentBackendRequest) -> tuple[dict[str, Any], dict[str, str]]:
        payload = {
            "task_goal": request.task_goal,
            "context": request.context,
            "conversation_history": request.conversation_history,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.webhook_secret}",
        }
        return payload, headers

    def _parse_response(self, response_data: Any) -> AgentBackendResponse:
        if not isinstance(response_data, dict):
            raise ValueError("Response must be a JSON object")
        return AgentBackendResponse(**response_data)

    def generate_response(self, request: AgentBackendRequest) -> AgentBackendResponse:
        payload, headers = self._prepare_request(request)
        attempts = 2
        for attempt in range(attempts):
            try:
                with httpx.Client() as client:
                    r = client.post(self.webhook_url, json=payload, headers=headers)
                r.raise_for_status()
                return self._parse_response(r.json())
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                if attempt < attempts - 1:
                    time.sleep(1.0)
                    continue
                raise e
            except httpx.HTTPStatusError as e:
                # Do not retry on HTTP error status (4xx/5xx)
                raise e

    async def generate_response_async(self, request: AgentBackendRequest) -> AgentBackendResponse:
        payload, headers = self._prepare_request(request)
        attempts = 2
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.post(self.webhook_url, json=payload, headers=headers)
                r.raise_for_status()
                return self._parse_response(r.json())
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                if attempt < attempts - 1:
                    await asyncio.sleep(1.0)
                    continue
                raise e
            except httpx.HTTPStatusError as e:
                # Do not retry on HTTP error status (4xx/5xx)
                raise e
