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
