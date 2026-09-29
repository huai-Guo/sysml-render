from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    element_id: str
    profile: str


PROFILE_BY_KIND: dict[str, str] = {
    "Package": "package-overview",
    "LibraryPackage": "package-overview",
    "PartDefinition": "structure",
    "PartUsage": "structure",
    "PortDefinition": "structure",
    "PortUsage": "structure",
    "RequirementDefinition": "requirements",
    "RequirementUsage": "requirements",
}


class SemanticSelector:
    def __init__(self, snapshot: dict[str, Any]):
        self.snapshot = snapshot
        self.elements = [
            element
            for element in snapshot.get("elements", [])
            if isinstance(element, dict) and isinstance(element.get("id"), str)
        ]
        self.by_id = {element["id"]: element for element in self.elements}

    def roots(self) -> list[dict[str, Any]]:
        return [
            element
            for element in self.elements
            if not element.get("parentId")
        ]

    def resolve(
        self,
        selector: str | None = None,
        *,
        profile: str | None = None,
    ) -> Selection:
        element = self._resolve_element(selector)
        selected_profile = profile or self.infer_profile(element)
        return Selection(
            element_id=element["id"],
            profile=selected_profile,
        )

    def infer_profile(self, element: dict[str, Any]) -> str:
        kind = element.get("kind")
        if kind in PROFILE_BY_KIND:
            return PROFILE_BY_KIND[kind]
        raise SelectionError(
            f"no default projection profile for semantic kind {kind!r}; "
            "specify --profile explicitly"
        )

    def _resolve_element(self, selector: str | None) -> dict[str, Any]:
        if selector:
            if selector in self.by_id:
                return self.by_id[selector]

            exact_qualified = [
                element
                for element in self.elements
                if element.get("qualifiedName") == selector
            ]
            if len(exact_qualified) == 1:
                return exact_qualified[0]

            exact_name = [
                element
                for element in self.elements
                if element.get("name") == selector
            ]
            if len(exact_name) == 1:
                return exact_name[0]
            if len(exact_name) > 1:
                candidates = ", ".join(
                    element.get("qualifiedName") or element["id"]
                    for element in exact_name[:10]
                )
                raise SelectionError(
                    f"semantic name {selector!r} is ambiguous; candidates: "
                    f"{candidates}"
                )

            raise SelectionError(f"semantic element not found: {selector!r}")

        roots = self.roots()
        preferred = [
            element
            for element in roots
            if element.get("kind") in {"Package", "LibraryPackage"}
        ]

        if len(preferred) == 1:
            return preferred[0]
        if len(roots) == 1:
            return roots[0]

        candidates = ", ".join(
            element.get("qualifiedName")
            or element.get("name")
            or element["id"]
            for element in (preferred or roots)[:10]
        )
        raise SelectionError(
            "multiple semantic roots are available; select one by id, name, "
            f"or qualifiedName. Candidates: {candidates}"
        )
