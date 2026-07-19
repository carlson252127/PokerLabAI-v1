from __future__ import annotations

from pathlib import Path
from typing import Any

from services.bot_profile_service import BotProfileService
from services.tracker_statistics_service import TrackerStatisticsService


class BotDNAService:
    """Builds an interpretable bot/player DNA profile.

    3Bet is intentionally excluded from DNA scoring until its opportunity
    calculation is validated.
    """

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

    def build_dna(
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

        tracker_mode = (
            "ALIAS"
            if mode == "ALIAS"
            else "PLAYER"
        )

        tracker = self.tracker_service.analyze(
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

        metric_map = {
            row["key"]: row
            for row in profile.get("metrics", [])
        }

        metrics: list[dict[str, Any]] = []

        def add_metric(
            label: str,
            key: str,
            entity_value: float,
            pool_value: float,
            category: str,
            scoring: bool = True,
            note: str = "",
        ) -> None:
            delta = float(entity_value) - float(pool_value)

            metrics.append(
                {
                    "label": label,
                    "key": key,
                    "entity": float(entity_value),
                    "pool": float(pool_value),
                    "delta": delta,
                    "category": category,
                    "scoring": scoring,
                    "note": note or self._interpret_metric(
                        key,
                        delta,
                    ),
                }
            )

        for key, label, category in [
            ("vpip", "VPIP", "Preflop"),
            ("pfr", "PFR", "Preflop"),
            ("flop_cbet_ip", "Flop CBet IP", "Flop"),
            ("flop_cbet_oop", "Flop CBet OOP", "Flop"),
            ("flop_raise_ip", "Flop XR/Raise IP", "Flop"),
            ("flop_raise_oop", "Flop XR OOP", "Flop"),
            ("turn_barrel_ip", "Turn Barrel IP", "Turn"),
            ("turn_barrel_oop", "Turn Barrel OOP", "Turn"),
            ("turn_raise_ip", "Turn XR/Raise IP", "Turn"),
            ("turn_raise_oop", "Turn XR OOP", "Turn"),
            ("turn_probe_ip", "Turn Stab/Probe IP", "Turn"),
            ("turn_probe_oop", "Turn Probe OOP", "Turn"),
            ("delay_cbet_ip", "Delay CBet IP", "Turn"),
            ("delay_cbet_oop", "Delay CBet OOP", "Turn"),
            ("fold_vs_delay_ip", "Fold vs Delay IP", "Turn"),
            ("fold_vs_delay_oop", "Fold vs Delay OOP", "Turn"),
            ("river_barrel_ip", "River Barrel IP", "River"),
            ("river_barrel_oop", "River Barrel OOP", "River"),
            ("river_raise_ip", "River XR/Raise IP", "River"),
            ("river_raise_oop", "River XR OOP", "River"),
            ("river_probe_ip", "River Stab/Probe IP", "River"),
            ("river_probe_oop", "River Probe OOP", "River"),
            ("avg_size_bb", "Ort. Open Size", "Preflop"),
        ]:
            row = metric_map.get(key)

            if row:
                add_metric(
                    label=label,
                    key=key,
                    entity_value=row["entity"],
                    pool_value=row["pool"],
                    category=category,
                )

        # Keep 3Bet visible but do not use it in DNA classification.
        three_bet_row = metric_map.get("three_bet")

        if three_bet_row:
            add_metric(
                label="3Bet (Geçici)",
                key="three_bet",
                entity_value=three_bet_row["entity"],
                pool_value=three_bet_row["pool"],
                category="Preflop",
                scoring=False,
                note=(
                    "Opportunity hesabı doğrulanmadı; "
                    "DNA skoruna dahil edilmedi."
                ),
            )

        add_metric(
            label="WWSF",
            key="wwsf",
            entity_value=tracker.get("wwsf", 0.0),
            pool_value=pool_tracker.get("wwsf", 0.0),
            category="Showdown",
        )
        add_metric(
            label="WTSD",
            key="wtsd",
            entity_value=tracker.get("wtsd", 0.0),
            pool_value=pool_tracker.get("wtsd", 0.0),
            category="Showdown",
        )
        add_metric(
            label="W$SD",
            key="wsd",
            entity_value=tracker.get("wsd", 0.0),
            pool_value=pool_tracker.get("wsd", 0.0),
            category="Showdown",
        )

        dimensions = self._build_dimensions(metrics)
        classification = self._classify(
            metrics=metrics,
            dimensions=dimensions,
        )
        strengths, weaknesses = self._strengths_weaknesses(
            metrics
        )
        exploits = self._build_exploits(
            metrics=metrics,
            dimensions=dimensions,
        )

        return {
            "entity_name": entity_name,
            "hands": int(profile.get("hands", 0)),
            "merged_nicks": int(
                profile.get("merged_nicks", 1)
            ),
            "classification": classification,
            "dimensions": dimensions,
            "metrics": sorted(
                metrics,
                key=lambda row: abs(row["delta"]),
                reverse=True,
            ),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "exploits": exploits,
            "summary": self._summary(
                classification,
                dimensions,
            ),
            "warning": (
                "3Bet geçici olarak yalnızca gösterilir; "
                "fırsat hesabı doğrulanana kadar DNA skoruna girmez."
            ),
        }

    def _build_dimensions(
        self,
        metrics: list[dict[str, Any]],
    ) -> dict[str, float]:
        values = {
            row["key"]: row
            for row in metrics
            if row["scoring"]
        }

        def delta(key: str) -> float:
            row = values.get(key)
            return float(row["delta"]) if row else 0.0

        preflop_pressure = self._clamp_score(
            50.0
            + delta("pfr") * 3.0
            + delta("vpip") * 1.2
        )

        flop_pressure = self._clamp_score(
            50.0
            + ((delta("flop_cbet_ip") + delta("flop_cbet_oop")) / 2.0) * 3.0
        )

        turn_pressure = self._clamp_score(
            50.0
            + ((delta("turn_barrel_ip") + delta("turn_barrel_oop")) / 2.0) * 3.0
        )

        river_pressure = self._clamp_score(
            50.0
            + ((delta("river_barrel_ip") + delta("river_barrel_oop")) / 2.0) * 2.5
        )

        showdown_quality = self._clamp_score(
            50.0
            + delta("wsd") * 3.0
            - abs(delta("wtsd")) * 0.5
        )

        pot_capture = self._clamp_score(
            50.0
            + delta("wwsf") * 3.0
        )

        sizing_pressure = self._clamp_score(
            50.0
            + delta("avg_size_bb") * 25.0
        )

        return {
            "Preflop Baskı": preflop_pressure,
            "Flop Baskı": flop_pressure,
            "Turn Baskı": turn_pressure,
            "River Baskı": river_pressure,
            "Pot Kazanma": pot_capture,
            "Showdown Kalitesi": showdown_quality,
            "Sizing Baskısı": sizing_pressure,
        }

    def _classify(
        self,
        metrics: list[dict[str, Any]],
        dimensions: dict[str, float],
    ) -> dict[str, str]:
        metric_map = {
            row["key"]: row
            for row in metrics
        }

        vpip = metric_map.get("vpip", {}).get("entity", 0.0)
        pfr = metric_map.get("pfr", {}).get("entity", 0.0)
        wwsf = metric_map.get("wwsf", {}).get("entity", 0.0)
        wtsd = metric_map.get("wtsd", {}).get("entity", 0.0)
        wsd = metric_map.get("wsd", {}).get("entity", 0.0)

        if vpip >= 29 and pfr >= 22:
            preflop_style = "Loose-Aggressive"
        elif vpip <= 22 and pfr <= 18:
            preflop_style = "Tight-Aggressive"
        else:
            preflop_style = "Balanced Aggressive"

        if dimensions["Turn Baskı"] >= 65:
            postflop_style = "Turn Pressure"
        elif dimensions["Flop Baskı"] >= 65:
            postflop_style = "Flop Pressure"
        elif dimensions["River Baskı"] >= 65:
            postflop_style = "River Pressure"
        else:
            postflop_style = "Balanced Postflop"

        if wsd >= 56 and wtsd <= 30:
            showdown_style = "Selective High-Quality Showdown"
        elif wsd >= 56:
            showdown_style = "Strong Showdown Conversion"
        elif wtsd >= 31:
            showdown_style = "Showdown Heavy"
        else:
            showdown_style = "Standard Showdown"

        if wwsf >= 53 and wsd >= 56:
            dna_type = "High Capture / High Showdown"
        elif wwsf >= 53:
            dna_type = "High Pot Capture"
        elif wsd >= 56:
            dna_type = "Value-Heavy Showdown"
        else:
            dna_type = "Balanced Pool-Like"

        return {
            "dna_type": dna_type,
            "preflop_style": preflop_style,
            "postflop_style": postflop_style,
            "showdown_style": showdown_style,
        }

    def _strengths_weaknesses(
        self,
        metrics: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        scoring_metrics = [
            row
            for row in metrics
            if row["scoring"]
        ]

        strengths = sorted(
            [
                row
                for row in scoring_metrics
                if row["delta"] >= 2.0
                or (
                    row["key"] == "avg_size_bb"
                    and row["delta"] >= 0.15
                )
            ],
            key=lambda row: row["delta"],
            reverse=True,
        )[:5]

        weaknesses = sorted(
            [
                row
                for row in scoring_metrics
                if row["delta"] <= -2.0
                or (
                    row["key"] == "avg_size_bb"
                    and row["delta"] <= -0.15
                )
            ],
            key=lambda row: row["delta"],
        )[:5]

        return strengths, weaknesses

    def _build_exploits(
        self,
        metrics: list[dict[str, Any]],
        dimensions: dict[str, float],
    ) -> list[str]:
        metric_map = {
            row["key"]: row
            for row in metrics
        }
        notes: list[str] = []

        turn_delta = max(
            metric_map.get("turn_barrel_ip", {}).get("delta", 0.0),
            metric_map.get("turn_barrel_oop", {}).get("delta", 0.0),
        )

        river_delta = max(
            metric_map.get("river_barrel_ip", {}).get("delta", 0.0),
            metric_map.get("river_barrel_oop", {}).get("delta", 0.0),
        )

        flop_delta = max(
            metric_map.get("flop_cbet_ip", {}).get("delta", 0.0),
            metric_map.get("flop_cbet_oop", {}).get("delta", 0.0),
        )

        wsd_delta = metric_map.get(
            "wsd",
            {},
        ).get("delta", 0.0)

        wtsd_delta = metric_map.get(
            "wtsd",
            {},
        ).get("delta", 0.0)

        if flop_delta >= 5:
            notes.append(
                "Flop c-bet baskısı yüksek: güçlü backdoor ve "
                "check-raise adaylarını daha geniş savun."
            )

        if turn_delta >= 5:
            notes.append(
                "Turn barrel baskısı yüksek: flop call aralığını "
                "turn devam planıyla birlikte kur."
            )

        if river_delta >= 5 and wsd_delta >= 2:
            notes.append(
                "River devamı ve showdown kalitesi birlikte yüksek: "
                "river bluff-catch aralığını dikkatli seç."
            )
        elif river_delta >= 5:
            notes.append(
                "River devamı yüksek: blocker bazlı bluff-catch "
                "ve raise fırsatlarını incele."
            )

        if wsd_delta >= 3 and wtsd_delta <= 0:
            notes.append(
                "Showdown seçimi güçlü: büyük river aksiyonlarına "
                "karşı marjinal bluff-catcherları azalt."
            )

        if dimensions["Pot Kazanma"] >= 65:
            notes.append(
                "Pot capture yüksek: pasif check-back hatlarına karşı "
                "daha fazla deny/protection planı kullan."
            )

        if not notes:
            notes.append(
                "Belirgin tek exploit çıkmadı; pozisyon ve board "
                "kırılımı gerekli."
            )

        return notes[:6]

    def _interpret_metric(
        self,
        key: str,
        delta: float,
    ) -> str:
        if key == "avg_size_bb":
            if delta >= 0.15:
                return "Pooldan daha büyük open sizing"
            if delta <= -0.15:
                return "Pooldan daha küçük open sizing"
            return "Open sizing poola yakın"

        if abs(delta) < 2.0:
            return "Poola yakın"

        if key == "flop_cbet":
            return (
                "Flop baskısı daha yüksek"
                if delta > 0
                else "Flop devamı daha düşük"
            )

        if key == "turn_barrel":
            return (
                "Turn baskısı daha yüksek"
                if delta > 0
                else "Turn devamı daha düşük"
            )

        if key == "river_barrel":
            return (
                "River baskısı daha yüksek"
                if delta > 0
                else "River devamı daha düşük"
            )

        if key == "wwsf":
            return (
                "Flop sonrası potları daha sık kazanıyor"
                if delta > 0
                else "Flop sonrası pot capture daha düşük"
            )

        if key == "wtsd":
            return (
                "Showdowna daha sık gidiyor"
                if delta > 0
                else "Showdowna daha seçici gidiyor"
            )

        if key == "wsd":
            return (
                "Showdown dönüşümü daha güçlü"
                if delta > 0
                else "Showdown dönüşümü daha düşük"
            )

        return (
            "Pooldan daha yüksek"
            if delta > 0
            else "Pooldan daha düşük"
        )

    def _summary(
        self,
        classification: dict[str, str],
        dimensions: dict[str, float],
    ) -> str:
        strongest_dimension = max(
            dimensions.items(),
            key=lambda item: item[1],
        )

        return (
            f"{classification['dna_type']} — "
            f"{classification['preflop_style']} / "
            f"{classification['postflop_style']}. "
            f"En güçlü boyut: {strongest_dimension[0]} "
            f"({strongest_dimension[1]:.0f}/100)."
        )

    def _clamp_score(
        self,
        value: float,
    ) -> float:
        return max(
            0.0,
            min(100.0, float(value)),
        )
