from __future__ import annotations

from pathlib import Path
from typing import Any
import re

import duckdb


class ResponseExplorerService:
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
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
                    """,
                    params + [int(minimum_hands)],
                ).fetchall()

            elif mode == "ALIAS":
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
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
                    """,
                    params + [int(minimum_hands)],
                ).fetchall()
            else:
                return []

        return [
            (str(name), int(hands or 0))
            for name, hands in rows
        ]

    def analyze(
        self,
        mode: str,
        entity_name: str,
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 30,
    ) -> dict[str, Any]:
        rows = self._load_rows(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
            position=position,
        )

        grouped = self._aggregate(
            rows,
            minimum_sample,
        )

        return {
            "rows": grouped,
            "summary": self._summary(grouped),
            "best_bucket": self._best_bucket(grouped),
            "total_opens": sum(
                int(row["opens"])
                for row in grouped
            ),
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
            filters.append("hp.player_name = ?")
            params.append(entity_name)

        elif mode == "ALIAS":
            filters.append(
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

        else:
            raise ValueError(
                "Mode PLAYER veya ALIAS olmalı."
            )

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
                    ) AS raise_no
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
            ),

            preflop_after_open AS (
                SELECT
                    o.hand_id,
                    a.player_name,
                    a.sequence_no,
                    UPPER(TRIM(a.action)) AS action
                FROM opens o
                JOIN actions a
                  ON a.hand_id = o.hand_id
                 AND UPPER(TRIM(a.street)) = 'PREFLOP'
                 AND a.sequence_no > o.open_seq
                 AND a.player_name <> o.opener
            ),

            preflop_response AS (
                SELECT
                    o.hand_id,
                    COUNT(DISTINCT pa.player_name) AS responders,
                    MAX(
                        CASE
                            WHEN pa.action = 'RAISE'
                            THEN 1 ELSE 0
                        END
                    ) AS faced_three_bet,
                    MAX(
                        CASE
                            WHEN pa.action = 'CALL'
                            THEN 1 ELSE 0
                        END
                    ) AS got_call,
                    MAX(
                        CASE
                            WHEN pa.action = 'FOLD'
                            THEN 1 ELSE 0
                        END
                    ) AS got_fold
                FROM opens o
                LEFT JOIN preflop_after_open pa
                  ON pa.hand_id = o.hand_id
                GROUP BY o.hand_id
            ),

            street_players AS (
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
                FROM street_players
                GROUP BY hand_id, street
            ),

            flags AS (
                SELECT
                    o.*,
                    COALESCE(pr.responders, 0) AS responders,
                    COALESCE(pr.faced_three_bet, 0) AS faced_three_bet,
                    COALESCE(pr.got_call, 0) AS got_call,
                    COALESCE(pr.got_fold, 0) AS got_fold,

                    CASE
                        WHEN COALESCE(sm_f.player_count, 0) = 2
                         AND sp_of.aggressive = 1
                        THEN 1 ELSE 0
                    END AS flop_cbet_made,

                    CASE
                        WHEN COALESCE(sm_f.player_count, 0) = 2
                         AND sp_of.aggressive = 1
                         AND EXISTS (
                            SELECT 1
                            FROM street_players opp
                            WHERE opp.hand_id = o.hand_id
                              AND opp.street = 'FLOP'
                              AND opp.player_name <> o.opener
                              AND opp.folded = 1
                         )
                        THEN 1 ELSE 0
                    END AS flop_fold_vs_cbet,

                    CASE
                        WHEN COALESCE(sm_t.player_count, 0) = 2
                         AND sp_of.aggressive = 1
                         AND sp_ot.aggressive = 1
                        THEN 1 ELSE 0
                    END AS turn_barrel_made,

                    CASE
                        WHEN COALESCE(sm_t.player_count, 0) = 2
                         AND sp_of.aggressive = 1
                         AND sp_ot.aggressive = 1
                         AND EXISTS (
                            SELECT 1
                            FROM street_players opp
                            WHERE opp.hand_id = o.hand_id
                              AND opp.street = 'TURN'
                              AND opp.player_name <> o.opener
                              AND opp.folded = 1
                         )
                        THEN 1 ELSE 0
                    END AS turn_fold_vs_barrel,

                    CASE
                        WHEN COALESCE(sm_r.player_count, 0) = 2
                         AND sp_ot.aggressive = 1
                         AND sp_or.aggressive = 1
                        THEN 1 ELSE 0
                    END AS river_barrel_made,

                    CASE
                        WHEN COALESCE(sm_r.player_count, 0) = 2
                         AND sp_ot.aggressive = 1
                         AND sp_or.aggressive = 1
                         AND EXISTS (
                            SELECT 1
                            FROM street_players opp
                            WHERE opp.hand_id = o.hand_id
                              AND opp.street = 'RIVER'
                              AND opp.player_name <> o.opener
                              AND opp.folded = 1
                         )
                        THEN 1 ELSE 0
                    END AS river_fold_vs_barrel

                FROM opens o
                LEFT JOIN preflop_response pr
                  ON pr.hand_id = o.hand_id

                LEFT JOIN street_players sp_of
                  ON sp_of.hand_id = o.hand_id
                 AND sp_of.street = 'FLOP'
                 AND sp_of.player_name = o.opener

                LEFT JOIN street_players sp_ot
                  ON sp_ot.hand_id = o.hand_id
                 AND sp_ot.street = 'TURN'
                 AND sp_ot.player_name = o.opener

                LEFT JOIN street_players sp_or
                  ON sp_or.hand_id = o.hand_id
                 AND sp_or.street = 'RIVER'
                 AND sp_or.player_name = o.opener

                LEFT JOIN street_meta sm_f
                  ON sm_f.hand_id = o.hand_id
                 AND sm_f.street = 'FLOP'

                LEFT JOIN street_meta sm_t
                  ON sm_t.hand_id = o.hand_id
                 AND sm_t.street = 'TURN'

                LEFT JOIN street_meta sm_r
                  ON sm_r.hand_id = o.hand_id
                 AND sm_r.street = 'RIVER'
            )

            SELECT *
            FROM flags
        """

        with self.connect() as con:
            raw_rows = con.execute(
                query,
                params,
            ).fetchall()

        columns = [
            "hand_id",
            "opener",
            "open_seq",
            "to_amount",
            "site",
            "stakes",
            "flop",
            "turn",
            "river",
            "position",
            "responders",
            "faced_three_bet",
            "got_call",
            "got_fold",
            "flop_cbet_made",
            "flop_fold_vs_cbet",
            "turn_barrel_made",
            "turn_fold_vs_barrel",
            "river_barrel_made",
            "river_fold_vs_barrel",
        ]

        result: list[dict[str, Any]] = []

        for raw in raw_rows:
            row = dict(zip(columns, raw))
            bb = self._parse_big_blind(
                str(row["stakes"] or "")
            )
            to_amount = self._float_or_none(
                row["to_amount"]
            )

            size_bb = (
                to_amount / bb
                if to_amount is not None
                and bb is not None
                and bb > 0
                else None
            )

            row["size_bb"] = size_bb
            row["size_bucket"] = self._size_bucket(
                size_bb
            )
            result.append(row)

        return result

    def _aggregate(
        self,
        rows: list[dict[str, Any]],
        minimum_sample: int,
    ) -> list[dict[str, Any]]:
        groups: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = {}

        for row in rows:
            key = (
                str(row["position"] or "OTHER"),
                str(row["size_bucket"]),
            )
            groups.setdefault(
                key,
                [],
            ).append(row)

        output: list[dict[str, Any]] = []

        for (position, bucket), items in groups.items():
            if len(items) < max(
                1,
                int(minimum_sample),
            ):
                continue

            opens = len(items)
            sizes = [
                float(item["size_bb"])
                for item in items
                if item["size_bb"] is not None
            ]

            preflop_fold = sum(
                1
                for item in items
                if bool(item["got_fold"])
                and not bool(item["got_call"])
                and not bool(item["faced_three_bet"])
            )
            preflop_call = sum(
                1
                for item in items
                if bool(item["got_call"])
                and not bool(item["faced_three_bet"])
            )
            preflop_3bet = sum(
                1
                for item in items
                if bool(item["faced_three_bet"])
            )

            flop_opp = sum(
                1
                for item in items
                if bool(item["flop_cbet_made"])
            )
            flop_fold = sum(
                1
                for item in items
                if bool(item["flop_fold_vs_cbet"])
            )

            turn_opp = sum(
                1
                for item in items
                if bool(item["turn_barrel_made"])
            )
            turn_fold = sum(
                1
                for item in items
                if bool(item["turn_fold_vs_barrel"])
            )

            river_opp = sum(
                1
                for item in items
                if bool(item["river_barrel_made"])
            )
            river_fold = sum(
                1
                for item in items
                if bool(item["river_fold_vs_barrel"])
            )

            row = {
                "position": position,
                "size_bucket": bucket,
                "opens": opens,
                "avg_size_bb": (
                    sum(sizes) / len(sizes)
                    if sizes
                    else 0.0
                ),
                "pool_fold_preflop": self._pct(
                    preflop_fold,
                    opens,
                ),
                "pool_call_preflop": self._pct(
                    preflop_call,
                    opens,
                ),
                "pool_3bet_preflop": self._pct(
                    preflop_3bet,
                    opens,
                ),
                "preflop_sample": opens,
                "flop_fold_vs_cbet": self._pct(
                    flop_fold,
                    flop_opp,
                ),
                "flop_sample": flop_opp,
                "turn_fold_vs_barrel": self._pct(
                    turn_fold,
                    turn_opp,
                ),
                "turn_sample": turn_opp,
                "river_fold_vs_barrel": self._pct(
                    river_fold,
                    river_opp,
                ),
                "river_sample": river_opp,
            }

            row["response_score"] = self._response_score(
                row
            )
            row["confidence"] = self._confidence(
                row
            )
            row["exploit_note"] = self._exploit_note(
                row
            )

            output.append(row)

        output.sort(
            key=lambda row: (
                self.POSITION_ORDER.get(
                    row["position"],
                    99,
                ),
                self.BUCKET_ORDER.get(
                    row["size_bucket"],
                    99,
                ),
            )
        )

        return output

    def _response_score(
        self,
        row: dict[str, Any],
    ) -> float:
        raw = (
            float(row["pool_fold_preflop"]) * 0.35
            + float(row["flop_fold_vs_cbet"]) * 0.30
            + float(row["turn_fold_vs_barrel"]) * 0.20
            + float(row["river_fold_vs_barrel"]) * 0.15
        )

        sample_weight = self._sample_weight(row)

        return raw * sample_weight + 50.0 * (
            1.0 - sample_weight
        )

    def _sample_weight(
        self,
        row: dict[str, Any],
    ) -> float:
        samples = [
            int(row["preflop_sample"]),
            int(row["flop_sample"]),
            int(row["turn_sample"]),
            int(row["river_sample"]),
        ]
        positive = [
            value
            for value in samples
            if value > 0
        ]

        if not positive:
            return 0.15

        minimum = min(positive)

        if minimum >= 500:
            return 1.0
        if minimum >= 200:
            return 0.85
        if minimum >= 100:
            return 0.70
        if minimum >= 50:
            return 0.55
        if minimum >= 20:
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

    def _exploit_note(
        self,
        row: dict[str, Any],
    ) -> str:
        notes: list[str] = []

        if float(row["pool_fold_preflop"]) >= 48:
            notes.append(
                "büyük open doğrudan fold üretiyor"
            )

        if float(row["pool_3bet_preflop"]) <= 10:
            notes.append(
                "pool az 3betliyor"
            )
        elif float(row["pool_3bet_preflop"]) >= 16:
            notes.append(
                "3bet baskısı yüksek"
            )

        if (
            float(row["flop_fold_vs_cbet"]) >= 52
            and int(row["flop_sample"]) >= 30
        ):
            notes.append(
                "flop c-bet baskısı kârlı"
            )

        if (
            float(row["turn_fold_vs_barrel"]) >= 48
            and int(row["turn_sample"]) >= 25
        ):
            notes.append(
                "turn barrel devam ettir"
            )

        if (
            float(row["river_fold_vs_barrel"]) >= 50
            and int(row["river_sample"]) >= 20
        ):
            notes.append(
                "river bluff fırsatı"
            )

        if row["confidence"] in {
            "Düşük",
            "Çok Düşük",
        }:
            notes.append(
                "sample uyarısı"
            )

        return (
            "; ".join(notes)
            if notes
            else "belirgin response leak yok"
        )

    def _best_bucket(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not rows:
            return {}

        return max(
            rows,
            key=lambda row: (
                float(row["response_score"]),
                int(row["opens"]),
            ),
        )

    def _summary(
        self,
        rows: list[dict[str, Any]],
    ) -> str:
        if not rows:
            return "Yeterli sample bulunamadı."

        best = self._best_bucket(rows)

        return (
            f"En yüksek response score: "
            f"{best['position']} {best['size_bucket']} "
            f"({best['response_score']:.0f}/100). "
            f"Preflop fold {best['pool_fold_preflop']:.1f}%, "
            f"call {best['pool_call_preflop']:.1f}%, "
            f"3bet {best['pool_3bet_preflop']:.1f}%."
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
