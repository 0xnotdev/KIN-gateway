# KIN V1.1 Terminal UI System

**Status:** Authoritative interface implementation contract

**Companion to:** `KIN-V1.1-MASTER-SPEC.md`

**Scope:** The terminal workspace only — its layout, widgets, keyboard behavior, streaming, themes, motion, accessibility, persistence, and rendering quality.

**Out of scope:** Agent protocol, relay transport, identity, policy decisions, and business logic. Those are defined in the V1.1 master specification. This document defines how their state is made legible and pleasurable to use.

---

## 1. Design mandate

KIN must feel like a premium native terminal workspace: calm, dense, keyboard-fluent, alive while work is happening, and trustworthy under pressure. It takes inspiration from the *quality bar* of modern AI terminals — stable panes, space/tab context, live work streams, restrained color, and a command-first workflow — but does not copy another product’s screen layout or visual identity.

The visual metaphor is **the Arena inside a personal operations room**:

- the persistent left rail is the owner’s world: spaces, agents, trusted network, and attention;
- the tab bar is the work currently open in the owner’s mind;
- the center is the selected collaboration or tool;
- the right inspector answers “what matters now?” without burying the user in logs;
- the footer always reports health, connection, and the next available action.

### 1.1 Non-negotiable UI principles

1. **Stable geography.** Important information lives in predictable places. Updates never reorder the user’s current focus unexpectedly.
2. **Keyboard before mouse, mouse never hostile.** Every interaction is complete from the keyboard; mouse resize/click support is additive.
3. **Progressive disclosure.** A calm overview becomes detail only when opened. No permanent wall of logs.
4. **Human attention is scarce.** The UI distinguishes `working`, `waiting`, `needs you`, and `failed`; only the latter two earn attention.
5. **Evidence over theatre.** Stream verified events, activity labels, outputs, and provenance. Never fabricate “thinking” or display private chain-of-thought.
6. **Fast even when busy.** Live sessions and streams update without cursor jumps, scroll resets, visual tearing, or input lag.
7. **Beautiful in normal terminals.** The baseline is 16-color-safe, readable text. True-color themes enhance it; they never carry meaning alone.

---

## 2. Implementation baseline

### 2.1 Technology choice

KIN V1.1 uses **Textual** for the full-screen interactive TUI and **Rich** for non-interactive command output, exported views, installers, and fallback terminals. The two share a small design-token package and component formatting primitives.

- The full-screen app uses the terminal alternate screen and restores the original screen on exit/crash.
- A non-TTY, `--plain`, or unsupported terminal runs the same command through Rich/plain output; no essential action is TUI-only.
- UI state is driven by typed node/session events. Widgets render state; they never make network or agent decisions directly.
- Long-running work runs in background workers. The main event loop remains responsive at all times.

### 2.2 Rendering rules

- Never print directly to stdout while the TUI owns the terminal. Route all changes through the event store and renderer.
- Batch high-frequency updates into at most one visual commit per frame. Target 30 FPS; degrade to 10 FPS before dropping keyboard responsiveness.
- Coalesce duplicate activity events (for example repeated “waiting for model”) into one row with elapsed time.
- Preserve user scroll position. A timeline only auto-follows while the user is at the latest event; otherwise show `↓ 12 new events`.
- Retain at least 10,000 structured in-memory timeline events per open workspace; older details remain in the local database and can be paged in.

---

## 3. Geometry, breakpoints, and layout engine

### 3.1 Application shell

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ WorkspaceTabBar                                                           │
├───────────────┬──────────────────────────────────────────────┬───────────┤
│ Sidebar       │ Active workspace                              │ Inspector │
│ persistent    │ dashboard / dispatch / session / agents       │ contextual│
├───────────────┴──────────────────────────────────────────────┴───────────┤
│ StatusBar + command hint + transport / keychain / relay health            │
└──────────────────────────────────────────────────────────────────────────┘
```

The shell has five persistent regions: **workspace tab bar**, **sidebar**, **main canvas**, optional **inspector**, and **status bar**. Each region has a stable widget ID so layout/state restoration is reliable.

### 3.2 Terminal breakpoints

| Terminal size | Layout | Rules |
|---|---|---|
| ≥160 × 44 | Wide | Sidebar + main + inspector; full dashboard and three-pane Arena |
| 120–159 × 36 | Standard | Sidebar + main; inspector docks beneath or opens with `i` |
| 90–119 × 28 | Compact | Collapsed sidebar icon rail; inspector is a modal/drawer; tables reduce columns |
| <90 columns or <28 rows | Minimal | Full-screen single-pane views, command palette, stacked cards; show resize hint once |

KIN must work at 80×24. It may not claim premium wide-screen density there, but it must remain complete and coherent.

### 3.3 Resizing and docking

- Sidebar default width: 32 columns; minimum 24; maximum 42.
- Inspector default width: 38 columns; minimum 30; maximum 52.
- Users resize with mouse drag when supported, or keyboard: `Alt+[` / `Alt+]` sidebar, `Alt+{` / `Alt+}` inspector, in two-column increments.
- `[` toggles/collapses sidebar; `]` toggles inspector. Collapsed rails retain icons, unread/approval count, and current selection marker.
- Pane dimensions, collapsed state, active theme, and last focused widget persist per profile in `ui-state.json` (no secrets, no session content).
- A dock may never cover the command input, status bar, or an active approval. On compact layouts it becomes a drawer rather than overlapping content.

### 3.4 Layout persistence

Persist only user interface preference:

```json
{
  "schema_version": 1,
  "theme": "kin-graphite",
  "sidebar_width": 32,
  "inspector_width": 38,
  "sidebar_collapsed": false,
  "inspector_visible": true,
  "focus_mode_default": false,
  "workspace_tabs": ["home", "session:abc"],
  "active_tab": "session:abc"
}
```

Persisted layout must survive an upgrade that can understand its schema, but a malformed file resets only UI preference and never blocks KIN startup.

---

## 4. Workspace manager and tabs

### 4.1 Workspace definition

A **workspace** is a local UI context, not a network object. It has its own focus, scroll positions, filters, inspector selection, and optional draft input. It does not create a new KIN identity or duplicate a session.

Workspace types:

| Type | Example | Tab behavior |
|---|---|---|
| Home | `Home` | Always available; cannot close |
| Session | `Budget pipeline` | Opens on dispatch/open; may pin/close/reopen |
| Dispatch | `New collaboration` | One reusable draft tab; warns before discarding unsent edits |
| Agents | `Agents` | Singleton tab |
| Network | `Network` | Singleton tab |
| Inbox | `Needs you (3)` | Singleton tab, badge updates in place |
| Search / command result | `Search: CSV` | Ephemeral; closeable |

### 4.2 Tab bar

```text
 KIN / alice    Home   Budget pipeline ●   Design review !   +
```

- The left label identifies the current profile, not a folder or Git branch.
- Tabs use short user-facing names, a compact state glyph, and an optional unread/approval marker.
- Active tab: violet underline/background plus high-contrast text.
- Live tab: mint dot. Needs-you tab: amber `!`. Error/security issue: red dot, never color-only.
- `Ctrl+Tab` / `Ctrl+Shift+Tab` cycle tabs; `Alt+1…9` jumps by visible position; `Ctrl+W` closes; `Ctrl+Shift+T` reopens last closed non-sensitive tab.
- `+` opens the workspace launcher; it is not a blank terminal.
- Tabs remain in stable order. Receiving an event never jumps a session to the front or steals active focus.

### 4.3 Sidebar

The sidebar is a scrollable but stable navigation tree. Its selection is independent of the main workspace until activated.

```text
SPACES                                               +
› Home
  Inbox                                      3
  Recent sessions

AGENTS                                              manage
  ● Code Scout                              ready
  ◌ Planner                                  working
  ! Finance Guard                    needs approval

NETWORK                                             trusted
  ● Bob                                  3 agents
  ○ Priya                                offline

NEEDS YOU                                            2
  ! Review Bob’s session request
  ! Export approval expires in 04:12
```

- Section headers are collapsible with `Enter`/`Space`; their collapsed state persists.
- `j/k` and arrow keys traverse items; `h/l` collapses/expands; `Enter` opens; `Space` previews in inspector; `/` filters the current tree.
- Selection remains sticky when rows update. If a selected row disappears, selection moves to its nearest sibling and shows a one-line status message.
- The sidebar never auto-scrolls to a new notification. Counts update in place.
- Focused row uses a subtle violet fill; current open workspace uses a persistent left marker; live state uses glyph + label, not blinking text.

---

## 5. Keyboard grammar

Keyboard behavior must be predictable enough that users learn it as a language.

### 5.1 Global bindings

| Key | Action |
|---|---|
| `Ctrl+K` | Command Palette — actions, navigation, settings, recent work |
| `Ctrl+P` | Quick Switcher — open workspaces, recent sessions, agents, contacts |
| `d` | Dispatch, unless text input is focused |
| `a` / `n` / `i` / `p` | Agents / Network / Inbox / Approvals |
| `?` | Contextual help overlay |
| `/` | Filter/search current visible collection |
| `Esc` | Clear search → close drawer/modal → return focus to main, in that order |
| `Tab` / `Shift+Tab` | Next / previous focusable widget |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous workspace tab |
| `Alt+1…9` | Jump to visible workspace tab |
| `Ctrl+W` | Close current closeable workspace |
| `Ctrl+S` | Save current local draft/note where meaningful |
| `q` | Quit only from Home; otherwise return Home after confirmation if work is active |

### 5.2 Collection and timeline bindings

| Key | Action |
|---|---|
| `j/k` or arrows | Move selection |
| `g/G` | First / last item |
| `Enter` | Open/activate selection |
| `Space` | Preview selection in inspector |
| `o` | Open in new workspace tab |
| `r` | Replay selected/current session |
| `f` | Fork current session locally |
| `.` | Open actions for current item |
| `x` | Context-safe cancel/archive action, always confirms when consequential |

### 5.3 Session Arena bindings

| Key | Action |
|---|---|
| `z` | Focus / Cockpit mode |
| `t` | Transcript lane |
| `e` | Events/activity lane |
| `o` | Outputs/artifacts lane |
| `c` | Checkpoints and decisions lane |
| `u` | Needs-you / approval lane |
| `m` | Compose a human message or clarification |
| `s` | Session state menu: pause, resume, cancel, hand back |
| `r` | Replay timeline |
| `i` | Toggle inspector |

No single-key action may execute a consequential approval, artifact import, session cancellation, or workspace write. Those always open a review surface with an explicit confirmation binding.

### 5.4 Command Palette

`Ctrl+K` opens a centered, searchable palette:

```text
┌ Command Palette ──────────────────────────────────────────────────────┐
│ > dispatch                                                             │
│                                                                         │
│   Dispatch a collaboration                                      d      │
│   Open session: Budget pipeline                                recent  │
│   Search agents                                                       │
│   Open Needs you                                              2 items  │
│   Change theme: KIN Graphite                                            │
│   Run doctor                                                           │
└────────────────────────────────────────────────────────────────────────┘
```

- Results are ranked by exact command, recent action, contextual relevance, then fuzzy match.
- Palette supports action arguments but does not expose destructive shell execution.
- `:` opens the command-line flavor of the palette for advanced users (`:open abc`, `:theme nord`).
- `Ctrl+P` is intentionally different: it switches/open existing things rather than invoking an operation.

---

## 6. Component library

Every production screen uses these reusable widgets. A widget specification includes input state, output events, keyboard behavior, and visual states. Screens compose widgets; they do not invent one-off patterns.

### 6.1 Foundation components

| Widget | Inputs | Outputs | Required states |
|---|---|---|---|
| `Panel` | title, body, emphasis, actions | focus/action | normal, focused, collapsed, empty, error |
| `Badge` | semantic status/count | none | neutral, live, waiting, approval, error, muted |
| `StatusLine` | icon, label, detail, timestamp | optional open | healthy, warning, error, stale |
| `Spinner` | task label, elapsed, cancellable | cancel request | indeterminate, delayed, failed, complete |
| `ProgressBar` | value/total or phase | none | active, paused, complete, error |
| `Toast` | severity, message, action | action/dismiss | info, success, warning, error, security |
| `Modal` | title, body, primary/secondary actions | decision | initial, validation error, submitting, complete |
| `EmptyState` | icon, explanation, one next action | action | no-data, no-search-result, unavailable |

### 6.2 Navigation and data components

| Widget | Inputs | Outputs | Required behavior |
|---|---|---|---|
| `WorkspaceTabBar` | workspace list, active tab | select/open/close/reorder | stable order, overflow menu, readable badges |
| `SidebarTree` | grouped nav nodes | select/open/preview/collapse | sticky selection, virtualized rows, filter mode |
| `CommandPalette` | command index, recents, context | run/open | keyboard-only, fuzzy search, no focus theft |
| `DataTable` | rows, columns, sort/filter config | select/sort/filter | column reduction on narrow terminals, accessible row labels |
| `Timeline` | ordered event stream | select/open/replay | scroll-lock, new-event pill, grouping, pagination |
| `Inspector` | selected entity | open related/action | contextual only, never required for core completion |
| `SearchField` | query, scope | update/submit/clear | debounced, clear escape behavior, match count |

### 6.3 KIN domain components

| Widget | Inputs | Outputs | Required visual contract |
|---|---|---|---|
| `AgentCard` | local/published card, availability | select/details/configure | capability chips, boundary summary, readiness, no secret leakage |
| `AgentPicker` | eligible agents, suggestion rationale | select/back | arrow/fuzzy navigation, details drawer, explicit selection |
| `DispatchWizard` | peer/cards/task draft/context pantry | save/send/cancel | numbered progress, review before send, resumable draft |
| `SessionMap` | participants, session state | participant select | neutral topology, roles, handoff markers, no “winner” visual |
| `ExchangeTimeline` | verified messages/events | select/quote | sender/agent/provenance, event grouping, new-event indicator |
| `ActivityFeed` | observable activities | select/details | concise verbs, elapsed time, coalescing, no fake thought stream |
| `ArtifactList` | offered/received artifacts | preview/export/import | MIME/size/hash/provenance, review before external import |
| `ApprovalCard` | request, scope, expiry, diff/artifact | approve/deny/edit | risk label, owner-only decision, expiry, explicit primary action |
| `OutcomeCard` | result, decisions, artifacts, duration | open/export/rerun/playbook | calm terminal state, next meaningful action |
| `TrustStrip` | pairing/card/transport/artifact state | explain trust | semantic glyphs + text, security state prominent |

### 6.4 Widget life-cycle rules

Every widget must explicitly implement:

1. loading/skeleton state;
2. empty state with one useful next action;
3. normal state;
4. keyboard focus state;
5. permission/disabled state with reason;
6. recoverable error state with retry/details;
7. narrow-terminal presentation.

No widget may expose a blank panel, raw exception, or spinner without an elapsed-time label and a path to cancel/back out where cancellation is safe.

---

## 7. Session Arena rendering specification

### 7.1 Wide layout

```text
┌ Budget pipeline · Alice/Code Scout ↔ Bob/Data Cleaner · LIVE ─────────┐
│ Working · round 3/12 · encrypted direct · 02:14        [Pause] [?]    │
├────────────────┬─────────────────────────────────┬────────────────────┤
│ SESSION MAP    │ VERIFIED EXCHANGE               │ INSPECTOR          │
│ Alice          │ 10:41 Code Scout                │ Activity           │
│ Code Scout     │ └ needs normalized dates        │ ✓ Parsed headers   │
│       ↕        │                                 │ ◌ Transforming CSV │
│ Bob            │ 10:42 Data Cleaner              │                    │
│ Data Cleaner   │ └ can return clean CSV + schema │ Artifacts          │
│                │                                 │ clean.csv  offered │
│ Checkpoints 1  │ 10:43 checkpoint                │                    │
├────────────────┴─────────────────────────────────┴────────────────────┤
│ [T] Transcript [E] Activity [O] Outputs [C] Decisions  z Focus  m Msg │
└────────────────────────────────────────────────────────────────────────┘
```

The center lane is authoritative: verified exchange and structured state. The side lanes provide orientation and detail. A user can complete all approvals/actions from a compact layout; wide layout is enhancement, not a requirement.

### 7.2 Event presentation

| Event class | Presentation |
|---|---|
| Peer/agent message | timestamp, person/agent, message kind, concise body, signature/provenance on inspect |
| Activity | muted single-line verb + elapsed time; group repeats |
| Checkpoint | bordered summary block; pin/decision controls |
| Artifact | compact offer card, hash/size/type, preview/import actions |
| Approval | amber card inserted into timeline and Needs-you queue |
| State transition | thin divider with icon and clear language |
| Security event | red high-priority card; no auto-dismiss |

Messages never masquerade as internal thought. A legitimate agent-generated rationale is labelled `Agent rationale` and distinguished from an execution event.

### 7.3 Streaming behavior

- New activity appears at the tail with a 120 ms highlight pulse, then settles into normal color.
- Streaming text renders as incremental chunks inside a bounded event card. It wraps naturally and never shifts an already focused input field.
- A completed stream replaces its cursor/spinner with a duration and a stable event ID.
- If an adapter sends more than 30 updates/second, KIN batches visual changes but preserves all structured events in storage.
- When off-tail, show a fixed `↓ N new events` control. Selecting it returns to tail; it never auto-scrolls the reader.
- Disconnect/reconnect inserts one state event rather than replaying duplicate activity.

---

## 8. Theme system and visual tokens

### 8.1 Semantic token model

Themes use semantic roles, never hard-coded widget colors:

```text
surface.base       surface.raised       surface.selected
text.primary       text.secondary       text.muted       text.inverse
border.subtle      border.focus         border.strong
state.live         state.waiting        state.approval   state.error
accent.primary     accent.secondary     accent.highlight
diff.add           diff.remove          diff.context
```

Status semantics must remain distinguishable in monochrome through glyphs, labels, and border treatment.

### 8.2 Built-in themes

| Theme | Character |
|---|---|
| `kin-graphite` (default) | graphite/indigo surfaces, mint live state, violet focus |
| `kin-night` | deeper blue-black, cyan activity, amber approvals |
| `nord` | cool low-saturation accessibility-friendly palette |
| `dracula` | familiar high-contrast purple/cyan palette |
| `catppuccin-mocha` | warm muted dark palette |
| `high-contrast` | maximum contrast, no low-contrast borders, color-independent states |

Themes are selectable through Settings, Command Palette, and `:theme <name>`. User overrides use a validated token-only YAML file; arbitrary custom CSS is not a supported V1.1 surface.

### 8.3 Typography, spacing, and borders

- Font: terminal’s configured monospace; never assume a specific proprietary font.
- Use bold sparingly: active title, primary value, destructive/security label only.
- Base spacing unit: one terminal cell. Panels use one-cell inner padding; dense tables use zero horizontal padding only when labels remain readable.
- Borders: subtle single-line box borders for normal panels; stronger/violet focus border; amber approval border; red security border. Avoid nested boxes deeper than two levels.
- Align timestamps/numbers in fixed columns; truncate from the middle for IDs and paths; never truncate a user’s primary task title without offering full view.

---

## 9. Motion and micro-interactions

Terminal motion must communicate state, not perform decoration. It is implemented using textual frame changes, color transitions, and layout interpolation where supported — not web-style opacity effects.

| Interaction | Behavior | Duration / rate |
|---|---|---|
| Focus change | border/selection moves with a short color settle | 80–120 ms |
| New live event | one highlight pulse then normal state | 120 ms |
| Section expand/collapse | rows reveal/conceal in 2–4 frame steps when terminal permits | 120–180 ms |
| Modal/drawer | immediate input focus plus short border/position settle | ≤120 ms |
| Spinner | low-motion braille/dot frame sequence with elapsed label | 8–12 FPS |
| Progress | monotonic bar updates; no bouncing fake progress | event-driven |
| Toast | enters at status edge, remains until read/timeout, exits quietly | 3–6 s default |
| Attention pulse | amber badge pulse at most twice, then static count | 2 pulses |

### 9.1 Reduced motion

`reduce_motion` is automatically enabled when terminal/environment accessibility settings expose it and can be toggled in Settings. Reduced mode removes interpolation/pulses, uses instant state changes, and preserves all labels/glyphs.

### 9.2 No-jank rules

- No widget may reflow the whole app for an ordinary status update.
- Animations pause when the terminal is unfocused/suspended or CPU pressure is detected.
- Do not animate more than one large region at a time.
- A user keystroke always wins over an animation frame.

---

## 10. Notifications, errors, and status bar

### 10.1 Notification hierarchy

| Level | Examples | Behavior |
|---|---|---|
| Security | signature failure, identity mismatch | persistent red card + Needs-you; never auto-dismiss |
| Action required | peer acceptance, local write approval | persistent amber queue item; optional toast |
| Important state | session completed, relay queue delivered | toast + timeline; no focus theft |
| Informational | agent ready, theme changed | short quiet toast or status line |
| Debug | verbose adapter event | inspector/log only when debug enabled |

### 10.2 Status bar

```text
 Ready  • relay online  • node reachable  • 2 trusted peers  • ^K commands  • ? help
```

The status bar is always one row. It uses compact health glyphs and one current contextual hint. It never scrolls marquee text. A degraded dependency says what failed and offers `Enter` for details.

### 10.3 Errors

Expected operational errors are shown as recoverable cards: what happened, impact, what KIN preserved, next action, optional technical details. Raw traceback is written to local diagnostics and available through `kin doctor --details`; it never takes over a normal user’s TUI.

---

## 11. Accessibility and terminal resilience

- Full keyboard completion for every primary flow; focus order is visible and logical.
- High-contrast theme and reduced-motion mode are first-class.
- No state relies on red/green alone; glyph + wording are mandatory.
- Screen-reader-oriented plain mode outputs ordered semantic headings/events, not box-art noise.
- Long labels wrap or open full detail; no essential information appears only in hover tooltips.
- Mouse use is optional. Unsupported mouse reports no error.
- On minimal terminals, KIN uses stacked views with a visible back breadcrumb and preserves draft input.
- Unicode symbols have ASCII fallbacks: `●` → `*`, `✓` → `OK`, `!` remains `!`, arrows become `->`.

---

## 12. UI quality gates

V1.1 UI is not done when screens merely render. It is done when the following evidence is green:

### 12.1 Automated

- Textual screenshot/snapshot tests for every primary screen in wide, standard, compact, and minimal breakpoints.
- Keyboard-flow tests for First Flight, Dispatch, agent selection, session approval, Session Arena, replay, and recovery.
- Theme snapshots for default, high-contrast, and 16-color fallback.
- Event-stream tests proving no scroll reset, focus theft, duplicate timeline row, or blocking render under burst traffic.
- Component tests for every widget state: loading, empty, normal, focused, disabled, recoverable error, narrow layout.
- Accessibility tests for glyph/text equivalence and global keyboard binding conflicts.

### 12.2 Human acceptance

1. A new user can discover their next action from Home without a tutorial video.
2. A user can dispatch a task and select both agents without typing an opaque ID.
3. During a live session, a spectator can answer: who is involved, what they are doing, what has been decided, what is waiting, and whether action is needed — in under 15 seconds.
4. An approval can be understood and denied safely without reading developer logs.
5. A user can return after a day, open Replay/Outcome Card, and understand the collaboration without trusting an LLM-generated summary.
6. The UI remains calm with multiple live sessions; no incoming event interrupts typing or changes selected context.

---

## 13. Definition of done

The KIN terminal UI system is complete when every V1.1 feature feels like it belongs to one deliberate workspace: panes are stable and persist, tabs carry context, keyboard actions follow one grammar, widgets have complete empty/loading/error/accessibility states, streaming work feels natural without leaking reasoning, and the user always knows what is happening and what — if anything — needs them.

---

## 14. Detailed terminal UI build execution plan

This section is the executable implementation and verification plan for the terminal contract. It is built against typed node-event fixtures first, then against the real node boundary.

### 14.1 Delivery rules and test harness

- **Ownership boundary:** the TUI renders immutable view models and dispatches explicit node commands. It cannot decrypt transport, select an agent automatically, evaluate policy, make an approval decision, or write a workspace directly.
- **State boundary:** define typed UiState with profile health, workspaces, navigation selection, node snapshots, overlays, toasts, and per-workspace focus/scroll state. Reducers accept only typed local events and command outcomes. Rendering code does not mutate domain state.
- **Command boundary:** every consequential operation opens a review surface, then calls one named node command after explicit confirmation. The command result and audit/event ID are authoritative. Disable confirmation while it is in flight; retries are idempotent.
- **Fixture boundary:** provide a demo/test node client emitting the same snapshots, results, errors, and event bursts as the real node. Fixtures include empty data, Alice/Bob sessions, stale card, queued relay, invalid signature, active approval, artifact preview, long labels, and a 10,000-event history.
- **Snapshot matrix:** each production screen has deterministic Textual snapshots at 160x44, 120x36, 90x28, and 80x24, in kin-graphite, high-contrast, and 16-color/ASCII modes. Freeze clock, animation state, IDs, and ordering.
- **Interaction matrix:** use Textual pilot tests for focus, bindings, confirmation, resize, tabs, drawers, modals, search, scrolling, and event arrival while an input is focused. Every widget is tested in all seven lifecycle states in section 6.4.
- **Checkpoint evidence:** each checkpoint requires green focused and regression suites, reviewed snapshots, keyboard-only smoke steps, and an explicit deferred-surface list. A wide-screen happy-path render is not sufficient.

### 14.2 Milestone T0 - Skeleton, tokens, and deterministic test infrastructure

**Goal:** establish a reliable application foundation before product screens are added.

**Build steps**

1. Add the Textual application entry point for interactive kin; retain Rich/plain output for non-TTY, --plain, and unsupported terminals. Use alternate screen only interactively and restore the original terminal on normal exit, exception, and interrupt.
2. Create the shared token package: section 8.1 semantic roles, typography helpers, border variants, glyph registry, ASCII fallbacks, and theme validation. Widgets use token names, never literal colors.
3. Define typed UI view models for health, tabs, sidebar items, session summaries, events, artifacts, approvals, agent cards, command results, and recoverable errors. Add fixture factories for every state.
4. Add deterministic snapshot, keyboard-pilot, and frame-timing helpers. Tests wait for an explicit settled state rather than arbitrary sleep; failures capture screen, focused widget, overlay state, and event log.
5. Add a global error boundary that converts expected node/UI failure into a recoverable card and writes technical details to diagnostics. A raw traceback may never occupy the normal TUI.

**Required tests**

- TTY detection and alternate-screen restoration on quit, exception, and Ctrl+C.
- Token validation rejects missing roles and arbitrary widget colors; all required roles resolve under default, high-contrast, and 16-color fixtures.
- Snapshot harness is deterministic across two runs; fixture serialization round-trips; error-boundary snapshot is readable.
- Plain-output smoke proves help, navigation, and doctor results are usable without box drawing or Unicode.

**Checkpoint T0 - stop/handoff:** kin launches a blank styled shell and exits cleanly; it can be snapshotted at every required size. No workflow is exposed yet.

### 14.3 Milestone T1 - Stable shell, responsive geometry, and preference persistence

**Goal:** make terminal geometry a supported input and preserve the five stable regions.

**Build steps**

1. Implement stable-ID WorkspaceTabBar, Sidebar, MainCanvas, optional Inspector, and one-row StatusBar. They remain in place while workspace content changes.
2. Implement exact breakpoints: wide at >=160x44; standard at 120-159x36; compact at 90-119x28; minimal below 90 columns or 28 rows. At compact the sidebar becomes an icon rail and the inspector becomes a drawer. At minimal render a single-pane stack with visible breadcrumb/back action. Completion is required at 80x24.
3. Implement sidebar default/minimum/maximum widths of 32/24/42 and inspector widths of 38/30/52. Bind Alt+[ / Alt+] and Alt+{ / Alt+} in two-column increments; bind [ / ] to collapse/toggle. A dock may not cover input, an active approval, or the status row.
4. Implement atomic, validated ui-state.json read/write for section 3.4 fields plus sidebar-section collapse state. A malformed or unsupported preference file resets only UI preferences and emits one quiet status message.
5. Implement status health slots and one contextual hint. Health updates change in place and never scroll, steal focus, move the cursor, or reflow unrelated content.

**Required tests**

- Golden snapshots at all four breakpoints for normal/collapsed sidebar, visible/hidden inspector, long profile name, and degraded relay/keychain health.
- Keyboard/mouse-capable resize tests at every min/max boundary, during terminal shrink, and while an approval or input is active.
- Persistence tests for valid state, malformed JSON, unknown schema, missing file, out-of-range values, and a compatible upgrade.
- Inject 100 health updates and assert unchanged focus, cursor, scroll position, and selected row.

**Checkpoint T1 - stop/handoff:** shell geography is stable from 80x24 through wide screens, preferences persist safely, and asynchronous health cannot disrupt a user.

### 14.4 Milestone T2 - Workspaces, keyboard grammar, and command surfaces

**Goal:** make all navigation predictable before building detailed content.

**Build steps**

1. Implement section 4.1 workspace rules: non-closeable Home; singleton Agents, Network, and Inbox; one reusable Dispatch draft with discard warning; closeable Session/Search tabs; stable ordering; reopen last closed non-sensitive tab; and + workspace launcher.
2. Implement the sidebar tree with independent preview selection, stable row identity, collapse persistence, slash filter, j/k, arrows, h/l, Enter, and Space. A disappearing selection moves to its nearest sibling with a one-line status message.
3. Register and centrally validate every binding in sections 5.1-5.3. Bindings are inactive while a text field owns the key where specified. Duplicate/conflicting global binding is a startup and test failure.
4. Implement Esc priority exactly: clear search, close drawer/modal, then return focus to main. All cancel/archive/state/approval/import/write actions open review and explicit confirmation.
5. Implement distinct Ctrl+K Command Palette and Ctrl+P Quick Switcher. Palette ranking is exact command, recent action, contextual relevance, then fuzzy match; support reviewed arguments and colon commands but never arbitrary shell execution.
6. Generate contextual help from the binding registry so help cannot list a missing or conflicting action.

**Required tests**

- Keyboard flows for tab cycling/jumping/closing/reopening, singleton rules, dirty Dispatch warning, tree filtering/preview/open, and disappearing row selection.
- One test for each global/Arena binding, including text-input focus and each Esc stage.
- Palette/switcher ranking golden tests, no-result state, keyboard-only selection, open/theme argument parsing, and rejection/absence of shell-like arbitrary execution.
- Tests proving no single key executes approval, artifact import, workspace write, cancellation, or destructive action.

**Checkpoint T2 - stop/handoff:** a keyboard-only user can open, switch, preview, search, close, and recover workspace contexts without raw IDs or focus theft.

### 14.5 Milestone T3 - Reusable widgets and complete lifecycle states

**Goal:** ensure every screen is composed from consistent, testable components.

**Build steps**

1. Implement foundation widgets: Panel, Badge, StatusLine, Spinner, ProgressBar, Toast, Modal, and EmptyState. They receive semantic inputs and emit actions; they do not own business state.
2. Implement WorkspaceTabBar, SidebarTree, CommandPalette, DataTable, Timeline, Inspector, and SearchField, including debounced search, match count, accessible labels, narrow table columns, virtualized/paged collections, and scroll lock.
3. Implement domain widgets: AgentCard, AgentPicker, DispatchWizard, SessionMap, ExchangeTimeline, ActivityFeed, ArtifactList, ApprovalCard, OutcomeCard, and TrustStrip.
4. Give every widget explicit loading/elapsed label, empty next action, normal, focused, disabled-with-reason, recoverable error/retry, and narrow presentation. A spinner has a safe cancel/back path where cancellation is possible.
5. Add one presentation-safety layer: redact prohibited values; label agent rationale; distinguish message/activity/transition/approval/artifact/security; never render raw prompts, chain-of-thought, secrets, or unapproved file content.

**Required tests**

- Parameterized tests for all seven lifecycle states at all breakpoints and required themes.
- Widget event/focus/disabled/retry/cancel/filter/pagination/overflow tests; every truncated essential label has a full-detail path.
- Semantic-label snapshots for status/approval/security glyphs in default, high-contrast, monochrome, and ASCII.
- Seed fake keys, hidden prompts, reasoning, and local paths; assert none is displayed in widgets, inspector, toast, action labels, or diagnostics summary.

**Checkpoint T3 - stop/handoff:** screens can be assembled entirely from reusable widgets; no blank panel, raw exception, unlabelled status, or hard-coded color remains.

### 14.6 Milestone T4 - First Flight, Home, Agents, Network, and Needs You

**Goal:** give a new owner a clear next action and safe operational overview.

**Build steps**

1. Build resumable First Flight: create/restore identity, connect agent, start/check node/relay, and pair trusted person. Include optional two-profile demo and guided dispatch. Persist progress only; do not persist secrets or session content in UI state.
2. Build Home with agent roster, live/recent sessions, network summary, Needs You queue, and status line. Counters update in place; an event never prints over input or opens a workspace.
3. Build Agents: create/import/inspect/enable/disable/configure local cards, readiness explanation, boundary summary, capability chips, and safe peer-card preview. Do not render secrets, raw adapter configuration, or private paths in peer contexts.
4. Build Network: contacts, pairing/fingerprint/trust, reachability, peer-card freshness, change-review trigger, and no public-discovery affordance.
5. Build Inbox/Needs You and Approval queue. Group by session/urgency; only acceptance, agent selection, clarification, approval, and outcome review are persistent attention. Quiet informational state becomes toast/status.
6. Build searchable kin guide short paths with one relevant next key/command per page for both TUI and plain output.

**Required tests**

- First Flight from empty profile, every resume point, failed keychain/relay/agent step, demo, skip, and return behavior.
- Home snapshots for empty/healthy/live/queued/approval/security, 100 sessions/20 agents, long labels, and all sizes.
- Agent/Network separation tests for safe local versus peer cards, readiness reason, stale-card review, unpaired state, and keyboard entry from Home.
- Needs You quiet-hour/snooze/grouping tests; security/expiring approval cannot vanish; incoming events do not interrupt focused draft input.
- Manual five-second discovery smoke: a new user can identify the next action from Home without a tutorial.

**Checkpoint T4 - stop/handoff:** a user can create/restore, connect an agent, assess health/attention, inspect safe peer capabilities, and enter Dispatch using only keyboard controls.

### 14.7 Milestone T5 - Dispatch, agent picker, Context Pantry, and review-before-send

**Goal:** make the collaboration contract legible before data leaves the machine.

**Build steps**

1. Implement the exact seven-step wizard: peer, owner agent, peer agent, collaboration type, goal, inputs, review. Saving a draft creates no send effect.
2. Implement AgentPicker as a modal overlay with arrows/j/k, fuzzy search, details drawer, select/back, availability, requirements, capabilities, boundaries, MIME types, and one-sentence Suggested-not-automatic rationale.
3. Validate non-empty outcome goal, selected agents, compatible types, explicit budget/turn limits, and fresh peer card before send. Use master session-type choices only.
4. Render Context Pantry as typed inventory: message, pasted text, approved artifact, local reference. Show size, classification, expiry, peer-sharing disposition, and reviewed local-reference output; never promise peer path browsing.
5. Make final review the outgoing manifest: selected local agent, peer, requested peer agent, goal, mode, budgets/constraints, all inputs/attachments, and exact state Packaging -> Signing -> Encrypting -> Delivered or Queued safely at relay.
6. A failed command retains the complete draft, says what was preserved, and offers retry/back/edit. Never show delivered before valid node acknowledgement.

**Required tests**

- Keyboard happy path at all sizes; fuzzy picker, no eligible agent, busy/reserved/blocked agent, stale card, unsupported peer/version, and each validation failure.
- Draft save/reopen/discard; no send command before final confirmation; double-confirm/retry creates one idempotent request.
- Final-review snapshots show every outbound item, classification, size/expiry/budget, and no secret/raw local path.
- Real-node fixture tests for direct delivered, queued relay, peer decline, clarification, and receiver confirmation with correct focus retention.

**Checkpoint T5 - stop/handoff:** an owner can select both agents, inspect exactly what leaves their machine, send once, and see truthful direct/queued/review state without typing an opaque ID.

### 14.8 Milestone T6 - Session Arena, live streams, artifacts, and approvals

**Goal:** deliver the calm third-person Arena and controlled local action surfaces.

**Build steps**

1. Implement Arena header/trust strip, session map, authoritative exchange timeline, activity/output inspector, and all lane bindings. Use three-lane Cockpit wide, docked/on-demand inspector standard, and complete stacked lanes compact/minimal.
2. Render section 7.2 event classes exactly: provenance-rich message; concise coalesced activity; bordered checkpoint; artifact metadata/preview; amber approval; clear state divider; persistent red security card.
3. Follow tail only when already at tail. Otherwise retain reader position and show fixed down-N-new-events control. Tail pulse lasts 120 ms and is absent in reduced motion. A completed stream has stable event ID/duration.
4. Batch visual commits at no more than 30 FPS, degrading to 10 FPS under pressure, while retaining every structured event. Coalesce repeated activity only; never coalesce approval/security/state. Reconnect adds one transition and deduplicates replay.
5. Implement z, t/e/o/c/u/m/s/r/i behavior, Focus/Cockpit preference, replay, clarification, state menu, inspector, decisions/checkpoints, and output lane.
6. Implement node-authoritative approval/artifact review: local owner, scope, reason, risk, constraints, expiry, and consequences. Approve once, deny, edit, bounded always-allow, import, and patch apply all require confirmation and command-result feedback.

**Required tests**

- Arena snapshots for each lifecycle/event class, empty/failed/recovering, long content, missing peer, stale card, direct/relay, and all sizes.
- Keyboard flows for every Arena binding, Focus/Cockpit parity, lane navigation, replay, off-tail behavior, state menu, deny, and cancel/confirm.
- Inject 31 or more updates per second and 10,000 events; assert no more than 30 commits per second normally, preserved count/order, no duplicates, no scroll reset, and unchanged focused input/selection.
- Signature-failure tests prove persistent labelled red state and no unsafe action view. Prohibited reasoning/content never renders.
- Artifact/approval integration tests prove inspect does not import/apply/approve, and rejected/expired node decision becomes accurate recoverable UI state.

**Checkpoint T6 - stop/handoff:** within 15 seconds a spectator can identify participants, current work, decisions, action-required state, and output provenance. Live traffic cannot disrupt typing or hide approval/security events.

### 14.9 Milestone T7 - Theme, motion, accessibility, and terminal resilience

**Goal:** keep the product complete in constrained and accessible terminals.

**Build steps**

1. Implement six built-in themes and validated token-only YAML override. Expose Settings, palette, and theme command; invalid overrides retain last valid theme and show recoverable error.
2. Implement semantic glyph/text/border fallback so live/waiting/approval/error/muted/security are distinguishable without color or Unicode.
3. Implement motion limits: focus 80-120 ms; event pulse 120 ms; expand 120-180 ms; modal no more than 120 ms; spinner 8-12 FPS plus elapsed label; toast 3-6 seconds; maximum two amber pulses. Keystrokes always win and ordinary updates never reflow the whole application.
4. Implement automatic/manual reduced motion and pause animation under CPU pressure/unfocused terminal. Reduced motion changes instantly but retains labels.
5. Complete 80x24 and plain mode: breadcrumb/back, draft preservation, ordered semantic output, full review/approval/export access, long-label details, no hover-only content, no unsupported-mouse error.

**Required tests**

- Snapshot every primary screen in all built-in themes smoke, default/high contrast, 16-color, monochrome, and ASCII; assert semantic token resolution/contrast rules.
- Keyboard-only journey from First Flight through approval/export; plain-output ordering golden tests; every visual state has text equivalent.
- Reduced-motion test proves no pulse/interpolation is scheduled; normal-motion test enforces duration/rate limits and keypress priority.
- 80x24 suite for Home, Dispatch, picker, inbox, approval, Arena, replay, and recovery; terminal resize preserves draft/focus.

**Checkpoint T7 - stop/handoff:** no required task depends on width, true color, Unicode, mouse, or motion. The interface remains recognizably KIN and safe at every supported terminal capability.

### 14.10 Milestone T8 - Real-node integration, performance, and release gate

**Goal:** prove the full UI with real persistent node behavior and two-person acceptance.

**Build steps**

1. Replace fixture-only wiring with typed real node client while retaining fixtures for deterministic tests. Malformed/unavailable node events become recoverable cards and diagnostics, never renderer crashes.
2. Run two isolated profiles with relay fallback, persistent replay, card state, approval expiry, artifact metadata, restart/reconnect, and all P0 UI actions.
3. Profile startup, dashboard input latency, event batching, memory retention, and resize. Retain at least 10,000 structured events per open workspace; page older events without losing order/provenance.
4. Execute manual two-laptop UI acceptance: install, First Flight, pair, card review, Dispatch, peer acceptance, live Arena, local approval, artifact review, outcome/replay/export, interruption/restart, and terminal fallback.
5. Maintain a release ledger mapping every UI requirement to snapshots, interaction tests, node integration, and manual evidence. Focus theft, expected-failure traceback, reasoning exposure, unconfirmable consequential action, or missing primary-flow breakpoint blocks release.

**Required release evidence**

| Area | Required pass condition |
|---|---|
| Startup/performance | Dashboard interactive in under two seconds with 100 sessions and 20 agents; typing remains responsive during bursts. |
| Event correctness | 10,000 events, reconnect, duplicate delivery, off-tail scroll, pagination, and stable focus/selection pass. |
| Full journey | Keyboard-only Alice/Bob dispatch, acceptance, live session, approval, artifact review, outcome/replay/export pass against real node fixtures. |
| Failure recovery | Relay/node/keychain/adapter faults yield clear recoverable cards and plain output, never tracebacks. |
| Accessibility | High contrast, reduced motion, 16-color, ASCII, 80x24, and plain modes pass the primary journey. |
| Human acceptance | Users discover next action, select both agents without IDs, assess live session in 15 seconds, deny safely, and understand a day-old outcome. |

**Checkpoint T8 - release/no-release:** release only when every snapshot, component/keyboard test, real-node integration test, performance check, accessibility check, and two-laptop acceptance step is green. Visual quality never waives interaction, security, or resilience failures.

### 14.11 UI completion ledger

Maintain one completion record per screen/widget with: owning module; input view model; emitted commands/events; seven lifecycle test IDs; four breakpoint snapshots; default/high-contrast/ASCII snapshots; keyboard-flow IDs; accessibility assertion; real-node integration test; and manual observation when needed. This ledger, not a subjective visual review, determines whether the terminal workspace meets its definition of done.
