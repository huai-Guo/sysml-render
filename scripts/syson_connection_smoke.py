#!/usr/bin/env python3
"""Live SysON connection round-trip smoke on a NEW disposable project only.

This script never writes to a caller-specified existing SysON project.
It leaves the test project for inspection and manual deletion.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "prototype"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from adapters.syson.importer import SysONImporter
from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig
from adapters.syson.textual_writer import SysONTextualWriter
from connection_editing import (
    compile_canvas_connection,
    connection_in_semantic_snapshot,
    connection_visible,
)
from projection import ProjectionEngine
from selection import SemanticSelector


def port_node_id(nodes: list, part_name: str, port_name: str) -> str:
    index = {node.id: node for node in nodes}
    matches = [
        node.id
        for node in nodes
        if node.kind == "PortUsage"
        and node.label == port_name
        and node.parent_id in index
        and index[node.parent_id].label == part_name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one projected port {part_name}.{port_name}, "
            f"found {len(matches)}. Inspect SysON typing/feature normalization."
        )
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SYSON_URL", "http://localhost:8080"))
    parser.add_argument("--token", default=os.getenv("SYSON_TOKEN"))
    parser.add_argument("--allow-writes", action="store_true", required=True)
    args = parser.parse_args()

    name = f"sysml-render-connection-smoke-{uuid.uuid4().hex[:12]}"
    model_path = ROOT / "examples/nested-system/vehicle-model.sysml"
    source = model_path.read_text(encoding="utf-8")
    importer = SysONImporter(args.url, token=args.token)
    imported = importer.import_text(
        source, filename="vehicle-model.sysml", project_name=name,
    )
    project_id = imported.project_id
    print(f"New disposable SysON project: {project_id}")
    print("The project will be retained for inspection and manual cleanup.")

    def snapshot():
        adapter = SysONRestAdapter(
            SysONRestConfig(base_url=args.url, project_id=project_id, token=args.token)
        )
        return adapter.snapshot()

    before = snapshot()
    selection = SemanticSelector(before).resolve("ElectricalSystem", profile="structure")
    root = selection.element_id
    graph = ProjectionEngine(before).project(root, "structure")
    source_port = port_node_id(graph.nodes, "battery", "powerOut")
    target_port = port_node_id(graph.nodes, "motor", "powerIn")
    plan = compile_canvas_connection(
        before, root, source_port, target_port, "batteryMotorSmoke",
    )
    print(f"Validated semantic statement: {plan.textual_content}")

    result = SysONTextualWriter(args.url, token=args.token).insert(
        editing_context_id=imported.editing_context_id,
        owner_element_id=plan.parent_id,
        textual_content=plan.textual_content,
    )
    print(f"GraphQL insertion accepted: {result.acknowledged}")
    after = snapshot()
    if not connection_in_semantic_snapshot(after, plan):
        raise RuntimeError(
            "SysON acknowledged insertion, but ConnectionUsage was not visible "
            "in normalized semantic REST snapshot. Do not retry blindly."
        )
    if not connection_visible(after, plan):
        raise RuntimeError(
            "SysON REST has the ConnectionUsage, but ProjectionEngine cannot "
            "materialize the edge. Inspect source/target feature references."
        )
    print("PASS: import -> automatic ports -> GraphQL connection insertion "
          "-> semantic REST reread -> visible diagram edge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
