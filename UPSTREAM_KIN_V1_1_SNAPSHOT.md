# Upstream KIN V1.1 Source Provenance

## Immutable source

- Source repository: `https://github.com/0xnotdev/kinto.git`
- Source branch at import: `main`
- Source commit: `58258fb037ea49f23d8e572ad7cd9df59ef5e388`
- Source commit date: `2026-08-05T18:42:03+05:30`
- Source commit subject: `Merge pull request #5 from 0xnotdev/codex/v11-final-release-readiness`
- Git tree: `808d495e70f7d03ac75f2ecaff50b29280fed494`
- Deterministic `git archive --format=tar` SHA-256: `6e6ffd95429df919c0e99f2951235588b76ff51df42248b427f144acbadb699a`
- Local immutable reference clone: `D:\KIN Gateway\original\kinto-main`
- Gateway import tag: `kin-v1.1-import`

## Preservation rule

The upstream/original KIN V1.1 repository is immutable. All gateway changes occur only in this repository after the `kin-v1.1-import` tag. The tag points at the exact upstream source commit above.

The earlier research document recorded SHA-256 `f2c58a556d3f1c98ff5c79ac2b4489c4ef08c262d915ad52b240bc7088c331aa` for an uploaded archive. That archive was not supplied during this Git import, so the value is retained as historical research metadata and is not presented as the checksum of the GitHub source imported here.

## Verification commands

```powershell
git rev-parse kin-v1.1-import
git rev-parse 'kin-v1.1-import^{tree}'
git diff --exit-code kin-v1.1-import -- . ':!UPSTREAM_KIN_V1_1_SNAPSHOT.md' ':!scope.md' ':!docs/planning'
```

To reproduce the archive checksum, create a tar archive from the import tag and hash the resulting bytes:

```powershell
git archive --format=tar --output=kin-v1.1-import.tar kin-v1.1-import
Get-FileHash -Algorithm SHA256 -LiteralPath kin-v1.1-import.tar
```
