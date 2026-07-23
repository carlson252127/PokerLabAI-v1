from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from models.analysis_period import AnalysisPeriod
from models.comparison_node import ComparisonNode
from models.comparison_results import (
    ActionFrequency, CohortReference, GTOReferenceStats, GroupNodeStats,
    NodeComparisonResult, SampleQuality,
)
from models.exploit_models import (
    ExploitRecommendation, ExploitScoreBreakdown,
)
from models.node_identity import InMemoryNodeIdentityRegistry


NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


def score(**overrides: object) -> ExploitScoreBreakdown:
    values: dict[str, object] = {
        "total_score": 50, "score_type": "FREQUENCY", "config_version": "v1",
        "deviation_component": .5, "confidence_component": .5,
        "occurrence_component": .5, "economic_component": .5,
        "reference_component": .5, "trend_component": .5,
        "feasibility_component": .5, "quality_penalty": .1,
        "dominance_penalty": .1, "fallback_penalty": .1,
        "missing_economics_penalty": .1, "input_coverage": .8,
    }
    values.update(overrides)
    return ExploitScoreBreakdown(**values)


def quality(low: bool = False) -> SampleQuality:
    return SampleQuality(.8, .2, .5, 100, 20, 120, low, False, "v1")


def group() -> GroupNodeStats:
    cohort = CohortReference("HUMAN_POOL", "coinpoker:pool", 1, NOW, "Pool")
    return GroupNodeStats(
        "Pool", cohort, (ActionFrequency("FOLD", 10, 4, 8, 3),),
        8, 3, 10, NOW, datetime(2026, 7, 25, tzinfo=timezone.utc),
    )


class ActionFrequencyTests(unittest.TestCase):
    def test_zero_opportunities_frequency_none(self) -> None:
        self.assertIsNone(ActionFrequency("BET", 0, 0).frequency)

    def test_two_of_four_is_half(self) -> None:
        self.assertEqual(ActionFrequency("CALL", 4, 2).frequency, .5)

    def test_count_cannot_exceed_opportunities(self) -> None:
        with self.assertRaises(ValueError):
            ActionFrequency("FOLD", 3, 4)

    def test_negative_count_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ActionFrequency("FOLD", 3, -1)

    def test_invalid_action_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ActionFrequency("SHOW", 1, 1)


class GTOTests(unittest.TestCase):
    def test_unavailable_does_not_become_zero_frequency(self) -> None:
        gto = GTOReferenceStats(resolution_type="UNAVAILABLE")
        self.assertEqual(gto.actions, ())
        self.assertIsNone(gto.match_quality)

    def test_similar_fallback_is_not_exact(self) -> None:
        gto = GTOReferenceStats(
            actions=(ActionFrequency("CHECK", 10, 5), ActionFrequency("BET", 10, 5)),
            resolution_type="SIMILAR_BOARD_FALLBACK", match_quality=.8,
        )
        self.assertNotEqual(gto.resolution_type.value, "EXACT")

    def test_match_quality_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GTOReferenceStats(
                actions=(ActionFrequency("CHECK", 1, 1),),
                resolution_type="EXACT", match_quality=1.1,
            )

    def test_missing_gto_supported_in_result(self) -> None:
        result = make_result()
        self.assertIsNone(result.gto_stats)


class ScoreTests(unittest.TestCase):
    def test_frequency_score_without_ev_component(self) -> None:
        self.assertIsNone(score().ev_component)

    def test_ev_score_without_ev_component_rejected(self) -> None:
        with self.assertRaises(ValueError):
            score(score_type="EV_BACKED")

    def test_total_above_100_rejected(self) -> None:
        with self.assertRaises(ValueError):
            score(total_score=101)

    def test_component_outside_unit_interval_rejected(self) -> None:
        with self.assertRaises(ValueError):
            score(confidence_component=1.1)

    def test_low_sample_strong_recommendation_is_downgraded(self) -> None:
        recommendation = ExploitRecommendation(
            "Review folds", "Pool", "FOLD", "INCREASE", "Synthetic deviation",
            8, 100, .7, "STRONG_FREQUENCY_CANDIDATE", score(),
            sample_quality=quality(True),
        )
        self.assertEqual(recommendation.strength.value, "REVIEW_CANDIDATE")
        self.assertTrue(recommendation.risk_warnings)


def make_result() -> NodeComparisonResult:
    node = ComparisonNode(street="FLOP", board="Ah 7d 2c")
    identity = InMemoryNodeIdentityRegistry().resolve_identity(node, 1, "board-v1")
    return NodeComparisonResult(
        identity,
        AnalysisPeriod("2026-07-01", "2026-08-01"),
        group(),
        gto_stats=None,
        pool_sample_quality=quality(),
        query_duration_ms=2.5,
        calculated_at=NOW,
        source_generation="synthetic-v1",
        warnings=("same", "same"),
    )


class SerializationTests(unittest.TestCase):
    def test_nested_result_round_trip(self) -> None:
        original = make_result()
        restored = NodeComparisonResult.from_dict(
            json.loads(json.dumps(original.to_dict()))
        )
        self.assertEqual(original, restored)
        self.assertEqual(restored.warnings, ("same",))

    def test_uuid_and_datetime_types_preserved(self) -> None:
        restored = NodeComparisonResult.from_dict(make_result().to_dict())
        self.assertEqual(restored.node_identity.node_id.version, 4)
        self.assertIsNotNone(restored.calculated_at.tzinfo)

    def test_enum_values_are_stable_strings(self) -> None:
        data = quality().to_dict()
        cohort = group().cohort.to_dict()
        self.assertEqual(cohort["cohort_type"], "HUMAN_POOL")
        self.assertEqual(data["model_version"], "v1")

    def test_unknown_critical_field_is_rejected(self) -> None:
        data = make_result().to_dict()
        data["unknown_critical"] = "value"
        with self.assertRaises(TypeError):
            NodeComparisonResult.from_dict(data)


if __name__ == "__main__":
    unittest.main()
