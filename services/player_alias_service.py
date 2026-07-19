from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb


class PlayerAliasService:
    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.create_table()

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path)

    def create_table(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS player_aliases (
                    player_name VARCHAR PRIMARY KEY,
                    alias_name VARCHAR NOT NULL,
                    note VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )

            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info('player_aliases')"
                ).fetchall()
            }

            if "created_at" not in columns:
                con.execute(
                    """
                    ALTER TABLE player_aliases
                    ADD COLUMN created_at TIMESTAMP
                    """
                )

            if "updated_at" not in columns:
                con.execute(
                    """
                    ALTER TABLE player_aliases
                    ADD COLUMN updated_at TIMESTAMP
                    """
                )

            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_player_alias_name
                ON player_aliases(alias_name)
                """
            )

    def assign_players(
        self,
        alias_name: str,
        player_names: list[str],
        note: str = "",
    ) -> int:
        alias_name = alias_name.strip()

        if not alias_name:
            raise ValueError("Alias adı boş olamaz.")

        cleaned_names = sorted(
            {
                name.strip()
                for name in player_names
                if name and name.strip()
            }
        )

        if not cleaned_names:
            raise ValueError("En az bir oyuncu adı gir.")

        now = datetime.now()

        with self.connect() as con:
            for player_name in cleaned_names:
                existing = con.execute(
                    """
                    SELECT created_at
                    FROM player_aliases
                    WHERE player_name = ?
                    """,
                    [player_name],
                ).fetchone()

                if existing:
                    con.execute(
                        """
                        UPDATE player_aliases
                        SET
                            alias_name = ?,
                            note = ?,
                            updated_at = ?
                        WHERE player_name = ?
                        """,
                        [
                            alias_name,
                            note.strip(),
                            now,
                            player_name,
                        ],
                    )
                else:
                    con.execute(
                        """
                        INSERT INTO player_aliases (
                            player_name,
                            alias_name,
                            note,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            player_name,
                            alias_name,
                            note.strip(),
                            now,
                            now,
                        ],
                    )

        return len(cleaned_names)

    def remove_player(self, player_name: str) -> bool:
        with self.connect() as con:
            before = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM player_aliases
                    WHERE player_name = ?
                    """,
                    [player_name],
                ).fetchone()[0]
            )

            con.execute(
                """
                DELETE FROM player_aliases
                WHERE player_name = ?
                """,
                [player_name],
            )

        return before > 0

    def delete_alias(self, alias_name: str) -> int:
        with self.connect() as con:
            count = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM player_aliases
                    WHERE alias_name = ?
                    """,
                    [alias_name],
                ).fetchone()[0]
            )

            con.execute(
                """
                DELETE FROM player_aliases
                WHERE alias_name = ?
                """,
                [alias_name],
            )

        return count

    def list_mappings(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT
                    alias_name,
                    player_name,
                    COALESCE(note, ''),
                    updated_at
                FROM player_aliases
                ORDER BY alias_name, player_name
                """
            ).fetchall()

        return [
            {
                "alias_name": row[0],
                "player_name": row[1],
                "note": row[2] or "",
                "updated_at": row[3] or "",
            }
            for row in rows
        ]

    def list_aliases(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT
                    alias_name,
                    COUNT(*) AS player_count,
                    STRING_AGG(
                        player_name,
                        ', '
                        ORDER BY player_name
                    ) AS players
                FROM player_aliases
                GROUP BY alias_name
                ORDER BY alias_name
                """
            ).fetchall()

        return [
            {
                "alias_name": row[0],
                "player_count": int(row[1]),
                "players": row[2] or "",
            }
            for row in rows
        ]

    def search_known_players(
        self,
        query: str = "",
        limit: int = 300,
    ) -> list[str]:
        query = query.strip().lower()

        with self.connect() as con:
            table_exists = bool(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'main'
                      AND table_name = 'hand_players'
                    """
                ).fetchone()[0]
            )

            if not table_exists:
                return []

            if query:
                rows = con.execute(
                    """
                    SELECT DISTINCT player_name
                    FROM hand_players
                    WHERE player_name IS NOT NULL
                      AND player_name <> ''
                      AND LOWER(player_name) LIKE ?
                    ORDER BY player_name
                    LIMIT ?
                    """,
                    [
                        f"%{query}%",
                        int(limit),
                    ],
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT DISTINCT player_name
                    FROM hand_players
                    WHERE player_name IS NOT NULL
                      AND player_name <> ''
                    ORDER BY player_name
                    LIMIT ?
                    """,
                    [int(limit)],
                ).fetchall()

        return [str(row[0]) for row in rows]

    def player_count(self) -> int:
        with self.connect() as con:
            table_exists = bool(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'main'
                      AND table_name = 'hand_players'
                    """
                ).fetchone()[0]
            )

            if not table_exists:
                return 0

            return int(
                con.execute(
                    """
                    SELECT COUNT(DISTINCT player_name)
                    FROM hand_players
                    """
                ).fetchone()[0]
            )
