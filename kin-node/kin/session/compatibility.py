"""V1.1 Capability advertisement and protocol compatibility negotiation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from kin.schemas import CapabilityAdvertisement


class IncompatibilityResult(BaseModel):
    compatible: bool
    missing_flags: list[str] = Field(default_factory=list)
    fallback_mode: str = "v1_ask"
    reason: str


def negotiate_capability(
    peer_advertisement: CapabilityAdvertisement | dict,
    required_features: list[str] | None = None,
) -> IncompatibilityResult:
    """Evaluate peer CapabilityAdvertisement against V1.1 requirements."""
    if isinstance(peer_advertisement, dict):
        try:
            peer_ad = CapabilityAdvertisement.model_validate(peer_advertisement)
        except Exception as e:
            return IncompatibilityResult(
                compatible=False,
                missing_flags=[],
                fallback_mode="v1_ask",
                reason=f"Invalid capability advertisement payload: {e}",
            )
    elif isinstance(peer_advertisement, CapabilityAdvertisement):
        peer_ad = peer_advertisement
    else:
        return IncompatibilityResult(
            compatible=False,
            missing_flags=[],
            fallback_mode="v1_ask",
            reason=f"Invalid capability advertisement payload: expected dict or CapabilityAdvertisement, got {type(peer_advertisement).__name__}",
        )

    if peer_ad.protocol_version != "1.1":
        return IncompatibilityResult(
            compatible=False,
            missing_flags=[],
            fallback_mode="v1_ask",
            reason=f"Peer protocol version '{peer_ad.protocol_version}' is incompatible with V1.1.",
        )

    required = set(required_features or [])
    supported = set(peer_ad.supported_features)
    missing = sorted(list(required - supported))

    if missing:
        return IncompatibilityResult(
            compatible=False,
            missing_flags=missing,
            fallback_mode="v1_ask",
            reason=f"Peer lacks required V1.1 feature flags: {', '.join(missing)}.",
        )

    return IncompatibilityResult(
        compatible=True,
        missing_flags=[],
        fallback_mode="none",
        reason="Peer satisfies all V1.1 capability requirements.",
    )
