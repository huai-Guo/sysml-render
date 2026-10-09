from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeleteAudit:
    safe: bool
    reasons: tuple[str, ...]


def audit_delete(
    snapshot: dict[str, Any],
    target_id: str,
    *,
    server_relationships: list[dict[str, Any]] | None,
) -> DeleteAudit:
    """Conservative, fail-closed check before removing a SysML definition.

    The normalized projection is not a complete model dependency graph. In
    particular, inherited or derived SysML references may not survive
    normalization. Always require a successful raw relationships query, and
    reject any reported associations until an ownership-aware cascade writer
    has been validated against a real SysON backend.
    """
    elements = snapshot.get("elements", [])
    relationships = snapshot.get("relationships", [])
    by_id = {element.get("id"): element for element in elements}
    target = by_id.get(target_id)
    reasons: list[str] = []

    if target is None:
        return DeleteAudit(False, ("Target element not found in semantic snapshot.",))

    if target.get("kind") not in {
        "PartDefinition", "PortDefinition", "ItemDefinition", "RequirementDefinition"
    }:
        reasons.append("Deletion is restricted to leaf definition kinds.")

    for element in elements:
        if element.get("id") == target_id:
            continue
        if element.get("parentId") == target_id:
            reasons.append(f"Element owns child {element.get('id')}.")
        for field in ("typeRef", "definitionRef", "specializes", "redefines", "subsets"):
            if _has_reference(element.get(field), target_id):
                reasons.append(f"Element {element.get('id')} references target through {field}.")

    for relationship in relationships:
        if _has_reference({
            key: value
            for key, value in relationship.items()
            if key != "id"
        }, target_id):
            reasons.append(
                f"Semantic relationship {relationship.get('id')} references target."
            )

    if server_relationships is None:
        reasons.append(
            "Server-side relationship audit unavailable; refusing deletion."
        )
    elif server_relationships:
        reasons.append(
            f"SysON reports {len(server_relationships)} associated relationship(s); "
            "owner membership and external dependencies are not safely removable yet."
        )

    return DeleteAudit(not reasons, tuple(dict.fromkeys(reasons)))


def _has_reference(value: Any, expected_id: str) -> bool:
    if isinstance(value, str):
        return value == expected_id
    if isinstance(value, (list, tuple, set)):
        return any(_has_reference(item, expected_id) for item in value)
    if isinstance(value, dict):
        return any(_has_reference(item, expected_id) for item in value.values())
    return False
