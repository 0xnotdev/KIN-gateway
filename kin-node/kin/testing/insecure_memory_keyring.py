"""Minimal in-process dict-backed keyring backend for automated non-OS test environments."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from keyring.backend import KeyringBackend


class InMemoryTestKeyring(KeyringBackend):
    """In-memory dictionary-backed keyring backend marked for test use only."""

    KIN_TEST_BACKEND = True
    priority = 10

    def _get_storage_path(self) -> Path:
        custom_path = os.environ.get("KIN_TEST_KEYRING_PATH")
        if custom_path:
            return Path(custom_path)
        return Path(tempfile.gettempdir()) / "kin_insecure_test_keyring.json"

    def _load(self) -> dict[str, str]:
        path = self._get_storage_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self, data: dict[str, str]) -> None:
        path = self._get_storage_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def get_password(self, service: str, username: str) -> str | None:
        data = self._load()
        key = f"{service}::{username}"
        return data.get(key)

    def set_password(self, service: str, username: str, password: str) -> None:
        data = self._load()
        key = f"{service}::{username}"
        data[key] = password
        self._save(data)

    def delete_password(self, service: str, username: str) -> None:
        data = self._load()
        key = f"{service}::{username}"
        if key in data:
            del data[key]
            self._save(data)
