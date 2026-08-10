"""Verify exhaustive accounting for the pinned A2A TCK collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from collections import Counter
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "tests/contract/tck-manifest.yaml"


def load_manifest(path: Path) -> dict[str, Any]:
    """Load the JSON-compatible YAML manifest without another dependency."""

    return json.loads(path.read_text(encoding="utf-8"))


def collect_nodeids(tck_path: Path, tck_python: Path) -> list[str]:
    """Collect the pinned suite in its native pytest environment."""

    result = subprocess.run(
        [
            str(tck_python),
            "-m",
            "pytest",
            "tests/compatibility",
            "--collect-only",
            "-q",
        ],
        cwd=tck_path,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"TCK collection failed:\n{result.stdout}\n{result.stderr}")
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("tests/")
    ]


def classify_nodeids(
    nodeids: list[str],
    manifest: dict[str, Any],
) -> list[dict[str, str]]:
    """Map every immutable case to pass, unsupported, or tracked defect."""

    supported = set(manifest["supported"])
    if len(supported) != len(manifest["supported"]):
        raise ValueError("Supported TCK node IDs must be unique")
    missing_supported = sorted(supported.difference(nodeids))
    if missing_supported:
        raise ValueError(f"Supported TCK node IDs are missing: {missing_supported}")

    rule_counts: Counter[str] = Counter()
    accounting: list[dict[str, str]] = []
    for nodeid in nodeids:
        if nodeid in supported:
            accounting.append(
                {
                    "nodeid": nodeid,
                    "disposition": "pass",
                    "rule": "SUPPORTED",
                    "reason": "Selected CP0 compatibility case.",
                }
            )
            continue

        matched = None
        for rule in manifest["exclusion_rules"]:
            if any(needle in nodeid for needle in rule["contains_any"]):
                matched = rule
                break
        if matched is None:
            raise ValueError(f"Unaccounted TCK node ID: {nodeid}")
        rule_counts[matched["id"]] += 1
        accounting.append(
            {
                "nodeid": nodeid,
                "disposition": matched["disposition"],
                "rule": matched["id"],
                "reason": matched["reason"],
            }
        )

    for rule in manifest["exclusion_rules"]:
        actual = rule_counts[rule["id"]]
        if actual != rule["expected_count"]:
            raise ValueError(
                f"Rule {rule['id']} expected {rule['expected_count']} cases, "
                f"found {actual}"
            )
    return accounting


def junit_statuses(path: Path, expected_count: int) -> list[str]:
    """Read statuses in collection order from a pytest JUnit report."""

    cases = list(ET.parse(path).getroot().iter("testcase"))
    if len(cases) != expected_count:
        raise ValueError(
            f"JUnit contains {len(cases)} cases; expected {expected_count}"
        )
    statuses: list[str] = []
    for case in cases:
        status = "passed"
        for candidate in ("failure", "error", "skipped"):
            if case.find(candidate) is not None:
                status = candidate
                break
        statuses.append(status)
    return statuses


def verify(
    *,
    manifest_path: Path,
    tck_path: Path,
    tck_python: Path,
    junit_report: Path | None,
    accounting_output: Path | None,
) -> None:
    manifest = load_manifest(manifest_path)
    commit = subprocess.run(
        ["git", "-C", str(tck_path), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    if commit != manifest["tck_commit"]:
        raise ValueError(
            f"TCK commit is {commit}; expected {manifest['tck_commit']}"
        )

    nodeids = collect_nodeids(tck_path, tck_python)
    collection_bytes = ("\n".join(nodeids) + "\n").encode("utf-8")
    collection_hash = hashlib.sha256(collection_bytes).hexdigest()
    if len(nodeids) != manifest["collection_count"]:
        raise ValueError(
            f"Collected {len(nodeids)} cases; expected "
            f"{manifest['collection_count']}"
        )
    if collection_hash != manifest["collection_sha256"]:
        raise ValueError(
            f"Collection hash is {collection_hash}; expected "
            f"{manifest['collection_sha256']}"
        )

    accounting = classify_nodeids(nodeids, manifest)
    if junit_report is not None:
        statuses = junit_statuses(junit_report, len(nodeids))
        for row, status in zip(accounting, statuses, strict=True):
            row["observed_status"] = status
            if row["disposition"] == "pass" and status != "passed":
                raise ValueError(
                    f"Supported case was not green: {row['nodeid']} ({status})"
                )

    if accounting_output is not None:
        accounting_output.parent.mkdir(parents=True, exist_ok=True)
        accounting_output.write_text(
            json.dumps(
                {
                    "tck_commit": commit,
                    "collection_sha256": collection_hash,
                    "cases": accounting,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    totals = Counter(row["disposition"] for row in accounting)
    print(
        "TCK manifest verified: "
        f"{len(nodeids)} collected, "
        f"{totals['pass']} supported, "
        f"{totals['expected-unsupported']} expected-unsupported, "
        f"{totals['tracked-defect']} tracked-defect"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tck-path", type=Path, required=True)
    parser.add_argument("--tck-python", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--junit-report", type=Path)
    parser.add_argument("--accounting-output", type=Path)
    args = parser.parse_args()
    try:
        verify(
            manifest_path=args.manifest.resolve(),
            tck_path=args.tck_path.resolve(),
            tck_python=args.tck_python.resolve(),
            junit_report=(
                args.junit_report.resolve() if args.junit_report else None
            ),
            accounting_output=(
                args.accounting_output.resolve()
                if args.accounting_output
                else None
            ),
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"TCK manifest verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
