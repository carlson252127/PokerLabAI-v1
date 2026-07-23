# Reconstructed `Stats` structure

## Confirmed

The old executable contains:

```cpp
std::map<int, Stats> user_stats;
```

Supporting old-only functions:

```text
GameTable::update_stats(int, Stats&)       0x6DC30
update_stats(int, Stats&, int)             0xB1980
parse_user_stats(..., int)                 0xD1890
process_stats(...)                         0xD20A0
```

The complete `std::map<int, Stats>` insert/erase implementation is absent
from the new executable.

## Packed string evidence

The old UPX1 stream contains one close cluster:

```text
0x357ADA vpip
0x357ADE pfr
0x357AE6 wtsd
0x357AFC foldTo
```

These are candidates for `Stats` field names or input keys. Their field
offsets cannot be recovered from packed bytes alone.

## Neutral layout

No field offset below is claimed:

```cpp
struct Stats {
    // Unknown packed layout.
    // Candidate semantic fields:
    //   vpip
    //   pfr
    //   wtsd
    //   one or more foldTo... statistics
};
```

| Candidate field | Offset | Type | Evidence | Confidence |
|---|---:|---|---|---|
| `vpip` | unknown | likely numeric | Old packed string cluster; old `hide_Vpip` UI key | Strong name, unknown layout |
| `pfr` | unknown | likely numeric | Old-only packed string cluster | Strong name, unknown layout |
| `wtsd` | unknown | likely numeric | Old-only packed string cluster | Strong name, unknown layout |
| `foldTo...` | unknown | likely numeric | Old-only `foldTo` prefix | Partial name only |

## Technical limitation

The original `.text` has `UPX0.RawSize == 0`. Without trusted static
unpacking, member accesses such as `[reg+0x20]` cannot be inspected.
Inventing offsets or data types would not be assembly-backed.
