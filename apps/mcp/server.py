from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mcp.server import MCPServer
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "prototype"
SCRIPTS = ROOT / "scripts"
for path in (ROOT, PROTOTYPE, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from adapters.syson.importer import SysONImporter
from adapters.syson.rest_adapter import SysONRestAdapter, SysONRestConfig
from graph_ir import DiagramEdge, DiagramIR, DiagramNode
from layout import EdgeRoute, LayoutResult, NodeLayout
from render_projection_html import render_html
from render_service import RenderService
from selection import SemanticSelector
from view_state import FileViewStateStore, ViewIdentity


ProjectionProfileName = Literal[
    "package-overview",
    "structure",
    "requirements",
]


class RenderToolResult(BaseModel):
    project_id: str = Field(description="SysON project containing the semantic model.")
    view_id: str = Field(description="Stable renderer view identity.")
    editing_context_id: str | None = Field(
        default=None,
        description="SysON editing context when the tool imported the model.",
    )
    document_id: str | None = Field(
        default=None,
        description="Imported SysML document identifier when applicable.",
    )
    root_semantic_id: str = Field(
        description="Semantic element used as the root of this view.",
    )
    profile: str = Field(description="Projection profile used to synthesize the diagram.")
    graph: dict[str, Any] = Field(
        description="Renderer-owned Diagram IR: semantic nodes and edges."
    )
    layout: dict[str, Any] = Field(
        description="Initial editable presentation layout."
    )
    preview_html: str = Field(
        description=(
            "Self-contained interactive HTML preview. Nodes can be dragged and "
            "semantic IDs can be inspected."
        )
    )
    diagnostics: Any = Field(
        default=None,
        description="Import diagnostics reported by the semantic engine, when available.",
    )


class SemanticElementResult(BaseModel):
    project_id: str
    element_id: str
    element: dict[str, Any]


class LayoutCommandResult(BaseModel):
    project_id: str
    view_id: str
    node_id: str
    x: float
    y: float
    pinned: bool = True




mcp = MCPServer(
    "sysml-render",
    version="0.1.0",
)


def _syson_url() -> str:
    return os.environ.get("SYSON_URL", "http://localhost:8080")


def _syson_token() -> str | None:
    return os.environ.get("SYSON_TOKEN") or None


def _adapter(project_id: str) -> SysONRestAdapter:
    return SysONRestAdapter(
        SysONRestConfig(
            base_url=_syson_url(),
            project_id=project_id,
            token=_syson_token(),
        )
    )


def _view_state_store() -> FileViewStateStore:
    return FileViewStateStore(
        os.environ.get("SYSML_RENDER_STATE_DIR", ".sysml-render-state")
    )


def _rebuild_ir(graph: dict[str, Any]) -> DiagramIR:
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


def _rebuild_layout(layout: dict[str, Any]) -> LayoutResult:
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


def _render_project(
    project_id: str,
    *,
    select: str | None = None,
    profile: ProjectionProfileName | None = None,
    editing_context_id: str | None = None,
    document_id: str | None = None,
    diagnostics: Any = None,
) -> RenderToolResult:
    snapshot = _adapter(project_id).snapshot()
    selection = SemanticSelector(snapshot).resolve(
        select,
        profile=profile,
    )
    identity = ViewIdentity(
        project_id=project_id,
        root_semantic_id=selection.element_id,
        profile=selection.profile,
    )
    overrides = _view_state_store().load(identity.id)

    result = RenderService().render(
        snapshot,
        select=selection.element_id,
        profile=selection.profile,
        layout_overrides=overrides,
    )
    preview = render_html(
        _rebuild_ir(result.graph),
        _rebuild_layout(result.layout),
    )
    return RenderToolResult(
        project_id=project_id,
        view_id=identity.id,
        editing_context_id=editing_context_id,
        document_id=document_id,
        root_semantic_id=result.root_semantic_id,
        profile=result.profile,
        graph=result.graph,
        layout=result.layout,
        preview_html=preview,
        diagnostics=diagnostics,
    )


@mcp.tool()
def render_sysml(
    sysml_text: str,
    select: str | None = None,
    profile: ProjectionProfileName | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
    filename: str = "model.sysml",
) -> RenderToolResult:
    """Import SysML v2 text and automatically synthesize an editable diagram.

    Existing SysML semantic relationships are converted into visual edges
    automatically. The renderer never invents a semantic relationship just to
    make the picture look connected. If project_id is omitted, a new SysON
    project is created.
    """
    if not project_name:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        project_name = f"sysml-render-{Path(filename).stem}-{stamp}"

    imported = SysONImporter(
        _syson_url(),
        token=_syson_token(),
    ).import_text(
        sysml_text,
        filename=filename,
        project_id=project_id,
        project_name=project_name,
    )

    return _render_project(
        imported.project_id,
        select=select,
        profile=profile,
        editing_context_id=imported.editing_context_id,
        document_id=imported.document_id,
        diagnostics=imported.import_report,
    )


@mcp.tool()
def render_project(
    project_id: str,
    select: str | None = None,
    profile: ProjectionProfileName | None = None,
) -> RenderToolResult:
    """Render an existing SysON project with automatic semantic projection."""
    return _render_project(
        project_id,
        select=select,
        profile=profile,
    )


@mcp.tool()
def get_view(
    project_id: str,
    root_semantic_id: str,
    profile: ProjectionProfileName,
) -> RenderToolResult:
    """Read a renderer view, including persisted human/Agent layout edits."""
    return _render_project(
        project_id,
        select=root_semantic_id,
        profile=profile,
    )


@mcp.tool()
def apply_layout_command(
    project_id: str,
    root_semantic_id: str,
    profile: ProjectionProfileName,
    node_id: str,
    x: float,
    y: float,
) -> LayoutCommandResult:
    """Move/pin one visual node without changing SysML semantics."""
    identity = ViewIdentity(
        project_id=project_id,
        root_semantic_id=root_semantic_id,
        profile=profile,
    )
    payload = _view_state_store().update_node(
        identity=identity,
        node_id=node_id,
        x=x,
        y=y,
        pinned=True,
    )
    node = payload["nodes"][node_id]
    return LayoutCommandResult(
        project_id=project_id,
        view_id=identity.id,
        node_id=node_id,
        x=node["x"],
        y=node["y"],
        pinned=node["pinned"],
    )


@mcp.tool()
def get_semantic_element(
    project_id: str,
    element_id: str,
) -> SemanticElementResult:
    """Read one semantic SysML element from the configured SysON backend."""
    element = _adapter(project_id).fetch_element(element_id)
    return SemanticElementResult(
        project_id=project_id,
        element_id=element_id,
        element=element,
    )


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )
    else:
        mcp.run()
