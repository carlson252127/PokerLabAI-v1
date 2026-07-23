from __future__ import annotations

import unittest

import duckdb

from services.response_node_schema import ensure_response_node_schema


class ResponseNodeSchemaMigrationTests(unittest.TestCase):
    def test_migrates_legacy_schema_without_inventing_aggressor(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(
                """
                CREATE TABLE response_nodes (
                    hand_id VARCHAR,
                    player_name VARCHAR,
                    position VARCHAR,
                    site VARCHAR,
                    stakes VARCHAR,
                    node VARCHAR,
                    response VARCHAR,
                    board_family VARCHAR
                )
                """
            )
            con.execute(
                """
                INSERT INTO response_nodes
                VALUES ('h1', 'Responder', 'BB', 'PokerStars', '1/2',
                        'ALL_RESPONSES', 'FOLD', 'A-high Dry')
                """
            )

            ensure_response_node_schema(con)
            ensure_response_node_schema(con)
            # This was the exact V4 startup statement that previously raised
            # BinderException against the legacy schema.
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rn_aggressor
                ON response_nodes(aggressor)
                """
            )

            columns = {
                str(row[1])
                for row in con.execute(
                    "PRAGMA table_info('response_nodes')"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "aggressor",
                    "responder",
                    "aggressor_position",
                    "responder_position",
                    "street",
                    "open_bucket",
                    "bet_bucket",
                }.issubset(columns)
            )

            row = con.execute(
                """
                SELECT player_name, position, aggressor, responder,
                       aggressor_position, responder_position
                FROM response_nodes
                WHERE hand_id = 'h1'
                """
            ).fetchone()
            self.assertEqual(row[0], "Responder")
            self.assertEqual(row[1], "BB")
            self.assertIsNone(row[2])
            self.assertEqual(row[3], "Responder")
            self.assertIsNone(row[4])
            self.assertEqual(row[5], "BB")
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM response_nodes").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM response_node_schema_migrations
                    WHERE migration_key = 'v4_responder_backfill'
                    """
                ).fetchone()[0],
                1,
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
