# KIN Relay

The KIN relay provides two deliberately small services for V1.1:

- a permanent username directory containing only public keys and current endpoints;
- a seven-day store-and-forward mailbox for opaque, end-to-end-encrypted blobs.

It cannot decrypt task content. Mail is retained until it expires or the authenticated recipient acknowledges successful local processing.

## Run locally

```powershell
python -m pip install -e ".[dev]"
uvicorn kin_relay.app:app --host 0.0.0.0 --port 8000
```

Point nodes at it with:

```powershell
$env:KIN_RELAY_URL = "https://your-relay.example"
```

For a pilot deployment, run the same command behind an HTTPS reverse proxy or a platform that terminates TLS. Persist the working directory's `relay.db` on durable storage; deleting that file destroys the public directory and any queued offline messages.

## Operational properties

- A username is permanently bound to its first Ed25519 public key; later registrations can update only its endpoint and X25519 public key when the Ed25519 key still matches.
- Relay inbox reads require a fresh signature from the recipient. Acknowledgements additionally sign the exact list of message IDs being removed.
- Expired mail is cleaned on inbox access. Valid mail is not deleted merely because it was fetched.

Install only the exact V1.1 release artifact from the matching signed source tag.
Operational deployment, retention, backup, TLS, and incident guidance lives in
`../docs/v1.1/RELAY-OPERATOR.md`. Run `pytest -q` before deploying changes.
