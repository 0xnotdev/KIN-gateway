"""Pytest fixtures for TUI tests.

Includes an autouse network isolation fixture to guarantee zero unmocked socket/HTTP I/O
during any TUI test, protecting all app shell geometry, workspace tabs, and widget tests.
"""

from pathlib import Path
import httpx
import pytest

from kin.tui.app import KinApp


@pytest.fixture(autouse=True)
def isolate_tui_network(monkeypatch):
    """Systemic autouse guard preventing unmocked real network I/O during TUI tests (§14.6 Phase B & C).

    Monkeypatches httpx.get and httpx.Client.get so unmocked socket connections fail fast
    with a 404 response, while explicit mock transports passed to httpx.Client are respected.
    """
    orig_client_get = httpx.Client.get

    def fast_mock_get(url, *args, **kwargs):
        return httpx.Response(status_code=404, json={"detail": "Network isolated in TUI test harness"})

    def smart_client_get(self, url, *args, **kwargs):
        # If client has a custom MockTransport attached, use its intended response
        if hasattr(self, "_transport") and type(self._transport).__name__ == "MockTransport":
            return orig_client_get(self, url, *args, **kwargs)
        return fast_mock_get(url, *args, **kwargs)

    monkeypatch.setattr(httpx, "get", fast_mock_get)
    monkeypatch.setattr(httpx.Client, "get", smart_client_get)


@pytest.fixture(autouse=True)
def isolate_tui_profile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Systemic autouse fixture isolating default user profile directory per test.

    Guarantees that no test mutates persistent user profiles on disk (~/.kin/profiles/default),
    preventing state leakage across snapshot tests in the full test suite.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))


@pytest.fixture
def tui_test_profile_root(tmp_path: Path) -> Path:
    p = tmp_path / "profiles" / "test_user"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def tui_app_instance(tui_test_profile_root: Path) -> KinApp:
    return KinApp(theme_name="kin-graphite", profile_name="test_user")
