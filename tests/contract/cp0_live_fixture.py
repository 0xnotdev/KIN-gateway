"""Real-network CP0 fixture for the pinned TCK and canonical demo."""

import os

from kin_gateway.app import create_gateway_app
from kin_gateway.config import AgentCardMirrorSettings, GatewaySettings
from tests.contract.reference_agent import build_reference_agent


UPSTREAM_BASE_URL = os.environ.get(
    "KIN_CP0_UPSTREAM_BASE_URL",
    "http://127.0.0.1:18081",
)
GATEWAY_BASE_URL = os.environ.get(
    "KIN_CP0_GATEWAY_BASE_URL",
    "http://127.0.0.1:18080",
)

upstream_app, _ = build_reference_agent(base_url=UPSTREAM_BASE_URL)
gateway_app = create_gateway_app(
    GatewaySettings(
        public_base_url=GATEWAY_BASE_URL,
        upstream_base_url=UPSTREAM_BASE_URL,
        agent_card=AgentCardMirrorSettings(
            approved_skill_ids=frozenset({"inventory.lookup"}),
            trusted_private_hosts=frozenset({"127.0.0.1"}),
        ),
    )
)
