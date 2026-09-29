#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and normalize a SysON project through the SysML v2 REST API."
    )
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--commit-id")
    parser.add_argument("--token")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    adapter = SysONRestAdapter(
        SysONRestConfig(
            base_url=args.url,
            project_id=args.project_id,
            commit_id=args.commit_id,
            token=args.token,
        )
    )
    snapshot = adapter.snapshot()
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(args.output)
    else:
        print(payload, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
