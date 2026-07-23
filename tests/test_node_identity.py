from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest
from uuid import uuid4

from models.analysis_period import AnalysisPeriod
from models.comparison_node import ComparisonNode
from models.node_identity import InMemoryNodeIdentityRegistry, NodeIdentity


class AnalysisPeriodTests(unittest.TestCase):
    def test_valid_half_open_period(self) -> None:
        period = AnalysisPeriod("2026-01-01", "2026-02-01")
        self.assertLess(period.date_from, period.date_to)

    def test_equal_dates_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AnalysisPeriod("2026-01-01", "2026-01-01")

    def test_reverse_dates_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AnalysisPeriod("2026-02-01", "2026-01-01")

    def test_iso_round_trip(self) -> None:
        period = AnalysisPeriod("2026-01-01", "2026-02-01", bucket_type="MONTH")
        self.assertEqual(period, AnalysisPeriod.from_dict(period.to_dict()))

    def test_label_does_not_affect_equality(self) -> None:
        self.assertEqual(
            AnalysisPeriod("2026-01-01", "2026-02-01", label="Current"),
            AnalysisPeriod("2026-01-01", "2026-02-01", label="Başka"),
        )


class NodeIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.node = ComparisonNode(street="FLOP", board="Ah 7d 2c")
        self.registry = InMemoryNodeIdentityRegistry()

    def test_same_key_version_returns_same_id(self) -> None:
        first = self.registry.resolve_identity(self.node, 1, "board-v1")
        second = self.registry.resolve_identity(self.node, 1, "board-v1")
        self.assertEqual(first.node_id, second.node_id)

    def test_new_node_version_returns_new_identity(self) -> None:
        first = self.registry.resolve_identity(self.node, 1, "board-v1")
        second = self.registry.resolve_identity(
            self.node, 2, "board-v2", supersedes_node_id=first.node_id
        )
        self.assertNotEqual(first.node_id, second.node_id)
        self.assertEqual(second.supersedes_node_id, first.node_id)

    def test_taxonomy_change_requires_node_version_change(self) -> None:
        self.registry.resolve_identity(self.node, 1, "board-v1")
        with self.assertRaisesRegex(ValueError, "increment node_version"):
            self.registry.resolve_identity(self.node, 1, "board-v2")

    def test_definition_key_mismatch_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        with self.assertRaisesRegex(ValueError, "does not match"):
            NodeIdentity(uuid4(), "bad-key", 1, "v1", self.node, now, now)

    def test_cannot_supersede_itself(self) -> None:
        now = datetime.now(timezone.utc)
        identity_id = uuid4()
        with self.assertRaisesRegex(ValueError, "supersede itself"):
            NodeIdentity(
                identity_id, self.node.to_key(), 1, "v1", self.node,
                now, now, supersedes_node_id=identity_id,
            )

    def test_created_after_updated_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            NodeIdentity(
                uuid4(), self.node.to_key(), 1, "v1", self.node,
                now, now - timedelta(seconds=1),
            )

    def test_inactive_identity_round_trip(self) -> None:
        now = datetime.now(timezone.utc)
        original = NodeIdentity(
            uuid4(), self.node.to_key(), 1, "v1", self.node,
            now, now, is_active=False,
        )
        restored = NodeIdentity.from_dict(
            json.loads(json.dumps(original.to_dict()))
        )
        self.assertEqual(original, restored)
        self.assertFalse(restored.is_active)
        self.assertEqual(
            restored.node_key,
            restored.definition.to_key(),
        )

    def test_identity_json_round_trip_preserves_definition_key(self) -> None:
        original = self.registry.resolve_identity(self.node, 1, "board-v1")
        restored = NodeIdentity.from_dict(
            json.loads(json.dumps(original.to_dict()))
        )
        self.assertEqual(original.node_key, restored.definition.to_key())


if __name__ == "__main__":
    unittest.main()
