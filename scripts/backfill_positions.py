from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.position_service import calculate_positions, validate_position_input


def distribution(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return dict(con.execute(
        "SELECT COALESCE(position, '<NULL>'), COUNT(*) FROM hand_players GROUP BY 1 ORDER BY 1"
    ).fetchall())


def create_backup(database: Path) -> Path:
    backup_dir = database.parent / "position_repair_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{database.stem}_before_position_repair_{stamp}{database.suffix}"
    print(f"Database backup: {backup}")
    shutil.copy2(database, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair PokerLab hand positions safely.")
    parser.add_argument("--database", default="database/pokerlab.duckdb")
    parser.add_argument("--batch-hands", type=int, default=25000)
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    database = Path(args.database).resolve()
    if not database.exists():
        raise FileNotFoundError(database)
    if args.batch_hands < 100:
        raise ValueError("--batch-hands must be at least 100")

    print("Close PokerLab AI before continuing.")
    if not args.dry_run and not args.skip_backup:
        create_backup(database)

    con = duckdb.connect(str(database))
    before = distribution(con)
    total_hands = con.execute("SELECT COUNT(*) FROM hands").fetchone()[0]
    print(f"Hands: {total_hands:,}")
    print(f"Before: {before}")

    invalid = Counter()
    generated = Counter()
    processed = 0
    last_hand_id: str | None = None

    if not args.dry_run:
        con.execute("BEGIN TRANSACTION")
        con.execute("CREATE TEMP TABLE position_updates(hand_id VARCHAR, seat_no INTEGER, position VARCHAR)")

    try:
        while True:
            params: list[object] = []
            boundary = ""
            if last_hand_id is not None:
                boundary = "WHERE h.hand_id > ?"
                params.append(last_hand_id)
            params.append(args.batch_hands)

            hand_rows = con.execute(f"""
                SELECT h.hand_id, h.button_seat, h.max_players,
                       LIST(hp.seat_no ORDER BY hp.seat_no) AS seats
                FROM hands h
                JOIN hand_players hp ON hp.hand_id = h.hand_id
                {boundary}
                GROUP BY h.hand_id, h.button_seat, h.max_players
                ORDER BY h.hand_id
                LIMIT ?
            """, params).fetchall()

            if not hand_rows:
                break

            updates: list[tuple[str, int, str]] = []
            for hand_id, button_seat, max_players, seats in hand_rows:
                validation = validate_position_input(seats, button_seat, max_players)
                if not validation.is_valid:
                    invalid[validation.message] += 1
                    continue
                positions = calculate_positions(seats, button_seat, max_players)
                if len(positions) != len(seats):
                    invalid["Position count mismatch"] += 1
                    continue
                for seat_no, position in positions.items():
                    updates.append((hand_id, seat_no, position))
                    generated[position] += 1

            if not args.dry_run and updates:
                con.executemany("INSERT INTO position_updates VALUES (?, ?, ?)", updates)
                con.execute("""
                    UPDATE hand_players AS hp
                    SET position = u.position
                    FROM position_updates AS u
                    WHERE hp.hand_id = u.hand_id AND hp.seat_no = u.seat_no
                """)
                con.execute("DELETE FROM position_updates")

            processed += len(hand_rows)
            last_hand_id = str(hand_rows[-1][0])
            print(f"Processed {processed:,}/{total_hands:,} hands", end="\r", flush=True)

        print()
        if invalid:
            raise RuntimeError(f"Invalid hands detected; rollback required: {dict(invalid)}")

        if not args.dry_run:
            # Hard invariants before commit.
            btn_count = con.execute("SELECT COUNT(*) FROM hand_players WHERE position='BTN'").fetchone()[0]
            duplicate_position_hands = con.execute("""
                SELECT COUNT(*) FROM (
                    SELECT hand_id, position, COUNT(*) AS n
                    FROM hand_players
                    GROUP BY hand_id, position
                    HAVING COUNT(*) > 1
                )
            """).fetchone()[0]
            blank_count = con.execute("SELECT COUNT(*) FROM hand_players WHERE position IS NULL OR position='' ").fetchone()[0]
            if btn_count != total_hands:
                raise RuntimeError(f"BTN invariant failed: {btn_count:,} != {total_hands:,}")
            if duplicate_position_hands:
                raise RuntimeError(f"Duplicate positions detected: {duplicate_position_hands:,}")
            if blank_count:
                raise RuntimeError(f"Blank positions detected: {blank_count:,}")
            con.execute("COMMIT")

        after = distribution(con) if not args.dry_run else dict(generated)
        print(f"After:  {after}")
        print("Dry run completed; database was not changed." if args.dry_run else "Position repair completed successfully.")
        return 0
    except Exception:
        if not args.dry_run:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
