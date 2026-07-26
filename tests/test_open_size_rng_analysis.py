from __future__ import annotations

from pathlib import Path
import random
import tempfile
import unittest

from services.open_size_rng_analysis_service import OpenSizeRngAnalysisService
from services.open_size_rng_model_validation import ComparableOpenSizeModels


def record(
    index: int,
    size: float,
    *,
    player: str = "bot-a",
    position: str = "BTN",
    session: str | None = None,
    sb: str = "reg",
    bb: str = "reg",
    stack: float = 100,
) -> dict:
    return {
        "hand_id": f"h-{index}",
        "timestamp": (
            f"2026-01-{1 + index // 1440:02d} "
            f"{(index // 60) % 24:02d}:{index % 60:02d}:00"
        ),
        "session_id": session or f"s-{index // 50}",
        "table_id": f"t-{index // 25}",
        "site": "test", "stake": "0.5/1", "ante": 0,
        "player": player, "position": position,
        "open_size_bb": size, "effective_stack_bb": stack,
        "players_dealt": 6, "sb_profile": sb, "bb_profile": bb,
    }


class OpenSizeRngAnalysisTests(unittest.TestCase):
    def test_comparable_models_share_target_sample_folds_and_weighting(self) -> None:
        rows = [
            OpenSizeRngAnalysisService._normalize(
                record(
                    i,
                    (2.5, 3.0, 3.5, 4.0)[i % 4],
                    player=f"bot-{i % 6}",
                    session=f"session-{i // 20}",
                )
            )
            for i in range(300)
        ]
        result = ComparableOpenSizeModels.evaluate(
            rows,
            bootstrap_iterations=20,
            permutation_iterations=5,
        )
        self.assertTrue(result["same_sample"])
        self.assertTrue(result["same_folds"])
        self.assertTrue(result["same_weighting"])
        samples = {row["records"] for row in result["metrics"]}
        targets = {row["target_classes"] for row in result["metrics"]}
        self.assertEqual(len(samples), 1)
        self.assertEqual(len(targets), 1)

    def test_player_and_session_groups_do_not_cross_folds(self) -> None:
        rows = [
            OpenSizeRngAnalysisService._normalize(
                record(
                    i,
                    4.0 if i % 2 else 2.5,
                    player=f"bot-{i % 5}",
                    session=f"session-{i // 10}",
                )
            )
            for i in range(200)
        ]
        for mode in ("session", "player"):
            fold_map = ComparableOpenSizeModels._fold_map(rows, 5, mode)
            ComparableOpenSizeModels.assert_no_leakage(rows, fold_map, mode)

    def test_independent_fixed_mixture_is_rng_leaning(self) -> None:
        rng = random.Random(20260726)
        rows = [
            record(i, 4.0 if rng.random() < 0.35 else 2.5)
            for i in range(1200)
        ]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=750)
        self.assertEqual(report.classification, "RNG_LEANING")

    def test_blind_dependent_data_is_strategy_leaning(self) -> None:
        rows = [
            record(
                i, 4.0 if i % 2 else 2.5,
                sb="fish" if i % 2 else "reg",
                bb="loose" if i % 2 else "reg",
            )
            for i in range(1000)
        ]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=750)
        self.assertEqual(report.classification, "STRATEGY_LEANING")
        self.assertGreater(report.condition_effects[0]["cramers_v"], 0.5)

    def test_two_stage_data_is_hybrid_leaning(self) -> None:
        rows = []
        for i in range(1200):
            high = i % 3 != 0 if i % 2 else i % 5 == 0
            if high:
                size = 3.5 if (i * 17) % 2 else 4.0
            else:
                size = 2.0 if (i * 13) % 2 else 2.5
            rows.append(record(i, size, sb="fish" if i % 2 else "reg"))
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=750)
        self.assertEqual(report.classification, "HYBRID_LEANING")

    def test_alternating_sequence_has_serial_dependence(self) -> None:
        rows = [record(i, 4.0 if i % 2 else 2.5) for i in range(800)]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=100)
        self.assertTrue(report.serial_metrics["serial_dependence"])
        self.assertLess(report.serial_metrics["lag1_autocorrelation"], -0.9)

    def test_duplicate_hands_are_counted_once(self) -> None:
        rows = [record(i, 2.5) for i in range(20)]
        rows += [dict(rows[0]), dict(rows[1])]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=1)
        self.assertEqual(report.used_records, 20)
        self.assertEqual(report.duplicate_records, 2)

    def test_player_dominance_reports_both_weightings(self) -> None:
        rows = [
            record(i, 4.0, player="dominant") for i in range(800)
        ] + [
            record(1000 + i, 2.5, player=f"small-{i % 4}")
            for i in range(200)
        ]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=100)
        self.assertGreater(report.player_shares[0]["share"], 0.25)
        self.assertNotEqual(
            report.natural_high_size_rate,
            report.equal_player_high_size_rate,
        )
        self.assertTrue(any("%25" in x for x in report.diagnostics))

    def test_low_sample_is_inconclusive(self) -> None:
        rows = [record(i, 4.0 if i % 2 else 2.5) for i in range(100)]
        report = OpenSizeRngAnalysisService.analyze_records(rows)
        self.assertEqual(report.classification, "INCONCLUSIVE")

    def test_position_confounding_is_visible_not_mislabeled_rng(self) -> None:
        rows = [
            record(
                i, 4.0 if i % 2 else 2.5,
                position="BTN" if i % 2 else "UTG",
                sb="fish" if i % 2 else "reg",
            )
            for i in range(1000)
        ]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=500)
        effects = {x["condition"]: x for x in report.condition_effects}
        self.assertGreater(effects["position"]["cramers_v"], 0.5)
        self.assertNotEqual(report.classification, "RNG_LEANING")

    def test_grouped_split_does_not_memorize_session_rows(self) -> None:
        rows = []
        for session in range(30):
            high = session % 2
            for offset in range(30):
                item = record(
                    session * 100 + offset,
                    4.0 if high else 2.5,
                    session=f"session-{session}",
                )
                item["timestamp"] = "2026-01-01 12:00:00"
                item["table_id"] = "shared-table-profile"
                rows.append(item)
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=500)
        conditional = next(
            x for x in report.model_metrics
            if x["model"] == "B_CONDITIONAL_HIGH"
        )
        # Session identity is a split group, not a predictor.
        self.assertLessEqual(conditional["auc"], 0.60)

    def test_missing_fields_are_diagnostic_not_crash_and_exports_exist(self) -> None:
        rows = [
            {"hand_id": f"h{i}", "player": "bot", "open_size_bb": 2.5}
            for i in range(30)
        ]
        report = OpenSizeRngAnalysisService.analyze_records(rows, min_sample=10)
        with tempfile.TemporaryDirectory() as directory:
            OpenSizeRngAnalysisService.export_report(report, directory)
            expected = {
                "open_size_rng_summary.md",
                "open_size_rng_by_position.csv",
                "open_size_rng_condition_effects.csv",
                "open_size_rng_transitions.csv",
                "open_size_rng_model_metrics.csv",
                "open_size_rng_player_share.csv",
                "open_size_rng_session_stability.csv",
            }
            self.assertEqual(expected, {p.name for p in Path(directory).iterdir()})


if __name__ == "__main__":
    unittest.main()
