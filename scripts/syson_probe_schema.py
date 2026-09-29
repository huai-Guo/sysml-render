#!/usr/bin/env python3
"""Probe the live Sirius Web GraphQL schema used by SysON.

The script deliberately discovers representation-related types at runtime.
GraphQL is an experimental SysON/Sirius Web API, so sysml-render should not
hard-code an assumed schema before the Phase-0 spike proves it.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

INTROSPECTION = """
query IntrospectSchema {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind
      name
      fields {
        name
        type {
          kind
          name
          ofType {
            kind
            name
          }
        }
      }
    }
  }
}
"""

KEYWORDS = (
    "representation",
    "diagram",
    "view",
    "editingcontext",
    "semantic",
    "object",
    "tool",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--token", default=None)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete matching type data as JSON",
    )
    return parser.parse_args()


def request_schema(url: str, token: str | None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(
        f"{url.rstrip('/')}/api/graphql",
        json={"query": INTROSPECTION},
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload["data"]["__schema"]


def is_interesting(type_info: dict[str, Any]) -> bool:
    name = (type_info.get("name") or "").lower()
    fields = " ".join(
        (field.get("name") or "").lower()
        for field in (type_info.get("fields") or [])
    )
    haystack = f"{name} {fields}"
    return any(keyword in haystack for keyword in KEYWORDS)


def main() -> int:
    args = parse_args()
    try:
        schema = request_schema(args.url, args.token)
    except (requests.RequestException, RuntimeError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    matches = sorted(
        (t for t in schema.get("types", []) if is_interesting(t)),
        key=lambda t: t.get("name") or "",
    )

    print(f"Query root: {schema.get('queryType')}")
    print(f"Mutation root: {schema.get('mutationType')}")
    print(f"Matching types: {len(matches)}")

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    for type_info in matches:
        name = type_info.get("name")
        field_names = [
            field.get("name")
            for field in (type_info.get("fields") or [])
            if field.get("name")
        ]
        preview = ", ".join(field_names[:14])
        suffix = " ..." if len(field_names) > 14 else ""
        print(f"- {name}: {preview}{suffix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
