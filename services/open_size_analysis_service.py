from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from services.poker_statistics import SHOWDOWN_ACTIONS, WIN_ACTIONS, sql_values


class OpenSizeAnalysisService:
    POSITION_ORDER = ["UTG", "UTG+1", "HJ", "CO", "BTN", "SB", "BB", "OTHER"]

    METRIC_SPECS = (
        ("fold_to_three_bet", "fold_to_three_bet_sample"),
        ("flop_cbet_ip", "flop_cbet_ip_sample"),
        ("flop_cbet_oop", "flop_cbet_oop_sample"),
        ("turn_barrel_ip", "turn_barrel_ip_sample"),
        ("turn_barrel_oop", "turn_barrel_oop_sample"),
        ("river_barrel_ip", "river_barrel_ip_sample"),
        ("river_barrel_oop", "river_barrel_oop_sample"),
        ("wwsf", "wwsf_sample"),
        ("wsd", "wsd_sample"),
    )

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path, read_only=True)

    def available_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        limit: int = 5000,
    ) -> list[tuple[str, int]]:
        mode = str(mode or "").upper()
        filters: list[str] = []
        params: list[Any] = []

        if site:
            filters.append("h.site = ?")
            params.append(site)
        if stakes:
            filters.append("h.stakes = ?")
            params.append(stakes)

        where_sql = "WHERE " + " AND ".join(filters) if filters else ""

        with self.connect() as con:
            if mode == "PLAYER":
                rows = con.execute(
                    f"""
                    SELECT hp.player_name, COUNT(DISTINCT hp.hand_id) AS hands
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY hp.player_name
                    ORDER BY hands DESC
                    LIMIT {max(1, int(limit))}
                    """,
                    params,
                ).fetchall()
            elif mode in {"ALIAS", "COMPARE"}:
                exists = bool(
                    con.execute(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = 'main'
                          AND table_name = 'player_aliases'
                        """
                    ).fetchone()[0]
                )
                if not exists:
                    return []

                rows = con.execute(
                    f"""
                    SELECT pa.alias_name, COUNT(DISTINCT hp.hand_id) AS hands
                    FROM player_aliases pa
                    JOIN hand_players hp
                      ON LOWER(TRIM(hp.player_name)) = LOWER(TRIM(pa.player_name))
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY pa.alias_name
                    ORDER BY hands DESC
                    LIMIT {max(1, int(limit))}
                    """,
                    params,
                ).fetchall()
            else:
                return []

        return [(str(name), int(hands or 0)) for name, hands in rows]

    def analyze(
        self,
        mode: str = "POOL",
        entity_name: str = "",
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 1,
    ) -> dict[str, Any]:
        mode = str(mode or "POOL").upper()
        minimum_sample = max(1, int(minimum_sample))

        entity_rows = self._load_open_rows(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position=position,
        )
        entity = self._aggregate(entity_rows, minimum_sample)

        # Pool baseline is calculated for every non-pool analysis.  This keeps
        # all Pool and Delta columns populated in PLAYER, ALIAS and COMPARE modes.
        if mode == "POOL":
            pool = entity
        else:
            pool_rows = self._load_open_rows(
                mode="POOL",
                entity_name="",
                site=site,
                stakes=stakes,
                position=position,
            )
            pool = self._aggregate(pool_rows, minimum_sample)

        self._attach_pool_baseline(entity, pool)
        self._finalize_rows(entity)

        return {
            "entity": entity,
            "pool": pool if mode != "POOL" else {},
            "position_summary": self._position_summary(entity.get("rows", [])),
        }

    def _load_open_rows(
        self,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        position: str,
    ) -> list[dict[str, Any]]:
        mode = str(mode or "POOL").upper()
        clauses: list[str] = []
        params: list[Any] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)
        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)
        if position:
            clauses.append("hp.position = ?")
            params.append(position)

        if mode == "PLAYER":
            clauses.append(
                "LOWER(TRIM(hp.player_name)) = LOWER(TRIM(?))"
            )
            params.append(entity_name)
        elif mode in {"ALIAS", "COMPARE"}:
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM player_aliases pa
                    WHERE LOWER(TRIM(pa.player_name)) =
                          LOWER(TRIM(hp.player_name))
                      AND pa.alias_name = ?
                )
                """
            )
            params.append(entity_name)
        elif mode == "POOL":
            # Human pool when bot tables exist; otherwise safely behaves as all pool.
            clauses.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM information_schema.tables t
                    WHERE t.table_schema = 'main'
                      AND t.table_name = 'bot_group_members'
                )
                OR NOT EXISTS (
                    SELECT 1
                    FROM bot_group_members bgm
                    WHERE LOWER(TRIM(bgm.player_name)) =
                          LOWER(TRIM(hp.player_name))
                )
                """
            )
        else:
            raise ValueError(f"Desteklenmeyen analiz modu: {mode}")

        where_sql = "WHERE " + " AND ".join(f"({c})" for c in clauses) if clauses else ""

        win_values = sql_values(WIN_ACTIONS)
        showdown_values = sql_values(SHOWDOWN_ACTIONS)
        query = f"""
            WITH preflop_raises AS (
                SELECT
                    a.hand_id,
                    a.player_name,
                    a.sequence_no,
                    a.amount,
                    a.to_amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id
                        ORDER BY a.sequence_no
                    ) AS raise_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id
                        ORDER BY a.sequence_no DESC
                    ) AS reverse_raise_no
                FROM actions a
                WHERE UPPER(TRIM(a.street)) = 'PREFLOP'
                  AND UPPER(TRIM(a.action)) = 'RAISE'
            ),
            opens AS (
                SELECT
                    r.hand_id,
                    r.player_name AS opener,
                    r.sequence_no AS open_seq,
                    r.amount AS open_increment,
                    r.to_amount AS open_to,
                    h.site,
                    h.stakes,
                    h.flop,
                    h.turn,
                    h.river,
                    hp.position,
                    hp.starting_stack
                FROM preflop_raises r
                JOIN hands h ON h.hand_id = r.hand_id
                JOIN hand_players hp
                  ON hp.hand_id = r.hand_id
                 AND LOWER(TRIM(hp.player_name)) =
                     LOWER(TRIM(r.player_name))
                {where_sql}
                {"AND" if where_sql else "WHERE"} r.raise_no = 1
            ),
            last_preflop_raiser AS (
                SELECT hand_id, player_name
                FROM preflop_raises
                WHERE reverse_raise_no = 1
            ),
            three_bet AS (
                SELECT
                    o.hand_id,
                    MIN(r.sequence_no) AS three_bet_seq
                FROM opens o
                JOIN preflop_raises r
                  ON r.hand_id = o.hand_id
                 AND r.sequence_no > o.open_seq
                GROUP BY o.hand_id
            ),
            preflop_response AS (
                SELECT
                    o.hand_id,
                    MAX(CASE
                        WHEN t.three_bet_seq IS NOT NULL THEN 1 ELSE 0
                    END) AS faced_three_bet,
                    MAX(CASE
                        WHEN t.three_bet_seq IS NOT NULL
                         AND UPPER(TRIM(a.action)) = 'FOLD'
                        THEN 1 ELSE 0
                    END) AS folded_to_three_bet
                FROM opens o
                LEFT JOIN three_bet t ON t.hand_id = o.hand_id
                LEFT JOIN actions a
                  ON a.hand_id = o.hand_id
                 AND LOWER(TRIM(a.player_name)) =
                     LOWER(TRIM(o.opener))
                 AND a.sequence_no > t.three_bet_seq
                 AND UPPER(TRIM(a.street)) = 'PREFLOP'
                GROUP BY o.hand_id
            ),
            street_player AS (
                SELECT
                    a.hand_id,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    MIN(a.sequence_no) AS first_seq,
                    MAX(CASE
                        WHEN UPPER(TRIM(a.action)) IN ('BET', 'RAISE')
                        THEN 1 ELSE 0
                    END) AS aggressive
                FROM actions a
                WHERE UPPER(TRIM(a.street)) IN ('FLOP', 'TURN', 'RIVER')
                GROUP BY
                    a.hand_id,
                    UPPER(TRIM(a.street)),
                    a.player_name
            ),
            street_meta AS (
                SELECT
                    hand_id,
                    street,
                    COUNT(DISTINCT player_name) AS player_count
                FROM street_player
                GROUP BY hand_id, street
            ),
            opener_street AS (
                SELECT
                    o.hand_id,
                    sp.street,
                    sp.first_seq AS opener_first_seq,
                    sp.aggressive,
                    MIN(opp.first_seq) AS opponent_first_seq
                FROM opens o
                JOIN street_player sp
                  ON sp.hand_id = o.hand_id
                 AND LOWER(TRIM(sp.player_name)) =
                     LOWER(TRIM(o.opener))
                LEFT JOIN street_player opp
                  ON opp.hand_id = sp.hand_id
                 AND opp.street = sp.street
                 AND LOWER(TRIM(opp.player_name)) <>
                     LOWER(TRIM(o.opener))
                GROUP BY
                    o.hand_id, sp.street, sp.first_seq, sp.aggressive
            ),
            street_flags AS (
                SELECT
                    o.hand_id,
                    CASE
                        WHEN lpr.player_name = o.opener
                         AND COALESCE(sm_f.player_count, 0) = 2
                        THEN 1 ELSE 0
                    END AS flop_opp,
                    CASE
                        WHEN lpr.player_name = o.opener
                         AND COALESCE(sm_f.player_count, 0) = 2
                         AND os_f.aggressive = 1
                        THEN 1 ELSE 0
                    END AS flop_made,
                    CASE
                        WHEN os_f.opener_first_seq > os_f.opponent_first_seq
                        THEN 'IP'
                        WHEN os_f.opener_first_seq < os_f.opponent_first_seq
                        THEN 'OOP'
                        ELSE NULL
                    END AS flop_pos,

                    CASE
                        WHEN o.turn IS NOT NULL
                         AND TRIM(o.turn) <> ''
                         AND COALESCE(sm_t.player_count, 0) = 2
                         AND os_f.aggressive = 1
                        THEN 1 ELSE 0
                    END AS turn_opp,
                    CASE
                        WHEN o.turn IS NOT NULL
                         AND TRIM(o.turn) <> ''
                         AND COALESCE(sm_t.player_count, 0) = 2
                         AND os_f.aggressive = 1
                         AND os_t.aggressive = 1
                        THEN 1 ELSE 0
                    END AS turn_made,
                    CASE
                        WHEN os_t.opener_first_seq > os_t.opponent_first_seq
                        THEN 'IP'
                        WHEN os_t.opener_first_seq < os_t.opponent_first_seq
                        THEN 'OOP'
                        ELSE NULL
                    END AS turn_pos,

                    CASE
                        WHEN o.river IS NOT NULL
                         AND TRIM(o.river) <> ''
                         AND COALESCE(sm_r.player_count, 0) = 2
                         AND os_t.aggressive = 1
                        THEN 1 ELSE 0
                    END AS river_opp,
                    CASE
                        WHEN o.river IS NOT NULL
                         AND TRIM(o.river) <> ''
                         AND COALESCE(sm_r.player_count, 0) = 2
                         AND os_t.aggressive = 1
                         AND os_r.aggressive = 1
                        THEN 1 ELSE 0
                    END AS river_made,
                    CASE
                        WHEN os_r.opener_first_seq > os_r.opponent_first_seq
                        THEN 'IP'
                        WHEN os_r.opener_first_seq < os_r.opponent_first_seq
                        THEN 'OOP'
                        ELSE NULL
                    END AS river_pos
                FROM opens o
                LEFT JOIN last_preflop_raiser lpr ON lpr.hand_id = o.hand_id
                LEFT JOIN street_meta sm_f
                  ON sm_f.hand_id = o.hand_id AND sm_f.street = 'FLOP'
                LEFT JOIN street_meta sm_t
                  ON sm_t.hand_id = o.hand_id AND sm_t.street = 'TURN'
                LEFT JOIN street_meta sm_r
                  ON sm_r.hand_id = o.hand_id AND sm_r.street = 'RIVER'
                LEFT JOIN opener_street os_f
                  ON os_f.hand_id = o.hand_id AND os_f.street = 'FLOP'
                LEFT JOIN opener_street os_t
                  ON os_t.hand_id = o.hand_id AND os_t.street = 'TURN'
                LEFT JOIN opener_street os_r
                  ON os_r.hand_id = o.hand_id AND os_r.street = 'RIVER'
            )
            SELECT
                o.hand_id,
                o.opener,
                o.site,
                o.stakes,
                o.position,
                o.starting_stack,
                o.open_increment,
                o.open_to,
                o.flop,
                o.turn,
                o.river,
                COALESCE(pr.faced_three_bet, 0),
                COALESCE(pr.folded_to_three_bet, 0),
                COALESCE(sf.flop_opp, 0),
                COALESCE(sf.flop_made, 0),
                sf.flop_pos,
                COALESCE(sf.turn_opp, 0),
                COALESCE(sf.turn_made, 0),
                sf.turn_pos,
                COALESCE(sf.river_opp, 0),
                COALESCE(sf.river_made, 0),
                sf.river_pos,
                EXISTS (
                    SELECT 1
                    FROM actions c
                    WHERE c.hand_id = o.hand_id
                      AND LOWER(TRIM(c.player_name)) =
                          LOWER(TRIM(o.opener))
                      AND UPPER(TRIM(c.action)) IN ({win_values})
                ) AS won_pot,
                EXISTS (
                    SELECT 1
                    FROM actions s
                    WHERE s.hand_id = o.hand_id
                      AND LOWER(TRIM(s.player_name)) =
                          LOWER(TRIM(o.opener))
                      AND UPPER(TRIM(s.action)) IN ({showdown_values})
                ) AS went_showdown
            FROM opens o
            LEFT JOIN preflop_response pr ON pr.hand_id = o.hand_id
            LEFT JOIN street_flags sf ON sf.hand_id = o.hand_id
        """

        with self.connect() as con:
            rows = con.execute(query, params).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            bb = self._parse_big_blind(row[3])
            to_amount = self._float_or_none(row[7])
            stack = self._float_or_none(row[5])

            size_bb = (
                to_amount / bb
                if to_amount is not None and bb is not None and bb > 0
                else None
            )
            stack_bb = (
                stack / bb
                if stack is not None and bb is not None and bb > 0
                else None
            )

            saw_flop = bool(row[8])
            won = bool(row[22])
            showdown = bool(row[23])

            result.append(
                {
                    "position": str(row[4] or "OTHER"),
                    "size_bb": size_bb,
                    "size_bucket": self._size_bucket(size_bb),
                    "stack_bb": stack_bb,
                    "faced_three_bet": bool(row[11]),
                    "folded_to_three_bet": bool(row[12]),
                    "flop_opp": bool(row[13]),
                    "flop_made": bool(row[14]),
                    "flop_pos": str(row[15] or ""),
                    "turn_opp": bool(row[16]),
                    "turn_made": bool(row[17]),
                    "turn_pos": str(row[18] or ""),
                    "river_opp": bool(row[19]),
                    "river_made": bool(row[20]),
                    "river_pos": str(row[21] or ""),
                    "saw_flop": saw_flop,
                    "won_pot": won,
                    "wwsf_opp": saw_flop,
                    "wwsf_win": saw_flop and won,
                    "wsd_opp": showdown,
                    "wsd_win": showdown and won,
                }
            )

        return result

    def _aggregate(
        self,
        rows: list[dict[str, Any]],
        minimum_sample: int,
    ) -> dict[str, Any]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[(row["position"], row["size_bucket"])].append(row)

        table_rows: list[dict[str, Any]] = []
        for (position, bucket), items in groups.items():
            count = len(items)
            if count < minimum_sample:
                continue

            sizes = [x["size_bb"] for x in items if x["size_bb"] is not None]
            stacks = [x["stack_bb"] for x in items if x["stack_bb"] is not None]

            row = {
                "position": position,
                "size_bucket": bucket,
                "opens": count,
                "share": self._pct(count, len(rows)),
                "avg_size_bb": self._mean(sizes),
                "avg_stack_bb": self._mean(stacks),
                "three_bet_faced": self._rate(items, "faced_three_bet", None),
                "fold_to_three_bet": self._rate(
                    items, "folded_to_three_bet", "faced_three_bet"
                ),
                "fold_to_three_bet_sample": self._count(items, "faced_three_bet"),
                "flop_cbet_ip": self._street_rate(items, "flop", "IP"),
                "flop_cbet_ip_sample": self._street_sample(items, "flop", "IP"),
                "flop_cbet_oop": self._street_rate(items, "flop", "OOP"),
                "flop_cbet_oop_sample": self._street_sample(items, "flop", "OOP"),
                "turn_barrel_ip": self._street_rate(items, "turn", "IP"),
                "turn_barrel_ip_sample": self._street_sample(items, "turn", "IP"),
                "turn_barrel_oop": self._street_rate(items, "turn", "OOP"),
                "turn_barrel_oop_sample": self._street_sample(items, "turn", "OOP"),
                "river_barrel_ip": self._street_rate(items, "river", "IP"),
                "river_barrel_ip_sample": self._street_sample(items, "river", "IP"),
                "river_barrel_oop": self._street_rate(items, "river", "OOP"),
                "river_barrel_oop_sample": self._street_sample(items, "river", "OOP"),
                "wwsf": self._rate(items, "wwsf_win", "wwsf_opp"),
                "wwsf_sample": self._count(items, "wwsf_opp"),
                "wsd": self._rate(items, "wsd_win", "wsd_opp"),
                "wsd_sample": self._count(items, "wsd_opp"),
            }
            row["pattern_note"] = self._pattern_note(row)
            table_rows.append(row)

        table_rows.sort(key=self._sort_key)

        all_sizes = [x["size_bb"] for x in rows if x["size_bb"] is not None]
        summary = {
            "opens": len(rows),
            "avg_size_bb": self._mean(all_sizes) or 0.0,
            "fold_to_three_bet": self._rate(
                rows, "folded_to_three_bet", "faced_three_bet"
            ),
            "fold_to_three_bet_sample": self._count(rows, "faced_three_bet"),
            "flop_cbet_ip": self._street_rate(rows, "flop", "IP"),
            "flop_cbet_ip_sample": self._street_sample(rows, "flop", "IP"),
            "flop_cbet_oop": self._street_rate(rows, "flop", "OOP"),
            "flop_cbet_oop_sample": self._street_sample(rows, "flop", "OOP"),
            "turn_barrel_ip": self._street_rate(rows, "turn", "IP"),
            "turn_barrel_ip_sample": self._street_sample(rows, "turn", "IP"),
            "turn_barrel_oop": self._street_rate(rows, "turn", "OOP"),
            "turn_barrel_oop_sample": self._street_sample(rows, "turn", "OOP"),
            "river_barrel_ip": self._street_rate(rows, "river", "IP"),
            "river_barrel_ip_sample": self._street_sample(rows, "river", "IP"),
            "river_barrel_oop": self._street_rate(rows, "river", "OOP"),
            "river_barrel_oop_sample": self._street_sample(rows, "river", "OOP"),
            "wwsf": self._rate(rows, "wwsf_win", "wwsf_opp"),
            "wwsf_sample": self._count(rows, "wwsf_opp"),
            "wsd": self._rate(rows, "wsd_win", "wsd_opp"),
            "wsd_sample": self._count(rows, "wsd_opp"),
            "rows": table_rows,
        }
        return summary

    def _attach_pool_baseline(
        self,
        entity: dict[str, Any],
        pool: dict[str, Any],
    ) -> None:
        pool_rows = {
            (str(r.get("position")), str(r.get("size_bucket"))): r
            for r in pool.get("rows", [])
        }

        for row in entity.get("rows", []):
            baseline = pool_rows.get(
                (str(row.get("position")), str(row.get("size_bucket")))
            )
            if baseline is None:
                baseline = self._position_pool_fallback(
                    pool.get("rows", []), str(row.get("position"))
                )

            for metric, _sample in self.METRIC_SPECS:
                pool_key = f"pool_{metric}"
                delta_key = f"delta_{metric}"
                pool_value = float(
                    (baseline or pool).get(metric, 0.0) or 0.0
                )
                row[pool_key] = pool_value
                row[delta_key] = float(row.get(metric, 0.0) or 0.0) - pool_value

        # Summary-level pool fields are useful to the comparison banner.
        for metric, _sample in self.METRIC_SPECS:
            entity[f"pool_{metric}"] = float(pool.get(metric, 0.0) or 0.0)
            entity[f"delta_{metric}"] = (
                float(entity.get(metric, 0.0) or 0.0)
                - float(pool.get(metric, 0.0) or 0.0)
            )

    def _finalize_rows(self, entity: dict[str, Any]) -> None:
        for row in entity.get("rows", []):
            row["strength_score"] = self._strength_score(row)
            row["exploitability"] = self._exploitability(row)
            row["strategy_tags"] = self._strategy_tags(row)
            row["confidence"] = self._confidence(row)
            row["heatmap"] = self._heatmap(row)
            row["transition_summary"] = self._transition_summary(row)
            row["exploit_note"] = self._exploit_note(row)

    def _strength_score(self, row: dict[str, Any]) -> float:
        # Descriptive strategic intensity, not a win-rate estimate.
        weighted = (
            float(row.get("flop_cbet_ip", 0.0)) * 0.12
            + float(row.get("flop_cbet_oop", 0.0)) * 0.10
            + float(row.get("turn_barrel_ip", 0.0)) * 0.12
            + float(row.get("turn_barrel_oop", 0.0)) * 0.10
            + float(row.get("river_barrel_ip", 0.0)) * 0.10
            + float(row.get("river_barrel_oop", 0.0)) * 0.08
            + float(row.get("wwsf", 0.0)) * 0.18
            + float(row.get("wsd", 0.0)) * 0.10
        )
        return self._clamp(weighted)

    def _exploitability(self, row: dict[str, Any]) -> float:
        weights = {
            "delta_fold_to_three_bet": 0.24,
            "delta_flop_cbet_ip": 0.12,
            "delta_flop_cbet_oop": 0.12,
            "delta_turn_barrel_ip": 0.12,
            "delta_turn_barrel_oop": 0.10,
            "delta_river_barrel_ip": 0.09,
            "delta_river_barrel_oop": 0.07,
            "delta_wwsf": 0.08,
            "delta_wsd": 0.06,
        }
        raw = sum(
            abs(float(row.get(key, 0.0) or 0.0)) * weight
            for key, weight in weights.items()
        )
        confidence_weight = self._confidence_weight(row)
        return self._clamp(raw * 4.0 * confidence_weight)

    def _strategy_tags(self, row: dict[str, Any]) -> str:
        tags: list[str] = []
        size = float(row.get("avg_size_bb") or 0.0)
        if size <= 2.3:
            tags.append("Small Open")
        elif size >= 3.2:
            tags.append("Large Open")

        f_ip = float(row.get("flop_cbet_ip") or 0.0)
        f_oop = float(row.get("flop_cbet_oop") or 0.0)
        t_ip = float(row.get("turn_barrel_ip") or 0.0)
        t_oop = float(row.get("turn_barrel_oop") or 0.0)
        r_ip = float(row.get("river_barrel_ip") or 0.0)
        r_oop = float(row.get("river_barrel_oop") or 0.0)
        fold3b = float(row.get("fold_to_three_bet") or 0.0)

        if max(f_ip, f_oop) >= 70:
            tags.append("High Flop CBet")
        if max(t_ip, t_oop) >= 60:
            tags.append("High Barrel")
        if max(r_ip, r_oop) >= 55:
            tags.append("River Pressure")
        if fold3b >= 65:
            tags.append("3Bet Overfold")
        elif row.get("fold_to_three_bet_sample", 0) >= 20 and fold3b <= 35:
            tags.append("3Bet Sticky")
        if float(row.get("wwsf") or 0.0) >= 52:
            tags.append("High WWSF")
        if float(row.get("wsd") or 0.0) >= 57:
            tags.append("Strong Showdown")

        return ", ".join(tags[:5]) or "Neutral"

    def _confidence(self, row: dict[str, Any]) -> str:
        weight = self._confidence_weight(row)
        if weight >= 0.9:
            return "Yüksek"
        if weight >= 0.65:
            return "Orta"
        if weight >= 0.4:
            return "Düşük"
        return "Çok Düşük"

    def _confidence_weight(self, row: dict[str, Any]) -> float:
        samples = [
            int(row.get("fold_to_three_bet_sample") or 0),
            int(row.get("flop_cbet_ip_sample") or 0),
            int(row.get("flop_cbet_oop_sample") or 0),
            int(row.get("turn_barrel_ip_sample") or 0),
            int(row.get("turn_barrel_oop_sample") or 0),
            int(row.get("river_barrel_ip_sample") or 0),
            int(row.get("river_barrel_oop_sample") or 0),
            int(row.get("wwsf_sample") or 0),
            int(row.get("wsd_sample") or 0),
        ]
        positive = sorted(x for x in samples if x > 0)
        if not positive:
            return 0.2
        # Lower quartile is more robust than the absolute minimum.
        effective = positive[max(0, len(positive) // 4 - 1)]
        if effective >= 300:
            return 1.0
        if effective >= 150:
            return 0.85
        if effective >= 75:
            return 0.7
        if effective >= 35:
            return 0.55
        if effective >= 15:
            return 0.4
        return 0.25

    def _heatmap(self, row: dict[str, Any]) -> str:
        score = float(row.get("exploitability") or 0.0)
        if score >= 70:
            return "█████"
        if score >= 50:
            return "████░"
        if score >= 30:
            return "███░░"
        if score >= 15:
            return "██░░░"
        return "█░░░░"

    def _transition_summary(self, row: dict[str, Any]) -> str:
        return (
            f"F IP/OOP {float(row.get('flop_cbet_ip') or 0):.0f}/"
            f"{float(row.get('flop_cbet_oop') or 0):.0f} → "
            f"T {float(row.get('turn_barrel_ip') or 0):.0f}/"
            f"{float(row.get('turn_barrel_oop') or 0):.0f} → "
            f"R {float(row.get('river_barrel_ip') or 0):.0f}/"
            f"{float(row.get('river_barrel_oop') or 0):.0f}"
        )

    def _exploit_note(self, row: dict[str, Any]) -> str:
        candidates = [
            (
                abs(float(row.get("delta_fold_to_three_bet") or 0.0)),
                "3bet'e karşı daha sık baskı uygula"
                if float(row.get("delta_fold_to_three_bet") or 0.0) > 0
                else "3bet range'ini value ağırlıklı tut",
            ),
            (
                abs(float(row.get("delta_flop_cbet_ip") or 0.0)),
                "IP flop cbet sapmasına karşı check-raise/call frekansını ayarla",
            ),
            (
                abs(float(row.get("delta_flop_cbet_oop") or 0.0)),
                "OOP flop cbet sapmasına karşı float planını ayarla",
            ),
            (
                abs(float(row.get("delta_turn_barrel_ip") or 0.0)),
                "Turn IP barrel sapmasını bluff-catch planında kullan",
            ),
            (
                abs(float(row.get("delta_river_barrel_ip") or 0.0)),
                "River IP pressure sapmasını bluff-catch eşiklerine yansıt",
            ),
        ]
        magnitude, note = max(candidates, key=lambda x: x[0])
        if magnitude < 5:
            return "Pool'a yakın; belirgin open-size exploiti yok"
        return note

    def _position_summary(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("position") or "OTHER")].append(row)

        output: list[dict[str, Any]] = []
        for position, items in grouped.items():
            total = sum(int(x.get("opens") or 0) for x in items)
            if total <= 0:
                continue
            top = max(items, key=lambda x: int(x.get("opens") or 0))
            avg = sum(
                float(x.get("avg_size_bb") or 0.0) * int(x.get("opens") or 0)
                for x in items
            ) / total
            output.append(
                {
                    "position": position,
                    "most_common": str(top.get("size_bucket") or "—"),
                    "avg_size_bb": avg,
                }
            )
        rank = {p: i for i, p in enumerate(self.POSITION_ORDER)}
        output.sort(key=lambda x: rank.get(x["position"], 99))
        return output

    def _position_pool_fallback(
        self,
        rows: list[dict[str, Any]],
        position: str,
    ) -> dict[str, Any] | None:
        candidates = [r for r in rows if str(r.get("position")) == position]
        if not candidates:
            return None

        total = sum(int(r.get("opens") or 0) for r in candidates)
        if total <= 0:
            return None

        merged: dict[str, Any] = {"position": position, "opens": total}
        for metric, sample_key in self.METRIC_SPECS:
            sample_total = sum(int(r.get(sample_key) or 0) for r in candidates)
            if sample_total > 0:
                merged[metric] = sum(
                    float(r.get(metric) or 0.0) * int(r.get(sample_key) or 0)
                    for r in candidates
                ) / sample_total
            else:
                merged[metric] = 0.0
        return merged

    def _street_rate(
        self,
        items: list[dict[str, Any]],
        street: str,
        pos: str,
    ) -> float:
        opp_key = f"{street}_opp"
        made_key = f"{street}_made"
        pos_key = f"{street}_pos"
        eligible = [
            x for x in items
            if bool(x.get(opp_key)) and str(x.get(pos_key) or "") == pos
        ]
        return self._pct(
            sum(1 for x in eligible if bool(x.get(made_key))),
            len(eligible),
        )

    def _street_sample(
        self,
        items: list[dict[str, Any]],
        street: str,
        pos: str,
    ) -> int:
        return sum(
            1 for x in items
            if bool(x.get(f"{street}_opp"))
            and str(x.get(f"{street}_pos") or "") == pos
        )

    def _rate(
        self,
        items: list[dict[str, Any]],
        numerator_key: str,
        denominator_key: str | None,
    ) -> float:
        if denominator_key is None:
            return self._pct(
                sum(1 for x in items if bool(x.get(numerator_key))),
                len(items),
            )
        eligible = [x for x in items if bool(x.get(denominator_key))]
        return self._pct(
            sum(1 for x in eligible if bool(x.get(numerator_key))),
            len(eligible),
        )

    def _count(self, items: list[dict[str, Any]], key: str) -> int:
        return sum(1 for x in items if bool(x.get(key)))

    def _pattern_note(self, row: dict[str, Any]) -> str:
        notes: list[str] = []
        position = str(row.get("position") or "")
        bucket = str(row.get("size_bucket") or "")
        avg_stack = row.get("avg_stack_bb")
        three_bet = float(row.get("three_bet_faced") or 0.0)

        if position in {"CO", "BTN", "SB"} and bucket in {"≤2.0x", "2.1–2.3x"}:
            notes.append("Geç pozisyon küçük sizing")
        if position in {"UTG", "UTG+1", "HJ"} and bucket in {"2.7–3.1x", ">3.1x"}:
            notes.append("Erken pozisyon büyük sizing")
        if avg_stack is not None and float(avg_stack) < 40:
            notes.append("Kısa stack")
        elif avg_stack is not None and float(avg_stack) > 150:
            notes.append("Deep stack")
        if three_bet >= 18:
            notes.append("Yüksek 3bet maruziyeti")
        return "; ".join(notes) or "Belirgin tek neden yok"

    def _parse_big_blind(self, stakes: str | None) -> float | None:
        if not stakes:
            return None
        numbers = re.findall(r"\d+(?:[.,]\d+)?", str(stakes))
        if len(numbers) < 2:
            return None
        try:
            return float(numbers[1].replace(",", "."))
        except ValueError:
            return None

    def _size_bucket(self, size_bb: float | None) -> str:
        if size_bb is None:
            return "UNKNOWN"
        if size_bb <= 2.05:
            return "≤2.0x"
        if size_bb <= 2.35:
            return "2.1–2.3x"
        if size_bb <= 2.65:
            return "2.4–2.6x"
        if size_bb <= 3.15:
            return "2.7–3.1x"
        return ">3.1x"

    def _sort_key(self, row: dict[str, Any]) -> tuple[int, int]:
        pos_rank = {p: i for i, p in enumerate(self.POSITION_ORDER)}
        bucket_rank = {
            "≤2.0x": 0,
            "2.1–2.3x": 1,
            "2.4–2.6x": 2,
            "2.7–3.1x": 3,
            ">3.1x": 4,
            "UNKNOWN": 5,
        }
        return (
            pos_rank.get(str(row.get("position")), 99),
            bucket_rank.get(str(row.get("size_bucket")), 99),
        )

    def _mean(self, values: list[float | None]) -> float | None:
        clean = [
            float(x) for x in values
            if x is not None and math.isfinite(float(x))
        ]
        return sum(clean) / len(clean) if clean else None

    def _pct(self, numerator: int, denominator: int) -> float:
        return numerator / denominator * 100.0 if denominator else 0.0

    def _clamp(self, value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    def _float_or_none(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None
