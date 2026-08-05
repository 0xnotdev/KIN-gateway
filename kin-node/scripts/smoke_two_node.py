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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        choices=("m0", "v11"),
        default="m0",
        help="Protocol lifecycle to exercise after the shared real-node setup.",
    )
    args = parser.parse_args()

    harness = TwoNodeSmokeHarness(enable_v11=args.protocol == "v11")
    failed = False
    try:
        harness.start()
        if args.protocol == "v11":
            evidence = harness.run_v11_lifecycle()
            _print_v11_evidence(evidence)
            print("PASS: V1.1 two-node session lifecycle over real sockets succeeded!")
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
