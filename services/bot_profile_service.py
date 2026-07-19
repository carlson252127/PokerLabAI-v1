from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from services.open_size_analysis_service import OpenSizeAnalysisService
from services.player_stats_service import PlayerStatsService


class BotProfileService:
    METRICS = [
        ("VPIP", "vpip"),
        ("PFR", "pfr"),
        ("3Bet", "three_bet"),
        ("Flop CBet IP", "flop_cbet_ip"),
        ("Flop CBet OOP", "flop_cbet_oop"),
        ("Flop XR/Raise IP", "flop_raise_ip"),
        ("Flop XR OOP", "flop_raise_oop"),
        ("Turn Barrel IP", "turn_barrel_ip"),
        ("Turn Barrel OOP", "turn_barrel_oop"),
        ("Turn XR/Raise IP", "turn_raise_ip"),
        ("Turn XR OOP", "turn_raise_oop"),
        ("Turn Stab/Probe IP", "turn_probe_ip"),
        ("Turn Probe OOP", "turn_probe_oop"),
        ("Delay CBet IP", "delay_cbet_ip"),
        ("Delay CBet OOP", "delay_cbet_oop"),
        ("Fold vs Delay IP", "fold_vs_delay_ip"),
        ("Fold vs Delay OOP", "fold_vs_delay_oop"),
        ("River Barrel IP", "river_barrel_ip"),
        ("River Barrel OOP", "river_barrel_oop"),
        ("River XR/Raise IP", "river_raise_ip"),
        ("River XR OOP", "river_raise_oop"),
        ("River Stab/Probe IP", "river_probe_ip"),
        ("River Probe OOP", "river_probe_oop"),
        ("Ort. Open Size", "avg_size_bb"),
        ("Open WWSF", "open_wwsf"),
        ("Open W$SD", "open_wsd"),
    ]

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.player_service = PlayerStatsService(self.database_path)
        self.open_service = OpenSizeAnalysisService(self.database_path)

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(
            self.database_path,
            read_only=True,
        )

    def available_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 100,
    ) -> list[dict[str, Any]]:
        return self.player_service.get_players(
            site=site,
            stakes=stakes,
            name_query="",
            minimum_hands=minimum_hands,
            limit=5000,
            use_aliases=mode.upper() == "ALIAS",
        )

    def build_profile(
        self,
        mode: str,
        entity_name: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 100,
    ) -> dict[str, Any]:
        mode = mode.upper()
        use_aliases = mode == "ALIAS"

        entity_rows = self.player_service.get_players(
            site=site,
            stakes=stakes,
            name_query=entity_name,
            minimum_hands=minimum_hands,
            limit=5000,
            use_aliases=use_aliases,
        )

        entity = next(
            (
                row
                for row in entity_rows
                if row["player_name"] == entity_name
            ),
            None,
        )

        if entity is None:
            raise ValueError(
                "Seçilen oyuncu veya alias profili bulunamadı."
            )

        pool_rows = self.player_service.get_players(
            site=site,
            stakes=stakes,
            name_query="",
            minimum_hands=1,
            limit=100000,
            use_aliases=False,
        )

        pool_preflop = self._weighted_preflop_pool(pool_rows)

        entity_postflop = self._postflop_stats(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )

        pool_postflop = self._postflop_stats(
            mode="POOL",
            entity_name="",
            site=site,
            stakes=stakes,
        )

        open_mode = "ALIAS" if mode == "ALIAS" else "PLAYER"

        entity_open = self.open_service.analyze(
            mode=open_mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position="",
            minimum_sample=1,
        )["entity"]

        pool_open = self.open_service.analyze(
            mode="POOL",
            entity_name="",
            site=site,
            stakes=stakes,
            position="",
            minimum_sample=1,
        )["entity"]

        entity_values = {
            "vpip": float(entity.get("vpip") or 0.0),
            "pfr": float(entity.get("pfr") or 0.0),
            "three_bet": float(entity.get("three_bet") or 0.0),
            "avg_size_bb": float(entity_open.get("avg_size_bb") or 0.0),
            "open_wwsf": float(entity_open.get("wwsf") or 0.0),
            "open_wsd": float(entity_open.get("wsd") or 0.0),
            **{
                key: float(entity_postflop.get(key) or 0.0)
                for key in (
                    "flop_cbet_ip",
                    "flop_cbet_oop",
                    "turn_barrel_ip",
                    "turn_barrel_oop",
                    "river_barrel_ip",
                    "river_barrel_oop",
                    "flop_raise_ip",
                    "flop_raise_oop",
                    "turn_raise_ip",
                    "turn_raise_oop",
                    "river_raise_ip",
                    "river_raise_oop",
                    "turn_probe_ip",
                    "turn_probe_oop",
                    "river_probe_ip",
                    "river_probe_oop",
                    "delay_cbet_ip",
                    "delay_cbet_oop",
                    "fold_vs_delay_ip",
                    "fold_vs_delay_oop",
                )
            },
        }

        pool_values = {
            "vpip": pool_preflop["vpip"],
            "pfr": pool_preflop["pfr"],
            "three_bet": pool_preflop["three_bet"],
            "avg_size_bb": float(pool_open.get("avg_size_bb") or 0.0),
            "open_wwsf": float(pool_open.get("wwsf") or 0.0),
            "open_wsd": float(pool_open.get("wsd") or 0.0),
            **{
                key: float(pool_postflop.get(key) or 0.0)
                for key in (
                    "flop_cbet_ip",
                    "flop_cbet_oop",
                    "turn_barrel_ip",
                    "turn_barrel_oop",
                    "river_barrel_ip",
                    "river_barrel_oop",
                    "flop_raise_ip",
                    "flop_raise_oop",
                    "turn_raise_ip",
                    "turn_raise_oop",
                    "river_raise_ip",
                    "river_raise_oop",
                    "turn_probe_ip",
                    "turn_probe_oop",
                    "river_probe_ip",
                    "river_probe_oop",
                    "delay_cbet_ip",
                    "delay_cbet_oop",
                    "fold_vs_delay_ip",
                    "fold_vs_delay_oop",
                )
            },
        }

        metrics: list[dict[str, Any]] = []

        for label, key in self.METRICS:
            entity_value = entity_values[key]
            pool_value = pool_values[key]
            delta = entity_value - pool_value

            metric = {
                "label": label,
                "key": key,
                "entity": entity_value,
                "pool": pool_value,
                "delta": delta,
                "interpretation": self._interpret(key, delta),
            }

            opp_key = f"{key}_opp"

            if opp_key in entity_postflop:
                metric["entity_opportunity"] = int(
                    entity_postflop[opp_key]
                )
                metric["pool_opportunity"] = int(
                    pool_postflop[opp_key]
                )

            metrics.append(metric)

        metrics.sort(
            key=lambda row: abs(float(row["delta"])),
            reverse=True,
        )

        strongest = metrics[0] if metrics else None

        return {
            "entity_name": entity_name,
            "hands": int(entity.get("hands") or 0),
            "merged_nicks": int(entity.get("merged_nicks") or 1),
            "metrics": metrics,
            "strongest": strongest,
            "summary": self._summary(metrics),
            "notes": [
                (
                    "IP/OOP yalnızca heads-up postflop ellerde, "
                    "street aksiyon sırasına göre hesaplanır."
                ),
                (
                    "3Bet fırsat hesabı henüz doğrulanmadı ve "
                    "Bot DNA skoruna dahil edilmez."
                ),
            ],
        }

    def _postflop_stats(
        self,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        if mode == "PLAYER":
            clauses.append("hp.player_name = ?")
            params.append(entity_name)
        elif mode == "ALIAS":
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM player_aliases pa
                    WHERE pa.player_name = hp.player_name
                      AND pa.alias_name = ?
                )
                """
            )
            params.append(entity_name)
        elif mode != "POOL":
            raise ValueError("Mode PLAYER, ALIAS veya POOL olmalı.")

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        query = f"""
            WITH selected AS (
                SELECT DISTINCT
                    hp.hand_id,
                    hp.player_name,
                    h.flop,
                    h.turn,
                    h.river
                FROM hand_players hp
                JOIN hands h
                  ON h.hand_id = hp.hand_id
                {where_sql}
            ),

            last_preflop_raiser AS (
                SELECT hand_id, player_name
                FROM (
                    SELECT
                        hand_id,
                        player_name,
                        ROW_NUMBER() OVER (
                            PARTITION BY hand_id
                            ORDER BY sequence_no DESC
                        ) AS rn
                    FROM actions
                    WHERE UPPER(TRIM(street)) = 'PREFLOP'
                      AND UPPER(TRIM(action)) = 'RAISE'
                )
                WHERE rn = 1
            ),

            postflop_players AS (
                SELECT
                    hand_id,
                    COUNT(DISTINCT player_name) AS player_count
                FROM actions
                WHERE UPPER(TRIM(street))
                      IN ('FLOP', 'TURN', 'RIVER')
                GROUP BY hand_id
            ),

            first_action AS (
                SELECT
                    hand_id,
                    UPPER(TRIM(street)) AS street,
                    player_name,
                    sequence_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY hand_id, UPPER(TRIM(street))
                        ORDER BY sequence_no
                    ) AS rn
                FROM actions
                WHERE UPPER(TRIM(street))
                      IN ('FLOP', 'TURN', 'RIVER')
            ),

            last_action AS (
                SELECT
                    hand_id,
                    UPPER(TRIM(street)) AS street,
                    player_name,
                    sequence_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY hand_id, UPPER(TRIM(street))
                        ORDER BY sequence_no DESC
                    ) AS rn
                FROM actions
                WHERE UPPER(TRIM(street))
                      IN ('FLOP', 'TURN', 'RIVER')
            ),

            flags AS (
                SELECT
                    s.hand_id,
                    s.player_name,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND lpr.player_name = s.player_name
                         AND s.flop IS NOT NULL
                         AND TRIM(s.flop) <> ''
                         AND la_flop.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS flop_cbet_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND lpr.player_name = s.player_name
                         AND s.flop IS NOT NULL
                         AND TRIM(s.flop) <> ''
                         AND fa_flop.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS flop_cbet_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'FLOP'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                        )
                        THEN 1 ELSE 0
                    END AS flop_bet_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'FLOP'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND la_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS turn_barrel_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'FLOP'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND fa_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS turn_barrel_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'TURN'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                        )
                        THEN 1 ELSE 0
                    END AS turn_bet_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.river IS NOT NULL
                         AND TRIM(s.river) <> ''
                         AND EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'TURN'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND la_river.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS river_barrel_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.river IS NOT NULL
                         AND TRIM(s.river) <> ''
                         AND EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'TURN'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND fa_river.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS river_barrel_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions a
                            WHERE a.hand_id = s.hand_id
                              AND a.player_name = s.player_name
                              AND UPPER(TRIM(a.street)) = 'RIVER'
                              AND UPPER(TRIM(a.action))
                                  IN ('BET', 'RAISE')
                        )
                        THEN 1 ELSE 0
                    END AS river_bet_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND la_flop.player_name = s.player_name
                         AND EXISTS (
                            SELECT 1
                            FROM actions bet_a
                            WHERE bet_a.hand_id = s.hand_id
                              AND UPPER(TRIM(bet_a.street)) = 'FLOP'
                              AND UPPER(TRIM(bet_a.action)) = 'BET'
                              AND bet_a.player_name <> s.player_name
                              AND bet_a.sequence_no < (
                                  SELECT MIN(resp.sequence_no)
                                  FROM actions resp
                                  WHERE resp.hand_id = s.hand_id
                                    AND resp.player_name = s.player_name
                                    AND UPPER(TRIM(resp.street)) = 'FLOP'
                                    AND resp.sequence_no > bet_a.sequence_no
                              )
                         )
                        THEN 1 ELSE 0
                    END AS flop_raise_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND fa_flop.player_name = s.player_name
                         AND EXISTS (
                            SELECT 1
                            FROM actions chk
                            JOIN actions bet_a
                              ON bet_a.hand_id = chk.hand_id
                             AND UPPER(TRIM(bet_a.street)) = 'FLOP'
                             AND UPPER(TRIM(bet_a.action)) = 'BET'
                             AND bet_a.player_name <> s.player_name
                             AND bet_a.sequence_no > chk.sequence_no
                            WHERE chk.hand_id = s.hand_id
                              AND chk.player_name = s.player_name
                              AND UPPER(TRIM(chk.street)) = 'FLOP'
                              AND UPPER(TRIM(chk.action)) = 'CHECK'
                         )
                        THEN 1 ELSE 0
                    END AS flop_raise_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions r
                            WHERE r.hand_id = s.hand_id
                              AND r.player_name = s.player_name
                              AND UPPER(TRIM(r.street)) = 'FLOP'
                              AND UPPER(TRIM(r.action)) = 'RAISE'
                        )
                        THEN 1 ELSE 0
                    END AS flop_raise_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND la_turn.player_name = s.player_name
                         AND EXISTS (
                            SELECT 1
                            FROM actions bet_a
                            WHERE bet_a.hand_id = s.hand_id
                              AND UPPER(TRIM(bet_a.street)) = 'TURN'
                              AND UPPER(TRIM(bet_a.action)) = 'BET'
                              AND bet_a.player_name <> s.player_name
                         )
                        THEN 1 ELSE 0
                    END AS turn_raise_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND fa_turn.player_name = s.player_name
                         AND EXISTS (
                            SELECT 1
                            FROM actions chk
                            JOIN actions bet_a
                              ON bet_a.hand_id = chk.hand_id
                             AND UPPER(TRIM(bet_a.street)) = 'TURN'
                             AND UPPER(TRIM(bet_a.action)) = 'BET'
                             AND bet_a.player_name <> s.player_name
                             AND bet_a.sequence_no > chk.sequence_no
                            WHERE chk.hand_id = s.hand_id
                              AND chk.player_name = s.player_name
                              AND UPPER(TRIM(chk.street)) = 'TURN'
                              AND UPPER(TRIM(chk.action)) = 'CHECK'
                         )
                        THEN 1 ELSE 0
                    END AS turn_raise_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions r
                            WHERE r.hand_id = s.hand_id
                              AND r.player_name = s.player_name
                              AND UPPER(TRIM(r.street)) = 'TURN'
                              AND UPPER(TRIM(r.action)) = 'RAISE'
                        )
                        THEN 1 ELSE 0
                    END AS turn_raise_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND la_river.player_name = s.player_name
                         AND EXISTS (
                            SELECT 1
                            FROM actions bet_a
                            WHERE bet_a.hand_id = s.hand_id
                              AND UPPER(TRIM(bet_a.street)) = 'RIVER'
                              AND UPPER(TRIM(bet_a.action)) = 'BET'
                              AND bet_a.player_name <> s.player_name
                         )
                        THEN 1 ELSE 0
                    END AS river_raise_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND fa_river.player_name = s.player_name
                         AND EXISTS (
                            SELECT 1
                            FROM actions chk
                            JOIN actions bet_a
                              ON bet_a.hand_id = chk.hand_id
                             AND UPPER(TRIM(bet_a.street)) = 'RIVER'
                             AND UPPER(TRIM(bet_a.action)) = 'BET'
                             AND bet_a.player_name <> s.player_name
                             AND bet_a.sequence_no > chk.sequence_no
                            WHERE chk.hand_id = s.hand_id
                              AND chk.player_name = s.player_name
                              AND UPPER(TRIM(chk.street)) = 'RIVER'
                              AND UPPER(TRIM(chk.action)) = 'CHECK'
                         )
                        THEN 1 ELSE 0
                    END AS river_raise_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions r
                            WHERE r.hand_id = s.hand_id
                              AND r.player_name = s.player_name
                              AND UPPER(TRIM(r.street)) = 'RIVER'
                              AND UPPER(TRIM(r.action)) = 'RAISE'
                        )
                        THEN 1 ELSE 0
                    END AS river_raise_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND NOT EXISTS (
                            SELECT 1
                            FROM actions ag
                            WHERE ag.hand_id = s.hand_id
                              AND UPPER(TRIM(ag.street)) = 'FLOP'
                              AND UPPER(TRIM(ag.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND la_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS turn_probe_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND NOT EXISTS (
                            SELECT 1
                            FROM actions ag
                            WHERE ag.hand_id = s.hand_id
                              AND UPPER(TRIM(ag.street)) = 'FLOP'
                              AND UPPER(TRIM(ag.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND fa_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS turn_probe_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions b
                            WHERE b.hand_id = s.hand_id
                              AND b.player_name = s.player_name
                              AND UPPER(TRIM(b.street)) = 'TURN'
                              AND UPPER(TRIM(b.action)) = 'BET'
                        )
                        THEN 1 ELSE 0
                    END AS turn_probe_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.river IS NOT NULL
                         AND TRIM(s.river) <> ''
                         AND NOT EXISTS (
                            SELECT 1
                            FROM actions ag
                            WHERE ag.hand_id = s.hand_id
                              AND UPPER(TRIM(ag.street)) = 'TURN'
                              AND UPPER(TRIM(ag.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND la_river.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS river_probe_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND s.river IS NOT NULL
                         AND TRIM(s.river) <> ''
                         AND NOT EXISTS (
                            SELECT 1
                            FROM actions ag
                            WHERE ag.hand_id = s.hand_id
                              AND UPPER(TRIM(ag.street)) = 'TURN'
                              AND UPPER(TRIM(ag.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND fa_river.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS river_probe_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions b
                            WHERE b.hand_id = s.hand_id
                              AND b.player_name = s.player_name
                              AND UPPER(TRIM(b.street)) = 'RIVER'
                              AND UPPER(TRIM(b.action)) = 'BET'
                        )
                        THEN 1 ELSE 0
                    END AS river_probe_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND lpr.player_name = s.player_name
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND NOT EXISTS (
                            SELECT 1
                            FROM actions fb
                            WHERE fb.hand_id = s.hand_id
                              AND fb.player_name = s.player_name
                              AND UPPER(TRIM(fb.street)) = 'FLOP'
                              AND UPPER(TRIM(fb.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND la_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS delay_cbet_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND lpr.player_name = s.player_name
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND NOT EXISTS (
                            SELECT 1
                            FROM actions fb
                            WHERE fb.hand_id = s.hand_id
                              AND fb.player_name = s.player_name
                              AND UPPER(TRIM(fb.street)) = 'FLOP'
                              AND UPPER(TRIM(fb.action))
                                  IN ('BET', 'RAISE')
                         )
                         AND fa_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS delay_cbet_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions tb
                            WHERE tb.hand_id = s.hand_id
                              AND tb.player_name = s.player_name
                              AND UPPER(TRIM(tb.street)) = 'TURN'
                              AND UPPER(TRIM(tb.action)) = 'BET'
                         )
                        THEN 1 ELSE 0
                    END AS delay_cbet_made,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND lpr.player_name <> s.player_name
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND EXISTS (
                            SELECT 1
                            FROM actions delay_bet
                            WHERE delay_bet.hand_id = s.hand_id
                              AND delay_bet.player_name = lpr.player_name
                              AND UPPER(TRIM(delay_bet.street)) = 'TURN'
                              AND UPPER(TRIM(delay_bet.action)) = 'BET'
                         )
                         AND la_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS fold_vs_delay_ip_opp,

                    CASE
                        WHEN COALESCE(pp.player_count, 0) = 2
                         AND lpr.player_name <> s.player_name
                         AND s.turn IS NOT NULL
                         AND TRIM(s.turn) <> ''
                         AND EXISTS (
                            SELECT 1
                            FROM actions delay_bet
                            WHERE delay_bet.hand_id = s.hand_id
                              AND delay_bet.player_name = lpr.player_name
                              AND UPPER(TRIM(delay_bet.street)) = 'TURN'
                              AND UPPER(TRIM(delay_bet.action)) = 'BET'
                         )
                         AND fa_turn.player_name = s.player_name
                        THEN 1 ELSE 0
                    END AS fold_vs_delay_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions tf
                            WHERE tf.hand_id = s.hand_id
                              AND tf.player_name = s.player_name
                              AND UPPER(TRIM(tf.street)) = 'TURN'
                              AND UPPER(TRIM(tf.action)) = 'FOLD'
                         )
                        THEN 1 ELSE 0
                    END AS fold_vs_delay_made

                FROM selected s
                LEFT JOIN last_preflop_raiser lpr
                  ON lpr.hand_id = s.hand_id
                LEFT JOIN postflop_players pp
                  ON pp.hand_id = s.hand_id

                LEFT JOIN first_action fa_flop
                  ON fa_flop.hand_id = s.hand_id
                 AND fa_flop.street = 'FLOP'
                 AND fa_flop.rn = 1
                LEFT JOIN last_action la_flop
                  ON la_flop.hand_id = s.hand_id
                 AND la_flop.street = 'FLOP'
                 AND la_flop.rn = 1

                LEFT JOIN first_action fa_turn
                  ON fa_turn.hand_id = s.hand_id
                 AND fa_turn.street = 'TURN'
                 AND fa_turn.rn = 1
                LEFT JOIN last_action la_turn
                  ON la_turn.hand_id = s.hand_id
                 AND la_turn.street = 'TURN'
                 AND la_turn.rn = 1

                LEFT JOIN first_action fa_river
                  ON fa_river.hand_id = s.hand_id
                 AND fa_river.street = 'RIVER'
                 AND fa_river.rn = 1
                LEFT JOIN last_action la_river
                  ON la_river.hand_id = s.hand_id
                 AND la_river.street = 'RIVER'
                 AND la_river.rn = 1
            )

            SELECT
                SUM(
                    CASE
                        WHEN flop_cbet_ip_opp = 1
                         AND flop_bet_made = 1
                        THEN 1 ELSE 0
                    END
                ),
                SUM(flop_cbet_ip_opp),

                SUM(
                    CASE
                        WHEN flop_cbet_oop_opp = 1
                         AND flop_bet_made = 1
                        THEN 1 ELSE 0
                    END
                ),
                SUM(flop_cbet_oop_opp),

                SUM(
                    CASE
                        WHEN turn_barrel_ip_opp = 1
                         AND turn_bet_made = 1
                        THEN 1 ELSE 0
                    END
                ),
                SUM(turn_barrel_ip_opp),

                SUM(
                    CASE
                        WHEN turn_barrel_oop_opp = 1
                         AND turn_bet_made = 1
                        THEN 1 ELSE 0
                    END
                ),
                SUM(turn_barrel_oop_opp),

                SUM(
                    CASE
                        WHEN river_barrel_ip_opp = 1
                         AND river_bet_made = 1
                        THEN 1 ELSE 0
                    END
                ),
                SUM(river_barrel_ip_opp),

                SUM(
                    CASE
                        WHEN river_barrel_oop_opp = 1
                         AND river_bet_made = 1
                        THEN 1 ELSE 0
                    END
                ),
                SUM(river_barrel_oop_opp),

                SUM(CASE WHEN flop_raise_ip_opp = 1 AND flop_raise_made = 1 THEN 1 ELSE 0 END),
                SUM(flop_raise_ip_opp),
                SUM(CASE WHEN flop_raise_oop_opp = 1 AND flop_raise_made = 1 THEN 1 ELSE 0 END),
                SUM(flop_raise_oop_opp),

                SUM(CASE WHEN turn_raise_ip_opp = 1 AND turn_raise_made = 1 THEN 1 ELSE 0 END),
                SUM(turn_raise_ip_opp),
                SUM(CASE WHEN turn_raise_oop_opp = 1 AND turn_raise_made = 1 THEN 1 ELSE 0 END),
                SUM(turn_raise_oop_opp),

                SUM(CASE WHEN river_raise_ip_opp = 1 AND river_raise_made = 1 THEN 1 ELSE 0 END),
                SUM(river_raise_ip_opp),
                SUM(CASE WHEN river_raise_oop_opp = 1 AND river_raise_made = 1 THEN 1 ELSE 0 END),
                SUM(river_raise_oop_opp),

                SUM(CASE WHEN turn_probe_ip_opp = 1 AND turn_probe_made = 1 THEN 1 ELSE 0 END),
                SUM(turn_probe_ip_opp),
                SUM(CASE WHEN turn_probe_oop_opp = 1 AND turn_probe_made = 1 THEN 1 ELSE 0 END),
                SUM(turn_probe_oop_opp),

                SUM(CASE WHEN river_probe_ip_opp = 1 AND river_probe_made = 1 THEN 1 ELSE 0 END),
                SUM(river_probe_ip_opp),
                SUM(CASE WHEN river_probe_oop_opp = 1 AND river_probe_made = 1 THEN 1 ELSE 0 END),
                SUM(river_probe_oop_opp),

                SUM(CASE WHEN delay_cbet_ip_opp = 1 AND delay_cbet_made = 1 THEN 1 ELSE 0 END),
                SUM(delay_cbet_ip_opp),
                SUM(CASE WHEN delay_cbet_oop_opp = 1 AND delay_cbet_made = 1 THEN 1 ELSE 0 END),
                SUM(delay_cbet_oop_opp),

                SUM(CASE WHEN fold_vs_delay_ip_opp = 1 AND fold_vs_delay_made = 1 THEN 1 ELSE 0 END),
                SUM(fold_vs_delay_ip_opp),
                SUM(CASE WHEN fold_vs_delay_oop_opp = 1 AND fold_vs_delay_made = 1 THEN 1 ELSE 0 END),
                SUM(fold_vs_delay_oop_opp)
            FROM flags
        """

        with self.connect() as con:
            row = con.execute(query, params).fetchone()

        values = [int(value or 0) for value in row]

        names = [
            "flop_cbet_ip",
            "flop_cbet_oop",
            "turn_barrel_ip",
            "turn_barrel_oop",
            "river_barrel_ip",
            "river_barrel_oop",
            "flop_raise_ip",
            "flop_raise_oop",
            "turn_raise_ip",
            "turn_raise_oop",
            "river_raise_ip",
            "river_raise_oop",
            "turn_probe_ip",
            "turn_probe_oop",
            "river_probe_ip",
            "river_probe_oop",
            "delay_cbet_ip",
            "delay_cbet_oop",
            "fold_vs_delay_ip",
            "fold_vs_delay_oop",
        ]

        result: dict[str, Any] = {}

        for index, name in enumerate(names):
            made = values[index * 2]
            opportunity = values[index * 2 + 1]

            result[name] = self._pct(made, opportunity)
            result[f"{name}_made"] = made
            result[f"{name}_opp"] = opportunity

        return result

    def _weighted_preflop_pool(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, float]:
        total_hands = sum(
            int(row.get("hands") or 0)
            for row in rows
        )

        if total_hands <= 0:
            return {
                "vpip": 0.0,
                "pfr": 0.0,
                "three_bet": 0.0,
            }

        def weighted(key: str) -> float:
            return sum(
                float(row.get(key) or 0.0)
                * int(row.get("hands") or 0)
                for row in rows
            ) / total_hands

        return {
            "vpip": weighted("vpip"),
            "pfr": weighted("pfr"),
            "three_bet": weighted("three_bet"),
        }

    def _interpret(
        self,
        key: str,
        delta: float,
    ) -> str:
        if key == "avg_size_bb":
            if delta >= 0.15:
                return "Pooldan daha büyük open"
            if delta <= -0.15:
                return "Pooldan daha küçük open"
            return "Open sizing poola yakın"

        if key == "three_bet":
            return (
                "3Bet geçici değer; doğrulanacak"
            )

        if abs(delta) < 3.0:
            return "Poola yakın"

        readable = {
            "flop_cbet_ip": "IP flop c-bet",
            "flop_cbet_oop": "OOP flop c-bet",
            "turn_barrel_ip": "IP turn barrel",
            "turn_barrel_oop": "OOP turn barrel",
            "river_barrel_ip": "IP river barrel",
            "river_barrel_oop": "OOP river barrel",
            "flop_raise_ip": "IP flop raise vs bet",
            "flop_raise_oop": "OOP flop check-raise",
            "turn_raise_ip": "IP turn raise vs bet",
            "turn_raise_oop": "OOP turn check-raise",
            "river_raise_ip": "IP river raise vs bet",
            "river_raise_oop": "OOP river check-raise",
            "turn_probe_ip": "IP turn stab/probe",
            "turn_probe_oop": "OOP turn probe",
            "river_probe_ip": "IP river stab/probe",
            "river_probe_oop": "OOP river probe",
            "delay_cbet_ip": "IP delayed c-bet",
            "delay_cbet_oop": "OOP delayed c-bet",
            "fold_vs_delay_ip": "IP fold vs delayed c-bet",
            "fold_vs_delay_oop": "OOP fold vs delayed c-bet",
            "vpip": "VPIP",
            "pfr": "PFR",
            "open_wwsf": "Open WWSF",
            "open_wsd": "Open W$SD",
        }.get(key, key)

        return (
            f"{readable} pooldan daha yüksek"
            if delta > 0
            else f"{readable} pooldan daha düşük"
        )

    def _summary(
        self,
        metrics: list[dict[str, Any]],
    ) -> str:
        valid = [
            row
            for row in metrics
            if row["key"] != "three_bet"
        ]

        meaningful = sorted(
            valid,
            key=lambda row: abs(row["delta"]),
            reverse=True,
        )[:3]

        if not meaningful:
            return "Profil poola yakın."

        return " | ".join(
            f"{row['label']}: {row['delta']:+.2f}"
            for row in meaningful
        )

    def _pct(
        self,
        numerator: int,
        denominator: int,
    ) -> float:
        if denominator <= 0:
            return 0.0

        return max(
            0.0,
            min(
                100.0,
                numerator / denominator * 100.0,
            ),
        )
