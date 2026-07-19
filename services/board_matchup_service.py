from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import math
import re

import duckdb

from services.analytics_cache import AnalyticsCache


class BoardMatchupService:
    """Compare selected bot-group c-bets with bot-free human-pool c-bets and responses."""

    STREET_ORDER = {"FLOP": 0, "TURN": 1, "RIVER": 2}
    POSITION_ORDER = {"UTG": 0, "MP": 1, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4, "BB": 5, "?": 99}
    RANK_VALUE = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                  "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))
        self.cache = AnalyticsCache.shared(self.database_path)

    def connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(self.database_path, read_only=True)
        con.execute("PRAGMA threads=4")
        return con

    def bot_groups(self) -> list[tuple[str, int]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT bg.name, COUNT(DISTINCT hp.hand_id) AS hands
                FROM bot_groups bg
                LEFT JOIN bot_group_members bgm ON bgm.group_id = bg.group_id
                LEFT JOIN hand_players hp
                  ON LOWER(TRIM(hp.player_name)) = LOWER(TRIM(bgm.player_name))
                GROUP BY bg.name
                ORDER BY hands DESC, LOWER(bg.name)
                """
            ).fetchall()
        return [(str(name), int(hands or 0)) for name, hands in rows]

    def sites(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                """SELECT DISTINCT TRIM(site) FROM hands
                   WHERE site IS NOT NULL AND TRIM(site) <> '' ORDER BY 1"""
            ).fetchall()
        return [str(row[0]) for row in rows]

    def stakes(self, site: str = "") -> list[str]:
        with self.connect() as con:
            if site:
                rows = con.execute(
                    """SELECT DISTINCT TRIM(stakes) FROM hands
                       WHERE site = ? AND stakes IS NOT NULL AND TRIM(stakes) <> '' ORDER BY 1""",
                    [site],
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT DISTINCT TRIM(stakes) FROM hands
                       WHERE stakes IS NOT NULL AND TRIM(stakes) <> '' ORDER BY 1"""
                ).fetchall()
        return [str(row[0]) for row in rows]

    def analyze(
        self,
        bot_group: str,
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 50,
    ) -> dict[str, Any]:
        key = self.cache.make_key(
            "board_matchup",
            bot_group=bot_group, site=site, stakes=stakes, position=position,
            minimum_sample=int(minimum_sample),
        )
        return self.cache.get_or_compute(
            key,
            lambda: self._analyze_uncached(
                bot_group=bot_group, site=site, stakes=stakes,
                position=position, minimum_sample=minimum_sample,
            ),
        )

    def _analyze_uncached(
        self,
        bot_group: str,
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 50,
    ) -> dict[str, Any]:
        if not bot_group:
            raise ValueError("Bot grubu seçilmedi.")

        minimum_sample = max(1, int(minimum_sample))

        hand_filters = [
            "h.flop IS NOT NULL",
            "TRIM(h.flop) <> ''",
        ]
        params: list[Any] = [bot_group]

        if site:
            hand_filters.append("h.site = ?")
            params.append(site)

        if stakes:
            hand_filters.append("h.stakes = ?")
            params.append(stakes)

        position_sql = ""
        if position:
            position_sql = (
                "AND UPPER(TRIM(hp.position)) = UPPER(TRIM(?))"
            )
            params.append(position)

        hand_where_sql = " AND ".join(hand_filters)

        query = f"""
        WITH selected_bots AS (
            SELECT DISTINCT LOWER(TRIM(bgm.player_name)) AS player_key
            FROM bot_group_members bgm
            JOIN bot_groups bg
              ON bg.group_id = bgm.group_id
            WHERE bg.name = ?
              AND bgm.player_name IS NOT NULL
              AND TRIM(bgm.player_name) <> ''
        ),

        all_bots AS (
            SELECT DISTINCT LOWER(TRIM(player_name)) AS player_key
            FROM bot_group_members
            WHERE player_name IS NOT NULL
              AND TRIM(player_name) <> ''
        ),

        eligible_hands AS (
            SELECT
                h.hand_id,
                h.flop,
                h.turn,
                h.river
            FROM hands h
            WHERE {hand_where_sql}
        ),

        preflop_raises AS (
            SELECT
                a.hand_id,
                a.player_name,
                a.sequence_no,
                ROW_NUMBER() OVER (
                    PARTITION BY a.hand_id
                    ORDER BY a.sequence_no
                ) AS raise_no
            FROM actions a
            JOIN eligible_hands eh
              ON eh.hand_id = a.hand_id
            WHERE UPPER(TRIM(a.street)) = 'PREFLOP'
              AND UPPER(TRIM(a.action)) = 'RAISE'
        ),

        opens AS (
            SELECT
                r.hand_id,
                r.player_name AS opener,
                hp.position,
                eh.flop,
                eh.turn,
                eh.river,
                CASE
                    WHEN sb.player_key IS NOT NULL THEN 'BOT'
                    ELSE 'HUMAN'
                END AS cohort
            FROM preflop_raises r
            JOIN eligible_hands eh
              ON eh.hand_id = r.hand_id
            JOIN hand_players hp
              ON hp.hand_id = r.hand_id
             AND LOWER(TRIM(hp.player_name)) = LOWER(TRIM(r.player_name))
            LEFT JOIN selected_bots sb
              ON sb.player_key = LOWER(TRIM(r.player_name))
            LEFT JOIN all_bots ab
              ON ab.player_key = LOWER(TRIM(r.player_name))
            WHERE r.raise_no = 1
              {position_sql}
              AND (
                    sb.player_key IS NOT NULL
                    OR ab.player_key IS NULL
              )
        ),

        relevant_actions AS (
            SELECT
                a.hand_id,
                a.player_name,
                a.sequence_no,
                UPPER(TRIM(a.street)) AS street,
                UPPER(TRIM(a.action)) AS action,
                COALESCE(a.amount, 0.0) AS amount
            FROM actions a
            JOIN (
                SELECT DISTINCT hand_id
                FROM opens
            ) oh
              ON oh.hand_id = a.hand_id
        ),

        action_pot AS (
            SELECT
                ra.*,
                SUM(
                    CASE
                        WHEN ra.action IN (
                            'POST_ANTE', 'POST_SB', 'POST_BB',
                            'CALL', 'BET', 'RAISE'
                        )
                        THEN ra.amount
                        ELSE 0.0
                    END
                ) OVER (
                    PARTITION BY ra.hand_id
                    ORDER BY ra.sequence_no
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS pot_before
            FROM relevant_actions ra
        ),

        streets AS (
            SELECT
                hand_id, opener, flop, cohort, 'FLOP' AS street
            FROM opens

            UNION ALL

            SELECT
                hand_id, opener, flop, cohort, 'TURN' AS street
            FROM opens
            WHERE turn IS NOT NULL
              AND TRIM(turn) <> ''

            UNION ALL

            SELECT
                hand_id, opener, flop, cohort, 'RIVER' AS street
            FROM opens
            WHERE river IS NOT NULL
              AND TRIM(river) <> ''
        ),

        actor_actions AS (
            SELECT
                s.hand_id,
                s.opener,
                s.flop,
                s.cohort,
                s.street,
                ap.action AS actor_action,
                ap.sequence_no AS actor_sequence,
                ap.amount,
                COALESCE(ap.pot_before, 0.0) AS pot_before,
                ROW_NUMBER() OVER (
                    PARTITION BY s.hand_id, s.street
                    ORDER BY ap.sequence_no
                ) AS actor_no
            FROM streets s
            JOIN action_pot ap
              ON ap.hand_id = s.hand_id
             AND ap.street = s.street
             AND LOWER(TRIM(ap.player_name)) = LOWER(TRIM(s.opener))
            WHERE ap.action IN (
                'CHECK', 'BET', 'RAISE', 'FOLD', 'CALL'
            )
        ),

        opportunities AS (
            SELECT
                aa.*,
                CASE
                    WHEN aa.actor_action IN ('BET', 'RAISE')
                    THEN 1 ELSE 0
                END AS cbet,
                CASE
                    WHEN aa.actor_action IN ('BET', 'RAISE')
                     AND aa.pot_before > 0
                    THEN 100.0 * aa.amount / aa.pot_before
                    ELSE NULL
                END AS size_pct
            FROM actor_actions aa
            WHERE aa.actor_no = 1
              AND NOT EXISTS (
                    SELECT 1
                    FROM relevant_actions prior
                    WHERE prior.hand_id = aa.hand_id
                      AND prior.street = aa.street
                      AND prior.sequence_no < aa.actor_sequence
                      AND LOWER(TRIM(prior.player_name))
                          <> LOWER(TRIM(aa.opener))
                      AND prior.action IN ('BET', 'RAISE')
              )
        ),

        responses AS (
            SELECT
                o.hand_id,
                o.street,
                o.actor_sequence,
                ra.action AS response,
                CASE
                    WHEN ab.player_key IS NULL THEN 'HUMAN'
                    ELSE 'BOT'
                END AS responder_cohort,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        o.hand_id,
                        o.street,
                        o.actor_sequence
                    ORDER BY ra.sequence_no
                ) AS response_no
            FROM opportunities o
            JOIN relevant_actions ra
              ON ra.hand_id = o.hand_id
             AND ra.street = o.street
             AND ra.sequence_no > o.actor_sequence
             AND LOWER(TRIM(ra.player_name))
                 <> LOWER(TRIM(o.opener))
            LEFT JOIN all_bots ab
              ON ab.player_key = LOWER(TRIM(ra.player_name))
            WHERE o.cbet = 1
              AND ra.action IN ('FOLD', 'CALL', 'RAISE')
        )

        SELECT
            o.cohort,
            o.flop,
            o.street,
            COUNT(*) AS opportunities,
            SUM(o.cbet) AS cbets,
            AVG(
                CASE WHEN o.cbet = 1 THEN o.size_pct END
            ) AS avg_size,
            AVG(
                CASE
                    WHEN o.cbet = 1 AND o.size_pct >= 100
                    THEN 1.0
                    WHEN o.cbet = 1
                    THEN 0.0
                    ELSE NULL
                END
            ) AS overbet_rate,
            SUM(
                CASE
                    WHEN o.cohort = 'BOT'
                     AND r.responder_cohort = 'HUMAN'
                     AND r.response_no = 1
                    THEN 1 ELSE 0
                END
            ) AS human_responses,
            SUM(
                CASE
                    WHEN o.cohort = 'BOT'
                     AND r.responder_cohort = 'HUMAN'
                     AND r.response_no = 1
                     AND r.response = 'FOLD'
                    THEN 1 ELSE 0
                END
            ) AS human_folds,
            SUM(
                CASE
                    WHEN o.cohort = 'BOT'
                     AND r.responder_cohort = 'HUMAN'
                     AND r.response_no = 1
                     AND r.response = 'CALL'
                    THEN 1 ELSE 0
                END
            ) AS human_calls,
            SUM(
                CASE
                    WHEN o.cohort = 'BOT'
                     AND r.responder_cohort = 'HUMAN'
                     AND r.response_no = 1
                     AND r.response = 'RAISE'
                    THEN 1 ELSE 0
                END
            ) AS human_raises,
            SUM(
                CASE
                    WHEN o.cohort = 'BOT'
                     AND r.responder_cohort = 'HUMAN'
                     AND r.response_no = 1
                     AND o.size_pct >= 100
                    THEN 1 ELSE 0
                END
            ) AS human_overbet_responses,
            SUM(
                CASE
                    WHEN o.cohort = 'BOT'
                     AND r.responder_cohort = 'HUMAN'
                     AND r.response_no = 1
                     AND o.size_pct >= 100
                     AND r.response = 'FOLD'
                    THEN 1 ELSE 0
                END
            ) AS human_overbet_folds
        FROM opportunities o
        LEFT JOIN responses r
          ON r.hand_id = o.hand_id
         AND r.street = o.street
         AND r.actor_sequence = o.actor_sequence
         AND r.response_no = 1
        GROUP BY
            o.cohort,
            o.flop,
            o.street
        """

        with self.connect() as con:
            raw = con.execute(query, params).fetchall()

        grouped: dict[
            tuple[str, str],
            dict[str, Any],
        ] = defaultdict(
            lambda: {
                "bot_opportunities": 0,
                "bot_cbets": 0,
                "human_opportunities": 0,
                "human_cbets": 0,
                "bot_size_sum": 0.0,
                "bot_size_weight": 0,
                "human_size_sum": 0.0,
                "human_size_weight": 0,
                "bot_overbet_sum": 0.0,
                "bot_overbet_weight": 0,
                "human_overbet_sum": 0.0,
                "human_overbet_weight": 0,
                "human_responses": 0,
                "human_folds": 0,
                "human_calls": 0,
                "human_raises": 0,
                "human_overbet_responses": 0,
                "human_overbet_folds": 0,
            }
        )

        for raw_row in raw:
            (
                cohort,
                flop,
                street,
                opportunities,
                cbets,
                avg_size,
                overbet_rate,
                human_responses,
                human_folds,
                human_calls,
                human_raises,
                human_overbet_responses,
                human_overbet_folds,
            ) = raw_row

            family = self.board_family(str(flop or ""))
            key = (family, str(street or "?").upper())
            item = grouped[key]

            prefix = (
                "bot"
                if str(cohort or "").upper() == "BOT"
                else "human"
            )

            opp_count = int(opportunities or 0)
            cbet_count = int(cbets or 0)

            item[f"{prefix}_opportunities"] += opp_count
            item[f"{prefix}_cbets"] += cbet_count

            if avg_size is not None and cbet_count > 0:
                item[f"{prefix}_size_sum"] += (
                    float(avg_size) * cbet_count
                )
                item[f"{prefix}_size_weight"] += cbet_count

            if overbet_rate is not None and cbet_count > 0:
                item[f"{prefix}_overbet_sum"] += (
                    float(overbet_rate) * cbet_count
                )
                item[f"{prefix}_overbet_weight"] += cbet_count

            if prefix == "bot":
                item["human_responses"] += int(
                    human_responses or 0
                )
                item["human_folds"] += int(
                    human_folds or 0
                )
                item["human_calls"] += int(
                    human_calls or 0
                )
                item["human_raises"] += int(
                    human_raises or 0
                )
                item["human_overbet_responses"] += int(
                    human_overbet_responses or 0
                )
                item["human_overbet_folds"] += int(
                    human_overbet_folds or 0
                )

        rows: list[dict[str, Any]] = []

        for (family, street), item in grouped.items():
            bot_opp = int(item["bot_opportunities"])
            human_opp = int(item["human_opportunities"])
            response_n = int(item["human_responses"])

            # Bot veya human tarafında anlamlı veri varsa satırı göster.
            # Önceki max(...) filtresi çok sayıda kullanılabilir grubu gizliyordu.
            if bot_opp < minimum_sample and human_opp < minimum_sample:
                continue

            bot_cbet = self.pct(
                int(item["bot_cbets"]),
                bot_opp,
            )
            human_cbet = self.pct(
                int(item["human_cbets"]),
                human_opp,
            )
            human_fold = self.pct(
                int(item["human_folds"]),
                response_n,
            )
            human_call = self.pct(
                int(item["human_calls"]),
                response_n,
            )
            human_raise = self.pct(
                int(item["human_raises"]),
                response_n,
            )

            bot_avg_size = self.safe_avg(
                float(item["bot_size_sum"]),
                int(item["bot_size_weight"]),
            )
            human_avg_size = self.safe_avg(
                float(item["human_size_sum"]),
                int(item["human_size_weight"]),
            )

            bot_overbet = 100.0 * self.safe_avg(
                float(item["bot_overbet_sum"]),
                int(item["bot_overbet_weight"]),
            )
            human_overbet = 100.0 * self.safe_avg(
                float(item["human_overbet_sum"]),
                int(item["human_overbet_weight"]),
            )

            fold_vs_overbet = self.pct(
                int(item["human_overbet_folds"]),
                int(item["human_overbet_responses"]),
            )

            cbet_delta = bot_cbet - human_cbet
            effective_sample = max(
                bot_opp,
                human_opp,
                response_n,
            )
            edge = self.edge_score(
                cbet_delta,
                human_fold,
                fold_vs_overbet,
                effective_sample,
            )

            rows.append(
                {
                    "board_family": family,
                    "street": street.title(),
                    "bot_cbet": bot_cbet,
                    "human_cbet": human_cbet,
                    "cbet_delta": cbet_delta,
                    "human_fold": human_fold,
                    "human_call": human_call,
                    "human_raise": human_raise,
                    "bot_avg_size": bot_avg_size,
                    "human_avg_size": human_avg_size,
                    "bot_overbet": bot_overbet,
                    "human_overbet": human_overbet,
                    "human_fold_vs_overbet": fold_vs_overbet,
                    "bot_sample": bot_opp,
                    "human_sample": human_opp,
                    "response_sample": response_n,
                    "overbet_response_sample": int(
                        item["human_overbet_responses"]
                    ),
                    "edge_score": edge,
                    "confidence": self.confidence(effective_sample),
                    "insight": self.insight(
                        street,
                        cbet_delta,
                        human_fold,
                        fold_vs_overbet,
                        response_n,
                    ),
                }
            )

        rows.sort(
            key=lambda item: (
                -int(item["edge_score"]),
                self.STREET_ORDER.get(
                    str(item["street"]).upper(),
                    99,
                ),
                str(item["board_family"]),
            )
        )

        diagnostics = {
            "raw_groups": len(raw),
            "board_groups": len(grouped),
            "visible_rows": len(rows),
            "minimum_sample": minimum_sample,
        }

        summary = self.summary(rows)
        if not rows:
            summary += (
                f" Ham grup: {diagnostics['raw_groups']}, "
                f"board grubu: {diagnostics['board_groups']}, "
                f"minimum sample: {minimum_sample}."
            )

        return {
            "rows": rows,
            "summary": summary,
            "total_rows": len(rows),
            "diagnostics": diagnostics,
        }

    @staticmethod
    def pct(num: int, den: int) -> float:
        return 100.0 * float(num) / float(den) if den else 0.0

    @staticmethod
    def safe_avg(total: float, weight: int) -> float:
        return float(total) / float(weight) if weight else 0.0

    @staticmethod
    def confidence(sample: int) -> str:
        if sample >= 5000:
            return "Çok Yüksek"
        if sample >= 1500:
            return "Yüksek"
        if sample >= 500:
            return "Orta"
        return "Düşük"

    @staticmethod
    def edge_score(delta: float, fold: float, fold_ob: float, sample: int) -> int:
        sample_factor = min(1.0, math.log10(max(sample, 10)) / 4.0)
        raw = max(0.0, delta) * 1.2 + max(0.0, fold - 50.0) * 0.8 + max(0.0, fold_ob - 55.0) * 0.5
        return int(round(min(100.0, raw * sample_factor)))

    @staticmethod
    def insight(street: str, delta: float, fold: float, fold_ob: float, sample: int) -> str:
        parts: list[str] = []
        if delta >= 8:
            parts.append(f"Bot {street.lower()} c-beti human pool'dan {delta:.1f} puan yüksek.")
        elif delta <= -8:
            parts.append(f"Bot {street.lower()} c-beti human pool'dan {abs(delta):.1f} puan düşük.")
        if sample >= 30:
            if fold >= 62:
                parts.append(f"Human pool bot bahislerine %{fold:.1f} fold ediyor.")
            elif fold <= 42:
                parts.append(f"Human pool dirençli; fold yalnızca %{fold:.1f}.")
        if fold_ob >= 65:
            parts.append(f"Overbet karşısında fold %{fold_ob:.1f}; yüksek baskı fırsatı.")
        elif 0 < fold_ob <= 42:
            parts.append(f"Overbet karşısında fold düşük (%{fold_ob:.1f}); bluff overbet dikkatli kullanılmalı.")
        if not parts:
            parts.append("Belirgin uç fark yok; sizing ve pozisyon kırılımı incelenmeli.")
        return " ".join(parts)

    @staticmethod
    def summary(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "Minimum sample koşulunu geçen sonuç bulunamadı."
        best = max(rows, key=lambda r: r["edge_score"])
        return (f"En güçlü eşleşme: {best['board_family']} / {best['street']} — "
                f"Edge {best['edge_score']}/100, Bot CBet %{best['bot_cbet']:.1f}, "
                f"Human Fold %{best['human_fold']:.1f}, Güven {best['confidence']}.")

    @classmethod
    def board_family(cls, flop: str) -> str:
        cards = cls.parse_cards(flop)
        if len(cards) < 3:
            return "Unknown"
        ranks = [cls.RANK_VALUE[c[0]] for c in cards[:3]]
        suits = [c[1] for c in cards[:3]]
        counts = sorted([ranks.count(v) for v in set(ranks)], reverse=True)
        high = max(ranks)
        monotone = len(set(suits)) == 1
        paired = counts[0] >= 2
        unique = sorted(set(ranks))
        connected = False
        if len(unique) == 3:
            connected = max(unique) - min(unique) <= 4
            if set(unique) == {14, 2, 3}:
                connected = True
        if monotone:
            return "Monotone High" if high >= 11 else "Monotone Low"
        if paired:
            return "Paired High" if high >= 11 else "Paired Low"
        if high == 14:
            return "A-high Dynamic" if connected else "A-high Dry"
        if high >= 11:
            return "K/Q/J-high Dynamic" if connected else "K/Q/J-high Dry"
        if high >= 8:
            return "Mid Connected" if connected else "Mid Dry"
        return "Low Connected" if connected else "Low Dry"

    @classmethod
    def parse_cards(cls, text: str) -> list[tuple[str, str]]:
        cleaned = str(text or "").upper().replace("10", "T")
        cleaned = cleaned.replace("♠", "S").replace("♥", "H").replace("♦", "D").replace("♣", "C")
        found = re.findall(r"([2-9TJQKA])\s*([SHDC])", cleaned)
        return [(r, s) for r, s in found]
