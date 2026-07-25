"""Adapter factory module per §9.3 and §2.1."""

from __future__ import annotations

from typing import Union

from kin.adapters.embedded import EmbeddedAdapter
from kin.adapters.local_command import LocalCommandAdapter
from kin.adapters.webhook import WebhookAdapter
from kin.schemas import AgentCard

AdapterInstance = Union[EmbeddedAdapter, WebhookAdapter, LocalCommandAdapter]


def get_adapter(card: AgentCard) -> AdapterInstance:
    """Return adapter instance corresponding to card.adapter's discriminated type."""
    adapter_type = card.adapter.type
    type_str = adapter_type.value if hasattr(adapter_type, "value") else str(adapter_type)

    if type_str == "embedded":
        return EmbeddedAdapter(card)
    elif type_str == "webhook":
        return WebhookAdapter(card)
    elif type_str == "local_command":
        return LocalCommandAdapter(card)
    elif type_str == "sdk":
        raise NotImplementedError("SDK adapter type is out of scope for M4 — see master spec §6.2")
    else:
        raise ValueError(f"Unknown adapter type '{type_str}'.")
