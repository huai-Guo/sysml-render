from __future__ import annotations

from html import escape
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Ref(BaseModel):
    id: str | None = Field(default=None, max_length=256)
    name: str | None = Field(default=None, max_length=4000)
    external: bool = False
    label: str | None = Field(default=None, max_length=4000)


class Entity(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    kind: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=4000)
    qualified_name: str | None = Field(default=None, max_length=8000)
    owner_id: str | None = Field(default=None, max_length=256)
    chaining_features: list[Ref] = Field(default_factory=list, max_length=128)


class Relation(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    kind: str = Field(min_length=1, max_length=128)
    source: Ref
    target: Ref


class SemanticModel(BaseModel):
    schema_version: Literal["1"]
    entities: list[Entity] = Field(max_length=5000)
    relations: list[Relation] = Field(max_length=10000)

    @model_validator(mode="after")
    def integrity(self):
        ids = {e.id for e in self.entities}
        if len(ids) != len(self.entities):
            raise ValueError("Duplicate entity identifiers")
        if len({r.id for r in self.relations}) != len(self.relations):
            raise ValueError("Duplicate relationship identifiers")
        for e in self.entities:
            if e.owner_id is not None and e.owner_id not in ids:
                raise ValueError("Unresolved owner identifier")
            for ref in e.chaining_features:
                if not ref.external and ref.id not in ids:
                    raise ValueError("Unresolved internal feature chain reference")
        for r in self.relations:
            for ref in (r.source, r.target):
                if not ref.external and ref.id not in ids:
                    raise ValueError("Unresolved internal relationship reference")
        # Check all containment paths, including unnamed elements.
        parents = {e.id: e.owner_id for e in self.entities}
        done: set[str] = set()
        for entity in self.entities:
            seen: set[str] = set()
            current = entity.id
            while current is not None and current not in done:
                if current in seen or len(seen) > 128:
                    raise ValueError("Cyclic or excessively deep containment")
                seen.add(current)
                current = parents[current]
            done.update(seen)
        return self


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_model: SemanticModel
    root_id: str | None = Field(default=None, max_length=256)


def render_svg(request: RenderRequest) -> dict:
    model = request.semantic_model
    entities = {e.id: e for e in model.entities}
    if request.root_id is not None and request.root_id not in entities:
        raise ValueError("Selected root does not exist")

    # Pilot represents contextual endpoints (battery.power) as anonymous feature
    # chains. Expose the exact semantic path as a node, preserving the instance
    # context instead of wiring two usages to the same definition's port.
    projected_paths = 0
    for e in model.entities:
        if not e.name and e.chaining_features:
            labels = [r.label or r.name or r.id or "?" for r in e.chaining_features]
            entities[e.id] = e.model_copy(update={"name": ".".join(labels), "kind": "FeaturePath"})
            projected_paths += 1

    def within(e: Entity) -> bool:
        current: str | None = e.id
        while current is not None:
            if current == request.root_id:
                return True
            current = entities[current].owner_id
        return request.root_id is None

    visible = [e for e in entities.values() if e.name and within(e)]
    if not visible:
        raise ValueError("No named authored elements to display")
    if len(visible) > 250:
        raise ValueError("Diagram exceeds 250 nodes; select a smaller root_id")
    visible_ids = {e.id for e in visible}
    positions = {}
    rows: dict[int, int] = {}
    for e in visible:
        depth = 0
        parent = e.owner_id
        while parent is not None:
            if parent in visible_ids:
                depth += 1
            parent = entities[parent].owner_id
        row = rows.get(depth, 0)
        rows[depth] = row + 1
        positions[e.id] = (40 + 360 * depth, 100 + 110 * row)

    edges = [r for r in model.relations if r.source.id in visible_ids and r.target.id in visible_ids]
    if len(edges) > 1500:
        raise ValueError("Diagram exceeds 1500 edges; select a smaller root_id")
    width = max(x for x, _ in positions.values()) + 340
    height = max(y for _, y in positions.values()) + 150
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
             '<title>SysML semantic structure</title>',
             f'<desc>Validated source SHA-256: {request.source_sha256}. Only supplied semantic relationships are shown.</desc>',
             '<rect width="100%" height="100%" fill="#f6f8fc"/>',
             '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#66758d"/></marker></defs>',
             '<g font-family="sans-serif"><text x="40" y="40" font-size="24" fill="#19324d">SysML · semantic structure</text>']
    for r in edges:
        x1, y1 = positions[r.source.id]
        x2, y2 = positions[r.target.id]
        title = escape(f"{r.kind}: {r.source.name or r.source.id} → {r.target.name or r.target.id}")
        dashed = ' stroke-dasharray="6 4"' if r.kind != "ownership" else ""
        parts.append(f'<path d="M{x1+280},{y1+38} L{x1+305},{y1+38} L{x2-25},{y2+38} L{x2},{y2+38}" fill="none" stroke="#66758d"{dashed} marker-end="url(#arrow)"><title>{title}</title></path>')
    for e in visible:
        x, y = positions[e.id]
        label = e.name if len(e.name) <= 27 else e.name[:26] + "…"
        parts.extend([f'<g><title>{escape(e.qualified_name or e.name)} · {escape(e.kind)}</title>',
                      f'<rect x="{x}" y="{y}" width="280" height="76" rx="10" fill="#fff" stroke="#bac9dc"/>',
                      f'<text x="{x+16}" y="{y+24}" font-size="12" fill="#65778e">{escape(e.kind)}</text>',
                      f'<text x="{x+16}" y="{y+52}" font-size="17" fill="#19324d">{escape(label)}</text></g>'])
    parts.extend([f'<text x="40" y="{height-25}" font-size="12" fill="#65778e">{len(visible)} elements · {len(edges)} relationships · solid: ownership / dashed: semantic reference</text>', '</g></svg>'])
    return {"source_sha256": request.source_sha256, "media_type": "image/svg+xml", "svg": "".join(parts),
            "coverage": {"profile": "authored-semantic-overview", "displayed_entities": len(visible),
                         "displayed_relations": len(edges), "omitted_entities": len(model.entities) - len(visible),
                         "omitted_relations": len(model.relations) - len(edges),
                         "projected_feature_paths": projected_paths,
                         "note": "Unnamed, external and out-of-scope elements are omitted; engineering correctness is not assessed."}}
