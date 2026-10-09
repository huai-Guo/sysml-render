from __future__ import annotations

from dataclasses import dataclass

from graph_ir import DiagramIR, DiagramNode
from projection import ProjectionEngine
from semantic_resolution import SemanticFeatureResolver
from semantic_commands import CreateConnectionCommand, SemanticCommandCompiler, SemanticCommandError


class ConnectionValidationError(ValueError):
    """The requested canvas edge cannot safely become a SysML connection."""


@dataclass(frozen=True)
class ConnectionPlan:
    parent_id: str
    source_node_id: str
    target_node_id: str
    source_path: tuple[str, ...]
    target_path: tuple[str, ...]
    textual_content: str
    name: str


def compile_canvas_connection(
    snapshot: dict,
    root_id: str,
    source_node_id: str,
    target_node_id: str,
    name: str,
) -> ConnectionPlan:
    """Prepare a semantic connection from two *visible* port projections.

    Projection IDs are view-local, not semantic endpoint identities. Resolve
    their displayed feature chains against the current semantic snapshot;
    reject ambiguous/hidden/non-port endpoints and preexisting edges.
    """
    elements = {item["id"]: item for item in snapshot.get("elements", [])}
    root = elements.get(root_id)
    if not root or root.get("kind") != "PartDefinition":
        raise ConnectionValidationError("Connection editing requires a PartDefinition view root.")

    diagram = ProjectionEngine(snapshot).project(root_id, "structure")
    nodes = {node.id: node for node in diagram.nodes}
    if source_node_id == target_node_id:
        raise ConnectionValidationError("A port cannot be connected to itself.")
    source = nodes.get(source_node_id)
    target = nodes.get(target_node_id)
    if not source or not target:
        raise ConnectionValidationError("Both endpoint nodes must be visible in the current view.")
    if source.kind != "PortUsage" or target.kind != "PortUsage":
        raise ConnectionValidationError("Connection endpoints must both be PortUsage nodes.")

    resolver = SemanticFeatureResolver(elements)
    source_path = _port_path(source, nodes, root_id)
    target_path = _port_path(target, nodes, root_id)
    for node, path in ((source, source_path), (target, target_path)):
        resolution = resolver.resolve(root_id, path)
        if not resolution or resolution.semantic_id != node.semantic_id:
            raise ConnectionValidationError(
                f"Endpoint {node.id!r} does not resolve to a unique semantic feature."
            )
        # The same semantic port definition can have multiple usages. A
        # feature path is authoritative; a semantic port ID alone is not.
        if not path or len(path) < 2:
            raise ConnectionValidationError("Choose a port in a concrete PartUsage context.")

    if any(
        (edge.source == source.id and edge.target == target.id)
        or (edge.source == target.id and edge.target == source.id)
        for edge in diagram.edges
    ):
        raise ConnectionValidationError("A semantic connection already exists between these ports.")

    if any(
        rel.get("ownerId") == root_id
        and rel.get("name") == name
        for rel in snapshot.get("relationships", [])
    ):
        raise ConnectionValidationError(f"A relationship named {name!r} already exists in this owner.")

    try:
        command = CreateConnectionCommand(
            parent_id=root_id,
            name=name,
            source_path=source_path,
            target_path=target_path,
        )
        compiled = SemanticCommandCompiler().compile(command)
    except SemanticCommandError as exc:
        raise ConnectionValidationError(str(exc)) from exc

    return ConnectionPlan(
        parent_id=root_id,
        source_node_id=source.id,
        target_node_id=target.id,
        source_path=source_path,
        target_path=target_path,
        textual_content=compiled.textual_content,
        name=name,
    )


def _port_path(node: DiagramNode, nodes: dict[str, DiagramNode], root_id: str) -> tuple[str, ...]:
    pieces: list[str] = []
    current = node
    visited: set[str] = set()
    while current.id != root_id:
        if current.id in visited or current.parent_id is None:
            raise ConnectionValidationError("Selected port is outside the requested semantic root.")
        visited.add(current.id)
        pieces.append(current.label)
        parent = nodes.get(current.parent_id)
        if parent is None:
            raise ConnectionValidationError("Missing diagram parent on selected feature chain.")
        current = parent
    pieces.reverse()
    return tuple(pieces)


def connection_visible(
    snapshot: dict,
    plan: ConnectionPlan,
) -> bool:
    graph: DiagramIR = ProjectionEngine(snapshot).project(plan.parent_id, "structure")
    return any(
        edge.source == plan.source_node_id and edge.target == plan.target_node_id
        for edge in graph.edges
    )


def connection_in_semantic_snapshot(snapshot: dict, plan: ConnectionPlan) -> bool:
    return any(
        rel.get("ownerId") == plan.parent_id
        and rel.get("kind") == "ConnectionUsage"
        and rel.get("name") == plan.name
        for rel in snapshot.get("relationships", [])
    )
