"""Summarize a pytest JUnit XML to a small JSON.

This is meant to avoid committing or diffing multi-megabyte JUnit files.

Usage:
  python tools/junit_summary.py --input evidence/test-results.xml
  python tools/junit_summary.py --input evidence/test-results.xml --output evidence/summary.json

The output is JSON and never includes test stdout/stderr bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def summarize(path: Path):
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    root = ET.fromstring(raw)

    def parse_int(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    if root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
        totals = {
            "tests": sum(parse_int(s.attrib.get("tests")) for s in suites),
            "failures": sum(parse_int(s.attrib.get("failures")) for s in suites),
            "errors": sum(parse_int(s.attrib.get("errors")) for s in suites),
            "skipped": sum(parse_int(s.attrib.get("skipped")) for s in suites),
        }
        timestamp = suites[0].attrib.get("timestamp") if suites else None
        duration = sum(float(s.attrib.get("time", 0.0) or 0.0) for s in suites)
    elif root.tag == "testsuite":
        totals = {
            "tests": parse_int(root.attrib.get("tests")),
            "failures": parse_int(root.attrib.get("failures")),
            "errors": parse_int(root.attrib.get("errors")),
            "skipped": parse_int(root.attrib.get("skipped")),
        }
        timestamp = root.attrib.get("timestamp")
        duration = float(root.attrib.get("time", 0.0) or 0.0)
    else:
        raise ValueError(f"Unsupported JUnit root tag: {root.tag}")

    return {
        "file": path.as_posix(),
        "bytes": len(raw),
        "sha256": sha256,
        "timestamp": timestamp,
        "duration_seconds": round(duration, 3),
        **totals,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summary = summarize(args.input)
    payload = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
