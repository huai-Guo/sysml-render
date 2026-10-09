from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SemanticCommandError(ValueError):
    pass


@dataclass(frozen=True)
class SemanticCommandPlan:
    kind: str
    parent_id: str
    textual_content: str
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CreateConnectionCommand:
    parent_id: str
    name: str
    source_path: tuple[str, ...]
    target_path: tuple[str, ...]
    kind: Literal["create_connection"] = "create_connection"


@dataclass(frozen=True)
class InsertSysMLCommand:
    parent_id: str
    textual_content: str
    kind: Literal["insert_sysml"] = "insert_sysml"


@dataclass(frozen=True)
class RenameElementCommand:
    element_id: str
    new_name: str
    kind: Literal["rename_element"] = "rename_element"


@dataclass(frozen=True)
class DeleteElementCommand:
    element_id: str
    kind: Literal["delete_element"] = "delete_element"


@dataclass(frozen=True)
class CreateOwnedElementCommand:
    owner_id: str
    element_type: str
    name: str
    kind: Literal["create_owned_element"] = "create_owned_element"


class SemanticCommandCompiler:
    """Compile renderer-owned semantic commands to textual SysML mutations."""

    def compile(
        self,
        command: CreateConnectionCommand | InsertSysMLCommand,
    ) -> SemanticCommandPlan:
        if isinstance(command, CreateConnectionCommand):
            return self._compile_connection(command)
        if isinstance(command, InsertSysMLCommand):
            return self._compile_insert(command)
        raise SemanticCommandError(
            f"unsupported semantic command: {type(command).__name__}"
        )

    def _compile_connection(
        self,
        command: CreateConnectionCommand,
    ) -> SemanticCommandPlan:
        self._validate_name(command.name, "connection name")
        source = self._feature_path(command.source_path, "source")
        target = self._feature_path(command.target_path, "target")

        textual = (
            f"connection {command.name} connect "
            f"{source} to {target};"
        )
        return SemanticCommandPlan(
            kind=command.kind,
            parent_id=command.parent_id,
            textual_content=textual,
            description=(
                f"Create semantic ConnectionUsage {command.name!r} "
                f"from {source} to {target}"
            ),
        )

    def _compile_insert(
        self,
        command: InsertSysMLCommand,
    ) -> SemanticCommandPlan:
        text = command.textual_content.strip()
        if not text:
            raise SemanticCommandError("textual SysML content is empty")
        return SemanticCommandPlan(
            kind=command.kind,
            parent_id=command.parent_id,
            textual_content=text,
            description="Insert textual SysML under the selected semantic parent",
        )

    def _feature_path(
        self,
        path: tuple[str, ...],
        role: str,
    ) -> str:
        if not path:
            raise SemanticCommandError(f"{role} feature path is empty")
        for segment in path:
            self._validate_name(segment, f"{role} path segment")
        return ".".join(path)

    @staticmethod
    def _validate_name(value: str, role: str) -> None:
        if not _SAFE_NAME.fullmatch(value):
            raise SemanticCommandError(
                f"{role} {value!r} is not a safe simple SysML identifier"
            )
