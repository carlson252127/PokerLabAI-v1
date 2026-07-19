from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import math
import re

import duckdb

from services.core_analytics_engine import CoreAnalyticsEngine
from services.research_source_service import ResearchSourceService


class SizeBoardStrategyService:
    POSITION_ORDER = CoreAnalyticsEngine.POSITION_ORDER

    BUCKET_ORDER = {
        **CoreAnalyticsEngine.BUCKET_ORDER,
        "Small ≤2.3x": 0,
        "Medium 2.4–3.1x": 1,
        "Large ≥3.2x": 2,
        "Unknown": 99,
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
        self.research_sources = ResearchSourceService(self.database_path)

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
        entities = self.research_sources.list_entities(
            mode=mode,
            site=site,
            stakes=stakes,
            minimum_hands=minimum_hands,
            limit=limit,
        )
        return [(item.key, item.label, item.hands) for item in entities]

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
            detailed_texture = self._texture_family(
                str(row.get("flop") or "")
            )
            simple_texture = self._simple_flop_family(
                str(row.get("flop") or "")
            )
            turn_transition = self._turn_transition(
                str(row.get("flop") or ""),
                str(row.get("turn") or ""),
            )

            row["detailed_texture"] = detailed_texture
            row["simple_texture"] = simple_texture
            row["turn_transition"] = turn_transition
            row["study_size_bucket"] = self._study_size_bucket(
                row.get("size_bb")
            )

            active_texture = (
                detailed_texture
                if normalized_view == "DETAIL"
                else simple_texture
            )
            if normalized_street == "TURN":
                active_texture = (
                    f"{simple_texture} › {turn_transition}"
                    if normalized_view != "DETAIL"
                    else f"{detailed_texture} › {turn_transition}"
                )

            if texture_filter and active_texture != texture_filter:
                continue
            if turn_filter and turn_transition != turn_filter:
                continue

            row["texture"] = active_texture
            row["size_bucket_active"] = (
                row["size_bucket"]
                if normalized_view == "DETAIL"
                else row["study_size_bucket"]
            )
            enriched.append(row)

        grouped = self._aggregate(
            enriched,
            minimum_sample,
        )

        return {
            "rows": grouped,
            "summary": self._summary(grouped),
            "evidence": self._evidence_summary(grouped),
            "strongest_difference": self._strongest_difference(
                grouped
            ),
            "view_mode": normalized_view,
            "street_mode": normalized_street,
            "actionable_groups": sum(
                1 for item in grouped
                if item.get("confidence") in {"Orta", "Yüksek", "Çok Yüksek"}
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
            position_values = CoreAnalyticsEngine.position_sql_values(position)
            placeholders = ", ".join("?" for _ in position_values)
            filters.append(
                f"UPPER(TRIM(hp.position)) IN ({placeholders})"
            )
            params.extend(position_values)

        source_sql, source_params = self.research_sources.source_condition(
            mode=mode,
            entity_key=entity_name,
            player_column="hp.player_name",
        )
        filters.append(source_sql)
        params.extend(source_params)

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

            action_pot AS (
                SELECT
                    a.hand_id,
                    a.sequence_no,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    UPPER(TRIM(a.action)) AS action,
                    COALESCE(a.amount, 0.0) AS amount,
                    SUM(
                        CASE
                            WHEN UPPER(TRIM(a.action)) IN (
                                'POST_ANTE', 'POST_SB', 'POST_BB',
                                'CALL', 'BET', 'RAISE'
                            )
                            THEN COALESCE(a.amount, 0.0)
                            ELSE 0.0
                        END
                    ) OVER (
                        PARTITION BY a.hand_id
                        ORDER BY a.sequence_no
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ) AS pot_before
                FROM actions a
            ),

            first_aggressive AS (
                SELECT
                    hand_id,
                    street,
                    player_name,
                    sequence_no,
                    amount,
                    pot_before,
                    CASE
                        WHEN COALESCE(pot_before, 0.0) > 0
                        THEN amount / pot_before * 100.0
                        ELSE NULL
                    END AS size_pct,
                    ROW_NUMBER() OVER (
                        PARTITION BY hand_id, street, player_name
                        ORDER BY sequence_no
                    ) AS aggressive_no
                FROM action_pot
                WHERE street IN ('FLOP', 'TURN', 'RIVER')
                  AND action IN ('BET', 'RAISE')
                  AND amount > 0
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

            flags AS (
                SELECT
                    o.*,

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
                    END AS went_showdown,

                    CASE
                        WHEN fa_f.aggressive_no = 1
                        THEN fa_f.size_pct
                        ELSE NULL
                    END AS flop_bet_size_pct,

                    CASE
                        WHEN fa_t.aggressive_no = 1
                        THEN fa_t.size_pct
                        ELSE NULL
                    END AS turn_bet_size_pct,

                    CASE
                        WHEN fa_r.aggressive_no = 1
                        THEN fa_r.size_pct
                        ELSE NULL
                    END AS river_bet_size_pct

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

                LEFT JOIN first_aggressive fa_f
                  ON fa_f.hand_id = o.hand_id
                 AND fa_f.street = 'FLOP'
                 AND fa_f.player_name = o.opener
                 AND fa_f.aggressive_no = 1

                LEFT JOIN first_aggressive fa_t
                  ON fa_t.hand_id = o.hand_id
                 AND fa_t.street = 'TURN'
                 AND fa_t.player_name = o.opener
                 AND fa_t.aggressive_no = 1

                LEFT JOIN first_aggressive fa_r
                  ON fa_r.hand_id = o.hand_id
                 AND fa_r.street = 'RIVER'
                 AND fa_r.player_name = o.opener
                 AND fa_r.aggressive_no = 1

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
                flop_bet_size_pct,
                turn_bet_size_pct,
                river_bet_size_pct
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
                flop_bet_size_pct,
                turn_bet_size_pct,
                river_bet_size_pct,
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
                    "position": CoreAnalyticsEngine.normalize_position(position_value),
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
                    "flop_bet_size_pct": self._valid_size_pct(
                        flop_bet_size_pct
                    ),
                    "turn_bet_size_pct": self._valid_size_pct(
                        turn_bet_size_pct
                    ),
                    "river_bet_size_pct": self._valid_size_pct(
                        river_bet_size_pct
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
                    row.get("size_bucket_active", row["size_bucket"]),
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

            flop_size_stats = self._size_statistics(
                [
                    item.get("flop_bet_size_pct")
                    for item in items
                    if item["flop_cbet_made"]
                ]
            )
            turn_size_stats = self._size_statistics(
                [
                    item.get("turn_bet_size_pct")
                    for item in items
                    if item["turn_barrel_made"]
                ]
            )
            river_size_stats = self._size_statistics(
                [
                    item.get("river_bet_size_pct")
                    for item in items
                    if item["river_barrel_made"]
                ]
            )

            board_counts = Counter(
                self._normalize_flop(item.get("flop"))
                for item in items
                if self._normalize_flop(item.get("flop"))
            )
            representative_boards = [
                {"board": board, "hands": count}
                for board, count in board_counts.most_common(5)
            ]
            representative_board = (
                representative_boards[0]["board"]
                if representative_boards
                else ""
            )
            representative_board_hands = (
                representative_boards[0]["hands"]
                if representative_boards
                else 0
            )

            row = {
                "position": position,
                "texture": texture,
                "size_bucket": bucket,
                "hands": len(items),
                "representative_board": representative_board,
                "representative_board_hands": representative_board_hands,
                "representative_boards": representative_boards,
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
                "flop_avg_bet_pct": flop_size_stats["average"],
                "flop_main_size": flop_size_stats["main"],
                "flop_size_distribution": flop_size_stats["distribution"],
                "flop_size_sample": flop_size_stats["sample"],
                "turn_avg_bet_pct": turn_size_stats["average"],
                "turn_main_size": turn_size_stats["main"],
                "turn_size_distribution": turn_size_stats["distribution"],
                "turn_size_sample": turn_size_stats["sample"],
                "river_avg_bet_pct": river_size_stats["average"],
                "river_main_size": river_size_stats["main"],
                "river_size_distribution": river_size_stats["distribution"],
                "river_size_sample": river_size_stats["sample"],
                "wwsf": self._pct(
                    wins,
                    saw_flop,
                ),
                "wwsf_sample": saw_flop,
                "wsd": self._pct(
                    showdown_wins,
                    showdown,
                ),
                "wsd_sample": showdown,
            }

            row["flop_freq_size"] = self._frequency_size_text(
                row["flop_cbet"], row["flop_avg_bet_pct"]
            )
            row["turn_freq_size"] = self._frequency_size_text(
                row["turn_barrel"], row["turn_avg_bet_pct"]
            )
            row["river_freq_size"] = self._frequency_size_text(
                row["river_barrel"], row["river_avg_bet_pct"]
            )
            row["size_dna"] = (
                f"F {row['flop_main_size']}"
                f" → T {row['turn_main_size']}"
                f" → R {row['river_main_size']}"
            )
            row["strategy_vector"] = (
                f"F {row['flop_freq_size']}"
                f" → T {row['turn_freq_size']}"
                f" → R {row['river_freq_size']}"
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

    @staticmethod
    def _normalize_flop(value: Any) -> str:
        """
        Veritabanındaki farklı board biçimlerini ortak formata çevirir.

        Desteklenen örnekler:
        - Ah Kd 7c
        - [Ah, Kd, 7c]
        - AhKd7c
        - A♥ K♦ 7♣
        - 10h 9s 8d
        """
        text = str(value or "").strip()
        if not text:
            return ""

        # Unicode suit sembollerini standart harflere çevir.
        suit_map = {
            "♠": "s",
            "♥": "h",
            "♦": "d",
            "♣": "c",
        }
        for symbol, suit in suit_map.items():
            text = text.replace(symbol, suit)

        # Bazı kaynaklarda onluk kart "10" olarak tutulabilir.
        text = re.sub(r"(?i)10(?=[shdc])", "T", text)

        cards = re.findall(
            r"([2-9TJQKA])\s*([shdc])",
            text,
            flags=re.IGNORECASE,
        )

        # JSON/list/ayraçlı veya tamamen kompakt değerler için ikinci geçiş.
        if len(cards) < 3:
            compact = re.sub(
                r"[^2-9TJQKAshdc]",
                "",
                text,
                flags=re.IGNORECASE,
            )
            cards = re.findall(
                r"([2-9TJQKA])([shdc])",
                compact,
                flags=re.IGNORECASE,
            )

        if len(cards) < 3:
            return ""

        return " ".join(
            f"{rank.upper()}{suit.lower()}"
            for rank, suit in cards[:3]
        )

    @staticmethod
    def _valid_size_pct(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed) or parsed <= 0 or parsed > 500:
            return None
        return parsed

    @staticmethod
    def _size_label(value: float) -> str:
        if value <= 27.5:
            return "≤25%"
        if value <= 40.0:
            return "33%"
        if value <= 62.5:
            return "50%"
        if value <= 87.5:
            return "75%"
        if value <= 112.5:
            return "100%"
        if value <= 162.5:
            return "150%"
        return ">150%"

    def _size_statistics(
        self,
        values: list[Any],
    ) -> dict[str, Any]:
        clean = [
            parsed
            for value in values
            if (parsed := self._valid_size_pct(value)) is not None
        ]
        if not clean:
            return {
                "average": 0.0,
                "main": "—",
                "distribution": {},
                "sample": 0,
            }

        counts: dict[str, int] = defaultdict(int)
        for value in clean:
            counts[self._size_label(value)] += 1

        ordered_labels = [
            "≤25%", "33%", "50%", "75%",
            "100%", "150%", ">150%",
        ]
        distribution = {
            label: round(counts.get(label, 0) / len(clean) * 100.0, 1)
            for label in ordered_labels
            if counts.get(label, 0) > 0
        }
        main = max(
            ordered_labels,
            key=lambda label: (counts.get(label, 0), -ordered_labels.index(label)),
        )
        return {
            "average": sum(clean) / len(clean),
            "main": main,
            "distribution": distribution,
            "sample": len(clean),
        }

    @staticmethod
    def _frequency_size_text(
        frequency: float,
        average_size: float,
    ) -> str:
        if average_size <= 0:
            return f"{frequency:.1f}% / —"
        return f"{frequency:.1f}% / {average_size:.1f}%"

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


    def _extract_cards(self, board: str) -> list[tuple[str, str]]:
        text = str(board or "").upper()
        cards = re.findall(r"([2-9TJQKA])([CDHS])", text)
        if cards:
            return cards
        compact = re.sub(r"[^2-9TJQKACDHS]", "", text)
        return re.findall(r"([2-9TJQKA])([CDHS])", compact)

    def _simple_flop_family(self, flop: str) -> str:
        cards = self._extract_cards(flop)[:3]
        if len(cards) != 3:
            return "Unknown"

        ranks = [self.RANK_VALUE[r] for r, _s in cards]
        suits = [s for _r, s in cards]
        unique_ranks = len(set(ranks))
        suit_count = max(suits.count(s) for s in set(suits))

        if unique_ranks == 1:
            return "Trips"
        if unique_ranks == 2:
            paired_rank = max(r for r in set(ranks) if ranks.count(r) == 2)
            return "Paired High" if paired_rank >= 10 else "Paired Low"
        if suit_count == 3:
            return "Monotone High" if max(ranks) >= 11 else "Monotone Low"

        ordered = sorted(set(ranks))
        span = ordered[-1] - ordered[0]
        gaps = [ordered[i+1] - ordered[i] for i in range(len(ordered)-1)]
        connected = span <= 5 and max(gaps) <= 3
        dynamic = connected or suit_count == 2
        high = max(ranks)

        if high == 14:
            return "A-high Dynamic" if dynamic else "A-high Dry"
        if high >= 11:
            return "K/Q/J-high Dynamic" if dynamic else "K/Q/J-high Dry"
        if high >= 9:
            return "Mid Connected" if connected else "Mid Dry"
        return "Low Connected" if connected else "Low Dry"

    def _turn_transition(self, flop: str, turn: str) -> str:
        flop_cards = self._extract_cards(flop)[:3]
        turn_cards = self._extract_cards(turn)
        if len(flop_cards) != 3 or not turn_cards:
            return "No Turn"
        turn_card = turn_cards[-1]
        tr, ts = turn_card
        trv = self.RANK_VALUE[tr]
        flop_ranks = [self.RANK_VALUE[r] for r, _s in flop_cards]
        flop_suits = [s for _r, s in flop_cards]

        pair = trv in flop_ranks
        flush_completed = flop_suits.count(ts) >= 2
        flush_added = (not flush_completed and max(flop_suits.count(s) for s in set(flop_suits)) == 1)

        before = sorted(set(flop_ranks))
        after = sorted(set(flop_ranks + [trv]))
        def straight_strength(vals: list[int]) -> int:
            expanded=set(vals)
            if 14 in expanded:
                expanded.add(1)
            best=0
            for start in range(1,11):
                best=max(best, len(expanded.intersection(range(start,start+5))))
            return best
        before_s=straight_strength(before)
        after_s=straight_strength(after)
        straight_completed = after_s >= 4 and before_s < 4
        straight_added = after_s > before_s and after_s >= 3

        dynamic_count = sum([flush_completed or flush_added, straight_completed or straight_added, pair])
        if dynamic_count >= 2 and not pair:
            return "Combo Dynamic"
        if flush_completed:
            return "Flush Completed"
        if straight_completed:
            return "Straight Completed"
        if pair:
            return "Board Pair"
        if flush_added:
            return "Flush Draw Added"
        if straight_added:
            return "Straight Draw Added"
        if trv > max(flop_ranks):
            return "Overcard"
        return "Blank"

    def _study_size_bucket(self, size_bb: float | None) -> str:
        if size_bb is None:
            return "Unknown"
        if size_bb <= 2.35:
            return "Small ≤2.3x"
        if size_bb <= 3.15:
            return "Medium 2.4–3.1x"
        return "Large ≥3.2x"

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
