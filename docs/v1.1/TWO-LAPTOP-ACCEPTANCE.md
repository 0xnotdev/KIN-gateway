# Two-laptop V1.1 acceptance
Use two independent Windows laptops, accounts, networks where practical, and
humans. Record only redacted timestamps, versions, state labels, durations, and
hash equality—not keys, phrases, content, paths, database files, or ciphertext.

1. Verify the signed `v1.1.0` tag and checksums; install from documentation on
   both clean accounts in under five minutes excluding provider setup.
2. Run `kin --version` and `kin doctor --plain`; complete First Flight and connect
   one agent per owner without database edits.
3. Start both nodes, pair by username, and compare fingerprints over a separate
   trusted channel. Review a changed card before accepting it.
4. Alice dispatches with explicit Alice/Bob agent selection. Bob accepts. Record
   time to live Arena; it must be under five seconds on a normal connection.
5. Exchange visible events. Disconnect direct reachability, confirm honest queued
   state, restart Bob, fetch through relay, and prove exactly-once reconstruction.
6. Trigger a bounded consequential action. Only its local owner may approve/deny;
   deny one crafted command/file/secret request and prove no adapter continuation.
7. Transfer an artifact; verify stored and computed SHA-256, inspect provenance and
   diff, import explicitly, and require separate approval before apply.
8. Complete the outcome; open deterministic replay a day later (or with a pinned
   test timestamp) and export. Confirm equal export hashes and policy redaction.
9. Repeat primary navigation at 80x24, high contrast, 16-color, ASCII/reduced
   motion, and plain output. Interrupt/restart and confirm no traceback or lost
   draft/focus.
10. Product and security owners sign `RELEASE-CHECKLIST.md` only if every step and
    automated CI job is green. Any failed gate is a no-release decision.
