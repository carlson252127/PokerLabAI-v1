from __future__ import annotations

import argparse
from pathlib import Path
import duckdb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="database/pokerlab.duckdb")
    args = parser.parse_args()
    db = Path(args.database).resolve()
    con = duckdb.connect(str(db), read_only=True)
    try:
        total_hands = con.execute("SELECT COUNT(*) FROM hands").fetchone()[0]
        distribution = con.execute("SELECT position, COUNT(*) FROM hand_players GROUP BY 1 ORDER BY 2 DESC").fetchall()
        btn = con.execute("SELECT COUNT(*) FROM hand_players WHERE position='BTN'").fetchone()[0]
        blanks = con.execute("SELECT COUNT(*) FROM hand_players WHERE position IS NULL OR position='' ").fetchone()[0]
        duplicates = con.execute("""
            SELECT COUNT(*) FROM (
                SELECT hand_id, position, COUNT(*) n
                FROM hand_players GROUP BY 1,2 HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        missing_btn = con.execute("""
            SELECT COUNT(*) FROM hands h
            WHERE NOT EXISTS (
                SELECT 1 FROM hand_players hp
                WHERE hp.hand_id=h.hand_id AND hp.position='BTN'
            )
        """).fetchone()[0]
        print(f"Hands: {total_hands:,}")
        print(f"BTN rows: {btn:,}")
        print(f"Missing BTN hands: {missing_btn:,}")
        print(f"Blank positions: {blanks:,}")
        print(f"Duplicate hand/position pairs: {duplicates:,}")
        print("Distribution:")
        for position, count in distribution:
            print(f"  {position}: {count:,}")
        ok = btn == total_hands and missing_btn == 0 and blanks == 0 and duplicates == 0
        print("RESULT: PASS" if ok else "RESULT: FAIL")
        return 0 if ok else 1
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
