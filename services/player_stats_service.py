from __future__ import annotations

from pathlib import Path

import duckdb


class PlayerStatsService:
    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(
            self.database_path,
            read_only=True,
        )

    def get_players(
        self,
        site: str = "",
        stakes: str = "",
        name_query: str = "",
        minimum_hands: int = 1,
        limit: int = 500,
        use_aliases: bool = False,
    ) -> list[dict]:
        alias_enabled = bool(
            use_aliases
            and self._table_exists("player_aliases")
        )
        alias_join = ""
        profile_expression = "hp.player_name"

        if alias_enabled:
            alias_join = """
                LEFT JOIN (
                    SELECT
                        LOWER(TRIM(player_name)) AS player_key,
                        MIN(alias_name) AS alias_name
                    FROM player_aliases
                    WHERE player_name IS NOT NULL
                      AND TRIM(player_name) <> ''
                      AND alias_name IS NOT NULL
                      AND TRIM(alias_name) <> ''
                    GROUP BY LOWER(TRIM(player_name))
                ) pa
                  ON pa.player_key = LOWER(TRIM(hp.player_name))
            """
            profile_expression = (
                "COALESCE(NULLIF(TRIM(pa.alias_name), ''), "
                "hp.player_name)"
            )

        clauses: list[str] = []
        params: list[object] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        if name_query:
            clauses.append(
                f"LOWER({profile_expression}) LIKE ?"
            )
            params.append(f"%{name_query.lower()}%")

        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)

        query = f"""
            WITH filtered_players AS (
                SELECT
                    hp.hand_id,
                    hp.player_name AS source_player_name,
                    {profile_expression} AS player_name,
                    hp.position
                FROM hand_players hp
                JOIN hands h
                  ON h.hand_id = hp.hand_id
                {alias_join}
                {where_sql}
            ),

            player_hands AS (
                SELECT
                    player_name,
                    COUNT(DISTINCT hand_id) AS hands,
                    COUNT(DISTINCT source_player_name) AS merged_nicks
                FROM filtered_players
                GROUP BY player_name
            ),

            preflop_flags AS (
                SELECT
                    fp.player_name,
                    fp.hand_id,
                    MAX(
                        CASE
                            WHEN a.street = 'PREFLOP'
                             AND a.action IN ('CALL', 'RAISE')
                            THEN 1 ELSE 0
                        END
                    ) AS vpip,
                    MAX(
                        CASE
                            WHEN a.street = 'PREFLOP'
                             AND a.action = 'RAISE'
                            THEN 1 ELSE 0
                        END
                    ) AS pfr
                FROM filtered_players fp
                LEFT JOIN actions a
                  ON a.hand_id = fp.hand_id
                 AND a.player_name = fp.source_player_name
                GROUP BY
                    fp.player_name,
                    fp.hand_id
            ),

            raise_order AS (
                SELECT
                    a.hand_id,
                    a.player_name,
                    a.sequence_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id
                        ORDER BY a.sequence_no
                    ) AS raise_no
                FROM actions a
                JOIN hands h
                  ON h.hand_id = a.hand_id
                WHERE a.street = 'PREFLOP'
                  AND a.action = 'RAISE'
                  {self._extra_hand_filter(site, stakes)}
            ),

            three_bet_flags AS (
                SELECT
                    fp.player_name,
                    fp.hand_id,
                    MAX(
                        CASE
                            WHEN ro.raise_no = 2
                            THEN 1 ELSE 0
                        END
                    ) AS three_bet
                FROM filtered_players fp
                LEFT JOIN raise_order ro
                  ON ro.hand_id = fp.hand_id
                 AND ro.player_name = fp.source_player_name
                GROUP BY
                    fp.player_name,
                    fp.hand_id
            ),

            pfr_by_hand AS (
                SELECT
                    hand_id,
                    player_name
                FROM (
                    SELECT
                        a.hand_id,
                        a.player_name,
                        a.sequence_no,
                        ROW_NUMBER() OVER (
                            PARTITION BY a.hand_id
                            ORDER BY a.sequence_no DESC
                        ) AS rn
                    FROM actions a
                    JOIN hands h
                      ON h.hand_id = a.hand_id
                    WHERE a.street = 'PREFLOP'
                      AND a.action = 'RAISE'
                      {self._extra_hand_filter(site, stakes)}
                ) x
                WHERE rn = 1
            ),

            postflop_flags AS (
                SELECT
                    fp.player_name,
                    fp.hand_id,

                    MAX(
                        CASE
                            WHEN pfr.player_name = fp.source_player_name
                             AND h.flop IS NOT NULL
                             AND h.flop <> ''
                            THEN 1 ELSE 0
                        END
                    ) AS flop_cbet_opp,

                    MAX(
                        CASE
                            WHEN pfr.player_name = fp.source_player_name
                             AND a.street = 'FLOP'
                             AND a.action = 'BET'
                            THEN 1 ELSE 0
                        END
                    ) AS flop_cbet,

                    MAX(
                        CASE
                            WHEN pfr.player_name = fp.source_player_name
                             AND h.turn IS NOT NULL
                             AND h.turn <> ''
                             AND EXISTS (
                                SELECT 1
                                FROM actions fa
                                WHERE fa.hand_id = fp.hand_id
                                  AND fa.player_name = fp.source_player_name
                                  AND fa.street = 'FLOP'
                                  AND fa.action = 'BET'
                             )
                            THEN 1 ELSE 0
                        END
                    ) AS turn_barrel_opp,

                    MAX(
                        CASE
                            WHEN pfr.player_name = fp.source_player_name
                             AND a.street = 'TURN'
                             AND a.action = 'BET'
                            THEN 1 ELSE 0
                        END
                    ) AS turn_barrel,

                    MAX(
                        CASE
                            WHEN pfr.player_name = fp.source_player_name
                             AND h.river IS NOT NULL
                             AND h.river <> ''
                             AND EXISTS (
                                SELECT 1
                                FROM actions ta
                                WHERE ta.hand_id = fp.hand_id
                                  AND ta.player_name = fp.source_player_name
                                  AND ta.street = 'TURN'
                                  AND ta.action = 'BET'
                             )
                            THEN 1 ELSE 0
                        END
                    ) AS river_barrel_opp,

                    MAX(
                        CASE
                            WHEN pfr.player_name = fp.source_player_name
                             AND a.street = 'RIVER'
                             AND a.action = 'BET'
                            THEN 1 ELSE 0
                        END
                    ) AS river_barrel

                FROM filtered_players fp
                JOIN hands h
                  ON h.hand_id = fp.hand_id
                LEFT JOIN pfr_by_hand pfr
                  ON pfr.hand_id = fp.hand_id
                LEFT JOIN actions a
                  ON a.hand_id = fp.hand_id
                 AND a.player_name = fp.source_player_name
                GROUP BY
                    fp.player_name,
                    fp.hand_id
            ),

            combined AS (
                SELECT
                    ph.player_name,
                    ph.hands,
                    ph.merged_nicks,

                    SUM(COALESCE(pf.vpip, 0)) AS vpip_made,
                    SUM(COALESCE(pf.pfr, 0)) AS pfr_made,
                    SUM(COALESCE(tb.three_bet, 0)) AS three_bet_made,

                    SUM(COALESCE(ps.flop_cbet, 0)) AS flop_cbet_made,
                    SUM(COALESCE(ps.flop_cbet_opp, 0)) AS flop_cbet_opp,

                    SUM(COALESCE(ps.turn_barrel, 0)) AS turn_barrel_made,
                    SUM(COALESCE(ps.turn_barrel_opp, 0)) AS turn_barrel_opp,

                    SUM(COALESCE(ps.river_barrel, 0)) AS river_barrel_made,
                    SUM(COALESCE(ps.river_barrel_opp, 0)) AS river_barrel_opp

                FROM player_hands ph
                LEFT JOIN preflop_flags pf
                  ON pf.player_name = ph.player_name
                LEFT JOIN three_bet_flags tb
                  ON tb.player_name = pf.player_name
                 AND tb.hand_id = pf.hand_id
                LEFT JOIN postflop_flags ps
                  ON ps.player_name = pf.player_name
                 AND ps.hand_id = pf.hand_id
                GROUP BY
                    ph.player_name,
                    ph.hands,
                    ph.merged_nicks
            )

            SELECT
                player_name,
                hands,

                100.0 * vpip_made
                    / NULLIF(hands, 0) AS vpip,

                100.0 * pfr_made
                    / NULLIF(hands, 0) AS pfr,

                100.0 * three_bet_made
                    / NULLIF(hands, 0) AS three_bet,

                100.0 * flop_cbet_made
                    / NULLIF(flop_cbet_opp, 0) AS flop_cbet,

                flop_cbet_made,
                flop_cbet_opp,

                100.0 * turn_barrel_made
                    / NULLIF(turn_barrel_opp, 0) AS turn_barrel,

                turn_barrel_made,
                turn_barrel_opp,

                100.0 * river_barrel_made
                    / NULLIF(river_barrel_opp, 0) AS river_barrel,

                river_barrel_made,
                river_barrel_opp,
                merged_nicks

            FROM combined
            WHERE hands >= ?
            ORDER BY hands DESC
            LIMIT ?
        """

        params.extend(
            [
                max(1, int(minimum_hands)),
                max(1, int(limit)),
            ]
        )

        with self.connect() as con:
            rows = con.execute(query, params).fetchall()

        result: list[dict] = []

        for row in rows:
            result.append(
                {
                    "player_name": row[0],
                    "hands": int(row[1] or 0),
                    "vpip": float(row[2] or 0.0),
                    "pfr": float(row[3] or 0.0),
                    "three_bet": float(row[4] or 0.0),
                    "flop_cbet": self._nullable_float(row[5]),
                    "flop_cbet_made": int(row[6] or 0),
                    "flop_cbet_opp": int(row[7] or 0),
                    "turn_barrel": self._nullable_float(row[8]),
                    "turn_barrel_made": int(row[9] or 0),
                    "turn_barrel_opp": int(row[10] or 0),
                    "river_barrel": self._nullable_float(row[11]),
                    "river_barrel_made": int(row[12] or 0),
                    "river_barrel_opp": int(row[13] or 0),
                    "merged_nicks": int(row[14] or 1),
                }
            )

        return result

    def _table_exists(self, table_name: str) -> bool:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND LOWER(table_name) = LOWER(?)
                """,
                [table_name],
            ).fetchone()

        return bool(row and int(row[0] or 0) > 0)

    def _extra_hand_filter(
        self,
        site: str,
        stakes: str,
    ) -> str:
        parts: list[str] = []

        if site:
            escaped = site.replace("'", "''")
            parts.append(f"h.site = '{escaped}'")

        if stakes:
            escaped = stakes.replace("'", "''")
            parts.append(f"h.stakes = '{escaped}'")

        if not parts:
            return ""

        return " AND " + " AND ".join(parts)

    def _nullable_float(
        self,
        value: object,
    ) -> float | None:
        if value is None:
            return None
        return float(value)
