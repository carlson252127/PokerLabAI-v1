from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import os
from typing import Iterable

import duckdb
import pyarrow as pa

from services.response_node_schema import ensure_response_node_schema


class AnalyticalStore:
    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = str(path)
        self.create_tables()

    def connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(self.database_path)
        thread_count = max(4, min(16, os.cpu_count() or 4))
        con.execute(f"PRAGMA threads={thread_count}")
        con.execute("SET preserve_insertion_order = false")
        return con

    def create_tables(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hands (
                    hand_id VARCHAR PRIMARY KEY,
                    site VARCHAR,
                    table_name VARCHAR,
                    stakes VARCHAR,
                    played_at VARCHAR,
                    max_players INTEGER,
                    button_seat INTEGER,
                    flop VARCHAR,
                    turn VARCHAR,
                    river VARCHAR,
                    pot DOUBLE,
                    rake DOUBLE,
                    source_file VARCHAR,
                    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hand_players (
                    hand_id VARCHAR,
                    seat_no INTEGER,
                    player_name VARCHAR,
                    starting_stack DOUBLE,
                    position VARCHAR
                )
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    hand_id VARCHAR,
                    sequence_no INTEGER,
                    street VARCHAR,
                    player_name VARCHAR,
                    action VARCHAR,
                    amount DOUBLE,
                    to_amount DOUBLE,
                    all_in BOOLEAN,
                    cards VARCHAR
                )
                """
            )

            ensure_response_node_schema(con)

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS response_node_meta (
                    meta_key VARCHAR PRIMARY KEY,
                    meta_value VARCHAR,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS response_node_indexed_hands (
                    hand_id VARCHAR PRIMARY KEY
                )
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS imported_files (
                    file_path VARCHAR PRIMARY KEY,
                    file_size BIGINT,
                    modified_ns BIGINT,
                    parsed_hands BIGINT,
                    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self._ensure_column(
                con,
                "hand_players",
                "position",
                "VARCHAR",
            )
            self._ensure_column(
                con,
                "actions",
                "all_in",
                "BOOLEAN",
            )
            self._ensure_column(
                con,
                "actions",
                "cards",
                "VARCHAR",
            )

            # hands.hand_id PRIMARY KEY already owns an implicit ART index.
            # Older builds also created this explicit duplicate, doubling
            # index maintenance during large imports.
            con.execute("DROP INDEX IF EXISTS idx_hands_hand_id")
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_players_hand_id
                ON hand_players(hand_id)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_players_name
                ON hand_players(player_name)
                """
            )
            # position and street contain only a handful of distinct values.
            # ART indexes are intended for highly selective lookups; keeping
            # these two low-cardinality indexes adds substantial maintenance
            # to every imported player/action row without helping analytical
            # scans. Remove indexes left by earlier builds.
            con.execute("DROP INDEX IF EXISTS idx_players_position")
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_actions_hand_id
                ON actions(hand_id)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_actions_player
                ON actions(player_name)
                """
            )
            con.execute("DROP INDEX IF EXISTS idx_actions_street")
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_response_nodes_node
                ON response_nodes(node)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_response_nodes_player
                ON response_nodes(player_name)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_response_nodes_hand
                ON response_nodes(hand_id)
                """
            )

    def _ensure_column(
        self,
        con: duckdb.DuckDBPyConnection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        columns = {
            row[1]
            for row in con.execute(
                f"PRAGMA table_info('{table_name}')"
            ).fetchall()
        }

        if column_name not in columns:
            con.execute(
                f'ALTER TABLE "{table_name}" '
                f'ADD COLUMN "{column_name}" {column_type}'
            )

    def pending_files(self, files: Iterable[str]) -> tuple[list[str], int]:
        """Return changed/new files and count of unchanged cached files."""
        file_list = [str(Path(path).resolve()) for path in files]
        if not file_list:
            return [], 0

        with self.connect() as con:
            cached = {
                row[0]: (int(row[1] or 0), int(row[2] or 0))
                for row in con.execute(
                    "SELECT file_path, file_size, modified_ns FROM imported_files"
                ).fetchall()
            }

        pending: list[str] = []
        unchanged = 0
        for path in file_list:
            try:
                stat = Path(path).stat()
            except OSError:
                pending.append(path)
                continue
            signature = (int(stat.st_size), int(stat.st_mtime_ns))
            if cached.get(path) == signature:
                unchanged += 1
            else:
                pending.append(path)
        return pending, unchanged

    def mark_files_imported(
        self,
        file_records: list[tuple[str, int]],
        con: duckdb.DuckDBPyConnection,
    ) -> None:
        if not file_records:
            return
        rows = []
        for path, parsed_hands in file_records:
            resolved = str(Path(path).resolve())
            try:
                stat = Path(resolved).stat()
                size = int(stat.st_size)
                modified_ns = int(stat.st_mtime_ns)
            except OSError:
                size = 0
                modified_ns = 0
            rows.append({
                "file_path": resolved,
                "file_size": size,
                "modified_ns": modified_ns,
                "parsed_hands": int(parsed_hands),
            })

        imported_at = datetime.now(timezone.utc).replace(tzinfo=None)
        for row in rows:
            row["imported_at"] = imported_at

        table = pa.Table.from_pylist(rows)
        con.register("incoming_file_registry", table)
        try:
            # DuckDB'nin bazı sürümlerinde CURRENT_TIMESTAMP, ON CONFLICT
            # bölümünde hedef tablo kolonu gibi bağlanabiliyor. Zamanı Python'dan
            # taşıyıp EXCLUDED üzerinden kullanmak bütün desteklenen sürümlerde
            # güvenlidir.
            con.execute(
                """
                INSERT INTO imported_files (
                    file_path, file_size, modified_ns, parsed_hands, imported_at
                )
                SELECT
                    file_path, file_size, modified_ns, parsed_hands, imported_at
                FROM incoming_file_registry
                ON CONFLICT (file_path) DO UPDATE SET
                    file_size = EXCLUDED.file_size,
                    modified_ns = EXCLUDED.modified_ns,
                    parsed_hands = EXCLUDED.parsed_hands,
                    imported_at = EXCLUDED.imported_at
                """
            )
        finally:
            try:
                con.unregister("incoming_file_registry")
            except Exception:
                pass

    @staticmethod
    def _board_family(text: str | None) -> str:
        import re as _re

        cards = _re.findall(r"([2-9TJQKA])([shdc])", str(text or ""), _re.I)
        if len(cards) < 3:
            return "Unknown"
        ranks = ["23456789TJQKA".index(rank.upper()) + 2 for rank, _ in cards[:3]]
        suits = [suit.lower() for _, suit in cards[:3]]
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
            return "K/Q/J-high Dynamic" if connected else "K/Q/J-high Dry"
        if high >= 8:
            return "Mid Connected" if connected else "Mid Dry"
        return "Low Connected" if connected else "Low Dry"

    @staticmethod
    def _response_node_rows(item: dict, hand_id: str) -> list[dict]:
        """Build compact response-node rows while the hand is already in memory.

        This avoids repeatedly scanning and multiplying the full actions table
        when Response Comparison is opened.
        """
        hand = item.get("hand", item)
        site = hand.get("site")
        stakes = hand.get("stakes")
        board_family = AnalyticalStore._board_family(hand.get("flop"))

        positions = {
            str(row.get("player_name") or row.get("name") or ""):
            str(row.get("position") or "")
            for row in item.get("players", [])
        }

        by_player: dict[str, dict[str, list[str]]] = {}
        ordered_actions = sorted(
            item.get("actions", []),
            key=lambda row: int(
                row.get("sequence_no")
                if row.get("sequence_no") is not None
                else row.get("action_order") or 0
            ),
        )

        for action_row in ordered_actions:
            player = str(
                action_row.get("player_name")
                or action_row.get("player")
                or ""
            ).strip()
            street = str(action_row.get("street") or "").upper().strip()
            action = str(
                action_row.get("action")
                or action_row.get("action_type")
                or ""
            ).upper().strip()
            if not player or street not in {"FLOP", "TURN", "RIVER"}:
                continue
            if action not in {"CHECK", "BET", "CALL", "RAISE", "FOLD"}:
                continue
            by_player.setdefault(
                player,
                {"FLOP": [], "TURN": [], "RIVER": []},
            )[street].append(action)

        rows: list[dict] = []

        def add(player: str, node: str, response: str) -> None:
            rows.append({
                "hand_id": hand_id,
                "player_name": player,
                "position": positions.get(player, ""),
                "site": site,
                "stakes": stakes,
                "node": node,
                "response": response,
                "board_family": board_family,
            })

        for player, streets in by_player.items():
            flop = streets["FLOP"]
            turn = streets["TURN"]
            river = streets["RIVER"]

            for street_actions in (flop, turn, river):
                for action in street_actions:
                    if action in {"FOLD", "CALL", "RAISE"}:
                        add(player, "ALL_RESPONSES", action)

            has = lambda actions, value: value in actions
            last = lambda actions: actions[-1] if actions else ""

            if has(flop, "CHECK") and has(flop, "CALL") and has(turn, "CHECK") and last(river) == "FOLD":
                add(player, "X_XC_XF_OOP", "FOLD")
            if has(flop, "CHECK") and has(turn, "CALL") and last(river) == "FOLD":
                add(player, "X_C_F_IP", "FOLD")
            if has(flop, "CHECK") and has(flop, "CALL") and has(turn, "CHECK") and last(turn) == "FOLD":
                add(player, "XC_XF_OOP", "FOLD")
            if has(flop, "CHECK") and has(flop, "CALL") and has(turn, "CHECK") and has(turn, "CALL"):
                add(player, "XC_XC_OOP", "CALL")
            if has(flop, "CHECK") and has(flop, "CALL") and has(turn, "CHECK") and has(turn, "RAISE"):
                add(player, "XC_XR_OOP", "RAISE")
            if has(flop, "CALL") and has(turn, "CALL") and has(river, "CHECK") and last(river) == "FOLD":
                add(player, "XC_XC_XF_OOP", "FOLD")
            if has(flop, "CALL") and has(turn, "CALL") and has(river, "CHECK") and has(river, "CALL"):
                add(player, "XC_XC_XC_OOP", "CALL")
            if has(flop, "CALL") and has(turn, "CALL") and has(river, "CHECK") and has(river, "RAISE"):
                add(player, "XC_XC_XR_OOP", "RAISE")
            if has(flop, "CHECK") and has(turn, "CALL") and has(river, "CALL"):
                add(player, "X_C_C_IP", "CALL")
            if has(flop, "CHECK") and has(turn, "CALL") and has(river, "RAISE"):
                add(player, "X_C_R_IP", "RAISE")
            if has(flop, "CHECK") and has(turn, "BET"):
                add(player, "PROBE_TURN", "RAISE")
            if has(flop, "CHECK") and any(value in turn for value in ("FOLD", "CALL", "RAISE")):
                outcome = "FOLD" if "FOLD" in turn else "RAISE" if "RAISE" in turn else "CALL"
                add(player, "DELAY_DEFENCE", outcome)
            if has(river, "CALL"):
                add(player, "RIVER_BLUFF_CATCH", "CALL")
            if has(river, "RAISE"):
                add(player, "RIVER_RAISE", "RAISE")

        return rows

    def insert_parsed_batch(
        self,
        parsed_hands: list[dict],
        con: duckdb.DuckDBPyConnection | None = None,
    ) -> tuple[int, int]:
        """Insert genuinely new hands with one conflict-aware bulk statement.

        The previous implementation anti-joined every incoming batch against
        the full, continuously growing hands table. Using the PRIMARY KEY's
        conflict handling avoids that repeated full-table work and RETURNING
        gives us exactly the hand IDs whose child rows must be inserted.
        """
        if not parsed_hands:
            return 0, 0

        unique_items: dict[str, dict] = {}
        for item in parsed_hands:
            hand = item.get("hand", item)
            hand_id = str(hand.get("hand_id") or "").strip()
            if hand_id and hand_id not in unique_items:
                unique_items[hand_id] = item

        if not unique_items:
            return 0, len(parsed_hands)

        hands_rows: list[dict] = []
        for hand_id, item in unique_items.items():
            hand = item.get("hand", item)
            hands_rows.append({
                "hand_id": hand_id,
                "site": hand.get("site"),
                "table_name": hand.get("table_name") or hand.get("table"),
                "stakes": hand.get("stakes"),
                "played_at": hand.get("played_at"),
                "max_players": hand.get("max_players"),
                "button_seat": hand.get("button_seat"),
                "flop": hand.get("flop"),
                "turn": hand.get("turn"),
                "river": hand.get("river"),
                "pot": hand.get("pot"),
                "rake": hand.get("rake"),
                "source_file": hand.get("source_file"),
            })

        own_connection = con is None
        db = con or self.connect()
        registered_tables: list[str] = []
        own_transaction = False
        try:
            if own_connection:
                db.execute("BEGIN TRANSACTION")
                own_transaction = True

            db.register("incoming_all_hands", pa.Table.from_pylist(hands_rows))
            registered_tables.append("incoming_all_hands")
            new_ids = {
                str(row[0])
                for row in db.execute(
                    """
                    INSERT INTO hands (
                        hand_id, site, table_name, stakes, played_at,
                        max_players, button_seat, flop, turn, river,
                        pot, rake, source_file, imported_at
                    )
                    SELECT
                        hand_id, site, table_name, stakes, played_at,
                        max_players, button_seat, flop, turn, river,
                        pot, rake, source_file, CURRENT_TIMESTAMP
                    FROM incoming_all_hands
                    ON CONFLICT (hand_id) DO NOTHING
                    RETURNING hand_id
                    """
                ).fetchall()
            }

            if not new_ids:
                if own_transaction:
                    db.execute("COMMIT")
                    own_transaction = False
                return 0, len(parsed_hands)

            players_rows: list[dict] = []
            actions_rows: list[dict] = []
            response_rows: list[dict] = []
            for hand_id in new_ids:
                item = unique_items[hand_id]
                response_rows.extend(
                    self._response_node_rows(item, hand_id)
                )
                for row in item.get("players", []):
                    players_rows.append({
                        "hand_id": hand_id,
                        "seat_no": row.get("seat_no") if row.get("seat_no") is not None else row.get("seat"),
                        "player_name": row.get("player_name") or row.get("name"),
                        "starting_stack": row.get("starting_stack") if row.get("starting_stack") is not None else row.get("stack"),
                        "position": row.get("position"),
                    })
                for row in item.get("actions", []):
                    actions_rows.append({
                        "hand_id": hand_id,
                        "sequence_no": row.get("sequence_no") if row.get("sequence_no") is not None else row.get("action_order"),
                        "street": row.get("street"),
                        "player_name": row.get("player_name") or row.get("player"),
                        "action": row.get("action") or row.get("action_type"),
                        "amount": row.get("amount"),
                        "to_amount": row.get("to_amount"),
                        "all_in": bool(row.get("all_in", False)),
                        "cards": row.get("cards"),
                    })

            if players_rows:
                db.register("incoming_players", pa.Table.from_pylist(players_rows))
                registered_tables.append("incoming_players")
                db.execute(
                    """
                    INSERT INTO hand_players
                    SELECT hand_id, seat_no, player_name, starting_stack, position
                    FROM incoming_players
                    """
                )

            if actions_rows:
                db.register("incoming_actions", pa.Table.from_pylist(actions_rows))
                registered_tables.append("incoming_actions")
                db.execute(
                    """
                    INSERT INTO actions
                    SELECT hand_id, sequence_no, street, player_name,
                           action, amount, to_amount, all_in, cards
                    FROM incoming_actions
                    """
                )

            indexed_hand_rows = [
                {"hand_id": hand_id}
                for hand_id in new_ids
            ]
            if indexed_hand_rows:
                db.register(
                    "incoming_response_indexed_hands",
                    pa.Table.from_pylist(indexed_hand_rows),
                )
                registered_tables.append("incoming_response_indexed_hands")
                db.execute(
                    """
                    INSERT INTO response_node_indexed_hands
                    SELECT hand_id
                    FROM incoming_response_indexed_hands
                    ON CONFLICT (hand_id) DO NOTHING
                    """
                )

            if response_rows:
                db.register(
                    "incoming_response_nodes",
                    pa.Table.from_pylist(response_rows),
                )
                registered_tables.append("incoming_response_nodes")
                db.execute(
                    """
                    INSERT INTO response_nodes (
                        hand_id, player_name, position, site, stakes,
                        node, response, board_family
                    )
                    SELECT hand_id, player_name, position, site, stakes,
                           node, response, board_family
                    FROM incoming_response_nodes
                    """
                )

            inserted = len(new_ids)
            skipped = len(parsed_hands) - inserted
            if own_transaction:
                db.execute("COMMIT")
                own_transaction = False
            return inserted, skipped
        except Exception:
            if own_transaction:
                try:
                    db.execute("ROLLBACK")
                except Exception:
                    pass
            raise
        finally:
            for table_name in reversed(registered_tables):
                try:
                    db.unregister(table_name)
                except Exception:
                    pass
            if own_connection:
                db.close()

    def hand_count(self) -> int:
        with self.connect() as con:
            return int(
                con.execute(
                    "SELECT COUNT(*) FROM hands"
                ).fetchone()[0]
            )

    def player_count(self) -> int:
        with self.connect() as con:
            return int(
                con.execute(
                    """
                    SELECT COUNT(DISTINCT player_name)
                    FROM hand_players
                    """
                ).fetchone()[0]
            )

    def action_count(self) -> int:
        with self.connect() as con:
            return int(
                con.execute(
                    "SELECT COUNT(*) FROM actions"
                ).fetchone()[0]
            )

    def export_parquet(
        self,
        output_folder: str = "exports",
    ) -> str:
        output = Path(output_folder)
        output.mkdir(parents=True, exist_ok=True)

        hands_path = output / "hands.parquet"
        players_path = output / "hand_players.parquet"
        actions_path = output / "actions.parquet"

        with self.connect() as con:
            con.execute(
                f"""
                COPY hands TO '{hands_path.as_posix()}'
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            con.execute(
                f"""
                COPY hand_players TO '{players_path.as_posix()}'
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            con.execute(
                f"""
                COPY actions TO '{actions_path.as_posix()}'
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

        return str(output.resolve())
