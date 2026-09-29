#!/usr/bin/env python3
"""SysON Phase-0 black-box probe for sysml-render.

This intentionally talks only through public HTTP/GraphQL surfaces. It does not
import SysON implementation classes, which is exactly the coupling boundary the
spike is trying to evaluate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
import websocket

DEFAULT_URL = "http://localhost:8080"
GRAPHQL_ENDPOINT = "/api/graphql"
GRAPHQL_UPLOAD_ENDPOINT = "/api/graphql/upload"
REST_ENDPOINT = "/api/rest"

FETCH_EDITING_CONTEXT = """
query FetchEditingContext($projectId: ID!) {
  viewer {
    project(projectId: $projectId) {
      currentEditingContext { id }
    }
  }
}
"""

UPLOAD_DOCUMENT = """
mutation UploadDocument($input: UploadDocumentInput!) {
  uploadDocument(input: $input) {
    __typename
    ... on UploadDocumentSuccessPayload { id report }
    ... on ErrorPayload { messages { body level } }
  }
}
"""

INSERT_TEXTUAL_SYSML = """
mutation InsertTextualSysMLv2($input: InsertTextualSysMLv2Input!) {
  insertTextualSysMLv2(input: $input) {
    __typename
    ... on SuccessPayload { id }
    ... on ErrorPayload { messages { body level } }
  }
}
"""

EXPLORER_SUBSCRIPTION = """
subscription explorerEvent($input: ExplorerEventInput!) {
  explorerEvent(input: $input) {
    __typename
    ... on TreeRefreshedEventPayload {
      id
      tree {
        id
        children {
          id
          kind
          hasChildren
          label {
            styledStringFragments { text }
          }
        }
      }
    }
  }
}
"""

GET_REPRESENTATION_DESCRIPTIONS = """
query getRepresentationDescriptions(
  $editingContextId: ID!,
  $objectId: ID!
) {
  viewer {
    editingContext(editingContextId: $editingContextId) {
      representationDescriptions(objectId: $objectId) {
        edges {
          node {
            id
            label
            defaultName
            documentation
          }
        }
      }
    }
  }
}
"""

CREATE_REPRESENTATION = """
mutation createRepresentation($input: CreateRepresentationInput!) {
  createRepresentation(input: $input) {
    __typename
    ... on CreateRepresentationSuccessPayload {
      representation {
        id
        __typename
      }
    }
    ... on ErrorPayload {
      messages { body level }
    }
  }
}
"""

GET_REPRESENTATIONS = """
query getRepresentations($editingContextId: ID!) {
  viewer {
    editingContext(editingContextId: $editingContextId) {
      representations {
        edges {
          node {
            id
            kind
            label
          }
        }
      }
    }
  }
}
"""

GENERAL_VIEW_DESCRIPTION_ID = (
    "siriusComponents://representationDescription?"
    "kind=diagramDescription&sourceKind=view&"
    "sourceId=8dcd14b0-6259-3193-ad2c-743f394c68e4&"
    "sourceElementId=db495705-e917-319b-af55-a32ad63f4089"
)

DIAGRAM_SUBSCRIPTION = """
subscription diagramEvent($input: DiagramEventInput!) {
  diagramEvent(input: $input) {
    __typename
    ... on ErrorPayload {
      messages { body level }
    }
    ... on DiagramRefreshedEventPayload {
      diagram {
        id
        targetObjectId
        metadata { label kind }
        style { background }
        layoutData {
          autoLaidOut
          nodeLayoutData {
            id
            position { x y }
            size { width height }
            movedByUser
            resizedByUser
          }
          edgeLayoutData {
            id
            bendingPoints { x y }
          }
        }
        nodes {
          id
          type
          targetObjectId
          targetObjectLabel
          state
          pinned
          insideLabel { id text }
          childNodes {
            id
            type
            targetObjectId
            targetObjectLabel
            state
            pinned
            insideLabel { id text }
            childNodes {
              id
              type
              targetObjectId
              targetObjectLabel
              state
              pinned
              insideLabel { id text }
            }
            borderNodes {
              id
              type
              targetObjectId
              targetObjectLabel
              state
              pinned
              insideLabel { id text }
            }
          }
          borderNodes {
            id
            type
            targetObjectId
            targetObjectLabel
            state
            pinned
            insideLabel { id text }
          }
        }
        edges {
          id
          type
          targetObjectId
          targetObjectLabel
          sourceId
          targetId
          state
          centerLabel { id text }
        }
      }
      cause
    }
  }
}
"""

DROP_ON_DIAGRAM = """
mutation dropOnDiagram($input: DropOnDiagramInput!) {
  dropOnDiagram(input: $input) {
    __typename
    ... on DropOnDiagramSuccessPayload {
      diagram {
        id
        targetObjectId
        nodes {
          id
          targetObjectId
          targetObjectLabel
          type
          childNodes {
            id
            targetObjectId
            targetObjectLabel
            type
          }
          borderNodes {
            id
            targetObjectId
            targetObjectLabel
            type
          }
        }
        edges {
          id
          targetObjectId
          targetObjectLabel
          sourceId
          targetId
          type
        }
      }
      messages { body level }
    }
    ... on ErrorPayload {
      messages { body level }
    }
  }
}
"""


class ProbeError(RuntimeError):
    pass


@dataclass
class ImportedDocument:
    project_id: str
    editing_context_id: str
    document_id: str
    import_report: str | None


class SysONClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def graphql_url(self) -> str:
        return self.base_url + GRAPHQL_ENDPOINT

    @property
    def upload_url(self) -> str:
        return self.base_url + GRAPHQL_UPLOAD_ENDPOINT

    @property
    def rest_url(self) -> str:
        return self.base_url + REST_ENDPOINT

    @property
    def subscriptions_url(self) -> str:
        if self.base_url.startswith("https://"):
            return "wss://" + self.base_url[len("https://"):] + "/subscriptions"
        if self.base_url.startswith("http://"):
            return "ws://" + self.base_url[len("http://"):] + "/subscriptions"
        raise ProbeError(f"unsupported base URL for WebSocket: {self.base_url}")

    @staticmethod
    def _tree_item_label(item: dict[str, Any]) -> str:
        fragments = (
            item.get("label", {})
            .get("styledStringFragments", [])
        )
        return "".join(
            fragment.get("text", "")
            for fragment in fragments
        )

    def discover_document_id(
        self,
        editing_context_id: str,
        preferred_name: str,
    ) -> str:
        operation_id = str(uuid.uuid4())
        representation_id = (
            "explorer://?treeDescriptionId=explorer_tree_description"
            "&expandedIds=[]&activeFilterIds=[]"
        )
        ws = websocket.create_connection(
            self.subscriptions_url,
            timeout=self.timeout,
            subprotocols=["graphql-ws"],
        )
        try:
            ws.send(json.dumps({"type": "connection_init", "payload": {}}))
            deadline = time.monotonic() + self.timeout
            started = False

            while time.monotonic() < deadline:
                raw = ws.recv()
                message = json.loads(raw)

                if message.get("type") == "connection_ack" and not started:
                    ws.send(
                        json.dumps(
                            {
                                "id": operation_id,
                                "type": "start",
                                "payload": {
                                    "query": EXPLORER_SUBSCRIPTION,
                                    "variables": {
                                        "input": {
                                            "id": str(uuid.uuid4()),
                                            "editingContextId": editing_context_id,
                                            "representationId": representation_id,
                                        }
                                    },
                                },
                            }
                        )
                    )
                    started = True
                    continue

                if message.get("type") in {"ka", "connection_ack"}:
                    continue

                if message.get("type") == "error":
                    raise ProbeError(
                        "Explorer subscription error: "
                        + json.dumps(message.get("payload"))
                    )

                if message.get("type") not in {"data", "next"}:
                    continue

                event = (
                    message.get("payload", {})
                    .get("data", {})
                    .get("explorerEvent", {})
                )
                tree = event.get("tree") or {}
                documents = [
                    item
                    for item in tree.get("children", [])
                    if item.get("kind") == "siriusWeb://document"
                ]
                if not documents:
                    continue

                preferred = preferred_name.lower()
                preferred_stem = Path(preferred_name).stem.lower()
                exact = []
                for item in documents:
                    label = self._tree_item_label(item).strip().lower()
                    if label in {preferred, preferred_stem}:
                        exact.append(item)

                candidates = exact or documents
                if len(candidates) == 1 and candidates[0].get("id"):
                    return candidates[0]["id"]

                labels = [
                    f"{self._tree_item_label(item)}:{item.get('id')}"
                    for item in documents
                ]
                raise ProbeError(
                    "could not uniquely identify uploaded document; "
                    f"candidates={labels}"
                )

            raise ProbeError(
                "timed out discovering document id from Explorer"
            )
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _json(self, response: requests.Response, context: str) -> Any:
        if not response.ok:
            raise ProbeError(
                f"{context}: HTTP {response.status_code}: {response.text[:1000]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProbeError(
                f"{context}: response is not JSON: {response.text[:1000]}"
            ) from exc

    def healthcheck(self) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.rest_url}/projects", timeout=self.timeout
        )
        data = self._json(response, "healthcheck")
        if not isinstance(data, list):
            raise ProbeError(
                f"healthcheck: expected project list, got {type(data).__name__}"
            )
        return data

    def create_project(self, name: str) -> str:
        response = self.session.post(
            f"{self.rest_url}/projects",
            params={"name": name},
            timeout=self.timeout,
        )
        data = self._json(response, "create project")
        project_id = data.get("@id")
        if not project_id:
            raise ProbeError(
                f"create project: missing @id in response: {data}"
            )
        return project_id

    def graphql(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        response = self.session.post(
            self.graphql_url,
            json={"query": query, "variables": variables},
            timeout=self.timeout,
        )
        data = self._json(response, "GraphQL")
        if data.get("errors"):
            raise ProbeError(
                "GraphQL errors: " + json.dumps(data["errors"], indent=2)
            )
        return data

    def editing_context_id(self, project_id: str) -> str:
        data = self.graphql(
            FETCH_EDITING_CONTEXT, {"projectId": project_id}
        )
        project = (
            data.get("data", {})
            .get("viewer", {})
            .get("project")
        )
        if not project:
            raise ProbeError(
                f"project not visible through GraphQL: {project_id}"
            )
        context = project.get("currentEditingContext")
        if not context or not context.get("id"):
            raise ProbeError(
                f"editing context missing for project: {project_id}"
            )
        return context["id"]

    def upload_sysml(
        self, project_id: str, file_path: Path
    ) -> ImportedDocument:
        editing_context_id = self.editing_context_id(project_id)
        operation_id = str(uuid.uuid4())
        operations = {
            "query": UPLOAD_DOCUMENT,
            "variables": {
                "input": {
                    "id": operation_id,
                    "editingContextId": editing_context_id,
                    "file": None,
                    "readOnly": False,
                }
            },
        }

        # Keep the mapping compatible with SysON's current official Python
        # import recipe. This is intentionally not abstracted yet: Phase 0 is
        # testing the real external contract first.
        file_map = {"0": "variables.file"}

        with file_path.open("rb") as handle:
            response = self.session.post(
                self.upload_url,
                data={
                    "operations": json.dumps(operations),
                    "map": json.dumps(file_map),
                },
                files={
                    "0": (file_path.name, handle, "text/plain"),
                },
                timeout=max(self.timeout, 120),
            )

        data = self._json(response, "upload SysML")
        if data.get("errors"):
            raise ProbeError(
                "upload GraphQL errors: "
                + json.dumps(data["errors"], indent=2)
            )
        payload = data.get("data", {}).get("uploadDocument", {})
        if payload.get("__typename") != "UploadDocumentSuccessPayload":
            raise ProbeError(
                "upload failed: " + json.dumps(payload, indent=2)
            )

        document_id = self.discover_document_id(
            editing_context_id,
            file_path.name,
        )

        return ImportedDocument(
            project_id=project_id,
            editing_context_id=editing_context_id,
            document_id=document_id,
            import_report=payload.get("report"),
        )

    def representation_descriptions(
        self,
        editing_context_id: str,
        object_id: str,
    ) -> list[dict[str, Any]]:
        data = self.graphql(
            GET_REPRESENTATION_DESCRIPTIONS,
            {
                "editingContextId": editing_context_id,
                "objectId": object_id,
            },
        )
        connection = (
            data.get("data", {})
            .get("viewer", {})
            .get("editingContext", {})
            .get("representationDescriptions", {})
        )
        return [
            edge.get("node", {})
            for edge in connection.get("edges", [])
            if edge.get("node")
        ]

    def create_general_view(
        self,
        editing_context_id: str,
        object_id: str,
        name: str = "Phase0 General View",
    ) -> tuple[str, str]:
        descriptions = self.representation_descriptions(
            editing_context_id,
            object_id,
        )
        general = next(
            (
                item
                for item in descriptions
                if item.get("id") == GENERAL_VIEW_DESCRIPTION_ID
                or item.get("label") == "General View"
            ),
            None,
        )
        if not general:
            available = [
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                }
                for item in descriptions
            ]
            raise ProbeError(
                "General View representation description not available "
                f"for target; available={available}"
            )

        description_id = general["id"]
        data = self.graphql(
            CREATE_REPRESENTATION,
            {
                "input": {
                    "id": str(uuid.uuid4()),
                    "editingContextId": editing_context_id,
                    "representationDescriptionId": description_id,
                    "objectId": object_id,
                    "representationName": name,
                }
            },
        )
        payload = (
            data.get("data", {})
            .get("createRepresentation", {})
        )
        if payload.get("__typename") != "CreateRepresentationSuccessPayload":
            raise ProbeError(
                "create General View failed: "
                + json.dumps(payload, indent=2)
            )
        representation = payload.get("representation") or {}
        representation_id = representation.get("id")
        if not representation_id:
            raise ProbeError(
                "create General View succeeded without representation.id"
            )
        return representation_id, description_id

    def representations(
        self,
        editing_context_id: str,
    ) -> list[dict[str, Any]]:
        data = self.graphql(
            GET_REPRESENTATIONS,
            {"editingContextId": editing_context_id},
        )
        connection = (
            data.get("data", {})
            .get("viewer", {})
            .get("editingContext", {})
            .get("representations", {})
        )
        return [
            edge.get("node", {})
            for edge in connection.get("edges", [])
            if edge.get("node")
        ]

    def diagram_snapshot(
        self,
        editing_context_id: str,
        diagram_id: str,
    ) -> dict[str, Any]:
        operation_id = str(uuid.uuid4())
        ws = websocket.create_connection(
            self.subscriptions_url,
            timeout=self.timeout,
            subprotocols=["graphql-ws"],
        )
        try:
            ws.send(json.dumps({"type": "connection_init", "payload": {}}))
            deadline = time.monotonic() + self.timeout
            started = False

            while time.monotonic() < deadline:
                raw = ws.recv()
                message = json.loads(raw)

                if message.get("type") == "connection_ack" and not started:
                    ws.send(
                        json.dumps(
                            {
                                "id": operation_id,
                                "type": "start",
                                "payload": {
                                    "query": DIAGRAM_SUBSCRIPTION,
                                    "variables": {
                                        "input": {
                                            "id": str(uuid.uuid4()),
                                            "editingContextId": editing_context_id,
                                            "diagramId": diagram_id,
                                        }
                                    },
                                },
                            }
                        )
                    )
                    started = True
                    continue

                if message.get("type") in {"ka", "connection_ack"}:
                    continue

                if message.get("type") == "error":
                    raise ProbeError(
                        "diagram subscription error: "
                        + json.dumps(message.get("payload"))
                    )

                if message.get("type") not in {"data", "next"}:
                    continue

                event = (
                    message.get("payload", {})
                    .get("data", {})
                    .get("diagramEvent", {})
                )
                if event.get("__typename") == "ErrorPayload":
                    raise ProbeError(
                        "diagram event returned error: "
                        + json.dumps(event.get("messages"))
                    )
                diagram = event.get("diagram")
                if diagram:
                    return diagram

            raise ProbeError(
                f"timed out reading diagram snapshot: {diagram_id}"
            )
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def drop_on_diagram(
        self,
        editing_context_id: str,
        diagram_id: str,
        semantic_element_ids: list[str],
        x: float = 0,
        y: float = 0,
    ) -> dict[str, Any]:
        data = self.graphql(
            DROP_ON_DIAGRAM,
            {
                "input": {
                    "id": str(uuid.uuid4()),
                    "editingContextId": editing_context_id,
                    "representationId": diagram_id,
                    "diagramTargetElementId": diagram_id,
                    "objectIds": semantic_element_ids,
                    "startingPositionX": x,
                    "startingPositionY": y,
                }
            },
        )
        payload = (
            data.get("data", {})
            .get("dropOnDiagram", {})
        )
        if payload.get("__typename") != "DropOnDiagramSuccessPayload":
            raise ProbeError(
                "dropOnDiagram failed: "
                + json.dumps(payload, indent=2)
            )
        diagram = payload.get("diagram")
        if not diagram:
            raise ProbeError("dropOnDiagram succeeded without diagram")
        return diagram

    def commits(self, project_id: str) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.rest_url}/projects/{project_id}/commits",
            timeout=self.timeout,
        )
        data = self._json(response, "fetch commits")
        if not isinstance(data, list) or not data:
            raise ProbeError("fetch commits: no commit returned")
        return data

    def latest_commit_id(self, project_id: str) -> str:
        commit = self.commits(project_id)[-1]
        commit_id = commit.get("@id")
        if not commit_id:
            raise ProbeError(
                f"latest commit has no @id: {commit}"
            )
        return commit_id

    def elements(self, project_id: str) -> list[dict[str, Any]]:
        commit_id = self.latest_commit_id(project_id)
        response = self.session.get(
            (
                f"{self.rest_url}/projects/{project_id}/commits/"
                f"{commit_id}/elements"
            ),
            timeout=max(self.timeout, 120),
        )
        data = self._json(response, "fetch elements")
        if not isinstance(data, list):
            raise ProbeError("fetch elements: expected a list")
        return data

    def export_document(self, imported: ImportedDocument) -> str:
        url = (
            f"{self.base_url}/api/editingcontexts/"
            f"{imported.editing_context_id}/documents/"
            f"{imported.document_id}"
        )
        response = self.session.get(
            url,
            headers={"Accept": "text/html"},
            timeout=max(self.timeout, 120),
        )
        if not response.ok:
            raise ProbeError(
                f"export SysML: HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )
        return response.text

    def insert_text(
        self, project_id: str, object_id: str, textual_content: str
    ) -> None:
        editing_context_id = self.editing_context_id(project_id)
        data = self.graphql(
            INSERT_TEXTUAL_SYSML,
            {
                "input": {
                    "id": str(uuid.uuid4()),
                    "editingContextId": editing_context_id,
                    "objectId": object_id,
                    "textualContent": textual_content,
                }
            },
        )
        payload = (
            data.get("data", {})
            .get("insertTextualSysMLv2", {})
        )
        if payload.get("__typename") != "SuccessPayload":
            raise ProbeError(
                "insert textual SysML failed: "
                + json.dumps(payload, indent=2)
            )


def element_name(element: dict[str, Any]) -> str | None:
    return element.get("declaredName") or element.get("name")


def element_type(element: dict[str, Any]) -> str | None:
    value = element.get("@type")
    if isinstance(value, list):
        return value[0] if value else None
    return value


def find_element(
    elements: Iterable[dict[str, Any]],
    name: str,
    type_name: str | None = None,
) -> dict[str, Any] | None:
    for element in elements:
        if element_name(element) != name:
            continue
        if type_name and element_type(element) != type_name:
            continue
        return element
    return None


def check_expected_elements(
    elements: list[dict[str, Any]],
    expected: list[dict[str, str]],
) -> list[str]:
    missing: list[str] = []
    for item in expected:
        if not find_element(
            elements, item["name"], item.get("type")
        ):
            missing.append(
                f"{item.get('type', '*')}:{item['name']}"
            )
    return missing


def run_all(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = (repo_root / args.fixture).resolve()
    mutation_file = (repo_root / args.mutation_file).resolve()
    expectations_path = (repo_root / args.expectations).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    expectations = json.loads(
        expectations_path.read_text(encoding="utf-8")
    )
    client = SysONClient(args.url, timeout=args.timeout)

    print(f"[1/13] Healthcheck {args.url}")
    projects = client.healthcheck()
    print(f"      OK - {len(projects)} existing project(s)")

    project_name = (
        args.project_name
        or f"sysml-render-phase0-{uuid.uuid4().hex[:8]}"
    )
    print(f"[2/13] Create project: {project_name}")
    project_id = client.create_project(project_name)
    print(f"      project_id={project_id}")

    print(f"[3/13] Import fixture: {fixture.name}")
    imported = client.upload_sysml(project_id, fixture)
    print(f"      document_id={imported.document_id}")
    if imported.import_report:
        print("      import report:")
        print(imported.import_report)

    print("[4/13] Inspect semantic element inventory")
    elements = client.elements(project_id)
    missing = check_expected_elements(
        elements, expectations["requiredElements"]
    )
    inventory_path = output_dir / "elements-before.json"
    inventory_path.write_text(
        json.dumps(elements, indent=2),
        encoding="utf-8",
    )
    if missing:
        raise ProbeError(
            "missing expected imported elements: "
            + ", ".join(missing)
        )
    print(
        f"      OK - {len(elements)} elements; "
        "required semantic sentinels found"
    )

    print("[5/13] Export textual SysML")
    exported_before = client.export_document(imported)
    before_path = output_dir / "export-before.sysml"
    before_path.write_text(exported_before, encoding="utf-8")
    missing_sentinels = [
        sentinel
        for sentinel in expectations["exportSentinels"]
        if sentinel not in exported_before
    ]
    if missing_sentinels:
        raise ProbeError(
            "export missing sentinels: "
            + ", ".join(missing_sentinels)
        )
    print(f"      OK - wrote {before_path}")

    print(
        "[6/13] Programmatic semantic mutation "
        "through InsertTextualSysMLv2"
    )
    target_spec = expectations["semanticMutationTarget"]
    target = find_element(
        elements,
        target_spec["name"],
        target_spec.get("type"),
    )
    if not target or not target.get("@id"):
        raise ProbeError(
            f"semantic mutation target not found: {target_spec}"
        )

    mutation_text = mutation_file.read_text(encoding="utf-8")
    client.insert_text(
        project_id,
        target["@id"],
        mutation_text,
    )
    print(
        f"      OK - inserted under {target_spec['name']} "
        f"({target['@id']})"
    )

    print("[7/13] Verify mutation through REST semantic inventory")
    elements_after = client.elements(project_id)
    missing_after = check_expected_elements(
        elements_after,
        expectations["requiredAfterMutation"],
    )
    after_inventory_path = output_dir / "elements-after.json"
    after_inventory_path.write_text(
        json.dumps(elements_after, indent=2),
        encoding="utf-8",
    )
    if missing_after:
        raise ProbeError(
            "mutation did not produce expected elements: "
            + ", ".join(missing_after)
        )
    print("      OK - semantic mutation is visible through REST")

    print("[8/13] Export after mutation")
    exported_after = client.export_document(imported)
    after_path = output_dir / "export-after.sysml"
    after_path.write_text(exported_after, encoding="utf-8")
    for item in expectations["requiredAfterMutation"]:
        if item["name"] not in exported_after:
            raise ProbeError(
                "post-mutation export does not contain "
                + item["name"]
            )
    print(f"      OK - wrote {after_path}")

    print("[9/13] Create General View programmatically")
    representation_id, representation_description_id = (
        client.create_general_view(
            imported.editing_context_id,
            target["@id"],
        )
    )
    print(
        "      OK - General View created; "
        f"representation_id={representation_id}"
    )

    print("[10/13] Verify representation metadata through GraphQL")
    representations = client.representations(
        imported.editing_context_id
    )
    created_representation = next(
        (
            item
            for item in representations
            if item.get("id") == representation_id
        ),
        None,
    )
    if not created_representation:
        raise ProbeError(
            "created General View is not visible in "
            "editingContext.representations"
        )
    representations_path = output_dir / "representations.json"
    representations_path.write_text(
        json.dumps(representations, indent=2),
        encoding="utf-8",
    )
    print(
        "      OK - representation metadata visible; "
        f"kind={created_representation.get('kind')}"
    )

    print("[11/13] Read structured diagram snapshot")
    diagram_before_drop = client.diagram_snapshot(
        imported.editing_context_id,
        representation_id,
    )
    initial_nodes = diagram_before_drop.get("nodes", [])
    print(
        "      OK - diagram subscription works; "
        f"initial top-level nodes={len(initial_nodes)}"
    )

    print("[12/13] Expose semantic elements by dropOnDiagram")
    expose_specs = [
        ("vehicle", "PartUsage"),
        ("Requirements", "Package"),
    ]
    expose_elements = []
    for name, type_name in expose_specs:
        element = find_element(elements_after, name, type_name)
        if not element or not element.get("@id"):
            raise ProbeError(
                f"diagram exposure target missing: {type_name}:{name}"
            )
        expose_elements.append(element)

    dropped_diagram = client.drop_on_diagram(
        imported.editing_context_id,
        representation_id,
        [item["@id"] for item in expose_elements],
    )
    dropped_target_ids = {
        node.get("targetObjectId")
        for node in dropped_diagram.get("nodes", [])
    }
    expected_target_ids = {
        item["@id"] for item in expose_elements
    }
    if not expected_target_ids.issubset(dropped_target_ids):
        raise ProbeError(
            "dropOnDiagram did not expose expected semantic nodes; "
            f"expected={expected_target_ids}, actual={dropped_target_ids}"
        )
    print(
        "      OK - diagram contains semantic nodes: "
        + ", ".join(name for name, _ in expose_specs)
    )

    print("[13/13] Re-read diagram and verify persistent view semantics")
    diagram_after_drop = client.diagram_snapshot(
        imported.editing_context_id,
        representation_id,
    )
    snapshot_path = output_dir / "diagram-after-drop.json"
    snapshot_path.write_text(
        json.dumps(diagram_after_drop, indent=2),
        encoding="utf-8",
    )
    final_target_ids = {
        node.get("targetObjectId")
        for node in diagram_after_drop.get("nodes", [])
    }
    if not expected_target_ids.issubset(final_target_ids):
        raise ProbeError(
            "diagram subscription lost exposed nodes after mutation"
        )

    exported_with_view = client.export_document(imported)
    view_export_path = output_dir / "export-with-view.sysml"
    view_export_path.write_text(
        exported_with_view,
        encoding="utf-8",
    )
    if "Phase0 General View" not in exported_with_view:
        raise ProbeError(
            "textual export does not contain created ViewUsage"
        )
    if "expose" not in exported_with_view:
        raise ProbeError(
            "textual export does not contain view expose semantics"
        )
    print(
        "      OK - diagram nodes persist and textual export "
        "contains ViewUsage/expose semantics"
    )

    summary = {
        "server": args.url,
        "projectId": project_id,
        "editingContextId": imported.editing_context_id,
        "documentId": imported.document_id,
        "elementCountBefore": len(elements),
        "elementCountAfter": len(elements_after),
        "fixture": str(fixture.relative_to(repo_root)),
        "semanticMutationTarget": target_spec,
        "generalViewRepresentationId": representation_id,
        "generalViewDescriptionId": representation_description_id,
        "representationKind": created_representation.get("kind"),
        "initialTopLevelNodeCount": len(initial_nodes),
        "exposedSemanticElementIds": sorted(expected_target_ids),
        "finalTopLevelNodeCount": len(
            diagram_after_drop.get("nodes", [])
        ),
        "automatedChecks": "PASS",
        "manualDiagramChecks": "PENDING",
    }
    summary_path = output_dir / "phase0-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(
        "\nAUTOMATED PHASE-0 CHECKS PASS\n"
        f"Summary: {summary_path}"
    )
    print(
        "Next: execute the manual diagram checklist in "
        "docs/spikes/SYSON_PHASE0.md"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SysON Phase-0 black-box integration probe"
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    run = sub.add_parser(
        "run-all",
        help=(
            "create a project and execute the automated "
            "Phase-0 flow"
        ),
    )
    run.add_argument("--url", default=DEFAULT_URL)
    run.add_argument("--timeout", type=int, default=30)
    run.add_argument("--project-name")
    run.add_argument(
        "--fixture",
        default="examples/phase0/vehicle.sysml",
    )
    run.add_argument(
        "--mutation-file",
        default="examples/phase0/insert_telemetry.sysml",
    )
    run.add_argument(
        "--expectations",
        default="examples/phase0/expectations.json",
    )
    run.add_argument(
        "--output-dir",
        default=".phase0-results",
    )
    run.set_defaults(func=run_all)

    health = sub.add_parser(
        "health",
        help="check that the SysON REST API is reachable",
    )
    health.add_argument("--url", default=DEFAULT_URL)
    health.add_argument("--timeout", type=int, default=10)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "health":
        projects = SysONClient(
            args.url,
            args.timeout,
        ).healthcheck()
        print(
            f"SysON reachable: {args.url}; "
            f"{len(projects)} project(s)"
        )
        return 0

    try:
        return args.func(args)
    except ProbeError as exc:
        print(
            f"PHASE-0 PROBE FAILED: {exc}",
            file=sys.stderr,
        )
        return 2
    except requests.RequestException as exc:
        print(
            f"PHASE-0 PROBE FAILED: network error: {exc}",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
