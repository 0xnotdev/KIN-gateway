"""Pytest wrapper for the two-process local smoke test harness."""

import re
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
    assert 'kinds=["task_request", "acceptance", "question", "answer", "final_result", "outcome"]' in res.stdout
    assert "status=completed, event_count=6" in res.stdout
    assert "PASS: V1.1" in res.stdout


@pytest.mark.smoke
def test_two_node_v11_phase_b_real_relay_restart_expiry_and_artifact():
    """Run every non-TUI Phase B gate over real relay and node subprocesses."""
    script_path = Path(__file__).parent.parent / "scripts" / "smoke_two_node.py"
    res = subprocess.run(
        [sys.executable, str(script_path), "--protocol", "v11-phase-b"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    print(res.stdout, end="")
    print(res.stderr, end="", file=sys.stderr)
    assert res.returncode == 0, (
        f"V1.1 Phase B smoke failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "dispatch=queued, queued_messages=1, first_poll=1" in res.stdout
    assert "mailbox_after_ack=0, second_poll=0, bob_event_count=1" in res.stdout
    assert "reconstructed_status=active, reconstructed_events=4" in res.stdout
    assert "final_status=completed, final_events=6" in res.stdout
    assert "success=False" in res.stdout and "has expired" in res.stdout and "decision=None" in res.stdout
    assert "delivery=direct" in res.stdout and "offered_by=alice, source=peer_received" in res.stdout
    hash_evidence = re.search(
        r"sha256=([0-9a-f]{64}), computed_sha256=([0-9a-f]{64})",
        res.stdout,
    )
    assert hash_evidence is not None, "Phase B output omitted stored/computed artifact hash evidence"
    assert hash_evidence.group(1) == hash_evidence.group(2), (
        f"Artifact hash mismatch in smoke evidence: stored={hash_evidence.group(1)} "
        f"computed={hash_evidence.group(2)}"
    )
    assert "PASS: V1.1 Phase B" in res.stdout
