from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable
import re

import duckdb


class TrackerHHExportService:
    """Exports selected original hand-history text blocks.

    The exporter preserves the original source syntax instead of rebuilding
    hands from database rows. This maximizes compatibility with poker trackers.
    """

    HAND_START_RE = re.compile(
        r"(?m)^(?:"
        r"CoinPoker Hand #(?P<coin>\d+)"
        r"|PokerStars(?: Zoom)? (?:Hand|Game) #(?P<stars>\d+)"
        r"|GGPoker Hand #(?P<gg>[\w-]+)"
        r"|GGNetwork Hand #(?P<ggn>[\w-]+)"
        r"|Poker Hand #(?P<poker>[\w-]+)"
        r"):"
    )

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(
            self.database_path,
            read_only=True,
        )

    def available_entities(
        self,
        mode: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 100,
        limit: int = 5000,
    ) -> list[tuple[str, int]]:
        mode = mode.upper()
        clauses: list[str] = []
        params: list[Any] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        with self.connect() as con:
            if mode == "PLAYER":
                rows = con.execute(
                    f"""
                    SELECT
                        hp.player_name,
                        COUNT(DISTINCT hp.hand_id) AS hands
                    FROM hand_players hp
                    JOIN hands h
                      ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY hp.player_name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
                    """,
                    params + [int(minimum_hands)],
                ).fetchall()

            elif mode == "ALIAS":
                rows = con.execute(
                    f"""
                    SELECT
                        pa.alias_name,
                        COUNT(DISTINCT hp.hand_id) AS hands
                    FROM player_aliases pa
                    JOIN hand_players hp
                      ON hp.player_name = pa.player_name
                    JOIN hands h
                      ON h.hand_id = hp.hand_id
                    {where_sql}
                    GROUP BY pa.alias_name
                    HAVING COUNT(DISTINCT hp.hand_id) >= ?
                    ORDER BY hands DESC
                    LIMIT {int(limit)}
                    """,
                    params + [int(minimum_hands)],
                ).fetchall()
            else:
                return []

        return [
            (str(name), int(hands or 0))
            for name, hands in rows
        ]

    def export(
        self,
        output_folder: str,
        mode: str = "ALL",
        entity_name: str = "",
        site: str = "",
        stakes: str = "",
        hands_per_file: int = 50000,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        selected = self._selected_hands(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )

        if not selected:
            raise ValueError(
                "Seçilen filtrelere uygun hand bulunamadı."
            )

        output = Path(output_folder).expanduser().resolve()
        output.mkdir(
            parents=True,
            exist_ok=True,
        )

        by_source: dict[str, set[str]] = defaultdict(set)

        for row in selected:
            source_file = str(row["source_file"] or "").strip()

            if source_file:
                by_source[source_file].add(
                    str(row["hand_id"])
                )

        if not by_source:
            raise ValueError(
                "Seçilen ellerin source_file bilgisi bulunamadı."
            )

        exported_blocks: list[str] = []
        found_ids: set[str] = set()
        missing_source_files: list[str] = []

        source_items = list(by_source.items())
        total_sources = len(source_items)

        for index, (source_file, wanted_ids) in enumerate(
            source_items,
            start=1,
        ):
            source_path = Path(source_file)

            if progress_callback:
                progress_callback(
                    index - 1,
                    total_sources,
                    source_path.name,
                )

            if not source_path.exists():
                missing_source_files.append(
                    str(source_path)
                )
                continue

            text = self._read_text(source_path)

            for hand_id, block in self._split_hands(text):
                if hand_id in wanted_ids:
                    exported_blocks.append(
                        block.rstrip() + "\n"
                    )
                    found_ids.add(hand_id)

            if progress_callback:
                progress_callback(
                    index,
                    total_sources,
                    source_path.name,
                )

        selected_ids = {
            str(row["hand_id"])
            for row in selected
        }
        missing_ids = sorted(
            selected_ids - found_ids
        )

        hands_per_file = max(
            1,
            int(hands_per_file),
        )

        exported_files: list[str] = []

        for file_index, start in enumerate(
            range(
                0,
                len(exported_blocks),
                hands_per_file,
            ),
            start=1,
        ):
            chunk = exported_blocks[
                start:start + hands_per_file
            ]

            output_file = output / (
                f"pokerlab_hh_export_{file_index:04d}.txt"
            )

            output_file.write_text(
                "\n".join(chunk).rstrip() + "\n",
                encoding="utf-8",
            )

            exported_files.append(
                str(output_file)
            )

        report_file = output / "pokerlab_hh_export_report.txt"
        report_lines = [
            "PokerLab HH Export Report",
            "=" * 60,
            f"Selected hands: {len(selected_ids)}",
            f"Exported hands: {len(found_ids)}",
            f"Missing hand IDs: {len(missing_ids)}",
            f"Missing source files: {len(missing_source_files)}",
            f"Output files: {len(exported_files)}",
            "",
            "Filters",
            "-" * 60,
            f"Mode: {mode}",
            f"Entity: {entity_name or 'ALL'}",
            f"Site: {site or 'ALL'}",
            f"Stakes: {stakes or 'ALL'}",
            "",
        ]

        if missing_source_files:
            report_lines.extend(
                [
                    "Missing source files",
                    "-" * 60,
                    *missing_source_files,
                    "",
                ]
            )

        if missing_ids:
            report_lines.extend(
                [
                    "Missing hand IDs",
                    "-" * 60,
                    *missing_ids,
                    "",
                ]
            )

        report_file.write_text(
            "\n".join(report_lines),
            encoding="utf-8",
        )

        return {
            "selected_hands": len(selected_ids),
            "exported_hands": len(found_ids),
            "missing_hand_ids": len(missing_ids),
            "missing_source_files": len(
                missing_source_files
            ),
            "exported_files": exported_files,
            "report_file": str(report_file),
            "output_folder": str(output),
        }

    def _selected_hands(
        self,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
    ) -> list[dict[str, Any]]:
        mode = mode.upper()
        clauses: list[str] = []
        params: list[Any] = []

        if site:
            clauses.append("h.site = ?")
            params.append(site)

        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)

        join_sql = ""

        if mode == "PLAYER":
            join_sql = """
                JOIN hand_players hp
                  ON hp.hand_id = h.hand_id
            """
            clauses.append("hp.player_name = ?")
            params.append(entity_name)

        elif mode == "ALIAS":
            join_sql = """
                JOIN hand_players hp
                  ON hp.hand_id = h.hand_id
                JOIN player_aliases pa
                  ON pa.player_name = hp.player_name
            """
            clauses.append("pa.alias_name = ?")
            params.append(entity_name)

        elif mode != "ALL":
            raise ValueError(
                "Mode ALL, PLAYER veya ALIAS olmalı."
            )

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        with self.connect() as con:
            rows = con.execute(
                f"""
                SELECT DISTINCT
                    h.hand_id,
                    h.source_file,
                    h.site,
                    h.stakes,
                    h.played_at
                FROM hands h
                {join_sql}
                {where_sql}
                ORDER BY
                    h.source_file,
                    h.played_at,
                    h.hand_id
                """,
                params,
            ).fetchall()

        return [
            {
                "hand_id": str(row[0]),
                "source_file": row[1],
                "site": row[2],
                "stakes": row[3],
                "played_at": row[4],
            }
            for row in rows
        ]

    def _split_hands(
        self,
        text: str,
    ) -> list[tuple[str, str]]:
        matches = list(
            self.HAND_START_RE.finditer(text)
        )
        hands: list[tuple[str, str]] = []

        for index, match in enumerate(matches):
            start = match.start()
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(text)
            )

            hand_id = next(
                value
                for value in match.groupdict().values()
                if value is not None
            )

            hands.append(
                (
                    str(hand_id),
                    text[start:end].strip(),
                )
            )

        return hands

    def _read_text(
        self,
        path: Path,
    ) -> str:
        encodings = (
            "utf-8-sig",
            "utf-8",
            "cp1252",
            "latin-1",
        )

        for encoding in encodings:
            try:
                return path.read_text(
                    encoding=encoding,
                )
            except UnicodeDecodeError:
                continue

        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
