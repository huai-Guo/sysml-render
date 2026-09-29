from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ViewIdentity:
    project_id: str
    root_semantic_id: str
    profile: str

    @property
    def id(self) -> str:
        raw = (
            f"{self.project_id}\n"
            f"{self.root_semantic_id}\n"
            f"{self.profile}"
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return f"view-{digest}"


class FileViewStateStore:
    """Persist presentation-only state independently from SysML semantics."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    def load(self, view_id: str) -> dict[str, dict[str, Any]]:
        path = self._path(view_id)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        nodes = payload.get("nodes", {})
        return nodes if isinstance(nodes, dict) else {}

    def update_node(
        self,
        *,
        identity: ViewIdentity,
        node_id: str,
        x: float,
        y: float,
        pinned: bool = True,
    ) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(identity.id)

        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = {
                "schemaVersion": 1,
                "viewId": identity.id,
                "projectId": identity.project_id,
                "rootSemanticId": identity.root_semantic_id,
                "profile": identity.profile,
                "nodes": {},
            }

        payload.setdefault("nodes", {})[node_id] = {
            "x": float(x),
            "y": float(y),
            "pinned": bool(pinned),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload

    def _path(self, view_id: str) -> Path:
        if not view_id.startswith("view-"):
            raise ValueError("invalid view id")
        return self.directory / f"{view_id}.sysmlview.json"
