# M7 Slice 3 — Context Pantry Boundary

Date: 2026-08-05
Spec: `KIN-V1.1-MASTER-SPEC.md` §15.10 build step 2 / §7.8

## Delivered

- `kin/context_pantry.py` implements classification, explicit review, expiry,
  size limits, encrypted opaque local-reference registration/resolution, and
  encrypted local-first context packs.
- Only reviewed, unexpired `share_with_peer` items enter the signed
  `TASK_REQUEST.context_pack`. `local_only` and `private` items remain local.
- Raw paths cannot be added through the wizard. Resolution performs one exact
  opaque-ID lookup and one exact file read. No directory enumeration API exists.
- Attaching a saved context pack is explicit and clears every review flag.

## Real / fixture boundary

Tests use real migration tables, AES-GCM encrypted paths/packs, real filesystem
files, real Ed25519 task-envelope signing, real symmetric self-ingestion, and the
real encrypted outbound queue. Network transmission is intentionally absent in
the wire test so the exact queued envelope can be decrypted and inspected locally.

## Adversarial result

An approved file is placed beside an unapproved, deliberately named secret file.
Neither directory, filename, sibling content, nor opaque reference ID appears in
the peer envelope or safe errors.

## P2 discipline

Context packs are local-first explicit attachments only. No public discovery,
reputation, payments, multi-owner teams, direct peer tool control, or graphical
client was introduced.

## Focused raw output

```text
....                                                                     [100%]
4 passed in 0.71s
```
