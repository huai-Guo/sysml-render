import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sysml_render.api import app
from sysml_render.svg import RenderRequest, render_svg


def payload():
    return {"source_sha256": "a" * 64, "semantic_model": {"schema_version": "1", "entities": [
        {"id": "a", "kind": "Package", "name": 'A<script>alert(1)</script>"'},
        {"id": "b", "kind": "PartDefinition", "name": "B", "owner_id": "a"},
    ], "relations": [{"id": "r", "kind": "ownership", "source": {"id": "a"}, "target": {"id": "b"}}]}}


def test_svg_escapes_labels_and_preserves_edges():
    result = render_svg(RenderRequest(**payload()))
    root = ET.fromstring(result["svg"])
    assert root.tag.endswith("svg")
    assert "<script>" not in result["svg"]
    assert result["coverage"]["displayed_relations"] == 1
    empty = payload()
    empty["semantic_model"]["relations"] = []
    assert render_svg(RenderRequest(**empty))["coverage"]["displayed_relations"] == 0


def test_duplicates_cycles_and_missing_references_rejected():
    for mutation in ("duplicate", "cycle", "missing", "chain"):
        data = payload()
        model = data["semantic_model"]
        if mutation == "duplicate":
            model["entities"].append(model["entities"][0])
        elif mutation == "cycle":
            model["entities"][0]["owner_id"] = "b"
        elif mutation == "chain":
            model["entities"][0]["chaining_features"] = [{"id": "absent"}]
        else:
            model["relations"][0]["target"]["id"] = "absent"
        with pytest.raises(ValidationError):
            RenderRequest(**data)


def test_authentication_and_body_limit(monkeypatch):
    monkeypatch.setenv("SYSML_RENDER_SERVICE_TOKEN", "x" * 32)
    with TestClient(app) as client:
        assert client.post("/v1/render", json=payload()).status_code == 401
        response = client.post("/v1/render", json=payload(), headers={"Authorization": "Bearer " + "x" * 32})
        assert response.status_code == 200
        assert response.json()["source_sha256"] == "a" * 64
        assert client.post("/v1/render", content=b"x" * (4 * 1024 * 1024 + 1)).status_code == 413


def test_anonymous_semantic_feature_paths_materialize_connections():
    data = payload()
    data["semantic_model"]["entities"].extend([
        {"id": "path1", "kind": "Feature", "owner_id": "a", "chaining_features": [{"id": "a", "label": "battery"}, {"id": "b", "label": "output"}]},
        {"id": "path2", "kind": "Feature", "owner_id": "a", "chaining_features": [{"id": "a", "label": "motor"}, {"id": "b", "label": "input"}]},
    ])
    data["semantic_model"]["relations"].append({"id": "conn", "kind": "ConnectionUsage", "source": {"id": "path1"}, "target": {"id": "path2"}})
    result = render_svg(RenderRequest(**data))
    assert "battery.output" in result["svg"] and "motor.input" in result["svg"]
    assert result["coverage"]["displayed_relations"] == 2
    assert result["coverage"]["projected_feature_paths"] == 2
