from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from layout import SimpleHierarchicalLayout
from projection import ProjectionEngine
from selection import SemanticSelector


@dataclass(frozen=True)
class RenderResult:
    root_semantic_id: str
    profile: str
    graph: dict[str, Any]
    layout: dict[str, Any]


class RenderService:
    """Source-neutral renderer orchestration.

    Input is the normalized semantic snapshot. This keeps SysON, future SysML
    API servers, and test fixtures outside the renderer core.
    """

    def render(
        self,
        snapshot: dict[str, Any],
        *,
        select: str | None = None,
        profile: str | None = None,
        layout_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> RenderResult:
        selection = SemanticSelector(snapshot).resolve(
            select,
            profile=profile,
        )
        ir = ProjectionEngine(snapshot).project(
            selection.element_id,
            selection.profile,
        )
        layout = SimpleHierarchicalLayout().layout(
            ir,
            overrides=layout_overrides,
        )

        return RenderResult(
            root_semantic_id=selection.element_id,
            profile=selection.profile,
            graph=ir.to_dict(),
            layout=layout.to_dict(),
        )
