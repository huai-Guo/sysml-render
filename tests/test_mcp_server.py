from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from apps.mcp.server import get_semantic_element, mcp, render_project


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

    def fetch_element(self, element_id):
        return {
            "@id": element_id,
            "@type": "PartDefinition",
            "name": "ElectricalSystem",
        }


class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_exposes_renderer_tools(self):
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}

        self.assertTrue(
            {
                "render_sysml",
                "render_project",
                "get_semantic_element",
            }.issubset(names)
        )

    @patch("apps.mcp.server.SysONRestAdapter", FakeAdapter)
    def test_render_project_reuses_renderer_core(self):
        result = render_project(
            "project-1",
            select="ElectricalSystem",
            profile="structure",
        )

        self.assertEqual("project-1", result.project_id)
        self.assertEqual("partdef:ElectricalSystem", result.root_semantic_id)
        self.assertEqual(2, len(result.graph["edges"]))
        self.assertIn("batteryPower", result.preview_html)

    @patch("apps.mcp.server.SysONRestAdapter", FakeAdapter)
    def test_get_semantic_element(self):
        result = get_semantic_element(
            "project-1",
            "partdef:ElectricalSystem",
        )

        self.assertEqual("project-1", result.project_id)
        self.assertEqual(
            "ElectricalSystem",
            result.element["name"],
        )


if __name__ == "__main__":
    unittest.main()
