from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "prototype"
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adapters.syson.importer import SysONImportError, SysONImporter
from adapters.syson.rest_adapter import SysONAdapterError, SysONRestAdapter, SysONRestConfig
from render_projection_html import render_html
from render_service import RenderService
from graph_ir import DiagramEdge, DiagramIR, DiagramNode
from layout import LayoutResult, NodeLayout, EdgeRoute
from selection import SelectionError, SemanticSelector
from view_state import FileViewStateStore, ViewIdentity


app = FastAPI(title="sysml-render", version="0.1.0")


def syson_url() -> str:
    return os.environ.get("SYSON_URL", "http://localhost:8080")


def syson_token() -> str | None:
    return os.environ.get("SYSON_TOKEN") or None


def view_state_store() -> FileViewStateStore:
    return FileViewStateStore(
        os.environ.get("SYSML_RENDER_STATE_DIR", ".sysml-render-state")
    )


class LayoutUpdate(BaseModel):
    project_id: str
    root_semantic_id: str
    profile: str
    node_id: str
    x: float
    y: float


def rebuild_ir(graph: dict) -> DiagramIR:
    return DiagramIR(
        root_semantic_id=graph["rootSemanticId"],
        profile=graph["profile"],
        nodes=[
            DiagramNode(
                id=node["id"],
                semantic_id=node["semantic_id"],
                label=node["label"],
                kind=node["kind"],
                parent_id=node.get("parent_id"),
                context_semantic_id=node.get("context_semantic_id"),
                derived=node.get("derived", False),
                metadata=node.get("metadata", {}),
            )
            for node in graph["nodes"]
        ],
        edges=[
            DiagramEdge(
                id=edge["id"],
                semantic_id=edge["semantic_id"],
                kind=edge["kind"],
                source=edge["source"],
                target=edge["target"],
                label=edge.get("label"),
                metadata=edge.get("metadata", {}),
            )
            for edge in graph["edges"]
        ],
    )


def rebuild_layout(layout: dict) -> LayoutResult:
    return LayoutResult(
        width=layout["width"],
        height=layout["height"],
        nodes=[
            NodeLayout(
                id=node["id"],
                x=node["x"],
                y=node["y"],
                width=node["width"],
                height=node["height"],
            )
            for node in layout["nodes"]
        ],
        edges=[
            EdgeRoute(
                id=edge["id"],
                points=[
                    (point["x"], point["y"])
                    for point in edge["points"]
                ],
            )
            for edge in layout["edges"]
        ],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/api/render")
def render_sysml(
    sysml_text: str = Form(""),
    file: UploadFile | None = File(None),
    project_id: str = Form(""),
    project_name: str = Form(""),
    select: str = Form(""),
    profile: str = Form(""),
):
    if file is not None and file.filename:
        raw = file.file.read()
        try:
            source_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Uploaded SysML file must be UTF-8 text.",
            ) from exc
        filename = file.filename
    else:
        source_text = sysml_text
        filename = "inline.sysml"

    if not source_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Provide SysML text or upload a .sysml file.",
        )

    if not filename.lower().endswith(".sysml"):
        filename = f"{filename}.sysml"

    if not project_name:
        stem = Path(filename).stem or "model"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        project_name = f"sysml-render-{stem}-{stamp}"

    try:
        importer = SysONImporter(
            syson_url(),
            token=syson_token(),
        )
        imported = importer.import_text(
            source_text,
            filename=filename,
            project_id=project_id or None,
            project_name=project_name,
        )

        adapter = SysONRestAdapter(
            SysONRestConfig(
                base_url=syson_url(),
                project_id=imported.project_id,
                token=syson_token(),
            )
        )
        snapshot = adapter.snapshot()
        selection = SemanticSelector(snapshot).resolve(
            select or None,
            profile=profile or None,
        )
        identity = ViewIdentity(
            project_id=imported.project_id,
            root_semantic_id=selection.element_id,
            profile=selection.profile,
        )
        overrides = view_state_store().load(identity.id)

        result = RenderService().render(
            snapshot,
            select=selection.element_id,
            profile=selection.profile,
            layout_overrides=overrides,
        )
    except (
        SysONImportError,
        SysONAdapterError,
        SelectionError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ir = rebuild_ir(result.graph)
    layout = rebuild_layout(result.layout)
    preview_html = render_html(ir, layout)

    return JSONResponse(
        {
            "projectId": imported.project_id,
            "editingContextId": imported.editing_context_id,
            "documentId": imported.document_id,
            "viewId": identity.id,
            "rootSemanticId": result.root_semantic_id,
            "profile": result.profile,
            "graph": result.graph,
            "layout": result.layout,
            "previewHtml": preview_html,
            "diagnostics": imported.import_report,
        }
    )


@app.post("/api/views/{view_id}/layout")
def update_layout(
    view_id: str,
    update: LayoutUpdate,
):
    identity = ViewIdentity(
        project_id=update.project_id,
        root_semantic_id=update.root_semantic_id,
        profile=update.profile,
    )
    if identity.id != view_id:
        raise HTTPException(
            status_code=409,
            detail="View identity does not match view id.",
        )

    payload = view_state_store().update_node(
        identity=identity,
        node_id=update.node_id,
        x=update.x,
        y=update.y,
        pinned=True,
    )
    return {
        "viewId": view_id,
        "node": payload["nodes"][update.node_id],
    }


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sysml-render</title>
<style>
  :root {
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #172033;
    background: #f5f7fb;
  }
  * { box-sizing: border-box; }
  body { margin: 0; height: 100vh; overflow: hidden; }
  header {
    height: 58px;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 20px;
    background: #fff;
    border-bottom: 1px solid #e3e8f0;
  }
  header strong { font-size: 17px; }
  header span { color: #718097; font-size: 12px; }
  main {
    height: calc(100vh - 58px);
    display: grid;
    grid-template-columns: 390px minmax(0, 1fr);
  }
  aside {
    padding: 18px;
    background: #fbfcfe;
    border-right: 1px solid #e3e8f0;
    overflow: auto;
  }
  .viewer { padding: 16px; min-width: 0; }
  iframe {
    width: 100%;
    height: 100%;
    border: 1px solid #dfe5ee;
    border-radius: 14px;
    background: #fff;
  }
  label { display: block; font-size: 12px; font-weight: 650; margin: 14px 0 7px; }
  textarea {
    width: 100%;
    min-height: 320px;
    resize: vertical;
    border: 1px solid #ccd5e2;
    border-radius: 10px;
    padding: 12px;
    font: 12px/1.5 "Cascadia Code", Consolas, monospace;
    background: #fff;
  }
  input, select {
    width: 100%;
    border: 1px solid #ccd5e2;
    border-radius: 9px;
    padding: 9px 10px;
    background: #fff;
  }
  button {
    width: 100%;
    margin-top: 16px;
    padding: 11px 14px;
    border: 0;
    border-radius: 10px;
    background: #243755;
    color: #fff;
    font-weight: 700;
    cursor: pointer;
  }
  button:disabled { opacity: .55; cursor: wait; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  #status {
    margin-top: 12px;
    padding: 10px;
    border-radius: 9px;
    background: #eef2f7;
    color: #536177;
    font-size: 12px;
    line-height: 1.45;
    white-space: pre-wrap;
  }
  .hint { color: #718097; font-size: 11px; line-height: 1.5; margin-top: 6px; }
</style>
</head>
<body>
<header>
  <strong>sysml-render</strong>
  <span>semantic model → automatic projection → editable view</span>
</header>
<main>
  <aside>
    <form id="render-form">
      <label>SysML 文本</label>
      <textarea name="sysml_text" spellcheck="false">package VehicleModel {
    part def Battery;
    part def Controller;
    part def ElectricalSystem {
        part battery : Battery;
        part controller : Controller;
    }
}</textarea>

      <label>或者导入 .sysml 文件</label>
      <input name="file" type="file" accept=".sysml,text/plain">

      <div class="row">
        <div>
          <label>选择元素</label>
          <input name="select" placeholder="自动 / ElectricalSystem">
        </div>
        <div>
          <label>视图类型</label>
          <select name="profile">
            <option value="">自动</option>
            <option value="package-overview">Package Overview</option>
            <option value="structure">Structure</option>
            <option value="requirements">Requirements</option>
          </select>
        </div>
      </div>

      <label>已有 SysON Project ID（可选）</label>
      <input name="project_id" placeholder="留空自动创建">
      <div class="hint">当前 Web MVP 使用 SysON 作为语义引擎。页面本身负责自动投影和连线，不使用 SysON 的手工 expose 工作流。</div>

      <button id="render-button" type="submit">导入并自动渲染</button>
      <div id="status">等待输入</div>
    </form>
  </aside>
  <section class="viewer">
    <iframe id="preview" title="SysML preview"></iframe>
  </section>
</main>
<script>
const form = document.getElementById("render-form");
const button = document.getElementById("render-button");
const status = document.getElementById("status");
const preview = document.getElementById("preview");
let currentRender = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = "正在导入 SysML 并构建语义图…";

  try {
    const response = await fetch("/api/render", {
      method: "POST",
      body: new FormData(form)
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || JSON.stringify(payload));
    }

    currentRender = payload;
    preview.srcdoc = payload.previewHtml;
    const projectInput = form.querySelector('[name="project_id"]');
    if (projectInput && !projectInput.value) projectInput.value = payload.projectId;
    status.textContent =
      "渲染完成\n" +
      "project: " + payload.projectId + "\n" +
      "view: " + payload.viewId + "\n" +
      "root: " + payload.rootSemanticId + "\n" +
      "profile: " + payload.profile + "\n" +
      "nodes: " + payload.graph.nodes.length + " / edges: " + payload.graph.edges.length;
  } catch (error) {
    status.textContent = "失败：\n" + error.message;
  } finally {
    button.disabled = false;
  }
});

window.addEventListener("message", async (event) => {
  const message = event.data;
  if (!currentRender || !message || message.type !== "sysml-render:layout-change") {
    return;
  }

  try {
    const response = await fetch(
      "/api/views/" + encodeURIComponent(currentRender.viewId) + "/layout",
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          project_id: currentRender.projectId,
          root_semantic_id: currentRender.rootSemanticId,
          profile: currentRender.profile,
          node_id: message.nodeId,
          x: message.x,
          y: message.y
        })
      }
    );
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "layout save failed");
    }
    status.textContent =
      status.textContent.split("\n布局：")[0] +
      "\n布局：已保存";
  } catch (error) {
    status.textContent =
      status.textContent.split("\n布局：")[0] +
      "\n布局：保存失败 - " + error.message;
  }
});
</script>
</body>
</html>
"""
