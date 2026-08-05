"""Production lifecycle coverage for durable two-node synchronization."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

import kin.node.app as node_app_module


def test_fastapi_lifespan_starts_real_synchronization_scheduler(monkeypatch, tmp_path: Path):
    called = Event()

    def synchronization_pass(app):
        assert app.state.profile_name == "runtime-test"
        assert app.state.db_path == tmp_path / "kin.db"
        called.set()

    monkeypatch.setattr(node_app_module, "_synchronize_once", synchronization_pass)
    node_app_module.app.state.profile_name = "runtime-test"
    node_app_module.app.state.db_path = tmp_path / "kin.db"

    with TestClient(node_app_module.app):
        assert called.wait(timeout=2), "node startup did not begin the synchronization loop"
