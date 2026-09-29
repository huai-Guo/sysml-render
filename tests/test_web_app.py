from __future__ import annotations

import json
import sys
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
