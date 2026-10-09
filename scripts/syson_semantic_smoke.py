#!/usr/bin/env python3
"""Opt-in, destructive-on-a-disposable-project SysON semantic smoke test.

Creates a fresh SysON project. Never points writes at an existing project.
It intentionally leaves the fresh test project in SysON for inspection.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.syson.importer import SysONImporter
from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig
from adapters.syson.semantic_writer import SysONSemanticWriter


def find_one(snapshot: dict, name: str) -> dict:
    matches = [e for e in snapshot["elements"] if e["name"] == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {name!r}, got {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("SYSON_URL", "http://localhost:8080"))
    parser.add_argument("--allow-writes", action="store_true", required=True)
    parser.add_argument("--token", default=os.environ.get("SYSON_TOKEN"))
    args = parser.parse_args()

    suffix = uuid.uuid4().hex[:10]
    package = f"Smoke_{suffix}"
    source = (
        f"package {package} {{\n"
        "  part def Battery;\n"
        "}\n"
    )
    print("Creating a NEW disposable SysON project; never reusing an existing one.")
    importer = SysONImporter(args.url, token=args.token)
    result = importer.import_text(
        source,
        filename="semantic_smoke.sysml",
        project_name=f"sysml-render-smoke-{suffix}",
    )
    project_id = result.project_id
    print(f"Test project: {project_id}")
    print("This project is intentionally retained for manual inspection/cleanup.")

    adapter = SysONRestAdapter(
        SysONRestConfig(base_url=args.url, project_id=project_id, token=args.token)
    )
    writer = SysONSemanticWriter(args.url, project_id, token=args.token)
    snapshot = adapter.snapshot()
    root = find_one(snapshot, package)
    battery = find_one(snapshot, "Battery")
    print("Import/read OK")

    rename = writer.rename(battery["id"], "BackupBattery")
    if not rename.verified:
        raise RuntimeError("Rename verification failed")
    find_one(adapter.snapshot(), "BackupBattery")
    print("Rename/reread OK")

    created = writer.create_owned(root["id"], "PartDefinition", "ProbeSensor")
    if not created.verified or not created.element_id:
        raise RuntimeError("Create verification failed")
    next_snapshot = adapter.snapshot()
    sensor = find_one(next_snapshot, "ProbeSensor")
    if sensor["id"] != created.element_id:
        raise RuntimeError("Created semantic ID mismatch")
    if sensor.get("parentId") != root["id"]:
        raise RuntimeError(
            "Created element exists but its owner is not projected correctly: "
            f"expected {root['id']!r}, found {sensor.get('parentId')!r}"
        )
    print("Create/membership/normalized parent OK")

    deleted = writer.delete(created.element_id)
    if not deleted.verified:
        raise RuntimeError("Delete verification failed")
    if any(e["id"] == created.element_id for e in adapter.snapshot()["elements"]):
        raise RuntimeError("Deleted element is still in normalized snapshot")
    print("Delete/reread OK")
    print("PASS: import -> rename -> create under owner -> delete -> reread")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise
