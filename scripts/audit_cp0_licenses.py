"""Capture installed license metadata and enforce the CP0 project-license gate."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any


PROJECT_PACKAGES = ("kin-cli", "kin-gateway", "kin-relay")


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _distribution_record(distribution: metadata.Distribution) -> dict[str, Any]:
    package_metadata = distribution.metadata
    name = package_metadata.get("Name") or "UNKNOWN"
    project_urls = package_metadata.get_all("Project-URL") or []
    home_page = package_metadata.get("Home-page")
    if home_page:
        project_urls.append(f"Home-page, {home_page}")
    return {
        "name": name,
        "canonical_name": _canonical_name(name),
        "version": package_metadata.get("Version") or "UNKNOWN",
        "license_expression": package_metadata.get("License-Expression"),
        "legacy_license": package_metadata.get("License"),
        "license_classifiers": [
            value
            for value in package_metadata.get_all("Classifier") or []
            if value.startswith("License ::")
        ],
        "license_files": package_metadata.get_all("License-File") or [],
        "project_urls": project_urls,
    }


def build_audit() -> dict[str, Any]:
    distributions = sorted(
        (_distribution_record(item) for item in metadata.distributions()),
        key=lambda item: (item["canonical_name"], item["version"]),
    )
    by_name = {item["canonical_name"]: item for item in distributions}
    failures: list[str] = []
    project_metadata: dict[str, Any] = {}

    for name in PROJECT_PACKAGES:
        record = by_name.get(name)
        if record is None:
            failures.append(f"{name} is not installed")
            continue
        project_metadata[name] = record
        if record["license_expression"] != "Apache-2.0":
            failures.append(
                f"{name} License-Expression is "
                f"{record['license_expression']!r}, expected 'Apache-2.0'"
            )
        missing_files = {"LICENSE", "NOTICE"} - set(record["license_files"])
        if missing_files:
            failures.append(
                f"{name} metadata is missing license files: "
                + ", ".join(sorted(missing_files))
            )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interpreter": {
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "platform": platform.platform(),
        },
        "gate": {
            "status": "pass" if not failures else "fail",
            "requirements": {
                "project_license_expression": "Apache-2.0",
                "project_license_files": ["LICENSE", "NOTICE"],
            },
            "failures": failures,
        },
        "project_packages": project_metadata,
        "distributions": distributions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    audit = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"CP0 license audit {audit['gate']['status']}: "
        f"{len(audit['distributions'])} installed distributions; "
        f"evidence={args.output}"
    )
    for failure in audit["gate"]["failures"]:
        print(f"ERROR: {failure}", file=sys.stderr)
    return 0 if audit["gate"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
