from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb

from services.core_analytics_engine import CoreAnalyticsEngine


class OpenSizeAnalysisService:
    POSITION_ORDER = [
        "UTG",
        "UTG+1",
        "HJ",
        "CO",
        "BTN",
        "SB",
        "BB",
        "OTHER",
    ]

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
        limit: int = 5000,
    ) -> list[tuple[str, int]]:
        mode = mode.upper()
        filters: list[str] = []
        params: list[Any] = []

        if site:
            filters.append("h.site = ?")
            params.append(site)

        if stakes:
            filters.append("h.stakes = ?")
            params.append(stakes)

        where_sql = (
            "WHERE " + " AND ".join(filters)
            if filters
            else ""
        )

        with self.connect() as con:
            if mode == "PLAYER":
                rows = con.execute(
                    f"""
                    SELECT
                        hp.player_name,
                        COUNT(DISTINCT hp.hand_id) AS hands
                    FROM hand_players hp
                    JOIN hands h
                      ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY hp.player_name
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
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
                    SELECT
                        pa.alias_name,
                        COUNT(DISTINCT hp.hand_id) AS hands
                    FROM player_aliases pa
                    JOIN hand_players hp
                      ON hp.player_name = pa.player_name
                    JOIN hands h
                      ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY pa.alias_name
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
                    """,
                    params,
                ).fetchall()
            else:
                return []

        return [
            (str(name), int(hands or 0))
            for name, hands in rows
        ]

    def analyze(
        self,
        mode: str = "POOL",
        entity_name: str = "",
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 1,
    ) -> dict[str, Any]:
        mode = mode.upper()

        entity_rows = self._load_open_rows(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position=position,
        )
        entity = self._aggregate(
            entity_rows,
            minimum_sample,
        )

        pool: dict[str, Any] = {}

        if mode != "POOL":
            pool_rows = self._load_open_rows(
                mode="POOL",
                entity_name="",
                site=site,
                stakes=stakes,
                position=position,
            )
            pool = self._aggregate(
                pool_rows,
                minimum_sample,
            )

            self._attach_pool_comparison(
                entity.get("rows", []),
                pool.get("rows", []),
            )

        return {
            "entity": entity,
            "pool": pool,
            "position_summary": self._position_summary(
                entity.get("rows", [])
            ),
            "best_sizes": self._best_sizes(
                entity.get("rows", [])
            ),
        }

    def _attach_pool_comparison(
        self,
        entity_rows: list[dict[str, Any]],
        pool_rows: list[dict[str, Any]],
    ) -> None:
        pool_map = {
            (
                row["position"],
                row["size_bucket"],
            ): row
            for row in pool_rows
        }

        compare_keys = [
            "fold_to_three_bet",
            "flop_cbet_ip",
            "flop_cbet_oop",
            "turn_barrel_ip",
            "turn_barrel_oop",
            "river_barrel_ip",
            "river_barrel_oop",
            "wwsf",
            "wsd",
        ]

        for row in entity_rows:
            pool_row = pool_map.get(
                (
                    row["position"],
                    row["size_bucket"],
                )
            )

            for key in compare_keys:
                entity_value = float(
                    row.get(key) or 0.0
                )

                pool_value = (
                    float(pool_row.get(key) or 0.0)
                    if pool_row
                    else 0.0
                )

                row[f"pool_{key}"] = pool_value
                row[f"delta_{key}"] = (
                    entity_value - pool_value
                )

            row["confidence"] = self._confidence_label(
                row
            )
            row["flow_summary"] = self._flow_summary(
                row
            )
            row["transition_summary"] = self._transition_summary(
                row
            )
            row["heatmap"] = self._heatmap_bar(
                row.get("share", 0.0)
            )
            row["strength_score"] = self._strength_score(
                row
            )
            row["strategy_tags"] = self._strategy_tags(
                row
            )
            row["exploitability"] = self._exploitability_score(
                row
            )
            row["exploit_note"] = self._exploit_note(
                row
            )

    def _confidence_label(
        self,
        row: dict[str, Any],
    ) -> str:
        samples = [
            int(
                row.get(
                    "fold_to_three_bet_sample",
                    0,
                )
                or 0
            ),
            int(
                row.get(
                    "flop_cbet_ip_sample",
                    0,
                )
                or 0
            )
            + int(
                row.get(
                    "flop_cbet_oop_sample",
                    0,
                )
                or 0
            ),
            int(
                row.get(
                    "turn_barrel_ip_sample",
                    0,
                )
                or 0
            )
            + int(
                row.get(
                    "turn_barrel_oop_sample",
                    0,
                )
                or 0
            ),
            int(
                row.get(
                    "river_barrel_ip_sample",
                    0,
                )
                or 0
            )
            + int(
                row.get(
                    "river_barrel_oop_sample",
                    0,
                )
                or 0
            ),
        ]

        positive = [
            sample
            for sample in samples
            if sample > 0
        ]

        if not positive:
            return "Çok Düşük"

        minimum = min(positive)

        if minimum >= 500:
            return "Yüksek"

        if minimum >= 150:
            return "Orta"

        if minimum >= 50:
            return "Düşük"

        return "Çok Düşük"

    def _flow_summary(
        self,
        row: dict[str, Any],
    ) -> str:
        flop = max(
            float(
                row.get("flop_cbet_ip") or 0.0
            ),
            float(
                row.get("flop_cbet_oop") or 0.0
            ),
        )
        turn = max(
            float(
                row.get("turn_barrel_ip") or 0.0
            ),
            float(
                row.get("turn_barrel_oop") or 0.0
            ),
        )
        river = max(
            float(
                row.get("river_barrel_ip") or 0.0
            ),
            float(
                row.get("river_barrel_oop") or 0.0
            ),
        )

        return (
            f"F {flop:.0f} → "
            f"T {turn:.0f} → "
            f"R {river:.0f}"
        )

    def _transition_summary(
        self,
        row: dict[str, Any],
    ) -> str:
        flop = max(
            float(row.get("flop_cbet_ip") or 0.0),
            float(row.get("flop_cbet_oop") or 0.0),
        )
        turn = max(
            float(row.get("turn_barrel_ip") or 0.0),
            float(row.get("turn_barrel_oop") or 0.0),
        )
        river = max(
            float(row.get("river_barrel_ip") or 0.0),
            float(row.get("river_barrel_oop") or 0.0),
        )

        return (
            f"F3B {float(row.get('fold_to_three_bet') or 0.0):.0f}"
            f" → F {flop:.0f}"
            f" → T {turn:.0f}"
            f" → R {river:.0f}"
            f" → WWSF {float(row.get('wwsf') or 0.0):.0f}"
            f" → W$SD {float(row.get('wsd') or 0.0):.0f}"
        )

    def _heatmap_bar(
        self,
        share: float,
    ) -> str:
        blocks = max(
            1,
            min(
                20,
                round(float(share or 0.0) / 5.0),
            ),
        )
        return "█" * blocks

    def _sample_weight(
        self,
        row: dict[str, Any],
    ) -> float:
        samples = [
            int(row.get("fold_to_three_bet_sample") or 0),
            int(row.get("flop_cbet_ip_sample") or 0)
            + int(row.get("flop_cbet_oop_sample") or 0),
            int(row.get("turn_barrel_ip_sample") or 0)
            + int(row.get("turn_barrel_oop_sample") or 0),
            int(row.get("river_barrel_ip_sample") or 0)
            + int(row.get("river_barrel_oop_sample") or 0),
            int(row.get("wwsf_sample") or 0),
            int(row.get("wsd_sample") or 0),
        ]

        positive = [value for value in samples if value > 0]

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

    def _strength_score(
        self,
        row: dict[str, Any],
    ) -> float:
        fold3b = 100.0 - float(
            row.get("fold_to_three_bet") or 0.0
        )
        flop = max(
            float(row.get("flop_cbet_ip") or 0.0),
            float(row.get("flop_cbet_oop") or 0.0),
        )
        turn = max(
            float(row.get("turn_barrel_ip") or 0.0),
            float(row.get("turn_barrel_oop") or 0.0),
        )
        river = max(
            float(row.get("river_barrel_ip") or 0.0),
            float(row.get("river_barrel_oop") or 0.0),
        )
        wwsf = float(row.get("wwsf") or 0.0)
        wsd = float(row.get("wsd") or 0.0)

        raw = (
            fold3b * 0.22
            + flop * 0.18
            + turn * 0.16
            + river * 0.14
            + wwsf * 0.18
            + wsd * 0.12
        )

        sample_weight = self._sample_weight(row)
        score = raw * sample_weight + 50.0 * (1.0 - sample_weight)

        return max(
            0.0,
            min(100.0, score),
        )

    def _exploitability_score(
        self,
        row: dict[str, Any],
    ) -> float:
        delta_keys = [
            "delta_fold_to_three_bet",
            "delta_flop_cbet_ip",
            "delta_flop_cbet_oop",
            "delta_turn_barrel_ip",
            "delta_turn_barrel_oop",
            "delta_river_barrel_ip",
            "delta_river_barrel_oop",
            "delta_wwsf",
            "delta_wsd",
        ]

        magnitude = sum(
            abs(float(row.get(key) or 0.0))
            for key in delta_keys
        ) / len(delta_keys)

        score = magnitude * 4.0 * self._sample_weight(row)

        return max(
            0.0,
            min(100.0, score),
        )

    def _strategy_tags(
        self,
        row: dict[str, Any],
    ) -> str:
        tags: list[str] = []

        size = float(row.get("avg_size_bb") or 0.0)
        fold3b = float(row.get("fold_to_three_bet") or 0.0)
        flop = max(
            float(row.get("flop_cbet_ip") or 0.0),
            float(row.get("flop_cbet_oop") or 0.0),
        )
        turn = max(
            float(row.get("turn_barrel_ip") or 0.0),
            float(row.get("turn_barrel_oop") or 0.0),
        )
        river = max(
            float(row.get("river_barrel_ip") or 0.0),
            float(row.get("river_barrel_oop") or 0.0),
        )
        wwsf = float(row.get("wwsf") or 0.0)
        wsd = float(row.get("wsd") or 0.0)

        if size >= 3.4:
            tags.append("Large Open")
        elif size <= 2.3:
            tags.append("Small Open")
        else:
            tags.append("Mid Open")

        if fold3b >= 68:
            tags.append("High Fold3B")
        elif fold3b <= 52:
            tags.append("3Bet Resistant")

        if flop >= 75:
            tags.append("Flop Pressure")
        elif flop <= 50:
            tags.append("Low Flop Pressure")

        if turn >= 55:
            tags.append("Turn Heavy")
        elif turn <= 40:
            tags.append("Turn Give-up")

        if river >= 58:
            tags.append("River Pressure")
        elif river <= 38:
            tags.append("Low River")

        if wwsf >= 56:
            tags.append("High WWSF")

        if wsd >= 56:
            tags.append("Strong Showdown")
        elif wsd <= 48:
            tags.append("Weak Showdown")

        if row.get("confidence") in {"Çok Düşük", "Düşük"}:
            tags.append("Low Sample")

        return " | ".join(tags[:5])

    def _best_sizes(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}

        for row in rows:
            grouped.setdefault(
                str(row.get("position") or "OTHER"),
                [],
            ).append(row)

        result: list[dict[str, Any]] = []

        for position, items in grouped.items():
            ranked = sorted(
                items,
                key=lambda item: (
                    float(item.get("strength_score") or 0.0),
                    int(item.get("opens") or 0),
                ),
                reverse=True,
            )

            if not ranked:
                continue

            best = ranked[0]

            result.append(
                {
                    "position": position,
                    "size_bucket": best.get("size_bucket", "—"),
                    "avg_size_bb": float(
                        best.get("avg_size_bb") or 0.0
                    ),
                    "score": float(
                        best.get("strength_score") or 0.0
                    ),
                    "confidence": best.get(
                        "confidence",
                        "—",
                    ),
                    "tags": best.get(
                        "strategy_tags",
                        "",
                    ),
                    "exploitability": float(
                        best.get("exploitability") or 0.0
                    ),
                }
            )

        order = {
            "UTG": 0,
            "UTG+1": 1,
            "HJ": 2,
            "CO": 3,
            "BTN": 4,
            "SB": 5,
            "BB": 6,
            "OTHER": 99,
        }

        result.sort(
            key=lambda row: order.get(
                row["position"],
                99,
            )
        )

        return result

    def _exploit_note(
        self,
        row: dict[str, Any],
    ) -> str:
        notes: list[str] = []

        fold3b_delta = float(
            row.get("delta_fold_to_three_bet")
            or 0.0
        )
        flop_delta = max(
            float(
                row.get("delta_flop_cbet_ip")
                or 0.0
            ),
            float(
                row.get("delta_flop_cbet_oop")
                or 0.0
            ),
        )
        turn_delta = max(
            float(
                row.get("delta_turn_barrel_ip")
                or 0.0
            ),
            float(
                row.get("delta_turn_barrel_oop")
                or 0.0
            ),
        )
        river_delta = max(
            float(
                row.get("delta_river_barrel_ip")
                or 0.0
            ),
            float(
                row.get("delta_river_barrel_oop")
                or 0.0
            ),
        )

        if fold3b_delta >= 8:
            notes.append("3bet bluff artır")
        elif fold3b_delta <= -8:
            notes.append("3bet value ağırlıklandır")

        if flop_delta >= 8:
            notes.append("flop XR/float artır")
        elif flop_delta <= -8:
            notes.append("flop deny/value bet artır")

        if turn_delta >= 8:
            notes.append("turn bluff-catch seçici")
        elif turn_delta <= -8:
            notes.append("turn float sonrası steal artır")

        if river_delta >= 10:
            notes.append("river bluff-catch azalt")
        elif river_delta <= -10:
            notes.append("river bluff-catch artır")

        if row.get("confidence") in {
            "Çok Düşük",
            "Düşük",
        }:
            notes.append("sample uyarısı")

        return (
            "; ".join(notes)
            if notes
            else "Belirgin exploit yok"
        )

    def _position_summary(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}

        for row in rows:
            grouped.setdefault(
                str(row.get("position") or "OTHER"),
                [],
            ).append(row)

        result: list[dict[str, Any]] = []

        for position, items in grouped.items():
            total_opens = sum(
                int(item.get("opens") or 0)
                for item in items
            )

            if total_opens <= 0:
                continue

            most_common = max(
                items,
                key=lambda item: int(item.get("opens") or 0),
            )

            weighted_avg = sum(
                float(item.get("avg_size_bb") or 0.0)
                * int(item.get("opens") or 0)
                for item in items
            ) / total_opens

            result.append(
                {
                    "position": position,
                    "opens": total_opens,
                    "most_common": most_common.get(
                        "size_bucket",
                        "—",
                    ),
                    "avg_size_bb": weighted_avg,
                    "share": float(
                        most_common.get("share") or 0.0
                    ),
                }
            )

        order = {
            "UTG": 0,
            "UTG+1": 1,
            "HJ": 2,
            "CO": 3,
            "BTN": 4,
            "SB": 5,
            "BB": 6,
            "OTHER": 99,
        }

        result.sort(
            key=lambda row: order.get(
                row["position"],
                99,
            )
        )

        return result

    def _load_open_rows(
        self,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        position: str,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        if position:
            position_values = CoreAnalyticsEngine.position_sql_values(position)
            placeholders = ", ".join("?" for _ in position_values)
            clauses.append(
                f"UPPER(TRIM(hp.position)) IN ({placeholders})"
            )
            params.extend(position_values)

        if mode == "PLAYER":
            clauses.append("hp.player_name = ?")
            params.append(entity_name)

        elif mode in {"ALIAS", "COMPARE"}:
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

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

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
                    r.player_name,
                    r.sequence_no AS open_sequence,
                    r.amount,
                    r.to_amount,
                    h.site,
                    h.stakes,
                    h.flop,
                    h.turn,
                    h.river,
                    h.pot,
                    hp.position,
                    hp.starting_stack
                FROM preflop_raises r
                JOIN hands h
                  ON h.hand_id = r.hand_id
                JOIN hand_players hp
                  ON hp.hand_id = r.hand_id
                 AND hp.player_name = r.player_name
                {where_sql}
                {"AND" if where_sql else "WHERE"} r.raise_no = 1
            ),

            last_preflop_raiser AS (
                SELECT
                    hand_id,
                    player_name,
                    sequence_no
                FROM preflop_raises
                WHERE reverse_raise_no = 1
            ),

            first_three_bet AS (
                SELECT
                    o.hand_id,
                    MIN(r.sequence_no) AS three_bet_sequence
                FROM opens o
                JOIN preflop_raises r
                  ON r.hand_id = o.hand_id
                 AND r.sequence_no > o.open_sequence
                GROUP BY o.hand_id
            ),

            street_player AS (
                SELECT
                    a.hand_id,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    MIN(a.sequence_no) AS first_sequence,
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
                    COUNT(DISTINCT player_name) AS player_count,
                    MIN(first_sequence) AS first_sequence
                FROM street_player
                GROUP BY
                    hand_id,
                    street
            ),

            open_flags AS (
                SELECT
                    o.*,

                    CASE
                        WHEN ftb.three_bet_sequence IS NOT NULL
                        THEN 1 ELSE 0
                    END AS faced_three_bet,

                    CASE
                        WHEN ftb.three_bet_sequence IS NOT NULL
                         AND EXISTS (
                            SELECT 1
                            FROM actions pf
                            WHERE pf.hand_id = o.hand_id
                              AND pf.player_name = o.player_name
                              AND UPPER(TRIM(pf.street)) = 'PREFLOP'
                              AND UPPER(TRIM(pf.action)) = 'FOLD'
                              AND pf.sequence_no > ftb.three_bet_sequence
                         )
                        THEN 1 ELSE 0
                    END AS folded_to_three_bet,

                    CASE
                        WHEN lpr.player_name = o.player_name
                         AND o.flop IS NOT NULL
                         AND TRIM(o.flop) <> ''
                         AND COALESCE(sm_f.player_count, 0) = 2
                        THEN 1 ELSE 0
                    END AS flop_cbet_opp,

                    CASE
                        WHEN lpr.player_name = o.player_name
                         AND o.flop IS NOT NULL
                         AND TRIM(o.flop) <> ''
                         AND COALESCE(sm_f.player_count, 0) = 2
                         AND sp_f.aggressive = 1
                        THEN 1 ELSE 0
                    END AS flop_cbet_made,

                    CASE
                        WHEN lpr.player_name = o.player_name
                         AND o.flop IS NOT NULL
                         AND TRIM(o.flop) <> ''
                         AND COALESCE(sm_f.player_count, 0) = 2
                         AND sp_f.first_sequence > sm_f.first_sequence
                        THEN 1 ELSE 0
                    END AS flop_cbet_ip_opp,

                    CASE
                        WHEN lpr.player_name = o.player_name
                         AND o.flop IS NOT NULL
                         AND TRIM(o.flop) <> ''
                         AND COALESCE(sm_f.player_count, 0) = 2
                         AND sp_f.first_sequence = sm_f.first_sequence
                        THEN 1 ELSE 0
                    END AS flop_cbet_oop_opp,

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
                        WHEN o.turn IS NOT NULL
                         AND TRIM(o.turn) <> ''
                         AND COALESCE(sm_t.player_count, 0) = 2
                         AND sp_f.aggressive = 1
                         AND sp_t.first_sequence > sm_t.first_sequence
                        THEN 1 ELSE 0
                    END AS turn_barrel_ip_opp,

                    CASE
                        WHEN o.turn IS NOT NULL
                         AND TRIM(o.turn) <> ''
                         AND COALESCE(sm_t.player_count, 0) = 2
                         AND sp_f.aggressive = 1
                         AND sp_t.first_sequence = sm_t.first_sequence
                        THEN 1 ELSE 0
                    END AS turn_barrel_oop_opp,

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
                        WHEN o.river IS NOT NULL
                         AND TRIM(o.river) <> ''
                         AND COALESCE(sm_r.player_count, 0) = 2
                         AND sp_t.aggressive = 1
                         AND sp_r.first_sequence > sm_r.first_sequence
                        THEN 1 ELSE 0
                    END AS river_barrel_ip_opp,

                    CASE
                        WHEN o.river IS NOT NULL
                         AND TRIM(o.river) <> ''
                         AND COALESCE(sm_r.player_count, 0) = 2
                         AND sp_t.aggressive = 1
                         AND sp_r.first_sequence = sm_r.first_sequence
                        THEN 1 ELSE 0
                    END AS river_barrel_oop_opp,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions c
                            WHERE c.hand_id = o.hand_id
                              AND c.player_name = o.player_name
                              AND UPPER(TRIM(c.action)) = 'COLLECT'
                        )
                        THEN 1 ELSE 0
                    END AS won_pot,

                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM actions sd
                            WHERE sd.hand_id = o.hand_id
                              AND sd.player_name = o.player_name
                              AND UPPER(TRIM(sd.action))
                                  IN ('SHOW', 'MUCK')
                        )
                        THEN 1 ELSE 0
                    END AS went_showdown

                FROM opens o

                LEFT JOIN last_preflop_raiser lpr
                  ON lpr.hand_id = o.hand_id

                LEFT JOIN first_three_bet ftb
                  ON ftb.hand_id = o.hand_id

                LEFT JOIN street_player sp_f
                  ON sp_f.hand_id = o.hand_id
                 AND sp_f.street = 'FLOP'
                 AND sp_f.player_name = o.player_name

                LEFT JOIN street_meta sm_f
                  ON sm_f.hand_id = o.hand_id
                 AND sm_f.street = 'FLOP'

                LEFT JOIN street_player sp_t
                  ON sp_t.hand_id = o.hand_id
                 AND sp_t.street = 'TURN'
                 AND sp_t.player_name = o.player_name

                LEFT JOIN street_meta sm_t
                  ON sm_t.hand_id = o.hand_id
                 AND sm_t.street = 'TURN'

                LEFT JOIN street_player sp_r
                  ON sp_r.hand_id = o.hand_id
                 AND sp_r.street = 'RIVER'
                 AND sp_r.player_name = o.player_name

                LEFT JOIN street_meta sm_r
                  ON sm_r.hand_id = o.hand_id
                 AND sm_r.street = 'RIVER'
            )

            SELECT
                hand_id,
                player_name,
                site,
                stakes,
                position,
                starting_stack,
                amount,
                to_amount,
                flop,
                turn,
                river,
                pot,
                faced_three_bet,
                folded_to_three_bet,
                flop_cbet_opp,
                flop_cbet_made,
                flop_cbet_ip_opp,
                flop_cbet_oop_opp,
                turn_barrel_opp,
                turn_barrel_made,
                turn_barrel_ip_opp,
                turn_barrel_oop_opp,
                river_barrel_opp,
                river_barrel_made,
                river_barrel_ip_opp,
                river_barrel_oop_opp,
                won_pot,
                went_showdown
            FROM open_flags
        """

        with self.connect() as con:
            rows = con.execute(
                query,
                params,
            ).fetchall()

        result: list[dict[str, Any]] = []

        for row in rows:
            bb = self._parse_big_blind(row[3])
            to_amount = self._float_or_none(row[7])
            stack = self._float_or_none(row[5])

            size_bb = (
                to_amount / bb
                if to_amount is not None
                and bb is not None
                and bb > 0
                else None
            )

            stack_bb = (
                stack / bb
                if stack is not None
                and bb is not None
                and bb > 0
                else None
            )

            saw_flop = bool(row[8])
            won = bool(row[26])
            showdown = bool(row[27])

            flop_made = bool(row[15])
            turn_made = bool(row[19])
            river_made = bool(row[23])

            result.append(
                {
                    "position": CoreAnalyticsEngine.normalize_position(row[4]),
                    "size_bb": size_bb,
                    "size_bucket": self._size_bucket(
                        size_bb
                    ),
                    "stack_bb": stack_bb,

                    "faced_three_bet": bool(row[12]),
                    "folded_to_three_bet": bool(row[13]),

                    "flop_cbet_opp": bool(row[14]),
                    "flop_cbet_made": flop_made,
                    "flop_cbet_ip_opp": bool(row[16]),
                    "flop_cbet_oop_opp": bool(row[17]),

                    "turn_barrel_opp": bool(row[18]),
                    "turn_barrel_made": turn_made,
                    "turn_barrel_ip_opp": bool(row[20]),
                    "turn_barrel_oop_opp": bool(row[21]),

                    "river_barrel_opp": bool(row[22]),
                    "river_barrel_made": river_made,
                    "river_barrel_ip_opp": bool(row[24]),
                    "river_barrel_oop_opp": bool(row[25]),

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
        groups: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = {}

        for row in rows:
            key = (
                row["position"],
                row["size_bucket"],
            )
            groups.setdefault(
                key,
                [],
            ).append(row)

        table_rows: list[dict[str, Any]] = []

        for (position, bucket), items in groups.items():
            count = len(items)

            if count < max(
                1,
                int(minimum_sample),
            ):
                continue

            sizes = [
                item["size_bb"]
                for item in items
                if item["size_bb"] is not None
            ]
            stacks = [
                item["stack_bb"]
                for item in items
                if item["stack_bb"] is not None
            ]

            row = {
                "position": position,
                "size_bucket": bucket,
                "opens": count,
                "share": self._pct(
                    count,
                    len(rows),
                ),
                "avg_size_bb": (
                    sum(sizes) / len(sizes)
                    if sizes
                    else None
                ),
                "avg_stack_bb": (
                    sum(stacks) / len(stacks)
                    if stacks
                    else None
                ),
            }

            self._add_rate(
                row,
                "three_bet_faced",
                items,
                "faced_three_bet",
                None,
            )
            self._add_rate(
                row,
                "fold_to_three_bet",
                items,
                "folded_to_three_bet",
                "faced_three_bet",
            )

            self._add_rate(
                row,
                "flop_cbet_ip",
                items,
                "flop_cbet_made",
                "flop_cbet_ip_opp",
            )
            self._add_rate(
                row,
                "flop_cbet_oop",
                items,
                "flop_cbet_made",
                "flop_cbet_oop_opp",
            )

            self._add_rate(
                row,
                "turn_barrel_ip",
                items,
                "turn_barrel_made",
                "turn_barrel_ip_opp",
            )
            self._add_rate(
                row,
                "turn_barrel_oop",
                items,
                "turn_barrel_made",
                "turn_barrel_oop_opp",
            )

            self._add_rate(
                row,
                "river_barrel_ip",
                items,
                "river_barrel_made",
                "river_barrel_ip_opp",
            )
            self._add_rate(
                row,
                "river_barrel_oop",
                items,
                "river_barrel_made",
                "river_barrel_oop_opp",
            )

            self._add_rate(
                row,
                "flop_seen",
                items,
                "saw_flop",
                None,
            )
            self._add_rate(
                row,
                "pot_won",
                items,
                "won_pot",
                None,
            )
            self._add_rate(
                row,
                "wwsf",
                items,
                "wwsf_win",
                "wwsf_opp",
            )
            self._add_rate(
                row,
                "wsd",
                items,
                "wsd_win",
                "wsd_opp",
            )

            row["pattern_note"] = self._pattern_note(
                position=position,
                bucket=bucket,
                avg_stack_bb=row["avg_stack_bb"],
                three_bet_faced=row["three_bet_faced"],
                fold_to_three_bet=row[
                    "fold_to_three_bet"
                ],
            )
            row["confidence"] = self._confidence_label(
                row
            )
            row["flow_summary"] = self._flow_summary(
                row
            )
            row["transition_summary"] = self._transition_summary(
                row
            )
            row["heatmap"] = self._heatmap_bar(
                row.get("share", 0.0)
            )
            row["strength_score"] = self._strength_score(
                row
            )
            row["strategy_tags"] = self._strategy_tags(
                row
            )
            row["exploitability"] = self._exploitability_score(
                row
            )
            row["exploit_note"] = "Pool baseline"

            table_rows.append(row)

        pos_rank = {
            position: index
            for index, position in enumerate(
                self.POSITION_ORDER
            )
        }

        bucket_rank = {
            "≤2.0x": 0,
            "2.1–2.3x": 1,
            "2.4–2.6x": 2,
            "2.7–3.1x": 3,
            ">3.1x": 4,
            "UNKNOWN": 5,
        }

        table_rows.sort(
            key=lambda row: (
                pos_rank.get(
                    row["position"],
                    99,
                ),
                bucket_rank.get(
                    row["size_bucket"],
                    99,
                ),
            )
        )

        all_sizes = [
            row["size_bb"]
            for row in rows
            if row["size_bb"] is not None
        ]

        summary: dict[str, Any] = {
            "opens": len(rows),
            "avg_size_bb": (
                sum(all_sizes) / len(all_sizes)
                if all_sizes
                else 0.0
            ),
            "rows": table_rows,
        }

        for key, made_key, opp_key in [
            ("wwsf", "wwsf_win", "wwsf_opp"),
            ("wsd", "wsd_win", "wsd_opp"),
            (
                "fold_to_three_bet",
                "folded_to_three_bet",
                "faced_three_bet",
            ),
            (
                "flop_cbet_ip",
                "flop_cbet_made",
                "flop_cbet_ip_opp",
            ),
            (
                "flop_cbet_oop",
                "flop_cbet_made",
                "flop_cbet_oop_opp",
            ),
            (
                "turn_barrel_ip",
                "turn_barrel_made",
                "turn_barrel_ip_opp",
            ),
            (
                "turn_barrel_oop",
                "turn_barrel_made",
                "turn_barrel_oop_opp",
            ),
            (
                "river_barrel_ip",
                "river_barrel_made",
                "river_barrel_ip_opp",
            ),
            (
                "river_barrel_oop",
                "river_barrel_made",
                "river_barrel_oop_opp",
            ),
        ]:
            numerator = sum(
                1
                for row in rows
                if row[made_key]
                and row[opp_key]
            )
            denominator = sum(
                1
                for row in rows
                if row[opp_key]
            )
            summary[key] = self._pct(
                numerator,
                denominator,
            )
            summary[f"{key}_sample"] = denominator

        return summary

    def _add_rate(
        self,
        target: dict[str, Any],
        output_key: str,
        items: list[dict[str, Any]],
        made_key: str,
        opportunity_key: str | None,
    ) -> None:
        if opportunity_key is None:
            denominator = len(items)
            numerator = sum(
                1
                for item in items
                if item[made_key]
            )
        else:
            denominator = sum(
                1
                for item in items
                if item[opportunity_key]
            )
            numerator = sum(
                1
                for item in items
                if item[opportunity_key]
                and item[made_key]
            )

        target[output_key] = self._pct(
            numerator,
            denominator,
        )
        target[f"{output_key}_sample"] = denominator

    def _pattern_note(
        self,
        position: str,
        bucket: str,
        avg_stack_bb: float | None,
        three_bet_faced: float,
        fold_to_three_bet: float,
    ) -> str:
        notes: list[str] = []

        if (
            position in {"CO", "BTN", "SB"}
            and bucket in {"≤2.0x", "2.1–2.3x"}
        ):
            notes.append(
                "Geç pozisyon/steal küçük sizing"
            )

        if (
            position in {"UTG", "UTG+1", "HJ"}
            and bucket in {"2.7–3.1x", ">3.1x"}
        ):
            notes.append(
                "Erken pozisyonda büyük sizing"
            )

        if (
            avg_stack_bb is not None
            and avg_stack_bb < 40
        ):
            notes.append("Kısa stack ilişkisi")
        elif (
            avg_stack_bb is not None
            and avg_stack_bb > 150
        ):
            notes.append("Deep-stack ilişkisi")

        if three_bet_faced >= 18:
            notes.append("Yüksek 3-bet maruziyeti")

        if fold_to_three_bet >= 55:
            notes.append("3-bete yüksek fold")
        elif (
            fold_to_three_bet > 0
            and fold_to_three_bet <= 35
        ):
            notes.append("3-bete dirençli")

        return (
            "; ".join(notes)
            or "Belirgin tek neden yok"
        )

    def _parse_big_blind(
        self,
        stakes: str | None,
    ) -> float | None:
        if not stakes:
            return None

        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            str(stakes),
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
        return CoreAnalyticsEngine.size_bucket(size_bb)

    def _pct(
        self,
        numerator: int,
        denominator: int,
    ) -> float:
        return CoreAnalyticsEngine.pct(numerator, denominator)

    def _float_or_none(
        self,
        value: Any,
    ) -> float | None:
        return CoreAnalyticsEngine.float_or_none(value)
