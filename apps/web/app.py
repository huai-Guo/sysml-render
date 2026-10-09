from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
import re
from typing import Literal

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
from adapters.syson.semantic_writer import SysONSemanticWriter, SysONSemanticWriterError
from adapters.syson.textual_writer import SysONTextualWriter, SysONTextualWriteError
from connection_editing import (
    ConnectionValidationError, compile_canvas_connection,
    connection_visible, connection_in_semantic_snapshot,
)
from prototype.semantic_commands import (RenameElementCommand, DeleteElementCommand, CreateOwnedElementCommand)
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


class ProjectRenderRequest(BaseModel):
    select: str | None = None
    profile: str | None = None


class SemanticEditRequest(BaseModel):
    kind: Literal["rename_element", "create_owned_element", "delete_element", "create_connection"]
    element_id: str | None = None
    owner_id: str | None = None
    new_name: str | None = None
    element_type: str | None = None
    confirmed: bool = False
    root_element_id: str | None = None
    source_node_id: str | None = None
    target_node_id: str | None = None


CREATABLE_TYPES = frozenset({
    "PartDefinition", "PortDefinition", "ItemDefinition",
    "RequirementDefinition", "Package",
})
DELETABLE_TYPES = frozenset({
    "PartDefinition", "PortDefinition", "ItemDefinition",
    "RequirementDefinition",
})
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def semantic_writes_enabled() -> bool:
    return os.environ.get("SYSON_ENABLE_SEMANTIC_WRITES") == "1"


def _semantic_snapshot(project_id: str) -> dict:
    return SysONRestAdapter(
        SysONRestConfig(
            base_url=syson_url(),
            project_id=project_id,
            token=syson_token(),
        )
    ).snapshot()


def _render_existing(
    project_id: str,
    *,
    select: str | None = None,
    profile: str | None = None,
    editing_context_id: str | None = None,
    document_id: str | None = None,
    diagnostics: object = None,
) -> dict:
    snapshot = _semantic_snapshot(project_id)
    selection = SemanticSelector(snapshot).resolve(select, profile=profile)
    identity = ViewIdentity(
        project_id=project_id,
        root_semantic_id=selection.element_id,
        profile=selection.profile,
    )
    result = RenderService().render(
        snapshot,
        select=selection.element_id,
        profile=selection.profile,
        layout_overrides=view_state_store().load(identity.id),
    )
    return {
        "projectId": project_id,
        "editingContextId": editing_context_id,
        "documentId": document_id,
        "viewId": identity.id,
        "rootSemanticId": result.root_semantic_id,
        "profile": result.profile,
        "modelCommitId": snapshot.get("source", {}).get("commitId"),
        "graph": result.graph,
        "layout": result.layout,
        "previewHtml": render_html(rebuild_ir(result.graph), rebuild_layout(result.layout)),
        "diagnostics": diagnostics,
    }


def _validate_name(name: str | None) -> str:
    candidate = (name or "").strip()
    if not _NAME.fullmatch(candidate):
        raise HTTPException(
            422, "Name must be a simple SysML identifier (letters, digits, underscores)."
        )
    return candidate


def _require_element(elements: dict, element_id: str | None) -> dict:
    element = elements.get(element_id)
    if element is None:
        raise HTTPException(404, f"Semantic element not found: {element_id}")
    return element


@app.get("/api/capabilities")
def capabilities():
    return {
        "semanticWritesEnabled": semantic_writes_enabled(),
        "allowedCreateTypes": sorted(CREATABLE_TYPES),
        "semanticWritesExperimental": True,
    }


@app.post("/api/projects/{project_id}/render")
def render_existing_project(project_id: str, request: ProjectRenderRequest):
    try:
        return _render_existing(
            project_id,
            select=request.select,
            profile=request.profile,
        )
    except (SysONAdapterError, SelectionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/projects/{project_id}/semantic-commands")
def apply_semantic_command(project_id: str, request: SemanticEditRequest):
    if not semantic_writes_enabled():
        raise HTTPException(
            403,
            "Semantic writes are experimental and disabled. "
            "Set SYSON_ENABLE_SEMANTIC_WRITES=1 only against a disposable SysON project.",
        )

    snapshot = _semantic_snapshot(project_id)
    elements = {item["id"]: item for item in snapshot.get("elements", [])}
    if request.kind == "create_connection":
        if not (request.root_element_id and request.source_node_id and request.target_node_id):
            raise HTTPException(422, "Connection requires root and two port node IDs.")
        name = _validate_name(request.new_name)
        try:
            plan = compile_canvas_connection(
                snapshot,
                request.root_element_id,
                request.source_node_id,
                request.target_node_id,
                name,
            )
        except ConnectionValidationError as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            editing_context_id = SysONImporter(
                syson_url(), token=syson_token()
            ).fetch_editing_context_id(project_id)
            insertion = SysONTextualWriter(
                syson_url(), token=syson_token()
            ).insert(
                editing_context_id=editing_context_id,
                owner_element_id=plan.parent_id,
                textual_content=plan.textual_content,
            )
        except (SysONImportError, SysONTextualWriteError) as exc:
            raise HTTPException(502, str(exc)) from exc

        try:
            refreshed = _semantic_snapshot(project_id)
            model_observed = connection_in_semantic_snapshot(refreshed, plan)
            visible = connection_visible(refreshed, plan)
        except (SysONAdapterError, ValueError):
            # SysON accepted the write, but post-write reading failed. Report
            # partial success; the client must not silently retry the insert.
            model_observed = False
            visible = False
        return {
            "projectId": project_id,
            "kind": "create_connection",
            "sourcePath": list(plan.source_path),
            "targetPath": list(plan.target_path),
            "textualContent": plan.textual_content,
            "acknowledged": insertion.acknowledged,
            "observedInModel": model_observed,
            "edgeVisible": visible,
            "verified": model_observed and visible,
            "messages": list(insertion.messages),
            "refreshRequired": True,
        }

    if request.kind == "rename_element":
        item = _require_element(elements, request.element_id)
        name = _validate_name(request.new_name)
        if item["name"] == name:
            raise HTTPException(422, "New name is identical to the current name.")
        command = RenameElementCommand(element_id=item["id"], new_name=name)
    elif request.kind == "create_owned_element":
        owner = _require_element(elements, request.owner_id)
        if owner["kind"] not in {"Package", "PartDefinition", "LibraryPackage"}:
            raise HTTPException(422, "Choose a Package or PartDefinition owner.")
        if request.element_type not in CREATABLE_TYPES:
            raise HTTPException(422, "Unsupported element type.")
        name = _validate_name(request.new_name)
        if any(
            child.get("parentId") == owner["id"] and child["name"] == name
            for child in elements.values()
        ):
            raise HTTPException(409, "An element with that name already exists here.")
        command = CreateOwnedElementCommand(
            owner_id=owner["id"], element_type=request.element_type, name=name
        )
    else:
        item = _require_element(elements, request.element_id)
        if not request.confirmed:
            raise HTTPException(409, "Deletion requires explicit confirmation.")
        if item["kind"] not in DELETABLE_TYPES:
            raise HTTPException(422, "Only unreferenced leaf definitions may be deleted.")
        if any(child.get("parentId") == item["id"] for child in elements.values()):
            raise HTTPException(409, "Cannot delete an element that owns children.")
        if any(
            ref.get("typeRef") == item["id"]
            for ref in elements.values()
        ):
            raise HTTPException(409, "Cannot delete a type referenced by usages.")
        if any(
            item["id"] in (
                relationship.get("sourceId"),
                relationship.get("targetId"),
                relationship.get("ownerId"),
                *relationship.get("relatedFeatureIds", []),
            )
            for relationship in snapshot.get("relationships", [])
        ):
            raise HTTPException(409, "Cannot delete an element involved in relationships.")
        command = DeleteElementCommand(element_id=item["id"])

    try:
        result = SysONSemanticWriter(
            syson_url(), project_id, token=syson_token()
        ).apply(command)
    except (SysONSemanticWriterError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc

    return {
        "projectId": project_id,
        "kind": result.command,
        "elementId": result.element_id,
        "membershipId": result.membership_id,
        "commitId": result.commit_id,
        "verified": result.verified,
        "refreshRequired": True,
    }


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

        return JSONResponse(
            _render_existing(
                imported.project_id,
                select=select or None,
                profile=profile or None,
                editing_context_id=imported.editing_context_id,
                document_id=imported.document_id,
                diagnostics=imported.import_report,
            )
        )
    except (
        SysONImportError,
        SysONAdapterError,
        SelectionError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
  .semantic-panel { margin-top: 18px; border-top: 1px solid #dfe5ee; padding-top: 16px; }
  .semantic-panel h2 { font-size: 15px; margin: 0 0 10px; }
  .semantic-panel .secondary { background: #eaf0f8; color: #203654; }
  .semantic-panel .danger { background: #fff0f0; color: #a92828; border: 1px solid #f0b7b7; }
  .semantic-panel .summary { font: 12px/1.5 Consolas, monospace; overflow-wrap: anywhere; color: #50607a; }
  .semantic-panel [hidden] { display: none; }
  .semantic-panel button { margin-top: 9px; }
  .semantic-panel fieldset { border: 0; padding: 0; margin: 12px 0; }
  .semantic-panel fieldset:disabled { opacity: .55; }

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
    <section class="semantic-panel" aria-label="语义编辑">
      <h2>语义编辑</h2>
      <p id="editor-mode" class="hint">检查写入能力…</p>
      <button type="button" id="refresh-project" class="secondary" disabled>重新读取当前项目（不重复导入）</button>
      <div id="selected-element" class="summary">点击图中的节点选择元素。</div>
      <fieldset id="semantic-actions" disabled>
        <label for="rename-value">修改元素名称</label>
        <input id="rename-value" placeholder="例如 BackupBattery">
        <button type="button" id="rename-element">保存语义名称</button>
        <label for="new-element-kind">在选中容器内创建</label>
        <select id="new-element-kind">
          <option value="PartDefinition">PartDefinition</option>
          <option value="PortDefinition">PortDefinition</option>
          <option value="ItemDefinition">ItemDefinition</option>
          <option value="RequirementDefinition">RequirementDefinition</option>
          <option value="Package">Package</option>
        </select>
        <input id="new-element-name" placeholder="新元素名称">
        <button type="button" id="create-element" class="secondary">创建子元素</button>
        <button type="button" id="delete-element" class="danger">删除选中元素（需确认）</button>
      </fieldset>
      <fieldset id="connection-actions" disabled>
        <label>创建语义 Connection（仅结构图 Port）</label>
        <p id="connection-pair" class="summary">先点击 Port，再设置源端口与目标端口。</p>
        <div class="row">
          <button type="button" class="secondary" id="set-source-port">设为源 Port</button>
          <button type="button" class="secondary" id="set-target-port">设为目标 Port</button>
        </div>
        <label for="connection-name">Connection 名称</label>
        <input id="connection-name" placeholder="例如 batteryToMotor">
        <button type="button" id="create-connection" disabled>创建语义连接</button>
      </fieldset>
    </section>
  </aside>
  <section class="viewer">
    <iframe id="preview" title="SysML preview" sandbox="allow-scripts"></iframe>
  </section>
</main>
<script>
const form = document.getElementById("render-form");
const button = document.getElementById("render-button");
const status = document.getElementById("status");
const preview = document.getElementById("preview");
let currentRender = null;
let selectedNode = null;
let writesEnabled = false;
let sourcePort = null;
let targetPort = null;
const connectionActions = document.getElementById("connection-actions");
const sourceButton = document.getElementById("set-source-port");
const targetButton = document.getElementById("set-target-port");
const connectButton = document.getElementById("create-connection");
const connectionPair = document.getElementById("connection-pair");
const connectionName = document.getElementById("connection-name");

function updateConnectionControls() {
  const isPort = writesEnabled && currentRender?.profile === "structure" &&
    selectedNode?.kind === "PortUsage";
  connectionActions.disabled = !writesEnabled || currentRender?.profile !== "structure";
  sourceButton.disabled = !isPort;
  targetButton.disabled = !isPort;
  connectButton.disabled = !sourcePort || !targetPort || !writesEnabled ||
    sourcePort.id === targetPort.id;
  connectionPair.textContent =
    "源：" + (sourcePort?.label || "未选") +
    "  →  目标：" + (targetPort?.label || "未选");
}

const actions = document.getElementById("semantic-actions");
const selectedLabel = document.getElementById("selected-element");
const modeLabel = document.getElementById("editor-mode");
const refreshButton = document.getElementById("refresh-project");
const renameValue = document.getElementById("rename-value");

async function requestJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || JSON.stringify(result));
  return result;
}

function setRender(payload) {
  currentRender = payload;
  selectedNode = null;
  sourcePort = null;
  targetPort = null;
  preview.srcdoc = payload.previewHtml;
  updateConnectionControls();
  actions.disabled = true;
  selectedLabel.textContent = "点击图中的节点选择元素。";
  refreshButton.disabled = false;
  status.textContent =
    "渲染完成\nproject: " + payload.projectId +
    "\nroot: " + payload.rootSemanticId +
    "\nprofile: " + payload.profile +
    "\nnodes: " + payload.graph.nodes.length +
    " / edges: " + payload.graph.edges.length;
}

async function refreshProject() {
  if (!currentRender) return;
  const payload = await requestJSON(
    "/api/projects/" + encodeURIComponent(currentRender.projectId) + "/render",
    {select: currentRender.rootSemanticId, profile: currentRender.profile}
  );
  setRender(payload);
}

async function applySemantic(command) {
  if (!currentRender || !selectedNode || !writesEnabled || selectedNode.derived) return;
  const projectId = currentRender.projectId;
  status.textContent = "正在提交语义修改…";
  const result = await requestJSON(
    "/api/projects/" + encodeURIComponent(projectId) + "/semantic-commands",
    command
  );
  status.textContent = "写入已验证；正在重新读取语义模型…";
  try {
    await refreshProject();
    status.textContent += "\n语义操作：" + result.kind + " 已验证";
  } catch (error) {
    status.textContent = "语义修改已提交，但重新渲染失败：" + error.message;
  }
}

async function loadCapabilities() {
  try {
    const response = await fetch("/api/capabilities");
    const capabilities = await response.json();
    writesEnabled = capabilities.semanticWritesEnabled === true;
    updateConnectionControls();
    modeLabel.textContent = writesEnabled
      ? "实验模式已开启。请仅在可丢弃的 SysON 测试项目中进行写操作。"
      : "语义写入默认关闭；只读图和布局编辑仍可使用。";
  } catch (error) {
    modeLabel.textContent = "无法获取语义编辑能力：" + error.message;
  }
}
loadCapabilities();

function showError(error) {
  status.textContent = "操作失败：" + error.message;
}

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  try { await refreshProject(); } catch (error) { showError(error); }
  finally { refreshButton.disabled = false; }
});

sourceButton.addEventListener("click", () => {
  if (selectedNode?.kind !== "PortUsage") return;
  sourcePort = {...selectedNode};
  updateConnectionControls();
});
targetButton.addEventListener("click", () => {
  if (selectedNode?.kind !== "PortUsage") return;
  targetPort = {...selectedNode};
  updateConnectionControls();
});
connectButton.addEventListener("click", async () => {
  if (!currentRender || !sourcePort || !targetPort || !writesEnabled) return;
  connectButton.disabled = true;
  const projectId = currentRender.projectId;
  status.textContent = "正在提交语义 Connection…";
  try {
    const result = await requestJSON(
      "/api/projects/" + encodeURIComponent(projectId) + "/semantic-commands",
      {
        kind: "create_connection",
        root_element_id: currentRender.rootSemanticId,
        source_node_id: sourcePort.id,
        target_node_id: targetPort.id,
        new_name: connectionName.value
      }
    );
    if (!result.acknowledged) {
      status.textContent = "SysON 未确认插入。";
      return;
    }
    try {
      await refreshProject();
      status.textContent = result.verified
        ? "连接已写入 SysML 并在图上显示。"
        : "SysON 已确认插入，但新连接尚未同时通过语义读取和图形校验；请检查模型，不要直接重试。";
    } catch (error) {
      status.textContent = "SysON 已确认插入，但图形刷新失败：" + error.message;
    }
  } catch (error) {
    showError(error);
  } finally {
    updateConnectionControls();
  }
});

document.getElementById("rename-element").addEventListener("click", async () => {
  if (!selectedNode) return;
  try {
    await applySemantic({
      kind: "rename_element",
      element_id: selectedNode.semanticId,
      new_name: renameValue.value
    });
  } catch (error) { showError(error); }
});
document.getElementById("create-element").addEventListener("click", async () => {
  if (!selectedNode) return;
  try {
    await applySemantic({
      kind: "create_owned_element",
      owner_id: selectedNode.semanticId,
      element_type: document.getElementById("new-element-kind").value,
      new_name: document.getElementById("new-element-name").value
    });
  } catch (error) { showError(error); }
});
document.getElementById("delete-element").addEventListener("click", async () => {
  if (!selectedNode) return;
  const entered = window.prompt(
    "此操作会修改 SysML 语义。输入元素名称确认删除：" + selectedNode.label
  );
  if (entered !== selectedNode.label) return;
  try {
    await applySemantic({
      kind: "delete_element",
      element_id: selectedNode.semanticId,
      confirmed: true
    });
  } catch (error) { showError(error); }
});

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

    setRender(payload);
    const projectInput = form.querySelector('[name="project_id"]');
    if (projectInput && !projectInput.value) projectInput.value = payload.projectId;
  } catch (error) {
    status.textContent = "失败：\n" + error.message;
  } finally {
    button.disabled = false;
  }
});

window.addEventListener("message", async (event) => {
  if (event.source !== preview.contentWindow || !currentRender) return;
  const message = event.data;
  if (!message || typeof message !== "object") return;

  if (message.type === "sysml-render:select-node") {
    const candidate = currentRender.graph.nodes.find(n => n.id === message.node?.id);
    if (!candidate) return;
    selectedNode = {
      id: candidate.id,
      semanticId: candidate.semantic_id,
      label: candidate.label,
      kind: candidate.kind,
      derived: candidate.derived
    };
    renameValue.value = candidate.label;
    selectedLabel.textContent =
      candidate.label + " · " + candidate.kind + "\n" + candidate.semantic_id +
      (candidate.derived ? "\n类型投影节点：不可直接语义编辑" : "");
    actions.disabled = !writesEnabled || Boolean(candidate.derived);
    updateConnectionControls();
    return;
  }

  if (message.type !== "sysml-render:layout-change" ||
      !currentRender.graph.nodes.some(n => n.id === message.nodeId)) return;

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
