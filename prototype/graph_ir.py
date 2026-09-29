from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiagramNode:
    id: str
    semantic_id: str
    label: str
    kind: str
    parent_id: str | None = None
    context_semantic_id: str | None = None
    derived: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagramEdge:
    id: str
    semantic_id: str
    kind: str
    source: str
    target: str
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagramIR:
    root_semantic_id: str
    profile: str
    nodes: list[DiagramNode] = field(default_factory=list)
    edges: list[DiagramEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rootSemanticId": self.root_semantic_id,
            "profile": self.profile,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
        }
