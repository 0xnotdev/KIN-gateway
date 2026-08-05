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


@pytest.mark.smoke
def test_two_node_v11_session_lifecycle_real_sockets():
    """Run dispatch, receive, accept, messages, and completion over real nodes."""
    script_path = Path(__file__).parent.parent / "scripts" / "smoke_two_node.py"
    res = subprocess.run(
        [sys.executable, str(script_path), "--protocol", "v11"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(res.stdout, end="")
    print(res.stderr, end="", file=sys.stderr)
    assert res.returncode == 0, (
        f"V1.1 smoke test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "Bob subprocess storage proof" in res.stdout
    assert 'kinds=["task_request", "acceptance", "question", "answer", "final_result"]' in res.stdout
    assert "status=completed, event_count=5" in res.stdout
    assert "PASS: V1.1" in res.stdout
