from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import duckdb

from services.research_source_service import ResearchSourceService


@dataclass(slots=True, frozen=True)
class BotGroupSummary:
    group_id: int
    name: str
    description: str
    member_count: int
    hand_count: int


class BotGroupService:
    """Manual bot-cluster management backed by the PokerLab DuckDB file."""

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))
        self.ensure_schema()
        ResearchSourceService(self.database_path)

    def connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(self.database_path)
        con.execute("PRAGMA threads=4")
        return con

    def ensure_schema(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS bot_group_id_seq START 1
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_groups (
                    group_id BIGINT PRIMARY KEY DEFAULT nextval('bot_group_id_seq'),
                    name VARCHAR NOT NULL UNIQUE,
                    description VARCHAR DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_group_members (
                    group_id BIGINT NOT NULL,
                    player_name VARCHAR NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, player_name)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bot_group_members_player
                ON bot_group_members(player_name)
                """
            )

    def list_groups(self) -> list[BotGroupSummary]:
        with self.connect() as con:
            rows = con.execute(
                """
                WITH member_stats AS (
                    SELECT
                        bgm.group_id,
                        COUNT(DISTINCT bgm.player_name) AS member_count,
                        COUNT(DISTINCT hp.hand_id) AS hand_count
                    FROM bot_group_members bgm
                    LEFT JOIN hand_players hp
                      ON LOWER(TRIM(hp.player_name)) = LOWER(TRIM(bgm.player_name))
                    GROUP BY bgm.group_id
                )
                SELECT
                    bg.group_id,
                    bg.name,
                    COALESCE(bg.description, ''),
                    COALESCE(ms.member_count, 0),
                    COALESCE(ms.hand_count, 0)
                FROM bot_groups bg
                LEFT JOIN member_stats ms ON ms.group_id = bg.group_id
                ORDER BY LOWER(bg.name)
                """
            ).fetchall()

        return [
            BotGroupSummary(
                group_id=int(row[0]),
                name=str(row[1]),
                description=str(row[2] or ""),
                member_count=int(row[3] or 0),
                hand_count=int(row[4] or 0),
            )
            for row in rows
        ]

    def create_group(self, name: str, description: str = "") -> int:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Grup adı boş olamaz.")

        with self.connect() as con:
            row = con.execute(
                """
                INSERT INTO bot_groups (name, description)
                VALUES (?, ?)
                RETURNING group_id
                """,
                [clean_name, description.strip()],
            ).fetchone()

        return int(row[0])

    def rename_group(self, group_id: int, name: str, description: str = "") -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Grup adı boş olamaz.")

        with self.connect() as con:
            con.execute(
                """
                UPDATE bot_groups
                SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE group_id = ?
                """,
                [clean_name, description.strip(), int(group_id)],
            )

    def delete_group(self, group_id: int) -> None:
        with self.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(
                    "DELETE FROM bot_group_members WHERE group_id = ?",
                    [int(group_id)],
                )
                con.execute(
                    "DELETE FROM bot_groups WHERE group_id = ?",
                    [int(group_id)],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def list_members(self, group_id: int) -> list[tuple[str, int]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT
                    bgm.player_name,
                    COUNT(DISTINCT hp.hand_id) AS hands
                FROM bot_group_members bgm
                LEFT JOIN hand_players hp
                  ON LOWER(TRIM(hp.player_name)) = LOWER(TRIM(bgm.player_name))
                WHERE bgm.group_id = ?
                GROUP BY bgm.player_name
                ORDER BY hands DESC, LOWER(bgm.player_name)
                """,
                [int(group_id)],
            ).fetchall()

        return [(str(row[0]), int(row[1] or 0)) for row in rows]

    def add_members(self, group_id: int, player_names: Iterable[str]) -> int:
        names = sorted({name.strip() for name in player_names if name and name.strip()})
        if not names:
            return 0

        added = 0
        with self.connect() as con:
            for name in names:
                before = con.execute(
                    """
                    SELECT COUNT(*) FROM bot_group_members
                    WHERE group_id = ? AND player_name = ?
                    """,
                    [int(group_id), name],
                ).fetchone()[0]
                if before:
                    continue
                con.execute(
                    """
                    INSERT INTO bot_group_members (group_id, player_name)
                    VALUES (?, ?)
                    """,
                    [int(group_id), name],
                )
                added += 1
        return added

    def remove_members(self, group_id: int, player_names: Iterable[str]) -> int:
        names = sorted({name.strip() for name in player_names if name and name.strip()})
        if not names:
            return 0

        removed = 0
        with self.connect() as con:
            for name in names:
                exists = con.execute(
                    """
                    SELECT COUNT(*) FROM bot_group_members
                    WHERE group_id = ? AND player_name = ?
                    """,
                    [int(group_id), name],
                ).fetchone()[0]
                if not exists:
                    continue
                con.execute(
                    """
                    DELETE FROM bot_group_members
                    WHERE group_id = ? AND player_name = ?
                    """,
                    [int(group_id), name],
                )
                removed += 1
        return removed

    def list_sites(self) -> list[str]:
        return ResearchSourceService(self.database_path).list_sites()

    def search_players(
        self,
        query: str = "",
        limit: int = 500,
        site: str = "",
        minimum_hands: int = 1,
        exclude_group_id: int | None = None,
    ) -> list[tuple[str, int]]:
        clean = query.strip()
        safe_limit = max(1, min(int(limit), 5000))
        minimum_hands = max(1, int(minimum_hands))
        clauses = ["hp.player_name IS NOT NULL", "TRIM(hp.player_name) <> ''"]
        params: list[object] = []
        if clean:
            clauses.append("LOWER(hp.player_name) LIKE ?")
            params.append(f"%{clean.lower()}%")
        if site:
            clauses.append("h.site = ?")
            params.append(site)
        if exclude_group_id is not None:
            clauses.append("""NOT EXISTS (
                SELECT 1 FROM bot_group_members existing
                WHERE existing.group_id = ?
                  AND LOWER(TRIM(existing.player_name)) = LOWER(TRIM(hp.player_name))
            )""")
            params.append(int(exclude_group_id))
        where_sql = " AND ".join(clauses)
        params.extend([minimum_hands, safe_limit])
        with self.connect() as con:
            rows = con.execute(f"""
                SELECT hp.player_name, COUNT(DISTINCT hp.hand_id) AS hands
                FROM hand_players hp
                JOIN hands h ON h.hand_id = hp.hand_id
                WHERE {where_sql}
                GROUP BY hp.player_name
                HAVING COUNT(DISTINCT hp.hand_id) >= ?
                ORDER BY hands DESC, LOWER(hp.player_name)
                LIMIT ?
            """, params).fetchall()
        return [(str(row[0]), int(row[1] or 0)) for row in rows]

    def all_bots_summary(self) -> tuple[int, int]:
        with self.connect() as con:
            row = con.execute("""
                SELECT COUNT(DISTINCT bgm.player_name), COUNT(DISTINCT hp.hand_id)
                FROM bot_group_members bgm
                LEFT JOIN hand_players hp
                  ON LOWER(TRIM(hp.player_name)) = LOWER(TRIM(bgm.player_name))
            """).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def group_player_names(self, group_id: int) -> list[str]:
        with self.connect() as con:
            return [
                str(row[0])
                for row in con.execute(
                    """
                    SELECT player_name
                    FROM bot_group_members
                    WHERE group_id = ?
                    ORDER BY LOWER(player_name)
                    """,
                    [int(group_id)],
                ).fetchall()
            ]

    def group_filter_sql(
        self,
        group_id: int,
        column_sql: str = "player_name",
    ) -> tuple[str, list[str]]:
        names = self.group_player_names(group_id)
        if not names:
            return "1 = 0", []
        placeholders = ", ".join("?" for _ in names)
        return f"LOWER(TRIM({column_sql})) IN ({placeholders})", [n.lower() for n in names]
