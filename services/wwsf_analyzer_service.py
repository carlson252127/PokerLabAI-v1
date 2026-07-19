from __future__ import annotations

from pathlib import Path
from typing import Any

from services.bot_profile_service import BotProfileService
from services.tracker_statistics_service import TrackerStatisticsService


class WWSFAnalyzerService:
    """Heuristic WWSF attribution engine.

    It explains which profile deltas are most associated with the observed
    WWSF gap. It is not a causal EV model.
    """

    CATEGORY_MAP = {
        "flop_cbet_ip": ("Flop CBet IP", "Flop"),
        "flop_cbet_oop": ("Flop CBet OOP", "Flop"),
        "flop_raise_ip": ("Flop Raise IP", "Flop"),
        "flop_raise_oop": ("Flop XR OOP", "Flop"),
        "turn_barrel_ip": ("Turn Barrel IP", "Turn"),
        "turn_barrel_oop": ("Turn Barrel OOP", "Turn"),
        "turn_raise_ip": ("Turn Raise IP", "Turn"),
        "turn_raise_oop": ("Turn XR OOP", "Turn"),
        "turn_probe_ip": ("Turn Stab/Probe IP", "Turn"),
        "turn_probe_oop": ("Turn Probe OOP", "Turn"),
        "river_barrel_ip": ("River Barrel IP", "River"),
        "river_barrel_oop": ("River Barrel OOP", "River"),
        "river_raise_ip": ("River Raise IP", "River"),
        "river_raise_oop": ("River XR OOP", "River"),
        "river_probe_ip": ("River Stab/Probe IP", "River"),
        "river_probe_oop": ("River Probe OOP", "River"),
        "avg_size_bb": ("Open Size", "Preflop"),
    }

    WEIGHTS = {
        "flop_cbet_ip": 0.85,
        "flop_cbet_oop": 0.95,
        "flop_raise_ip": 0.75,
        "flop_raise_oop": 1.05,
        "turn_barrel_ip": 1.15,
        "turn_barrel_oop": 1.25,
        "turn_raise_ip": 0.90,
        "turn_raise_oop": 1.10,
        "turn_probe_ip": 1.05,
        "turn_probe_oop": 1.15,
        "river_barrel_ip": 0.80,
        "river_barrel_oop": 0.90,
        "river_raise_ip": 0.65,
        "river_raise_oop": 0.75,
        "river_probe_ip": 0.75,
        "river_probe_oop": 0.85,
        "avg_size_bb": 0.35,
    }

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.profile_service = BotProfileService(self.database_path)
        self.tracker_service = TrackerStatisticsService(self.database_path)

    def available_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 500,
    ) -> list[dict[str, Any]]:
        return self.profile_service.available_entities(
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

        profile = self.profile_service.build_profile(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            minimum_hands=minimum_hands,
        )

        tracker_mode = "ALIAS" if mode == "ALIAS" else "PLAYER"

        entity_tracker = self.tracker_service.analyze(
            mode=tracker_mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )["entity"]

        pool_tracker = self.tracker_service.analyze(
            mode="POOL",
            entity_name="",
            site=site,
            stakes=stakes,
        )["entity"]

        entity_wwsf = float(entity_tracker.get("wwsf") or 0.0)
        pool_wwsf = float(pool_tracker.get("wwsf") or 0.0)
        gap = entity_wwsf - pool_wwsf

        metric_map = {
            row["key"]: row
            for row in profile.get("metrics", [])
        }

        raw_components: list[dict[str, Any]] = []

        for key, (label, street) in self.CATEGORY_MAP.items():
            row = metric_map.get(key)
            if row is None:
                continue

            delta = float(row.get("delta") or 0.0)
            opportunity = int(row.get("entity_opportunity") or 0)

            sample_factor = min(
                1.0,
                opportunity / 5000.0,
            ) if opportunity > 0 else 0.55

            scale = 12.0 if key == "avg_size_bb" else 1.0
            weighted_signal = delta * self.WEIGHTS[key] * sample_factor * scale

            raw_components.append(
                {
                    "key": key,
                    "label": label,
                    "street": street,
                    "entity": float(row.get("entity") or 0.0),
                    "pool": float(row.get("pool") or 0.0),
                    "delta": delta,
                    "opportunity": opportunity,
                    "sample_factor": sample_factor,
                    "weighted_signal": weighted_signal,
                }
            )

        positive_total = sum(
            max(0.0, row["weighted_signal"])
            for row in raw_components
        )
        negative_total = sum(
            abs(min(0.0, row["weighted_signal"]))
            for row in raw_components
        )

        if gap >= 0:
            denominator = positive_total or 1.0
            for row in raw_components:
                signal = max(0.0, row["weighted_signal"])
                row["attribution"] = gap * signal / denominator
        else:
            denominator = negative_total or 1.0
            for row in raw_components:
                signal = abs(min(0.0, row["weighted_signal"]))
                row["attribution"] = gap * signal / denominator

        raw_components.sort(
            key=lambda row: abs(row["attribution"]),
            reverse=True,
        )

        grouped = self._group_by_street(raw_components)
        insights = self._build_insights(
            gap=gap,
            components=raw_components,
            grouped=grouped,
        )

        return {
            "entity_name": entity_name,
            "hands": int(profile.get("hands") or 0),
            "entity_wwsf": entity_wwsf,
            "pool_wwsf": pool_wwsf,
            "gap": gap,
            "components": raw_components,
            "grouped": grouped,
            "insights": insights,
            "summary": self._summary(
                entity_wwsf,
                pool_wwsf,
                gap,
                raw_components,
            ),
            "warning": (
                "Katkılar heuristic attribution'dır; "
                "nedensel EV veya bb/100 hesabı değildir."
            ),
        }

    def _group_by_street(
        self,
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        streets = ["Preflop", "Flop", "Turn", "River"]
        result: list[dict[str, Any]] = []

        for street in streets:
            rows = [
                row
                for row in components
                if row["street"] == street
            ]

            if not rows:
                continue

            result.append(
                {
                    "street": street,
                    "attribution": sum(
                        float(row["attribution"])
                        for row in rows
                    ),
                    "signal": sum(
                        float(row["weighted_signal"])
                        for row in rows
                    ),
                    "metrics": len(rows),
                }
            )

        result.sort(
            key=lambda row: abs(row["attribution"]),
            reverse=True,
        )
        return result

    def _build_insights(
        self,
        gap: float,
        components: list[dict[str, Any]],
        grouped: list[dict[str, Any]],
    ) -> list[str]:
        notes: list[str] = []

        if abs(gap) < 1.0:
            notes.append(
                "WWSF poola çok yakın; belirgin tek davranış kaynağı yok."
            )
            return notes

        top = [
            row
            for row in components
            if abs(row["attribution"]) >= 0.10
        ][:5]

        for row in top:
            direction = (
                "yukarı taşıyor"
                if row["attribution"] > 0
                else "aşağı çekiyor"
            )
            notes.append(
                f"{row['label']} yaklaşık "
                f"{row['attribution']:+.2f} puan ile WWSF'yi {direction}."
            )

        if grouped:
            strongest = grouped[0]
            notes.append(
                f"En büyük street etkisi {strongest['street']}: "
                f"{strongest['attribution']:+.2f} puan."
            )

        return notes

    def _summary(
        self,
        entity_wwsf: float,
        pool_wwsf: float,
        gap: float,
        components: list[dict[str, Any]],
    ) -> str:
        top = components[:3]

        if not top:
            return (
                f"WWSF {entity_wwsf:.2f}, pool {pool_wwsf:.2f}, "
                f"delta {gap:+.2f}."
            )

        top_text = ", ".join(
            f"{row['label']} {row['attribution']:+.2f}"
            for row in top
        )

        return (
            f"WWSF {entity_wwsf:.2f} vs pool {pool_wwsf:.2f} "
            f"({gap:+.2f}). Ana ilişkili katkılar: {top_text}."
        )
