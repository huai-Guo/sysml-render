from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import requests

from semantic_provider import first_ref, ref_id


class SysONAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class SysONRestConfig:
    base_url: str
    project_id: str
    token: str | None = None
    commit_id: str | None = None

    @property
    def effective_commit_id(self) -> str:
        return self.commit_id or self.project_id


class SysONRestAdapter:
    """Read semantic SysML data from SysON's SysML v2 REST API.

    Reading semantic data uses the standard-shaped REST surface. GraphQL should
    be reserved for SysON/Sirius-specific capabilities such as representation
    creation or editing tools.
    """

    RELATIONSHIP_KINDS = frozenset(
        {
            "ConnectionUsage",
            "FlowUsage",
            "InterfaceUsage",
            "Dependency",
            "SatisfyRequirementUsage",
            "RequirementDerivation",
            "AllocationUsage",
            "SuccessionAsUsage",
            "TransitionUsage",
        }
    )

    INTERNAL_RELATIONSHIP_KINDS = frozenset(
        {
            "OwningMembership",
            "FeatureMembership",
            "FeatureTyping",
            "Subsetting",
            "Redefinition",
            "ReferenceSubsetting",
            "NamespaceImport",
            "MembershipImport",
        }
    )

    def __init__(
        self,
        config: SysONRestConfig,
        *,
        session: requests.Session | Any | None = None,
    ):
        self.config = config
        self.session = session or requests.Session()
        self._resolved_commit_id: str | None = config.commit_id

    def snapshot(self) -> dict[str, Any]:
        raw_elements = self.fetch_elements()
        return self.normalize_elements(raw_elements)

    def fetch_elements(self) -> list[dict[str, Any]]:
        url = self._url("elements")
        response = self.session.get(
            url,
            headers=self._headers(),
            timeout=120,
        )
        if response.status_code != 200:
            raise SysONAdapterError(
                f"SysON elements API returned HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise SysONAdapterError("SysON elements API did not return a list")
        return payload

    def fetch_element(self, element_id: str) -> dict[str, Any]:
        url = self._url(f"elements/{element_id}")
        response = self.session.get(
            url,
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code != 200:
            raise SysONAdapterError(
                f"SysON element API returned HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise SysONAdapterError("SysON element API did not return an object")
        return payload

    def fetch_relationships(self, element_id: str) -> list[dict[str, Any]]:
        url = self._url(f"elements/{element_id}/relationships")
        response = self.session.get(
            url,
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code != 200:
            raise SysONAdapterError(
                f"SysON relationships API returned HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise SysONAdapterError(
                "SysON relationships API did not return a list"
            )
        return payload

    def fetch_roots(self) -> list[dict[str, Any]]:
        url = (
            f"{self.config.base_url.rstrip('/')}/api/rest/projects/"
            f"{self.config.project_id}/commits/"
            f"{self._commit_id()}/roots"
        )
        response = self.session.get(
            url,
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code != 200:
            raise SysONAdapterError(
                f"SysON roots API returned HTTP {response.status_code}: "
                f"{response.text[:2000]}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise SysONAdapterError("SysON roots API did not return a list")
        return payload

    def normalize_elements(
        self,
        raw_elements: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        raw = [item for item in raw_elements if isinstance(item, dict)]
        by_id = {
            element_id: item
            for item in raw
            if (element_id := ref_id(item))
        }

        owned_parent = self._build_owned_parent_index(raw)
        normalized_elements: list[dict[str, Any]] = []
        normalized_relationships: list[dict[str, Any]] = []

        for item in raw:
            element_id = ref_id(item)
            kind = item.get("@type")
            if not element_id or not isinstance(kind, str):
                continue

            if kind in self.INTERNAL_RELATIONSHIP_KINDS:
                continue

            if kind in self.RELATIONSHIP_KINDS:
                relationship = self._normalize_relationship(item)
                if relationship:
                    normalized_relationships.append(relationship)
                # Some relationship usages can also be visible nodes in
                # specialized views, but the initial structural renderer keeps
                # the semantic relation in the edge channel.
                continue

            parent_id = self._semantic_parent_id(item, owned_parent, by_id)
            normalized = {
                "id": element_id,
                "name": self._name(item, element_id),
                "kind": kind,
                "parentId": parent_id,
            }

            type_ref = self._type_ref(item)
            if type_ref:
                normalized["typeRef"] = type_ref

            qualified_name = item.get("qualifiedName")
            if isinstance(qualified_name, str):
                normalized["qualifiedName"] = qualified_name

            normalized_elements.append(normalized)

        return {
            "schemaVersion": 1,
            "modelId": self.config.project_id,
            "source": {
                "kind": "syson-rest",
                "projectId": self.config.project_id,
                "commitId": (
                    self._resolved_commit_id
                    or self.config.effective_commit_id
                ),
            },
            "elements": normalized_elements,
            "relationships": normalized_relationships,
        }

    def _normalize_relationship(
        self,
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        element_id = ref_id(item)
        kind = item.get("@type")
        if not element_id or not isinstance(kind, str):
            return None

        source_id = (
            first_ref(item.get("sourceFeature"))
            or first_ref(item.get("source"))
        )
        target_id = (
            first_ref(item.get("targetFeature"))
            or first_ref(item.get("target"))
        )

        result: dict[str, Any] = {
            "id": element_id,
            "name": self._name(item, element_id),
            "kind": kind,
            "ownerId": first_ref(item.get("owner"))
            or first_ref(item.get("owningNamespace"))
            or first_ref(item.get("owningType")),
        }

        if source_id:
            result["sourceId"] = source_id
        if target_id:
            result["targetId"] = target_id

        related = [
            candidate
            for value in item.get("relatedFeature", [])
            if (candidate := ref_id(value))
        ]
        if related:
            result["relatedFeatureIds"] = related

        return result

    def _semantic_parent_id(
        self,
        item: dict[str, Any],
        owned_parent: dict[str, str],
        by_id: dict[str, dict[str, Any]],
    ) -> str | None:
        element_id = ref_id(item)
        candidates = (
            first_ref(item.get("owner")),
            first_ref(item.get("owningNamespace")),
            first_ref(item.get("owningType")),
            first_ref(item.get("owningUsage")),
            owned_parent.get(element_id) if element_id else None,
        )
        for candidate in candidates:
            if candidate and candidate in by_id:
                parent_kind = by_id[candidate].get("@type")
                if parent_kind not in self.INTERNAL_RELATIONSHIP_KINDS:
                    return candidate
        return owned_parent.get(element_id) if element_id else None

    def _build_owned_parent_index(
        self,
        raw: list[dict[str, Any]],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for parent in raw:
            parent_id = ref_id(parent)
            if not parent_id:
                continue
            for child in parent.get("ownedElement", []):
                child_id = ref_id(child)
                if child_id:
                    result.setdefault(child_id, parent_id)
        return result

    @staticmethod
    def _type_ref(item: dict[str, Any]) -> str | None:
        for key in (
            "type",
            "definition",
            "partDefinition",
            "portDefinition",
            "itemDefinition",
            "occurrenceDefinition",
        ):
            candidate = first_ref(item.get(key))
            if candidate:
                return candidate
        return None

    @staticmethod
    def _name(item: dict[str, Any], fallback: str) -> str:
        for key in ("name", "declaredName", "qualifiedName"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        return fallback

    def _url(self, suffix: str) -> str:
        return (
            f"{self.config.base_url.rstrip('/')}/api/rest/projects/"
            f"{self.config.project_id}/commits/"
            f"{self._commit_id()}/{suffix}"
        )

    def _commit_id(self) -> str:
        if self._resolved_commit_id:
            return self._resolved_commit_id

        commits_url = (
            f"{self.config.base_url.rstrip('/')}/api/rest/projects/"
            f"{self.config.project_id}/commits"
        )
        response = self.session.get(
            commits_url,
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, list) and payload:
                candidate = payload[-1].get("@id")
                if isinstance(candidate, str) and candidate:
                    self._resolved_commit_id = candidate
                    return candidate

        # Backward compatibility with older SysON deployments where projectId
        # was accepted as the single effective commit identifier.
        self._resolved_commit_id = self.config.project_id
        return self._resolved_commit_id

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return headers
