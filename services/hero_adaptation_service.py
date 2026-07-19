from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import re

import duckdb

from services.experiment_database_service import (
    ExperimentDatabaseService,
)


class HeroAdaptationService:
    def __init__(
        self,
        main_database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.main_database_path = str(
            Path(main_database_path)
        )
        self.experiment_service = (
            ExperimentDatabaseService(
                main_database_path
            )
        )

    def list_experiments(
        self,
    ) -> list[dict[str, Any]]:
        return self.experiment_service.list_experiments()

    def analyze(
        self,
        experiment_name: str,
        position: str = "",
        size_bucket: str = "",
        minimum_open_sample: int = 20,
        minimum_postflop_sample: int = 10,
    ) -> dict[str, Any]:
        record = self.experiment_service.get_experiment(
            experiment_name
        )

        if not record:
            raise ValueError(
                "Deney bulunamadı."
            )

        database_path = str(
            record["database_path"]
        )
        hero_name = str(
            record["hero_name"]
        )
        block_size = max(
            500,
            int(
                record.get("block_size")
                or 5000
            ),
        )

        if not Path(database_path).exists():
            raise FileNotFoundError(
                f"Deney database bulunamadı: "
                f"{database_path}"
            )

        rows = self._load_rows(
            database_path=database_path,
            hero_name=hero_name,
            block_size=block_size,
            position=position,
        )

        if size_bucket:
            rows = [
                row
                for row in rows
                if row["size_bucket"]
                == size_bucket
            ]

        blocks = self._aggregate(
            rows=rows,
            block_size=block_size,
            minimum_open_sample=max(
                1,
                int(minimum_open_sample),
            ),
            minimum_postflop_sample=max(
                1,
                int(
                    minimum_postflop_sample
                ),
            ),
        )

        pool_trend = self._pool_trend(blocks)
        hero_drift = self._hero_drift(blocks)
        adaptation_score = (
            self._adaptation_score(
                pool_trend,
                blocks,
            )
        )
        drift_score = self._drift_score(
            hero_drift,
            blocks,
        )

        return {
            "experiment": record,
            "blocks": blocks,
            "total_blocks": len(blocks),
            "hero_hands": sum(
                int(row["hero_hands"])
                for row in blocks
            ),
            "total_opens": sum(
                int(row["opens"])
                for row in blocks
            ),
            "pool_trend": pool_trend,
            "hero_drift": hero_drift,
            "adaptation_score": (
                adaptation_score
            ),
            "drift_score": drift_score,
            "status": self._status(
                adaptation_score,
                blocks,
            ),
            "summary": self._summary(
                adaptation_score,
                drift_score,
                pool_trend,
                hero_drift,
                blocks,
            ),
            "recommendations": (
                self._recommendations(
                    adaptation_score,
                    drift_score,
                    pool_trend,
                    hero_drift,
                    blocks,
                )
            ),
        }

    def _load_rows(
        self,
        database_path: str,
        hero_name: str,
        block_size: int,
        position: str,
    ) -> list[dict[str, Any]]:
        filters = [
            "hp.player_name = ?",
        ]
        params: list[Any] = [
            hero_name,
        ]

        if position:
            filters.append(
                "hp.position = ?"
            )
            params.append(position)

        where_sql = " AND ".join(
            filters
        )

        query = f"""
            WITH hero_hands AS (
                SELECT DISTINCT
                    hp.hand_id,
                    hp.player_name,
                    hp.position,
                    h.stakes,
                    h.played_at,
                    h.flop,
                    h.turn,
                    h.river,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            COALESCE(
                                CAST(
                                    h.played_at
                                    AS VARCHAR
                                ),
                                ''
                            ),
                            hp.hand_id
                    ) AS hero_hand_no
                FROM hand_players hp
                JOIN hands h
                  ON h.hand_id = hp.hand_id
                WHERE {where_sql}
            ),

            numbered AS (
                SELECT
                    *,
                    CAST(
                        FLOOR(
                            (hero_hand_no - 1)
                            / ?
                        ) + 1
                        AS BIGINT
                    ) AS block_no
                FROM hero_hands
            ),

            pf_raises AS (
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
                WHERE UPPER(
                    TRIM(a.street)
                ) = 'PREFLOP'
                  AND UPPER(
                    TRIM(a.action)
                  ) = 'RAISE'
            ),

            opens AS (
                SELECT
                    n.hand_id,
                    n.player_name,
                    r.sequence_no AS open_seq,
                    r.to_amount
                FROM numbered n
                JOIN pf_raises r
                  ON r.hand_id = n.hand_id
                 AND r.player_name =
                     n.player_name
                 AND r.raise_no = 1
            ),

            pf_after AS (
                SELECT
                    o.hand_id,
                    o.player_name,
                    MAX(
                        CASE
                            WHEN a.player_name
                                 <> o.player_name
                             AND UPPER(
                                 TRIM(a.action)
                             ) = 'RAISE'
                             AND a.sequence_no
                                 > o.open_seq
                            THEN 1
                            ELSE 0
                        END
                    ) AS got_3bet,
                    MAX(
                        CASE
                            WHEN a.player_name
                                 <> o.player_name
                             AND UPPER(
                                 TRIM(a.action)
                             ) = 'CALL'
                             AND a.sequence_no
                                 > o.open_seq
                            THEN 1
                            ELSE 0
                        END
                    ) AS got_call,
                    MAX(
                        CASE
                            WHEN a.player_name
                                 = o.player_name
                             AND UPPER(
                                 TRIM(a.action)
                             ) = 'FOLD'
                             AND a.sequence_no
                                 > o.open_seq
                            THEN 1
                            ELSE 0
                        END
                    ) AS hero_folded_after
                FROM opens o
                LEFT JOIN actions a
                  ON a.hand_id = o.hand_id
                GROUP BY
                    o.hand_id,
                    o.player_name
            ),

            street_player AS (
                SELECT
                    a.hand_id,
                    UPPER(
                        TRIM(a.street)
                    ) AS street,
                    a.player_name,
                    MAX(
                        CASE
                            WHEN UPPER(
                                TRIM(a.action)
                            ) IN ('BET', 'RAISE')
                            THEN 1
                            ELSE 0
                        END
                    ) AS aggressive,
                    MAX(
                        CASE
                            WHEN UPPER(
                                TRIM(a.action)
                            ) = 'FOLD'
                            THEN 1
                            ELSE 0
                        END
                    ) AS folded
                FROM actions a
                WHERE UPPER(
                    TRIM(a.street)
                ) IN (
                    'FLOP',
                    'TURN',
                    'RIVER'
                )
                GROUP BY
                    a.hand_id,
                    UPPER(
                        TRIM(a.street)
                    ),
                    a.player_name
            ),

            street_meta AS (
                SELECT
                    hand_id,
                    street,
                    COUNT(
                        DISTINCT player_name
                    ) AS players
                FROM street_player
                GROUP BY
                    hand_id,
                    street
            )

            SELECT
                n.hand_id,
                n.position,
                n.stakes,
                n.block_no,
                o.to_amount,

                CASE
                    WHEN o.hand_id IS NOT NULL
                    THEN 1 ELSE 0
                END AS opened,

                COALESCE(
                    pf.got_3bet,
                    0
                ) AS got_3bet,

                COALESCE(
                    pf.got_call,
                    0
                ) AS got_call,

                CASE
                    WHEN COALESCE(
                        pf.got_3bet,
                        0
                    ) = 1
                     AND COALESCE(
                        pf.hero_folded_after,
                        0
                    ) = 1
                    THEN 1
                    ELSE 0
                END AS folded_to_3bet,

                CASE
                    WHEN o.hand_id IS NOT NULL
                     AND COALESCE(
                        sm_f.players,
                        0
                    ) = 2
                    THEN 1
                    ELSE 0
                END AS flop_cbet_opp,

                CASE
                    WHEN o.hand_id IS NOT NULL
                     AND COALESCE(
                        sm_f.players,
                        0
                    ) = 2
                     AND own_f.aggressive = 1
                    THEN 1
                    ELSE 0
                END AS flop_cbet_made,

                CASE
                    WHEN own_f.aggressive = 1
                     AND n.turn IS NOT NULL
                     AND TRIM(
                         CAST(
                             n.turn AS VARCHAR
                         )
                     ) <> ''
                     AND COALESCE(
                         sm_t.players,
                         0
                     ) = 2
                    THEN 1
                    ELSE 0
                END AS turn_barrel_opp,

                CASE
                    WHEN own_f.aggressive = 1
                     AND n.turn IS NOT NULL
                     AND TRIM(
                         CAST(
                             n.turn AS VARCHAR
                         )
                     ) <> ''
                     AND COALESCE(
                         sm_t.players,
                         0
                     ) = 2
                     AND own_t.aggressive = 1
                    THEN 1
                    ELSE 0
                END AS turn_barrel_made,

                CASE
                    WHEN own_t.aggressive = 1
                     AND n.river IS NOT NULL
                     AND TRIM(
                         CAST(
                             n.river AS VARCHAR
                         )
                     ) <> ''
                     AND COALESCE(
                         sm_r.players,
                         0
                     ) = 2
                    THEN 1
                    ELSE 0
                END AS river_barrel_opp,

                CASE
                    WHEN own_t.aggressive = 1
                     AND n.river IS NOT NULL
                     AND TRIM(
                         CAST(
                             n.river AS VARCHAR
                         )
                     ) <> ''
                     AND COALESCE(
                         sm_r.players,
                         0
                     ) = 2
                     AND own_r.aggressive = 1
                    THEN 1
                    ELSE 0
                END AS river_barrel_made,

                CASE
                    WHEN n.flop IS NOT NULL
                     AND TRIM(
                         CAST(
                             n.flop AS VARCHAR
                         )
                     ) <> ''
                    THEN 1
                    ELSE 0
                END AS saw_flop,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM actions win_action
                        WHERE win_action.hand_id
                              = n.hand_id
                          AND win_action.player_name
                              = n.player_name
                          AND UPPER(
                              TRIM(
                                  win_action.action
                              )
                          ) = 'COLLECT'
                    )
                    THEN 1
                    ELSE 0
                END AS won_pot,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM actions sd
                        WHERE sd.hand_id
                              = n.hand_id
                          AND sd.player_name
                              = n.player_name
                          AND UPPER(
                              TRIM(sd.action)
                          ) IN ('SHOW', 'MUCK')
                    )
                    THEN 1
                    ELSE 0
                END AS went_showdown

            FROM numbered n

            LEFT JOIN opens o
              ON o.hand_id = n.hand_id
             AND o.player_name =
                 n.player_name

            LEFT JOIN pf_after pf
              ON pf.hand_id = n.hand_id
             AND pf.player_name =
                 n.player_name

            LEFT JOIN street_player own_f
              ON own_f.hand_id = n.hand_id
             AND own_f.street = 'FLOP'
             AND own_f.player_name =
                 n.player_name

            LEFT JOIN street_player own_t
              ON own_t.hand_id = n.hand_id
             AND own_t.street = 'TURN'
             AND own_t.player_name =
                 n.player_name

            LEFT JOIN street_player own_r
              ON own_r.hand_id = n.hand_id
             AND own_r.street = 'RIVER'
             AND own_r.player_name =
                 n.player_name

            LEFT JOIN street_meta sm_f
              ON sm_f.hand_id = n.hand_id
             AND sm_f.street = 'FLOP'

            LEFT JOIN street_meta sm_t
              ON sm_t.hand_id = n.hand_id
             AND sm_t.street = 'TURN'

            LEFT JOIN street_meta sm_r
              ON sm_r.hand_id = n.hand_id
             AND sm_r.street = 'RIVER'
        """

        with duckdb.connect(
            database_path,
            read_only=True,
        ) as con:
            raw = con.execute(
                query,
                params + [int(block_size)],
            ).fetchall()

        result: list[dict[str, Any]] = []

        for row in raw:
            (
                hand_id,
                position_value,
                stakes,
                block_no,
                to_amount,
                opened,
                got_3bet,
                got_call,
                folded_to_3bet,
                flop_cbet_opp,
                flop_cbet_made,
                turn_barrel_opp,
                turn_barrel_made,
                river_barrel_opp,
                river_barrel_made,
                saw_flop,
                won_pot,
                went_showdown,
            ) = row

            bb = self._parse_big_blind(
                str(stakes or "")
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
                    "position": str(
                        position_value or "OTHER"
                    ),
                    "block_no": int(
                        block_no
                    ),
                    "size_bb": size_bb,
                    "size_bucket": (
                        self._size_bucket(
                            size_bb
                        )
                    ),
                    "opened": bool(opened),
                    "got_3bet": bool(
                        got_3bet
                    ),
                    "got_call": bool(
                        got_call
                    ),
                    "folded_to_3bet": bool(
                        folded_to_3bet
                    ),
                    "flop_cbet_opp": bool(
                        flop_cbet_opp
                    ),
                    "flop_cbet_made": bool(
                        flop_cbet_made
                    ),
                    "turn_barrel_opp": bool(
                        turn_barrel_opp
                    ),
                    "turn_barrel_made": bool(
                        turn_barrel_made
                    ),
                    "river_barrel_opp": bool(
                        river_barrel_opp
                    ),
                    "river_barrel_made": bool(
                        river_barrel_made
                    ),
                    "saw_flop": bool(
                        saw_flop
                    ),
                    "won_pot": bool(
                        won_pot
                    ),
                    "went_showdown": bool(
                        went_showdown
                    ),
                }
            )

        return result

    def _aggregate(
        self,
        rows: list[dict[str, Any]],
        block_size: int,
        minimum_open_sample: int,
        minimum_postflop_sample: int,
    ) -> list[dict[str, Any]]:
        grouped: dict[
            int,
            list[dict[str, Any]],
        ] = defaultdict(list)

        for row in rows:
            grouped[
                int(row["block_no"])
            ].append(row)

        output: list[dict[str, Any]] = []
        previous: dict[str, Any] | None = None

        for block_no in sorted(grouped):
            items = grouped[block_no]

            hero_hands = len(items)

            open_items = [
                item
                for item in items
                if item["opened"]
            ]
            opens = len(open_items)

            size_values = [
                float(item["size_bb"])
                for item in open_items
                if item["size_bb"]
                is not None
            ]

            got_3bet = sum(
                1
                for item in open_items
                if item["got_3bet"]
            )
            got_call = sum(
                1
                for item in open_items
                if item["got_call"]
                and not item["got_3bet"]
            )
            pool_fold = max(
                0,
                opens
                - got_3bet
                - got_call,
            )

            folded_to_3bet = sum(
                1
                for item in open_items
                if item["folded_to_3bet"]
            )

            flop_opp = sum(
                1
                for item in items
                if item["flop_cbet_opp"]
            )
            flop_made = sum(
                1
                for item in items
                if item["flop_cbet_made"]
            )

            turn_opp = sum(
                1
                for item in items
                if item["turn_barrel_opp"]
            )
            turn_made = sum(
                1
                for item in items
                if item["turn_barrel_made"]
            )

            river_opp = sum(
                1
                for item in items
                if item["river_barrel_opp"]
            )
            river_made = sum(
                1
                for item in items
                if item["river_barrel_made"]
            )

            saw_flop = sum(
                1
                for item in items
                if item["saw_flop"]
            )
            wins_after_flop = sum(
                1
                for item in items
                if item["saw_flop"]
                and item["won_pot"]
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

            current: dict[str, Any] = {
                "block_no": block_no,
                "block_label": (
                    f"{(block_no - 1) * block_size + 1:,}"
                    f"–{block_no * block_size:,}"
                ),
                "hero_hands": hero_hands,
                "opens": opens,
                "open_frequency": self._pct(
                    opens,
                    hero_hands,
                ),
                "avg_open_size": (
                    sum(size_values)
                    / len(size_values)
                    if size_values
                    else 0.0
                ),
                "pool_fold": self._pct(
                    pool_fold,
                    opens,
                ),
                "pool_call": self._pct(
                    got_call,
                    opens,
                ),
                "pool_3bet": self._pct(
                    got_3bet,
                    opens,
                ),
                "fold_to_3bet": self._pct(
                    folded_to_3bet,
                    got_3bet,
                ),
                "f3b_sample": got_3bet,
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
                    wins_after_flop,
                    saw_flop,
                ),
                "wwsf_sample": saw_flop,
                "wtsd": self._pct(
                    showdown,
                    saw_flop,
                ),
                "wsd": self._pct(
                    showdown_wins,
                    showdown,
                ),
                "wsd_sample": showdown,
            }

            current["confidence"] = (
                self._confidence(
                    current,
                    minimum_open_sample,
                    minimum_postflop_sample,
                )
            )

            delta_keys = (
                "avg_open_size",
                "pool_fold",
                "pool_3bet",
                "fold_to_3bet",
                "flop_cbet",
                "turn_barrel",
                "river_barrel",
                "wwsf",
                "wtsd",
                "wsd",
            )

            for key in delta_keys:
                current[
                    f"delta_{key}"
                ] = (
                    float(current[key])
                    - float(previous[key])
                    if previous
                    is not None
                    else 0.0
                )

            output.append(current)
            previous = current

        return output

    def _pool_trend(
        self,
        blocks: list[dict[str, Any]],
    ) -> dict[str, float]:
        valid = self._reliable_blocks(
            blocks
        )

        if len(valid) < 2:
            return {
                "pool_fold": 0.0,
                "pool_call": 0.0,
                "pool_3bet": 0.0,
            }

        first = valid[0]
        last = valid[-1]

        return {
            key: (
                float(last[key])
                - float(first[key])
            )
            for key in (
                "pool_fold",
                "pool_call",
                "pool_3bet",
            )
        }

    def _hero_drift(
        self,
        blocks: list[dict[str, Any]],
    ) -> dict[str, float]:
        valid = self._reliable_blocks(
            blocks
        )

        keys = (
            "avg_open_size",
            "fold_to_3bet",
            "flop_cbet",
            "turn_barrel",
            "river_barrel",
            "wwsf",
            "wtsd",
            "wsd",
        )

        if len(valid) < 2:
            return {
                key: 0.0
                for key in keys
            }

        first = valid[0]
        last = valid[-1]

        return {
            key: (
                float(last[key])
                - float(first[key])
            )
            for key in keys
        }

    def _adaptation_score(
        self,
        trend: dict[str, float],
        blocks: list[dict[str, Any]],
    ) -> float:
        reliability = min(
            1.0,
            len(
                self._reliable_blocks(
                    blocks
                )
            )
            / 4.0,
        )

        raw = (
            max(
                0.0,
                -trend["pool_fold"],
            )
            * 2.2
            + max(
                0.0,
                trend["pool_3bet"],
            )
            * 2.8
            + max(
                0.0,
                trend["pool_call"],
            )
            * 1.4
        )

        return max(
            0.0,
            min(
                100.0,
                raw * reliability,
            ),
        )

    def _drift_score(
        self,
        drift: dict[str, float],
        blocks: list[dict[str, Any]],
    ) -> float:
        reliability = min(
            1.0,
            len(
                self._reliable_blocks(
                    blocks
                )
            )
            / 4.0,
        )

        raw = (
            abs(
                drift["avg_open_size"]
            )
            * 18.0
            + abs(
                drift["fold_to_3bet"]
            )
            * 1.2
            + abs(
                drift["flop_cbet"]
            )
            * 0.8
            + abs(
                drift["turn_barrel"]
            )
            * 0.7
            + abs(
                drift["river_barrel"]
            )
            * 0.6
            + abs(
                drift["wwsf"]
            )
            * 0.8
            + abs(
                drift["wtsd"]
            )
            * 0.5
            + abs(
                drift["wsd"]
            )
            * 0.6
        )

        return max(
            0.0,
            min(
                100.0,
                raw * reliability,
            ),
        )

    def _reliable_blocks(
        self,
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in blocks
            if row["confidence"]
            in {
                "Orta",
                "Yüksek",
            }
        ]

    def _confidence(
        self,
        row: dict[str, Any],
        minimum_open_sample: int,
        minimum_postflop_sample: int,
    ) -> str:
        if int(
            row["opens"]
        ) < minimum_open_sample:
            return "Çok Düşük"

        post_samples = [
            int(row["flop_sample"]),
            int(row["turn_sample"]),
            int(row["river_sample"]),
        ]

        valid_post = sum(
            1
            for value in post_samples
            if value
            >= minimum_postflop_sample
        )

        if (
            int(row["opens"])
            >= minimum_open_sample * 4
            and valid_post >= 2
        ):
            return "Yüksek"

        if (
            int(row["opens"])
            >= minimum_open_sample * 2
            and valid_post >= 1
        ):
            return "Orta"

        return "Düşük"

    def _status(
        self,
        score: float,
        blocks: list[dict[str, Any]],
    ) -> str:
        if len(
            self._reliable_blocks(
                blocks
            )
        ) < 2:
            return "Insufficient Sample"

        if score >= 65:
            return "Strong Adaptation"

        if score >= 35:
            return "Slight Adaptation"

        return "Stable"

    def _recommendations(
        self,
        adaptation_score: float,
        drift_score: float,
        pool_trend: dict[str, float],
        hero_drift: dict[str, float],
        blocks: list[dict[str, Any]],
    ) -> list[str]:
        notes: list[str] = []

        if len(
            self._reliable_blocks(
                blocks
            )
        ) < 2:
            return [
                "En az iki güvenilir 5K blok tamamlanmadan strateji değiştirme."
            ]

        if pool_trend["pool_3bet"] >= 5:
            notes.append(
                "Pool 3beti belirgin artıyor: büyük open branch'ini sıkılaştır veya 4bet/call savunmasını güçlendir."
            )

        if pool_trend["pool_fold"] <= -5:
            notes.append(
                "Pool openlarına daha az fold ediyor: en zayıf büyük-size openlarını çıkar."
            )

        if pool_trend["pool_call"] >= 5:
            notes.append(
                "Pool daha çok call ediyor: postflop value yoğunluğunu artır, otomatik c-beti azalt."
            )

        if hero_drift["fold_to_3bet"] >= 7:
            notes.append(
                "Hero fold-to-3bet yükseliyor: büyük sizing ile fazla dead money bırakıyor olabilirsin."
            )

        if (
            hero_drift["flop_cbet"] >= 8
            and hero_drift["turn_barrel"]
            <= -5
        ):
            notes.append(
                "Flop baskısı artarken turn devamı düşmüş: float exploitine açık olabilirsin."
            )

        if hero_drift["wwsf"] <= -4:
            notes.append(
                "WWSF düşüyor: pool daha iyi savunuyor veya hero fazla give-up yapıyor."
            )

        if hero_drift["wsd"] <= -5:
            notes.append(
                "W$SD düşüyor: river bluff/call kalitesini kontrol et."
            )

        if (
            adaptation_score < 35
            and drift_score < 35
        ):
            notes.append(
                "Şimdilik anlamlı adaptasyon yok; aynı A/B planını sürdür."
            )

        return notes[:6]

    def _summary(
        self,
        adaptation_score: float,
        drift_score: float,
        pool_trend: dict[str, float],
        hero_drift: dict[str, float],
        blocks: list[dict[str, Any]],
    ) -> str:
        if len(blocks) < 2:
            return (
                "İlk 5K blok tamamlanıyor. "
                "Karşılaştırma için en az iki blok gerekli."
            )

        return (
            f"Adaptation {adaptation_score:.0f}/100, "
            f"Hero Drift {drift_score:.0f}/100. "
            f"Pool Fold {pool_trend['pool_fold']:+.1f}, "
            f"Pool 3Bet {pool_trend['pool_3bet']:+.1f}, "
            f"Pool Call {pool_trend['pool_call']:+.1f}. "
            f"Hero F3B {hero_drift['fold_to_3bet']:+.1f}, "
            f"WWSF {hero_drift['wwsf']:+.1f}, "
            f"W$SD {hero_drift['wsd']:+.1f} puan."
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
                numerator
                / denominator
                * 100.0,
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
