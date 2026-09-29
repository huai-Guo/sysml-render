from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from layout import SimpleHierarchicalLayout
from projection import ProjectionEngine
from view_state import FileViewStateStore, ViewIdentity


class ViewStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = ROOT / "examples" / "nested-system" / "vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))

    def test_view_identity_is_stable_and_scope_specific(self):
        a = ViewIdentity("p1", "root", "structure")
        b = ViewIdentity("p1", "root", "structure")
        c = ViewIdentity("p1", "root", "requirements")

        self.assertEqual(a.id, b.id)
        self.assertNotEqual(a.id, c.id)

    def test_store_persists_only_layout_state(self):
        identity = ViewIdentity(
            "project-1",
            "partdef:ElectricalSystem",
            "structure",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileViewStateStore(directory)
            store.update_node(
                identity=identity,
                node_id="part:ElectricalSystem.battery",
                x=777,
                y=333,
            )

            state = store.load(identity.id)

            self.assertEqual(
                {
                    "x": 777.0,
                    "y": 333.0,
                    "pinned": True,
                },
                state["part:ElectricalSystem.battery"],
            )
            persisted = json.loads(
                (
                    Path(directory)
                    / f"{identity.id}.sysmlview.json"
                ).read_text(encoding="utf-8")
            )
            self.assertNotIn("semanticElements", persisted)
            self.assertEqual(
                "partdef:ElectricalSystem",
                persisted["rootSemanticId"],
            )

    def test_layout_override_moves_part_and_context_ports(self):
        ir = ProjectionEngine(self.snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )
        engine = SimpleHierarchicalLayout()
        initial = engine.layout(ir)
        initial_positions = {
            node.id: node
            for node in initial.nodes
        }

        part_id = "part:ElectricalSystem.battery"
        port_id = (
            "projection:part:ElectricalSystem.battery/"
            "port:Battery.powerOut"
        )
        part_before = initial_positions[part_id]
        port_before = initial_positions[port_id]

        moved = engine.layout(
            ir,
            overrides={
                part_id: {
                    "x": part_before.x + 125,
                    "y": part_before.y + 80,
                    "pinned": True,
                }
            },
        )
        moved_positions = {
            node.id: node
            for node in moved.nodes
        }
        part_after = moved_positions[part_id]
        port_after = moved_positions[port_id]

        self.assertEqual(part_before.x + 125, part_after.x)
        self.assertEqual(part_before.y + 80, part_after.y)
        self.assertEqual(port_before.x + 125, port_after.x)
        self.assertEqual(port_before.y + 80, port_after.y)


if __name__ == "__main__":
    unittest.main()
