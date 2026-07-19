from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True, slots=True)
class PopulationSummary:
    all_players: int
    bot_players: int
    human_players: int
    all_hands: int
    bot_hands: int
    human_hands: int


class PopulationService:
    """Tek ve güvenilir population ayrımı.

    Human Pool, Bot Group Manager'daki herhangi bir gruba eklenmiş oyuncuları
    kesin olarak dışarıda bırakır. İsim karşılaştırması trim + case-insensitive'dir.
    """

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))

    def connect(self, read_only: bool = True) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path, read_only=read_only)

    @staticmethod
    def human_condition(player_column: str = "hp.player_name") -> str:
        return f"""NOT EXISTS (
            SELECT 1 FROM bot_group_members bgm_population
            WHERE LOWER(TRIM(bgm_population.player_name)) =
                  LOWER(TRIM({player_column}))
        )"""

    @staticmethod
    def bot_condition(player_column: str = "hp.player_name") -> str:
        return f"""EXISTS (
            SELECT 1 FROM bot_group_members bgm_population
            WHERE LOWER(TRIM(bgm_population.player_name)) =
                  LOWER(TRIM({player_column}))
        )"""

    def summary(self) -> PopulationSummary:
        with self.connect() as con:
            row = con.execute(f"""
                WITH player_population AS (
                    SELECT DISTINCT
                        hp.player_name,
                        CASE WHEN {self.bot_condition('hp.player_name')}
                             THEN TRUE ELSE FALSE END AS is_bot
                    FROM hand_players hp
                    WHERE hp.player_name IS NOT NULL
                      AND TRIM(hp.player_name) <> ''
                ),
                hand_population AS (
                    SELECT
                        hp.hand_id,
                        BOOL_OR({self.bot_condition('hp.player_name')}) AS has_bot,
                        BOOL_OR({self.human_condition('hp.player_name')}) AS has_human
                    FROM hand_players hp
                    GROUP BY hp.hand_id
                )
                SELECT
                    COUNT(*) AS all_players,
                    COUNT(*) FILTER (WHERE is_bot) AS bot_players,
                    COUNT(*) FILTER (WHERE NOT is_bot) AS human_players,
                    (SELECT COUNT(*) FROM hands) AS all_hands,
                    (SELECT COUNT(*) FROM hand_population WHERE has_bot) AS bot_hands,
                    (SELECT COUNT(*) FROM hand_population WHERE has_human) AS human_hands
                FROM player_population
            """).fetchone()
        values = [int(value or 0) for value in row]
        return PopulationSummary(*values)
