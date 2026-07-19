from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import math
import re

import duckdb


class BoardMatchupService:
    """Compare selected bot-group c-bets with bot-free human-pool c-bets and responses."""

    STREET_ORDER = {"FLOP": 0, "TURN": 1, "RIVER": 2}
    POSITION_ORDER = {"UTG": 0, "MP": 1, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4, "BB": 5, "?": 99}
    RANK_VALUE = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                  "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))

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
        if not bot_group:
            raise ValueError("Bot grubu seçilmedi.")

        filters = ["h.flop IS NOT NULL", "TRIM(h.flop) <> ''"]
        params: list[Any] = [bot_group]
        if site:
            filters.append("h.site = ?")
            params.append(site)
        if stakes:
            filters.append("h.stakes = ?")
            params.append(stakes)
        if position:
            filters.append("UPPER(TRIM(hp.position)) = UPPER(TRIM(?))")
            params.append(position)
        where_sql = " AND ".join(filters)

        query = f"""
        WITH selected_bots AS (
            SELECT DISTINCT LOWER(TRIM(bgm.player_name)) AS player_key
            FROM bot_group_members bgm
            JOIN bot_groups bg ON bg.group_id = bgm.group_id
            WHERE bg.name = ?
        ),
        all_bots AS (
            SELECT DISTINCT LOWER(TRIM(player_name)) AS player_key
            FROM bot_group_members
            WHERE player_name IS NOT NULL AND TRIM(player_name) <> ''
        ),
        preflop_raises AS (
            SELECT a.hand_id, a.player_name, a.sequence_no,
                   ROW_NUMBER() OVER (PARTITION BY a.hand_id ORDER BY a.sequence_no) AS raise_no
            FROM actions a
            WHERE UPPER(TRIM(a.street)) = 'PREFLOP'
              AND UPPER(TRIM(a.action)) = 'RAISE'
        ),
        opens AS (
            SELECT r.hand_id, r.player_name AS opener, hp.position,
                   h.flop, h.turn, h.river,
                   CASE WHEN sb.player_key IS NOT NULL THEN 'BOT' ELSE 'HUMAN' END AS cohort
            FROM preflop_raises r
            JOIN hands h ON h.hand_id = r.hand_id
            JOIN hand_players hp ON hp.hand_id = r.hand_id AND hp.player_name = r.player_name
            LEFT JOIN selected_bots sb ON sb.player_key = LOWER(TRIM(r.player_name))
            LEFT JOIN all_bots ab ON ab.player_key = LOWER(TRIM(r.player_name))
            WHERE r.raise_no = 1
              AND {where_sql}
              AND (sb.player_key IS NOT NULL OR ab.player_key IS NULL)
        ),
        action_pot AS (
            SELECT a.*,
                   SUM(CASE WHEN UPPER(TRIM(a.action)) IN
                       ('POST_ANTE','POST_SB','POST_BB','CALL','BET','RAISE')
                       THEN COALESCE(a.amount, 0) ELSE 0 END)
                   OVER (PARTITION BY a.hand_id ORDER BY a.sequence_no
                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pot_before
            FROM actions a
        ),
        streets AS (
            SELECT hand_id, opener, position, flop, cohort, 'FLOP' AS street FROM opens
            UNION ALL
            SELECT hand_id, opener, position, flop, cohort, 'TURN' AS street FROM opens
            WHERE turn IS NOT NULL AND TRIM(turn) <> ''
            UNION ALL
            SELECT hand_id, opener, position, flop, cohort, 'RIVER' AS street FROM opens
            WHERE river IS NOT NULL AND TRIM(river) <> ''
        ),
        actor_first AS (
            SELECT s.hand_id, s.opener, s.position, s.flop, s.cohort, s.street,
                   UPPER(TRIM(a.action)) AS actor_action,
                   a.sequence_no AS actor_sequence,
                   COALESCE(a.amount, 0) AS amount,
                   COALESCE(a.pot_before, 0) AS pot_before,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.hand_id, s.street
                       ORDER BY a.sequence_no
                   ) AS actor_no
            FROM streets s
            JOIN action_pot a ON a.hand_id = s.hand_id
                             AND a.player_name = s.opener
                             AND UPPER(TRIM(a.street)) = s.street
            WHERE UPPER(TRIM(a.action)) IN ('CHECK','BET','RAISE','FOLD','CALL')
        ),
        prior_opp_aggression AS (
            SELECT af.hand_id, af.street, af.actor_sequence,
                   COUNT(*) AS prior_aggression
            FROM actor_first af
            JOIN actions a ON a.hand_id = af.hand_id
                          AND UPPER(TRIM(a.street)) = af.street
                          AND a.sequence_no < af.actor_sequence
                          AND a.player_name <> af.opener
                          AND UPPER(TRIM(a.action)) IN ('BET','RAISE')
            WHERE af.actor_no = 1
            GROUP BY af.hand_id, af.street, af.actor_sequence
        ),
        opportunities AS (
            SELECT af.*,
                   CASE WHEN af.actor_action IN ('BET','RAISE') THEN 1 ELSE 0 END AS cbet,
                   CASE WHEN af.actor_action IN ('BET','RAISE') AND af.pot_before > 0
                        THEN 100.0 * af.amount / af.pot_before ELSE NULL END AS size_pct
            FROM actor_first af
            LEFT JOIN prior_opp_aggression po
              ON po.hand_id = af.hand_id AND po.street = af.street
             AND po.actor_sequence = af.actor_sequence
            WHERE af.actor_no = 1 AND COALESCE(po.prior_aggression, 0) = 0
        ),
        responses AS (
            SELECT o.hand_id, o.street, o.actor_sequence,
                   UPPER(TRIM(a.action)) AS response,
                   CASE WHEN ab.player_key IS NULL THEN 'HUMAN' ELSE 'BOT' END AS responder_cohort,
                   ROW_NUMBER() OVER (
                       PARTITION BY o.hand_id, o.street, o.actor_sequence
                       ORDER BY a.sequence_no
                   ) AS response_no
            FROM opportunities o
            JOIN actions a ON a.hand_id = o.hand_id
                          AND UPPER(TRIM(a.street)) = o.street
                          AND a.sequence_no > o.actor_sequence
                          AND a.player_name <> o.opener
            LEFT JOIN all_bots ab ON ab.player_key = LOWER(TRIM(a.player_name))
            WHERE o.cbet = 1 AND UPPER(TRIM(a.action)) IN ('FOLD','CALL','RAISE')
        )
        SELECT o.cohort, o.position, o.flop, o.street,
               COUNT(*) AS opportunities,
               SUM(o.cbet) AS cbets,
               AVG(CASE WHEN o.cbet = 1 THEN o.size_pct END) AS avg_size,
               AVG(CASE WHEN o.cbet = 1 AND o.size_pct >= 100 THEN 1.0 ELSE 0.0 END) AS overbet_rate,
               SUM(CASE WHEN o.cohort = 'BOT' AND r.responder_cohort = 'HUMAN' AND r.response_no = 1 THEN 1 ELSE 0 END) AS human_responses,
               SUM(CASE WHEN o.cohort = 'BOT' AND r.responder_cohort = 'HUMAN' AND r.response_no = 1 AND r.response = 'FOLD' THEN 1 ELSE 0 END) AS human_folds,
               SUM(CASE WHEN o.cohort = 'BOT' AND r.responder_cohort = 'HUMAN' AND r.response_no = 1 AND r.response = 'CALL' THEN 1 ELSE 0 END) AS human_calls,
               SUM(CASE WHEN o.cohort = 'BOT' AND r.responder_cohort = 'HUMAN' AND r.response_no = 1 AND r.response = 'RAISE' THEN 1 ELSE 0 END) AS human_raises,
               SUM(CASE WHEN o.cohort = 'BOT' AND r.responder_cohort = 'HUMAN' AND r.response_no = 1 AND o.size_pct >= 100 THEN 1 ELSE 0 END) AS human_overbet_responses,
               SUM(CASE WHEN o.cohort = 'BOT' AND r.responder_cohort = 'HUMAN' AND r.response_no = 1 AND o.size_pct >= 100 AND r.response = 'FOLD' THEN 1 ELSE 0 END) AS human_overbet_folds
        FROM opportunities o
        LEFT JOIN responses r ON r.hand_id = o.hand_id AND r.street = o.street
                             AND r.actor_sequence = o.actor_sequence AND r.response_no = 1
        GROUP BY o.cohort, o.position, o.flop, o.street
        """

        with self.connect() as con:
            raw = con.execute(query, params).fetchall()

        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
            "bot_opportunities": 0, "bot_cbets": 0, "human_opportunities": 0, "human_cbets": 0,
            "bot_size_sum": 0.0, "bot_size_weight": 0, "human_size_sum": 0.0, "human_size_weight": 0,
            "bot_overbet_sum": 0.0, "bot_overbet_weight": 0, "human_overbet_sum": 0.0, "human_overbet_weight": 0,
            "human_responses": 0, "human_folds": 0, "human_calls": 0, "human_raises": 0,
            "human_overbet_responses": 0, "human_overbet_folds": 0,
        })

        for row in raw:
            (cohort, pos, flop, street, opps, cbets, avg_size, overbet_rate,
             hresp, hfold, hcall, hraise, hobresp, hobfold) = row
            family = self.board_family(str(flop or ""))
            key = (family, str(street or "?"))
            item = grouped[key]
            prefix = "bot" if str(cohort) == "BOT" else "human"
            item[f"{prefix}_opportunities"] += int(opps or 0)
            item[f"{prefix}_cbets"] += int(cbets or 0)
            if avg_size is not None and int(cbets or 0) > 0:
                item[f"{prefix}_size_sum"] += float(avg_size) * int(cbets or 0)
                item[f"{prefix}_size_weight"] += int(cbets or 0)
            if overbet_rate is not None and int(cbets or 0) > 0:
                item[f"{prefix}_overbet_sum"] += float(overbet_rate) * int(cbets or 0)
                item[f"{prefix}_overbet_weight"] += int(cbets or 0)
            if prefix == "bot":
                item["human_responses"] += int(hresp or 0)
                item["human_folds"] += int(hfold or 0)
                item["human_calls"] += int(hcall or 0)
                item["human_raises"] += int(hraise or 0)
                item["human_overbet_responses"] += int(hobresp or 0)
                item["human_overbet_folds"] += int(hobfold or 0)

        rows: list[dict[str, Any]] = []
        for (family, street), item in grouped.items():
            bot_opp = item["bot_opportunities"]
            human_opp = item["human_opportunities"]
            response_n = item["human_responses"]
            if max(bot_opp, human_opp, response_n) < int(minimum_sample):
                continue
            bot_cbet = self.pct(item["bot_cbets"], bot_opp)
            human_cbet = self.pct(item["human_cbets"], human_opp)
            human_fold = self.pct(item["human_folds"], response_n)
            human_call = self.pct(item["human_calls"], response_n)
            human_raise = self.pct(item["human_raises"], response_n)
            bot_avg_size = self.safe_avg(item["bot_size_sum"], item["bot_size_weight"])
            human_avg_size = self.safe_avg(item["human_size_sum"], item["human_size_weight"])
            bot_ob = 100.0 * self.safe_avg(item["bot_overbet_sum"], item["bot_overbet_weight"])
            human_ob = 100.0 * self.safe_avg(item["human_overbet_sum"], item["human_overbet_weight"])
            fold_vs_ob = self.pct(item["human_overbet_folds"], item["human_overbet_responses"])
            delta = bot_cbet - human_cbet
            edge = self.edge_score(delta, human_fold, fold_vs_ob, response_n)
            rows.append({
                "board_family": family,
                "street": street.title(),
                "bot_cbet": bot_cbet,
                "human_cbet": human_cbet,
                "cbet_delta": delta,
                "human_fold": human_fold,
                "human_call": human_call,
                "human_raise": human_raise,
                "bot_avg_size": bot_avg_size,
                "human_avg_size": human_avg_size,
                "bot_overbet": bot_ob,
                "human_overbet": human_ob,
                "human_fold_vs_overbet": fold_vs_ob,
                "bot_sample": bot_opp,
                "human_sample": human_opp,
                "response_sample": response_n,
                "overbet_response_sample": item["human_overbet_responses"],
                "edge_score": edge,
                "confidence": self.confidence(max(bot_opp, human_opp, response_n)),
                "insight": self.insight(street, delta, human_fold, fold_vs_ob, response_n),
            })

        rows.sort(key=lambda x: (-x["edge_score"], self.STREET_ORDER.get(x["street"].upper(), 99), x["board_family"]))
        return {
            "rows": rows,
            "summary": self.summary(rows),
            "total_rows": len(rows),
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
