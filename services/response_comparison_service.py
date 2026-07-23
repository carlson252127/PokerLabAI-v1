from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import math
import os
import re

import duckdb
import pyarrow as pa

from services.response_node_schema import ensure_response_node_schema


class ResponseComparisonService:
    """Incremental, bounded-memory response comparison engine.

    The first analysis indexes only missing hands in small batches. Later analyses
    read the compact response_nodes table and do not rescan the full actions table.
    """

    NODE_LABELS = {
        "ALL_RESPONSES": "Genel Response",
        "X_XC_XF_OOP": "X-XC-XF OOP Caller",
        "X_C_F_IP": "X-C-F IP Caller",
        "XC_XF_OOP": "XC-XF OOP",
        "XC_XC_OOP": "XC-XC OOP",
        "XC_XR_OOP": "XC-XR OOP",
        "XC_XC_XF_OOP": "XC-XC-XF OOP",
        "XC_XC_XC_OOP": "XC-XC-XC OOP",
        "XC_XC_XR_OOP": "XC-XC-XR OOP",
        "X_C_C_IP": "X-C-C IP",
        "X_C_R_IP": "X-C-R IP",
        "PROBE_TURN": "Turn Probe",
        "DELAY_DEFENCE": "Delay Cbet Defence",
        "RIVER_BLUFF_CATCH": "River Bluff Catch",
        "RIVER_RAISE": "River Raise",
    }

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))
        self.batch_size = 5_000

    def connect(self) -> duckdb.DuckDBPyConnection:
        # Do not use read_only=True: AnalyticalStore opens the same file writable.
        con = duckdb.connect(self.database_path)
        con.execute(f"PRAGMA threads={max(2, min(8, os.cpu_count() or 4))}")
        con.execute("SET preserve_insertion_order = false")
        return con

    def nodes(self) -> list[tuple[str, str]]:
        return list(self.NODE_LABELS.items())

    def _ensure_tables(self, con: duckdb.DuckDBPyConnection) -> None:
        ensure_response_node_schema(con)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rn_node ON response_nodes(node)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rn_aggressor ON response_nodes(aggressor)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_rn_filters "
            "ON response_nodes(site, stakes, aggressor_position)"
        )

    def groups(self) -> list[tuple[str, int]]:
        with self.connect() as con:
            self._ensure_tables(con)
            if not self._table_exists(con, "bot_groups"):
                return []
            rows = con.execute(
                """
                SELECT bg.name, COUNT(DISTINCT hp.hand_id)
                FROM bot_groups bg
                LEFT JOIN bot_group_members bgm ON bgm.group_id = bg.group_id
                LEFT JOIN hand_players hp
                  ON LOWER(TRIM(hp.player_name)) =
                     LOWER(TRIM(bgm.player_name))
                GROUP BY bg.name
                ORDER BY 2 DESC, LOWER(bg.name)
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
                    WHERE site = ? AND stakes IS NOT NULL AND TRIM(stakes) <> ''
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

    def index_status(self) -> dict[str, int]:
        with self.connect() as con:
            self._ensure_tables(con)
            total = int(con.execute("SELECT COUNT(*) FROM hands").fetchone()[0])
            indexed = int(
                con.execute(
                    "SELECT COUNT(*) FROM response_node_v4_indexed_hands"
                ).fetchone()[0]
            )
            nodes = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM response_nodes
                    WHERE aggressor IS NOT NULL
                    """
                ).fetchone()[0]
            )
        return {"total": total, "indexed": indexed, "pending": max(0, total - indexed), "nodes": nodes}

    def ensure_index(self) -> dict[str, int]:
        """Index all missing hands using small, transaction-safe batches."""
        with self.connect() as con:
            self._ensure_tables(con)
            added_hands = 0
            added_nodes = 0

            while True:
                ids = [
                    str(row[0])
                    for row in con.execute(
                        f"""
                        SELECT h.hand_id
                        FROM hands h
                        ANTI JOIN response_node_v4_indexed_hands i USING (hand_id)
                        LIMIT {int(self.batch_size)}
                        """
                    ).fetchall()
                ]
                if not ids:
                    break

                id_table = pa.Table.from_pylist([{"hand_id": value} for value in ids])
                con.register("response_batch_ids", id_table)
                try:
                    hands = {
                        str(row[0]): {
                            "site": row[1],
                            "stakes": row[2],
                            "flop": row[3],
                            "turn": row[4],
                            "river": row[5],
                        }
                        for row in con.execute(
                            """
                            SELECT h.hand_id, h.site, h.stakes, h.flop, h.turn, h.river
                            FROM hands h
                            JOIN response_batch_ids b USING (hand_id)
                            """
                        ).fetchall()
                    }
                    positions: dict[str, dict[str, str]] = defaultdict(dict)
                    for hand_id, player, position in con.execute(
                        """
                        SELECT hp.hand_id, hp.player_name, hp.position
                        FROM hand_players hp
                        JOIN response_batch_ids b USING (hand_id)
                        """
                    ).fetchall():
                        positions[str(hand_id)][self._key(player)] = str(position or "?")

                    actions: dict[str, list[dict[str, Any]]] = defaultdict(list)
                    for row in con.execute(
                        """
                        SELECT a.hand_id, a.sequence_no, a.street, a.player_name,
                               a.action, a.amount, a.to_amount
                        FROM actions a
                        JOIN response_batch_ids b USING (hand_id)
                        ORDER BY a.hand_id, a.sequence_no
                        """
                    ).fetchall():
                        actions[str(row[0])].append(
                            {
                                "sequence": int(row[1] or 0),
                                "street": str(row[2] or "").upper().strip(),
                                "player": str(row[3] or ""),
                                "action": str(row[4] or "").upper().strip(),
                                "amount": float(row[5] or 0),
                                "to_amount": float(row[6] or 0),
                            }
                        )
                finally:
                    con.unregister("response_batch_ids")

                node_rows: list[dict[str, Any]] = []
                for hand_id in ids:
                    node_rows.extend(
                        self._build_hand_nodes(
                            hand_id,
                            hands.get(hand_id, {}),
                            positions.get(hand_id, {}),
                            actions.get(hand_id, []),
                        )
                    )

                con.execute("BEGIN TRANSACTION")
                try:
                    if node_rows:
                        con.register(
                            "incoming_response_nodes",
                            pa.Table.from_pylist(node_rows),
                        )
                        con.execute(
                            """
                            INSERT INTO response_nodes (
                                hand_id, aggressor, responder,
                                aggressor_position, responder_position,
                                site, stakes, node, street, response,
                                board_family, open_bucket, bet_bucket
                            )
                            SELECT hand_id, aggressor, responder,
                                   aggressor_position, responder_position,
                                   site, stakes, node, street, response,
                                   board_family, open_bucket, bet_bucket
                            FROM incoming_response_nodes
                            """
                        )
                        con.unregister("incoming_response_nodes")
                    con.register(
                        "indexed_response_batch",
                        pa.Table.from_pylist([{"hand_id": value} for value in ids]),
                    )
                    con.execute(
                        """
                        INSERT INTO response_node_v4_indexed_hands
                        SELECT hand_id FROM indexed_response_batch
                        ON CONFLICT (hand_id) DO NOTHING
                        """
                    )
                    con.unregister("indexed_response_batch")
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise

                added_hands += len(ids)
                added_nodes += len(node_rows)

            status = self.index_status()
            status["added_hands"] = added_hands
            status["added_nodes"] = added_nodes
            return status

    def analyze(
        self,
        bot_group: str,
        node: str = "ALL_RESPONSES",
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 50,
    ) -> dict[str, Any]:
        if not bot_group:
            raise ValueError("Bot group seçilmedi.")
        if node not in self.NODE_LABELS:
            raise ValueError(f"Desteklenmeyen node: {node}")

        index_info = self.ensure_index()
        minimum_sample = max(1, int(minimum_sample))

        filters = ["rn.node = ?"]
        params: list[Any] = [bot_group, node]
        if site:
            filters.append("rn.site = ?")
            params.append(site)
        if stakes:
            filters.append("rn.stakes = ?")
            params.append(stakes)
        if position:
            filters.append("rn.aggressor_position = ?")
            params.append(position)

        where_sql = " AND ".join(filters)
        with self.connect() as con:
            self._ensure_tables(con)
            raw = con.execute(
                f"""
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
                classified AS (
                    SELECT
                        CASE
                            WHEN sb.player_key IS NOT NULL THEN 'BOT'
                            ELSE 'POOL'
                        END AS cohort,
                        rn.aggressor_position,
                        rn.open_bucket,
                        rn.board_family,
                        rn.street,
                        rn.bet_bucket,
                        rn.response
                    FROM response_nodes rn
                    LEFT JOIN selected_bots sb
                      ON sb.player_key = LOWER(TRIM(rn.aggressor))
                    LEFT JOIN all_bots ab
                      ON ab.player_key = LOWER(TRIM(rn.aggressor))
                    WHERE {where_sql}
                      AND rn.aggressor IS NOT NULL
                      AND (sb.player_key IS NOT NULL OR ab.player_key IS NULL)
                )
                SELECT cohort, aggressor_position, open_bucket, board_family,
                       street, bet_bucket, response, COUNT(*)
                FROM classified
                GROUP BY ALL
                """,
                params,
            ).fetchall()

        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for cohort, pos, open_bucket, board, street, bet_bucket, response, count in raw:
            key = (
                str(pos or "?"),
                str(open_bucket or "?"),
                str(board or "UNKNOWN"),
                f"{street} {bet_bucket}",
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
            response_key = str(response or "").upper()
            n = int(count or 0)
            target[response_key] = target.get(response_key, 0) + n
            target["n"] += n

        rows: list[dict[str, Any]] = []
        for item in grouped.values():
            bot = item["bot"]
            pool = item["pool"]
            effective = min(int(bot["n"]), int(pool["n"]))
            if effective < minimum_sample:
                continue
            result = {k: v for k, v in item.items() if k not in {"bot", "pool"}}
            for prefix, data in (("bot", bot), ("pool", pool)):
                total = max(1, int(data["n"]))
                result[f"{prefix}_sample"] = int(data["n"])
                for response in ("fold", "call", "raise"):
                    result[f"{prefix}_{response}"] = (
                        100.0 * int(data[response.upper()]) / total
                    )
            result["pressure_edge"] = result["bot_fold"] - result["pool_fold"]
            result["call_edge"] = result["bot_call"] - result["pool_call"]
            result["raise_edge"] = result["bot_raise"] - result["pool_raise"]
            result["confidence"] = self._confidence(effective)
            result["priority"] = self._priority(
                result["pressure_edge"],
                result["call_edge"],
                result["raise_edge"],
                effective,
            )
            result["finding"] = self._finding(result)
            rows.append(result)

        rows.sort(
            key=lambda row: (float(row["priority"]), abs(float(row["pressure_edge"]))),
            reverse=True,
        )
        return {
            "rows": rows,
            "bot_group": bot_group,
            "node": node,
            "count": len(rows),
            "positive_edges": sum(r["pressure_edge"] >= 3 for r in rows),
            "negative_edges": sum(r["pressure_edge"] <= -3 for r in rows),
            "summary": self._summary(rows, bot_group, self.NODE_LABELS[node]),
            "index": index_info,
        }

    def _build_hand_nodes(
        self,
        hand_id: str,
        hand: dict[str, Any],
        positions: dict[str, str],
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        open_to = 0.0
        for action in actions:
            if action["street"] == "PREFLOP" and action["action"] == "RAISE":
                open_to = action["to_amount"] or action["amount"]
                break

        pot = 0.0
        history: dict[str, list[str]] = defaultdict(list)
        street_actions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for action in actions:
            street_actions[action["street"]].append(action)

        for street in ("FLOP", "TURN", "RIVER"):
            street_list = street_actions.get(street, [])
            for index, aggression in enumerate(street_list):
                if aggression["action"] not in {"BET", "RAISE"}:
                    self._record_history(history, aggression)
                    continue

                responder_action = None
                for candidate in street_list[index + 1:]:
                    if self._key(candidate["player"]) == self._key(aggression["player"]):
                        continue
                    if candidate["action"] in {"FOLD", "CALL", "RAISE"}:
                        responder_action = candidate
                        break
                if responder_action is None:
                    self._record_history(history, aggression)
                    continue

                responder = responder_action["player"]
                aggressor = aggression["player"]
                response = responder_action["action"]
                base = {
                    "hand_id": hand_id,
                    "aggressor": aggressor,
                    "responder": responder,
                    "aggressor_position": positions.get(self._key(aggressor), "?"),
                    "responder_position": positions.get(self._key(responder), "?"),
                    "site": hand.get("site"),
                    "stakes": hand.get("stakes"),
                    "street": street,
                    "response": response,
                    "board_family": self._board_family(str(hand.get("flop") or "")),
                    "open_bucket": self._open_bucket(open_to),
                    "bet_bucket": self._bet_bucket(
                        self._estimated_size_pct(aggression, pot)
                    ),
                }
                rows.append({**base, "node": "ALL_RESPONSES"})

                for node in self._matching_nodes(
                    street,
                    response,
                    history.get(self._key(responder), []),
                    history.get(self._key(aggressor), []),
                    base["responder_position"],
                    base["aggressor_position"],
                ):
                    rows.append({**base, "node": node})

                self._record_history(history, aggression)
                self._record_history(history, responder_action)

            for action in street_list:
                if action["action"] in {"BET", "CALL", "RAISE"}:
                    pot += max(0.0, action["amount"])

        return rows

    @staticmethod
    def _record_history(history: dict[str, list[str]], action: dict[str, Any]) -> None:
        code = {
            "CHECK": "X",
            "CALL": "C",
            "FOLD": "F",
            "RAISE": "R",
            "BET": "B",
        }.get(action["action"])
        if code:
            history[ResponseComparisonService._key(action["player"])].append(
                f"{action['street']}:{code}"
            )

    def _matching_nodes(
        self,
        street: str,
        response: str,
        responder_history: list[str],
        aggressor_history: list[str],
        responder_position: str,
        aggressor_position: str,
    ) -> list[str]:
        result: list[str] = []
        rh = "|".join(responder_history)
        ah = "|".join(aggressor_history)
        oop = self._is_oop(responder_position, aggressor_position)

        if street == "TURN" and response == "FOLD" and oop and "FLOP:X" in rh and "FLOP:C" in rh:
            result.extend(["X_XC_XF_OOP", "XC_XF_OOP"])
        if street == "TURN" and response == "CALL" and oop and "FLOP:X" in rh and "FLOP:C" in rh:
            result.append("XC_XC_OOP")
        if street == "TURN" and response == "RAISE" and oop and "FLOP:X" in rh and "FLOP:C" in rh:
            result.append("XC_XR_OOP")
        if street == "RIVER" and oop and "FLOP:X" in rh and "FLOP:C" in rh and "TURN:C" in rh:
            if response == "FOLD":
                result.append("XC_XC_XF_OOP")
            elif response == "CALL":
                result.extend(["XC_XC_XC_OOP", "RIVER_BLUFF_CATCH"])
            elif response == "RAISE":
                result.extend(["XC_XC_XR_OOP", "RIVER_RAISE"])
        if street == "TURN" and not oop and "FLOP:X" in ah:
            if response == "FOLD":
                result.append("X_C_F_IP")
            elif response == "CALL":
                result.append("X_C_C_IP")
            elif response == "RAISE":
                result.append("X_C_R_IP")
        if street == "TURN" and "FLOP:X" in ah and response in {"FOLD", "CALL", "RAISE"}:
            result.append("PROBE_TURN")
        if street == "TURN" and "FLOP:X" in ah:
            result.append("DELAY_DEFENCE")
        if street == "RIVER" and response == "CALL":
            result.append("RIVER_BLUFF_CATCH")
        if street == "RIVER" and response == "RAISE":
            result.append("RIVER_RAISE")
        return list(dict.fromkeys(result))

    @staticmethod
    def _is_oop(responder_position: str, aggressor_position: str) -> bool:
        order = {"SB": 0, "BB": 1, "UTG": 2, "UTG+1": 3, "HJ": 4, "CO": 5, "BTN": 6}
        return order.get(str(responder_position), -1) < order.get(str(aggressor_position), -1)

    @staticmethod
    def _estimated_size_pct(action: dict[str, Any], pot_before: float) -> float:
        if pot_before <= 0:
            return 0.0
        return 100.0 * max(0.0, float(action.get("amount") or 0)) / pot_before

    @staticmethod
    def _key(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
        return bool(
            con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table],
            ).fetchone()[0]
        )

    @staticmethod
    def _open_bucket(value: float) -> str:
        if value <= 0:
            return "?"
        rounded = round(value * 4) / 4
        return f"{rounded:g}"

    @staticmethod
    def _bet_bucket(value: float) -> str:
        if value <= 0:
            return "UNKNOWN"
        if value < 35:
            return "<35%"
        if value < 55:
            return "35-54%"
        if value < 80:
            return "55-79%"
        if value < 120:
            return "80-119%"
        return "120%+"

    @staticmethod
    def _board_family(flop: str) -> str:
        ranks = re.findall(r"[2-9TJQKA]", flop.upper())
        suits = re.findall(r"[SHDC]", flop.upper())
        if len(ranks) < 3:
            return "UNKNOWN"
        paired = len(set(ranks[:3])) < 3
        monotone = len(suits) >= 3 and len(set(suits[:3])) == 1
        two_tone = len(suits) >= 3 and len(set(suits[:3])) == 2
        high = any(rank in {"A", "K"} for rank in ranks[:3])
        parts = [
            "PAIRED" if paired else "UNPAIRED",
            "MONO" if monotone else ("TWO-TONE" if two_tone else "RAINBOW"),
            "HIGH" if high else "LOW",
        ]
        return " / ".join(parts)

    @staticmethod
    def _confidence(sample: int) -> str:
        if sample >= 2_000:
            return "Çok yüksek"
        if sample >= 750:
            return "Yüksek"
        if sample >= 250:
            return "Orta"
        return "Düşük"

    @staticmethod
    def _priority(pressure: float, call: float, raise_edge: float, sample: int) -> float:
        effect = abs(pressure) + 0.35 * abs(call) + 0.50 * abs(raise_edge)
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
    def _summary(rows: list[dict[str, Any]], group: str, node_label: str) -> str:
        if not rows:
            return f"{group} / {node_label}: minimum sample koşulunu geçen spot bulunamadı."
        top = rows[0]
        return (
            f"{group} / {node_label}: {len(rows)} karşılaştırılabilir spot. "
            f"En yüksek öncelik: {top['position']} / {top['board']} / {top['spot']}."
        )
