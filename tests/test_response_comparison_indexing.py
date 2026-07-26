from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import duckdb

from services.response_comparison_service import ResponseComparisonService
from services.analytical_store import AnalyticalStore


class ResponseComparisonIndexingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = str(
            Path(self.temp_dir.name) / "response-index.duckdb"
        )
        con = duckdb.connect(self.database_path)
        try:
            con.execute(
                """
                CREATE TABLE hands (
                    hand_id VARCHAR PRIMARY KEY,
                    site VARCHAR,
                    stakes VARCHAR,
                    flop VARCHAR,
                    turn VARCHAR,
                    river VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE hand_players (
                    hand_id VARCHAR,
                    player_name VARCHAR,
                    position VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE actions (
                    hand_id VARCHAR,
                    sequence_no INTEGER,
                    street VARCHAR,
                    player_name VARCHAR,
                    action VARCHAR,
                    amount DOUBLE,
                    to_amount DOUBLE
                )
                """
            )
            for number in range(1, 6):
                hand_id = f"h{number}"
                con.execute(
                    "INSERT INTO hands VALUES (?, 'site', '1/2', 'Ah7d2c', NULL, NULL)",
                    [hand_id],
                )
                con.execute(
                    """
                    INSERT INTO hand_players VALUES
                        (?, 'Aggressor', 'BTN'),
                        (?, 'Responder', 'BB')
                    """,
                    [hand_id, hand_id],
                )
                con.execute(
                    """
                    INSERT INTO actions VALUES
                        (?, 1, 'FLOP', 'Aggressor', 'BET', 5, 5),
                        (?, 2, 'FLOP', 'Responder', 'FOLD', 0, 0)
                    """,
                    [hand_id, hand_id],
                )
        finally:
            con.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cancel_commits_completed_batch_and_resume_is_idempotent(self) -> None:
        service = ResponseComparisonService(self.database_path)
        service.batch_size = 2
        cancel = False
        updates: list[dict] = []

        def progress(update: dict) -> None:
            nonlocal cancel
            updates.append(update)
            if int(update.get("completed", 0)) >= 2:
                cancel = True

        first = service.ensure_index(progress, lambda: cancel)
        self.assertTrue(first["cancelled"])
        self.assertEqual(first["added_hands"], 2)
        self.assertEqual(first["indexed"], 2)

        second = service.ensure_index()
        self.assertFalse(second["cancelled"])
        self.assertEqual(second["added_hands"], 3)
        self.assertEqual(second["indexed"], 5)

        third = service.ensure_index()
        self.assertEqual(third["added_hands"], 0)
        self.assertEqual(third["indexed"], 5)

        con = duckdb.connect(self.database_path, read_only=True)
        try:
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM response_node_v4_indexed_hands"
                ).fetchone()[0],
                5,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM response_nodes"
                ).fetchone()[0],
                5,
            )
        finally:
            con.close()

    def test_import_creates_canonical_v4_rows_and_checkpoint(self) -> None:
        import_path = str(Path(self.temp_dir.name) / "import.duckdb")
        store = AnalyticalStore(import_path)
        inserted, skipped = store.insert_parsed_batch([
            {
                "hand": {
                    "hand_id": "import-1",
                    "site": "site",
                    "stakes": "1/2",
                    "flop": "Ah7d2c",
                },
                "players": [
                    {"player_name": "Aggressor", "position": "BTN"},
                    {"player_name": "Responder", "position": "BB"},
                ],
                "actions": [
                    {
                        "sequence_no": 1,
                        "street": "FLOP",
                        "player_name": "Aggressor",
                        "action": "BET",
                        "amount": 5,
                        "to_amount": 5,
                    },
                    {
                        "sequence_no": 2,
                        "street": "FLOP",
                        "player_name": "Responder",
                        "action": "CALL",
                        "amount": 5,
                        "to_amount": 5,
                    },
                ],
            }
        ])
        self.assertEqual((inserted, skipped), (1, 0))

        con = duckdb.connect(import_path, read_only=True)
        try:
            self.assertEqual(
                con.execute(
                    """
                    SELECT aggressor, responder, node, response
                    FROM response_nodes
                    """
                ).fetchone(),
                ("Aggressor", "Responder", "ALL_RESPONSES", "CALL"),
            )
            self.assertEqual(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM response_node_v4_indexed_hands
                    WHERE hand_id = 'import-1'
                    """
                ).fetchone()[0],
                1,
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
