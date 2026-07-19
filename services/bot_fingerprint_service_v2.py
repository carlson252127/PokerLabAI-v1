from __future__ import annotations

from pathlib import Path
from typing import Any

from services.bot_profile_service import BotProfileService
from services.tracker_statistics_service import TrackerStatisticsService
from services.open_size_analysis_service import OpenSizeAnalysisService
from services.response_explorer_service import ResponseExplorerService
from services.size_board_strategy_service import SizeBoardStrategyService


class BotFingerprintService:
    """Combines major PokerLab analysis engines into one strategy fingerprint."""

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.profile = BotProfileService(self.database_path)
        self.tracker = TrackerStatisticsService(self.database_path)
        self.open_size = OpenSizeAnalysisService(self.database_path)
        self.response = ResponseExplorerService(self.database_path)
        self.size_board = SizeBoardStrategyService(self.database_path)

    def available_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 500,
    ) -> list[dict[str, Any]]:
        return self.profile.available_entities(
            mode=mode,
            site=site,
            stakes=stakes,
            minimum_hands=minimum_hands,
        )

    def analyze(
        self,
        mode: str,
        entity_name: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 500,
    ) -> dict[str, Any]:
        mode = mode.upper()

        profile = self.profile.build_profile(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            minimum_hands=minimum_hands,
        )
        tracker_mode = "ALIAS" if mode == "ALIAS" else "PLAYER"
        tracker = self.tracker.analyze(
            mode=tracker_mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )["entity"]

        open_report = self.open_size.analyze(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position="",
            minimum_sample=30,
        )

        response_report = self.response.analyze(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position="",
            minimum_sample=30,
        )

        board_report = self.size_board.analyze(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position="",
            texture_filter="",
            minimum_sample=30,
        )

        metrics = {
            row["key"]: row
            for row in profile.get("metrics", [])
        }

        dimensions = self._dimensions(
            metrics=metrics,
            tracker=tracker,
            open_report=open_report,
            response_report=response_report,
            board_report=board_report,
        )

        overall = sum(
            float(row["score"]) * float(row["weight"])
            for row in dimensions
        ) / sum(float(row["weight"]) for row in dimensions)

        tags = self._global_tags(dimensions, open_report, board_report)
        leaks = self._leaks(dimensions, metrics)
        strengths = self._strengths(dimensions)
        classification = self._classification(dimensions, tags)

        return {
            "entity_name": entity_name,
            "hands": int(profile.get("hands") or 0),
            "overall_score": overall,
            "classification": classification,
            "dimensions": dimensions,
            "tags": tags,
            "leaks": leaks,
            "strengths": strengths,
            "best_sizes": open_report.get("best_sizes", []),
            "adaptation_risk": self._adaptation_risk(
                open_report,
                response_report,
            ),
            "summary": self._summary(
                entity_name,
                overall,
                classification,
                strengths,
                leaks,
            ),
        }

    def _dimensions(
        self,
        metrics: dict[str, dict[str, Any]],
        tracker: dict[str, Any],
        open_report: dict[str, Any],
        response_report: dict[str, Any],
        board_report: dict[str, Any],
    ) -> list[dict[str, Any]]:
        def metric_value(key: str) -> float:
            return float(metrics.get(key, {}).get("entity") or 0.0)

        def pool_value(key: str) -> float:
            return float(metrics.get(key, {}).get("pool") or 0.0)

        open_rows = open_report.get("entity", {}).get("rows", [])
        avg_open = float(
            open_report.get("entity", {}).get("avg_size_bb") or 0.0
        )
        fold3b = float(
            open_report.get("entity", {}).get("fold_to_three_bet") or 0.0
        )
        pool_fold3b = float(
            open_report.get("pool", {}).get("fold_to_three_bet") or 0.0
        )

        response_best = response_report.get("best_bucket", {})
        response_ev = float(response_best.get("ev_score") or 0.0)
        board_strongest = board_report.get("strongest_difference", {})
        branch_score = float(
            board_strongest.get("difference_score") or 0.0
        )

        flop_pressure = max(
            metric_value("flop_cbet_ip"),
            metric_value("flop_cbet_oop"),
            metric_value("flop_raise_ip"),
            metric_value("flop_raise_oop"),
        )
        turn_pressure = max(
            metric_value("turn_barrel_ip"),
            metric_value("turn_barrel_oop"),
            metric_value("turn_probe_ip"),
            metric_value("turn_probe_oop"),
            metric_value("turn_raise_ip"),
            metric_value("turn_raise_oop"),
        )
        river_pressure = max(
            metric_value("river_barrel_ip"),
            metric_value("river_barrel_oop"),
            metric_value("river_probe_ip"),
            metric_value("river_probe_oop"),
            metric_value("river_raise_ip"),
            metric_value("river_raise_oop"),
        )

        wwsf = float(tracker.get("wwsf") or 0.0)
        wsd = float(tracker.get("wsd") or 0.0)
        wtsd = float(tracker.get("wtsd") or 0.0)

        return [
            {
                "key": "open_strategy",
                "label": "Open Strategy",
                "score": self._scale(avg_open, 2.0, 4.5),
                "weight": 1.0,
                "value": f"{avg_open:.2f}x",
                "note": "Büyük sizing eğilimi" if avg_open >= 3.2 else "Standart/küçük sizing",
            },
            {
                "key": "threebet_defence",
                "label": "3Bet Defence",
                "score": max(0.0, min(100.0, 100.0 - fold3b)),
                "weight": 1.15,
                "value": f"Fold {fold3b:.1f}%",
                "note": f"Pooldan {fold3b - pool_fold3b:+.1f} puan",
            },
            {
                "key": "flop_pressure",
                "label": "Flop Pressure",
                "score": flop_pressure,
                "weight": 1.0,
                "value": f"{flop_pressure:.1f}%",
                "note": "CBet/XR birleşik baskı",
            },
            {
                "key": "turn_pressure",
                "label": "Turn Pressure",
                "score": turn_pressure,
                "weight": 1.1,
                "value": f"{turn_pressure:.1f}%",
                "note": "Barrel/probe/XR birleşik baskı",
            },
            {
                "key": "river_pressure",
                "label": "River Pressure",
                "score": river_pressure,
                "weight": 1.0,
                "value": f"{river_pressure:.1f}%",
                "note": "Barrel/probe/raise birleşik baskı",
            },
            {
                "key": "wwsf",
                "label": "WWSF",
                "score": self._scale(wwsf, 42.0, 58.0),
                "weight": 1.2,
                "value": f"{wwsf:.1f}%",
                "note": "Postflop pot kazanma",
            },
            {
                "key": "showdown",
                "label": "Showdown Quality",
                "score": (
                    self._scale(wsd, 47.0, 58.0) * 0.7
                    + self._scale(30.0 - abs(wtsd - 27.0), 15.0, 30.0) * 0.3
                ),
                "weight": 1.0,
                "value": f"W$SD {wsd:.1f} / WTSD {wtsd:.1f}",
                "note": "Showdown seçimi ve kalite",
            },
            {
                "key": "response_exploitation",
                "label": "Pool Response Exploit",
                "score": response_ev,
                "weight": 1.15,
                "value": f"{response_ev:.0f}/100",
                "note": "Pool fold/3bet/call tepkisini kullanma",
            },
            {
                "key": "branch_complexity",
                "label": "Size-Board Branching",
                "score": branch_score,
                "weight": 0.9,
                "value": f"{branch_score:.0f}/100",
                "note": "Size'ların farklı board planlarıyla ilişkisi",
            },
        ]

    def _global_tags(
        self,
        dimensions: list[dict[str, Any]],
        open_report: dict[str, Any],
        board_report: dict[str, Any],
    ) -> list[str]:
        scores = {row["key"]: float(row["score"]) for row in dimensions}
        tags: list[str] = []

        if scores["open_strategy"] >= 65:
            tags.append("Large Open Strategy")
        if scores["threebet_defence"] <= 42:
            tags.append("High Fold vs 3Bet")
        elif scores["threebet_defence"] >= 58:
            tags.append("3Bet Resistant")
        if scores["flop_pressure"] >= 70:
            tags.append("Flop Pressure")
        if scores["turn_pressure"] >= 55:
            tags.append("Turn Heavy")
        if scores["river_pressure"] >= 55:
            tags.append("River Pressure")
        if scores["wwsf"] >= 65:
            tags.append("High Realization")
        if scores["showdown"] >= 65:
            tags.append("Strong Showdown")
        if scores["branch_complexity"] >= 35:
            tags.append("Structured Branching")
        else:
            tags.append("RNG/Mixed Branch Candidate")

        return tags[:7]

    def _leaks(
        self,
        dimensions: list[dict[str, Any]],
        metrics: dict[str, dict[str, Any]],
    ) -> list[str]:
        notes: list[str] = []
        scores = {row["key"]: float(row["score"]) for row in dimensions}

        if scores["threebet_defence"] < 42:
            notes.append("Büyük sizing branch'lerinde 3bet karşısı fazla teslim olabilir.")
        if scores["turn_pressure"] < 38:
            notes.append("Flop sonrası turn give-up frekansı yüksek olabilir.")
        if scores["river_pressure"] < 38:
            notes.append("River baskısı düşük; bluff-catch artışıyla exploit edilebilir.")
        if scores["showdown"] < 45:
            notes.append("Showdown seçimi veya river call kalitesi zayıf olabilir.")
        if scores["branch_complexity"] < 20:
            notes.append("Open size değişse de postflop planı çok benzer; sizing bilgi sızdırmayabilir ama gereksiz maliyet yaratabilir.")

        return notes[:5] or ["Belirgin büyük leak bulunamadı."]

    def _strengths(
        self,
        dimensions: list[dict[str, Any]],
    ) -> list[str]:
        ranked = sorted(
            dimensions,
            key=lambda row: float(row["score"]),
            reverse=True,
        )
        return [
            f"{row['label']}: {row['value']}"
            for row in ranked[:4]
        ]

    def _classification(
        self,
        dimensions: list[dict[str, Any]],
        tags: list[str],
    ) -> str:
        scores = {row["key"]: float(row["score"]) for row in dimensions}

        if scores["open_strategy"] >= 65 and scores["flop_pressure"] >= 68:
            return "Large-Open Pressure Reg"
        if scores["branch_complexity"] >= 40 and scores["wwsf"] >= 60:
            return "Structured High-Realization Bot Profile"
        if scores["showdown"] >= 65 and scores["river_pressure"] >= 50:
            return "Showdown-Efficient Value Profile"
        if scores["threebet_defence"] < 40:
            return "Exploit-Open / Overfold Profile"
        return "Mixed Strategy Regular Profile"

    def _adaptation_risk(
        self,
        open_report: dict[str, Any],
        response_report: dict[str, Any],
    ) -> str:
        entity = open_report.get("entity", {})
        avg_size = float(entity.get("avg_size_bb") or 0.0)
        fold3b = float(entity.get("fold_to_three_bet") or 0.0)
        best = response_report.get("best_bucket", {})
        threebet = float(best.get("pool_3bet_preflop") or 0.0)

        if avg_size >= 3.3 and fold3b >= 62:
            return "Yüksek"
        if avg_size >= 3.0 and threebet >= 20:
            return "Orta"
        return "Düşük"

    def _summary(
        self,
        entity_name: str,
        overall: float,
        classification: str,
        strengths: list[str],
        leaks: list[str],
    ) -> str:
        return (
            f"{entity_name}: {classification}. Fingerprint Score "
            f"{overall:.0f}/100. En güçlü alan: {strengths[0]}. "
            f"Öncelikli kontrol: {leaks[0]}"
        )

    def _scale(self, value: float, low: float, high: float) -> float:
        if high <= low:
            return 50.0
        return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))
