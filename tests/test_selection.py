from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from selection import SelectionError, SemanticSelector


class SemanticSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = ROOT / "examples" / "nested-system" / "vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))

    def test_selects_single_root_package_by_default(self):
        selection = SemanticSelector(self.snapshot).resolve()

        self.assertEqual("pkg:VehicleModel", selection.element_id)
        self.assertEqual("package-overview", selection.profile)

    def test_resolves_by_name_and_infers_structure_profile(self):
        selection = SemanticSelector(self.snapshot).resolve(
            "ElectricalSystem"
        )

        self.assertEqual("partdef:ElectricalSystem", selection.element_id)
        self.assertEqual("structure", selection.profile)

    def test_resolves_by_id(self):
        selection = SemanticSelector(self.snapshot).resolve(
            "req:powerContinuity"
        )

        self.assertEqual("requirements", selection.profile)

    def test_explicit_profile_overrides_inference(self):
        selection = SemanticSelector(self.snapshot).resolve(
            "ElectricalSystem",
            profile="package-overview",
        )

        self.assertEqual("package-overview", selection.profile)

    def test_ambiguous_name_requires_disambiguation(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["elements"].append(
            {
                "id": "other",
                "name": "ElectricalSystem",
                "qualifiedName": "Other::ElectricalSystem",
                "kind": "PartDefinition",
                "parentId": "pkg:VehicleModel",
            }
        )

        with self.assertRaises(SelectionError):
            SemanticSelector(snapshot).resolve("ElectricalSystem")


if __name__ == "__main__":
    unittest.main()
