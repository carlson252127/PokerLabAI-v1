from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import duckdb


@dataclass
class ExperimentRecord:
    name: str
    database_path: str
    hero_name: str
    site: str
    stakes: str
    start_date: str
    block_size: int
    created_at: str


class ExperimentDatabaseService:
    def __init__(self, main_database_path: str = "database/pokerlab.duckdb") -> None:
        self.main_database_path = str(Path(main_database_path).resolve())
        self.project_root = Path(self.main_database_path).parent.parent
        self.database_dir = self.project_root / "database"
        self.experiments_dir = self.database_dir / "experiments"
        self.registry_path = self.database_dir / "experiments_registry.json"
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

    def list_experiments(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def get_experiment(self, name: str) -> dict[str, Any] | None:
        wanted = name.strip().lower()
        for row in self.list_experiments():
            if str(row.get("name", "")).strip().lower() == wanted:
                return row
        return None

    def create_experiment(
        self,
        name: str,
        hero_name: str,
        site: str = "",
        stakes: str = "",
        start_date: str = "",
        block_size: int = 5000,
    ) -> dict[str, Any]:
        clean = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")
        if not clean:
            raise ValueError("Geçerli bir deney adı gir.")
        if not hero_name.strip():
            raise ValueError("Hero nick boş bırakılamaz.")
        if self.get_experiment(name):
            raise ValueError("Bu isimde bir deney zaten var.")

        db_path = (self.experiments_dir / f"{clean}.duckdb").resolve()
        if db_path.exists():
            raise FileExistsError(f"Database zaten var: {db_path}")

        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")

        self._clone_schema(db_path)

        record = ExperimentRecord(
            name=name.strip(),
            database_path=str(db_path),
            hero_name=hero_name.strip(),
            site=site.strip(),
            stakes=stakes.strip(),
            start_date=start_date.strip(),
            block_size=max(500, int(block_size)),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

        rows = self.list_experiments()
        rows.append(asdict(record))
        self.registry_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with duckdb.connect(str(db_path)) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS experiment_metadata (
                    name VARCHAR, database_path VARCHAR, hero_name VARCHAR,
                    site VARCHAR, stakes VARCHAR, start_date VARCHAR,
                    block_size BIGINT, created_at VARCHAR
                )
            """)
            con.execute("DELETE FROM experiment_metadata")
            con.execute(
                "INSERT INTO experiment_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    record.name, record.database_path, record.hero_name,
                    record.site, record.stakes, record.start_date,
                    record.block_size, record.created_at,
                ],
            )

        return asdict(record)

    def sync_experiment(self, experiment_name: str) -> dict[str, Any]:
        record = self.get_experiment(experiment_name)
        if not record:
            raise ValueError("Deney bulunamadı.")

        target = Path(record["database_path"]).resolve()
        if not target.exists():
            self._clone_schema(target)

        with duckdb.connect(str(target)) as con:
            source = self.main_database_path.replace("'", "''")
            con.execute(f"ATTACH '{source}' AS source_db (READ_ONLY)")

            clauses = ["hp.player_name = ?"]
            params: list[Any] = [record["hero_name"]]

            if record.get("start_date"):
                clauses.append("""
                    TRY_CAST(REPLACE(SUBSTR(CAST(h.played_at AS VARCHAR),1,10),'/','-') AS DATE)
                    >= TRY_CAST(? AS DATE)
                """)
                params.append(record["start_date"])
            if record.get("site"):
                clauses.append("TRIM(h.site) = ?")
                params.append(record["site"])
            if record.get("stakes"):
                clauses.append("TRIM(h.stakes) = ?")
                params.append(record["stakes"])

            con.execute(
                f"""
                CREATE OR REPLACE TEMP TABLE selected_ids AS
                SELECT DISTINCT h.hand_id
                FROM source_db.hands h
                JOIN source_db.hand_players hp ON hp.hand_id = h.hand_id
                WHERE {' AND '.join(clauses)}
                """,
                params,
            )
            selected = int(con.execute("SELECT COUNT(*) FROM selected_ids").fetchone()[0])

            con.execute("""
                CREATE OR REPLACE TEMP TABLE new_ids AS
                SELECT s.hand_id
                FROM selected_ids s
                LEFT JOIN hands t ON t.hand_id = s.hand_id
                WHERE t.hand_id IS NULL
            """)
            new_count = int(con.execute("SELECT COUNT(*) FROM new_ids").fetchone()[0])

            if new_count:
                for table in ("hands", "hand_players", "actions"):
                    self._copy_new_rows(con, table)

            total = int(con.execute("SELECT COUNT(*) FROM hands").fetchone()[0])
            hero_hands = int(
                con.execute(
                    "SELECT COUNT(DISTINCT hand_id) FROM hand_players WHERE player_name = ?",
                    [record["hero_name"]],
                ).fetchone()[0]
            )

            con.execute("""
                CREATE TABLE IF NOT EXISTS experiment_sync_log (
                    synced_at VARCHAR, selected_hands BIGINT,
                    new_hands BIGINT, total_hands BIGINT
                )
            """)
            con.execute(
                "INSERT INTO experiment_sync_log VALUES (?, ?, ?, ?)",
                [datetime.now().isoformat(timespec="seconds"), selected, new_count, total],
            )
            con.execute("DETACH source_db")

        return {
            "experiment_name": experiment_name,
            "selected_hands": selected,
            "new_hands": new_count,
            "total_hands": total,
            "hero_hands": hero_hands,
            "database_path": str(target),
        }

    def experiment_stats(self, experiment_name: str) -> dict[str, Any]:
        record = self.get_experiment(experiment_name)
        if not record:
            raise ValueError("Deney bulunamadı.")
        path = Path(record["database_path"])
        if not path.exists():
            return {"hero_hands": 0, "completed_blocks": 0, "current_block_hands": 0, "block_size": int(record["block_size"])}

        with duckdb.connect(str(path), read_only=True) as con:
            hero_hands = int(
                con.execute(
                    "SELECT COUNT(DISTINCT hand_id) FROM hand_players WHERE player_name = ?",
                    [record["hero_name"]],
                ).fetchone()[0]
            )

        block = max(1, int(record.get("block_size") or 5000))
        return {
            "hero_hands": hero_hands,
            "completed_blocks": hero_hands // block,
            "current_block_hands": hero_hands % block,
            "block_size": block,
        }

    def _clone_schema(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(target)) as con:
            source = self.main_database_path.replace("'", "''")
            con.execute(f"ATTACH '{source}' AS source_db (READ_ONLY)")
            tables = {
                str(row[0])
                for row in con.execute("""
                    SELECT table_name
                    FROM source_db.information_schema.tables
                    WHERE table_schema = 'main'
                """).fetchall()
            }
            for table in ("hands", "hand_players", "actions", "player_aliases", "gto_baselines"):
                if table in tables:
                    con.execute(
                        f'CREATE TABLE IF NOT EXISTS "{table}" AS '
                        f'SELECT * FROM source_db."{table}" WHERE 1=0'
                    )
            con.execute("DETACH source_db")

    def _copy_new_rows(self, con: duckdb.DuckDBPyConnection, table: str) -> None:
        target_cols = [str(row[1]) for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()]
        source_cols = [
            str(row[0])
            for row in con.execute("""
                SELECT column_name
                FROM source_db.information_schema.columns
                WHERE table_schema='main' AND table_name=?
                ORDER BY ordinal_position
            """, [table]).fetchall()
        ]
        cols = [col for col in target_cols if col in source_cols]
        if not cols:
            raise RuntimeError(f"{table}: ortak kolon bulunamadı.")
        quoted = ", ".join('"' + col.replace('"', '""') + '"' for col in cols)
        con.execute(
            f'INSERT INTO "{table}" ({quoted}) '
            f'SELECT {quoted} FROM source_db."{table}" src '
            f'JOIN new_ids n ON n.hand_id = src.hand_id'
        )
