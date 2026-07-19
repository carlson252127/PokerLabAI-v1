import sqlite3
from pathlib import Path
from typing import Iterable


class DatabaseService:
    def __init__(self, db_path: str = "database/pokerlab.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(
            self.db_path,
            timeout=60,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row

        self._configure_database()
        self.create_tables()

    def _configure_database(self) -> None:
        cursor = self.connection.cursor()

        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA temp_store=MEMORY;")
        cursor.execute("PRAGMA cache_size=-200000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=60000;")

        self.connection.commit()

    def create_tables(self) -> None:
        cursor = self.connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS hands (
                hand_id TEXT PRIMARY KEY,
                site TEXT,
                table_name TEXT,
                stakes TEXT,
                played_at TEXT,
                max_players INTEGER,
                button_seat INTEGER,
                flop TEXT,
                turn TEXT,
                river TEXT,
                pot REAL,
                rake REAL,
                source_file TEXT,
                raw_hand TEXT,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hand_id TEXT NOT NULL,
                player_name TEXT,
                seat INTEGER,
                position TEXT,
                stack REAL,
                hole_cards TEXT,
                won REAL,
                FOREIGN KEY (hand_id) REFERENCES hands(hand_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hand_id TEXT NOT NULL,
                street TEXT,
                action_order INTEGER,
                player_name TEXT,
                action_type TEXT,
                amount REAL,
                all_in INTEGER DEFAULT 0,
                FOREIGN KEY (hand_id) REFERENCES hands(hand_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hands_hand_id
            ON hands(hand_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hands_table_name
            ON hands(table_name)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hands_played_at
            ON hands(played_at)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_players_hand_id
            ON players(hand_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_actions_hand_id
            ON actions(hand_id)
            """
        )

        self.connection.commit()

    def insert_hand(self, hand: dict) -> bool:
        cursor = self.connection.cursor()
        before = self.connection.total_changes

        cursor.execute(
            """
            INSERT OR IGNORE INTO hands (
                hand_id,
                site,
                table_name,
                stakes,
                played_at,
                max_players,
                button_seat,
                flop,
                turn,
                river,
                pot,
                rake,
                source_file,
                raw_hand
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._hand_to_tuple(hand),
        )

        self.connection.commit()
        return self.connection.total_changes > before

    def insert_hands_batch(
        self,
        hands: Iterable[dict],
        batch_size: int = 5000,
    ) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        batch: list[tuple] = []

        for item in hands:
            hand = item.get("hand", item)

            if not hand.get("hand_id"):
                skipped += 1
                continue

            batch.append(self._hand_to_tuple(hand))

            if len(batch) >= batch_size:
                batch_inserted = self._execute_batch(batch)
                inserted += batch_inserted
                skipped += len(batch) - batch_inserted
                batch.clear()

        if batch:
            batch_inserted = self._execute_batch(batch)
            inserted += batch_inserted
            skipped += len(batch) - batch_inserted

        return inserted, skipped

    def insert_parsed_batch(
        self,
        parsed_hands: list[dict],
    ) -> tuple[int, int]:
        if not parsed_hands:
            return 0, 0

        inserted = 0
        skipped = 0
        cursor = self.connection.cursor()

        try:
            cursor.execute("BEGIN")

            for item in parsed_hands:
                hand = item.get("hand", item)
                hand_id = hand.get("hand_id")

                if not hand_id:
                    skipped += 1
                    continue

                before = self.connection.total_changes

                cursor.execute(
                    """
                    INSERT OR IGNORE INTO hands (
                        hand_id,
                        site,
                        table_name,
                        stakes,
                        played_at,
                        max_players,
                        button_seat,
                        flop,
                        turn,
                        river,
                        pot,
                        rake,
                        source_file,
                        raw_hand
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._hand_to_tuple(hand),
                )

                was_inserted = self.connection.total_changes > before

                if not was_inserted:
                    skipped += 1
                    continue

                inserted += 1

                players = item.get("players", [])
                actions = item.get("actions", [])

                if players:
                    player_rows = [
                        (
                            hand_id,
                            row.get("player_name") or row.get("name"),
                            row.get("seat"),
                            row.get("position"),
                            row.get("stack"),
                            row.get("hole_cards"),
                            row.get("won"),
                        )
                        for row in players
                    ]

                    cursor.executemany(
                        """
                        INSERT INTO players (
                            hand_id,
                            player_name,
                            seat,
                            position,
                            stack,
                            hole_cards,
                            won
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        player_rows,
                    )

                if actions:
                    action_rows = [
                        (
                            hand_id,
                            row.get("street"),
                            row.get("action_order") or row.get("order"),
                            row.get("player_name") or row.get("player"),
                            row.get("action_type") or row.get("action"),
                            row.get("amount"),
                            1 if row.get("all_in") else 0,
                        )
                        for row in actions
                    ]

                    cursor.executemany(
                        """
                        INSERT INTO actions (
                            hand_id,
                            street,
                            action_order,
                            player_name,
                            action_type,
                            amount,
                            all_in
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        action_rows,
                    )

            self.connection.commit()

        except Exception:
            self.connection.rollback()
            raise

        return inserted, skipped

    def _execute_batch(self, batch: list[tuple]) -> int:
        before_count = self.connection.total_changes

        self.connection.executemany(
            """
            INSERT OR IGNORE INTO hands (
                hand_id,
                site,
                table_name,
                stakes,
                played_at,
                max_players,
                button_seat,
                flop,
                turn,
                river,
                pot,
                rake,
                source_file,
                raw_hand
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )

        self.connection.commit()
        return self.connection.total_changes - before_count

    def _hand_to_tuple(self, hand: dict) -> tuple:
        return (
            hand.get("hand_id"),
            hand.get("site"),
            hand.get("table_name") or hand.get("table"),
            hand.get("stakes"),
            hand.get("played_at"),
            hand.get("max_players"),
            hand.get("button_seat"),
            hand.get("flop"),
            hand.get("turn"),
            hand.get("river"),
            hand.get("pot"),
            hand.get("rake"),
            hand.get("source_file"),
            hand.get("raw_hand"),
        )

    def hand_count(self) -> int:
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM hands")
        return int(cursor.fetchone()[0])

    def clear_hands(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM actions")
        cursor.execute("DELETE FROM players")
        cursor.execute("DELETE FROM hands")
        self.connection.commit()

    def optimize(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute("PRAGMA optimize;")
        self.connection.commit()

    def close(self) -> None:
        if self.connection:
            self.connection.commit()
            self.connection.close()