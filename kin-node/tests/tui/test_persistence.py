"""Unit tests for UI preferences persistence and atomic file I/O.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3.4, §14.3
"""

import json
from pathlib import Path
import pytest

from kin.tui.persistence import (
    UiStatePreferences,
    get_profile_dir,
    load_ui_preferences,
    save_ui_preferences,
)


@pytest.fixture
def mock_profile_dir(tmp_path, monkeypatch):
    """Monkeypatch get_profile_dir to use a temporary directory for isolation."""
    profile_path = tmp_path / ".kin" / "profiles" / "test_profile"
    monkeypatch.setattr("kin.tui.persistence.get_profile_dir", lambda name="default": profile_path)
    return profile_path


def test_valid_file_roundtrips_correctly(mock_profile_dir):
    """Assert valid preferences round-trip to disk and back cleanly without loss."""
    prefs = UiStatePreferences(
        theme="kin-graphite",
        sidebar_width=36,
        inspector_width=40,
        sidebar_collapsed=True,
        sidebar_section_collapse={"spaces": True, "agents": False},
        inspector_visible=False,
        focus_mode_default=True,
        workspace_tabs=["home", "session:s1"],
        active_tab="session:s1",
    )
    save_ui_preferences(prefs)

    loaded, status_msg = load_ui_preferences()
    assert status_msg is None
    assert loaded == prefs
    assert loaded.sidebar_width == 36
    assert loaded.sidebar_section_collapse == {"spaces": True, "agents": False}


def test_malformed_json_resets_ui_preferences_safely(mock_profile_dir):
    """Assert malformed JSON resets only UI preferences and surfaces a quiet status message."""
    mock_profile_dir.mkdir(parents=True, exist_ok=True)
    bad_file = mock_profile_dir / "ui-state.json"
    bad_file.write_text("{invalid json content, missing quotes...", encoding="utf-8")

    loaded, status_msg = load_ui_preferences()
    assert loaded == UiStatePreferences()
    assert status_msg is not None
    assert "malformed ui-state.json" in status_msg


def test_unknown_schema_version_resets_ui_preferences_safely(mock_profile_dir):
    """Assert unknown or higher schema_version resets preferences safely with a quiet message."""
    mock_profile_dir.mkdir(parents=True, exist_ok=True)
    file_path = mock_profile_dir / "ui-state.json"

    # Higher integer version (e.g. schema_version 99)
    file_path.write_text(json.dumps({"schema_version": 99, "theme": "future-theme"}), encoding="utf-8")
    loaded, status_msg = load_ui_preferences()
    assert loaded == UiStatePreferences()
    assert status_msg is not None
    assert "unsupported schema version" in status_msg

    # Non-integer schema version (e.g. string "v1")
    file_path.write_text(json.dumps({"schema_version": "v1", "theme": "custom"}), encoding="utf-8")
    loaded_str, status_msg_str = load_ui_preferences()
    assert loaded_str == UiStatePreferences()
    assert status_msg_str is not None
    assert "unsupported schema version" in status_msg_str


def test_missing_file_creates_defaults_atomically(mock_profile_dir):
    """Assert missing file creates default ui-state.json atomically without error."""
    file_path = mock_profile_dir / "ui-state.json"
    assert not file_path.exists()

    loaded, status_msg = load_ui_preferences()
    assert status_msg is None
    assert loaded == UiStatePreferences()
    assert file_path.is_file()

    # Verify written JSON
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["sidebar_width"] == 32


def test_out_of_range_values_are_clamped_to_valid_bounds(mock_profile_dir):
    """Assert out-of-range dimensions are clamped to nearest valid bounds without resetting file."""
    mock_profile_dir.mkdir(parents=True, exist_ok=True)
    file_path = mock_profile_dir / "ui-state.json"

    # sidebar_width 99 (above 42 max), inspector_width 10 (below 30 min)
    raw_data = {
        "schema_version": 1,
        "theme": "kin-graphite",
        "sidebar_width": 99,
        "inspector_width": 10,
        "sidebar_collapsed": True,
    }
    file_path.write_text(json.dumps(raw_data), encoding="utf-8")

    loaded, status_msg = load_ui_preferences()
    assert status_msg is None
    assert loaded.sidebar_width == 42  # clamped from 99 to max 42
    assert loaded.inspector_width == 30  # clamped from 10 to min 30
    assert loaded.sidebar_collapsed is True  # preserved!


def test_compatible_upgrade_loads_missing_fields_with_defaults(mock_profile_dir):
    """Assert v1 file missing newer optional fields loads missing fields with defaults."""
    mock_profile_dir.mkdir(parents=True, exist_ok=True)
    file_path = mock_profile_dir / "ui-state.json"

    # Older v1 schema without sidebar_section_collapse or focus_mode_default
    raw_data = {
        "schema_version": 1,
        "theme": "kin-graphite",
        "sidebar_width": 36,
        "sidebar_collapsed": True,
    }
    file_path.write_text(json.dumps(raw_data), encoding="utf-8")

    loaded, status_msg = load_ui_preferences()
    assert status_msg is None
    assert loaded.sidebar_width == 36
    assert loaded.sidebar_collapsed is True
    # Missing fields populated with model defaults
    assert loaded.sidebar_section_collapse == {}
    assert loaded.focus_mode_default is False
    assert loaded.inspector_width == 38


def test_atomic_write_preserves_existing_valid_file_on_crash(mock_profile_dir, monkeypatch):
    """Assert write failure leaves original file content 100% untouched (§3.4, §14.3)."""
    mock_profile_dir.mkdir(parents=True, exist_ok=True)

    initial_prefs = UiStatePreferences(sidebar_width=30, theme="kin-graphite")
    save_ui_preferences(initial_prefs)

    file_path = mock_profile_dir / "ui-state.json"
    assert file_path.is_file()
    initial_content = file_path.read_text(encoding="utf-8")

    def mock_replace_raises(self, target):
        raise IOError("Simulated atomic replace failure during disk write")

    monkeypatch.setattr(Path, "replace", mock_replace_raises)

    new_prefs = UiStatePreferences(sidebar_width=40, theme="invalid-crash-theme")
    with pytest.raises(IOError, match="Simulated atomic replace failure"):
        save_ui_preferences(new_prefs)

    assert file_path.read_text(encoding="utf-8") == initial_content
    loaded, status_msg = load_ui_preferences()
    assert status_msg is None
    assert loaded.sidebar_width == 30
    assert loaded.theme == "kin-graphite"
