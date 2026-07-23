"""Persistent identity models without production persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from models.comparison_node import ComparisonNode


def _aware_datetime(value: datetime | str, field_name: str) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    return result


@dataclass(frozen=True, slots=True)
class NodeIdentity:
    """Stable UUID identity associated with a versioned deterministic node key."""

    node_id: UUID | str
    node_key: str
    node_version: int
    taxonomy_version: str
    definition: ComparisonNode
    created_at: datetime | str
    updated_at: datetime | str
    is_active: bool = True
    supersedes_node_id: UUID | str | None = None

    def __post_init__(self) -> None:
        node_id = self.node_id if isinstance(self.node_id, UUID) else UUID(str(self.node_id))
        object.__setattr__(self, "node_id", node_id)
        if not isinstance(self.definition, ComparisonNode):
            raise TypeError("definition must be a ComparisonNode.")
        expected = self.definition.to_key()
        if str(self.node_key) != expected:
            raise ValueError("node_key does not match definition.to_key().")
        version = int(self.node_version)
        if version < 1:
            raise ValueError("node_version must be at least 1.")
        object.__setattr__(self, "node_version", version)
        taxonomy = str(self.taxonomy_version or "").strip()
        if not taxonomy:
            raise ValueError("taxonomy_version cannot be empty.")
        object.__setattr__(self, "taxonomy_version", taxonomy)
        created = _aware_datetime(self.created_at, "created_at")
        updated = _aware_datetime(self.updated_at, "updated_at")
        if created > updated:
            raise ValueError("created_at cannot be after updated_at.")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        supersedes = (
            self.supersedes_node_id
            if isinstance(self.supersedes_node_id, UUID)
            else UUID(str(self.supersedes_node_id))
            if self.supersedes_node_id is not None
            else None
        )
        if supersedes == node_id:
            raise ValueError("A node cannot supersede itself.")
        object.__setattr__(self, "supersedes_node_id", supersedes)
        object.__setattr__(self, "is_active", bool(self.is_active))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "node_key": self.node_key,
            "node_version": self.node_version,
            "taxonomy_version": self.taxonomy_version,
            "definition": self.definition.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "supersedes_node_id": (
                str(self.supersedes_node_id) if self.supersedes_node_id else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NodeIdentity:
        values = dict(data)
        values["definition"] = ComparisonNode.from_dict(values["definition"])
        return cls(**values)


class InMemoryNodeIdentityRegistry:
    """Test-only identity resolver with no database or filesystem access."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, int], NodeIdentity] = {}

    def resolve_identity(
        self,
        node: ComparisonNode,
        node_version: int,
        taxonomy_version: str,
        *,
        supersedes_node_id: UUID | str | None = None,
    ) -> NodeIdentity:
        key = (node.to_key(), int(node_version))
        existing = self._items.get(key)
        if existing is not None:
            if existing.taxonomy_version != str(taxonomy_version).strip():
                raise ValueError(
                    "taxonomy_version changed for the same node_key/node_version; "
                    "increment node_version."
                )
            return existing
        now = datetime.now(timezone.utc)
        identity = NodeIdentity(
            node_id=uuid4(),
            node_key=key[0],
            node_version=key[1],
            taxonomy_version=taxonomy_version,
            definition=node,
            created_at=now,
            updated_at=now,
            supersedes_node_id=supersedes_node_id,
        )
        self._items[key] = identity
        return identity
