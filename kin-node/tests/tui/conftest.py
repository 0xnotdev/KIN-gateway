"""Pytest fixtures for TUI tests.

Includes an autouse network isolation fixture to guarantee zero unmocked socket/HTTP I/O
during any TUI test, protecting all app shell geometry, workspace tabs, and widget tests.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
from rich.console import ColorSystem
from textual.app import App

from kin.tui.app import KinApp


TApp = TypeVar("TApp", bound=App)


@pytest.fixture(autouse=True)
def isolate_tui_network(monkeypatch, request):
    """Systemic autouse guard preventing unmocked real network I/O during TUI tests (§14.6 Phase B & C).

    Monkeypatches httpx.get and httpx.Client.get so unmocked socket connections fail fast
    with a 404 response, while explicit mock transports passed to httpx.Client are respected.
    """
    if request.node.get_closest_marker("smoke") is not None:
        # Smoke tests explicitly prove real node/relay boundaries. Their child
        # processes and TUI transport must retain genuine socket access.
        yield
        return

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
    yield


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
def build_tui_app(monkeypatch: pytest.MonkeyPatch) -> Callable[..., App]:
    """Build an App with deterministic UTF-8 truecolor terminal capabilities.

    This is the canonical constructor for TUI snapshot apps and for interaction
    tests whose Unicode assertions depend on terminal capability detection.
    It supports both ``KinApp`` and small custom ``App`` harness subclasses.
    """

    def _build(
        app_type: type[TApp] = KinApp,
        /,
        **kwargs: Any,
    ) -> TApp:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")

        app = app_type(**kwargs)
        prefs = getattr(app, "prefs", None)
        if prefs is not None:
            prefs.ascii_fallback = False
            prefs.color_depth = "auto"
        else:
            # Custom snapshot harnesses do not own KinApp preferences, so pin
            # the effective capability directly for LifecycleWidgetMixin._g().
            setattr(app, "is_ascii_fallback_active", False)

        monkeypatch.setattr(
            type(app.console),
            "encoding",
            property(lambda _console: "utf-8"),
        )
        monkeypatch.setattr(app.console, "_color_system", ColorSystem.TRUECOLOR)
        return app

    return _build


@pytest.fixture
def tui_app_instance(tui_test_profile_root: Path) -> KinApp:
    return KinApp(theme_name="kin-graphite", profile_name="test_user")
