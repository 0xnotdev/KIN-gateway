# Security and incident reporting
Do not open a public issue containing credentials, recovery phrases, private
notes, raw profile databases, relay ciphertext, unredacted transcripts, or local
paths. Use GitHub's private **Report a vulnerability** flow for this repository.
Include the KIN version, affected command/surface, minimal redacted reproduction,
expected boundary, and observed boundary.

If compromise is suspected: stop `kin serve`, disconnect any tunnel, preserve a
copy of the affected profile for analysis, rotate provider credentials in the
provider and OS keychain, notify paired contacts out of band, and do not trust
new traffic until fingerprints are reverified. A recovery phrase restores the
same identity; it does not rotate a compromised one.

Supported security fixes target the latest V1.1 patch release. Critical/high
unmitigated findings block release. The relay is treated as untrusted storage and
must never receive plaintext session content.
