from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolutionStep:
    name: str
    semantic_id: str
    kind: str
    context_semantic_id: str | None
    via_type: bool


@dataclass(frozen=True)
class FeatureResolution:
    owner_id: str
    path: tuple[str, ...]
    steps: tuple[ResolutionStep, ...]

    @property
    def semantic_id(self) -> str:
        return self.steps[-1].semantic_id

    @property
    def context_semantic_id(self) -> str | None:
        return self.steps[-1].context_semantic_id


class SemanticFeatureResolver:
    """Resolve SysML feature chains across ownership and typing boundaries.

    A path such as::

        vehicle.electrical.battery.powerOut

    may cross several PartUsage -> PartDefinition typing boundaries. The
    resolver keeps those crossings explicit instead of flattening them into a
    string lookup.
    """

    def __init__(self, elements: dict[str, dict[str, Any]]):
        self.elements = elements
        self.children: dict[str, list[dict[str, Any]]] = {}
        for element in elements.values():
            parent_id = element.get("parentId")
            if isinstance(parent_id, str):
                self.children.setdefault(parent_id, []).append(element)

    def resolve(
        self,
        owner_id: str,
        path: list[str] | tuple[str, ...],
    ) -> FeatureResolution | None:
        if not path:
            return None
        if owner_id not in self.elements:
            return None

        current_id = owner_id
        current_context_id: str | None = None
        steps: list[ResolutionStep] = []

        for segment in path:
            direct = self._child_named(current_id, segment)
            via_type = False

            if direct is None:
                current = self.elements.get(current_id)
                type_ref = current.get("typeRef") if current else None
                if not isinstance(type_ref, str):
                    return None
                direct = self._child_named(type_ref, segment)
                if direct is None:
                    return None
                via_type = True

            semantic_id = direct["id"]

            if via_type:
                # The semantic feature belongs to the definition, but the
                # visible occurrence is contextualized by the usage we just
                # traversed from.
                context_id = current_id
            else:
                context_id = current_context_id

            steps.append(
                ResolutionStep(
                    name=segment,
                    semantic_id=semantic_id,
                    kind=direct["kind"],
                    context_semantic_id=context_id,
                    via_type=via_type,
                )
            )

            current_id = semantic_id
            # Once a usage is traversed, it becomes the context for any feature
            # resolved through its type on the next step.
            if direct["kind"].endswith("Usage"):
                current_context_id = semantic_id

        return FeatureResolution(
            owner_id=owner_id,
            path=tuple(path),
            steps=tuple(steps),
        )

    def _child_named(
        self,
        parent_id: str,
        name: str,
    ) -> dict[str, Any] | None:
        matches = [
            child
            for child in self.children.get(parent_id, [])
            if child.get("name") == name
        ]
        if len(matches) == 1:
            return matches[0]
        return None
