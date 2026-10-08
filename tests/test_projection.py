from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from projection import ProjectionEngine


class ProjectionEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = ROOT / "examples" / "nested-system" / "vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))

    def test_structure_projection_materializes_parts_ports_and_connections(self):
        ir = ProjectionEngine(self.snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )

        node_ids = {node.id for node in ir.nodes}
        edge_ids = {edge.id for edge in ir.edges}

        self.assertIn("part:ElectricalSystem.battery", node_ids)
        self.assertIn("part:ElectricalSystem.controller", node_ids)
        self.assertIn("part:ElectricalSystem.motor", node_ids)

        battery_power = (
            "projection:part:ElectricalSystem.battery/"
            "port:Battery.powerOut"
        )
        controller_power = (
            "projection:part:ElectricalSystem.controller/"
            "port:Controller.powerIn"
        )
        controller_command = (
            "projection:part:ElectricalSystem.controller/"
            "port:Controller.motorCommand"
        )
        motor_command = (
            "projection:part:ElectricalSystem.motor/"
            "port:Motor.commandIn"
        )

        self.assertIn(battery_power, node_ids)
        self.assertIn(controller_power, node_ids)
        self.assertIn(controller_command, node_ids)
        self.assertIn(motor_command, node_ids)

        self.assertEqual(
            {
                "conn:ElectricalSystem.batteryPower",
                "conn:ElectricalSystem.motorControl",
            },
            edge_ids,
        )

        edges = {edge.id: edge for edge in ir.edges}
        self.assertEqual(
            battery_power,
            edges["conn:ElectricalSystem.batteryPower"].source,
        )
        self.assertEqual(
            controller_power,
            edges["conn:ElectricalSystem.batteryPower"].target,
        )
        self.assertEqual(
            controller_command,
            edges["conn:ElectricalSystem.motorControl"].source,
        )
        self.assertEqual(
            motor_command,
            edges["conn:ElectricalSystem.motorControl"].target,
        )

    def test_projected_ports_keep_semantic_identity_and_usage_context(self):
        ir = ProjectionEngine(self.snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )

        node = next(
            node
            for node in ir.nodes
            if node.id
            == "projection:part:ElectricalSystem.battery/port:Battery.powerOut"
        )

        self.assertTrue(node.derived)
        self.assertEqual("port:Battery.powerOut", node.semantic_id)
        self.assertEqual(
            "part:ElectricalSystem.battery",
            node.context_semantic_id,
        )

    def test_structure_projection_resolves_multi_hop_feature_chain(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["relationships"].append(
            {
                "id": "conn:Vehicle.deepPower",
                "name": "deepPower",
                "kind": "ConnectionUsage",
                "ownerId": "partdef:Vehicle",
                "sourcePath": [
                    "electrical",
                    "battery",
                    "powerOut",
                ],
                "targetPath": [
                    "electrical",
                    "controller",
                    "powerIn",
                ],
            }
        )

        ir = ProjectionEngine(snapshot).project(
            "partdef:Vehicle",
            "structure",
        )

        edges = {edge.id: edge for edge in ir.edges}
        self.assertIn("conn:Vehicle.deepPower", edges)

        edge = edges["conn:Vehicle.deepPower"]
        self.assertIn("part:ElectricalSystem.battery", edge.source)
        self.assertIn("port:Battery.powerOut", edge.source)
        self.assertIn("part:ElectricalSystem.controller", edge.target)
        self.assertIn("port:Controller.powerIn", edge.target)

        projected = {
            node.id: node
            for node in ir.nodes
            if node.derived
        }
        self.assertIn(edge.source, projected)
        self.assertIn(edge.target, projected)

    def test_renderer_does_not_invent_edges(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["relationships"] = []

        ir = ProjectionEngine(snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )

        self.assertEqual([], ir.edges)

    def test_package_overview_discovers_nested_semantic_elements(self):
        ir = ProjectionEngine(self.snapshot).project(
            "pkg:VehicleModel",
            "package-overview",
        )

        labels = {node.label for node in ir.nodes}
        self.assertTrue(
            {
                "VehicleModel",
                "Interfaces",
                "Requirements",
                "Definitions",
                "Usages",
                "Battery",
                "Controller",
                "Motor",
                "ElectricalSystem",
                "Vehicle",
                "PowerPort",
                "ControlPort",
                "vehicle",
                "powerContinuity",
                "motorControl",
                "PowerContinuityRequirement",
                "MotorControlRequirement",
            }.issubset(labels)
        )


if __name__ == "__main__":
    unittest.main()
