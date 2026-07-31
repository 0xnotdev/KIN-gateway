"""Centralized TUI Content Redaction Module for KIN V1.1.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5 (Phase D build step 5)
"""

import re
from typing import Final, Optional

from kin.adapters.base import FORBIDDEN_REASONING_KEYS, SECRET_PATTERN_REGEX

# Additional secret patterns specific to common API keys and tokens
TUI_SECRET_REGEX = re.compile(
    r"(?i)(api[_-]?key\s*[:=]\s*[^\s,;]+|"
    r"secret[_-]?key\s*[:=]\s*[^\s,;]+|"
    r"access[_-]?token\s*[:=]\s*[^\s,;]+|"
    r"password\s*[:=]\s*[^\s,;]+|"
    r"token\s*[:=]\s*[^\s,;]+|"
    r"bearer\s+[a-zA-Z0-9_\-\.]{20,}|"
    r"sk[_-]live[_-][a-zA-Z0-9]{24,}|"
    r"sk[_-]proj[_-][a-zA-Z0-9_\-]{24,}|"
    r"sk[_-][a-zA-Z0-9]{24,}|"
    r"ghp_[a-zA-Z0-9]{36}|"
    r"AWS_[A-Z0-9]{20})"
)

# Absolute filesystem path regexes (Windows C:\... and POSIX /home/... /Users/...)
PATH_WIN_REGEX = re.compile(r"(?i)[a-z]:\\[^\s:?\"<>|]{4,}")
PATH_POSIX_REGEX = re.compile(r"/(?:Users|home|private|root|var|etc)/[^\s:?\"<>|]{3,}")

# Chain-of-thought and scratchpad tags/blocks regex
COT_TAG_REGEX = re.compile(
    r"(?i)(<think>.*?</think>|<scratchpad>.*?</scratchpad>|chain\s*of\s*thought\s*:\s*[^\n]+|internal\s*reasoning\s*:\s*[^\n]+)",
    re.DOTALL,
)


def redact_ui_text(text: Optional[str]) -> str:
    """Centralized text scrubbing function for all free-form TUI text (§14.5).

    Redacts:
    1. Secrets, API keys, and tokens -> '[REDACTED SECRET]'
    2. Absolute local file paths -> '[REDACTED PATH]'
    3. Chain-of-thought reasoning and scratchpads -> '[reasoning hidden]'
    """
    if not text or not isinstance(text, str):
        return "" if text is None else str(text)

    scrubbed = text

    # 1. Redact Chain-of-Thought & Scratchpads
    scrubbed = COT_TAG_REGEX.sub("[reasoning hidden]", scrubbed)

    # 2. Redact Secrets & API Keys (adapters regex + TUI extended regex)
    scrubbed = SECRET_PATTERN_REGEX.sub("[REDACTED SECRET]", scrubbed)
    scrubbed = TUI_SECRET_REGEX.sub("[REDACTED SECRET]", scrubbed)

    # 3. Redact Absolute Filesystem Paths
    scrubbed = PATH_WIN_REGEX.sub("[REDACTED PATH]", scrubbed)
    scrubbed = PATH_POSIX_REGEX.sub("[REDACTED PATH]", scrubbed)

    return scrubbed


def contains_secrets_or_paths(text: str) -> bool:
    """Return True if text contains unredacted secret patterns or absolute paths."""
    if not text or not isinstance(text, str):
        return False

    return bool(
        SECRET_PATTERN_REGEX.search(text)
        or TUI_SECRET_REGEX.search(text)
        or PATH_WIN_REGEX.search(text)
        or PATH_POSIX_REGEX.search(text)
        or COT_TAG_REGEX.search(text)
    )
