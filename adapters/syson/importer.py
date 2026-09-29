from __future__ import annotations

from dataclasses import dataclass
import json
import uuid
from typing import Any

import requests


class SysONImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportedModel:
    project_id: str
    editing_context_id: str
    document_id: str | None
    import_report: Any = None


class SysONImporter:
    GRAPHQL_ENDPOINT = "/api/graphql"
    GRAPHQL_UPLOAD_ENDPOINT = "/api/graphql/upload"

    FETCH_EDITING_CONTEXT = """
query FetchEditingContext($projectId: ID!) {
  viewer {
    project(projectId: $projectId) {
      currentEditingContext {
        id
      }
    }
  }
}
"""

    UPLOAD_DOCUMENT = """
mutation UploadDocument($input: UploadDocumentInput!) {
  uploadDocument(input: $input) {
    __typename
    ... on UploadDocumentSuccessPayload {
      id
      report
    }
    ... on ErrorPayload {
      messages {
        body
        level
      }
    }
  }
}
"""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        session: requests.Session | Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def create_project(self, name: str) -> str:
        response = self.session.post(
            f"{self.base_url}/api/rest/projects",
            params={"name": name},
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code != 201:
            raise SysONImportError(
                f"SysON project creation returned HTTP "
                f"{response.status_code}: {response.text[:2000]}"
            )
        payload = response.json()
        project_id = payload.get("@id")
        if not isinstance(project_id, str) or not project_id:
            raise SysONImportError(
                "SysON project creation did not return a project @id"
            )
        return project_id

    def fetch_editing_context_id(self, project_id: str) -> str:
        response = self.session.post(
            f"{self.base_url}{self.GRAPHQL_ENDPOINT}",
            json={
                "query": self.FETCH_EDITING_CONTEXT,
                "variables": {"projectId": project_id},
            },
            headers={
                **self._headers(),
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise SysONImportError(
                f"SysON GraphQL returned HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )
        payload = response.json()
        if payload.get("errors"):
            raise SysONImportError(
                "SysON GraphQL errors: "
                + json.dumps(payload["errors"], ensure_ascii=False)
            )
        editing_context_id = (
            payload.get("data", {})
            .get("viewer", {})
            .get("project", {})
            .get("currentEditingContext", {})
            .get("id")
        )
        if not isinstance(editing_context_id, str) or not editing_context_id:
            raise SysONImportError(
                f"SysON project {project_id!r} has no editing context"
            )
        return editing_context_id

    def import_text(
        self,
        text: str,
        *,
        filename: str = "model.sysml",
        project_id: str | None = None,
        project_name: str = "sysml-render",
        read_only: bool = False,
    ) -> ImportedModel:
        if project_id is None:
            project_id = self.create_project(project_name)

        editing_context_id = self.fetch_editing_context_id(project_id)
        operation_id = str(uuid.uuid4())
        operations = {
            "query": self.UPLOAD_DOCUMENT,
            "variables": {
                "input": {
                    "id": operation_id,
                    "editingContextId": editing_context_id,
                    "file": None,
                    "readOnly": read_only,
                }
            },
        }
        file_map = {"0": ["variables.input.file"]}

        response = self.session.post(
            f"{self.base_url}{self.GRAPHQL_UPLOAD_ENDPOINT}",
            data={
                "operations": json.dumps(operations),
                "map": json.dumps(file_map),
            },
            files={
                "0": (
                    filename,
                    text.encode("utf-8"),
                    "text/plain",
                )
            },
            headers=self._headers(),
            timeout=120,
        )
        if response.status_code != 200:
            raise SysONImportError(
                f"SysON upload returned HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )

        payload = response.json()
        if payload.get("errors"):
            raise SysONImportError(
                "SysON upload GraphQL errors: "
                + json.dumps(payload["errors"], ensure_ascii=False)
            )

        result = payload.get("data", {}).get("uploadDocument", {})
        if result.get("__typename") != "UploadDocumentSuccessPayload":
            raise SysONImportError(
                "SysON rejected the SysML document: "
                + json.dumps(result, ensure_ascii=False)
            )

        return ImportedModel(
            project_id=project_id,
            editing_context_id=editing_context_id,
            document_id=result.get("id"),
            import_report=result.get("report"),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
