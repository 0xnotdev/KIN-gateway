# Relay operator guide
The relay is an untrusted directory and opaque mailbox, not an agent runtime.
Install the `kin-relay` wheel in its own environment and expose it only through
TLS:

```powershell
python -m venv .relay-venv
.\.relay-venv\Scripts\python -m pip install .\kin_relay-1.1.0-py3-none-any.whl
.\.relay-venv\Scripts\python -m uvicorn kin_relay.app:app --host 127.0.0.1 --port 8000
```

Put an authenticated administrative boundary and TLS reverse proxy in front of
the process. Back up `relay.db` with SQLite's online backup API or while the
process is stopped. Restrict filesystem access to the service account. Monitor
availability, disk growth, expiry sweeps, and repeated invalid requests without
logging request bodies or ciphertext. Never inspect, transform, or decrypt
mailbox payloads. Restore tests must prove pending envelopes and ACK deletion
semantics without duplicate delivery.
