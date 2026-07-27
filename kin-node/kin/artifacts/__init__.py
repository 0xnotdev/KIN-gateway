"""Artifact vault package for encrypted artifact storage (§15.8)."""

from kin.artifacts.vault import (
    ArtifactCorruptedError,
    ArtifactIdConflictError,
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    get_artifact_metadata,
    load_artifact_bytes,
    store_artifact,
)

__all__ = [
    "ArtifactCorruptedError",
    "ArtifactIdConflictError",
    "ArtifactMetadata",
    "ArtifactNotFoundError",
    "ArtifactTooLargeError",
    "get_artifact_metadata",
    "load_artifact_bytes",
    "store_artifact",
]
