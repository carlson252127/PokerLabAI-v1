from __future__ import annotations

from pathlib import Path
from typing import Any
import math
import re

import duckdb


class ResponseComparisonService:
    """Bot aggression versus bot-free pool aggression response comparison."""

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(self.database_path, read_only=True)
        con.execute("PRAGMA threads=4")
        return con

    def groups(self) -> list[tuple[str, int]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT bg.name, COUNT(DISTINCT hp.hand_id) AS hand_count
                FROM bot_groups bg
                LEFT JOIN bot_group_members bgm ON bgm.group_id = bg.group_id
                LEFT JOIN hand_players hp
                  ON LOWER(TRIM(hp.player_name)) =
                     LOWER(TRIM(bgm.player_name))
                GROUP BY bg.name
                ORDER BY hand_count DESC, LOWER(bg.name)
                """
            ).fetchall()
        return [(str(name), int(count or 0)) for name, count in rows]

    def sites(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT TRIM(site)
                FROM hands
                WHERE site IS NOT NULL AND TRIM(site) <> ''
                ORDER BY 1
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    def stakes(self, site: str = "") -> list[str]:
        with self.connect() as con:
            if site:
                rows = con.execute(
                    """
                    SELECT DISTINCT TRIM(stakes)
                    FROM hands
                    WHERE site = ?
                      AND stakes IS NOT NULL
                      AND TRIM(stakes) <> ''
                    ORDER BY 1
                    """,
                    [site],
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT DISTINCT TRIM(stakes)
                    FROM hands
                    WHERE stakes IS NOT NULL AND TRIM(stakes) <> ''
                    ORDER BY 1
                    """
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
            raise ValueError("Bot group seçilmedi.")

        filters = [
            "h.flop IS NOT NULL",
            "TRIM(h.flop) <> ''",
        ]
        params: list[Any] = [bot_group]

        if site:
            filters.append("h.site = ?")
            params.append(site)
        if stakes:
            filters.append("h.stakes = ?")
            params.append(stakes)
        if position:
            filters.append("hp.position = ?")
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
            WHERE player_name IS NOT NULL
        ),
        preflop_raises AS (
            SELECT
                a.hand_id,
                a.player_name,
                a.sequence_no,
                COALESCE(a.to_amount, a.amount, 0) AS open_to,
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
                r.open_to,
                h.flop,
                hp.position,
                CASE
                    WHEN sb.player_key IS NOT NULL THEN 'BOT'
                    ELSE 'POOL'
                END AS cohort
            FROM preflop_raises r
            JOIN hands h ON h.hand_id = r.hand_id
            JOIN hand_players hp
              ON hp.hand_id = r.hand_id
             AND hp.player_name = r.player_name
            LEFT JOIN selected_bots sb
              ON sb.player_key = LOWER(TRIM(r.player_name))
            LEFT JOIN all_bots ab
              ON ab.player_key = LOWER(TRIM(r.player_name))
            WHERE r.raise_no = 1
              AND {where_sql}
              AND (
                    sb.player_key IS NOT NULL
                    OR ab.player_key IS NULL
              )
        ),
        action_pot AS (
            SELECT
                a.*,
                SUM(
                    CASE
                        WHEN UPPER(TRIM(a.action)) IN (
                            'POST_ANTE', 'POST_SB', 'POST_BB',
                            'CALL', 'BET', 'RAISE'
                        )
                        THEN COALESCE(a.amount, 0)
                        ELSE 0
                    END
                ) OVER (
                    PARTITION BY a.hand_id
                    ORDER BY a.sequence_no
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS pot_before
            FROM actions a
        ),
        aggression AS (
            SELECT
                o.hand_id,
                o.opener,
                o.open_to,
                o.flop,
                o.position,
                o.cohort,
                UPPER(TRIM(a.street)) AS street,
                a.sequence_no AS aggression_sequence,
                CASE
                    WHEN COALESCE(a.pot_before, 0) > 0
                    THEN 100.0 * COALESCE(a.amount, 0) / a.pot_before
                    ELSE NULL
                END AS size_pct,
                ROW_NUMBER() OVER (
                    PARTITION BY a.hand_id, UPPER(TRIM(a.street))
                    ORDER BY a.sequence_no
                ) AS aggression_no
            FROM opens o
            JOIN action_pot a
              ON a.hand_id = o.hand_id
             AND a.player_name = o.opener
            WHERE UPPER(TRIM(a.street)) IN ('FLOP', 'TURN', 'RIVER')
              AND UPPER(TRIM(a.action)) IN ('BET', 'RAISE')
              AND COALESCE(a.amount, 0) > 0
        ),
        first_response AS (
            SELECT
                ag.hand_id,
                ag.street,
                ag.aggression_sequence,
                UPPER(TRIM(a.action)) AS response,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        ag.hand_id,
                        ag.street,
                        ag.aggression_sequence
                    ORDER BY a.sequence_no
                ) AS response_no
            FROM aggression ag
            JOIN actions a
              ON a.hand_id = ag.hand_id
             AND a.sequence_no > ag.aggression_sequence
             AND UPPER(TRIM(a.street)) = ag.street
             AND a.player_name <> ag.opener
            WHERE UPPER(TRIM(a.action)) IN ('FOLD', 'CALL', 'RAISE')
        )
        SELECT
            ag.cohort,
            ag.position,
            ag.open_to,
            ag.flop,
            ag.street,
            ag.size_pct,
            fr.response,
            COUNT(*) AS response_count
        FROM aggression ag
        JOIN first_response fr
          ON fr.hand_id = ag.hand_id
         AND fr.street = ag.street
         AND fr.aggression_sequence = ag.aggression_sequence
         AND fr.response_no = 1
        WHERE ag.aggression_no = 1
        GROUP BY
            ag.cohort,
            ag.position,
            ag.open_to,
            ag.flop,
            ag.street,
            ag.size_pct,
            fr.response
        """

        with self.connect() as con:
            raw = con.execute(query, params).fetchall()

        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}

        for (
            cohort, pos, open_to, flop, street,
            size_pct, response, response_count,
        ) in raw:
            key = (
                str(pos or "?"),
                self._open_bucket(float(open_to or 0)),
                self._board_family(str(flop or "")),
                f"{str(street)} {self._bet_bucket(float(size_pct or 0))}",
            )
            item = grouped.setdefault(
                key,
                {
                    "position": key[0],
                    "open_size": key[1],
                    "board": key[2],
                    "spot": key[3],
                    "bot": {"FOLD": 0, "CALL": 0, "RAISE": 0, "n": 0},
                    "pool": {"FOLD": 0, "CALL": 0, "RAISE": 0, "n": 0},
                },
            )
            target = item["bot" if cohort == "BOT" else "pool"]
            count = int(response_count or 0)
            response_key = str(response or "").upper()
            target[response_key] = target.get(response_key, 0) + count
            target["n"] += count

        rows: list[dict[str, Any]] = []
        min_required = max(1, int(minimum_sample))

        for item in grouped.values():
            bot = item["bot"]
            pool = item["pool"]
            effective_sample = min(bot["n"], pool["n"])

            if effective_sample < min_required:
                continue

            result = {
                key: value
                for key, value in item.items()
                if key not in ("bot", "pool")
            }

            for prefix, data in (("bot", bot), ("pool", pool)):
                total = max(1, int(data["n"]))
                result[f"{prefix}_sample"] = int(data["n"])
                result[f"{prefix}_fold"] = 100.0 * data["FOLD"] / total
                result[f"{prefix}_call"] = 100.0 * data["CALL"] / total
                result[f"{prefix}_raise"] = 100.0 * data["RAISE"] / total

            result["pressure_edge"] = (
                result["bot_fold"] - result["pool_fold"]
            )
            result["call_edge"] = (
                result["bot_call"] - result["pool_call"]
            )
            result["raise_edge"] = (
                result["bot_raise"] - result["pool_raise"]
            )
            result["confidence"] = self._confidence(effective_sample)
            result["priority"] = self._priority(
                result["pressure_edge"],
                result["call_edge"],
                result["raise_edge"],
                effective_sample,
            )
            result["finding"] = self._finding(result)
            rows.append(result)

        rows.sort(
            key=lambda row: (
                float(row["priority"]),
                abs(float(row["pressure_edge"])),
            ),
            reverse=True,
        )

        positive = [r for r in rows if r["pressure_edge"] >= 3.0]
        negative = [r for r in rows if r["pressure_edge"] <= -3.0]

        return {
            "rows": rows,
            "bot_group": bot_group,
            "count": len(rows),
            "positive_edges": len(positive),
            "negative_edges": len(negative),
            "summary": self._summary(rows, bot_group),
        }

    @staticmethod
    def _priority(
        pressure: float,
        call: float,
        raise_edge: float,
        sample: int,
    ) -> float:
        effect = (
            abs(pressure)
            + 0.35 * abs(call)
            + 0.50 * abs(raise_edge)
        )
        sample_weight = min(1.0, math.log10(max(10, sample)) / 3.0)
        return round(effect * sample_weight, 2)

    @staticmethod
    def _finding(row: dict[str, Any]) -> str:
        edge = float(row["pressure_edge"])
        if edge >= 7:
            return "Pool bot agresyonuna belirgin daha fazla fold ediyor"
        if edge >= 3:
            return "Pool bot agresyonuna biraz daha fazla fold ediyor"
        if edge <= -7:
            return "Pool bot agresyonuna belirgin daha az fold ediyor"
        if edge <= -3:
            return "Pool bot agresyonuna biraz daha az fold ediyor"
        return "Anlamlı response farkı görünmüyor"

    @staticmethod
    def _summary(rows: list[dict[str, Any]], group: str) -> str:
        if not rows:
            return (
                f"{group}: minimum sample koşulunu geçen "
                "karşılaştırılabilir spot bulunamadı."
            )
        top = rows[0]
        return (
            f"{group}: {len(rows)} karşılaştırılabilir spot. "
            f"En yüksek araştırma önceliği: {top['position']} / "
            f"{top['board']} / {top['spot']}; "
            f"Pressure Edge {top['pressure_edge']:+.1f} puan, "
            f"güven {top['confidence']}."
        )

    @staticmethod
    def _open_bucket(value: float) -> str:
        if value <= 0:
            return "Unknown"
        if value <= 2.3:
            return "Small ≤2.3x"
        if value <= 3.1:
            return "Medium 2.4–3.1x"
        return "Large ≥3.2x"

    @staticmethod
    def _bet_bucket(value: float) -> str:
        if value <= 0:
            return "?"
        if value <= 30:
            return "≤30%"
        if value <= 42:
            return "33%"
        if value <= 62:
            return "50%"
        if value <= 87:
            return "75%"
        if value <= 125:
            return "100%"
        if value <= 175:
            return "150%"
        return ">150%"

    @staticmethod
    def _confidence(sample: int) -> str:
        if sample >= 2000:
            return "Çok Yüksek"
        if sample >= 750:
            return "Yüksek"
        if sample >= 250:
            return "Orta"
        if sample >= 75:
            return "Düşük"
        return "Çok Düşük"

    @staticmethod
    def _board_family(text: str) -> str:
        cards = re.findall(r"([2-9TJQKA])([shdc])", text, re.I)
        if len(cards) < 3:
            return "Unknown"

        ranks = [
            "23456789TJQKA".index(rank.upper()) + 2
            for rank, _suit in cards[:3]
        ]
        suits = [suit.lower() for _rank, suit in cards[:3]]
        high = max(ranks)
        paired = len(set(ranks)) < 3
        monotone = len(set(suits)) == 1
        connected = max(ranks) - min(ranks) <= 4

        if monotone:
            return "Monotone High" if high >= 11 else "Monotone Low"
        if paired:
            return "Paired High" if high >= 11 else "Paired Low"
        if high == 14:
            return "A-high Dynamic" if connected else "A-high Dry"
        if high >= 11:
            return (
                "K/Q/J-high Dynamic"
                if connected
                else "K/Q/J-high Dry"
            )
        if high >= 8:
            return "Mid Connected" if connected else "Mid Dry"
        return "Low Connected" if connected else "Low Dry"
