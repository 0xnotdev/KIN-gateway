"""Pytest fixtures for TUI tests."""

from pathlib import Path
import pytest

from kin.tui.app import KinApp


@pytest.fixture
def tui_test_profile_root(tmp_path: Path) -> Path:
    p = tmp_path / "profiles" / "test_user"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def tui_app_instance(tui_test_profile_root: Path) -> KinApp:
    return KinApp(theme_name="kin-graphite", profile_name="test_user")
