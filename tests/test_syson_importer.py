from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from adapters.syson.importer import SysONImporter


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))

        if url.endswith("/api/rest/projects"):
            return FakeResponse(
                201,
                {
                    "@id": "project-1",
                    "@type": "Project",
                    "name": "demo",
                },
            )

        if url.endswith("/api/graphql"):
            return FakeResponse(
                200,
                {
                    "data": {
                        "viewer": {
                            "project": {
                                "currentEditingContext": {
                                    "id": "editing-1"
                                }
                            }
                        }
                    }
                },
            )

        if url.endswith("/api/graphql/upload"):
            return FakeResponse(
                200,
                {
                    "data": {
                        "uploadDocument": {
                            "__typename": "UploadDocumentSuccessPayload",
                            "id": "document-1",
                            "report": {"messages": []},
                        }
                    }
                },
            )

        raise AssertionError(f"unexpected POST {url}")


class SysONImporterTests(unittest.TestCase):
    def test_create_project_uses_syson_rest_api(self):
        session = FakeSession()
        importer = SysONImporter(
            "http://localhost:8080",
            session=session,
        )

        project_id = importer.create_project("demo")

        self.assertEqual("project-1", project_id)
        url, kwargs = session.calls[0]
        self.assertEqual(
            "http://localhost:8080/api/rest/projects",
            url,
        )
        self.assertEqual({"name": "demo"}, kwargs["params"])

    def test_fetch_editing_context_uses_graphql(self):
        session = FakeSession()
        importer = SysONImporter(
            "http://localhost:8080",
            session=session,
        )

        editing_context_id = importer.fetch_editing_context_id("project-1")

        self.assertEqual("editing-1", editing_context_id)
        url, kwargs = session.calls[0]
        self.assertEqual(
            "http://localhost:8080/api/graphql",
            url,
        )
        self.assertEqual(
            {"projectId": "project-1"},
            kwargs["json"]["variables"],
        )

    def test_import_text_can_create_project_and_upload_document(self):
        session = FakeSession()
        importer = SysONImporter(
            "http://localhost:8080",
            session=session,
        )

        result = importer.import_text(
            "package Demo {}",
            filename="demo.sysml",
            project_name="demo",
        )

        self.assertEqual("project-1", result.project_id)
        self.assertEqual("editing-1", result.editing_context_id)
        self.assertEqual("document-1", result.document_id)
        self.assertEqual(3, len(session.calls))

        upload_url, upload_kwargs = session.calls[2]
        self.assertEqual(
            "http://localhost:8080/api/graphql/upload",
            upload_url,
        )
        self.assertIn("operations", upload_kwargs["data"])
        self.assertIn("map", upload_kwargs["data"])
        self.assertEqual(
            "demo.sysml",
            upload_kwargs["files"]["0"][0],
        )
        self.assertEqual(
            b"package Demo {}",
            upload_kwargs["files"]["0"][1],
        )

    def test_import_text_reuses_existing_project(self):
        session = FakeSession()
        importer = SysONImporter(
            "http://localhost:8080",
            session=session,
        )

        result = importer.import_text(
            "package Demo {}",
            filename="demo.sysml",
            project_id="existing-project",
        )

        self.assertEqual("existing-project", result.project_id)
        self.assertEqual(2, len(session.calls))
        self.assertTrue(session.calls[0][0].endswith("/api/graphql"))
        self.assertTrue(session.calls[1][0].endswith("/api/graphql/upload"))


if __name__ == "__main__":
    unittest.main()
