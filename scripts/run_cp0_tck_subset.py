"""Execute exactly the supported node IDs from the pinned CP0 TCK manifest."""

from __future__ import annotations

import argparse
import json
import subprocess

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "tests/contract/tck-manifest.yaml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tck-path", type=Path, required=True)
    parser.add_argument("--tck-python", type=Path, required=True)
    parser.add_argument("--sut-host", default="http://127.0.0.1:18080")
    parser.add_argument("--report-directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report_directory = args.report_directory.resolve()
    report_directory.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.tck_python.resolve()),
        "-m",
        "pytest",
        *manifest["supported"],
        f"--sut-host={args.sut_host}",
        "--transport=jsonrpc,http_json",
        "-v",
        "--tb=short",
        f"--compatibility-report={report_directory / 'compatibility'}",
        f"--html={report_directory / 'tck_report.html'}",
        "--self-contained-html",
        f"--junitxml={report_directory / 'junitreport.xml'}",
    ]
    completed = subprocess.run(
        command,
        cwd=args.tck_path.resolve(),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
