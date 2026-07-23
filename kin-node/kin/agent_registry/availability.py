"""Availability computation engine and human-readable explanation mapping."""

from __future__ import annotations

from pathlib import Path
import keyring

from kin.schemas import AgentAvailability, AgentCard, WebhookAdapterConfig, LocalCommandAdapterConfig
from kin.identity.storage import get_agent_credential_service

AVAILABILITY_EXPLANATIONS: dict[AgentAvailability, str] = {
    AgentAvailability.READY: "Ready to accept work.",
    AgentAvailability.BUSY: "Currently working on another session.",
    AgentAvailability.RESERVED: "Reserved for a planned collaboration.",
    AgentAvailability.NEEDS_KEY: "A required credential is not yet stored in the keychain.",
    AgentAvailability.NEEDS_WORKSPACE: "The configured working directory is not available.",
    AgentAvailability.WAITING_FOR_APPROVAL: "Waiting on an owner approval decision.",
    AgentAvailability.OFFLINE: "This agent's backend is not reachable.",
    AgentAvailability.POLICY_BLOCKED: "Local policy blocks this task.",
}


def compute_availability(
    card: AgentCard,
    profile: str,
    stored_availability: AgentAvailability = AgentAvailability.READY,
    enabled: bool = True,
) -> AgentAvailability:
    """Compute an agent's active availability state based on environment readiness and enabled status.

    Args:
        card: Active AgentCard.
        profile: Profile name for keychain lookups.
        stored_availability: Current stored availability status.
        enabled: Whether the local agent is enabled by owner policy.

    Returns:
        Computed AgentAvailability enum value.
    """
    if not enabled:
        return AgentAvailability.POLICY_BLOCKED

    if isinstance(card.adapter, WebhookAdapterConfig):
        service_name = get_agent_credential_service(profile, card.id, "webhook_secret")
        secret = keyring.get_password(service_name, "webhook_secret")
        if secret is None:
            return AgentAvailability.NEEDS_KEY

    elif isinstance(card.adapter, LocalCommandAdapterConfig):
        wdir = Path(card.adapter.working_directory)
        if not wdir.is_dir():
            return AgentAvailability.NEEDS_WORKSPACE

    return stored_availability
