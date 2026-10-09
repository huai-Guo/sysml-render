from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig
from projection import ProjectionEngine


RAW_ELEMENTS = [
    {
        "@id": "pkg",
        "@type": "Package",
        "name": "SystemModel",
        "ownedElement": [
            {"@id": "sys"},
            {"@id": "Battery"},
            {"@id": "Controller"},
        ],
    },
    {
        "@id": "Battery",
        "@type": "PartDefinition",
        "name": "Battery",
        "owner": {"@id": "pkg"},
        "ownedElement": [{"@id": "Battery.powerOut"}],
    },
    {
        "@id": "Battery.powerOut",
        "@type": "PortUsage",
        "name": "powerOut",
        "owner": {"@id": "Battery"},
    },
    {
        "@id": "Controller",
        "@type": "PartDefinition",
        "name": "Controller",
        "owner": {"@id": "pkg"},
        "ownedElement": [{"@id": "Controller.powerIn"}],
    },
    {
        "@id": "Controller.powerIn",
        "@type": "PortUsage",
        "name": "powerIn",
        "owner": {"@id": "Controller"},
    },
    {
        "@id": "sys",
        "@type": "PartDefinition",
        "name": "ElectricalSystem",
        "owner": {"@id": "pkg"},
        "ownedElement": [
            {"@id": "battery"},
            {"@id": "controller"},
            {"@id": "battery.powerOut"},
            {"@id": "controller.powerIn"},
            {"@id": "conn"},
        ],
    },
    {
        "@id": "battery",
        "@type": "PartUsage",
        "name": "battery",
        "owner": {"@id": "sys"},
        "type": [{"@id": "Battery"}],
    },
    {
        "@id": "controller",
        "@type": "PartUsage",
        "name": "controller",
        "owner": {"@id": "sys"},
        "type": [{"@id": "Controller"}],
    },
    {
        "@id": "battery.powerOut",
        "@type": "PortUsage",
        "name": "powerOut",
        "owner": {"@id": "sys"},
    },
    {
        "@id": "controller.powerIn",
        "@type": "PortUsage",
        "name": "powerIn",
        "owner": {"@id": "sys"},
    },
    {
        "@id": "conn",
        "@type": "ConnectionUsage",
        "name": "batteryPower",
        "owner": {"@id": "sys"},
        "sourceFeature": {"@id": "battery.powerOut"},
        "targetFeature": [{"@id": "controller.powerIn"}],
    },
    {
        "@id": "typing",
        "@type": "FeatureTyping",
        "source": [{"@id": "battery"}],
        "target": [{"@id": "Battery"}],
    },
]


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        if url.endswith("/commits"):
            return FakeResponse(200, [{"@id": "commit-9"}])
        return FakeResponse(200, self.payload)


class SysONRestAdapterTests(unittest.TestCase):
    def make_adapter(self, session=None):
        return SysONRestAdapter(
            SysONRestConfig(
                base_url="http://localhost:8080",
                project_id="project-1",
            ),
            session=session,
        )

    def test_uses_sysml_v2_elements_endpoint(self):
        session = FakeSession(RAW_ELEMENTS)
        snapshot = self.make_adapter(session).snapshot()

        self.assertEqual("project-1", snapshot["modelId"])
        self.assertEqual(2, len(session.calls))
        self.assertEqual(
            "http://localhost:8080/api/rest/projects/project-1/commits",
            session.calls[0][0],
        )
        self.assertEqual(
            "http://localhost:8080/api/rest/projects/project-1/"
            "commits/commit-9/elements",
            session.calls[1][0],
        )

    def test_normalizes_owner_type_and_connection_endpoints(self):
        snapshot = self.make_adapter().normalize_elements(RAW_ELEMENTS)
        elements = {element["id"]: element for element in snapshot["elements"]}
        relationships = {
            relationship["id"]: relationship
            for relationship in snapshot["relationships"]
        }

        self.assertEqual("sys", elements["battery"]["parentId"])
        self.assertEqual("Battery", elements["battery"]["typeRef"])
        self.assertEqual("sys", relationships["conn"]["ownerId"])
        self.assertEqual(
            "battery.powerOut",
            relationships["conn"]["sourceId"],
        )
        self.assertEqual(
            "controller.powerIn",
            relationships["conn"]["targetId"],
        )

    def test_owning_membership_projects_child_into_package(self):
        raw = [
            {
                "@id": "root",
                "@type": "Package",
                "name": "Root",
                "ownedRelationship": [{"@id": "membership"}],
            },
            {
                "@id": "membership",
                "@type": "OwningMembership",
                "owner": {"@id": "root"},
                "ownedRelatedElement": [{"@id": "sensor"}],
            },
            {
                "@id": "sensor",
                "@type": "PartDefinition",
                "name": "Sensor",
                "owner": {"@id": "membership"},
            },
        ]
        snapshot = self.make_adapter().normalize_elements(raw)
        sensor = next(e for e in snapshot["elements"] if e["id"] == "sensor")
        self.assertEqual("root", sensor["parentId"])
        self.assertNotIn(
            "membership",
            {e["id"] for e in snapshot["elements"]},
        )

    def test_filters_internal_metamodel_relationships(self):
        snapshot = self.make_adapter().normalize_elements(RAW_ELEMENTS)
        ids = {element["id"] for element in snapshot["elements"]}
        relationship_ids = {
            relationship["id"]
            for relationship in snapshot["relationships"]
        }

        self.assertNotIn("typing", ids)
        self.assertNotIn("typing", relationship_ids)

    def test_normalized_snapshot_projects_existing_connection_automatically(self):
        snapshot = self.make_adapter().normalize_elements(RAW_ELEMENTS)
        ir = ProjectionEngine(snapshot).project("sys", "structure")

        self.assertEqual(1, len(ir.edges))
        edge = ir.edges[0]
        self.assertEqual("conn", edge.semantic_id)
        self.assertEqual("battery.powerOut", edge.source)
        self.assertEqual("controller.powerIn", edge.target)


if __name__ == "__main__":
    unittest.main()
