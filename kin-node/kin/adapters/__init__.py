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
    InputItem,
    ValidationOutcome,
    validate_adapter_output,
)
from kin.adapters.factory import get_adapter

__all__ = [
    "AdapterRequest",
    "InputItem",
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
