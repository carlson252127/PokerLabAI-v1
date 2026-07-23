from __future__ import annotations

import duckdb


RESPONSE_NODE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("hand_id", "VARCHAR"),
    # Legacy import-time fields. Keep them for old databases and writers.
    ("player_name", "VARCHAR"),
    ("position", "VARCHAR"),
    # Response Comparison V4 fields.
    ("aggressor", "VARCHAR"),
    ("responder", "VARCHAR"),
    ("aggressor_position", "VARCHAR"),
    ("responder_position", "VARCHAR"),
    ("site", "VARCHAR"),
    ("stakes", "VARCHAR"),
    ("node", "VARCHAR"),
    ("street", "VARCHAR"),
    ("response", "VARCHAR"),
    ("board_family", "VARCHAR"),
    ("open_bucket", "VARCHAR"),
    ("bet_bucket", "VARCHAR"),
)


def ensure_response_node_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create or additively migrate the shared response-node schema.

    Legacy ``player_name`` represents the responder, not the aggressor. Only
    responder fields are therefore safe to backfill. V4 reconstructs missing
    aggressor-aware rows from the immutable hand/action source tables.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS response_nodes (
            hand_id VARCHAR,
            player_name VARCHAR,
            position VARCHAR,
            aggressor VARCHAR,
            responder VARCHAR,
            aggressor_position VARCHAR,
            responder_position VARCHAR,
            site VARCHAR,
            stakes VARCHAR,
            node VARCHAR,
            street VARCHAR,
            response VARCHAR,
            board_family VARCHAR,
            open_bucket VARCHAR,
            bet_bucket VARCHAR
        )
        """
    )

    existing = {
        str(row[1]).lower()
        for row in con.execute("PRAGMA table_info('response_nodes')").fetchall()
    }
    for name, column_type in RESPONSE_NODE_COLUMNS:
        if name.lower() not in existing:
            con.execute(
                f'ALTER TABLE response_nodes ADD COLUMN "{name}" {column_type}'
            )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS response_node_schema_migrations (
            migration_key VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    migration_key = "v4_responder_backfill"
    applied = con.execute(
        """
        SELECT COUNT(*)
        FROM response_node_schema_migrations
        WHERE migration_key = ?
        """,
        [migration_key],
    ).fetchone()[0]
    if not applied:
        # These are the only lossless mappings from the legacy schema.
        con.execute(
            """
            UPDATE response_nodes
            SET responder = player_name
            WHERE responder IS NULL
              AND player_name IS NOT NULL
            """
        )
        con.execute(
            """
            UPDATE response_nodes
            SET responder_position = position
            WHERE responder_position IS NULL
              AND position IS NOT NULL
            """
        )
        con.execute(
            """
            INSERT INTO response_node_schema_migrations (migration_key)
            VALUES (?)
            ON CONFLICT (migration_key) DO NOTHING
            """,
            [migration_key],
        )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS response_node_v4_indexed_hands (
            hand_id VARCHAR PRIMARY KEY
        )
        """
    )
