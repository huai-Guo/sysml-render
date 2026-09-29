#!/usr/bin/env python3
"""
Phase-0 SysON smoke test for sysml-render.

It verifies that a running SysON instance is reachable, resolves the project's
current editing context, and uploads a textual SysML v2 file through the same
GraphQL endpoint used by Sirius Web.

This script intentionally does not automate browser UI actions. Phase 0 is
trying to prove that the integration can be API-driven.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import requests

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


class SmokeFailure(RuntimeError):
    pass


def headers(token: str | None = None) -> dict[str, str]:
    result = {"Accept": "application/json"}
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def graphql_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{GRAPHQL_ENDPOINT}"


def upload_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{GRAPHQL_UPLOAD_ENDPOINT}"


def graphql(
    base_url: str,
    query: str,
    variables: dict[str, Any],
    token: str | None,
) -> dict[str, Any]:
    response = requests.post(
        graphql_url(base_url),
        json={"query": query, "variables": variables},
        headers={**headers(token), "Content-Type": "application/json"},
        timeout=30,
    )
    if response.status_code != 200:
        raise SmokeFailure(
            f"GraphQL HTTP {response.status_code}: {response.text[:1000]}"
        )
    payload = response.json()
    if payload.get("errors"):
        raise SmokeFailure(
            "GraphQL errors: " + json.dumps(payload["errors"], ensure_ascii=False)
        )
    return payload


def fetch_editing_context(
    base_url: str, project_id: str, token: str | None
) -> str:
    payload = graphql(
        base_url,
        FETCH_EDITING_CONTEXT,
        {"projectId": project_id},
        token,
    )
    project = payload.get("data", {}).get("viewer", {}).get("project")
    if not project:
        raise SmokeFailure(f"Project not found: {project_id}")

    editing_context = project.get("currentEditingContext")
    if not editing_context or not editing_context.get("id"):
        raise SmokeFailure(f"No current editing context for project: {project_id}")

    return editing_context["id"]


def upload_sysml(
    base_url: str,
    project_id: str,
    file_path: Path,
    token: str | None,
    read_only: bool,
) -> dict[str, Any]:
    editing_context_id = fetch_editing_context(base_url, project_id, token)

    operation_id = str(uuid.uuid4())
    operations = {
        "query": UPLOAD_DOCUMENT,
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

    with file_path.open("rb") as stream:
        response = requests.post(
            upload_url(base_url),
            data={
                "operations": json.dumps(operations),
                "map": json.dumps(file_map),
            },
            files={"0": (file_path.name, stream, "text/plain")},
            headers=headers(token),
            timeout=120,
        )

    if response.status_code != 200:
        raise SmokeFailure(
            f"Upload HTTP {response.status_code}: {response.text[:2000]}"
        )

    payload = response.json()
    if payload.get("errors"):
        raise SmokeFailure(
            "Upload GraphQL errors: "
            + json.dumps(payload["errors"], ensure_ascii=False)
        )

    result = payload.get("data", {}).get("uploadDocument", {})
    if result.get("__typename") != "UploadDocumentSuccessPayload":
        raise SmokeFailure(
            "SysON rejected the document: "
            + json.dumps(result, ensure_ascii=False, indent=2)
        )

    return {
        "projectId": project_id,
        "editingContextId": editing_context_id,
        "documentId": result.get("id"),
        "report": result.get("report"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "file",
        type=Path,
        help="SysML v2 textual file to upload",
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Existing SysON project UUID",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="SysON base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional bearer token for authenticated SysON instances",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Import the SysML document read-only",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.file.exists():
        print(f"ERROR: file does not exist: {args.file}", file=sys.stderr)
        return 2

    try:
        result = upload_sysml(
            args.url,
            args.project_id,
            args.file,
            args.token,
            args.read_only,
        )
    except (requests.RequestException, SmokeFailure) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS: SysML document imported through SysON API")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
