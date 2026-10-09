from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.syson.semantic_writer import SysONSemanticWriter
from prototype.semantic_commands import (
    CreateOwnedElementCommand,
    DeleteElementCommand,
    RenameElementCommand,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.commits = ["project-1"]
        self.elements = {
            "part-1": {
                "@id": "part-1",
                "@type": "PartDefinition",
                "declaredName": "Battery",
                "name": "Battery",
            },
            "pkg-1": {
                "@id": "pkg-1",
                "@type": "Package",
                "declaredName": "Demo",
                "name": "Demo",
            },
        }
        self.posts = []

    def get(self, url, **kwargs):
        if url.endswith("/commits"):
            return FakeResponse(
                200,
                [{"@id": commit_id} for commit_id in self.commits],
            )

        if "/elements/" in url:
            element_id = url.rsplit("/", 1)[-1]
            element = self.elements.get(element_id)
            if element is None:
                return FakeResponse(404, {})
            return FakeResponse(200, dict(element))

        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, json=None, **kwargs):
        self.posts.append((url, json))
        next_commit = "project-1"  # SysON currently returns one effective commit

        for change in json.get("change", []):
            identity = change.get("identity")
            payload = change.get("payload")

            if identity and payload is None:
                self.elements.pop(identity["@id"], None)
                continue

            if identity and payload:
                target_id = identity["@id"]
                if target_id in self.elements:
                    if "declaredName" in payload:
                        self.elements[target_id]["declaredName"] = payload["declaredName"]
                        self.elements[target_id]["name"] = payload["declaredName"]
                continue

            if identity is None and payload:
                if payload.get("@type") != "OwningMembership":
                    element_id = payload["@id"]
                    self.elements[element_id] = {
                        "@id": element_id,
                        "@type": payload["@type"],
                        "declaredName": payload.get("declaredName"),
                        "name": payload.get("declaredName"),
                    }

        return FakeResponse(201, {"@id": next_commit, "@type": "Commit"})


class SysONSemanticWriterTests(unittest.TestCase):
    def make_writer(self):
        session = FakeSession()
        writer = SysONSemanticWriter(
            "http://localhost:8080",
            "project-1",
            session=session,
        )
        return writer, session

    def test_rename_posts_identity_and_new_payload_then_verifies(self):
        writer, session = self.make_writer()

        result = writer.apply(
            RenameElementCommand(
                element_id="part-1",
                new_name="BackupBattery",
            )
        )

        self.assertTrue(result.verified)
        self.assertEqual("BackupBattery", session.elements["part-1"]["name"])
        body = session.posts[0][1]
        change = body["change"][0]
        self.assertEqual("part-1", change["identity"]["@id"])
        self.assertEqual("PartDefinition", change["payload"]["@type"])
        self.assertEqual("BackupBattery", change["payload"]["declaredName"])
        self.assertNotEqual("part-1", change["payload"]["@id"])
        self.assertEqual("part-1", change["payload"]["elementId"])
        self.assertNotIn("previousCommit", body)

    def test_delete_omits_payload_and_verifies_404(self):
        writer, session = self.make_writer()

        result = writer.apply(DeleteElementCommand(element_id="part-1"))

        self.assertTrue(result.verified)
        self.assertNotIn("part-1", session.elements)
        change = session.posts[0][1]["change"][0]
        self.assertEqual("part-1", change["identity"]["@id"])
        self.assertNotIn("payload", change)

    def test_create_owned_uses_membership_then_element_commit(self):
        writer, session = self.make_writer()

        result = writer.apply(
            CreateOwnedElementCommand(
                owner_id="pkg-1",
                element_type="PartDefinition",
                name="Controller",
            )
        )

        self.assertTrue(result.verified)
        self.assertEqual(2, len(session.posts))
        first_body = session.posts[0][1]
        second_body = session.posts[1][1]

        self.assertNotIn("previousCommit", first_body)
        self.assertNotIn("previousCommit", second_body)
        self.assertEqual("project-1", result.commit_id)
        self.assertEqual(
            "OwningMembership",
            first_body["change"][0]["payload"]["@type"],
        )
        self.assertEqual(
            "PartDefinition",
            second_body["change"][0]["payload"]["@type"],
        )
        self.assertEqual(
            "Controller",
            second_body["change"][0]["payload"]["declaredName"],
        )
        self.assertIn(result.element_id, session.elements)


if __name__ == "__main__":
    unittest.main()
