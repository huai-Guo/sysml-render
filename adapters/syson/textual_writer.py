from __future__ import annotations

from dataclasses import dataclass
import json
import uuid
from typing import Any

import requests


class SysONTextualWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class TextualWriteResult:
    acknowledged: bool
    messages: tuple[str, ...]


class SysONTextualWriter:
    """Insert validated SysML statements below an existing semantic owner.

    This calls SysON's native GraphQL insertTextualSysMLv2 tool, not a new
    uploadDocument (which would import an additional standalone document).
    """

    QUERY = """
mutation InsertTextualSysMLv2($input: InsertTextualSysMLv2Input!) {
  insertTextualSysMLv2(input: $input) {
    __typename
    ... on SuccessPayload {
      id
      messages { body level }
    }
    ... on ErrorPayload {
      messages { body level }
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def insert(
        self,
        *,
        editing_context_id: str,
        owner_element_id: str,
        textual_content: str,
    ) -> TextualWriteResult:
        if not editing_context_id or not owner_element_id or not textual_content.strip():
            raise ValueError("editing context, semantic owner and SysML text are required")
        response = self.session.post(
            f"{self.base_url}/api/graphql",
            json={
                "query": self.QUERY,
                "variables": {
                    "input": {
                        "id": str(uuid.uuid4()),
                        "editingContextId": editing_context_id,
                        "objectId": owner_element_id,
                        "textualContent": textual_content,
                    }
                },
            },
            headers=self._headers(),
            timeout=120,
        )
        if response.status_code != 200:
            raise SysONTextualWriteError(
                f"SysON GraphQL HTTP {response.status_code}: {response.text[:1200]}"
            )
        body = response.json()
        if body.get("errors"):
            raise SysONTextualWriteError(json.dumps(body["errors"], ensure_ascii=False))
        payload = body.get("data", {}).get("insertTextualSysMLv2") or {}
        messages = tuple(
            str(item.get("body", ""))
            for item in payload.get("messages", []) or []
            if isinstance(item, dict)
        )
        if payload.get("__typename") != "SuccessPayload":
            raise SysONTextualWriteError(
                "SysON rejected textual insertion: " + "; ".join(messages)
            )
        return TextualWriteResult(acknowledged=True, messages=messages)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
