from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class ParserDebuggerService:
    WIN_ACTIONS = {
        "COLLECT",
        "COLLECTED",
        "WIN",
        "WINS",
        "WON",
        "AWARD",
        "AWARDED",
    }

    SHOW_ACTIONS = {
        "SHOW",
        "SHOWS",
        "REVEAL",
        "REVEALS",
    }

    PREFLOP_CONTINUE_ACTIONS = {
        "CALL",
        "RAISE",
        "CHECK",
    }

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

    def find_suspicious_hands(
        self,
        mode: str,
        entity_name: str,
        site: str = "",
        stakes: str = "",
        category: str = "FLOP_REACHED_NOT_SEEN",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        rows = self._load_player_hands(
            mode=mode,
            entity_name=entity_name,
            site=site,
            stakes=stakes,
        )

        filtered = [
            row
            for row in rows
            if self._matches_category(row, category)
        ]

        filtered.sort(
            key=lambda row: (
                str(row.get("played_at") or ""),
                row["hand_id"],
            ),
            reverse=True,
        )

        return filtered[: max(1, int(limit))]

    def inspect_hand(
        self,
        hand_id: str,
        player_name: str,
    ) -> dict[str, Any]:
        with self.connect() as con:
            hand = con.execute(
                """
                SELECT
                    hand_id,
                    site,
                    table_name,
                    stakes,
                    played_at,
                    flop,
                    turn,
                    river,
                    pot,
                    rake,
                    source_file
                FROM hands
                WHERE hand_id = ?
                """,
                [hand_id],
            ).fetchone()

            if hand is None:
                raise ValueError("Hand bulunamadı.")

            player = con.execute(
                """
                SELECT
                    seat_no,
                    player_name,
                    starting_stack,
                    position
                FROM hand_players
                WHERE hand_id = ?
                  AND player_name = ?
                """,
                [hand_id, player_name],
            ).fetchone()

            actions = con.execute(
                """
                SELECT
                    sequence_no,
                    street,
                    player_name,
                    action,
                    amount,
                    to_amount
                FROM actions
                WHERE hand_id = ?
                ORDER BY sequence_no
                """,
                [hand_id],
            ).fetchall()

        player_actions = [
            {
                "sequence_no": int(row[0] or 0),
                "street": str(row[1] or ""),
                "player_name": str(row[2] or ""),
                "action": str(row[3] or ""),
                "amount": row[4],
                "to_amount": row[5],
            }
            for row in actions
            if str(row[2] or "") == player_name
        ]

        all_actions = [
            {
                "sequence_no": int(row[0] or 0),
                "street": str(row[1] or ""),
                "player_name": str(row[2] or ""),
                "action": str(row[3] or ""),
                "amount": row[4],
                "to_amount": row[5],
            }
            for row in actions
        ]

        flags = self._calculate_flags(
            flop=hand[5],
            player_actions=player_actions,
        )

        return {
            "hand": {
                "hand_id": str(hand[0]),
                "site": hand[1],
                "table_name": hand[2],
                "stakes": hand[3],
                "played_at": hand[4],
                "flop": hand[5],
                "turn": hand[6],
                "river": hand[7],
                "pot": hand[8],
                "rake": hand[9],
                "source_file": hand[10],
            },
            "player": {
                "seat_no": player[0] if player else None,
                "player_name": player_name,
                "starting_stack": player[2] if player else None,
                "position": player[3] if player else None,
            },
            "flags": flags,
            "player_actions": player_actions,
            "all_actions": all_actions,
            "explanation": self._explain(flags),
        }

    def _load_player_hands(
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

        if mode == "PLAYER":
            clauses.append("hp.player_name = ?")
            params.append(entity_name)

        elif mode == "ALIAS":
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM player_aliases pa
                    WHERE pa.player_name = hp.player_name
                      AND pa.alias_name = ?
                )
                """
            )
            params.append(entity_name)

        else:
            raise ValueError("Mode PLAYER veya ALIAS olmalı.")

        where_sql = "WHERE " + " AND ".join(clauses)

        query = f"""
            SELECT DISTINCT
                hp.hand_id,
                hp.player_name,
                COALESCE(NULLIF(hp.position, ''), 'OTHER') AS position,
                h.site,
                h.stakes,
                h.played_at,
                h.flop,
                h.turn,
                h.river,
                h.source_file
            FROM hand_players hp
            JOIN hands h
              ON h.hand_id = hp.hand_id
            {where_sql}
        """

        with self.connect() as con:
            base_rows = con.execute(
                query,
                params,
            ).fetchall()

            result: list[dict[str, Any]] = []

            for row in base_rows:
                action_rows = con.execute(
                    """
                    SELECT
                        sequence_no,
                        street,
                        action
                    FROM actions
                    WHERE hand_id = ?
                      AND player_name = ?
                    ORDER BY sequence_no
                    """,
                    [str(row[0]), str(row[1])],
                ).fetchall()

                player_actions = [
                    {
                        "sequence_no": int(action[0] or 0),
                        "street": str(action[1] or ""),
                        "action": str(action[2] or ""),
                    }
                    for action in action_rows
                ]

                flags = self._calculate_flags(
                    flop=row[6],
                    player_actions=player_actions,
                )

                result.append(
                    {
                        "hand_id": str(row[0]),
                        "player_name": str(row[1]),
                        "position": str(row[2] or "OTHER"),
                        "site": row[3],
                        "stakes": row[4],
                        "played_at": row[5],
                        "flop": row[6],
                        "turn": row[7],
                        "river": row[8],
                        "source_file": row[9],
                        **flags,
                        "reason": self._short_reason(flags),
                    }
                )

        return result

    def _calculate_flags(
        self,
        flop: Any,
        player_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = [
            {
                "street": str(row.get("street") or "").strip().upper(),
                "action": str(row.get("action") or "").strip().upper(),
            }
            for row in player_actions
        ]

        hand_reached_flop = (
            flop is not None
            and str(flop).strip() != ""
        )

        folded_preflop = any(
            row["street"] == "PREFLOP"
            and row["action"] == "FOLD"
            for row in normalized
        )

        preflop_continue = any(
            row["street"] == "PREFLOP"
            and row["action"] in self.PREFLOP_CONTINUE_ACTIONS
            for row in normalized
        )

        has_flop_action = any(
            row["street"] == "FLOP"
            for row in normalized
        )

        has_turn_action = any(
            row["street"] == "TURN"
            for row in normalized
        )

        has_river_action = any(
            row["street"] == "RIVER"
            for row in normalized
        )

        showed_cards = any(
            row["action"] in self.SHOW_ACTIONS
            for row in normalized
        )

        won_pot = any(
            row["action"] in self.WIN_ACTIONS
            for row in normalized
        )

        saw_flop = (
            hand_reached_flop
            and not folded_preflop
            and (
                preflop_continue
                or has_flop_action
                or has_turn_action
                or has_river_action
                or showed_cards
                or won_pot
            )
        )

        wwsf_eligible = saw_flop
        wwsf_won = saw_flop and won_pot
        wtsd_eligible = saw_flop
        wtsd_reached = saw_flop and showed_cards
        wsd_eligible = showed_cards
        wsd_won = showed_cards and won_pot

        return {
            "hand_reached_flop": hand_reached_flop,
            "folded_preflop": folded_preflop,
            "preflop_continue": preflop_continue,
            "has_flop_action": has_flop_action,
            "has_turn_action": has_turn_action,
            "has_river_action": has_river_action,
            "showed_cards": showed_cards,
            "won_pot": won_pot,
            "saw_flop": saw_flop,
            "wwsf_eligible": wwsf_eligible,
            "wwsf_won": wwsf_won,
            "wtsd_eligible": wtsd_eligible,
            "wtsd_reached": wtsd_reached,
            "wsd_eligible": wsd_eligible,
            "wsd_won": wsd_won,
        }

    def _matches_category(
        self,
        row: dict[str, Any],
        category: str,
    ) -> bool:
        category = category.upper()

        if category == "FLOP_REACHED_NOT_SEEN":
            return (
                row["hand_reached_flop"]
                and not row["folded_preflop"]
                and not row["saw_flop"]
            )

        if category == "SAW_FLOP_NO_ACTION":
            return (
                row["saw_flop"]
                and not row["has_flop_action"]
            )

        if category == "WON_NOT_WWSF":
            return (
                row["won_pot"]
                and not row["wwsf_won"]
            )

        if category == "SHOW_NO_WIN":
            return (
                row["showed_cards"]
                and not row["won_pot"]
            )

        if category == "NO_PLAYER_ACTION":
            return not any(
                [
                    row["folded_preflop"],
                    row["preflop_continue"],
                    row["has_flop_action"],
                    row["has_turn_action"],
                    row["has_river_action"],
                    row["showed_cards"],
                    row["won_pot"],
                ]
            )

        return True

    def _short_reason(
        self,
        flags: dict[str, Any],
    ) -> str:
        if (
            flags["hand_reached_flop"]
            and flags["folded_preflop"]
        ):
            return "Board açıldı fakat oyuncu preflop fold etti."

        if (
            flags["hand_reached_flop"]
            and not flags["saw_flop"]
        ):
            return "Board açıldı ancak oyuncunun devam ettiğine dair aksiyon yok."

        if (
            flags["saw_flop"]
            and not flags["has_flop_action"]
        ):
            return "Saw Flop kabul edildi fakat FLOP street aksiyonu yok."

        if (
            flags["won_pot"]
            and not flags["wwsf_won"]
        ):
            return "Pot kazandı fakat WWSF sampleına girmedi."

        return "Sayaçlara normal biçimde dahil."

    def _explain(
        self,
        flags: dict[str, Any],
    ) -> list[str]:
        lines = [
            f"Hand flopa ulaştı: {self._yes_no(flags['hand_reached_flop'])}",
            f"Preflop fold: {self._yes_no(flags['folded_preflop'])}",
            f"Preflop devam aksiyonu: {self._yes_no(flags['preflop_continue'])}",
            f"Flop aksiyonu: {self._yes_no(flags['has_flop_action'])}",
            f"Turn aksiyonu: {self._yes_no(flags['has_turn_action'])}",
            f"River aksiyonu: {self._yes_no(flags['has_river_action'])}",
            f"Show: {self._yes_no(flags['showed_cards'])}",
            f"Pot kazandı: {self._yes_no(flags['won_pot'])}",
            f"Saw Flop: {self._yes_no(flags['saw_flop'])}",
            f"WWSF sample: {self._yes_no(flags['wwsf_eligible'])}",
            f"WWSF win: {self._yes_no(flags['wwsf_won'])}",
            f"WTSD sample: {self._yes_no(flags['wtsd_eligible'])}",
            f"WTSD reached: {self._yes_no(flags['wtsd_reached'])}",
            f"W$SD sample: {self._yes_no(flags['wsd_eligible'])}",
            f"W$SD win: {self._yes_no(flags['wsd_won'])}",
        ]

        lines.append("")
        lines.append("Sonuç: " + self._short_reason(flags))

        return lines

    def _yes_no(
        self,
        value: bool,
    ) -> str:
        return "EVET" if value else "HAYIR"
