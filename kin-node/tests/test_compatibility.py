"""Unit tests for V1.1 capability negotiation and protocol compatibility (kin.session.compatibility)."""

import pytest

from kin.schemas import CapabilityAdvertisement
from kin.session.compatibility import IncompatibilityResult, negotiate_capability


def test_negotiate_capability_matching_protocol_and_features():
    """Matching protocol_version '1.1' + all required features present returns compatible=True."""
    ad = CapabilityAdvertisement(
        protocol_version="1.1",
        supported_features=["session_v1", "vault_gcm", "jcs_signatures"],
        max_turn_limit=12,
    )
    res = negotiate_capability(ad, required_features=["jcs_signatures", "session_v1"])
    assert isinstance(res, IncompatibilityResult)
    assert res.compatible is True
    assert res.missing_flags == []
    assert res.fallback_mode == "none"
    assert "satisfies all" in res.reason.lower()


def test_negotiate_capability_mismatched_protocol_version():
    """Mismatched protocol_version returns compatible=False with fallback_mode='v1_ask'."""
    ad = CapabilityAdvertisement(
        protocol_version="1.0",
        supported_features=["session_v1"],
        max_turn_limit=12,
    )
    res = negotiate_capability(ad, required_features=["session_v1"])
    assert res.compatible is False
    assert res.fallback_mode == "v1_ask"
    assert "incompatible" in res.reason.lower()
    assert "1.0" in res.reason


def test_negotiate_capability_missing_feature_flags():
    """Missing one or more required feature flags returns compatible=False with sorted missing_flags."""
    ad_dict = {
        "protocol_version": "1.1",
        "supported_features": ["featA", "featZ"],
        "max_turn_limit": 10,
    }
    required = ["featZ", "featB", "featA", "featC"]
    res = negotiate_capability(ad_dict, required_features=required)
    assert res.compatible is False
    assert res.fallback_mode == "v1_ask"
    # missing_flags must be sorted alphabetically: ["featB", "featC"]
    assert res.missing_flags == ["featB", "featC"]
    assert "lacks required V1.1 feature flags: featB, featC" in res.reason


def test_negotiate_capability_malformed_raw_dict_input():
    """Malformed or invalid raw dict input returns structured IncompatibilityResult and never raises unhandled exception."""
    malformed_dicts = [
        {"protocol_version": 123},  # protocol_version must be str
        {"supported_features": "not_a_list"},  # supported_features must be list
        {"max_turn_limit": -5},  # max_turn_limit must be >= 1
        {},  # missing required fields
        "not_even_a_dict",  # non-dict string input
    ]

    for raw in malformed_dicts:
        res = negotiate_capability(raw)
        assert isinstance(res, IncompatibilityResult)
        assert res.compatible is False
        assert res.fallback_mode == "v1_ask"
        assert res.missing_flags == []
        assert "invalid capability advertisement" in res.reason.lower()
