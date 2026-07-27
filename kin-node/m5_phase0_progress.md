# Milestone M5 Phase 0 — Baseline Integrity Gate Progress Report

**Issued by**: Claude (Tech Lead)  
**Executed by**: Antigravity (Execution Engine)  
**Date**: 2026-07-25  

---

## 1. Pre-Fix Reproduction Evidence

### Defect A Reproduction
Command:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"
py -3.11 -m pytest -q
```
Raw Output BEFORE fix:
```text
[2026-07-25 23:26:16,738] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
.....................................................F.F.....FF..FFF..F. [ 25%]
................F.......................................................... [ 51%]
........................................................................ [ 77%]
................................................................         [100%]
================================== FAILURES ===================================
____________________________ test_cli_ask_success _____________________________
...
AssertionError: assert 1 == 0
______________________ test_cli_ask_relays_error_cleanly ______________________
...
AssertionError: assert 'Error from receiving node: Requester is not a verified contact.' in 'WARNING: KIN_UNSAFE_TEST_KEYRING=1 — using an insecure in-memory keyring. Test use only.\nError loading private key from keychain: Private key not found for profile: test-p\n'
...
_____________________ test_cli_fetch_success_and_warnings _____________________
...
>           assert "Successfully processed new task." in output
E           assert 'Successfully processed new task.' in "Fetched 6 message(s) from relay.\nProcessing message 1/6 from 'bob'...\nProcessing message 2/6 from 'bob'...\nProcess...essage.\nWarning: Decryption failed for message from 'bob': Ciphertext too short to contain nonce. Skipping message.\n"

FAILED tests/test_cli_ask.py::test_cli_ask_success - assert 1 == 0
FAILED tests/test_cli_ask.py::test_cli_ask_relays_error_cleanly - AssertionEr...
FAILED tests/test_cli_ask.py::test_cli_respond_happy_path - assert 1 == 0
FAILED tests/test_cli_ask.py::test_cli_respond_cancel - assert 1 == 0
FAILED tests/test_cli_ask.py::test_cli_respond_finalize_proposal_accept - ass...
FAILED tests/test_cli_ask.py::test_cli_respond_finalize_proposal_reject - ass...
FAILED tests/test_cli_ask.py::test_cli_respond_finalize_option - assert 1 == 0
FAILED tests/test_cli_ask.py::test_finalize_accept_outcome_byte_identical - a...
FAILED tests/test_cli_relay_fallback.py::test_cli_fetch_success_and_warnings
9 failed, 271 passed, 1 deselected, 1 warning in 22.59s
```

And when running `test_cli_relay_fallback.py` alone:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"; py -3.11 -m pytest tests/test_cli_relay_fallback.py -q
```
```text
FAILED tests/test_cli_relay_fallback.py::test_cli_fetch_success_and_warnings
1 failed, 4 passed in 5.14s
```

### Defect A New Regression Test Pre-Fix Failure
Command:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"; py -3.11 -m pytest tests/test_keyring_isolation.py -v
```
Raw Output BEFORE fix:
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_keyring_isolation.py::test_isolation_part1 PASSED             [ 50%]
tests/test_keyring_isolation.py::test_isolation_part2 FAILED             [100%]

================================== FAILURES ===================================
____________________________ test_isolation_part2 _____________________________

    def test_isolation_part2():
        """Test 2 must NOT see private key saved by Test 1 for profile 'test-p'."""
        keyring.set_keyring(InMemoryTestKeyring())
>       with pytest.raises(SecretNotFoundError):
E       Failed: DID NOT RAISE SecretNotFoundError

tests\test_keyring_isolation.py:22: Failed
=========================== short test summary info ===========================
FAILED tests/test_keyring_isolation.py::test_isolation_part2 - Failed: DID NO...
========================= 1 failed, 1 passed in 0.31s =========================
```

---

## 2. Root Cause Analysis (Defect A)

`kin/testing/insecure_memory_keyring.py`'s `InMemoryTestKeyring` was persisting all keyring data to a single fixed path:
```python
Path(tempfile.gettempdir()) / "kin_insecure_test_keyring.json"
```
Because no test-scoped override was wired up in `tests/conftest.py`, and multiple test files (`test_cli_ask.py`, `test_cli_pair.py`, `test_cli_relay_fallback.py`, `test_setup.py`, `test_storage_keychain.py`) all used the literal profile name `"test-p"` while defining disconnected `InMemoryKeyring` classes with local `self.passwords` dicts:
1. `kin/cli.py` invoked `keyring.set_keyring(InMemoryTestKeyring())` when `KIN_UNSAFE_TEST_KEYRING=1` was active.
2. `InMemoryTestKeyring` reads/writes the shared file at `/tmp/kin_insecure_test_keyring.json`.
3. Keys saved in earlier test fixtures were either overwritten or leaked across test boundaries, causing `SecretNotFoundError` or wrong key decryption errors when later tests executed.

---

## 3. Files Modified and One-Line Rationales

1. [tests/conftest.py](file:///d:/KIN/kin-node/tests/conftest.py): Added autouse fixture `isolate_test_keyring` to set `KIN_TEST_KEYRING_PATH` to a unique `tmp_path / "test_keyring.json"` per test function.
2. [kin/transport/v11.py](file:///d:/KIN/kin-node/kin/transport/v11.py): Validated `1 <= max_turns <= 12` in `dispatch_session`, passed `max_turns` inside signed envelope payload, and extracted `payload["max_turns"]` into `sessions.turn_limit` and `SessionState.max_turns` in `ingest_envelope`.
3. [tests/test_keyring_isolation.py](file:///d:/KIN/kin-node/tests/test_keyring_isolation.py): [NEW] Added regression test verifying cross-test keyring isolation across process/fixture boundaries.
4. [tests/test_v11_transport_m3.py](file:///d:/KIN/kin-node/tests/test_v11_transport_m3.py): Added regression tests for `dispatch_session` custom `max_turns` persistence, enforcement down to 4 turns, and rejection of `max_turns > 12`.
5. [tests/test_cli_ask.py](file:///d:/KIN/kin-node/tests/test_cli_ask.py): Updated `mock_keyring` fixture to use `InMemoryTestKeyring` backed by `KIN_TEST_KEYRING_PATH`.
6. [tests/test_cli_pair.py](file:///d:/KIN/kin-node/tests/test_cli_pair.py): Updated `mock_keyring` fixture to use `InMemoryTestKeyring` backed by `KIN_TEST_KEYRING_PATH`.
7. [tests/test_cli_relay_fallback.py](file:///d:/KIN/kin-node/tests/test_cli_relay_fallback.py): Updated `mock_keyring` fixture to use `InMemoryTestKeyring` backed by `KIN_TEST_KEYRING_PATH`.
8. [tests/test_setup.py](file:///d:/KIN/kin-node/tests/test_setup.py): Updated `mock_keyring` fixture to use `InMemoryTestKeyring` backed by `KIN_TEST_KEYRING_PATH`.
9. [tests/test_storage_keychain.py](file:///d:/KIN/kin-node/tests/test_storage_keychain.py): Updated `mock_keyring` fixture to use `InMemoryTestKeyring` backed by `KIN_TEST_KEYRING_PATH`.
10. [KNOWN_LIMITATIONS.md](file:///d:/KIN/kin-node/KNOWN_LIMITATIONS.md): Added Section 11 documenting Phase 0 baseline integrity defect fixes without altering prior entries.

---

## 4. Three Consecutive Full Test Suite Runs (Raw Output)

Command for all three runs:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"
py -3.11 -m pytest -q
```

### Run 1:
```text
[2026-07-25 23:37:42,343] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
........................................................................ [ 25%]
........................................................................ [ 50%]
........................................................................ [ 76%]
....................................................................     [100%]
============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
284 passed, 1 deselected, 1 warning in 21.99s
```

### Run 2:
```text
[2026-07-25 23:38:15,488] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
........................................................................ [ 25%]
........................................................................ [ 50%]
........................................................................ [ 76%]
....................................................................     [100%]
============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
284 passed, 1 deselected, 1 warning in 21.86s
```

### Run 3:
```text
[2026-07-25 23:38:50,499] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
........................................................................ [ 25%]
........................................................................ [ 50%]
........................................................................ [ 76%]
....................................................................     [100%]
============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
284 passed, 1 deselected, 1 warning in 21.83s
```

---

## 5. New Regression Tests Run Individually (-v)

### Test A: `tests/test_keyring_isolation.py`
Command:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"; py -3.11 -m pytest tests/test_keyring_isolation.py -v
```
Raw Output:
```text
[2026-07-25 23:34:41,701] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_keyring_isolation.py::test_isolation_part1 PASSED             [ 50%]
tests/test_keyring_isolation.py::test_isolation_part2 PASSED             [100%]

============================== 2 passed in 0.12s ==============================
```

### Test B: `tests/test_v11_transport_m3.py` (New max_turns tests)
Command:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"; py -3.11 -m pytest tests/test_v11_transport_m3.py -k "test_dispatch_session_custom_max_turns_isolation_and_enforcement or test_dispatch_session_invalid_max_turns_rejected" -v
```
Raw Output:
```text
[2026-07-25 23:37:25,156] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 33 items / 31 deselected / 2 selected

tests/test_v11_transport_m3.py::test_dispatch_session_custom_max_turns_isolation_and_enforcement PASSED [ 50%]
tests/test_v11_transport_m3.py::test_dispatch_session_invalid_max_turns_rejected PASSED [100%]

====================== 2 passed, 31 deselected in 0.25s =======================
```

---

## 6. Unmodified Reducer Invariant Test Confirmation

Command:
```powershell
$env:KIN_UNSAFE_TEST_KEYRING="1"; py -3.11 -m pytest tests/test_session_reducer.py::test_max_turns_cannot_be_increased_by_events_or_commands -v
```
Raw Output:
```text
[2026-07-25 23:37:32,853] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.0, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/test_session_reducer.py::test_max_turns_cannot_be_increased_by_events_or_commands PASSED [100%]

============================== 1 passed in 0.05s ==============================
```

---

## 7. Known Limitations / Open Questions

1. **Phase Scope Boundaries**: Work on artifact vaults, approval objects, CLI, or TUI features remains strictly deferred to Phase 1+ per instructions.
2. **Production Credential Store**: `KIN_UNSAFE_TEST_KEYRING=1` remains strictly a test-harness mechanism. Production backend allowlist enforcement in `_assert_secure_backend()` is completely untouched.
