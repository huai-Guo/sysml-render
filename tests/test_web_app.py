from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from apps.web.app import app


class FakeImporter:
    def __init__(self, *args, **kwargs):
        pass

    def import_text(self, *args, **kwargs):
        return SimpleNamespace(
            project_id="project-web",
            editing_context_id="editing-web",
            document_id="document-web",
            import_report={"messages": []},
        )


class FakeAdapter:
    def __init__(self, *args, **kwargs):
        pass

    def snapshot(self):
        fixture = (
            ROOT
            / "examples"
            / "nested-system"
            / "vehicle-semantic.json"
        )
        return json.loads(fixture.read_text(encoding="utf-8"))


class FakeWriter:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def apply(self, command):
        self.calls.append(command)
        return SimpleNamespace(
            project_id="project-web",
            command=command.kind,
            element_id=getattr(command, "element_id", "generated-element"),
            membership_id=None,
            commit_id="project-web",
            verified=True,
        )


class FakeAdapterWithLeaf(FakeAdapter):
    def snapshot(self):
        data = super().snapshot()
        data["elements"].append({
            "id": "partdef:Orphan",
            "name": "Orphan",
            "kind": "PartDefinition",
            "parentId": "pkg:Definitions",
        })
        return data


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    def test_home_exposes_text_and_file_inputs(self):
        response = self.client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn('name="sysml_text"', response.text)
        self.assertIn('name="file"', response.text)
        self.assertIn("导入并自动渲染", response.text)

    @patch("apps.web.app.SysONRestAdapter", FakeAdapter)
    @patch("apps.web.app.SysONImporter", FakeImporter)
    def test_render_endpoint_returns_auto_projected_graph_and_preview(self):
        response = self.client.post(
            "/api/render",
            data={
                "sysml_text": "package VehicleModel {}",
                "select": "ElectricalSystem",
                "profile": "structure",
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("project-web", payload["projectId"])
        self.assertEqual(
            "partdef:ElectricalSystem",
            payload["rootSemanticId"],
        )
        self.assertEqual("structure", payload["profile"])
        self.assertEqual(2, len(payload["graph"]["edges"]))
        self.assertIn(
            "conn:ElectricalSystem.batteryPower",
            {edge["id"] for edge in payload["graph"]["edges"]},
        )
        self.assertIn("batteryPower", payload["previewHtml"])
        self.assertIn("controller", payload["previewHtml"])

    @patch("apps.web.app.SysONRestAdapter", FakeAdapter)
    @patch("apps.web.app.SysONImporter", FakeImporter)
    def test_saved_layout_is_restored_on_next_render(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"SYSML_RENDER_STATE_DIR": directory},
                clear=False,
            ):
                first = self.client.post(
                    "/api/render",
                    data={
                        "sysml_text": "package VehicleModel {}",
                        "select": "ElectricalSystem",
                        "profile": "structure",
                    },
                )
                self.assertEqual(200, first.status_code)
                payload = first.json()

                part_id = "part:ElectricalSystem.battery"
                before = next(
                    node
                    for node in payload["layout"]["nodes"]
                    if node["id"] == part_id
                )

                saved_x = before["x"] + 211
                saved_y = before["y"] + 97
                update = self.client.post(
                    f'/api/views/{payload["viewId"]}/layout',
                    json={
                        "project_id": payload["projectId"],
                        "root_semantic_id": payload["rootSemanticId"],
                        "profile": payload["profile"],
                        "node_id": part_id,
                        "x": saved_x,
                        "y": saved_y,
                    },
                )
                self.assertEqual(200, update.status_code)

                second = self.client.post(
                    "/api/render",
                    data={
                        "sysml_text": "package VehicleModel {}",
                        "project_id": payload["projectId"],
                        "select": "ElectricalSystem",
                        "profile": "structure",
                    },
                )
                self.assertEqual(200, second.status_code)
                after = next(
                    node
                    for node in second.json()["layout"]["nodes"]
                    if node["id"] == part_id
                )

                self.assertEqual(saved_x, after["x"])
                self.assertEqual(saved_y, after["y"])

    @patch("apps.web.app.SysONRestAdapter", FakeAdapter)
    def test_read_only_refresh_does_not_import_existing_model(self):
        response = self.client.post(
            "/api/projects/project-web/render",
            json={"select": "ElectricalSystem", "profile": "structure"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("partdef:ElectricalSystem", response.json()["rootSemanticId"])
        self.assertEqual(2, len(response.json()["graph"]["edges"]))

    @patch.dict(os.environ, {"SYSON_ENABLE_SEMANTIC_WRITES": "0"})
    def test_semantic_edit_disabled_by_default(self):
        response = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={
                "kind": "rename_element",
                "element_id": "partdef:Battery",
                "new_name": "BackupBattery",
            },
        )
        self.assertEqual(403, response.status_code)

    @patch.dict(os.environ, {"SYSON_ENABLE_SEMANTIC_WRITES": "1"})
    @patch("apps.web.app.SysONSemanticWriter", FakeWriter)
    @patch("apps.web.app.SysONRestAdapter", FakeAdapter)
    def test_semantic_rename_routes_to_writer(self):
        FakeWriter.calls.clear()
        response = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={
                "kind": "rename_element",
                "element_id": "partdef:Battery",
                "new_name": "BackupBattery",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()["verified"])
        self.assertEqual("BackupBattery", FakeWriter.calls[-1].new_name)
        self.assertTrue(response.json()["refreshRequired"])

    @patch.dict(os.environ, {"SYSON_ENABLE_SEMANTIC_WRITES": "1"})
    @patch("apps.web.app.SysONSemanticWriter", FakeWriter)
    @patch("apps.web.app.SysONRestAdapter", FakeAdapter)
    def test_semantic_create_rejects_duplicate_and_accepts_valid_child(self):
        FakeWriter.calls.clear()
        duplicate = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={
                "kind": "create_owned_element",
                "owner_id": "pkg:Definitions",
                "element_type": "PartDefinition",
                "new_name": "Battery",
            },
        )
        self.assertEqual(409, duplicate.status_code)
        valid = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={
                "kind": "create_owned_element",
                "owner_id": "pkg:Definitions",
                "element_type": "PartDefinition",
                "new_name": "NewSensor",
            },
        )
        self.assertEqual(200, valid.status_code)
        self.assertEqual("NewSensor", FakeWriter.calls[-1].name)

    @patch.dict(os.environ, {"SYSON_ENABLE_SEMANTIC_WRITES": "1"})
    @patch("apps.web.app.SysONSemanticWriter", FakeWriter)
    @patch("apps.web.app.SysONRestAdapter", FakeAdapterWithLeaf)
    def test_delete_requires_confirmation_and_rejects_referenced_definitions(self):
        FakeWriter.calls.clear()
        missing_confirmation = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={"kind": "delete_element", "element_id": "partdef:Orphan"},
        )
        self.assertEqual(409, missing_confirmation.status_code)
        referenced = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={
                "kind": "delete_element",
                "element_id": "partdef:Battery",
                "confirmed": True,
            },
        )
        self.assertEqual(409, referenced.status_code)
        allowed = self.client.post(
            "/api/projects/project-web/semantic-commands",
            json={
                "kind": "delete_element",
                "element_id": "partdef:Orphan",
                "confirmed": True,
            },
        )
        self.assertEqual(200, allowed.status_code)
        self.assertEqual("partdef:Orphan", FakeWriter.calls[-1].element_id)

    def test_web_exposes_selection_and_refresh_controls(self):
        html = self.client.get("/").text
        self.assertIn('id="semantic-actions"', html)
        self.assertIn('id="refresh-project"', html)
        self.assertIn('sandbox="allow-scripts"', html)

    @patch("apps.web.app.SysONRestAdapter", FakeAdapter)
    @patch("apps.web.app.SysONImporter", FakeImporter)
    def test_render_endpoint_accepts_sysml_file(self):
        response = self.client.post(
            "/api/render",
            files={
                "file": (
                    "vehicle.sysml",
                    b"package VehicleModel {}",
                    "text/plain",
                )
            },
            data={
                "select": "ElectricalSystem",
                "profile": "structure",
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "partdef:ElectricalSystem",
            response.json()["rootSemanticId"],
        )


if __name__ == "__main__":
    unittest.main()
