from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from semantic_resolution import SemanticFeatureResolver


class SemanticFeatureResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = ROOT / "examples" / "nested-system" / "vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))
        cls.elements = {
            element["id"]: element
            for element in cls.snapshot["elements"]
        }

    def test_resolves_existing_two_segment_feature_chain(self):
        resolver = SemanticFeatureResolver(self.elements)
        result = resolver.resolve(
            "partdef:ElectricalSystem",
            ["battery", "powerOut"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            "port:Battery.powerOut",
            result.semantic_id,
        )
        self.assertTrue(result.steps[-1].via_type)
        self.assertEqual(
            "part:ElectricalSystem.battery",
            result.steps[-1].context_semantic_id,
        )

    def test_resolves_arbitrary_depth_through_multiple_types(self):
        resolver = SemanticFeatureResolver(self.elements)
        result = resolver.resolve(
            "partdef:Vehicle",
            ["electrical", "battery", "powerOut"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            [
                "part:Vehicle.electrical",
                "part:ElectricalSystem.battery",
                "port:Battery.powerOut",
            ],
            [step.semantic_id for step in result.steps],
        )
        self.assertEqual(
            "part:ElectricalSystem.battery",
            result.steps[-1].context_semantic_id,
        )

    def test_unknown_segment_fails_without_guessing(self):
        resolver = SemanticFeatureResolver(self.elements)

        self.assertIsNone(
            resolver.resolve(
                "partdef:Vehicle",
                ["electrical", "missing", "powerOut"],
            )
        )


if __name__ == "__main__":
    unittest.main()
