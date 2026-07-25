"""KIN Adapters package."""

from kin.adapters.base import (
    AdapterActivityEvent,
    AdapterApprovalEvent,
    AdapterCapabilityDeclaration,
    AdapterErrorEvent,
    AdapterErrorInfo,
    AdapterEvent,
    AdapterMessage,
    AdapterRequest,
    AdapterResponse,
    ValidationOutcome,
    validate_adapter_output,
)
from kin.adapters.factory import get_adapter

__all__ = [
    "AdapterRequest",
    "AdapterEvent",
    "AdapterActivityEvent",
    "AdapterApprovalEvent",
    "AdapterErrorEvent",
    "AdapterResponse",
    "AdapterMessage",
    "AdapterErrorInfo",
    "AdapterCapabilityDeclaration",
    "ValidationOutcome",
    "validate_adapter_output",
    "get_adapter",
]
