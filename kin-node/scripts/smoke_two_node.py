#!/usr/bin/env python3
"""Real relay + two-node smoke entry point for legacy and V1.1 protocols."""

from __future__ import annotations

import argparse
import json
import sys

from smoke_two_node_harness import TwoNodeSmokeHarness


def _print_v11_evidence(evidence: dict) -> None:
    received = evidence["bob_received"]
    alice_final = evidence["alice_final"]
    bob_final = evidence["bob_final"]
    print(f"SMOKE V1.1: session_id={evidence['session_id']}")
    print(
        "SMOKE V1.1: Bob subprocess storage proof -> "
        f"status={received['status']}, event_count={received['event_count']}, "
        f"goal={received['goal']!r}"
    )
    print(
        "SMOKE V1.1: Alice final -> "
        f"status={alice_final['status']}, event_count={alice_final['event_count']}, "
        f"kinds={json.dumps(alice_final['event_kinds'])}"
    )
    print(
        "SMOKE V1.1: Bob final -> "
        f"status={bob_final['status']}, event_count={bob_final['event_count']}, "
        f"kinds={json.dumps(bob_final['event_kinds'])}"
    )


def _print_phase_b_evidence(evidence: dict) -> None:
    relay = evidence["relay"]
    restart = evidence["restart"]
    expiry = evidence["expiry"]
    artifact = evidence["artifact"]
    assert artifact["after_restart"]["sha256"] == artifact["after_restart"]["computed_sha256"], (
        f"Artifact hash mismatch after restart: stored={artifact['after_restart']['sha256']} "
        f"computed={artifact['after_restart']['computed_sha256']}"
    )
    print(
        "SMOKE V1.1 PHASE B RELAY: "
        f"session_id={relay['session_id']}, dispatch={relay['dispatch']['status']}, "
        f"queued_messages={relay['queued_mailbox']['message_count']}, "
        f"first_poll={relay['first_poll']['processed_count']}, "
        f"consumer={relay['relay_consumer']}, "
        f"mailbox_after_ack={relay['empty_mailbox']['message_count']}, "
        f"second_poll={relay['second_poll']['processed_count']}, "
        f"bob_event_count={relay['bob_after_second_poll']['event_count']}"
    )
    print(
        "SMOKE V1.1 PHASE B RESTART: "
        f"session_id={restart['session_id']}, sigterm_returncode={restart['sigterm_returncode']}, "
        f"before_status={restart['before_crash']['status']}, "
        f"reconstructed_status={restart['reconstructed']['status']}, "
        f"reconstructed_events={restart['reconstructed']['event_count']}, "
        f"final_status={restart['final']['status']}, final_events={restart['final']['event_count']}"
    )
    print(
        "SMOKE V1.1 PHASE B EXPIRY: "
        f"session_id={expiry['session_id']}, approval_id={expiry['approval']['approval_id']}, "
        f"expires_at={expiry['approval']['expires_at']}, success={expiry['decision']['success']}, "
        f"error={expiry['decision']['error']!r}, decision={expiry['decision']['decision']}"
    )
    print(
        "SMOKE V1.1 PHASE B ARTIFACT: "
        f"session_id={artifact['session_id']}, artifact_id={artifact['offer']['artifact_id']}, "
        f"delivery={artifact['offer']['delivery']}, sha256={artifact['after_restart']['sha256']}, "
        f"computed_sha256={artifact['after_restart']['computed_sha256']}, "
        f"offered_by={artifact['after_restart']['offered_by']}, "
        f"source={artifact['after_restart']['source']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        choices=("m0", "v11", "v11-phase-b"),
        default="m0",
        help="Protocol lifecycle to exercise after the shared real-node setup.",
    )
    args = parser.parse_args()

    harness = TwoNodeSmokeHarness(enable_v11=args.protocol in {"v11", "v11-phase-b"})
    failed = False
    try:
        harness.start()
        if args.protocol == "v11":
            evidence = harness.run_v11_lifecycle()
            _print_v11_evidence(evidence)
            print("PASS: V1.1 two-node session lifecycle over real sockets succeeded!")
        elif args.protocol == "v11-phase-b":
            evidence = harness.run_v11_phase_b()
            _print_phase_b_evidence(evidence)
            print("PASS: V1.1 Phase B relay, restart, expiry, and artifact gates succeeded!")
        else:
            evidence = harness.run_legacy_task_lifecycle()
            print(f"SMOKE: Created task_id -> {evidence['task_id']}", file=sys.stderr)
            print(f"SMOKE: Bob's drafted tasks content:\n{evidence['bob_tasks']}", file=sys.stderr)
            print(f"SMOKE: Full Alice transcript at completion:\n{evidence['alice_transcript']}", file=sys.stderr)
            print("PASS: Two-process local smoke test over real sockets succeeded!")
    except Exception as exc:
        failed = True
        print(f"FAIL: Two-process local smoke test failed: {exc}", file=sys.stderr)
        raise
    finally:
        harness.cleanup()
        if failed:
            output = harness.failure_output()
            if output:
                print("\n=== SUBPROCESS OUTPUT CAPTURE ON FAILURE ===", file=sys.stderr)
                print(output, file=sys.stderr)


if __name__ == "__main__":
    main()
