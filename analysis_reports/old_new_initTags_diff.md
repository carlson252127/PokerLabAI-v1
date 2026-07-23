# `ThudForm::initTags()` old/new comparison

## Confirmed symbol data

| Build | Section-relative address | Size |
|---|---:|---:|
| Old | `0xE1220` | `0x4FF0` |
| New | `0xD7530` | `0x4D70` |

The old function is exactly `0x280` (640) bytes larger.

The following related functions have identical symbol-derived sizes:

| Function | Old size | New size |
|---|---:|---:|
| `ThudForm::setTagValue` | `0x240` | `0x240` |
| `ThudForm::plSetTagValue` | `0x3F0` | `0x3F0` |
| `ThudForm::replaceTagsInFormula` | `0x290` | `0x290` |
| `ThudForm::processFormulas` | `0x560` | `0x560` |
| `ThudForm::updateTags` | `0x19B0` | `0x19B0` |
| `getStColorForTag` | `0x220` | `0x220` |

## Strong interpretation

The generic player-tag and color machinery was retained, while one or
more initialization blocks were deleted from `initTags()`. The removed
blocks are likely connected to the removed `Stats` ingestion pipeline,
but this cannot be proven at instruction level from the packed image.

## Why no basic-block diff is included

Both binaries use UPX:

```text
UPX0 RawSize = 0
UPX1 contains compressed code
```

UPX was not installed. Therefore no original function bytes exist in the
on-disk PE image at the COFF-reported function VAs.

Unavailable until static unpack:

- Exact old-only VA range inside `initTags`
- Basic blocks and branch edges
- UnicodeString construction calls
- Map insertion calls
- Default text/numeric values
- ColorRange and ColorPos initialization
