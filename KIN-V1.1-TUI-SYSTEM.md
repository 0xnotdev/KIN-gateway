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

