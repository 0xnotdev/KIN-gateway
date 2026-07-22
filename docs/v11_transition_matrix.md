# KIN V1.1 Session State Transition Matrix

**Status:** Authoritative V1.1 State Machine Specification  
**Module:** `kin.session.transition_matrix`

---

## 1. Session Lifecycle States

| State | Character | Resumable / Terminal |
| :--- | :--- | :--- |
| `draft` | Local uncommitted session proposal | Non-terminal |
| `sent` | Outbound request transmitted by node | Non-terminal |
| `queued` | Enqueued safely at relay | Non-terminal |
| `delivered` | Processing acknowledgment received from peer | Non-terminal |
| `peer_review` | Peer owner inspecting session request | Non-terminal |
| `needs_clarification` | Peer owner requesting scope clarification | Non-terminal |
| `accepted` | Peer owner confirmed agent selection & scope | Non-terminal |
| `active` | Active agent collaboration session | Non-terminal |
| `awaiting_owner_approval` | Session paused waiting for local owner approval decision | Resumable |
| `awaiting_peer` | Session paused waiting for peer agent/owner turn | Resumable |
| `paused` | Explicit human-initiated pause | Resumable |
| `completed` | Successfully concluded collaboration | **Terminal** |
| `failed` | Terminated due to error or policy block | **Terminal** |
| `cancelled` | Terminated by explicit human cancellation | **Terminal** |
| `expired` | Terminated due to TTL or approval timeout | **Terminal** |
| `declined` | Peer owner declined session invitation | **Terminal** |

---

## 2. Permitted Transition Matrix

$$\begin{array}{rcl}
\text{draft} &\longrightarrow& \{\text{sent}, \text{cancelled}, \text{expired}\} \\
\text{sent} &\longrightarrow& \{\text{queued}, \text{delivered}, \text{failed}, \text{expired}\} \\
\text{queued} &\longrightarrow& \{\text{delivered}, \text{failed}, \text{expired}\} \\
\text{delivered} &\longrightarrow& \{\text{peer\_review}, \text{failed}, \text{expired}\} \\
\text{peer\_review} &\longrightarrow& \{\text{accepted}, \text{declined}, \text{needs\_clarification}, \text{cancelled}, \text{expired}\} \\
\text{needs\_clarification} &\longrightarrow& \{\text{peer\_review}, \text{cancelled}, \text{failed}, \text{expired}\} \\
\text{accepted} &\longrightarrow& \{\text{active}, \text{cancelled}, \text{expired}\} \\
\text{active} &\longrightarrow& \{\text{awaiting\_owner\_approval}, \text{awaiting\_peer}, \text{paused}, \text{completed}, \text{failed}, \text{cancelled}, \text{expired}\} \\
\text{awaiting\_owner\_approval} &\longrightarrow& \{\text{active}, \text{paused}, \text{failed}, \text{cancelled}, \text{expired}\} \\
\text{awaiting\_peer} &\longrightarrow& \{\text{active}, \text{paused}, \text{failed}, \text{cancelled}, \text{expired}\} \\
\text{paused} &\longrightarrow& \{\text{active}, \text{cancelled}, \text{failed}, \text{expired}\} \\
\text{completed, failed, cancelled, expired, declined} &\longrightarrow& \varnothing \quad (\text{Immutable Terminal States})
\end{array}$$
