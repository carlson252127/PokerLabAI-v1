from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb


class SpotEngine:
    SUPPORTED_STATS = {
        "VPIP": "vpip",
        "PFR": "pfr",
        "3Bet": "three_bet",
        "Flop PFR CBet": "flop_pfr_cbet",
        "Turn PFR Barrel": "turn_pfr_barrel",
        "River PFR Barrel": "river_pfr_barrel",
        "Flop Fold vs Bet": "flop_fold_vs_bet",
        "Turn Fold vs Bet": "turn_fold_vs_bet",
        "River Fold vs Bet": "river_fold_vs_bet",
        "Flop Check-Raise": "flop_check_raise",
        "Turn Check-Raise": "turn_check_raise",
        "River Check-Raise": "river_check_raise",
        "Flop Donk": "flop_donk",
        "Turn Probe": "turn_probe",
        "River Bet": "river_bet",
    }

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path)

    def calculate(
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
        if stat_key == "vpip":
            return self._vpip(
                site,
                stakes,
                hero_position,
            )

        if stat_key == "pfr":
            return self._pfr(
                site,
                stakes,
                hero_position,
            )

        if stat_key == "three_bet":
            return self._three_bet(
                site,
                stakes,
                hero_position,
                villain_position,
            )

        if stat_key == "flop_pfr_cbet":
            return self._pfr_bet_stat(
                street="FLOP",
                site=site,
                stakes=stakes,
                hero_position=hero_position,
                villain_position=villain_position,
                location=location,
                pot_type=pot_type,
                board_texture=board_texture,
            )

        if stat_key == "turn_pfr_barrel":
            return self._pfr_bet_stat(
                street="TURN",
                site=site,
                stakes=stakes,
                hero_position=hero_position,
                villain_position=villain_position,
                location=location,
                pot_type=pot_type,
                board_texture=board_texture,
            )

        if stat_key == "river_pfr_barrel":
            return self._pfr_bet_stat(
                street="RIVER",
                site=site,
                stakes=stakes,
                hero_position=hero_position,
                villain_position=villain_position,
                location=location,
                pot_type=pot_type,
                board_texture=board_texture,
            )

        if stat_key.endswith("_fold_vs_bet"):
            street = stat_key.split("_")[0].upper()
            return self._fold_vs_bet(
                street,
                site,
                stakes,
                hero_position,
                villain_position,
                location,
                pot_type,
                board_texture,
            )

        if stat_key.endswith("_check_raise"):
            street = stat_key.split("_")[0].upper()
            return self._check_raise(
                street,
                site,
                stakes,
                hero_position,
                villain_position,
                location,
                pot_type,
                board_texture,
            )

        if stat_key == "flop_donk":
            return self._donk(
                "FLOP",
                site,
                stakes,
                hero_position,
                villain_position,
                location,
                pot_type,
                board_texture,
            )

        if stat_key == "turn_probe":
            return self._probe(
                site,
                stakes,
                hero_position,
                villain_position,
                location,
                pot_type,
                board_texture,
            )

        if stat_key == "river_bet":
            return self._street_bet(
                "RIVER",
                site,
                stakes,
                hero_position,
                villain_position,
                location,
                pot_type,
                board_texture,
            )

        raise ValueError(f"Desteklenmeyen stat: {stat_key}")

    def _hand_filters(
        self,
        site: str,
        stakes: str,
    ) -> tuple[list[str], list[str]]:
        clauses: list[str] = []
        params: list[str] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        return clauses, params

    def _player_filter(
        self,
        alias: str,
        position: str,
        clauses: list[str],
        params: list[str],
    ) -> None:
        if position:
            clauses.append(f"{alias}.position = ?")
            params.append(position)

    def _location_filter(
        self,
        hero_alias: str,
        villain_alias: str,
        location: str,
        clauses: list[str],
    ) -> None:
        if location == "IP":
            clauses.append(
                f"""
                CASE {hero_alias}.position
                    WHEN 'BTN' THEN 6
                    WHEN 'CO' THEN 5
                    WHEN 'HJ' THEN 4
                    WHEN 'UTG' THEN 3
                    WHEN 'SB' THEN 2
                    WHEN 'BB' THEN 1
                    ELSE 0
                END
                >
                CASE {villain_alias}.position
                    WHEN 'BTN' THEN 6
                    WHEN 'CO' THEN 5
                    WHEN 'HJ' THEN 4
                    WHEN 'UTG' THEN 3
                    WHEN 'SB' THEN 2
                    WHEN 'BB' THEN 1
                    ELSE 0
                END
                """
            )

        elif location == "OOP":
            clauses.append(
                f"""
                CASE {hero_alias}.position
                    WHEN 'BTN' THEN 6
                    WHEN 'CO' THEN 5
                    WHEN 'HJ' THEN 4
                    WHEN 'UTG' THEN 3
                    WHEN 'SB' THEN 2
                    WHEN 'BB' THEN 1
                    ELSE 0
                END
                <
                CASE {villain_alias}.position
                    WHEN 'BTN' THEN 6
                    WHEN 'CO' THEN 5
                    WHEN 'HJ' THEN 4
                    WHEN 'UTG' THEN 3
                    WHEN 'SB' THEN 2
                    WHEN 'BB' THEN 1
                    ELSE 0
                END
                """
            )

    def _pot_type_filter(
        self,
        pot_type: str,
        clauses: list[str],
    ) -> None:
        if not pot_type:
            return

        if pot_type == "SRP":
            clauses.append("pf.raise_count = 1")
        elif pot_type == "3BET":
            clauses.append("pf.raise_count = 2")
        elif pot_type == "4BET":
            clauses.append("pf.raise_count >= 3")
        elif pot_type == "LIMP":
            clauses.append(
                "pf.raise_count = 0 AND pf.call_count > 0"
            )

    def _board_texture_filter(
        self,
        board_texture: str,
        clauses: list[str],
        params: list[str],
    ) -> None:
        if not board_texture:
            return

        if board_texture in {
            "RAINBOW",
            "TWO_TONE",
            "MONOTONE",
        }:
            clauses.append("h.flop_suit_type = ?")
            params.append(board_texture)
            return

        if board_texture in {
            "PAIRED",
            "TRIPS",
        }:
            clauses.append("h.flop_paired_type = ?")
            params.append(board_texture)
            return

        if board_texture == "CONNECTED":
            clauses.append("h.flop_connected = TRUE")
            return

        clauses.append("h.flop_texture = ?")
        params.append(board_texture)

    def _vpip(
        self,
        site: str,
        stakes: str,
        hero_position: str,
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hp",
            hero_position,
            clauses,
            params,
        )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        with self.connect() as con:
            denominator = int(
                con.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where}
                    """,
                    params,
                ).fetchone()[0]
            )

            numerator = int(
                con.execute(
                    f"""
                    SELECT COUNT(DISTINCT
                        a.hand_id || '|' || a.player_name
                    )
                    FROM actions a
                    JOIN hands h ON h.hand_id = a.hand_id
                    JOIN hand_players hp
                      ON hp.hand_id = a.hand_id
                     AND hp.player_name = a.player_name
                    {where}
                    {"AND" if where else "WHERE"}
                        a.street = 'PREFLOP'
                        AND a.action IN ('CALL', 'RAISE')
                    """,
                    params,
                ).fetchone()[0]
            )

        return self._result(numerator, denominator)

    def _pfr(
        self,
        site: str,
        stakes: str,
        hero_position: str,
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hp",
            hero_position,
            clauses,
            params,
        )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        with self.connect() as con:
            denominator = int(
                con.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where}
                    """,
                    params,
                ).fetchone()[0]
            )

            numerator = int(
                con.execute(
                    f"""
                    SELECT COUNT(DISTINCT
                        a.hand_id || '|' || a.player_name
                    )
                    FROM actions a
                    JOIN hands h ON h.hand_id = a.hand_id
                    JOIN hand_players hp
                      ON hp.hand_id = a.hand_id
                     AND hp.player_name = a.player_name
                    {where}
                    {"AND" if where else "WHERE"}
                        a.street = 'PREFLOP'
                        AND a.action = 'RAISE'
                    """,
                    params,
                ).fetchone()[0]
            )

        return self._result(numerator, denominator)

    def _three_bet(
        self,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hero",
            hero_position,
            clauses,
            params,
        )
        self._player_filter(
            "villain",
            villain_position,
            clauses,
            params,
        )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH pf_raises AS (
                SELECT
                    a.hand_id,
                    a.player_name,
                    a.sequence_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id
                        ORDER BY a.sequence_no
                    ) AS raise_no
                FROM actions a
                WHERE a.street = 'PREFLOP'
                  AND a.action = 'RAISE'
            ),
            opportunities AS (
                SELECT DISTINCT
                    first_raise.hand_id,
                    hero.player_name AS hero_name
                FROM pf_raises first_raise
                JOIN hands h
                  ON h.hand_id = first_raise.hand_id
                JOIN hand_players villain
                  ON villain.hand_id = first_raise.hand_id
                 AND villain.player_name = first_raise.player_name
                JOIN hand_players hero
                  ON hero.hand_id = first_raise.hand_id
                 AND hero.player_name <> first_raise.player_name
                {where}
                {"AND" if where else "WHERE"}
                    first_raise.raise_no = 1
            ),
            three_bets AS (
                SELECT DISTINCT
                    r.hand_id,
                    r.player_name
                FROM pf_raises r
                WHERE r.raise_no = 2
            )
            SELECT
                COUNT(DISTINCT
                    t.hand_id || '|' || t.player_name
                ) AS made,
                COUNT(DISTINCT
                    o.hand_id || '|' || o.hero_name
                ) AS opportunities
            FROM opportunities o
            LEFT JOIN three_bets t
              ON t.hand_id = o.hand_id
             AND t.player_name = o.hero_name
        """

        with self.connect() as con:
            row = con.execute(query, params).fetchone()

        return self._result(
            int(row[0] or 0),
            int(row[1] or 0),
        )

    def _pfr_bet_stat(
        self,
        street: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hero",
            hero_position,
            clauses,
            params,
        )
        self._player_filter(
            "villain",
            villain_position,
            clauses,
            params,
        )
        self._location_filter(
            "hero",
            "villain",
            location,
            clauses,
        )
        self._pot_type_filter(
            pot_type,
            clauses,
        )
        self._board_texture_filter(
            board_texture,
            clauses,
            params,
        )

        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH pf AS (
                SELECT
                    hand_id,
                    COUNT(*) FILTER (
                        WHERE action = 'RAISE'
                    ) AS raise_count,
                    COUNT(*) FILTER (
                        WHERE action = 'CALL'
                    ) AS call_count
                FROM actions
                WHERE street = 'PREFLOP'
                GROUP BY hand_id
            ),
            pfr AS (
                SELECT DISTINCT ON (hand_id)
                    hand_id,
                    player_name
                FROM actions
                WHERE street = 'PREFLOP'
                  AND action = 'RAISE'
                ORDER BY hand_id, sequence_no DESC
            ),
            candidates AS (
                SELECT DISTINCT
                    h.hand_id,
                    pfr.player_name AS hero_name,
                    villain.player_name AS villain_name
                FROM hands h
                JOIN pf ON pf.hand_id = h.hand_id
                JOIN pfr ON pfr.hand_id = h.hand_id
                JOIN hand_players hero
                  ON hero.hand_id = h.hand_id
                 AND hero.player_name = pfr.player_name
                JOIN hand_players villain
                  ON villain.hand_id = h.hand_id
                 AND villain.player_name <> hero.player_name
                {where}
                {"AND" if where else "WHERE"}
                    EXISTS (
                        SELECT 1
                        FROM actions sx
                        WHERE sx.hand_id = h.hand_id
                          AND sx.street = ?
                    )
            )
            SELECT
                COUNT(DISTINCT
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM actions a
                        WHERE a.hand_id = c.hand_id
                          AND a.player_name = c.hero_name
                          AND a.street = ?
                          AND a.action = 'BET'
                    )
                    THEN c.hand_id || '|' || c.hero_name
                    END
                ) AS made,
                COUNT(DISTINCT
                    c.hand_id || '|' || c.hero_name
                ) AS opportunities
            FROM candidates c
        """

        with self.connect() as con:
            row = con.execute(
                query,
                params + [street, street],
            ).fetchone()

        return self._result(
            int(row[0] or 0),
            int(row[1] or 0),
        )

    def _fold_vs_bet(
        self,
        street: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        return self._response_stat(
            street,
            "FOLD",
            site,
            stakes,
            hero_position,
            villain_position,
            location,
            pot_type,
            board_texture,
        )

    def _check_raise(
        self,
        street: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hero",
            hero_position,
            clauses,
            params,
        )
        self._player_filter(
            "villain",
            villain_position,
            clauses,
            params,
        )
        self._location_filter(
            "hero",
            "villain",
            location,
            clauses,
        )
        self._pot_type_filter(
            pot_type,
            clauses,
        )
        self._board_texture_filter(
            board_texture,
            clauses,
            params,
        )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH pf AS (
                SELECT
                    hand_id,
                    COUNT(*) FILTER (
                        WHERE action = 'RAISE'
                    ) AS raise_count,
                    COUNT(*) FILTER (
                        WHERE action = 'CALL'
                    ) AS call_count
                FROM actions
                WHERE street = 'PREFLOP'
                GROUP BY hand_id
            ),
            candidates AS (
                SELECT DISTINCT
                    h.hand_id,
                    hero.player_name AS hero_name
                FROM hands h
                JOIN pf ON pf.hand_id = h.hand_id
                JOIN hand_players hero
                  ON hero.hand_id = h.hand_id
                JOIN hand_players villain
                  ON villain.hand_id = h.hand_id
                 AND villain.player_name <> hero.player_name
                {where}
                {"AND" if where else "WHERE"}
                    EXISTS (
                        SELECT 1
                        FROM actions c
                        WHERE c.hand_id = h.hand_id
                          AND c.player_name = hero.player_name
                          AND c.street = ?
                          AND c.action = 'CHECK'
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM actions b
                        WHERE b.hand_id = h.hand_id
                          AND b.player_name <> hero.player_name
                          AND b.street = ?
                          AND b.action = 'BET'
                    )
            )
            SELECT
                COUNT(DISTINCT
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM actions r
                        WHERE r.hand_id = c.hand_id
                          AND r.player_name = c.hero_name
                          AND r.street = ?
                          AND r.action = 'RAISE'
                    )
                    THEN c.hand_id || '|' || c.hero_name
                    END
                ),
                COUNT(DISTINCT
                    c.hand_id || '|' || c.hero_name
                )
            FROM candidates c
        """

        with self.connect() as con:
            row = con.execute(
                query,
                params + [street, street, street],
            ).fetchone()

        return self._result(
            int(row[0] or 0),
            int(row[1] or 0),
        )

    def _donk(
        self,
        street: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        return self._street_bet(
            street,
            site,
            stakes,
            hero_position,
            villain_position,
            location,
            pot_type,
            exclude_pfr=True,
            board_texture=board_texture,
        )

    def _probe(
        self,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        return self._street_bet(
            "TURN",
            site,
            stakes,
            hero_position,
            villain_position,
            location,
            pot_type,
            exclude_pfr=True,
            board_texture=board_texture,
        )

    def _street_bet(
        self,
        street: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        exclude_pfr: bool = False,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hero",
            hero_position,
            clauses,
            params,
        )
        self._player_filter(
            "villain",
            villain_position,
            clauses,
            params,
        )
        self._location_filter(
            "hero",
            "villain",
            location,
            clauses,
        )
        self._pot_type_filter(
            pot_type,
            clauses,
        )
        self._board_texture_filter(
            board_texture,
            clauses,
            params,
        )

        if exclude_pfr:
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM actions pr
                    WHERE pr.hand_id = h.hand_id
                      AND pr.player_name = hero.player_name
                      AND pr.street = 'PREFLOP'
                      AND pr.action = 'RAISE'
                )
                """
            )

        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH pf AS (
                SELECT
                    hand_id,
                    COUNT(*) FILTER (
                        WHERE action = 'RAISE'
                    ) AS raise_count,
                    COUNT(*) FILTER (
                        WHERE action = 'CALL'
                    ) AS call_count
                FROM actions
                WHERE street = 'PREFLOP'
                GROUP BY hand_id
            ),
            candidates AS (
                SELECT DISTINCT
                    h.hand_id,
                    hero.player_name AS hero_name
                FROM hands h
                JOIN pf ON pf.hand_id = h.hand_id
                JOIN hand_players hero
                  ON hero.hand_id = h.hand_id
                JOIN hand_players villain
                  ON villain.hand_id = h.hand_id
                 AND villain.player_name <> hero.player_name
                {where}
                {"AND" if where else "WHERE"}
                    EXISTS (
                        SELECT 1
                        FROM actions sx
                        WHERE sx.hand_id = h.hand_id
                          AND sx.street = ?
                    )
            )
            SELECT
                COUNT(DISTINCT
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM actions a
                        WHERE a.hand_id = c.hand_id
                          AND a.player_name = c.hero_name
                          AND a.street = ?
                          AND a.action = 'BET'
                    )
                    THEN c.hand_id || '|' || c.hero_name
                    END
                ),
                COUNT(DISTINCT
                    c.hand_id || '|' || c.hero_name
                )
            FROM candidates c
        """

        with self.connect() as con:
            row = con.execute(
                query,
                params + [street, street],
            ).fetchone()

        return self._result(
            int(row[0] or 0),
            int(row[1] or 0),
        )

    def _response_stat(
        self,
        street: str,
        response_action: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str = "",
    ) -> tuple[float, int, int]:
        clauses, params = self._hand_filters(site, stakes)
        self._player_filter(
            "hero",
            hero_position,
            clauses,
            params,
        )
        self._player_filter(
            "villain",
            villain_position,
            clauses,
            params,
        )
        self._location_filter(
            "hero",
            "villain",
            location,
            clauses,
        )
        self._pot_type_filter(
            pot_type,
            clauses,
        )
        self._board_texture_filter(
            board_texture,
            clauses,
            params,
        )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH pf AS (
                SELECT
                    hand_id,
                    COUNT(*) FILTER (
                        WHERE action = 'RAISE'
                    ) AS raise_count,
                    COUNT(*) FILTER (
                        WHERE action = 'CALL'
                    ) AS call_count
                FROM actions
                WHERE street = 'PREFLOP'
                GROUP BY hand_id
            ),
            opportunities AS (
                SELECT DISTINCT
                    h.hand_id,
                    hero.player_name AS hero_name
                FROM hands h
                JOIN pf ON pf.hand_id = h.hand_id
                JOIN hand_players hero
                  ON hero.hand_id = h.hand_id
                JOIN hand_players villain
                  ON villain.hand_id = h.hand_id
                 AND villain.player_name <> hero.player_name
                {where}
                {"AND" if where else "WHERE"}
                    EXISTS (
                        SELECT 1
                        FROM actions b
                        WHERE b.hand_id = h.hand_id
                          AND b.player_name <> hero.player_name
                          AND b.street = ?
                          AND b.action = 'BET'
                    )
            )
            SELECT
                COUNT(DISTINCT
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM actions f
                        WHERE f.hand_id = o.hand_id
                          AND f.player_name = o.hero_name
                          AND f.street = ?
                          AND f.action = ?
                    )
                    THEN o.hand_id || '|' || o.hero_name
                    END
                ),
                COUNT(DISTINCT
                    o.hand_id || '|' || o.hero_name
                )
            FROM opportunities o
        """

        with self.connect() as con:
            row = con.execute(
                query,
                params + [
                    street,
                    street,
                    response_action,
                ],
            ).fetchone()

        return self._result(
            int(row[0] or 0),
            int(row[1] or 0),
        )

    def _result(
        self,
        numerator: int,
        denominator: int,
    ) -> tuple[float, int, int]:
        value = (
            numerator / denominator * 100.0
            if denominator
            else 0.0
        )
        return value, numerator, denominator
