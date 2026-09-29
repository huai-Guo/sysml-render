#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from adapters.syson.importer import SysONImporter
from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig
from layout import SimpleHierarchicalLayout
from projection import ProjectionEngine
from render_projection_html import render_html
from selection import SemanticSelector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import textual SysML into SysON and automatically render a "
            "semantic editable HTML view."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--file",
        type=Path,
        help="Path to a textual SysML v2 file.",
    )
    source.add_argument(
        "--text",
        help="Literal SysML v2 textual content.",
    )
    source.add_argument(
        "--stdin",
        action="store_true",
        help="Read SysML v2 textual content from stdin.",
    )

    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument(
        "--project-id",
        help="Import into an existing SysON project. Omit to create one.",
    )
    parser.add_argument("--project-name")
    parser.add_argument("--token")
    parser.add_argument(
        "--select",
        help="Root element id, name, or qualifiedName. Defaults to a single root.",
    )
    parser.add_argument(
        "--profile",
        help="Projection profile override; otherwise inferred automatically.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_text(args: argparse.Namespace) -> tuple[str, str]:
    if args.file:
        return args.file.read_text(encoding="utf-8"), args.file.name
    if args.text is not None:
        return args.text, "inline.sysml"
    return sys.stdin.read(), "stdin.sysml"


def main() -> int:
    args = parse_args()
    text, filename = load_text(args)

    project_name = args.project_name
    if not project_name:
        stem = Path(filename).stem or "model"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        project_name = f"sysml-render-{stem}-{stamp}"

    importer = SysONImporter(
        args.url,
        token=args.token,
    )
    imported = importer.import_text(
        text,
        filename=filename,
        project_id=args.project_id,
        project_name=project_name,
    )

    adapter = SysONRestAdapter(
        SysONRestConfig(
            base_url=args.url,
            project_id=imported.project_id,
            token=args.token,
        )
    )
    snapshot = adapter.snapshot()

    selection = SemanticSelector(snapshot).resolve(
        args.select,
        profile=args.profile,
    )
    ir = ProjectionEngine(snapshot).project(
        selection.element_id,
        selection.profile,
    )
    layout = SimpleHierarchicalLayout().layout(ir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(ir, layout), encoding="utf-8")

    print(f"projectId={imported.project_id}")
    print(f"editingContextId={imported.editing_context_id}")
    print(f"documentId={imported.document_id}")
    print(f"root={selection.element_id}")
    print(f"profile={selection.profile}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
