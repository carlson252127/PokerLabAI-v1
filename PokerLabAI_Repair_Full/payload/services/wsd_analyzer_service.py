from __future__ import annotations

from pathlib import Path
from typing import Any

from services.bot_profile_service import BotProfileService
from services.tracker_statistics_service import TrackerStatisticsService


class WSDAnalyzerService:
    """Heuristic W$SD attribution engine.

    This explains which observed profile deltas are most associated with
    the W$SD gap. It is not a causal EV model.
    """

    CATEGORY_MAP = {
        "wtsd": ("WTSD", "Showdown"),
        "river_barrel_ip": ("River Barrel IP", "River"),
        "river_barrel_oop": ("River Barrel OOP", "River"),
        "river_probe_ip": ("River Stab/Probe IP", "River"),
        "river_probe_oop": ("River Probe OOP", "River"),
        "river_raise_ip": ("River Raise IP", "River"),
        "river_raise_oop": ("River XR OOP", "River"),
        "turn_barrel_ip": ("Turn Barrel IP", "Turn"),
        "turn_barrel_oop": ("Turn Barrel OOP", "Turn"),
        "turn_probe_ip": ("Turn Stab/Probe IP", "Turn"),
        "turn_probe_oop": ("Turn Probe OOP", "Turn"),
        "avg_size_bb": ("Open Size", "Preflop"),
    }

    WEIGHTS = {
        "wtsd": -1.35,
        "river_barrel_ip": 0.80,
        "river_barrel_oop": 0.90,
        "river_probe_ip": 0.60,
        "river_probe_oop": 0.70,
        "river_raise_ip": 0.85,
        "river_raise_oop": 0.95,
        "turn_barrel_ip": 0.35,
        "turn_barrel_oop": 0.40,
        "turn_probe_ip": 0.25,
        "turn_probe_oop": 0.30,
        "avg_size_bb": 0.20,
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

        entity_wsd = float(entity_tracker.get("wsd") or 0.0)
        pool_wsd = float(pool_tracker.get("wsd") or 0.0)
        gap = entity_wsd - pool_wsd

        metric_map = {
            row["key"]: row
            for row in profile.get("metrics", [])
        }

        # Inject tracker stats directly.
        metric_map["wtsd"] = {
            "key": "wtsd",
            "entity": float(entity_tracker.get("wtsd") or 0.0),
            "pool": float(pool_tracker.get("wtsd") or 0.0),
            "delta": (
                float(entity_tracker.get("wtsd") or 0.0)
                - float(pool_tracker.get("wtsd") or 0.0)
            ),
            "entity_opportunity": int(
                entity_tracker.get("flop_seen") or 0
            ),
        }

        components: list[dict[str, Any]] = []

        for key, (label, street) in self.CATEGORY_MAP.items():
            row = metric_map.get(key)
            if row is None:
                continue

            delta = float(row.get("delta") or 0.0)
            opportunity = int(row.get("entity_opportunity") or 0)

            sample_factor = min(
                1.0,
                opportunity / 3000.0,
            ) if opportunity > 0 else 0.55

            scale = 10.0 if key == "avg_size_bb" else 1.0
            weighted_signal = (
                delta
                * self.WEIGHTS[key]
                * sample_factor
                * scale
            )

            components.append(
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
            for row in components
        )
        negative_total = sum(
            abs(min(0.0, row["weighted_signal"]))
            for row in components
        )

        if gap >= 0:
            denominator = positive_total or 1.0

            for row in components:
                signal = max(0.0, row["weighted_signal"])
                row["attribution"] = (
                    gap * signal / denominator
                )
        else:
            denominator = negative_total or 1.0

            for row in components:
                signal = abs(
                    min(0.0, row["weighted_signal"])
                )
                row["attribution"] = (
                    gap * signal / denominator
                )

        components.sort(
            key=lambda row: abs(row["attribution"]),
            reverse=True,
        )

        grouped = self._group_by_street(components)
        insights = self._build_insights(
            gap=gap,
            components=components,
            entity_tracker=entity_tracker,
            pool_tracker=pool_tracker,
        )

        return {
            "entity_name": entity_name,
            "hands": int(profile.get("hands") or 0),
            "entity_wsd": entity_wsd,
            "pool_wsd": pool_wsd,
            "gap": gap,
            "entity_wtsd": float(
                entity_tracker.get("wtsd") or 0.0
            ),
            "pool_wtsd": float(
                pool_tracker.get("wtsd") or 0.0
            ),
            "showdown": int(
                entity_tracker.get("showdown") or 0
            ),
            "showdown_wins": int(
                entity_tracker.get("showdown_wins") or 0
            ),
            "components": components,
            "grouped": grouped,
            "insights": insights,
            "summary": self._summary(
                entity_wsd=entity_wsd,
                pool_wsd=pool_wsd,
                gap=gap,
                entity_wtsd=float(
                    entity_tracker.get("wtsd") or 0.0
                ),
                pool_wtsd=float(
                    pool_tracker.get("wtsd") or 0.0
                ),
                components=components,
            ),
            "warning": (
                "Katkılar heuristic attribution'dır; "
                "nedensel EV veya gerçek bluff/value ayrımı değildir."
            ),
        }

    def _group_by_street(
        self,
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        order = ["Preflop", "Turn", "River", "Showdown"]
        grouped: list[dict[str, Any]] = []

        for street in order:
            rows = [
                row
                for row in components
                if row["street"] == street
            ]

            if not rows:
                continue

            grouped.append(
                {
                    "street": street,
                    "attribution": sum(
                        float(row["attribution"])
                        for row in rows
                    ),
                    "metrics": len(rows),
                }
            )

        grouped.sort(
            key=lambda row: abs(row["attribution"]),
            reverse=True,
        )

        return grouped

    def _build_insights(
        self,
        gap: float,
        components: list[dict[str, Any]],
        entity_tracker: dict[str, Any],
        pool_tracker: dict[str, Any],
    ) -> list[str]:
        notes: list[str] = []

        entity_wtsd = float(
            entity_tracker.get("wtsd") or 0.0
        )
        pool_wtsd = float(
            pool_tracker.get("wtsd") or 0.0
        )

        if gap >= 2.0 and entity_wtsd < pool_wtsd:
            notes.append(
                "Yüksek W$SD ile düşük WTSD birlikte: "
                "showdown seçimi pooldan daha güçlü görünüyor."
            )

        if gap >= 2.0 and entity_wtsd >= pool_wtsd:
            notes.append(
                "Hem WTSD hem W$SD yüksek: range realization "
                "ve value extraction güçlü olabilir."
            )

        if gap <= -2.0 and entity_wtsd > pool_wtsd:
            notes.append(
                "Düşük W$SD ve yüksek WTSD: fazla bluff-catch "
                "veya zayıf showdown seçimi ihtimali var."
            )

        for row in components[:5]:
            if abs(row["attribution"]) < 0.10:
                continue

            direction = (
                "yukarı taşıyor"
                if row["attribution"] > 0
                else "aşağı çekiyor"
            )

            notes.append(
                f"{row['label']} yaklaşık "
                f"{row['attribution']:+.2f} puan ile W$SD'yi {direction}."
            )

        if not notes:
            notes.append(
                "W$SD poola yakın; belirgin tek davranış kaynağı yok."
            )

        return notes

    def _summary(
        self,
        entity_wsd: float,
        pool_wsd: float,
        gap: float,
        entity_wtsd: float,
        pool_wtsd: float,
        components: list[dict[str, Any]],
    ) -> str:
        top = components[:3]

        top_text = ", ".join(
            f"{row['label']} {row['attribution']:+.2f}"
            for row in top
        ) if top else "belirgin katkı yok"

        return (
            f"W$SD {entity_wsd:.2f} vs pool {pool_wsd:.2f} "
            f"({gap:+.2f}). WTSD {entity_wtsd:.2f} vs "
            f"{pool_wtsd:.2f}. Ana ilişkili katkılar: {top_text}."
        )
