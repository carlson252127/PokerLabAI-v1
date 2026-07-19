from __future__ import annotations

import re
from pathlib import Path

import duckdb


class BoardTextureService:
    TEXTURES = [
        "",
        "A_HIGH_RAINBOW",
        "A_HIGH_TWO_TONE",
        "A_HIGH_MONOTONE",
        "K_HIGH_RAINBOW",
        "K_HIGH_TWO_TONE",
        "Q_HIGH_RAINBOW",
        "LOW_RAINBOW",
        "LOW_TWO_TONE",
        "PAIRED",
        "TRIPS",
        "CONNECTED",
        "MONOTONE",
        "RAINBOW",
        "TWO_TONE",
    ]

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.ensure_schema()

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path)

    def ensure_schema(self) -> None:
        with self.connect() as con:
            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info('hands')"
                ).fetchall()
            }

            additions = {
                "flop_texture": "VARCHAR",
                "flop_high_card": "VARCHAR",
                "flop_suit_type": "VARCHAR",
                "flop_paired_type": "VARCHAR",
                "flop_connected": "BOOLEAN",
            }

            for column_name, column_type in additions.items():
                if column_name not in columns:
                    con.execute(
                        f"""
                        ALTER TABLE hands
                        ADD COLUMN {column_name} {column_type}
                        """
                    )

    def backfill(self, only_missing: bool = True) -> int:
        where = (
            """
            WHERE flop IS NOT NULL
              AND flop <> ''
              AND (
                    flop_texture IS NULL
                    OR flop_texture = ''
              )
            """
            if only_missing
            else """
            WHERE flop IS NOT NULL
              AND flop <> ''
            """
        )

        with self.connect() as con:
            rows = con.execute(
                f"""
                SELECT hand_id, flop
                FROM hands
                {where}
                """
            ).fetchall()

        updates: list[tuple] = []

        for hand_id, flop in rows:
            data = self.classify(flop)

            updates.append(
                (
                    data["texture"],
                    data["high_card"],
                    data["suit_type"],
                    data["paired_type"],
                    data["connected"],
                    str(hand_id),
                )
            )

        if not updates:
            return 0

        with self.connect() as con:
            con.executemany(
                """
                UPDATE hands
                SET
                    flop_texture = ?,
                    flop_high_card = ?,
                    flop_suit_type = ?,
                    flop_paired_type = ?,
                    flop_connected = ?
                WHERE hand_id = ?
                """,
                updates,
            )

        return len(updates)

    def classify(self, flop: str | None) -> dict:
        cards = re.findall(
            r"([2-9TJQKA])([shdcSHDC])",
            str(flop or ""),
        )

        if len(cards) < 3:
            return {
                "texture": "UNKNOWN",
                "high_card": "UNKNOWN",
                "suit_type": "UNKNOWN",
                "paired_type": "UNKNOWN",
                "connected": False,
            }

        ranks = [rank.upper() for rank, _ in cards[:3]]
        suits = [suit.lower() for _, suit in cards[:3]]

        rank_map = {
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            "7": 7,
            "8": 8,
            "9": 9,
            "T": 10,
            "J": 11,
            "Q": 12,
            "K": 13,
            "A": 14,
        }

        values = sorted(
            [rank_map[rank] for rank in ranks],
            reverse=True,
        )

        high_card = {
            14: "A_HIGH",
            13: "K_HIGH",
            12: "Q_HIGH",
            11: "J_HIGH",
            10: "T_HIGH",
        }.get(values[0], "LOW")

        unique_suits = len(set(suits))

        if unique_suits == 1:
            suit_type = "MONOTONE"
        elif unique_suits == 2:
            suit_type = "TWO_TONE"
        else:
            suit_type = "RAINBOW"

        unique_ranks = len(set(ranks))

        if unique_ranks == 1:
            paired_type = "TRIPS"
        elif unique_ranks == 2:
            paired_type = "PAIRED"
        else:
            paired_type = "UNPAIRED"

        unique_values = sorted(set(values))

        connected = False

        if len(unique_values) == 3:
            gaps = [
                unique_values[index + 1] - unique_values[index]
                for index in range(2)
            ]
            connected = max(gaps) <= 2

        labels = []

        if paired_type in {"PAIRED", "TRIPS"}:
            labels.append(paired_type)
        else:
            labels.append(high_card)
            labels.append(suit_type)

        if connected:
            labels.append("CONNECTED")

        return {
            "texture": "_".join(labels),
            "high_card": high_card,
            "suit_type": suit_type,
            "paired_type": paired_type,
            "connected": connected,
        }
