#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig
from layout import SimpleHierarchicalLayout
from projection import ProjectionEngine
from render_projection_html import render_html
from selection import SemanticSelector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a live SysON semantic model into an editable HTML preview."
    )
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--commit-id")
    parser.add_argument("--token")
    parser.add_argument(
        "--select",
        help="Semantic element id, name, or qualifiedName. If omitted, auto-select a single root.",
    )
    parser.add_argument(
        "--root",
        help="Deprecated alias for --select.",
    )
    parser.add_argument(
        "--profile",
        help="Projection profile override. Otherwise inferred from semantic kind.",
    )
    parser.add_argument("--output", type=Path, required=True)
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
    selector = SemanticSelector(snapshot)
    selection = selector.resolve(
        args.select or args.root,
        profile=args.profile,
    )
    ir = ProjectionEngine(snapshot).project(
        selection.element_id,
        selection.profile,
    )
    layout = SimpleHierarchicalLayout().layout(ir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(ir, layout), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
