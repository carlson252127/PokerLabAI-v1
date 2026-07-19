from __future__ import annotations

from pathlib import Path

import duckdb


class DatabaseAdminService:
    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path)

    def get_counts(self) -> dict[str, int]:
        with self.connect() as con:
            return {
                "hands": self._safe_count(con, "hands"),
                "players": self._safe_count(con, "hand_players"),
                "actions": self._safe_count(con, "actions"),
                "gto_baselines": self._safe_count(
                    con,
                    "gto_baselines",
                ),
            }

    def clear_hand_data(self) -> dict[str, int]:
        before = self.get_counts()

        with self.connect() as con:
            con.execute("BEGIN TRANSACTION")

            try:
                if self._table_exists(con, "actions"):
                    con.execute("DELETE FROM actions")

                if self._table_exists(con, "hand_players"):
                    con.execute("DELETE FROM hand_players")

                if self._table_exists(con, "hands"):
                    con.execute("DELETE FROM hands")

                con.execute("COMMIT")

            except Exception:
                con.execute("ROLLBACK")
                raise

        after = self.get_counts()

        return {
            "deleted_hands": before["hands"] - after["hands"],
            "deleted_players": (
                before["players"] - after["players"]
            ),
            "deleted_actions": (
                before["actions"] - after["actions"]
            ),
            "preserved_gto": after["gto_baselines"],
        }

    def checkpoint(self) -> None:
        with self.connect() as con:
            con.execute("CHECKPOINT")

    def _safe_count(
        self,
        con: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> int:
        if not self._table_exists(con, table_name):
            return 0

        return int(
            con.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
        )

    def _table_exists(
        self,
        con: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> bool:
        return bool(
            con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'main'
                  AND table_name = ?
                """,
                [table_name],
            ).fetchone()[0]
        )
