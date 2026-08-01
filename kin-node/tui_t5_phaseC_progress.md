# KIN V1.1 TUI — Milestone T5 Phase C Progress Report

**Issued by:** Antigravity (Execution Engine)  
**Spec Authority:** `KIN-V1.1-TUI-SYSTEM.md` §14.7 (build steps 1, 3, 4, 5, 6)  
**Date:** 2026-08-01  
**Retroactive:** Yes — this report was produced retroactively from a code audit.
Phase C was originally committed without a dedicated progress report.

---

## 1. Overview — Phase C: 7-Step Dispatch Wizard, Context Pantry, and Worker-Based Send

Phase C implements the core dispatch workflow specified in §14.7 build steps 1 and 3–6: the seven-step wizard
UI, Context Pantry data model, non-blocking worker-based send, and draft retention on failure.

### Initial Commit
- `9bbf795`: `feat(tui): implement 7-step Dispatch Wizard, off-main-thread worker, and real-node integration tests (§14.7 Phase C & D)`

### Rework Commit
- `d808d22`: `fix(tui): wire keyboard-driven peer/agent/mode selection into Dispatch Wizard (§14.7 Phase C Rework)`

> **Note:** The initial commit (`9bbf795`) contained the structural wizard and worker
> implementation but shipped with incomplete keyboard wiring and a hardcoded 3-type
> SessionType validation. The rework commit (`d808d22`) completed the keyboard
> interaction and corrected the validation. Both are detailed below as the combined
> Phase C deliverable.

---

## 2. Implementation Detail

### 2.1 DispatchWizardWidget ([dispatch_wizard.py](file:///d:/KIN/kin-node/kin/tui/widgets/dispatch_wizard.py), 634 lines)

Subclasses `LifecycleWidgetMixin` + `Widget`. Central `on_key(event)` handler routes to step-specific handlers.

**Seven-Step Flow:**

| Step | Purpose | Key Wiring | Backend Call |
|---|---|---|---|
| 0 — Peer Contact | Select paired contact | `Enter` → push `ContactPickerModal` | `controller.select_peer(username)` |
| 1 — Sender Agent | Select owner's local agent | `Enter` → push `AgentPickerWidget(is_peer=False)` | `controller.select_sender_agent(agent_id)` |
| 2 — Receiver Agent | Select peer's published agent | `Enter` → push `AgentPickerWidget(is_peer=True, peer_username=...)` | `controller.select_receiver_agent(agent_id)` |
| 3 — Collaboration Type | Choose session type | `j`/`k`/`up`/`down` cycle through `VALID_SESSION_TYPES` | `controller.set_session_type(type)` |
| 4 — Define Goal | Free-text objective entry | Printable character capture + backspace (buffer idiom from `search_field.py`) | `controller.set_goal(text)` |
| 5 — Context Pantry | Attach/remove input items | `a` add, `d`/`x` remove selected | `controller.add_pantry_item()` / `controller.remove_pantry_item()` |
| 6 — Review & Dispatch | Inspect outbound manifest, confirm send | `Enter` confirms → `confirm_dispatch()` | Worker-based `dispatch_new_session()` |

Step navigation: `right`/`n` forward, `left`/`p` backward.

**ContactPickerModal** (inner class): `ModalScreen[Optional[ContactSummary]]` — renders paired contacts with
`j`/`k` navigation, `Enter` to select, `Esc` to cancel.

**SessionType Validation:** `VALID_SESSION_TYPES = tuple(st.value for st in SessionType)` — imports directly
from `kin.schemas.SessionType` enum. All 6 master types are selectable: `ask`, `research`, `debate`,
`build_pipeline`, `review`, `delegate_subtask`.

### 2.2 DispatchController ([dispatch.py](file:///d:/KIN/kin-node/kin/tui/dispatch.py), 140 lines)

Pure state-machine controller (no Textual dependency in the controller itself).

**State Fields:**
- `current_step: int` (0–6), `peer_username`, `sender_agent_id`, `receiver_agent_id`
- `session_type: str` (default `"ask"`), `goal: str`, `max_turns: int` (default 12)
- `pantry_items: list[ContextPantryItem]`, `dirty: bool`
- `dispatch_error: Optional[RecoverableError]`, `dispatch_result: Optional[dict]`

**Key Methods:**

| Method | Purpose |
|---|---|
| `select_peer(username)` | Set peer, mark dirty |
| `select_sender_agent(agent_id)` | Set sender agent, mark dirty |
| `select_receiver_agent(agent_id)` | Set receiver agent, mark dirty |
| `set_session_type(session_type)` | Validate against VALID_SESSION_TYPES, set, mark dirty |
| `set_goal(goal)` | Set goal text, mark dirty |
| `add_pantry_item(item)` | Append ContextPantryItem, mark dirty |
| `remove_pantry_item(index)` | Remove by index, mark dirty |
| `validate_current_step()` | Returns `(is_valid, error_message)` for current step |
| `validate_all()` | Pre-dispatch validation of all required fields |
| `to_draft()` / `from_draft(draft)` | Serialize/restore to/from `DispatchDraft` dataclass |
| `reset()` | Clear all state to defaults |

### 2.3 Context Pantry Data Model ([state.py](file:///d:/KIN/kin-node/kin/tui/state.py))

**ContextPantryItem** dataclass:
- `kind: str` — item type (`"message"`, `"pasted_text"`, `"artifact"`, `"local_reference"`)
- `label: str` — display label
- `size_bytes: int` — content size
- `classification: str` — security classification
- `expiry: Optional[str]` — optional expiry timestamp
- `content: str` — actual content

**DispatchDraft** dataclass:
- All controller fields + `pantry_items: list[ContextPantryItem]`, `dirty: bool`, `current_step: int`

### 2.4 Review-Before-Send (Step 6)

`_render_step_6_review()` renders the **complete outbound manifest**:
- Selected peer contact
- Selected sender agent (ID + name)
- Selected receiver agent (ID + name)
- Collaboration type
- Full goal text
- Budget / turn limit (max_turns)
- All pantry items with kind, size, and classification

Nothing is hidden. The user sees exactly what leaves the machine before pressing Enter.

### 2.5 Worker-Based Send

`confirm_dispatch()` is decorated with `@work(thread=True)` — executes off the main Textual event loop:

1. Calls `controller.validate_all()` — blocks on failure
2. Calls `dispatch_new_session(profile_dir, profile_name, peer_username, sender_agent_id, receiver_agent_id, session_type, goal, max_turns, http_client)` in `local_state.py`
3. Backend validates peer exists in contacts, loads Ed25519 private key, calls `dispatch_session()` from transport layer
4. Returns result dict with `status` (`"delivered"` | `"queued"` | `"error"`), `session_id`, optional error
5. `_on_dispatch_result(result)` callback on main thread updates UI state

**Exception Handling:**
- `(NoActiveAppError, LookupError, RuntimeError)` — graceful fallback (app closed during send)
- Any other exception → widget transitions to `RECOVERABLE_ERROR` with "Dispatch Worker Error" headline
- **Draft state is preserved on all failure paths** — user can retry or edit without re-entering data

### 2.6 Draft Persistence

- `controller.to_draft()` serializes full controller state to `DispatchDraft`
- `controller.from_draft(draft)` restores complete state including step position and pantry items
- `controller.reset()` clears to defaults
- `dirty` flag tracks unsaved changes for discard-warning on workspace close
- Draft survives tab switches (controller is owned by `KinApp`, not the widget)

---

## 3. Test Coverage

### test_dispatch_wizard.py (6 tests):

| Test | Type | Verifies |
|---|---|---|
| `test_dispatch_wizard_7_steps_navigation` | Direct-call | Controller step progression 0→6, SessionType enum validation |
| `test_dispatch_wizard_context_pantry_operations` | Direct-call | Pantry item add/remove, M7 local reference notice |
| `test_dispatch_wizard_dirty_state_tracking` | Direct-call | Draft dirty flag correctly tracks mutations |
| `test_dispatch_wizard_non_blocking_worker_execution` | Direct-call | `@work` worker runs off main thread without blocking |
| `test_dispatch_wizard_keyboard_only_end_to_end_pilot_flow` | **Pilot-driven** | Full `pilot.press()` flow: Enter contact modal, right-arrow navigation, down-arrow mode cycling to RESEARCH, character typing "Audit security flaws", `a` pantry add, Enter dispatch confirm |
| `test_dispatch_wizard_invalid_key_preserves_session_type` | **Pilot-driven** | Pressing `z` on step 3 does not change session_type |

### test_dispatch_backend_wiring.py (3 tests):

| Test | Verifies |
|---|---|
| `test_dispatch_unverified_peer_rejected` | Unverified peer username → RecoverableError |
| `test_dispatch_stale_peer_card_rejected` | Stale card timestamp → RecoverableError |
| `test_dispatch_invalid_session_type_rejected` | Invalid session type → RecoverableError; Ed25519 key conversion verified |

### test_phaseE_node_fixture.py (5 tests):

| Test | Verifies |
|---|---|
| `test_phaseE_real_node_fixture_boots` | Real node fixture boots with profile/DB |
| `test_phaseE_real_dispatch_direct_happy_path` | Full dispatch through real node, direct transport, delivered state |
| `test_phaseE_real_dispatch_relay_queued` | Dispatch with relay fallback, queued state |
| `test_phaseE_real_dispatch_peer_decline` | Peer declines session, declined state in UI |
| `test_phaseE_real_dispatch_receiver_confirmation` | Receiver confirms agent selection, active state |

---

## 4. Known Gap Addressed in Rework

The initial Phase C commit (`9bbf795`) shipped with:
1. **Hardcoded 3-type SessionType validation** — `("ask", "delegate", "coordinate")` instead of the 6 enum values
2. **Incomplete keyboard wiring** — steps 0–2 didn't push modal screens on Enter; step 3 lacked j/k cycling; step 4 lacked character capture; step 5 lacked a/d/x bindings
3. **Overly broad exception handling** — `confirm_dispatch()` caught all exceptions equally
4. **No AgentPicker sort order** — READY agents were not sorted to top

The rework commit (`d808d22`) and the subsequent "Phase C Rework" report ([tui_t5_progress.md](file:///d:/KIN/kin-node/tui_t5_progress.md)) document the corrections. All four issues were resolved before merge to main.

---

## 5. Spec Coverage Summary (§14.7 Build Steps)

| Build Step | Status | Evidence |
|---|---|---|
| 1. Exact seven-step wizard | ✅ | Steps 0–6 implemented with step-specific renderers and key handlers |
| 3. Non-empty goal, selected agents, compatible types, fresh card, budget validation | ✅ | `validate_all()` + backend `dispatch_new_session()` checks |
| 4. Context Pantry as typed inventory | ✅ | `ContextPantryItem` with kind, size, classification, expiry |
| 5. Final review = outgoing manifest | ✅ | `_render_step_6_review()` shows all selections, pantry, budget |
| 6. Failed command retains draft, says what was preserved, offers retry | ✅ | RECOVERABLE_ERROR state with preserved controller, retry available |
