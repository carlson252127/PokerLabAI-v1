# Player-stat call graph

## Confirmed old-only components

```text
parse_user_stats(...)                    old only, 0xD1890
process_stats(...)                       old only, 0xD20A0
user_stats : std::map<int, Stats>        old only, section 3 +0xC88
update_stats(int, Stats&, int)           old only, 0xB1980
GameTable::update_stats(int, Stats&)     old only, 0x6DC30
```

## Confirmed retained components

```text
ThudForm::updateTags()
ThudForm::plSetTagValue(...)
getStColorForTag(UnicodeString,double)
ThudForm::render()
ThudForm::paint()
```

## Architecture-level data flow

```text
incoming player-stat text
        |
        v
parse_user_stats
        |
        v
process_stats
        |
        v
user_stats : map<int, Stats>
        |
        v
update_stats / GameTable::update_stats
        |
        v
ThudForm tag update layer
        |
        v
plSetTagValue
        |
        +---- numeric value ---> getStColorForTag ---> tagColorRange
        |
        +---- display string ------------------------> render / paint
```

## XREF status

The nodes and their old/new presence are confirmed by COFF symbols and
template instantiations. The arrows are the strongest architecture-level
interpretation, not verified CALL instructions.

Instruction-level direct/indirect-call classification requires the
original `.text` bytes, which remain UPX-compressed.
