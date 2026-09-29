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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

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

        document = payload.get("document") or {}
        document_id = document.get("id")
        if not document_id:
            raise ProbeError(
                "upload succeeded without document.id; "
                f"payload keys={list(payload.keys())}"
            )

        return ImportedDocument(
            project_id=project_id,
            editing_context_id=editing_context_id,
            document_id=document_id,
            import_report=payload.get("report"),
        )

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

    print(f"[1/8] Healthcheck {args.url}")
    projects = client.healthcheck()
    print(f"      OK - {len(projects)} existing project(s)")

    project_name = (
        args.project_name
        or f"sysml-render-phase0-{uuid.uuid4().hex[:8]}"
    )
    print(f"[2/8] Create project: {project_name}")
    project_id = client.create_project(project_name)
    print(f"      project_id={project_id}")

    print(f"[3/8] Import fixture: {fixture.name}")
    imported = client.upload_sysml(project_id, fixture)
    print(f"      document_id={imported.document_id}")
    if imported.import_report:
        print("      import report:")
        print(imported.import_report)

    print("[4/8] Inspect semantic element inventory")
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

    print("[5/8] Export textual SysML")
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
        "[6/8] Programmatic semantic mutation "
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

    print("[7/8] Verify mutation through REST semantic inventory")
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

    print("[8/8] Export after mutation")
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

    summary = {
        "server": args.url,
        "projectId": project_id,
        "editingContextId": imported.editing_context_id,
        "documentId": imported.document_id,
        "elementCountBefore": len(elements),
        "elementCountAfter": len(elements_after),
        "fixture": str(fixture.relative_to(repo_root)),
        "semanticMutationTarget": target_spec,
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
