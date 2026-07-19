from __future__ import annotations

from services.board_taxonomy import board_family, simple_family
from services.size_bucket_service import open_bucket, postflop_bucket

tests = [
    ("Ah Kd 7c", "High Rainbow Disconnected"),
    ("9h 8h 7c", "Medium Two-tone Connected"),
    ("6s 6d 2c", "Paired Rainbow Disconnected"),
]

for board, expected in tests:
    actual = board_family(board)
    print(f"{board:12} -> {actual}")
    assert actual == expected, (board, actual, expected)

print("Open buckets:", [open_bucket(v) for v in (2.0, 2.25, 2.5, 3.0, 3.5, 4.0, 4.5)])
print("Postflop:", [postflop_bucket(v) for v in (20, 30, 40, 50, 60, 75, 90, 110, 140, 175, 225, 250)])
print("Simple:", simple_family("Ah Kd 7c"))
print("OK: Board + Size + Visual pack aktif.")
