# KIN V1.1 TUI — Milestone T4 Phase B Progress Report
**Issued by:** Antigravity (Execution Engine)  
**Spec Authority:** `KIN-V1.1-TUI-SYSTEM.md` §14.6 (build step 2)  
**Date:** 2026-07-30  

---

## 1. Real-vs-Fixture Data Boundary (§1 & §7)

As required by §14.6 Phase B, the data sources feeding `HomeScreenWidget` adhere strictly to the real-vs-fixture boundary:

### REAL Data Queries
1. **Agent Roster Preview**: Queries local YAML agent card registry via `kin.agent_registry.scan_local_cards()` through shared `kin.tui.local_state`.
2. **Network Summary**: Queries real SQLite `contacts` table in the profile database via `get_local_contacts_summaries()`.
3. **Status Line / Health**: Built dynamically via `query_health_snapshot()` using real local identity checks & relay reachability status (accepting HTTP 200, 204, and 404 directory probe responses as live routing proof).

### FIXTURE-ONLY Data
1. **Live & Recent Sessions**: Driven by `make_all_session_summary_fixtures()` until the real session engine integration in Milestone T5.
2. **Needs You Queue**: Driven by `make_all_approval_view_fixtures()` until the real approval engine integration in Milestone T6.

---

## 2. Shared Query Layer & View Model Justification

### Shared Query Layer (`kin/tui/local_state.py`)
- Extracted local identity, agent registry, SQLite contacts table, and relay reachability probe functions out of `FirstFlightController` into a centralized, reusable query layer (`kin/tui/local_state.py`).
- Both `FirstFlightController` and `HomeScreenWidget` import from `local_state.py`, preventing query duplication across Phase A, Phase B, Phase C (Agents), and Phase D (Network).

### New `ContactSummary` View Model (`kin/tui/state.py`)
- **Justification**: No view model existed for a paired contact (`AgentCardView` is strictly for agent cards and cannot represent peer contact endpoints/fingerprints).
- **Structure**: Following T0 conventions, `ContactSummary` is a plain dataclass with zero business logic:
  ```python
  @dataclass
  class ContactSummary:
      username: str
      display_name: str
      public_key: str
      x25519_public_key: str
      endpoint: str
      autonomy_level: str = "always_ask"
      fingerprint: Optional[str] = None
      verified_at: Optional[str] = None
  ```

---

## 3. Five-Second Discovery Smoke Test & Manual Judgment (§6)

> [!NOTE]
> **Manual Discoverability Affordance Judgment**:
> For a brand-new empty profile (zero connected agents and zero paired contacts), `HomeScreenWidget` renders a prominent, high-contrast `[Getting Started]` panel:
> 
> ```
> 🚀 FIRST FLIGHT ONBOARDING RECOMMENDED
> Welcome to KIN V1.1! Your profile is empty. To get started:
>  • Run First Flight wizard to initialize identity, connect agents & relay.
>  • Or press [Ctrl+P] / type /init in command bar.
> Next Action: Complete First Flight setup step to unlock agent dispatch.
> ```
> 
> **Why it satisfies the 5-second bar**: Within 5 seconds of opening an unconfigured profile, the user's eye is immediately drawn to the yellow border and bold onboarding prompt. The single clear "Next Action" affordance eliminates ambiguity on what step to perform next.

---

## 4. Canvas Tab Branching & Snapshot Updates (§0)

- `MainCanvas` in [kin/tui/shell.py](file:///d:/KIN/kin-node/kin/tui/shell.py) now branches dynamically on `active_tab_kind`:
  - `"home"` $\rightarrow$ mounts and renders `HomeScreenWidget`.
  - Non-home tabs (`"agents"`, `"network"`, `"inbox"`, `"session"`, `"dispatch"`, `"search"`) $\rightarrow$ renders clean `"[KIND] WORKSPACE — Screen arriving in Phase C/D/E/T5/T6"` placeholders.
- The temporary hardcoded fake-approval string from T1 was deleted entirely. All 10 app shell geometry snapshots were updated to match the new `HomeScreenWidget` default canvas rendering.

---

## 5. Files Modified List

### New Files
1. [local_state.py](file:///d:/KIN/kin-node/kin/tui/local_state.py) — Shared local state query module.
2. [home_screen.py](file:///d:/KIN/kin-node/kin/tui/widgets/home_screen.py) — Home Screen & Live Dashboard widget composing Roster, Network, Sessions, Approvals, and Status.
3. [test_home_screen.py](file:///d:/KIN/kin-node/tests/tui/test_home_screen.py) — 6 unit, snapshot, scale virtualization, long label, counter stress, and no-interrupt tests.
4. [tui_t4_phaseB_progress.md](file:///d:/KIN/kin-node/tui_t4_phaseB_progress.md) — Phase B progress report.

### Modified Files
5. [state.py](file:///d:/KIN/kin-node/kin/tui/state.py) — Added `ContactSummary` view model.
6. [shell.py](file:///d:/KIN/kin-node/kin/tui/shell.py) — Updated `MainCanvas` tab branching and mounted `HomeScreenWidget`.
7. [first_flight.py](file:///d:/KIN/kin-node/kin/tui/first_flight.py) — Refactored to use `local_state.py`.

---

## 6. Unabridged Raw Test Outputs

### Run 1: Home Screen Test Suite (`tests/tui/test_home_screen.py`)
`python -c "import subprocess; p = subprocess.run(['py', '-3.11', '-m', 'pytest', '-v', 'tests/tui/test_home_screen.py'], capture_output=True, text=True); open('t4b_fresh_verify.txt', 'w', encoding='utf-8').write(p.stdout + '\n' + p.stderr)"`

```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 6 items

tests/tui/test_home_screen.py::test_home_screen_empty_profile_state PASSED [ 16%]
tests/tui/test_home_screen.py::test_home_screen_healthy_with_agents_and_contacts PASSED [ 33%]
tests/tui/test_home_screen.py::test_home_screen_scale_virtualization_100_sessions_20_agents PASSED [ 50%]
tests/tui/test_home_screen.py::test_home_screen_long_labels PASSED       [ 66%]
tests/tui/test_home_screen.py::test_home_screen_counters_update_in_place_stress_test PASSED [ 83%]
tests/tui/test_home_screen.py::test_home_screen_no_interrupt_active_input PASSED [100%]

======================== 6 passed in 468.76s (0:07:48) ========================
```

### Run 2: Complete TUI Suite (`tests/tui/`)
`python -c "import subprocess; p = subprocess.run(['py', '-3.11', '-m', 'pytest', '-v', 'tests/tui/'], capture_output=True, text=True); open('tui_fresh_verify.txt', 'w', encoding='utf-8').write(p.stdout + '\n' + p.stderr)"`

```
======================= 848 passed in 745.25s (0:12:25) =======================
```

### Run 3: Full Combined Project Suite (`py -3.11 -m pytest -v`)
`python -c "import subprocess; p = subprocess.run(['py', '-3.11', '-m', 'pytest', '-v'], capture_output=True, text=True); open('combined_fresh_verify.txt', 'w', encoding='utf-8').write(p.stdout + '\n' + p.stderr)"`

```
========== 1194 passed, 1 deselected, 1 warning in 789.37s (0:13:09) ==========
```
