from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from layout import SimpleHierarchicalLayout
from projection import ProjectionEngine


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = ROOT / "examples" / "nested-system" / "vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))

    def test_structure_layout_places_all_projected_nodes(self):
        ir = ProjectionEngine(self.snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )
        result = SimpleHierarchicalLayout().layout(ir)

        self.assertEqual(
            {node.id for node in ir.nodes},
            {node.id for node in result.nodes},
        )

    def test_structure_layout_routes_all_semantic_edges(self):
        ir = ProjectionEngine(self.snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )
        result = SimpleHierarchicalLayout().layout(ir)

        self.assertEqual(
            {edge.id for edge in ir.edges},
            {edge.id for edge in result.edges},
        )
        for edge in result.edges:
            self.assertGreaterEqual(len(edge.points), 2)

    def test_package_overview_is_geometrically_nested(self):
        ir = ProjectionEngine(self.snapshot).project(
            "pkg:VehicleModel",
            "package-overview",
        )
        result = SimpleHierarchicalLayout().layout(ir)
        positions = {node.id: node for node in result.nodes}

        root = positions["pkg:VehicleModel"]
        definitions = positions["pkg:Definitions"]
        battery = positions["partdef:Battery"]

        self.assertGreater(definitions.x, root.x)
        self.assertGreater(definitions.y, root.y)
        self.assertLess(
            definitions.x + definitions.width,
            root.x + root.width,
        )
        self.assertLess(
            definitions.y + definitions.height,
            root.y + root.height,
        )

        self.assertGreater(battery.x, definitions.x)
        self.assertGreater(battery.y, definitions.y)
        self.assertLess(
            battery.x + battery.width,
            definitions.x + definitions.width,
        )
        self.assertLess(
            battery.y + battery.height,
            definitions.y + definitions.height,
        )

    def test_moving_nested_container_moves_complete_visual_subtree(self):
        ir = ProjectionEngine(self.snapshot).project(
            "pkg:VehicleModel",
            "package-overview",
        )
        engine = SimpleHierarchicalLayout()
        initial = engine.layout(ir)
        before = {node.id: node for node in initial.nodes}

        definitions = before["pkg:Definitions"]
        battery = before["partdef:Battery"]
        dx, dy = 133.0, 71.0

        moved = engine.layout(
            ir,
            overrides={
                "pkg:Definitions": {
                    "x": definitions.x + dx,
                    "y": definitions.y + dy,
                    "pinned": True,
                }
            },
        )
        after = {node.id: node for node in moved.nodes}

        self.assertEqual(definitions.x + dx, after["pkg:Definitions"].x)
        self.assertEqual(definitions.y + dy, after["pkg:Definitions"].y)
        self.assertEqual(battery.x + dx, after["partdef:Battery"].x)
        self.assertEqual(battery.y + dy, after["partdef:Battery"].y)

    def test_ports_stay_on_part_boundaries(self):
        ir = ProjectionEngine(self.snapshot).project(
            "partdef:ElectricalSystem",
            "structure",
        )
        result = SimpleHierarchicalLayout().layout(ir)
        positions = {node.id: node for node in result.nodes}

        part_id = "part:ElectricalSystem.battery"
        port_id = (
            "projection:part:ElectricalSystem.battery/"
            "port:Battery.powerOut"
        )
        part = positions[part_id]
        port = positions[port_id]
        port_center_x = port.x + port.width / 2

        self.assertIn(
            port_center_x,
            {part.x, part.x + part.width},
        )


if __name__ == "__main__":
    unittest.main()
