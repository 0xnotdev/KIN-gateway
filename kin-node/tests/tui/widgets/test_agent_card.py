"""Unit tests for AgentCardWidget peer security isolation.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

import pytest

from kin.tui.state import AgentCardView
from kin.tui.widgets import AgentCardWidget


def test_agent_card_peer_security_isolation_rendered_output():
    """END-TO-END PEER SAFETY TEST (§14.5).

    Renders a peer AgentCardView through AgentCardWidget and asserts the RENDERED OUTPUT string
    never leaks adapter config, working_directory, or credential markers — even when given an adversarial fixture.
    """
    # Adversarial card view representing a published peer agent card
    peer_card = AgentCardView(
        agent_id="peer_agent_123",
        name="Adversarial Peer Agent",
        description="Public description of peer agent",
        availability="available",
        readiness_reason="ready",
        is_peer=True,
        capabilities_tags=["search", "analysis"],
    )

    # Attach secret fields dynamically to test adversarial leakage prevention
    peer_card.adapter_config = {"api_key": "SECRET_KEY_12345", "working_directory": "/private/user/data"}  # type: ignore

    widget = AgentCardWidget(card_view=peer_card)
    rendered = widget.render()

    # ASSERTIONS: Public fields present, secret fields strictly absent in rendered output
    assert "Adversarial Peer Agent" in rendered
    assert "peer_agent_123" in rendered
    assert "public description" in rendered.lower()
    assert "[PEER]" in rendered

    # STRICT SECURITY BOUNDARY ASSERTIONS
    assert "SECRET_KEY" not in rendered
    assert "api_key" not in rendered
    assert "/private/user/data" not in rendered
    assert "working_directory" not in rendered
    assert "adapter_config" not in rendered
