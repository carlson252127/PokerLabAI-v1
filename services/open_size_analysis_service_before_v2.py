from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb


class OpenSizeAnalysisService:
    POSITION_ORDER = ["UTG", "HJ", "CO", "BTN", "SB", "BB", "OTHER"]

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
        mode = mode.upper()
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
                    SELECT pa.alias_name, COUNT(DISTINCT hp.hand_id) AS hands
                    FROM player_aliases pa
                    JOIN hand_players hp ON hp.player_name = pa.player_name
                    JOIN hands h ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY pa.alias_name
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
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
        mode = mode.upper()

        entity_rows = self._load_open_rows(
            mode, entity_name, site, stakes, position
        )
        entity = self._aggregate(entity_rows, minimum_sample)

        pool: dict[str, Any] = {}
        if mode == "COMPARE":
            pool_rows = self._load_open_rows(
                "POOL", "", site, stakes, position
            )
            pool = self._aggregate(pool_rows, minimum_sample)

        return {"entity": entity, "pool": pool}

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
            clauses.append("hp.position = ?")
            params.append(position)

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

        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH raises AS (
                SELECT
                    a.hand_id,
                    a.player_name,
                    a.sequence_no,
                    a.amount,
                    a.to_amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id
                        ORDER BY a.sequence_no
                    ) AS raise_no
                FROM actions a
                WHERE a.street = 'PREFLOP'
                  AND a.action = 'RAISE'
            ),
            opens AS (
                SELECT
                    r.hand_id,
                    r.player_name,
                    r.sequence_no,
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
                FROM raises r
                JOIN hands h ON h.hand_id = r.hand_id
                JOIN hand_players hp
                  ON hp.hand_id = r.hand_id
                 AND hp.player_name = r.player_name
                {where_sql}
                {"AND" if where_sql else "WHERE"} r.raise_no = 1
            )
            SELECT
                o.hand_id,
                o.player_name,
                o.site,
                o.stakes,
                o.position,
                o.starting_stack,
                o.amount,
                o.to_amount,
                o.flop,
                o.turn,
                o.river,
                o.pot,
                EXISTS (
                    SELECT 1
                    FROM actions r2
                    WHERE r2.hand_id = o.hand_id
                      AND r2.street = 'PREFLOP'
                      AND r2.action = 'RAISE'
                      AND r2.sequence_no > o.sequence_no
                ) AS faced_three_bet,
                EXISTS (
                    SELECT 1
                    FROM actions c
                    WHERE c.hand_id = o.hand_id
                      AND c.player_name = o.player_name
                      AND c.action = 'COLLECT'
                ) AS won_pot,
                EXISTS (
                    SELECT 1
                    FROM actions s
                    WHERE s.hand_id = o.hand_id
                      AND s.player_name = o.player_name
                      AND s.action = 'SHOW'
                ) AS went_showdown
            FROM opens o
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
            won = bool(row[13])
            showdown = bool(row[14])

            result.append(
                {
                    "position": row[4] or "OTHER",
                    "size_bb": size_bb,
                    "size_bucket": self._size_bucket(size_bb),
                    "stack_bb": stack_bb,
                    "faced_three_bet": bool(row[12]),
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
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

        for row in rows:
            key = (row["position"], row["size_bucket"])
            groups.setdefault(key, []).append(row)

        table_rows: list[dict[str, Any]] = []

        for (position, bucket), items in groups.items():
            count = len(items)
            if count < max(1, int(minimum_sample)):
                continue

            sizes = [x["size_bb"] for x in items if x["size_bb"] is not None]
            stacks = [x["stack_bb"] for x in items if x["stack_bb"] is not None]

            three_bet = sum(1 for x in items if x["faced_three_bet"])
            flop_seen = sum(1 for x in items if x["saw_flop"])
            won = sum(1 for x in items if x["won_pot"])
            wwsf_opp = sum(1 for x in items if x["wwsf_opp"])
            wwsf_win = sum(1 for x in items if x["wwsf_win"])
            wsd_opp = sum(1 for x in items if x["wsd_opp"])
            wsd_win = sum(1 for x in items if x["wsd_win"])

            avg_stack = sum(stacks) / len(stacks) if stacks else None

            table_rows.append(
                {
                    "position": position,
                    "size_bucket": bucket,
                    "opens": count,
                    "share": self._pct(count, len(rows)),
                    "avg_size_bb": sum(sizes) / len(sizes) if sizes else None,
                    "avg_stack_bb": avg_stack,
                    "three_bet_faced": self._pct(three_bet, count),
                    "flop_seen": self._pct(flop_seen, count),
                    "pot_won": self._pct(won, count),
                    "wwsf": self._pct(wwsf_win, wwsf_opp),
                    "wwsf_sample": wwsf_opp,
                    "wsd": self._pct(wsd_win, wsd_opp),
                    "wsd_sample": wsd_opp,
                    "pattern_note": self._pattern_note(
                        position,
                        bucket,
                        avg_stack,
                        self._pct(three_bet, count),
                        self._pct(flop_seen, count),
                    ),
                }
            )

        pos_rank = {p: i for i, p in enumerate(self.POSITION_ORDER)}
        bucket_rank = {
            "≤2.0x": 0,
            "2.1–2.3x": 1,
            "2.4–2.6x": 2,
            "2.7–3.1x": 3,
            ">3.1x": 4,
            "UNKNOWN": 5,
        }

        table_rows.sort(
            key=lambda r: (
                pos_rank.get(r["position"], 99),
                bucket_rank.get(r["size_bucket"], 99),
            )
        )

        all_sizes = [x["size_bb"] for x in rows if x["size_bb"] is not None]
        wwsf_opp = sum(1 for x in rows if x["wwsf_opp"])
        wwsf_win = sum(1 for x in rows if x["wwsf_win"])
        wsd_opp = sum(1 for x in rows if x["wsd_opp"])
        wsd_win = sum(1 for x in rows if x["wsd_win"])

        return {
            "opens": len(rows),
            "avg_size_bb": sum(all_sizes) / len(all_sizes) if all_sizes else 0.0,
            "wwsf": self._pct(wwsf_win, wwsf_opp),
            "wwsf_sample": wwsf_opp,
            "wsd": self._pct(wsd_win, wsd_opp),
            "wsd_sample": wsd_opp,
            "rows": table_rows,
        }

    def _pattern_note(
        self,
        position: str,
        bucket: str,
        avg_stack_bb: float | None,
        three_bet_faced: float,
        flop_seen: float,
    ) -> str:
        notes: list[str] = []

        if position in {"CO", "BTN", "SB"} and bucket in {"≤2.0x", "2.1–2.3x"}:
            notes.append("Geç pozisyon/steal ile ilişkili küçük sizing")
        if position in {"UTG", "HJ"} and bucket in {"2.7–3.1x", ">3.1x"}:
            notes.append("Erken pozisyonda daha büyük sizing")
        if avg_stack_bb is not None and avg_stack_bb < 40:
            notes.append("Kısa stack ilişkisi")
        elif avg_stack_bb is not None and avg_stack_bb > 150:
            notes.append("Deep-stack ilişkisi")
        if three_bet_faced >= 18:
            notes.append("Yüksek 3-bet maruziyeti")
        if flop_seen >= 70:
            notes.append("Flopa sık taşınan sizing")
        elif flop_seen <= 40:
            notes.append("Sık preflop sonuçlanan sizing")

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

    def _pct(self, numerator: int, denominator: int) -> float:
        return numerator / denominator * 100.0 if denominator else 0.0

    def _float_or_none(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
