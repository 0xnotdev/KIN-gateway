"""Factory function to load agent and build the correct backend."""

from __future__ import annotations

from typing import Optional
from kin.agent_backend.base import BaseAgentBackend
from kin.agent_backend.llm_backend import LLMAgentBackend
from kin.agent_backend.webhook_backend import WebhookAgentBackend
from kin.agent_roster.loader import load_agent_roster, AgentLoadingError


def get_agent_backend(profile_name: str, agent_name: Optional[str] = None) -> BaseAgentBackend:
    """Loads agent configuration and returns the appropriate backend.
    
    If agent_name is None, falls back to the active agent configuration.
    If zero agents configured or roster load fails, returns default LLMAgentBackend.
    """
    try:
        roster = load_agent_roster(profile_name)
    except AgentLoadingError:
        return LLMAgentBackend(profile_name)

    if not roster:
        return LLMAgentBackend(profile_name)

    selected_name = agent_name
    if not selected_name:
        # Default auto-selection: if one, use it. Otherwise, use alphabetically first.
        if len(roster) == 1:
            selected_name = next(iter(roster.keys()))
        else:
            selected_name = sorted(roster.keys())[0]

    if selected_name not in roster:
        return LLMAgentBackend(profile_name)

    config = roster[selected_name]
    if config.backend_type == "webhook":
        return WebhookAgentBackend(
            webhook_url=config.webhook_url,
            webhook_secret=config.webhook_secret
        )
    else:
        # Embedded backend uses LLMAgentBackend with loaded configuration (for custom prompts)
        return LLMAgentBackend(profile_name, agent_config=config)
