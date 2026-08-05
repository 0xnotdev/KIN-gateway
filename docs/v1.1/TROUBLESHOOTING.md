# Troubleshooting
Start with `kin --profile NAME doctor --plain`. It checks package/profile,
keychain, identity, relay/directory, node/tunnel, cards, provider credentials,
Inbox, and migration/recovery state without printing secrets.

- **`kin` is not found:** open a new terminal after installation or run
  `%LOCALAPPDATA%\KIN\bin\kin.cmd`.
- **Keychain failure:** use a normal signed-in Windows desktop session and verify
  Windows Credential Manager is available. Never set `KIN_UNSAFE_TEST_KEYRING`
  outside isolated tests.
- **Relay offline:** keep the node running or retry `kin fetch`; queued state must
  remain visible and safe. Do not resend by creating duplicate raw envelopes.
- **Tunnel unavailable:** install `cloudflared` yourself or provide a managed HTTPS
  endpoint. KIN never silently installs it.
- **Migration required:** run the documented dry-run and migration. Do not modify
  the database.
- **Small/plain terminal:** use an 80x24-or-larger terminal or the `--plain`/`--json`
  CLI equivalents. Recoverable failures should render a next action, not traceback.

Before reporting an incident, redact usernames if sensitive, absolute paths,
tokens, keys, recovery words, private notes, and session content.
