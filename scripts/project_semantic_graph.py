#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from projection import PROFILES, ProjectionEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project a normalized SysML semantic snapshot into Diagram IR."
    )
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--root", required=True)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    ir = ProjectionEngine(snapshot).project(args.root, args.profile)
    payload = json.dumps(ir.to_dict(), ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
