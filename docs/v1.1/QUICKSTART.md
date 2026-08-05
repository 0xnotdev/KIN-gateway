# KIN V1.1 quick start
On each computer, install KIN and use a distinct profile and username:

```powershell
kin --profile alice doctor --plain
kin --profile alice tui
```

First Flight creates or restores the local identity and connects a local agent
card. Provider credentials stay in the OS keychain. Start the local node in a
second terminal:

```powershell
kin --profile alice serve --tunnel
```

If `cloudflared` is unavailable, use a public HTTPS endpoint you operate:
`kin --profile alice serve --host 0.0.0.0 --public-endpoint https://...`.

Pair by username and compare every fingerprint word over a separate trusted
channel. Do not accept screenshots or fingerprint text sent through the same KIN
connection being paired.

Use `d` in the TUI for Dispatch, select both agents explicitly, review Context
Pantry items, and confirm. The receiver accepts from Inbox. Consequential actions
appear only on the executing owner's computer. Export from the Session Arena with
Ctrl+E. For automation use `--json`; for constrained terminals use `--plain`.
