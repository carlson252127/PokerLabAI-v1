from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable
import math
import os
import re

import duckdb
import pyarrow as pa

from services.response_node_schema import ensure_response_node_schema
from services.canonical_wws_engine import CanonicalWWSEngine


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

    def heroes(self, limit: int = 500) -> list[tuple[str, int]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT CASE
                    WHEN h.site = 'CoinPoker'
                     AND LOWER(TRIM(hp.player_name)) = 'hero'
                    THEN 'PashaLevo'
                    ELSE hp.player_name
                END AS player_name,
                COUNT(DISTINCT hp.hand_id) AS hands
                FROM hand_players hp
                JOIN hands h USING (hand_id)
                WHERE hp.player_name IS NOT NULL
                  AND TRIM(hp.player_name) <> ''
                GROUP BY 1
                ORDER BY hands DESC, 1
                LIMIT ?
                """,
                [max(1, int(limit))],
            ).fetchall()
        return [(str(name), int(hands or 0)) for name, hands in rows]

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

    def ensure_index(
        self,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Index all missing hands using small, transaction-safe batches."""
        with self.connect() as con:
            self._ensure_tables(con)
            added_hands = 0
            added_nodes = 0
            cancelled = False

            total = int(con.execute("SELECT COUNT(*) FROM hands").fetchone()[0])
            indexed_at_start = int(
                con.execute(
                    "SELECT COUNT(*) FROM response_node_v4_indexed_hands"
                ).fetchone()[0]
            )

            # Materialize the missing set once.  The previous implementation
            # reran the full hands/marker ANTI JOIN for every 5,000-hand batch.
            # On multi-million-hand databases that changed a linear backfill
            # into thousands of repeated full-table discovery scans.
            con.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE response_v4_pending AS
                SELECT
                    ROW_NUMBER() OVER () AS pending_row,
                    h.hand_id
                FROM hands h
                ANTI JOIN response_node_v4_indexed_hands i USING (hand_id)
                """
            )
            pending = int(
                con.execute(
                    "SELECT COUNT(*) FROM response_v4_pending"
                ).fetchone()[0]
            )
            if progress_callback is not None:
                progress_callback({
                    "phase": "index",
                    "completed": 0,
                    "pending": pending,
                    "total": total,
                    "indexed": indexed_at_start,
                    "added_nodes": 0,
                })

            for start_row in range(1, pending + 1, self.batch_size):
                if should_cancel is not None and should_cancel():
                    cancelled = True
                    break
                ids = [
                    str(row[0])
                    for row in con.execute(
                        """
                        SELECT hand_id
                        FROM response_v4_pending
                        WHERE pending_row BETWEEN ? AND ?
                        ORDER BY pending_row
                        """,
                        [start_row, start_row + self.batch_size - 1],
                    ).fetchall()
                ]
                if not ids:
                    continue

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
                incoming_nodes_registered = False
                indexed_batch_registered = False
                try:
                    if node_rows:
                        con.register(
                            "incoming_response_nodes",
                            pa.Table.from_pylist(node_rows),
                        )
                        incoming_nodes_registered = True
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
                    con.register(
                        "indexed_response_batch",
                        pa.Table.from_pylist([{"hand_id": value} for value in ids]),
                    )
                    indexed_batch_registered = True
                    con.execute(
                        """
                        INSERT INTO response_node_v4_indexed_hands
                        SELECT hand_id FROM indexed_response_batch
                        ON CONFLICT (hand_id) DO NOTHING
                        """
                    )
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                finally:
                    if indexed_batch_registered:
                        con.unregister("indexed_response_batch")
                    if incoming_nodes_registered:
                        con.unregister("incoming_response_nodes")

                added_hands += len(ids)
                added_nodes += len(node_rows)
                if progress_callback is not None:
                    progress_callback({
                        "phase": "index",
                        "completed": added_hands,
                        "pending": pending,
                        "total": total,
                        "indexed": indexed_at_start + added_hands,
                        "added_nodes": added_nodes,
                    })

                # Drop batch-sized Python/Arrow references before the next
                # extraction so adjacent batches do not overlap in memory.
                del id_table, hands, positions, actions, node_rows, ids

            indexed = int(
                con.execute(
                    "SELECT COUNT(*) FROM response_node_v4_indexed_hands"
                ).fetchone()[0]
            )
            nodes = int(
                con.execute(
                    """
                    SELECT COUNT(*) FROM response_nodes
                    WHERE aggressor IS NOT NULL
                    """
                ).fetchone()[0]
            )
            status: dict[str, Any] = {
                "total": total,
                "indexed": indexed,
                "pending": max(0, total - indexed),
                "nodes": nodes,
                "cancelled": cancelled,
            }
            status["added_hands"] = added_hands
            status["added_nodes"] = added_nodes
            return status

    def analyze(
        self,
        bot_group: str,
        hero_name: str,
        node: str = "ALL_RESPONSES",
        site: str = "",
        stakes: str = "",
        position: str = "",
        minimum_sample: int = 50,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Hero / clean Pool / selected Bot / Winning Regs comparison.

        Winning Regs: hands >= 10,000, winrate >= +1 bb/100,
        WWS between -5 and +20 bb/100, not Hero and not any bot.
        """
        if not bot_group:
            raise ValueError("Bot group seçilmedi.")
        hero_name = str(hero_name or "").strip()
        if not hero_name:
            raise ValueError("Hero seçilmedi.")
        if node not in self.NODE_LABELS:
            raise ValueError(f"Desteklenmeyen node: {node}")

        index_info = self.ensure_index(progress_callback, should_cancel)
        if index_info.get("cancelled"):
            return {
                "rows": [], "bot_group": bot_group,
                "hero_name": hero_name, "node": node, "count": 0,
                "positive_edges": 0, "negative_edges": 0,
                "summary": "İndeksleme durduruldu; sonraki çalıştırma kaldığı yerden devam eder.",
                "index": index_info,
            }
        if progress_callback is not None:
            progress_callback({
                "phase": "comparison", "completed": index_info["indexed"],
                "pending": index_info["pending"], "total": index_info["total"],
                "indexed": index_info["indexed"],
                "added_nodes": index_info["added_nodes"],
            })

        minimum_sample = max(1, int(minimum_sample))
        hero_key = self._key(hero_name)
        rn_filters = ["rn.node = ?"]
        rn_params: list[Any] = [node]
        perf_filters: list[str] = []
        perf_params: list[Any] = []
        if site:
            rn_filters.append("rn.site = ?")
            rn_params.append(site)
            perf_filters.append("c.site = ?")
            perf_params.append(site)
        if stakes:
            rn_filters.append("rn.stakes = ?")
            rn_params.append(stakes)
            perf_filters.append("c.stakes = ?")
            perf_params.append(stakes)
        if position:
            rn_filters.append("rn.aggressor_position = ?")
            rn_params.append(position)
        filtered_filters = [item.replace("rn.", "") for item in rn_filters]
        filtered_where = " AND ".join(filtered_filters)
        perf_where = "WHERE " + " AND ".join(perf_filters) if perf_filters else ""
        canonical_sql = CanonicalWWSEngine.sql_cte()

        with self.connect() as con:
            self._ensure_tables(con)
            raw, meta = self._run_comparison_query(
                con,
                bot_group=bot_group,
                hero_key=hero_key,
                filtered_where=filtered_where,
                perf_where=perf_where,
                canonical_sql=canonical_sql,
                rn_params=rn_params,
                perf_params=perf_params,
                minimum_sample=minimum_sample,
            )

        rows = self._build_comparison_rows(raw, minimum_sample)
        wp,wh,wbb,wwws=int(meta[0] or 0),int(meta[1] or 0),float(meta[2] or 0),float(meta[3] or 0)
        return {
            "rows":rows,"bot_group":bot_group,"hero_name":hero_name,"node":node,"count":len(rows),
            "positive_edges":sum(r["bot_pool_fold_delta"]>=3 for r in rows),
            "negative_edges":sum(r["bot_pool_fold_delta"]<=-3 for r in rows),
            "winning_regs":{"players":wp,"hands":wh,"bb100":wbb,"wws_bb100":wwws},
            "summary":self._summary_v5(rows,bot_group,hero_name,self.NODE_LABELS[node],wp,wh,wbb,wwws),
            "index":index_info,
        }

    def _run_comparison_query(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        bot_group: str,
        hero_key: str,
        filtered_where: str,
        perf_where: str,
        canonical_sql: str,
        rn_params: list[Any],
        perf_params: list[Any],
        minimum_sample: int,
    ) -> tuple[list[tuple[Any, ...]], tuple[Any, ...]]:
        """Materialize cohort tables once, then aggregate filtered nodes."""
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE rc_canonical_wws AS {canonical_sql}"
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE rc_performance AS
            SELECT CASE
                WHEN c.site='CoinPoker' AND LOWER(TRIM(c.source_player))='hero'
                THEN 'pashalevo' ELSE LOWER(TRIM(c.source_player)) END player_key,
                COUNT(*) FILTER (WHERE c.denominator_included) hands,
                SUM(CASE WHEN c.denominator_included THEN COALESCE(c.net_bb,0) ELSE 0 END) net_bb,
                SUM(CASE WHEN c.denominator_included THEN COALESCE(c.non_showdown_bb,0) ELSE 0 END) wws_bb
            FROM rc_canonical_wws c
            {perf_where}
            GROUP BY 1
            """,
            perf_params,
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE rc_all_bots AS
            SELECT DISTINCT LOWER(TRIM(player_name)) player_key
            FROM bot_group_members
            WHERE player_name IS NOT NULL
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE rc_selected_bots AS
            SELECT DISTINCT LOWER(TRIM(bgm.player_name)) player_key
            FROM bot_group_members bgm
            JOIN bot_groups bg ON bg.group_id = bgm.group_id
            WHERE bg.name = ?
            """,
            [bot_group],
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE rc_winning_regs AS
            SELECT p.player_key, p.hands, p.net_bb, p.wws_bb
            FROM rc_performance p
            LEFT JOIN rc_all_bots ab USING(player_key)
            WHERE p.hands >= 10000
              AND 100.0 * p.net_bb / NULLIF(p.hands, 0) >= 1.0
              AND 100.0 * p.wws_bb / NULLIF(p.hands, 0) BETWEEN -5.0 AND 20.0
              AND ab.player_key IS NULL
              AND p.player_key <> ?
            """,
            [hero_key],
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE rc_filtered_nodes AS
            SELECT
                LOWER(TRIM(aggressor)) AS aggressor_key,
                CASE
                    WHEN site = 'CoinPoker' AND LOWER(TRIM(aggressor)) = 'hero'
                    THEN 'pashalevo'
                    ELSE LOWER(TRIM(aggressor))
                END AS perf_key,
                site,
                aggressor_position,
                open_bucket,
                board_family,
                street,
                bet_bucket,
                response
            FROM response_nodes
            WHERE {filtered_where}
              AND aggressor IS NOT NULL
            """,
            rn_params,
        )

        raw = con.execute(
            """
            WITH classified AS (
                SELECT CASE
                    WHEN rn.aggressor_key = ?
                      OR (? = 'pashalevo'
                          AND rn.site = 'CoinPoker'
                          AND rn.aggressor_key = 'hero') THEN 'HERO'
                    WHEN sb.player_key IS NOT NULL THEN 'BOT'
                    WHEN wr.player_key IS NOT NULL THEN 'WINNING'
                    WHEN ab.player_key IS NULL THEN 'POOL'
                    ELSE NULL END cohort,
                    rn.aggressor_position,
                    rn.open_bucket,
                    rn.board_family,
                    rn.street,
                    rn.bet_bucket,
                    rn.response
                FROM rc_filtered_nodes rn
                LEFT JOIN rc_selected_bots sb
                  ON sb.player_key = rn.aggressor_key
                LEFT JOIN rc_all_bots ab
                  ON ab.player_key = rn.aggressor_key
                LEFT JOIN rc_winning_regs wr
                  ON wr.player_key = rn.perf_key
            ),
            counts AS (
                SELECT cohort, aggressor_position, open_bucket, board_family,
                       street, bet_bucket, response, COUNT(*) AS cnt
                FROM classified
                WHERE cohort IS NOT NULL
                GROUP BY ALL
            ),
            spots AS (
                SELECT
                    COALESCE(aggressor_position, '?') AS position,
                    COALESCE(open_bucket, '?') AS open_size,
                    COALESCE(board_family, 'UNKNOWN') AS board,
                    street || ' ' || bet_bucket AS spot,
                    SUM(CASE WHEN cohort = 'HERO' AND UPPER(response) = 'FOLD'
                        THEN cnt ELSE 0 END) AS hero_fold,
                    SUM(CASE WHEN cohort = 'HERO' AND UPPER(response) = 'CALL'
                        THEN cnt ELSE 0 END) AS hero_call,
                    SUM(CASE WHEN cohort = 'HERO' AND UPPER(response) = 'RAISE'
                        THEN cnt ELSE 0 END) AS hero_raise,
                    SUM(CASE WHEN cohort = 'HERO' THEN cnt ELSE 0 END) AS hero_sample,
                    SUM(CASE WHEN cohort = 'POOL' AND UPPER(response) = 'FOLD'
                        THEN cnt ELSE 0 END) AS pool_fold,
                    SUM(CASE WHEN cohort = 'POOL' AND UPPER(response) = 'CALL'
                        THEN cnt ELSE 0 END) AS pool_call,
                    SUM(CASE WHEN cohort = 'POOL' AND UPPER(response) = 'RAISE'
                        THEN cnt ELSE 0 END) AS pool_raise,
                    SUM(CASE WHEN cohort = 'POOL' THEN cnt ELSE 0 END) AS pool_sample,
                    SUM(CASE WHEN cohort = 'BOT' AND UPPER(response) = 'FOLD'
                        THEN cnt ELSE 0 END) AS bot_fold,
                    SUM(CASE WHEN cohort = 'BOT' AND UPPER(response) = 'CALL'
                        THEN cnt ELSE 0 END) AS bot_call,
                    SUM(CASE WHEN cohort = 'BOT' AND UPPER(response) = 'RAISE'
                        THEN cnt ELSE 0 END) AS bot_raise,
                    SUM(CASE WHEN cohort = 'BOT' THEN cnt ELSE 0 END) AS bot_sample,
                    SUM(CASE WHEN cohort = 'WINNING' AND UPPER(response) = 'FOLD'
                        THEN cnt ELSE 0 END) AS winning_fold,
                    SUM(CASE WHEN cohort = 'WINNING' AND UPPER(response) = 'CALL'
                        THEN cnt ELSE 0 END) AS winning_call,
                    SUM(CASE WHEN cohort = 'WINNING' AND UPPER(response) = 'RAISE'
                        THEN cnt ELSE 0 END) AS winning_raise,
                    SUM(CASE WHEN cohort = 'WINNING' THEN cnt ELSE 0 END) AS winning_sample
                FROM counts
                GROUP BY 1, 2, 3, 4
            )
            SELECT *
            FROM spots
            WHERE LEAST(bot_sample, pool_sample) >= ?
            ORDER BY LEAST(bot_sample, pool_sample) DESC
            """,
            [hero_key, hero_key, minimum_sample],
        ).fetchall()

        meta = con.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(hands), 0),
                   COALESCE(100.0 * SUM(net_bb) / NULLIF(SUM(hands), 0), 0),
                   COALESCE(100.0 * SUM(wws_bb) / NULLIF(SUM(hands), 0), 0)
            FROM rc_winning_regs
            """
        ).fetchone()
        return raw, meta

    @staticmethod
    def _build_comparison_rows(
        raw: list[tuple[Any, ...]],
        minimum_sample: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (
            position,
            open_size,
            board,
            spot,
            hero_fold_n,
            hero_call_n,
            hero_raise_n,
            hero_sample,
            pool_fold_n,
            pool_call_n,
            pool_raise_n,
            pool_sample,
            bot_fold_n,
            bot_call_n,
            bot_raise_n,
            bot_sample,
            winning_fold_n,
            winning_call_n,
            winning_raise_n,
            winning_sample,
        ) in raw:
            effective = min(int(bot_sample or 0), int(pool_sample or 0))
            if effective < minimum_sample:
                continue
            result: dict[str, Any] = {
                "position": str(position),
                "open_size": str(open_size),
                "board": str(board),
                "spot": str(spot),
            }
            cohort_counts = {
                "hero": (hero_fold_n, hero_call_n, hero_raise_n, hero_sample),
                "pool": (pool_fold_n, pool_call_n, pool_raise_n, pool_sample),
                "bot": (bot_fold_n, bot_call_n, bot_raise_n, bot_sample),
                "winning": (
                    winning_fold_n,
                    winning_call_n,
                    winning_raise_n,
                    winning_sample,
                ),
            }
            for prefix, (fold_n, call_n, raise_n, sample) in cohort_counts.items():
                total = int(sample or 0)
                result[f"{prefix}_sample"] = total
                result[f"{prefix}_fold"] = (
                    100.0 * int(fold_n or 0) / total if total else 0.0
                )
                result[f"{prefix}_call"] = (
                    100.0 * int(call_n or 0) / total if total else 0.0
                )
                result[f"{prefix}_raise"] = (
                    100.0 * int(raise_n or 0) / total if total else 0.0
                )
            result["hero_pool_fold_delta"] = result["hero_fold"] - result["pool_fold"]
            result["bot_pool_fold_delta"] = result["bot_fold"] - result["pool_fold"]
            result["winning_pool_fold_delta"] = (
                result["winning_fold"] - result["pool_fold"]
            )
            result["bot_winning_fold_delta"] = (
                result["bot_fold"] - result["winning_fold"]
            )
            result["pressure_edge"] = result["bot_pool_fold_delta"]
            result["call_edge"] = result["bot_call"] - result["pool_call"]
            result["raise_edge"] = result["bot_raise"] - result["pool_raise"]
            result["confidence"] = ResponseComparisonService._confidence(effective)
            result["priority"] = ResponseComparisonService._priority(
                result["pressure_edge"],
                result["call_edge"],
                result["raise_edge"],
                effective,
            )
            result["finding"] = ResponseComparisonService._finding_v5(result)
            rows.append(result)
        rows.sort(
            key=lambda r: (float(r["priority"]), abs(float(r["bot_pool_fold_delta"]))),
            reverse=True,
        )
        return rows

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

    def build_parsed_hand_nodes(
        self,
        item: dict[str, Any],
        hand_id: str,
    ) -> list[dict[str, Any]]:
        """Build canonical V4 rows directly from an import parser item."""
        hand = item.get("hand", item)
        positions = {
            self._key(row.get("player_name") or row.get("name")):
            str(row.get("position") or "?")
            for row in item.get("players", [])
        }
        actions = [
            {
                "sequence": int(
                    row.get("sequence_no")
                    if row.get("sequence_no") is not None
                    else row.get("action_order") or 0
                ),
                "street": str(row.get("street") or "").upper().strip(),
                "player": str(
                    row.get("player_name") or row.get("player") or ""
                ),
                "action": str(
                    row.get("action") or row.get("action_type") or ""
                ).upper().strip(),
                "amount": float(row.get("amount") or 0),
                "to_amount": float(row.get("to_amount") or 0),
            }
            for row in item.get("actions", [])
        ]
        actions.sort(key=lambda row: row["sequence"])
        return self._build_hand_nodes(
            hand_id,
            {
                "site": hand.get("site"),
                "stakes": hand.get("stakes"),
                "flop": hand.get("flop"),
                "turn": hand.get("turn"),
                "river": hand.get("river"),
            },
            positions,
            actions,
        )

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
    def _finding_v5(row: dict[str, Any]) -> str:
        parts: list[str] = []
        if row["bot_pool_fold_delta"] >= 5: parts.append("Botlar Pool'dan daha fazla fold ediyor")
        elif row["bot_pool_fold_delta"] <= -5: parts.append("Botlar Pool'dan daha az fold ediyor")
        if row["winning_pool_fold_delta"] >= 5: parts.append("Winning Regs Pool'dan daha fazla fold ediyor")
        elif row["winning_pool_fold_delta"] <= -5: parts.append("Winning Regs Pool'dan daha az fold ediyor")
        if row.get("hero_sample",0):
            d=row["hero_fold"]-row["winning_fold"]
            if d>=5: parts.append("Hero Winning Regs'ten daha fazla fold ediyor")
            elif d<=-5: parts.append("Hero Winning Regs'ten daha az fold ediyor")
        return " • ".join(parts) if parts else "Gruplar arasında büyük fold farkı yok"

    @staticmethod
    def _summary_v5(rows: list[dict[str, Any]], group: str, hero: str, node_label: str, players: int, hands: int, bb100: float, wws: float) -> str:
        meta=f"Winning Regs: {players:,} oyuncu, {hands:,} el, {bb100:+.2f} bb/100, WWS {wws:+.2f} bb/100."
        if not rows: return f"{hero} / {group} / {node_label}: minimum sample koşulunu geçen spot yok. {meta}"
        top=rows[0]
        return f"{hero} / Pool / {group} / Winning Regs — {node_label}: {len(rows)} spot. En yüksek öncelik: {top['position']} / {top['board']} / {top['spot']}. {meta}"

    @staticmethod
    def _summary(rows: list[dict[str, Any]], group: str, node_label: str) -> str:
        if not rows:
            return f"{group} / {node_label}: minimum sample koşulunu geçen spot bulunamadı."
        top = rows[0]
        return (
            f"{group} / {node_label}: {len(rows)} karşılaştırılabilir spot. "
            f"En yüksek öncelik: {top['position']} / {top['board']} / {top['spot']}."
        )
