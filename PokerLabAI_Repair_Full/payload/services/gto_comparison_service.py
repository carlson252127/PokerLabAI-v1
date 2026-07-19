from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb

from services.spot_engine import SpotEngine


class GTOComparisonService:
    EXPECTED_COLUMNS = [
        "site",
        "stakes",
        "hero_position",
        "villain_position",
        "location",
        "pot_type",
        "board_texture",
        "stat_key",
        "gto_value",
        "note",
        "updated_at",
    ]

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.spot_engine = SpotEngine(self.database_path)
        self.create_table()

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path)

    def create_table(self) -> None:
        with self.connect() as con:
            self._migrate_legacy_table(con)

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS gto_baselines (
                    site VARCHAR NOT NULL,
                    stakes VARCHAR NOT NULL,
                    hero_position VARCHAR NOT NULL,
                    villain_position VARCHAR NOT NULL,
                    location VARCHAR NOT NULL,
                    pot_type VARCHAR NOT NULL,
                    board_texture VARCHAR NOT NULL,
                    stat_key VARCHAR NOT NULL,
                    gto_value DOUBLE NOT NULL,
                    note VARCHAR,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (
                        site,
                        stakes,
                        hero_position,
                        villain_position,
                        location,
                        pot_type,
                        board_texture,
                        stat_key
                    )
                )
                """
            )

    def _migrate_legacy_table(
        self,
        con: duckdb.DuckDBPyConnection,
    ) -> None:
        exists = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_name = 'gto_baselines'
                """
            ).fetchone()[0]
        )

        if not exists:
            return

        actual_columns = [
            row[1]
            for row in con.execute(
                "PRAGMA table_info('gto_baselines')"
            ).fetchall()
        ]

        if actual_columns == self.EXPECTED_COLUMNS:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"gto_baselines_legacy_{timestamp}"

        con.execute(
            f"""
            ALTER TABLE gto_baselines
            RENAME TO {backup_name}
            """
        )

    def save_baseline(
        self,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str,
        stat_key: str,
        gto_value: float,
        note: str = "",
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO gto_baselines (
                    site,
                    stakes,
                    hero_position,
                    villain_position,
                    location,
                    pot_type,
                    board_texture,
                    stat_key,
                    gto_value,
                    note,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (
                    site,
                    stakes,
                    hero_position,
                    villain_position,
                    location,
                    pot_type,
                    board_texture,
                    stat_key
                )
                DO UPDATE SET
                    gto_value = EXCLUDED.gto_value,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    site,
                    stakes,
                    hero_position,
                    villain_position,
                    location,
                    pot_type,
                    board_texture,
                    stat_key,
                    float(gto_value),
                    note,
                ],
            )

    def get_baseline(
        self,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str,
        stat_key: str,
    ) -> Optional[float]:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT gto_value
                FROM gto_baselines
                WHERE site = ?
                  AND stakes = ?
                  AND hero_position = ?
                  AND villain_position = ?
                  AND location = ?
                  AND pot_type = ?
                  AND board_texture = ?
                  AND stat_key = ?
                """,
                [
                    site,
                    stakes,
                    hero_position,
                    villain_position,
                    location,
                    pot_type,
                    board_texture,
                    stat_key,
                ],
            ).fetchone()

        return float(row[0]) if row else None

    def calculate_population_stat(
        self,
        stat_key: str,
        site: str = "",
        stakes: str = "",
        hero_position: str = "",
        villain_position: str = "",
        location: str = "",
        pot_type: str = "",
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        return self.spot_engine.calculate(
            stat_key=stat_key,
            site=site,
            stakes=stakes,
            hero_position=hero_position,
            villain_position=villain_position,
            location=location,
            pot_type=pot_type,
            board_texture=board_texture,
        )
