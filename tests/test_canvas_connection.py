from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "prototype") not in sys.path:
    sys.path.insert(0, str(ROOT / "prototype"))

from connection_editing import (
    ConnectionValidationError,
    compile_canvas_connection,
    connection_visible,
    connection_in_semantic_snapshot,
)


class CanvasConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "examples/nested-system/vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))
        cls.root = "partdef:ElectricalSystem"
        cls.battery = (
            "projection:part:ElectricalSystem.battery/port:Battery.powerOut"
        )
        cls.motor = (
            "projection:part:ElectricalSystem.motor/port:Motor.powerIn"
        )
        cls.controller = (
            "projection:part:ElectricalSystem.controller/port:Controller.powerIn"
        )

    def test_compiles_visible_port_pairs_to_sysml_semantics(self):
        plan = compile_canvas_connection(
            self.snapshot, self.root, self.battery, self.motor, "batteryToMotor"
        )
        self.assertEqual(("battery", "powerOut"), plan.source_path)
        self.assertEqual(("motor", "powerIn"), plan.target_path)
        self.assertEqual(
            "connection batteryToMotor connect battery.powerOut to motor.powerIn;",
            plan.textual_content,
        )
        self.assertFalse(connection_visible(self.snapshot, plan))
        self.assertFalse(connection_in_semantic_snapshot(self.snapshot, plan))

        updated = json.loads(json.dumps(self.snapshot))
        updated["relationships"].append({
            "id": "conn:ElectricalSystem.batteryToMotor",
            "name": "batteryToMotor",
            "kind": "ConnectionUsage",
            "ownerId": self.root,
            "sourcePath": ["battery", "powerOut"],
            "targetPath": ["motor", "powerIn"],
        })
        self.assertTrue(connection_in_semantic_snapshot(updated, plan))
        self.assertTrue(connection_visible(updated, plan))

    def test_existing_semantic_connection_cannot_be_duplicated(self):
        with self.assertRaisesRegex(ConnectionValidationError, "already exists"):
            compile_canvas_connection(
                self.snapshot, self.root, self.battery, self.controller, "duplicate"
            )

    def test_rejects_unrelated_diagram_nodes_and_self_loops(self):
        for source, target in [
            ("part:ElectricalSystem.battery", self.motor),
            ("not-a-node", self.motor),
            (self.battery, self.battery),
        ]:
            with self.subTest(source=source, target=target):
                with self.assertRaises(ConnectionValidationError):
                    compile_canvas_connection(
                        self.snapshot, self.root, source, target, "sample"
                    )

    def test_prevents_injected_sysml_identifiers(self):
        with self.assertRaisesRegex(ConnectionValidationError, "safe"):
            compile_canvas_connection(
                self.snapshot, self.root, self.battery, self.motor,
                "bad; delete sysml",
            )

    def test_prevents_duplicate_semantic_names(self):
        with self.assertRaisesRegex(ConnectionValidationError, "already exists"):
            compile_canvas_connection(
                self.snapshot, self.root, self.battery, self.motor, "motorControl"
            )

    def test_does_not_infer_semantic_relationships_from_nearby_parts(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["relationships"] = []
        plan = compile_canvas_connection(
            snapshot, self.root, self.battery, self.motor, "newConnection"
        )
        self.assertFalse(connection_visible(snapshot, plan))


if __name__ == "__main__":
    unittest.main()
