from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "prototype") not in sys.path:
    sys.path.insert(0, str(ROOT / "prototype"))

from reference_integrity import audit_delete


class ReferenceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "examples/nested-system/vehicle-semantic.json"
        cls.snapshot = json.loads(fixture.read_text(encoding="utf-8"))

    def test_rejects_definition_referenced_by_part_usage(self):
        audit = audit_delete(self.snapshot, "partdef:Battery", server_relationships=[])
        self.assertFalse(audit.safe)
        self.assertTrue(any("typeRef" in reason for reason in audit.reasons))

    def test_rejects_semantic_owner_with_children(self):
        audit = audit_delete(self.snapshot, "partdef:ElectricalSystem", server_relationships=[])
        self.assertFalse(audit.safe)
        self.assertTrue(any("owns child" in reason for reason in audit.reasons))

    def test_fails_closed_when_remote_relationship_check_is_unavailable(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["elements"].append({
            "id": "partdef:Sensor", "name": "Sensor",
            "kind": "PartDefinition", "parentId": "pkg:Definitions",
        })
        audit = audit_delete(snapshot, "partdef:Sensor", server_relationships=None)
        self.assertFalse(audit.safe)
        self.assertTrue(any("unavailable" in reason for reason in audit.reasons))

    def test_rejects_remote_relationship_even_if_snapshot_looks_unreferenced(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["elements"].append({
            "id": "partdef:Sensor", "name": "Sensor",
            "kind": "PartDefinition", "parentId": "pkg:Definitions",
        })
        audit = audit_delete(
            snapshot, "partdef:Sensor",
            server_relationships=[{"@type": "OwningMembership", "@id": "membership"}],
        )
        self.assertFalse(audit.safe)
        self.assertTrue(any("associated" in reason for reason in audit.reasons))

    def test_unreferenced_leaf_may_pass_only_with_empty_remote_results(self):
        snapshot = json.loads(json.dumps(self.snapshot))
        snapshot["elements"].append({
            "id": "partdef:Sensor", "name": "Sensor",
            "kind": "PartDefinition", "parentId": "pkg:Definitions",
        })
        audit = audit_delete(snapshot, "partdef:Sensor", server_relationships=[])
        self.assertTrue(audit.safe, audit.reasons)


if __name__ == "__main__":
    unittest.main()
