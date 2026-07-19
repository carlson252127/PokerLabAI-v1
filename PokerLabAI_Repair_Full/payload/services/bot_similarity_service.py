from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from services.player_stats_service import PlayerStatsService


class BotSimilarityService:
    FEATURE_KEYS = [
        "vpip",
        "pfr",
        "three_bet",
        "flop_cbet",
        "turn_barrel",
        "river_barrel",
    ]

    FEATURE_LABELS = {
        "vpip": "VPIP",
        "pfr": "PFR",
        "three_bet": "3Bet",
        "flop_cbet": "Flop CBet",
        "turn_barrel": "Turn Barrel",
        "river_barrel": "River Barrel",
    }

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.player_service = PlayerStatsService(
            self.database_path
        )

    def get_entities(
        self,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 100,
        use_aliases: bool = True,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        return self.player_service.get_players(
            site=site,
            stakes=stakes,
            name_query="",
            minimum_hands=minimum_hands,
            limit=limit,
            use_aliases=use_aliases,
        )

    def compare(
        self,
        reference_name: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 100,
        use_aliases: bool = True,
        limit: int = 250,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        entities = self.get_entities(
            site=site,
            stakes=stakes,
            minimum_hands=minimum_hands,
            use_aliases=use_aliases,
            limit=5000,
        )

        reference = next(
            (
                row
                for row in entities
                if row["player_name"] == reference_name
            ),
            None,
        )

        if reference is None:
            raise ValueError(
                "Referans oyuncu veya alias bulunamadı."
            )

        reference_vector = self._feature_vector(reference)

        results: list[dict[str, Any]] = []

        for entity in entities:
            if entity["player_name"] == reference_name:
                continue

            vector = self._feature_vector(entity)
            similarity = self._cosine_similarity(
                reference_vector,
                vector,
            )

            distance = self._normalized_distance(
                reference_vector,
                vector,
            )

            confidence = self._confidence(
                reference,
                entity,
            )

            results.append(
                {
                    "player_name": entity["player_name"],
                    "hands": entity["hands"],
                    "merged_nicks": entity.get(
                        "merged_nicks",
                        1,
                    ),
                    "similarity": similarity * 100.0,
                    "distance": distance,
                    "confidence": confidence,
                    "vpip": entity["vpip"],
                    "pfr": entity["pfr"],
                    "three_bet": entity["three_bet"],
                    "flop_cbet": entity["flop_cbet"],
                    "turn_barrel": entity["turn_barrel"],
                    "river_barrel": entity["river_barrel"],
                }
            )

        results.sort(
            key=lambda row: (
                row["similarity"],
                row["hands"],
            ),
            reverse=True,
        )

        return reference, results[:limit]

    def _feature_vector(
        self,
        row: dict[str, Any],
    ) -> list[float]:
        vector: list[float] = []

        for key in self.FEATURE_KEYS:
            value = row.get(key)

            if value is None:
                value = 0.0

            vector.append(float(value) / 100.0)

        return vector

    def _cosine_similarity(
        self,
        left: list[float],
        right: list[float],
    ) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))

        if left_norm == 0 or right_norm == 0:
            return 0.0

        return max(
            0.0,
            min(1.0, dot / (left_norm * right_norm)),
        )

    def _normalized_distance(
        self,
        left: list[float],
        right: list[float],
    ) -> float:
        if not left:
            return 0.0

        squared = sum(
            (a - b) ** 2
            for a, b in zip(left, right)
        )

        return math.sqrt(squared / len(left)) * 100.0

    def _confidence(
        self,
        reference: dict[str, Any],
        entity: dict[str, Any],
    ) -> str:
        sample = min(
            int(reference.get("hands", 0)),
            int(entity.get("hands", 0)),
        )

        postflop_samples = [
            int(reference.get("flop_cbet_opp", 0)),
            int(reference.get("turn_barrel_opp", 0)),
            int(reference.get("river_barrel_opp", 0)),
            int(entity.get("flop_cbet_opp", 0)),
            int(entity.get("turn_barrel_opp", 0)),
            int(entity.get("river_barrel_opp", 0)),
        ]

        postflop_floor = min(postflop_samples)

        if sample >= 10000 and postflop_floor >= 500:
            return "Yüksek"

        if sample >= 2500 and postflop_floor >= 100:
            return "Orta"

        if sample >= 500:
            return "Düşük"

        return "Çok düşük"
