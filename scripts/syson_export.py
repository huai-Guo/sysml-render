#!/usr/bin/env python3
"""Download a SysON document as textual SysML v2 for round-trip tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--editing-context-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    endpoint = (
        f"{args.url.rstrip('/')}/api/editingcontexts/"
        f"{args.editing_context_id}/documents/{args.document_id}"
    )
    headers = {"Accept": "text/html"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    try:
        response = requests.get(endpoint, headers=headers, timeout=120)
    except requests.RequestException as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if response.status_code != 200:
        print(
            f"FAIL: HTTP {response.status_code}: {response.text[:2000]}",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(response.content)
    print(f"PASS: exported textual SysML -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
