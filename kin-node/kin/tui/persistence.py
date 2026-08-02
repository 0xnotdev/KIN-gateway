"""UI Preferences Persistence for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.3, §3.4, §14.3
"""

import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from kin.tui.layout import (
    INSPECTOR_DEFAULT_WIDTH,
    INSPECTOR_MAX_WIDTH,
    INSPECTOR_MIN_WIDTH,
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
    clamp_inspector_width,
    clamp_sidebar_width,
)


from typing import Any, Dict, List, Literal, Optional, Tuple


class UiStatePreferences(BaseModel):
    """Pydantic model representing ui-state.json preferences (§3.4, §14.3).

    Strictly forbids extra fields to ensure schema integrity.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    theme: str = "kin-graphite"
    sidebar_width: int = Field(SIDEBAR_DEFAULT_WIDTH, ge=SIDEBAR_MIN_WIDTH, le=SIDEBAR_MAX_WIDTH)
    inspector_width: int = Field(INSPECTOR_DEFAULT_WIDTH, ge=INSPECTOR_MIN_WIDTH, le=INSPECTOR_MAX_WIDTH)
    sidebar_collapsed: bool = False
    sidebar_section_collapse: Dict[str, bool] = Field(default_factory=dict)
    inspector_visible: bool = True
    focus_mode_default: bool = False
    workspace_tabs: List[str] = Field(default_factory=lambda: ["home"])
    active_tab: str = "home"
    first_flight_progress: Dict[str, Any] = Field(default_factory=dict)
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"
    snoozed_items: Dict[str, str] = Field(default_factory=dict)
    reduced_motion: bool = False
    ascii_fallback: bool = False
    color_depth: str = "auto"


def get_profile_dir(profile_name: str = "default") -> Path:
    """Compute profile directory path independently (Path.home() / '.kin' / 'profiles' / profile_name)."""
    return Path.home() / ".kin" / "profiles" / profile_name


def load_ui_preferences(profile_name: str = "default") -> Tuple[UiStatePreferences, Optional[str]]:
    """Load UI preferences from <profile_dir>/ui-state.json.

    Returns:
      (preferences, quiet_status_message_if_reset)

    Behaviors per §14.3:
      - Missing file: creates default file atomically, status_msg = None.
      - Malformed JSON: resets ONLY UI preferences to defaults, status_msg set.
      - Unknown schema_version (!= 1 or non-int): resets ONLY UI preferences to defaults, status_msg set.
      - Out-of-range values: clamps sidebar_width and inspector_width to nearest bound instead of rejecting file.
      - Compatible upgrade: loads missing optional fields with defaults while preserving existing fields.
    """
    profile_dir = get_profile_dir(profile_name)
    file_path = profile_dir / "ui-state.json"

    if not file_path.is_file():
        default_prefs = UiStatePreferences()
        save_ui_preferences(default_prefs, profile_name)
        return default_prefs, None

    try:
        raw_text = file_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception:
        # Malformed JSON
        default_prefs = UiStatePreferences()
        return default_prefs, "Loaded default UI preferences due to malformed ui-state.json."

    if not isinstance(data, dict):
        return UiStatePreferences(), "Loaded default UI preferences due to malformed ui-state.json."

    # Check schema_version: must be int and equal to 1
    ver = data.get("schema_version")
    if not isinstance(ver, int) or ver != 1:
        return (
            UiStatePreferences(),
            f"Loaded default UI preferences due to unsupported schema version ('{ver}').",
        )

    # Clamp out-of-range dimensions if present
    if "sidebar_width" in data and isinstance(data["sidebar_width"], (int, float)):
        data["sidebar_width"] = clamp_sidebar_width(int(data["sidebar_width"]))
    if "inspector_width" in data and isinstance(data["inspector_width"], (int, float)):
        data["inspector_width"] = clamp_inspector_width(int(data["inspector_width"]))

    # Attempt parsing with Pydantic
    try:
        prefs = UiStatePreferences.model_validate(data)
        return prefs, None
    except Exception:
        # Fallback gracefully if unknown extra fields or invalid data types
        return UiStatePreferences(), "Loaded default UI preferences due to invalid settings in ui-state.json."


def save_ui_preferences(prefs: UiStatePreferences, profile_name: str = "default") -> None:
    """Atomic write of ui-state.json (write to temp file in target dir, then replace)."""
    profile_dir = get_profile_dir(profile_name)
    profile_dir.mkdir(parents=True, exist_ok=True)

    file_path = profile_dir / "ui-state.json"
    temp_path = profile_dir / "ui-state.json.tmp"

    data_str = prefs.model_dump_json(indent=2)
    temp_path.write_text(data_str, encoding="utf-8")
    temp_path.replace(file_path)
