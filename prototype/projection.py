from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graph_ir import DiagramEdge, DiagramIR, DiagramNode


@dataclass(frozen=True)
class ProjectionProfile:
    name: str
    node_kinds: frozenset[str]
    edge_kinds: frozenset[str]
    max_depth: int
    materialize_typed_ports: bool = False


PROFILES: dict[str, ProjectionProfile] = {
    "package-overview": ProjectionProfile(
        name="package-overview",
        node_kinds=frozenset(
            {
                "Package",
                "PartDefinition",
                "RequirementDefinition",
            }
        ),
        edge_kinds=frozenset(),
        max_depth=2,
    ),
    "structure": ProjectionProfile(
        name="structure",
        node_kinds=frozenset(
            {
                "PartDefinition",
                "PartUsage",
                "PortUsage",
            }
        ),
        edge_kinds=frozenset({"ConnectionUsage"}),
        max_depth=2,
        materialize_typed_ports=True,
    ),
    "requirements": ProjectionProfile(
        name="requirements",
        node_kinds=frozenset(
            {
                "RequirementDefinition",
                "RequirementUsage",
                "PartUsage",
            }
        ),
        edge_kinds=frozenset(
            {
                "SatisfyRequirementUsage",
                "RequirementVerificationMembership",
                "Dependency",
            }
        ),
        max_depth=3,
    ),
}


class SemanticIndex:
    def __init__(self, snapshot: dict[str, Any]):
        self.snapshot = snapshot
        self.elements = {element["id"]: element for element in snapshot["elements"]}
        self.relationships = snapshot.get("relationships", [])

        self._children: dict[str | None, list[dict[str, Any]]] = {}
        for element in snapshot["elements"]:
            self._children.setdefault(element.get("parentId"), []).append(element)

    def element(self, element_id: str) -> dict[str, Any]:
        try:
            return self.elements[element_id]
        except KeyError as exc:
            raise ValueError(f"unknown semantic element: {element_id}") from exc

    def children(self, parent_id: str) -> list[dict[str, Any]]:
        return list(self._children.get(parent_id, []))

    def child_named(self, parent_id: str, name: str) -> dict[str, Any] | None:
        for child in self.children(parent_id):
            if child["name"] == name:
                return child
        return None


class ProjectionEngine:
    """Transforms a semantic model snapshot into a renderer-owned Diagram IR.

    The engine never creates semantic relationships. It only materializes
    relationships already present in the snapshot.
    """

    def __init__(self, snapshot: dict[str, Any]):
        self.index = SemanticIndex(snapshot)

    def project(self, root_id: str, profile_name: str) -> DiagramIR:
        if profile_name not in PROFILES:
            raise ValueError(f"unknown projection profile: {profile_name}")

        profile = PROFILES[profile_name]
        root = self.index.element(root_id)
        ir = DiagramIR(root_semantic_id=root_id, profile=profile.name)

        ir.nodes.append(
            DiagramNode(
                id=root_id,
                semantic_id=root_id,
                label=root["name"],
                kind=root["kind"],
                parent_id=None,
                metadata={"root": True},
            )
        )

        self._collect_owned_nodes(
            ir=ir,
            semantic_parent_id=root_id,
            diagram_parent_id=root_id,
            profile=profile,
            depth=0,
        )

        if profile.materialize_typed_ports:
            self._materialize_typed_ports(ir)

        self._materialize_semantic_edges(ir, root_id, profile)
        return ir

    def _collect_owned_nodes(
        self,
        *,
        ir: DiagramIR,
        semantic_parent_id: str,
        diagram_parent_id: str,
        profile: ProjectionProfile,
        depth: int,
    ) -> None:
        if depth >= profile.max_depth:
            return

        for child in self.index.children(semantic_parent_id):
            should_include = child["kind"] in profile.node_kinds

            next_diagram_parent = diagram_parent_id
            if should_include:
                ir.nodes.append(
                    DiagramNode(
                        id=child["id"],
                        semantic_id=child["id"],
                        label=child["name"],
                        kind=child["kind"],
                        parent_id=diagram_parent_id,
                        metadata={
                            "typeRef": child.get("typeRef"),
                            "semanticParentId": semantic_parent_id,
                        },
                    )
                )
                next_diagram_parent = child["id"]

            # Traverse through filtered semantic elements as well. A profile may
            # hide an intermediate semantic concept while still showing its
            # descendants.
            self._collect_owned_nodes(
                ir=ir,
                semantic_parent_id=child["id"],
                diagram_parent_id=next_diagram_parent,
                profile=profile,
                depth=depth + 1,
            )

    def _materialize_typed_ports(self, ir: DiagramIR) -> None:
        """Project a PartUsage's typed ports as context-specific visual nodes.

        Example:
            part battery : Battery

        Battery owns semantic port "powerOut". In a structure view we need the
        visual endpoint "battery.powerOut", while preserving that the semantic
        port identity comes from Battery::powerOut.
        """

        existing_ids = {node.id for node in ir.nodes}
        part_nodes = [node for node in list(ir.nodes) if node.kind == "PartUsage"]

        for part_node in part_nodes:
            part = self.index.element(part_node.semantic_id)
            type_ref = part.get("typeRef")
            if not type_ref or type_ref not in self.index.elements:
                continue

            for typed_feature in self.index.children(type_ref):
                if typed_feature["kind"] != "PortUsage":
                    continue

                projection_id = self._typed_feature_node_id(
                    part_node.semantic_id,
                    typed_feature["id"],
                )
                if projection_id in existing_ids:
                    continue

                ir.nodes.append(
                    DiagramNode(
                        id=projection_id,
                        semantic_id=typed_feature["id"],
                        context_semantic_id=part_node.semantic_id,
                        label=typed_feature["name"],
                        kind=typed_feature["kind"],
                        parent_id=part_node.id,
                        derived=True,
                        metadata={
                            "projectionKind": "typed-feature",
                            "typeOwnerId": type_ref,
                        },
                    )
                )
                existing_ids.add(projection_id)

    def _materialize_semantic_edges(
        self,
        ir: DiagramIR,
        root_id: str,
        profile: ProjectionProfile,
    ) -> None:
        visible_node_ids = {node.id for node in ir.nodes}

        for relationship in self.index.relationships:
            if relationship["kind"] not in profile.edge_kinds:
                continue
            if relationship.get("ownerId") != root_id:
                continue

            source = self._resolve_relationship_endpoint(
                ir,
                root_id,
                relationship,
                "source",
            )
            target = self._resolve_relationship_endpoint(
                ir,
                root_id,
                relationship,
                "target",
            )
            if source is None or target is None:
                continue
            if source not in visible_node_ids or target not in visible_node_ids:
                continue

            ir.edges.append(
                DiagramEdge(
                    id=relationship["id"],
                    semantic_id=relationship["id"],
                    kind=relationship["kind"],
                    source=source,
                    target=target,
                    label=relationship.get("name"),
                    metadata={"semantic": True},
                )
            )

    def _resolve_relationship_endpoint(
        self,
        ir: DiagramIR,
        owner_id: str,
        relationship: dict[str, Any],
        side: str,
    ) -> str | None:
        direct_id = relationship.get(f"{side}Id")
        if isinstance(direct_id, str):
            visible_ids = {node.id for node in ir.nodes}
            if direct_id in visible_ids:
                return direct_id

            # A REST relationship may point at a typed semantic feature while
            # the diagram contains a context-specific projection of that
            # feature. Resolve it only when the mapping is unambiguous.
            projected = [
                node.id
                for node in ir.nodes
                if node.derived and node.semantic_id == direct_id
            ]
            if len(projected) == 1:
                return projected[0]

        path = relationship.get(f"{side}Path")
        if isinstance(path, list) and all(isinstance(p, str) for p in path):
            return self._resolve_endpoint(owner_id, path)

        return None

    def _resolve_endpoint(
        self,
        owner_id: str,
        feature_path: list[str],
    ) -> str | None:
        if not feature_path:
            return None

        current = self.index.child_named(owner_id, feature_path[0])
        if current is None:
            return None

        if len(feature_path) == 1:
            return current["id"]

        if current["kind"] != "PartUsage":
            return None

        type_ref = current.get("typeRef")
        if not type_ref:
            return None

        typed_feature = self.index.child_named(type_ref, feature_path[1])
        if typed_feature is None:
            return None

        if len(feature_path) != 2:
            # Deeper feature chaining is intentionally deferred until the
            # adapter provides a complete SysML feature-chain resolver.
            return None

        return self._typed_feature_node_id(current["id"], typed_feature["id"])

    @staticmethod
    def _typed_feature_node_id(part_usage_id: str, feature_id: str) -> str:
        return f"projection:{part_usage_id}/{feature_id}"
