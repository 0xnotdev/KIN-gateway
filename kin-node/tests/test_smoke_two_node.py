"""Pytest wrapper for the two-process local smoke test harness."""

import subprocess
import sys
from pathlib import Path
import pytest


@pytest.mark.smoke
def test_two_node_walking_skeleton_real_sockets():
    """Run two-process local smoke test harness over real TCP sockets."""
    script_path = Path(__file__).parent.parent / "scripts" / "smoke_two_node.py"
    res = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, f"Smoke test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "PASS" in res.stdout
