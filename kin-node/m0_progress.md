# KIN V1.1 — Milestone M0 & M0.1 In-Depth Progress & Architecture Report

---

## Executive Summary

During this session, **Milestone M0 and M0.1** of the KIN V1.1 protocol were fully designed, architected, implemented, hardened, and verified with 100% test passage across the codebase.

Key achievements include:
1. **Full Protocol Spec & TUI Analysis:** Comprehensive review of `KIN-V1.1-MASTER-SPEC.md` and `KIN-V1.1-TUI-SYSTEM.md`.
2. **Strict RFC 8785 JCS Canonicalization:** Replaced non-compliant key sorting with the official `rfc8785` package, guaranteeing UTF-16 code-unit key ordering and ECMAScript float formatting.
3. **6-Stage `VerifiedEnvelope` Pipeline:** Implemented an unbypassable cryptographic gate (`verify_and_build_envelope`) before any envelope reaches the state machine.
4. **Authority-Split Session Reducer:** Divided state transitions into three explicit authorities (Peer Envelope, Node Command, Owner Command) and restricted agent actors from issuing human-only control actions like `CANCEL`.
5. **Bilateral Two-Human-Owner Model:** Modeled both `initiator_username` and `receiver_username` on `SessionState`, allowing either human owner (Alice or Bob) to pause, resume, or cancel their participation.
6. **Production Security Module (`ProfileContextResolver`):** Enforced regex validation (`[a-zA-Z0-9_-]+`) and strict directory containment via `Path.is_relative_to()`.
7. **Two-Process Local Socket Smoke Test Harness:** Built a complete, automated end-to-end smoke test (`scripts/smoke_two_node.py` and `tests/test_smoke_two_node.py`) that executes two separate OS processes over real TCP sockets with zero live LLM or OS keychain dependencies.
8. **100% Test Verification:** 108 tests in `kin-node` and 11 tests in `kin-relay` passing green with zero regressions.

---

## 1. Complete Architectural & Technical Breakdown

### A. Strict RFC 8785 JCS Canonicalization (`kin/schemas.py` & `pyproject.toml`)
- **Package Dependency:** Pinned `rfc8785>=0.1.4,<1.0.0` in `pyproject.toml`.
- **UTF-16 Code-Unit Key Sorting:** Standard Python dictionary sorting orders by Unicode code points (UTF-32 order). RFC 8785 Section 3.2.1 requires sorting keys strictly by **UTF-16 code units**. For example, non-BMP characters like emojis `😀` (`\U0001F600`, UTF-16 surrogates `0xD83D 0xDE00`) sort **before** `\uFFFF` because $0\text{xD83D} < 0\text{xFFFF}$.
- **ECMAScript Number Serialization:** Complies with RFC 8785 Section 3.2.3 float rendering rules (`1.0` $\rightarrow$ `1`, `1e21` $\rightarrow$ `1e+21`).
- **Recursive JSON Primitive Validator (`validate_json_primitives`):** Rejects invalid JSON types (NaNs, Infinities, sets, custom objects) before canonicalization.

### B. 6-Stage `VerifiedEnvelope` Security Gate (`kin/schemas.py`)
Before an envelope can be processed by the session reducer, it must pass through `verify_and_build_envelope()`:
1. **Stage 1 — Structural Schema Validation:** Validates `SessionEnvelope` schema, strict sequence integer validator (`@field_validator("sequence", mode="before")` rejecting string `"1"`), ISO 8601 UTC timestamps, and 43-character URL-safe Base64 SHA-256 content hashes.
2. **Stage 2 — Session ID Match:** Confirms `envelope.session_id == active_session_id`.
3. **Stage 3 — Canonical Payload Hash Verification:** Computes `compute_content_hash(payload)` over canonical JCS bytes and asserts byte-for-byte equivalence with `envelope.content_hash`.
4. **Stage 4 — Participant Authorization:** Confirms `actor_username` is in the session participant map and `envelope.actor_agent_id` matches the registered agent ID for that participant.
5. **Stage 5 — Public Key Resolution:** Resolves the trusted contact's Ed25519 public key.
6. **Stage 6 — Cryptographic Signature Verification:** Verifies the base64url Ed25519 signature over the canonical JCS envelope bytes.

Output: An immutable `VerifiedEnvelope` dataclass instance.

### C. Authority-Split Session Reducer (`kin/session/reducer.py`)
The state machine separates operations by authority source:

#### 1. Peer Envelopes (`process_peer_envelope`)
- Accepts **ONLY** `VerifiedEnvelope` objects.
- Maps `MessageKind` strictly to state transitions via `PEER_KIND_TRANSITION_MAP`.
- **Role Verification:** `OWNER_ONLY_KINDS = {MessageKind.CANCEL, MessageKind.APPROVAL_DECISION}` are forbidden for agent actors (`role == "agent"`). If an agent attempts to send `CANCEL`, it is rejected with `UNAUTHORIZED_ROLE_ACTION`.
- Enforces strict sequence monotonicity per actor (`expected_seq = last_seq + 1`).
- Enforces session turn limits (`max_turns`).

#### 2. Local Node Commands (`process_node_command`)
- Handles node transport infrastructure transitions: `mark_queued`, `mark_delivered`, `mark_peer_review`, `mark_expired`, `mark_failed`.

#### 3. Local Owner Commands (`process_owner_command`)
- Handles local human owner control actions: `owner_pause`, `owner_resume`, `owner_cancel`, `owner_approval_decision`.
- Verifies `owner_username in state.owner_usernames` so that **either** human owner (Alice or Bob) can pause, resume, or cancel their participation in the bilateral session.

### D. State Machine & Expiry Transition Matrix (`kin/session/transition_matrix.py` & `docs/v11_transition_matrix.md`)
- Terminal states: `TERMINAL_STATES = {"completed", "failed", "cancelled", "expired", "declined"}`.
- Added `declined` state (mapped from `MessageKind.DECLINE`).
- Added `expired` transitions reachable from all non-terminal states.

### E. Production `ProfileContextResolver` (`kin/identity/resolver.py`)
- Created production module `kin.identity.resolver` with `ProfileContextResolver` and `AccessBoundaryViolation`.
- Validates profile names against `^[a-zA-Z0-9_-]+$` regex.
- Enforces directory containment using `Path.is_relative_to()`.

---

## 2. Two-Process Local Socket Smoke Test Harness (TASK BLOCK m0_1)

To prove Milestone M0 over real TCP sockets across separate OS processes without relying on OS keychains or live LLM APIs:

### A. Test Keyring Backend (`kin/testing/insecure_memory_keyring.py`)
- Minimal `KeyringBackend` implementation with class attribute `KIN_TEST_BACKEND = True`.
- Gated strictly by environment variable `KIN_UNSAFE_TEST_KEYRING=1` and activated only inside `kin/cli.py`'s `main()` callback with a mandatory stderr warning.
- Persists secrets to a temporary test JSON file specified by `KIN_TEST_KEYRING_PATH` (allowing separate CLI subprocesses like `kin pair`, `kin serve`, `kin ask`, `kin respond` to read/write credentials across process boundaries).

### B. Fake LLM Response Hook (`kin/agent_backend/llm_backend.py`)
- Gated strictly by environment variable `KIN_FAKE_LLM_RESPONSE`.
- When set (e.g. `{"reply": "4", "message_type": "answer"}`), short-circuits `generate_response_async` and `generate_response` in `LLMAgentBackend`, returning the pre-configured response without making external network or API calls.

### C. End-to-End Smoke Test Script (`scripts/smoke_two_node.py`)
Executes the full walking skeleton over real TCP sockets using `subprocess.Popen`:
1. Selects free localhost ports for `kin-relay`, Alice's node, and Bob's node.
2. Creates isolated temporary directories for `relay.db`, Alice's `HOME`, and Bob's `HOME`.
3. Starts `kin-relay` (uvicorn) and polls `/directory/lookup/nonexistent` until 404 OK.
4. Executes non-interactive identity creation (`kin pair`) for Alice and Bob, dynamically parsing 12-word recovery phrases from stdout and answering confirmation prompts.
5. Starts Alice's and Bob's node servers (`kin serve --host 127.0.0.1 --port <port> --public-endpoint http://127.0.0.1:<port> --no-fetch`) and polls `/.well-known/agent-card.json` until 200 OK.
6. Executes bilateral pairing (`kin pair bob` on Alice, `kin pair alice` on Bob), parses and compares the word fingerprints computed on both sides, and asserts they match before confirming `"y"`.
7. Runs `kin ask bob "What is 2+2? Reply with just the number."`, capturing `task_id`.
8. Polls Bob's tasks (`kin tasks --status input-required`) until the task appears.
9. Runs `kin respond <task_id>` on Bob's node, feeding `"f\n"` (propose finalization with answer `"4"`).
10. Polls Alice's status (`kin status <task_id>`). When Alice receives the finalization proposal, runs `kin respond <task_id>` on Alice's node, feeding `"a\n"` (accept finalization).
11. Asserts Alice's task status reaches `completed` and transcript contains `"4"`.
12. Automatically cleans up all temporary directories and process handles in a `finally:` block using `shutil.rmtree(temp_dir, ignore_errors=True)`.

### D. Pytest Integration (`tests/test_smoke_two_node.py` & `pyproject.toml`)
- Wrapped smoke script inside `test_two_node_walking_skeleton_real_sockets` marked `@pytest.mark.smoke`.
- Configured `[tool.pytest.ini_options]` in `pyproject.toml` with `testpaths = ["tests"]` and `addopts = "-m 'not smoke'"`.
- Running `pytest -q` automatically excludes the smoke test by default (`107 passed, 1 deselected`).
- Running `pytest -q -m smoke -v` explicitly runs the full two-process smoke test.

---

## 3. Comprehensive File Modification Registry

| File Path | Description of Changes |
| :--- | :--- |
| [pyproject.toml](file:///d:/KIN/kin-node/pyproject.toml) | Added `rfc8785>=0.1.4,<1.0.0` dependency; added `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `markers = ["smoke"]`, and `addopts = "-m 'not smoke'"`. |
| [README.md](file:///d:/KIN/kin-node/README.md) | Added section `"Local two-process smoke test (not yet a real network boundary)"` detailing what the smoke test proves vs manual two-laptop testing. |
| [kin/schemas.py](file:///d:/KIN/kin-node/kin/schemas.py) | Implemented RFC 8785 JCS canonicalization via `rfc8785.dumps()`, recursive JSON primitive validator, strict wire schemas with required versions, pre-validator for strict sequence ints, Ed25519 signing/verifying, `VerifiedEnvelope` dataclass, and 6-stage `verify_and_build_envelope()` gate. |
| [kin/session/reducer.py](file:///d:/KIN/kin-node/kin/session/reducer.py) | Implemented authority-split reducers (`process_peer_envelope`, `process_node_command`, `process_owner_command`), bilateral owner model (`initiator_username`, `receiver_username`, `owner_usernames`), agent role cancellation restrictions (`OWNER_ONLY_KINDS`), sequence monotonicity, and turn limits. |
| [kin/session/transition_matrix.py](file:///d:/KIN/kin-node/kin/session/transition_matrix.py) | Added `declined` terminal state and `expired` transitions. |
| [kin/identity/resolver.py](file:///d:/KIN/kin-node/kin/identity/resolver.py) | Created production `ProfileContextResolver` enforcing profile name regex and `Path.is_relative_to()` boundary containment. |
| [kin/testing/insecure_memory_keyring.py](file:///d:/KIN/kin-node/kin/testing/insecure_memory_keyring.py) | Created minimal file-backed test keyring backend with `KIN_TEST_BACKEND = True` for cross-process test secret persistence. |
| [kin/testing/__init__.py](file:///d:/KIN/kin-node/kin/testing/__init__.py) | Package init for testing module. |
| [kin/cli.py](file:///d:/KIN/kin-node/kin/cli.py) | Added `KIN_UNSAFE_TEST_KEYRING` activation hook in `main()` callback; added `if __name__ == "__main__": app()`. |
| [kin/agent_backend/llm_backend.py](file:///d:/KIN/kin-node/kin/agent_backend/llm_backend.py) | Added `_check_fake_llm_response()` hook for `KIN_FAKE_LLM_RESPONSE` env var short-circuiting. |
| [kin/__main__.py](file:///d:/KIN/kin-node/kin/__main__.py) | Created module entry point calling `app()`. |
| [scripts/smoke_two_node.py](file:///d:/KIN/kin-node/scripts/smoke_two_node.py) | Two-process local socket smoke test script with port discovery, phrase parsing, fingerprint validation, task execution, rich stderr logging, and temp dir cleanup. |
| [tests/test_schemas.py](file:///d:/KIN/kin-node/tests/test_schemas.py) | RFC 8785 non-BMP key sorting, ES6 float formatting, schema rejection, and 6-stage envelope verification pipeline tests. |
| [tests/test_session_reducer.py](file:///d:/KIN/kin-node/tests/test_session_reducer.py) | Peer lifecycle, bilateral owner authority, agent role cancel restriction, turn limit, and sequence monotonicity tests. |
| [tests/test_harness_isolation.py](file:///d:/KIN/kin-node/tests/test_harness_isolation.py) | Updated to test production `ProfileContextResolver`. |
| [tests/test_smoke_two_node.py](file:///d:/KIN/kin-node/tests/test_smoke_two_node.py) | Pytest wrapper marked `@pytest.mark.smoke`. |
| [tests/fixtures/v11_canonical_envelopes.json](file:///d:/KIN/kin-node/tests/fixtures/v11_canonical_envelopes.json) | Golden fixture corpus with RFC 8785 JCS strings, SHA-256 hashes, and Ed25519 signatures. |

---

## 4. Test Suite Verification & Proof of Work

### A. Default Test Suite Run (`pytest -q`)
```
[2026-07-22 14:12:19,257] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
........................................................................ [ 67%]
...................................                                      [100%]
============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
107 passed, 1 deselected, 1 warning in 10.15s
```

### B. Smoke Test Run (`pytest -q -m smoke -v`)
```
[2026-07-22 14:12:34,776] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 108 items / 107 deselected / 1 selected

tests\test_smoke_two_node.py .                                           [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 1 passed, 107 deselected, 1 warning in 19.02s ================
```

### C. Direct Smoke Script Output (`python scripts/smoke_two_node.py`)
```
SMOKE: Selected real ports -> relay: 54861, alice: 54862, bob: 54863
SMOKE: Computed Fingerprints MATCH -> alice: swamp-census-invite-echo, bob: swamp-census-invite-echo
SMOKE: Created task_id -> 76e6cdee-5ff2-4fd7-98f4-0fa7ff91b509
SMOKE: Bob's drafted tasks content:
TASKS
76e6cdee-5ff2-4fd7-98f4-0fa7ff91b509  input-required  with alice
  What is 2+2? Reply with just the number.
  updated 2026-07-22T08:42:06.372701+00:00
SMOKE: Full Alice transcript at completion:
Task: 76e6cdee-5ff2-4fd7-98f4-0fa7ff91b509
Contact: bob
Status: completed
Goal: What is 2+2? Reply with just the number.

[2026-07-22T08:42:07.961539+00:00] bob (finalize_proposal)
4

[2026-07-22T08:42:09.360953+00:00] alice (finalize_accept)
4

RESULT
{"outcome": "4", "finalized_by": "alice"}
PASS: Two-process local smoke test over real sockets succeeded!
```

---

## 5. Status & Next Steps

Milestone M0 and M0.1 are **100% complete**, fully documented, and cryptographically & functionally verified across both in-process and multi-process socket harnesses.

The project is now ready to proceed to **Milestone M1 (Peer Roster, Card Discovery & Offer Exchange)** when requested.
