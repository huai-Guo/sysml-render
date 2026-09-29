from __future__ import annotations

from typing import Any, Protocol


class SemanticModelProvider(Protocol):
    """Source-neutral semantic model provider.

    ProjectionEngine consumes the normalized snapshot returned here and does
    not know whether the source is SysON, SysIDE, another SysML API server, or
    a test fixture.
    """

    def snapshot(self) -> dict[str, Any]:
        """Return the complete normalized semantic snapshot."""


def ref_id(value: Any) -> str | None:
    """Extract a SysML API @id from common reference shapes."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidate = value.get("@id") or value.get("id")
        return candidate if isinstance(candidate, str) else None
    return None


def first_ref(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            candidate = ref_id(item)
            if candidate:
                return candidate
        return None
    return ref_id(value)
