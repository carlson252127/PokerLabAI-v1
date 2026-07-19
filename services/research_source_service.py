from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

import duckdb


@dataclass(frozen=True, slots=True)
class ResearchEntity:
    mode: str
    key: str
    label: str
    hands: int


class ResearchSourceService:
    """Canonical Player/Alias/Bot Group/Bot Family/Pool source resolver."""

    MODES = ("PLAYER", "ALIAS", "BOT_GROUP", "BOT_FAMILY", "POOL", "ALL_POOL")

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
        cache_ttl_seconds: float = 20.0,
    ) -> None:
        self.database_path = str(Path(database_path))
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._cache_lock = RLock()
        self.ensure_schema()

    def connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(self.database_path, read_only=read_only)
        con.execute("PRAGMA threads=4")
        return con

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def _cache_get(self, key: tuple[Any, ...]) -> Any | None:
        if self.cache_ttl_seconds <= 0:
            return None
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            created_at, value = cached
            if monotonic() - created_at > self.cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            return value

    def _cache_set(self, key: tuple[Any, ...], value: Any) -> Any:
        if self.cache_ttl_seconds > 0:
            with self._cache_lock:
                self._cache[key] = (monotonic(), value)
        return value

    def ensure_schema(self) -> None:
        with self.connect() as con:
            con.execute("CREATE SEQUENCE IF NOT EXISTS bot_family_id_seq START 1")
            con.execute("""
                CREATE TABLE IF NOT EXISTS bot_families (
                    family_id BIGINT PRIMARY KEY DEFAULT nextval('bot_family_id_seq'),
                    name VARCHAR NOT NULL UNIQUE,
                    description VARCHAR DEFAULT '',
                    auto_include_all_groups BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS bot_family_groups (
                    family_id BIGINT NOT NULL,
                    group_id BIGINT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (family_id, group_id)
                )
            """)
            con.execute("""
                INSERT INTO bot_families (
                    name,
                    description,
                    auto_include_all_groups
                )
                SELECT
                    'All Bots',
                    'Bütün bot gruplarını benzersiz oyuncularla birleştirir.',
                    TRUE
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM bot_families
                    WHERE LOWER(name) = 'all bots'
                )
            """)

    def list_sites(self) -> list[str]:
        cache_key = ("sites",)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)

        with self.connect(read_only=True) as con:
            result = [
                str(row[0])
                for row in con.execute("""
                    SELECT DISTINCT TRIM(site)
                    FROM hands
                    WHERE site IS NOT NULL
                      AND TRIM(site) <> ''
                    ORDER BY 1
                """).fetchall()
            ]
        return list(self._cache_set(cache_key, result))

    def list_stakes(self, site: str = "") -> list[str]:
        cache_key = ("stakes", site)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)

        with self.connect(read_only=True) as con:
            if site:
                rows = con.execute("""
                    SELECT DISTINCT TRIM(stakes)
                    FROM hands
                    WHERE site = ?
                      AND stakes IS NOT NULL
                      AND TRIM(stakes) <> ''
                    ORDER BY 1
                """, [site]).fetchall()
            else:
                rows = con.execute("""
                    SELECT DISTINCT TRIM(stakes)
                    FROM hands
                    WHERE stakes IS NOT NULL
                      AND TRIM(stakes) <> ''
                    ORDER BY 1
                """).fetchall()

        result = [str(row[0]) for row in rows]
        return list(self._cache_set(cache_key, result))

    def list_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 1,
        limit: int = 5000,
    ) -> list[ResearchEntity]:
        mode = str(mode or "").upper()
        if mode not in self.MODES:
            return []

        minimum_hands = max(1, int(minimum_hands))
        limit = max(1, min(int(limit), 20000))
        cache_key = (
            "entities",
            mode,
            site,
            stakes,
            minimum_hands,
            limit,
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)

        filters, params = self._hand_filters(site, stakes)
        where_sql = "WHERE " + " AND ".join(filters) if filters else ""

        with self.connect(read_only=True) as con:
            if mode == "PLAYER":
                rows = con.execute(f"""
                    SELECT
                        hp.player_name,
                        COUNT(DISTINCT hp.hand_id)
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY hp.player_name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY 2 DESC
                    LIMIT {limit}
                """, params + [minimum_hands]).fetchall()

            elif mode == "ALIAS":
                rows = con.execute(f"""
                    SELECT
                        pa.alias_name,
                        COUNT(DISTINCT hp.hand_id)
                    FROM player_aliases pa
                    JOIN hand_players hp
                      ON LOWER(TRIM(hp.player_name))
                       = LOWER(TRIM(pa.player_name))
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY pa.alias_name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY 2 DESC
                    LIMIT {limit}
                """, params + [minimum_hands]).fetchall()

            elif mode == "BOT_GROUP":
                extra = list(filters)
                extra.append("bgm.player_name IS NOT NULL")
                group_where = "WHERE " + " AND ".join(extra)
                rows = con.execute(f"""
                    SELECT
                        CAST(bg.group_id AS VARCHAR),
                        bg.name,
                        COUNT(DISTINCT hp.hand_id)
                    FROM bot_groups bg
                    JOIN bot_group_members bgm
                      ON bgm.group_id = bg.group_id
                    JOIN hand_players hp
                      ON LOWER(TRIM(hp.player_name))
                       = LOWER(TRIM(bgm.player_name))
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {group_where}
                    GROUP BY bg.group_id, bg.name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY 3 DESC
                    LIMIT {limit}
                """, params + [minimum_hands]).fetchall()
                result = [
                    ResearchEntity(mode, str(key), str(name), int(hands or 0))
                    for key, name, hands in rows
                ]
                return list(self._cache_set(cache_key, result))

            elif mode == "BOT_FAMILY":
                rows = con.execute(f"""
                    WITH family_members AS (
                        SELECT DISTINCT
                            bf.family_id,
                            bf.name,
                            bgm.player_name
                        FROM bot_families bf
                        JOIN bot_groups bg
                          ON bf.auto_include_all_groups
                        JOIN bot_group_members bgm
                          ON bgm.group_id = bg.group_id

                        UNION

                        SELECT DISTINCT
                            bf.family_id,
                            bf.name,
                            bgm.player_name
                        FROM bot_families bf
                        JOIN bot_family_groups bfg
                          ON bfg.family_id = bf.family_id
                        JOIN bot_group_members bgm
                          ON bgm.group_id = bfg.group_id
                    )
                    SELECT
                        CAST(fm.family_id AS VARCHAR),
                        fm.name,
                        COUNT(DISTINCT hp.hand_id)
                    FROM family_members fm
                    JOIN hand_players hp
                      ON LOWER(TRIM(hp.player_name))
                       = LOWER(TRIM(fm.player_name))
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY fm.family_id, fm.name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY 3 DESC
                    LIMIT {limit}
                """, params + [minimum_hands]).fetchall()
                result = [
                    ResearchEntity(mode, str(key), str(name), int(hands or 0))
                    for key, name, hands in rows
                ]
                return list(self._cache_set(cache_key, result))

            elif mode == "POOL":
                extra = list(filters)
                extra.append("""
                    NOT EXISTS (
                        SELECT 1
                        FROM bot_group_members bgm_pool
                        WHERE LOWER(TRIM(bgm_pool.player_name))
                            = LOWER(TRIM(hp.player_name))
                    )
                """)
                pool_where = "WHERE " + " AND ".join(extra)
                row = con.execute(f"""
                    SELECT COUNT(DISTINCT hp.hand_id)
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {pool_where}
                """, params).fetchone()
                hands = int((row or [0])[0] or 0)
                result = (
                    [ResearchEntity(
                        mode,
                        "HUMAN_POOL",
                        "Human Pool (Botlar Hariç)",
                        hands,
                    )]
                    if hands >= minimum_hands
                    else []
                )
                return list(self._cache_set(cache_key, result))

            else:
                row = con.execute(f"""
                    SELECT COUNT(DISTINCT hp.hand_id)
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                """, params).fetchone()
                hands = int((row or [0])[0] or 0)
                result = (
                    [ResearchEntity(
                        mode,
                        "ALL_POOL",
                        "All Pool",
                        hands,
                    )]
                    if hands >= minimum_hands
                    else []
                )
                return list(self._cache_set(cache_key, result))

        result = [
            ResearchEntity(mode, str(name), str(name), int(hands or 0))
            for name, hands in rows
        ]
        return list(self._cache_set(cache_key, result))

    def source_condition(
        self,
        mode: str,
        entity_key: str,
        player_column: str = "hp.player_name",
    ) -> tuple[str, list[Any]]:
        mode = str(mode or "").upper()

        if mode == "PLAYER":
            return (
                f"LOWER(TRIM({player_column})) = LOWER(TRIM(?))",
                [entity_key],
            )

        if mode == "ALIAS":
            return f"""
                EXISTS (
                    SELECT 1
                    FROM player_aliases pa
                    WHERE LOWER(TRIM(pa.player_name))
                        = LOWER(TRIM({player_column}))
                      AND pa.alias_name = ?
                )
            """, [entity_key]

        if mode == "BOT_GROUP":
            return f"""
                EXISTS (
                    SELECT 1
                    FROM bot_group_members bgm
                    WHERE bgm.group_id = ?
                      AND LOWER(TRIM(bgm.player_name))
                        = LOWER(TRIM({player_column}))
                )
            """, [int(entity_key)]

        if mode == "BOT_FAMILY":
            return f"""
                EXISTS (
                    SELECT 1
                    FROM bot_families bf
                    WHERE bf.family_id = ?
                      AND (
                        (
                            bf.auto_include_all_groups
                            AND EXISTS (
                                SELECT 1
                                FROM bot_group_members bgm_all
                                WHERE LOWER(TRIM(bgm_all.player_name))
                                    = LOWER(TRIM({player_column}))
                            )
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM bot_family_groups bfg
                            JOIN bot_group_members bgm
                              ON bgm.group_id = bfg.group_id
                            WHERE bfg.family_id = bf.family_id
                              AND LOWER(TRIM(bgm.player_name))
                                = LOWER(TRIM({player_column}))
                        )
                      )
                )
            """, [int(entity_key)]

        if mode == "POOL":
            return f"""
                NOT EXISTS (
                    SELECT 1
                    FROM bot_group_members bgm_pool
                    WHERE LOWER(TRIM(bgm_pool.player_name))
                        = LOWER(TRIM({player_column}))
                )
            """, []

        if mode == "ALL_POOL":
            return "1 = 1", []

        raise ValueError(f"Desteklenmeyen research mode: {mode}")

    @staticmethod
    def _hand_filters(site: str, stakes: str) -> tuple[list[str], list[Any]]:
        filters: list[str] = []
        params: list[Any] = []

        if site:
            filters.append("h.site = ?")
            params.append(site)

        if stakes:
            filters.append("h.stakes = ?")
            params.append(stakes)

        return filters, params
