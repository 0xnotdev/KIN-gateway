# V1 to V1.1 migration
Back up the profile first. Then run:

```powershell
kin --profile NAME migrate --dry-run --json
kin --profile NAME migrate --json
kin --profile NAME doctor --plain
```

Migration copies the database to staging, applies additive migrations, verifies
integrity, and atomically replaces the active database only after success. On
failure, the original profile remains usable and a redacted failure report is
written. Identity/keychain references, contacts, V1 tasks, and queued relay
messages are retained. Never edit migration tables or protocol payloads by hand.

Keep the pre-upgrade backup until pairing, task history, queued delivery, and one
deterministic export have been checked on the new release.
