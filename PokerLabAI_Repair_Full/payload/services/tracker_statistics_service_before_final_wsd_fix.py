from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class TrackerStatisticsService:
    """Shared tracker-style WWSF / WTSD / W$SD statistics engine."""

    POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB", "OTHER"]

    WIN_ACTIONS = {
        "COLLECT",
        "COLLECTED",
        "WIN",
        "WINS",
        "WON",
        "AWARD",
        "AWARDED",
    }

    SHOW_ACTIONS = {
        "SHOW",
        "SHOWS",
        "REVEAL",
        "REVEALS",
    }

    PREFLOP_CONTINUE_ACTIONS = {
        "CALL",
        "RAISE",
        "CHECK",
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
        clauses: list[str] = []
        params: list[Any] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
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

            elif mode in {"ALIAS", "COMPARE"}:
                if not self._table_exists(
                    con,
                    "player_aliases",
                ):
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
        entity_name: str = "",
        site: str = "",
        stakes: str = "",
    ) -> dict[str, Any]:
        mode = mode.upper()

        entity = self._analyze_scope(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )

        pool: dict[str, Any] = {}

        if mode == "COMPARE":
            pool = self._analyze_scope(
                mode="POOL",
                entity_name="",
                site=site,
                stakes=stakes,
            )

        return {
            "entity": entity,
            "pool": pool,
        }

    def validate(
        self,
        mode: str,
        entity_name: str,
        site: str = "",
        stakes: str = "",
    ) -> dict[str, Any]:
        result = self._analyze_scope(
            mode=mode.upper(),
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )

        result["diagnosis"] = self._diagnosis(result)

        return result

    def _analyze_scope(
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

        elif mode != "POOL":
            raise ValueError(
                "Mode PLAYER, ALIAS, COMPARE veya POOL olmalı."
            )

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        win_values = self._sql_values(
            self.WIN_ACTIONS
        )
        show_values = self._sql_values(
            self.SHOW_ACTIONS
        )
        continue_values = self._sql_values(
            self.PREFLOP_CONTINUE_ACTIONS
        )

        query = f"""
            WITH selected AS (
                SELECT DISTINCT
                    hp.hand_id,
                    hp.player_name,
                    COALESCE(
                        NULLIF(hp.position, ''),
                        'OTHER'
                    ) AS position,
                    h.flop
                FROM hand_players hp
                JOIN hands h
                  ON h.hand_id = hp.hand_id
                {where_sql}
            ),

            flags AS (
                SELECT
                    s.hand_id,
                    s.player_name,
                    s.position,

                    CASE
                        WHEN s.flop IS NOT NULL
                         AND TRIM(s.flop) <> ''
                        THEN 1 ELSE 0
                    END AS hand_reached_flop,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'PREFLOP'
                             AND UPPER(TRIM(a.action)) = 'FOLD'
                            THEN 1 ELSE 0
                        END
                    ) AS folded_preflop,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'PREFLOP'
                             AND UPPER(TRIM(a.action))
                                 IN ({continue_values})
                            THEN 1 ELSE 0
                        END
                    ) AS preflop_continue,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street))
                                 IN ('FLOP', 'TURN', 'RIVER')
                            THEN 1 ELSE 0
                        END
                    ) AS has_postflop_action,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'FLOP'
                            THEN 1 ELSE 0
                        END
                    ) AS has_flop_action,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'TURN'
                            THEN 1 ELSE 0
                        END
                    ) AS has_turn_action,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'RIVER'
                            THEN 1 ELSE 0
                        END
                    ) AS has_river_action,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.action))
                                 IN ({win_values})
                            THEN 1 ELSE 0
                        END
                    ) AS won_pot,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.action))
                                 IN ({show_values})
                            THEN 1 ELSE 0
                        END
                    ) AS showed_cards,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'FLOP'
                             AND UPPER(TRIM(a.action))
                                 IN ('BET', 'RAISE')
                            THEN 1 ELSE 0
                        END
                    ) AS flop_aggressive,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'TURN'
                             AND UPPER(TRIM(a.action))
                                 IN ('BET', 'RAISE')
                            THEN 1 ELSE 0
                        END
                    ) AS turn_aggressive,

                    MAX(
                        CASE
                            WHEN UPPER(TRIM(a.street)) = 'RIVER'
                             AND UPPER(TRIM(a.action))
                                 IN ('BET', 'RAISE')
                            THEN 1 ELSE 0
                        END
                    ) AS river_aggressive

                FROM selected s
                LEFT JOIN actions a
                  ON a.hand_id = s.hand_id
                 AND a.player_name = s.player_name
                GROUP BY
                    s.hand_id,
                    s.player_name,
                    s.position,
                    s.flop
            ),

            final AS (
                SELECT
                    *,

                    CASE
                        WHEN hand_reached_flop = 1
                         AND folded_preflop = 0
                         AND (
                            preflop_continue = 1
                            OR has_postflop_action = 1
                            OR showed_cards = 1
                            OR won_pot = 1
                         )
                        THEN 1 ELSE 0
                    END AS saw_flop

                FROM flags
            )

            SELECT
                hand_id,
                player_name,
                position,
                hand_reached_flop,
                folded_preflop,
                preflop_continue,
                has_flop_action,
                has_turn_action,
                has_river_action,
                won_pot,
                showed_cards,
                flop_aggressive,
                turn_aggressive,
                river_aggressive,
                saw_flop
            FROM final
        """

        with self.connect() as con:
            rows = con.execute(
                query,
                params,
            ).fetchall()

        records = [
            {
                "hand_id": str(row[0]),
                "player_name": str(row[1]),
                "position": str(row[2] or "OTHER"),
                "hand_reached_flop": bool(row[3]),
                "folded_preflop": bool(row[4]),
                "preflop_continue": bool(row[5]),
                "has_flop_action": bool(row[6]),
                "has_turn_action": bool(row[7]),
                "has_river_action": bool(row[8]),
                "won_pot": bool(row[9]),
                "went_showdown": bool(row[10]),
                "flop_aggressive": bool(row[11]),
                "turn_aggressive": bool(row[12]),
                "river_aggressive": bool(row[13]),
                "saw_flop": bool(row[14]),
            }
            for row in rows
        ]

        return self._aggregate(records)

    def _aggregate(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        overall = self._metrics(records)

        by_position: list[dict[str, Any]] = []

        for position in self.POSITIONS:
            subset = [
                record
                for record in records
                if record["position"] == position
            ]

            if not subset:
                continue

            metrics = self._metrics(subset)
            metrics["position"] = position
            metrics["impact_score"] = self._impact_score(
                metrics
            )
            by_position.append(metrics)

        by_position.sort(
            key=lambda item: (
                item["impact_score"],
                item["flop_seen"],
            ),
            reverse=True,
        )

        overall["by_position"] = by_position
        overall["strongest_position"] = (
            by_position[0]["position"]
            if by_position
            else "—"
        )

        overall["summary"] = self._summary(
            overall,
            by_position,
        )

        return overall

    def _metrics(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        player_hand_rows = len(records)
        distinct_hands = len(
            {
                record["hand_id"]
                for record in records
            }
        )

        preflop_folds = sum(
            record["folded_preflop"]
            for record in records
        )

        hands_reaching_flop = sum(
            record["hand_reached_flop"]
            for record in records
        )

        saw_flop = sum(
            record["saw_flop"]
            for record in records
        )

        player_flop_actions = sum(
            record["has_flop_action"]
            for record in records
        )

        player_turn_actions = sum(
            record["has_turn_action"]
            for record in records
        )

        player_river_actions = sum(
            record["has_river_action"]
            for record in records
        )

        pot_wins = sum(
            record["won_pot"]
            for record in records
        )

        saw_flop_and_won = sum(
            record["saw_flop"]
            and record["won_pot"]
            for record in records
        )

        showdown = sum(
            record["went_showdown"]
            for record in records
        )

        showdown_wins = sum(
            record["went_showdown"]
            and record["won_pot"]
            for record in records
        )

        flop_aggressive = sum(
            record["saw_flop"]
            and record["flop_aggressive"]
            for record in records
        )

        turn_aggressive = sum(
            record["saw_flop"]
            and record["turn_aggressive"]
            for record in records
        )

        river_aggressive = sum(
            record["saw_flop"]
            and record["river_aggressive"]
            for record in records
        )

        result = {
            "hands": player_hand_rows,
            "player_hand_rows": player_hand_rows,
            "distinct_hands": distinct_hands,
            "preflop_folds": int(preflop_folds),
            "hands_reaching_flop": int(
                hands_reaching_flop
            ),
            "flop_seen": int(saw_flop),
            "saw_flop": int(saw_flop),
            "player_flop_actions": int(
                player_flop_actions
            ),
            "player_turn_actions": int(
                player_turn_actions
            ),
            "player_river_actions": int(
                player_river_actions
            ),
            "pot_wins": int(pot_wins),
            "saw_flop_and_won": int(
                saw_flop_and_won
            ),
            "showdown": int(showdown),
            "showdown_wins": int(
                showdown_wins
            ),
            "wwsf": self._pct(
                saw_flop_and_won,
                saw_flop,
            ),
            "wtsd": self._pct(
                showdown,
                saw_flop,
            ),
            "wsd": self._pct(
                showdown_wins,
                showdown,
            ),
            "pot_won": self._pct(
                pot_wins,
                player_hand_rows,
            ),
            "preflop_fold_rate": self._pct(
                preflop_folds,
                player_hand_rows,
            ),
            "flop_seen_rate": self._pct(
                saw_flop,
                player_hand_rows,
            ),
            "flop_aggression_reach": self._pct(
                flop_aggressive,
                saw_flop,
            ),
            "turn_aggression_reach": self._pct(
                turn_aggressive,
                saw_flop,
            ),
            "river_aggression_reach": self._pct(
                river_aggressive,
                saw_flop,
            ),
        }

        return result

    def _diagnosis(
        self,
        result: dict[str, Any],
    ) -> list[str]:
        notes: list[str] = []

        if result["pot_wins"] == 0:
            notes.append(
                "COLLECT/WIN aksiyonu bulunamadı."
            )

        if result["showdown"] == 0:
            notes.append(
                "SHOW aksiyonu bulunamadı."
            )

        if (
            result["player_flop_actions"]
            > result["saw_flop"]
        ):
            notes.append(
                "Flop aksiyonu saw-flop sayısından yüksek; "
                "street sınıflandırmasını kontrol et."
            )

        if result["flop_seen_rate"] < 15:
            notes.append(
                "Flop seen oranı çok düşük; parserdaki eksik "
                "preflop aksiyonları kontrol edilmeli."
            )

        if result["wwsf"] < 35:
            notes.append(
                "WWSF hâlâ düşük. Kazanan adı ile player_name "
                "eşleşmesi veya eksik collect satırları incelenmeli."
            )

        if not notes:
            notes.append(
                "Tracker sayaçları temel olarak tutarlı görünüyor."
            )

        return notes

    def _impact_score(
        self,
        metrics: dict[str, Any],
    ) -> float:
        sample_weight = min(
            1.0,
            float(metrics["flop_seen"]) / 5000.0,
        )

        return (
            float(metrics["wwsf"]) * 0.45
            + float(metrics["wsd"]) * 0.35
            + (100.0 - abs(
                float(metrics["wtsd"]) - 27.0
            )) * 0.20
        ) * sample_weight

    def _summary(
        self,
        overall: dict[str, Any],
        by_position: list[dict[str, Any]],
    ) -> str:
        if overall["flop_seen"] == 0:
            return "Tracker tanımına göre flop gören el bulunamadı."

        text = (
            f"WWSF {overall['wwsf']:.2f}, "
            f"WTSD {overall['wtsd']:.2f}, "
            f"W$SD {overall['wsd']:.2f}."
        )

        if by_position:
            top = by_position[0]

            text += (
                f" En güçlü örnek-ağırlıklı pozisyon "
                f"{top['position']}: WWSF {top['wwsf']:.2f}, "
                f"WTSD {top['wtsd']:.2f}, "
                f"W$SD {top['wsd']:.2f}."
            )

        return text

    def _sql_values(
        self,
        values: set[str],
    ) -> str:
        return ", ".join(
            f"'{value}'"
            for value in sorted(values)
        )

    def _table_exists(
        self,
        con: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> bool:
        return bool(
            con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_name = ?
                """,
                [table_name],
            ).fetchone()[0]
        )

    def _pct(
        self,
        numerator: int,
        denominator: int,
    ) -> float:
        return (
            numerator / denominator * 100.0
            if denominator
            else 0.0
        )
