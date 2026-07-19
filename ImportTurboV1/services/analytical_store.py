from __future__ import annotations

from pathlib import Path
import os
from typing import Iterable

import duckdb
import pyarrow as pa


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

            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hands_hand_id
                ON hands(hand_id)
                """
            )
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
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_players_position
                ON hand_players(position)
                """
            )
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
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_actions_street
                ON actions(street)
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

        table = pa.Table.from_pylist(rows)
        con.register("incoming_file_registry", table)
        con.execute(
            """
            INSERT INTO imported_files AS dst
            SELECT
                file_path,
                file_size,
                modified_ns,
                parsed_hands,
                CURRENT_TIMESTAMP
            FROM incoming_file_registry
            ON CONFLICT (file_path) DO UPDATE SET
                file_size = EXCLUDED.file_size,
                modified_ns = EXCLUDED.modified_ns,
                parsed_hands = EXCLUDED.parsed_hands,
                imported_at = CURRENT_TIMESTAMP
            """
        )
        con.unregister("incoming_file_registry")

    def insert_parsed_batch(
        self,
        parsed_hands: list[dict],
        con: duckdb.DuckDBPyConnection | None = None,
    ) -> tuple[int, int]:
        """Insert only genuinely new hands using Arrow and one DuckDB transaction.

        Re-imported hand IDs are skipped instead of deleting and rebuilding all
        child rows. This is the main speed-up for large databases.
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
        try:
            db.register("incoming_all_hands", pa.Table.from_pylist(hands_rows))
            new_ids = {
                str(row[0])
                for row in db.execute(
                    """
                    SELECT src.hand_id
                    FROM incoming_all_hands AS src
                    ANTI JOIN hands AS existing USING (hand_id)
                    """
                ).fetchall()
            }

            if not new_ids:
                db.unregister("incoming_all_hands")
                return 0, len(parsed_hands)

            new_hand_rows = [
                row for row in hands_rows if row["hand_id"] in new_ids
            ]
            db.register(
                "incoming_new_hands",
                pa.Table.from_pylist(new_hand_rows),
            )
            db.execute(
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
                FROM incoming_new_hands
                """
            )
            db.unregister("incoming_new_hands")
            db.unregister("incoming_all_hands")

            players_rows: list[dict] = []
            actions_rows: list[dict] = []
            for hand_id in new_ids:
                item = unique_items[hand_id]
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
                db.execute(
                    """
                    INSERT INTO hand_players
                    SELECT hand_id, seat_no, player_name, starting_stack, position
                    FROM incoming_players
                    """
                )
                db.unregister("incoming_players")

            if actions_rows:
                db.register("incoming_actions", pa.Table.from_pylist(actions_rows))
                db.execute(
                    """
                    INSERT INTO actions
                    SELECT hand_id, sequence_no, street, player_name,
                           action, amount, to_amount, all_in, cards
                    FROM incoming_actions
                    """
                )
                db.unregister("incoming_actions")

            inserted = len(new_ids)
            skipped = len(parsed_hands) - inserted
            return inserted, skipped
        finally:
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
