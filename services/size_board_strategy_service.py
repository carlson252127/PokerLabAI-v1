from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import math
import re

import duckdb


class SizeBoardStrategyService:
    POSITION_ORDER = {
        "UTG": 0,
        "UTG+1": 1,
        "HJ": 2,
        "CO": 3,
        "BTN": 4,
        "SB": 5,
        "BB": 6,
        "OTHER": 99,
    }

    BUCKET_ORDER = {
        "≤2.0x": 0,
        "2.1–2.3x": 1,
        "2.4–2.6x": 2,
        "2.7–3.1x": 3,
        ">3.1x": 4,
        "UNKNOWN": 99,
    }

    RANK_VALUE = {
        "2": 2, "3": 3, "4": 4, "5": 5,
        "6": 6, "7": 7, "8": 8, "9": 9,
        "T": 10, "J": 11, "Q": 12,
        "K": 13, "A": 14,
    }

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

    def available_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 100,
        limit: int = 5000,
    ) -> list[tuple[str, str, int]]:
        """UI kaynak listesini (key, label, hands) biçiminde döndürür."""
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
        minimum_hands = max(1, int(minimum_hands))
        limit = max(1, int(limit))

        with self.connect() as con:
            if mode == "PLAYER":
                rows = con.execute(
                    f"""
                    SELECT hp.player_name, COUNT(DISTINCT hp.hand_id) AS hands
                    FROM hand_players hp
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY hp.player_name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC
                    LIMIT {limit}
                    """,
                    params + [minimum_hands],
                ).fetchall()
                return [(str(name), str(name), int(hands or 0)) for name, hands in rows]

            if mode == "ALIAS":
                table_exists = bool(con.execute(
                    """SELECT COUNT(*) FROM information_schema.tables
                       WHERE table_schema='main' AND table_name='player_aliases'"""
                ).fetchone()[0])
                if not table_exists:
                    return []
                rows = con.execute(
                    f"""
                    SELECT pa.alias_name, COUNT(DISTINCT hp.hand_id) AS hands
                    FROM player_aliases pa
                    JOIN hand_players hp ON hp.player_name = pa.player_name
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY pa.alias_name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC
                    LIMIT {limit}
                    """,
                    params + [minimum_hands],
                ).fetchall()
                return [(str(name), str(name), int(hands or 0)) for name, hands in rows]

            if mode in {"BOT_GROUP", "BOT_FAMILY"}:
                tables = {row[0] for row in con.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
                ).fetchall()}
                if not {"bot_groups", "bot_group_members"}.issubset(tables):
                    return []
                extra = ""
                extra_params: list[Any] = []
                if site:
                    extra += " AND h.site = ?"
                    extra_params.append(site)
                if stakes:
                    extra += " AND h.stakes = ?"
                    extra_params.append(stakes)
                rows = con.execute(
                    f"""
                    SELECT bg.name, COUNT(DISTINCT hp.hand_id) AS hands
                    FROM bot_groups bg
                    JOIN bot_group_members bgm ON bgm.group_id = bg.group_id
                    JOIN hand_players hp
                      ON LOWER(TRIM(hp.player_name)) = LOWER(TRIM(bgm.player_name))
                    JOIN hands h ON h.hand_id = hp.hand_id
                    WHERE 1=1 {extra}
                    GROUP BY bg.name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC, LOWER(bg.name)
                    LIMIT {limit}
                    """,
                    extra_params + [minimum_hands],
                ).fetchall()
                return [(str(name), str(name), int(hands or 0)) for name, hands in rows]

            if mode in {"POOL", "ALL_POOL"}:
                extra = []
                extra_params: list[Any] = []
                if site:
                    extra.append("h.site = ?")
                    extra_params.append(site)
                if stakes:
                    extra.append("h.stakes = ?")
                    extra_params.append(stakes)
                where = "WHERE " + " AND ".join(extra) if extra else ""
                hands = int(con.execute(
                    f"SELECT COUNT(DISTINCT h.hand_id) FROM hands h {where}",
                    extra_params,
                ).fetchone()[0] or 0)
                label = "Human Pool (Botlar Hariç)" if mode == "POOL" else "All Pool"
                return [("__POOL__", label, hands)] if hands >= minimum_hands else []

        return []

    def analyze(
        self,
        mode: str,
        entity_name: str,
        site: str = "",
        stakes: str = "",
        position: str = "",
        texture_filter: str = "",
        minimum_sample: int = 30,
        view_mode: str = "STUDY",
        street_mode: str = "FLOP",
        turn_filter: str = "",
    ) -> dict[str, Any]:
        rows = self._load_rows(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position=position,
        )

        enriched: list[dict[str, Any]] = []
        normalized_view = str(view_mode or "STUDY").upper()
        normalized_street = str(street_mode or "FLOP").upper()

        for row in rows:
            flop = str(row.get("flop") or "")
            turn = str(row.get("turn") or "")
            detailed_texture = self._texture_family(flop)
            simple_texture = self._simple_flop_family(flop)
            turn_transition = self._turn_transition(flop, turn)

            texture = detailed_texture if normalized_view == "DETAIL" else simple_texture
            if normalized_street == "TURN":
                texture = f"{texture} › {turn_transition}"

            if texture_filter and texture != texture_filter:
                continue
            if turn_filter and turn_transition != turn_filter:
                continue

            row["texture"] = texture
            row["detailed_texture"] = detailed_texture
            row["simple_texture"] = simple_texture
            row["turn_transition"] = turn_transition
            row["study_size_bucket"] = self._study_size_bucket(row.get("size_bb"))
            if normalized_view != "DETAIL":
                row["size_bucket"] = row["study_size_bucket"]
            enriched.append(row)

        grouped = self._aggregate(
            enriched,
            minimum_sample,
        )

        return {
            "rows": grouped,
            "summary": self._summary(grouped),
            "evidence": self._evidence_summary(grouped),
            "strongest_difference": self._strongest_difference(grouped),
            "actionable_groups": sum(
                1 for item in grouped
                if item.get("confidence") in {"Orta", "Yüksek"}
            ),
            "view_mode": normalized_view,
            "street_mode": normalized_street,
        }

    def _load_rows(
        self,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        position: str,
    ) -> list[dict[str, Any]]:
        mode = mode.upper()
        filters: list[str] = []
        params: list[Any] = []

        if site:
            filters.append("h.site = ?")
            params.append(site)

        if stakes:
            filters.append("h.stakes = ?")
            params.append(stakes)

        if position:
            filters.append("hp.position = ?")
            params.append(position)

        if mode == "PLAYER":
            filters.append("LOWER(TRIM(hp.player_name)) = LOWER(TRIM(?))")
            params.append(entity_name)
        elif mode == "ALIAS":
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM player_aliases pa
                    WHERE LOWER(TRIM(pa.player_name)) = LOWER(TRIM(hp.player_name))
                      AND pa.alias_name = ?
                )
                """
            )
            params.append(entity_name)
        elif mode in {"BOT_GROUP", "BOT_FAMILY"}:
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM bot_group_members bgm
                    JOIN bot_groups bg ON bg.group_id = bgm.group_id
                    WHERE LOWER(TRIM(bgm.player_name)) = LOWER(TRIM(hp.player_name))
                      AND bg.name = ?
                )
                """
            )
            params.append(entity_name)
        elif mode == "POOL":
            filters.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM bot_group_members bgm
                    WHERE LOWER(TRIM(bgm.player_name)) = LOWER(TRIM(hp.player_name))
                )
                """
            )
        elif mode == "ALL_POOL":
            pass
        else:
            raise ValueError(f"Desteklenmeyen analiz modu: {mode}")

        where_sql = "WHERE " + " AND ".join(filters)

        query = f"""
            WITH preflop_raises AS (
                SELECT
                    a.hand_id,
                    a.player_name,
                    a.sequence_no,
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
                    r.to_amount,
                    h.site,
                    h.stakes,
                    h.flop,
                    h.turn,
                    h.river,
                    hp.position
                FROM preflop_raises r
                JOIN hands h
                  ON h.hand_id = r.hand_id
                JOIN hand_players hp
                  ON hp.hand_id = r.hand_id
                 AND hp.player_name = r.player_name
                {where_sql}
                  AND r.raise_no = 1
                  AND h.flop IS NOT NULL
                  AND TRIM(h.flop) <> ''
            ),

            last_preflop_raiser AS (
                SELECT
                    hand_id,
                    player_name
                FROM preflop_raises
                WHERE reverse_raise_no = 1
            ),

            street_player AS (
                SELECT
                    a.hand_id,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    MIN(a.sequence_no) AS first_seq,
                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.action))
                                 IN ('BET', 'RAISE')
                            THEN 1 ELSE 0
                        END
                    ) AS aggressive,
                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.action)) = 'FOLD'
                            THEN 1 ELSE 0
                        END
                    ) AS folded
                FROM actions a
                WHERE UPPER(TRIM(a.street))
                      IN ('FLOP', 'TURN', 'RIVER')
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

            action_flow AS (
                SELECT
                    a.hand_id,
                    a.sequence_no,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    UPPER(TRIM(a.action)) AS action,
                    a.amount,
                    a.to_amount,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN UPPER(TRIM(a.action)) IN (
                                    'POST_ANTE', 'POST_SB', 'POST_BB',
                                    'CALL', 'BET', 'RAISE'
                                )
                                THEN COALESCE(a.amount, 0)
                                WHEN UPPER(TRIM(a.action)) = 'RETURN'
                                THEN -COALESCE(a.amount, 0)
                                ELSE 0
                            END
                        ) OVER (
                            PARTITION BY a.hand_id
                            ORDER BY a.sequence_no
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                        ),
                        0
                    ) AS pot_before
                FROM actions a
            ),

            opener_street_bets AS (
                SELECT
                    o.hand_id,
                    af.street,
                    af.amount AS bet_amount,
                    af.pot_before,
                    ROW_NUMBER() OVER (
                        PARTITION BY o.hand_id, af.street
                        ORDER BY af.sequence_no
                    ) AS bet_no
                FROM opens o
                JOIN action_flow af
                  ON af.hand_id = o.hand_id
                 AND af.player_name = o.opener
                WHERE af.street IN ('FLOP', 'TURN', 'RIVER')
                  AND af.action = 'BET'
                  AND af.amount IS NOT NULL
                  AND af.amount > 0
                  AND af.pot_before > 0
            ),

            street_bet_metrics AS (
                SELECT
                    hand_id,
                    MAX(CASE
                        WHEN street = 'FLOP' AND bet_no = 1
                        THEN bet_amount
                    END) AS flop_bet_amount,
                    MAX(CASE
                        WHEN street = 'FLOP' AND bet_no = 1
                        THEN pot_before
                    END) AS flop_pot_before,
                    MAX(CASE
                        WHEN street = 'TURN' AND bet_no = 1
                        THEN bet_amount
                    END) AS turn_bet_amount,
                    MAX(CASE
                        WHEN street = 'TURN' AND bet_no = 1
                        THEN pot_before
                    END) AS turn_pot_before,
                    MAX(CASE
                        WHEN street = 'RIVER' AND bet_no = 1
                        THEN bet_amount
                    END) AS river_bet_amount,
                    MAX(CASE
                        WHEN street = 'RIVER' AND bet_no = 1
                        THEN pot_before
                    END) AS river_pot_before
                FROM opener_street_bets
                GROUP BY hand_id
            ),

            flags AS (
                SELECT
                    o.*,
                    sbm.flop_bet_amount,
                    sbm.flop_pot_before,
                    sbm.turn_bet_amount,
                    sbm.turn_pot_before,
                    sbm.river_bet_amount,
                    sbm.river_pot_before,

                    CASE
                        WHEN lpr.player_name = o.opener
                         AND COALESCE(sm_f.player_count, 0) = 2
                        THEN 1 ELSE 0
                    END AS flop_cbet_opp,

                    CASE
                        WHEN lpr.player_name = o.opener
                         AND COALESCE(sm_f.player_count, 0) = 2
                         AND sp_f.aggressive = 1
                        THEN 1 ELSE 0
                    END AS flop_cbet_made,

                    CASE
                        WHEN o.turn IS NOT NULL
                         AND TRIM(o.turn) <> ''
                         AND COALESCE(sm_t.player_count, 0) = 2
                         AND sp_f.aggressive = 1
                        THEN 1 ELSE 0
                    END AS turn_barrel_opp,

                    CASE
                        WHEN o.turn IS NOT NULL
                         AND TRIM(o.turn) <> ''
                         AND COALESCE(sm_t.player_count, 0) = 2
                         AND sp_f.aggressive = 1
                         AND sp_t.aggressive = 1
                        THEN 1 ELSE 0
                    END AS turn_barrel_made,

                    CASE
                        WHEN o.river IS NOT NULL
                         AND TRIM(o.river) <> ''
                         AND COALESCE(sm_r.player_count, 0) = 2
                         AND sp_t.aggressive = 1
                        THEN 1 ELSE 0
                    END AS river_barrel_opp,

                    CASE
                        WHEN o.river IS NOT NULL
                         AND TRIM(o.river) <> ''
                         AND COALESCE(sm_r.player_count, 0) = 2
                         AND sp_t.aggressive = 1
                         AND sp_r.aggressive = 1
                        THEN 1 ELSE 0
                    END AS river_barrel_made,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions c
                            WHERE c.hand_id = o.hand_id
                              AND c.player_name = o.opener
                              AND UPPER(TRIM(c.action)) = 'COLLECT'
                        )
                        THEN 1 ELSE 0
                    END AS won_pot,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions sd
                            WHERE sd.hand_id = o.hand_id
                              AND sd.player_name = o.opener
                              AND UPPER(TRIM(sd.action))
                                  IN ('SHOW', 'MUCK')
                        )
                        THEN 1 ELSE 0
                    END AS went_showdown

                FROM opens o

                LEFT JOIN last_preflop_raiser lpr
                  ON lpr.hand_id = o.hand_id

                LEFT JOIN street_player sp_f
                  ON sp_f.hand_id = o.hand_id
                 AND sp_f.street = 'FLOP'
                 AND sp_f.player_name = o.opener

                LEFT JOIN street_player sp_t
                  ON sp_t.hand_id = o.hand_id
                 AND sp_t.street = 'TURN'
                 AND sp_t.player_name = o.opener

                LEFT JOIN street_player sp_r
                  ON sp_r.hand_id = o.hand_id
                 AND sp_r.street = 'RIVER'
                 AND sp_r.player_name = o.opener

                LEFT JOIN street_meta sm_f
                  ON sm_f.hand_id = o.hand_id
                 AND sm_f.street = 'FLOP'

                LEFT JOIN street_meta sm_t
                  ON sm_t.hand_id = o.hand_id
                 AND sm_t.street = 'TURN'

                LEFT JOIN street_meta sm_r
                  ON sm_r.hand_id = o.hand_id
                 AND sm_r.street = 'RIVER'

                LEFT JOIN street_bet_metrics sbm
                  ON sbm.hand_id = o.hand_id
            )

            SELECT
                hand_id,
                opener,
                to_amount,
                stakes,
                flop,
                turn,
                river,
                position,
                flop_cbet_opp,
                flop_cbet_made,
                turn_barrel_opp,
                turn_barrel_made,
                river_barrel_opp,
                river_barrel_made,
                won_pot,
                went_showdown,
                flop_bet_amount,
                flop_pot_before,
                turn_bet_amount,
                turn_pot_before,
                river_bet_amount,
                river_pot_before
            FROM flags
        """

        with self.connect() as con:
            raw_rows = con.execute(
                query,
                params,
            ).fetchall()

        result: list[dict[str, Any]] = []

        for raw in raw_rows:
            (
                hand_id,
                opener,
                to_amount,
                stakes_value,
                flop,
                turn,
                river,
                position_value,
                flop_opp,
                flop_made,
                turn_opp,
                turn_made,
                river_opp,
                river_made,
                won_pot,
                went_showdown,
                flop_bet_amount,
                flop_pot_before,
                turn_bet_amount,
                turn_pot_before,
                river_bet_amount,
                river_pot_before,
            ) = raw

            bb = self._parse_big_blind(
                str(stakes_value or "")
            )
            amount = self._float_or_none(
                to_amount
            )

            size_bb = (
                amount / bb
                if amount is not None
                and bb is not None
                and bb > 0
                else None
            )

            result.append(
                {
                    "hand_id": str(hand_id),
                    "opener": str(opener),
                    "position": str(
                        position_value or "OTHER"
                    ),
                    "flop": str(flop or ""),
                    "turn": turn,
                    "river": river,
                    "size_bb": size_bb,
                    "size_bucket": self._size_bucket(
                        size_bb
                    ),
                    "flop_cbet_opp": bool(flop_opp),
                    "flop_cbet_made": bool(flop_made),
                    "turn_barrel_opp": bool(turn_opp),
                    "turn_barrel_made": bool(turn_made),
                    "river_barrel_opp": bool(river_opp),
                    "river_barrel_made": bool(river_made),
                    "won_pot": bool(won_pot),
                    "went_showdown": bool(went_showdown),
                    "flop_bet_amount": self._float_or_none(flop_bet_amount),
                    "flop_pot_before": self._float_or_none(flop_pot_before),
                    "flop_bet_pct": self._bet_pct(
                        flop_bet_amount,
                        flop_pot_before,
                    ),
                    "turn_bet_amount": self._float_or_none(turn_bet_amount),
                    "turn_pot_before": self._float_or_none(turn_pot_before),
                    "turn_bet_pct": self._bet_pct(
                        turn_bet_amount,
                        turn_pot_before,
                    ),
                    "river_bet_amount": self._float_or_none(river_bet_amount),
                    "river_pot_before": self._float_or_none(river_pot_before),
                    "river_bet_pct": self._bet_pct(
                        river_bet_amount,
                        river_pot_before,
                    ),
                }
            )

        return result

    def _aggregate(
        self,
        rows: list[dict[str, Any]],
        minimum_sample: int,
    ) -> list[dict[str, Any]]:
        grouped: dict[
            tuple[str, str, str],
            list[dict[str, Any]],
        ] = defaultdict(list)

        for row in rows:
            grouped[
                (
                    row["position"],
                    row["texture"],
                    row["size_bucket"],
                )
            ].append(row)

        output: list[dict[str, Any]] = []

        for (
            position,
            texture,
            bucket,
        ), items in grouped.items():
            if len(items) < max(
                1,
                int(minimum_sample),
            ):
                continue

            flop_opp = sum(
                1
                for item in items
                if item["flop_cbet_opp"]
            )
            flop_made = sum(
                1
                for item in items
                if item["flop_cbet_opp"]
                and item["flop_cbet_made"]
            )

            turn_opp = sum(
                1
                for item in items
                if item["turn_barrel_opp"]
            )
            turn_made = sum(
                1
                for item in items
                if item["turn_barrel_opp"]
                and item["turn_barrel_made"]
            )

            river_opp = sum(
                1
                for item in items
                if item["river_barrel_opp"]
            )
            river_made = sum(
                1
                for item in items
                if item["river_barrel_opp"]
                and item["river_barrel_made"]
            )

            saw_flop = len(items)
            wins = sum(
                1
                for item in items
                if item["won_pot"]
            )
            showdown = sum(
                1
                for item in items
                if item["went_showdown"]
            )
            showdown_wins = sum(
                1
                for item in items
                if item["went_showdown"]
                and item["won_pot"]
            )

            sizes = [
                item["size_bb"]
                for item in items
                if item["size_bb"] is not None
            ]

            row = {
                "position": position,
                "texture": texture,
                "size_bucket": bucket,
                "hands": len(items),
                "avg_size_bb": (
                    sum(sizes) / len(sizes)
                    if sizes
                    else 0.0
                ),
                "flop_cbet": self._pct(
                    flop_made,
                    flop_opp,
                ),
                "flop_sample": flop_opp,
                "turn_barrel": self._pct(
                    turn_made,
                    turn_opp,
                ),
                "turn_sample": turn_opp,
                "river_barrel": self._pct(
                    river_made,
                    river_opp,
                ),
                "river_sample": river_opp,
                "wwsf": self._pct(
                    wins,
                    saw_flop,
                ),
                "wwsf_sample": saw_flop,
                "wtsd": self._pct(
                    showdown,
                    saw_flop,
                ),
                "wtsd_sample": saw_flop,
                "wsd": self._pct(
                    showdown_wins,
                    showdown,
                ),
                "wsd_sample": showdown,
                "flop_avg_bet_pct": self._average_metric(
                    items,
                    "flop_bet_pct",
                ),
                "turn_avg_bet_pct": self._average_metric(
                    items,
                    "turn_bet_pct",
                ),
                "river_avg_bet_pct": self._average_metric(
                    items,
                    "river_bet_pct",
                ),
                "flop_bet_size_sample": self._metric_sample(
                    items,
                    "flop_bet_pct",
                ),
                "turn_bet_size_sample": self._metric_sample(
                    items,
                    "turn_bet_pct",
                ),
                "river_bet_size_sample": self._metric_sample(
                    items,
                    "river_bet_pct",
                ),
                "representative_board": self._representative_board(items),
                "representative_board_hands": self._representative_board_count(items),
                "representative_boards": self._representative_boards(items),
                "flop_size_distribution": self._size_distribution(items, "flop_bet_pct"),
                "turn_size_distribution": self._size_distribution(items, "turn_bet_pct"),
                "river_size_distribution": self._size_distribution(items, "river_bet_pct"),
            }

            row["size_dna_data"] = self._size_dna_data(row, items)
            row["size_dna"] = self._format_size_dna(row["size_dna_data"])

            row["strategy_vector"] = (
                f"F {row['flop_cbet']:.0f}"
                f" → T {row['turn_barrel']:.0f}"
                f" → R {row['river_barrel']:.0f}"
                f" → WWSF {row['wwsf']:.0f}"
                f" → W$SD {row['wsd']:.0f}"
            )

            output.append(row)

        self._attach_texture_deltas(output)

        output.sort(
            key=lambda row: (
                self.POSITION_ORDER.get(
                    row["position"],
                    99,
                ),
                row["texture"],
                self.BUCKET_ORDER.get(
                    row["size_bucket"],
                    99,
                ),
            )
        )

        return output

    def _attach_texture_deltas(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        groups: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = defaultdict(list)

        for row in rows:
            groups[
                (
                    row["position"],
                    row["texture"],
                )
            ].append(row)

        for items in groups.values():
            if not items:
                continue

            baseline = min(
                items,
                key=lambda row: (
                    self.BUCKET_ORDER.get(
                        row["size_bucket"],
                        99,
                    ),
                    -row["hands"],
                ),
            )

            for row in items:
                row["delta_flop"] = (
                    row["flop_cbet"]
                    - baseline["flop_cbet"]
                )
                row["delta_turn"] = (
                    row["turn_barrel"]
                    - baseline["turn_barrel"]
                )
                row["delta_river"] = (
                    row["river_barrel"]
                    - baseline["river_barrel"]
                )
                row["delta_wwsf"] = (
                    row["wwsf"]
                    - baseline["wwsf"]
                )
                row["delta_wsd"] = (
                    row["wsd"]
                    - baseline["wsd"]
                )

                row["difference_score"] = self._difference_score(
                    row
                )
                row["confidence"] = self._confidence(
                    row
                )
                row["interpretation"] = self._interpretation(
                    row
                )

    def _difference_score(
        self,
        row: dict[str, Any],
    ) -> float:
        raw = (
            abs(float(row["delta_flop"])) * 0.28
            + abs(float(row["delta_turn"])) * 0.24
            + abs(float(row["delta_river"])) * 0.20
            + abs(float(row["delta_wwsf"])) * 0.16
            + abs(float(row["delta_wsd"])) * 0.12
        )

        weight = self._sample_weight(row)

        return max(
            0.0,
            min(
                100.0,
                raw * 3.5 * weight,
            ),
        )

    def _sample_weight(
        self,
        row: dict[str, Any],
    ) -> float:
        samples = [
            int(row["flop_sample"]),
            int(row["turn_sample"]),
            int(row["river_sample"]),
            int(row["wwsf_sample"]),
            int(row["wsd_sample"]),
        ]

        positive = [
            value
            for value in samples
            if value > 0
        ]

        if not positive:
            return 0.15

        effective = min(positive)

        if effective >= 500:
            return 1.0
        if effective >= 200:
            return 0.85
        if effective >= 100:
            return 0.70
        if effective >= 50:
            return 0.55
        if effective >= 20:
            return 0.35
        return 0.20

    def _confidence(
        self,
        row: dict[str, Any],
    ) -> str:
        weight = self._sample_weight(row)

        if weight >= 0.85:
            return "Yüksek"
        if weight >= 0.55:
            return "Orta"
        if weight >= 0.35:
            return "Düşük"
        return "Çok Düşük"

    def _interpretation(
        self,
        row: dict[str, Any],
    ) -> str:
        score = float(
            row.get("difference_score") or 0.0
        )

        if row["confidence"] in {
            "Çok Düşük",
            "Düşük",
        }:
            return "Sample yetersiz; RNG ayrımı yapılamaz"

        if score >= 35:
            return "Size, farklı postflop branch ile ilişkili"

        if score >= 18:
            return "Orta düzey strateji farkı"

        return "Postflop planı size'lar arasında benzer"

    def _strongest_difference(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not rows:
            return {}

        return max(
            rows,
            key=lambda row: (
                float(row["difference_score"]),
                int(row["hands"]),
            ),
        )

    def _evidence_summary(
        self,
        rows: list[dict[str, Any]],
    ) -> str:
        reliable = [
            row
            for row in rows
            if row["confidence"] in {
                "Orta",
                "Yüksek",
            }
        ]

        if not reliable:
            return (
                "Yeterli güvenilir texture-size grubu yok. "
                "RNG veya branch ayrımı için daha fazla sample gerekli."
            )

        strong = [
            row
            for row in reliable
            if float(row["difference_score"]) >= 35
        ]

        ratio = len(strong) / len(reliable)

        if ratio >= 0.45:
            verdict = (
                "Büyük sizing'ler sistematik olarak farklı "
                "postflop branch'lerle ilişkili görünüyor."
            )
        elif ratio >= 0.20:
            verdict = (
                "Bazı board ailelerinde size-strateji bağı var; "
                "tamamen random görünmüyor."
            )
        else:
            verdict = (
                "Güvenilir grupların çoğunda postflop planı benzer; "
                "size seçimi kısmen RNG olabilir."
            )

        return (
            f"{verdict} Güvenilir grup: {len(reliable)}, "
            f"güçlü fark bulunan: {len(strong)}."
        )

    def _summary(
        self,
        rows: list[dict[str, Any]],
    ) -> str:
        if not rows:
            return "Filtrelere uygun yeterli sample bulunamadı."

        strongest = self._strongest_difference(
            rows
        )

        return (
            f"En güçlü ayrışma: {strongest['position']} "
            f"{strongest['texture']} "
            f"{strongest['size_bucket']} — "
            f"Difference Score "
            f"{strongest['difference_score']:.0f}/100, "
            f"Güven {strongest['confidence']}."
        )

    def _texture_family(
        self,
        flop: str,
    ) -> str:
        cards = re.findall(
            r"([2-9TJQKA])([cdhs])",
            flop,
            flags=re.IGNORECASE,
        )

        if len(cards) != 3:
            return "Unknown"

        ranks = [
            rank.upper()
            for rank, _suit in cards
        ]
        suits = [
            suit.lower()
            for _rank, suit in cards
        ]
        values = sorted(
            [
                self.RANK_VALUE[rank]
                for rank in ranks
            ],
            reverse=True,
        )

        rank_counts = {
            rank: ranks.count(rank)
            for rank in set(ranks)
        }

        if max(rank_counts.values()) >= 2:
            rank_family = "Paired"
        elif values[0] == 14:
            rank_family = "A-high"
        elif values[0] == 13:
            rank_family = "K-high"
        elif values[0] == 12:
            rank_family = "Q-high"
        elif values[0] == 11:
            rank_family = "J-high"
        else:
            rank_family = "Low"

        unique_suits = len(set(suits))

        if unique_suits == 1:
            suit_family = "Monotone"
        elif unique_suits == 2:
            suit_family = "Two-tone"
        else:
            suit_family = "Rainbow"

        connected = (
            values[0] - values[2] <= 4
            or (
                14 in values
                and 5 in values
                and 4 in values
            )
        )

        connection_family = (
            "Connected"
            if connected
            else "Disconnected"
        )

        return (
            f"{rank_family} | "
            f"{suit_family} | "
            f"{connection_family}"
        )

    def _simple_flop_family(self, flop: str) -> str:
        cards = re.findall(r"([2-9TJQKA])([cdhs])", flop, flags=re.IGNORECASE)
        if len(cards) != 3:
            return "Unknown"
        ranks = [rank.upper() for rank, _ in cards]
        suits = [suit.lower() for _, suit in cards]
        values = sorted((self.RANK_VALUE[r] for r in ranks), reverse=True)
        counts = {r: ranks.count(r) for r in set(ranks)}
        if max(counts.values()) >= 2:
            rank_family = "Paired"
        elif values[0] >= 12:
            rank_family = "High"
        elif values[0] >= 9:
            rank_family = "Medium"
        else:
            rank_family = "Low"
        unique_suits = len(set(suits))
        suit_family = "Monotone" if unique_suits == 1 else "Two-tone" if unique_suits == 2 else "Rainbow"
        connected = values[0] - values[2] <= 4 or (14 in values and 5 in values and 4 in values)
        return f"{rank_family} {suit_family} {'Connected' if connected else 'Disconnected'}"

    def _turn_transition(self, flop: str, turn: str) -> str:
        flop_cards = re.findall(r"([2-9TJQKA])([cdhs])", flop, flags=re.IGNORECASE)
        turn_cards = re.findall(r"([2-9TJQKA])([cdhs])", turn, flags=re.IGNORECASE)
        if len(flop_cards) != 3 or not turn_cards:
            return "No Turn"
        tr, ts = turn_cards[-1][0].upper(), turn_cards[-1][1].lower()
        flop_ranks = [r.upper() for r, _ in flop_cards]
        flop_suits = [s.lower() for _, s in flop_cards]
        flop_vals = sorted((self.RANK_VALUE[r] for r in flop_ranks), reverse=True)
        tv = self.RANK_VALUE[tr]
        board_pair = tr in flop_ranks
        flush_before = max(flop_suits.count(s) for s in set(flop_suits))
        flush_after = max((flop_suits + [ts]).count(s) for s in set(flop_suits + [ts]))
        vals_after = sorted(set(flop_vals + [tv]))
        straight_after = any(vals_after[i+4] - vals_after[i] <= 4 for i in range(max(0, len(vals_after)-4))) if len(vals_after) >= 5 else False
        if board_pair:
            return "Board Pair"
        if flush_before == 2 and flush_after == 3:
            return "Flush Completed"
        if flush_before < 2 and flush_after == 2:
            return "Flush Draw Added"
        if straight_after:
            return "Straight Completed"
        if tv > max(flop_vals):
            return "Overcard"
        if max(flop_vals + [tv]) - min(flop_vals + [tv]) <= 5:
            return "Straight Draw Added"
        if (flush_after >= 2) and (max(flop_vals + [tv]) - min(flop_vals + [tv]) <= 6):
            return "Combo Dynamic"
        return "Blank"

    def _study_size_bucket(self, size_bb: float | None) -> str:
        if size_bb is None:
            return "Unknown"
        if size_bb <= 2.3:
            return "Small ≤2.3x"
        if size_bb <= 3.1:
            return "Medium 2.4–3.1x"
        return "Large ≥3.2x"

    def _representative_board(self, items: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            board = str(item.get("flop") or "").strip()
            if board:
                counts[board] += 1
        return max(counts, key=counts.get) if counts else ""

    def _representative_board_count(self, items: list[dict[str, Any]]) -> int:
        board = self._representative_board(items)
        return sum(1 for item in items if str(item.get("flop") or "").strip() == board)

    def _representative_boards(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            board = str(item.get("flop") or "").strip()
            if board:
                counts[board] += 1
        return [
            {"board": board, "hands": count}
            for board, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        ]

    def _size_distribution(
        self,
        items: list[dict[str, Any]],
        key: str,
    ) -> list[dict[str, Any]]:
        """Return stable pot-percentage buckets for a street."""
        labels = (
            ("≤25%", 0.0, 25.0),
            ("26–40%", 25.0, 40.0),
            ("41–60%", 40.0, 60.0),
            ("61–80%", 60.0, 80.0),
            ("81–100%", 80.0, 100.0),
            ("101–125%", 100.0, 125.0),
            (">125%", 125.0, float("inf")),
        )
        values = [
            float(item[key])
            for item in items
            if item.get(key) is not None
            and math.isfinite(float(item[key]))
            and float(item[key]) > 0
        ]
        total = len(values)
        result: list[dict[str, Any]] = []
        for label, lower, upper in labels:
            count = sum(
                1 for value in values
                if value > lower and value <= upper
            )
            result.append({
                "bucket": label,
                "count": count,
                "pct": self._pct(count, total),
            })
        return result

    def _size_dna_data(
        self,
        row: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sizes = [
            float(item["size_bb"])
            for item in items
            if item.get("size_bb") is not None
            and math.isfinite(float(item["size_bb"]))
        ]
        return {
            "open_avg_bb": sum(sizes) / len(sizes) if sizes else 0.0,
            "open_min_bb": min(sizes) if sizes else 0.0,
            "open_max_bb": max(sizes) if sizes else 0.0,
            "flop_frequency": float(row.get("flop_cbet") or 0.0),
            "flop_avg_bet_pct": float(row.get("flop_avg_bet_pct") or 0.0),
            "flop_size_sample": int(row.get("flop_bet_size_sample") or 0),
            "turn_frequency": float(row.get("turn_barrel") or 0.0),
            "turn_avg_bet_pct": float(row.get("turn_avg_bet_pct") or 0.0),
            "turn_size_sample": int(row.get("turn_bet_size_sample") or 0),
            "river_frequency": float(row.get("river_barrel") or 0.0),
            "river_avg_bet_pct": float(row.get("river_avg_bet_pct") or 0.0),
            "river_size_sample": int(row.get("river_bet_size_sample") or 0),
            "wwsf": float(row.get("wwsf") or 0.0),
            "wtsd": float(row.get("wtsd") or 0.0),
            "wsd": float(row.get("wsd") or 0.0),
            "hands": int(row.get("hands") or 0),
        }

    def _format_size_dna(self, dna: dict[str, Any]) -> str:
        if int(dna.get("hands") or 0) <= 0:
            return "Size verisi yok"

        def street(label: str, frequency_key: str, size_key: str, sample_key: str) -> str:
            frequency = float(dna.get(frequency_key) or 0.0)
            avg_size = float(dna.get(size_key) or 0.0)
            sample = int(dna.get(sample_key) or 0)
            size_text = f"{avg_size:.0f}%" if sample > 0 else "—"
            return f"{label} {frequency:.0f}%@{size_text}"

        return (
            f"Open {float(dna.get('open_avg_bb') or 0.0):.2f}x"
            f" • {street('F', 'flop_frequency', 'flop_avg_bet_pct', 'flop_size_sample')}"
            f" • {street('T', 'turn_frequency', 'turn_avg_bet_pct', 'turn_size_sample')}"
            f" • {street('R', 'river_frequency', 'river_avg_bet_pct', 'river_size_sample')}"
            f" • WWSF {float(dna.get('wwsf') or 0.0):.0f}"
            f" • WTSD {float(dna.get('wtsd') or 0.0):.0f}"
            f" • W$SD {float(dna.get('wsd') or 0.0):.0f}"
        )

    def _parse_big_blind(
        self,
        stakes: str,
    ) -> float | None:
        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            stakes,
        )

        if len(numbers) < 2:
            return None

        try:
            return float(
                numbers[1].replace(
                    ",",
                    ".",
                )
            )
        except ValueError:
            return None

    def _size_bucket(
        self,
        size_bb: float | None,
    ) -> str:
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

    def _bet_pct(
        self,
        bet_amount: Any,
        pot_before: Any,
    ) -> float | None:
        bet = self._float_or_none(bet_amount)
        pot = self._float_or_none(pot_before)

        if bet is None or pot is None or bet <= 0 or pot <= 0:
            return None

        value = bet / pot * 100.0

        # Gerçek all-in overbet'ler %100'ü aşabilir. Çok uç değerler ise
        # genellikle bozuk hand-history miktarına işaret eder.
        if not math.isfinite(value) or value > 1000.0:
            return None

        return value

    def _average_metric(
        self,
        items: list[dict[str, Any]],
        key: str,
    ) -> float:
        values = [
            float(item[key])
            for item in items
            if item.get(key) is not None
            and math.isfinite(float(item[key]))
        ]
        return sum(values) / len(values) if values else 0.0

    def _metric_sample(
        self,
        items: list[dict[str, Any]],
        key: str,
    ) -> int:
        return sum(
            1
            for item in items
            if item.get(key) is not None
            and math.isfinite(float(item[key]))
        )

    def _float_or_none(
        self,
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        try:
            return float(value)
        except (
            TypeError,
            ValueError,
        ):
            return None
