from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

import requests

from prototype.semantic_commands import (
    CreateOwnedElementCommand,
    DeleteElementCommand,
    RenameElementCommand,
)


class SysONSemanticWriterError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticWriteResult:
    command: str
    project_id: str
    commit_id: str
    element_id: str | None = None
    membership_id: str | None = None
    verified: bool = False


class SysONSemanticWriter:
    """Write semantic model changes through the SysML v2 commit REST API."""

    def __init__(
        self,
        base_url: str,
        project_id: str,
        *,
        token: str | None = None,
        session: requests.Session | Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.token = token
        self.session = session or requests.Session()

    def apply(
        self,
        command: RenameElementCommand
        | DeleteElementCommand
        | CreateOwnedElementCommand,
    ) -> SemanticWriteResult:
        if isinstance(command, RenameElementCommand):
            return self.rename(command.element_id, command.new_name)
        if isinstance(command, DeleteElementCommand):
            return self.delete(command.element_id)
        if isinstance(command, CreateOwnedElementCommand):
            return self.create_owned(
                command.owner_id,
                command.element_type,
                command.name,
            )
        raise TypeError(f"unsupported semantic command: {type(command)!r}")

    def head_commit_id(self) -> str:
        # SysON currently exposes a single effective commit per project and
        # may return the project ID after every write. Do not infer a version
        # counter from POST /commits.
        response = self.session.get(
            self._commits_url(),
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code != 200:
            raise SysONSemanticWriterError(
                f"Unable to fetch commits: HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )
        commits = response.json()
        if not isinstance(commits, list) or not commits:
            raise SysONSemanticWriterError("Project has no commits")
        commit_id = commits[-1].get("@id")
        if not isinstance(commit_id, str) or not commit_id:
            raise SysONSemanticWriterError("Latest commit has no @id")
        return commit_id

    def fetch_element(
        self,
        element_id: str,
        *,
        commit_id: str | None = None,
    ) -> dict[str, Any] | None:
        commit_id = commit_id or self.head_commit_id()
        response = self.session.get(
            self._element_url(commit_id, element_id),
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SysONSemanticWriterError(
                f"Unable to fetch element {element_id}: "
                f"HTTP {response.status_code}: {response.text[:2000]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise SysONSemanticWriterError("Element response is not an object")
        return payload

    def rename(self, element_id: str, new_name: str) -> SemanticWriteResult:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("new_name must not be empty")

        head = self.head_commit_id()
        current = self.fetch_element(element_id, commit_id=head)
        if current is None:
            raise SysONSemanticWriterError(
                f"Cannot rename missing element {element_id!r}"
            )

        element_type = current.get("@type")
        if not isinstance(element_type, str):
            raise SysONSemanticWriterError(
                f"Element {element_id!r} has no @type"
            )

        commit_id = self._post_commit(
            {
                "@type": "Commit",
                "change": [
                    {
                        "@type": "DataVersion",
                        "identity": {
                            "@id": element_id,
                            "@type": "DataIdentity",
                        },
                        "payload": {
                            "@id": element_id,
                            "@type": element_type,
                            "elementId": element_id,
                            "declaredName": new_name,
                        },
                    }
                ],
            }
        )

        updated = self.fetch_element(element_id, commit_id=commit_id)
        if not (
            updated
            and (
                updated.get("declaredName") == new_name
                or updated.get("name") == new_name
            )
        ):
            raise SysONSemanticWriterError(
                "Rename verification did not observe the new name"
            )

        return SemanticWriteResult(
            command="rename_element",
            project_id=self.project_id,
            commit_id=commit_id,
            element_id=element_id,
            verified=True,
        )

    def delete(self, element_id: str) -> SemanticWriteResult:
        head = self.head_commit_id()
        if self.fetch_element(element_id, commit_id=head) is None:
            raise SysONSemanticWriterError(
                f"Cannot delete missing element {element_id!r}"
            )

        commit_id = self._post_commit(
            {
                "@type": "Commit",
                "change": [
                    {
                        "@type": "DataVersion",
                        "identity": {
                            "@id": element_id,
                            "@type": "DataIdentity",
                        },
                    }
                ],
            }
        )

        if self.fetch_element(element_id, commit_id=commit_id) is not None:
            raise SysONSemanticWriterError(
                "Delete verification failed; element is still accessible"
            )

        return SemanticWriteResult(
            command="delete_element",
            project_id=self.project_id,
            commit_id=commit_id,
            element_id=element_id,
            verified=True,
        )

    def create_owned(
        self,
        owner_id: str,
        element_type: str,
        name: str,
    ) -> SemanticWriteResult:
        element_type = element_type.strip()
        name = name.strip()
        if not element_type or not name:
            raise ValueError("element_type and name must not be empty")

        head = self.head_commit_id()
        if self.fetch_element(owner_id, commit_id=head) is None:
            raise SysONSemanticWriterError(
                f"Cannot create under missing owner {owner_id!r}"
            )

        membership_id = str(uuid.uuid4())
        self._post_commit(
            {
                "@type": "Commit",
                "change": [
                    {
                        "@type": "DataVersion",
                        "identity": None,
                        "payload": {
                            "@id": membership_id,
                            "@type": "OwningMembership",
                            "elementId": membership_id,
                        },
                    },
                    {
                        "@type": "DataVersion",
                        "identity": {
                            "@id": owner_id,
                            "@type": "DataIdentity",
                        },
                        "payload": {
                            "@id": str(uuid.uuid4()),
                            "@type": "OwningMembership",
                            "ownedRelationship": [{"@id": membership_id}],
                        },
                    },
                ],
            }
        )

        element_id = str(uuid.uuid4())
        element_commit = self._post_commit(
            {
                "@type": "Commit",
                "change": [
                    {
                        "@type": "DataVersion",
                        "identity": None,
                        "payload": {
                            "@id": element_id,
                            "@type": element_type,
                            "declaredName": name,
                            "elementId": element_id,
                        },
                    },
                    {
                        "@type": "DataVersion",
                        "identity": {
                            "@id": membership_id,
                            "@type": "DataIdentity",
                        },
                        "payload": {
                            "@id": str(uuid.uuid4()),
                            "@type": element_type,
                            "ownedRelatedElement": [{"@id": element_id}],
                        },
                    },
                ],
            }
        )

        created = self.fetch_element(element_id, commit_id=element_commit)
        if not (
            created
            and created.get("@type") == element_type
            and (
                created.get("declaredName") == name
                or created.get("name") == name
            )
        ):
            raise SysONSemanticWriterError(
                "Create verification could not observe the new element"
            )

        return SemanticWriteResult(
            command="create_owned_element",
            project_id=self.project_id,
            commit_id=element_commit,
            element_id=element_id,
            membership_id=membership_id,
            verified=True,
        )

    def _post_commit(self, body: dict[str, Any]) -> str:
        response = self.session.post(
            self._commits_url(),
            json=body,
            headers={
                **self._headers(),
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        if response.status_code not in {200, 201}:
            raise SysONSemanticWriterError(
                f"Commit failed: HTTP {response.status_code}: "
                f"{response.text[:4000]}"
            )
        payload = response.json()
        commit_id = payload.get("@id")
        if not isinstance(commit_id, str) or not commit_id:
            raise SysONSemanticWriterError(
                "Commit response did not contain @id"
            )
        return commit_id

    def _commits_url(self) -> str:
        return (
            f"{self.base_url}/api/rest/projects/"
            f"{self.project_id}/commits"
        )

    def _element_url(self, commit_id: str, element_id: str) -> str:
        return (
            f"{self.base_url}/api/rest/projects/{self.project_id}/"
            f"commits/{commit_id}/elements/{element_id}"
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
