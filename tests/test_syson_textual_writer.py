from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.syson.textual_writer import SysONTextualWriter, SysONTextualWriteError


class Response:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload, self.status_code)


class TextualWriterTests(unittest.TestCase):
    def test_uses_confirmed_syson_mutation_and_parent_semantic_id(self):
        session = Session({
            "data": {"insertTextualSysMLv2": {
                "__typename": "SuccessPayload", "id": "operation-id", "messages": []
            }}
        })
        writer = SysONTextualWriter("http://localhost:8080", session=session)
        result = writer.insert(
            editing_context_id="editing",
            owner_element_id="electrical",
            textual_content="connection c connect a.port to b.port;",
        )
        self.assertTrue(result.acknowledged)
        url, options = session.calls[0]
        self.assertEqual("http://localhost:8080/api/graphql", url)
        body = options["json"]
        self.assertIn("insertTextualSysMLv2", body["query"])
        entry = body["variables"]["input"]
        self.assertEqual("editing", entry["editingContextId"])
        self.assertEqual("electrical", entry["objectId"])
        self.assertEqual("connection c connect a.port to b.port;", entry["textualContent"])

    def test_rejects_error_payload_even_if_http_ok(self):
        session = Session({
            "data": {"insertTextualSysMLv2": {
                "__typename": "ErrorPayload",
                "messages": [{"level": "ERROR", "body": "Bad SysML"}],
            }}
        })
        with self.assertRaisesRegex(SysONTextualWriteError, "Bad SysML"):
            SysONTextualWriter("http://localhost:8080", session=session).insert(
                editing_context_id="editing",
                owner_element_id="electrical",
                textual_content="bad code",
            )

    def test_rejects_graphql_error(self):
        session = Session({"errors": [{"message": "No permission"}]})
        with self.assertRaisesRegex(SysONTextualWriteError, "No permission"):
            SysONTextualWriter("http://localhost:8080", session=session).insert(
                editing_context_id="editing",
                owner_element_id="electrical",
                textual_content="connection c connect a.x to b.y;",
            )


if __name__ == "__main__":
    unittest.main()
