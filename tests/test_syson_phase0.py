import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "syson_phase0.py"
spec = importlib.util.spec_from_file_location("syson_phase0", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class Phase0HelpersTest(unittest.TestCase):
    def test_find_element_prefers_declared_name_and_type(self):
        elements = [
            {
                "@id": "1",
                "@type": "Package",
                "declaredName": "VehicleArchitecture",
            },
            {
                "@id": "2",
                "@type": "PartUsage",
                "declaredName": "VehicleArchitecture",
            },
        ]
        found = mod.find_element(
            elements,
            "VehicleArchitecture",
            "Package",
        )
        self.assertEqual(found["@id"], "1")

    def test_check_expected_elements_reports_missing_type_name_pair(self):
        elements = [
            {
                "@type": "Package",
                "declaredName": "A",
            }
        ]
        missing = mod.check_expected_elements(
            elements,
            [
                {"name": "A", "type": "Package"},
                {"name": "B", "type": "PartDefinition"},
            ],
        )
        self.assertEqual(missing, ["PartDefinition:B"])

    def test_expectation_fixture_is_consistent(self):
        data = json.loads(
            (
                ROOT
                / "examples/phase0/expectations.json"
            ).read_text(encoding="utf-8")
        )
        names = {
            item["name"]
            for item in data["requiredElements"]
        }
        self.assertIn(
            data["semanticMutationTarget"]["name"],
            names,
        )
        self.assertTrue(data["requiredAfterMutation"])


if __name__ == "__main__":
    unittest.main()
