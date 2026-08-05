# Release artifacts

The release owner runs `scripts/build_release.ps1` only from a clean, signed
`v1.1.0` tag. The script builds both wheels and source archives and rewrites
`SHA256SUMS`. Upload the generated files to the matching GitHub release without
renaming them. Generated archives are intentionally ignored. The signed tag is
the source authority; the matching GitHub release must contain every generated
artifact, `requirements-windows.lock`, and the generated `SHA256SUMS` asset. The
installer verifies both the wheel and lock, then applies the lock as pip
constraints. It fetches all three from the same immutable versioned release.
