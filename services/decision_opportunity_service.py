from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from models.comparison_results import ActionFrequency
from models.decision_opportunity import DecisionOpportunity, DecisionType
from services.poker_statistics import (
    CHECK_OR_BET_ACTIONS,
    DECISION_ACTIONS,
    FACING_ACTIONS,
    NON_DECISION_ACTIONS,
)


@dataclass(frozen=True, slots=True)
class OpportunityBuildResult:
    opportunities: tuple[DecisionOpportunity, ...]
    warnings: tuple[str, ...] = ()


class DecisionOpportunityService:
    """Build decision denominators from normalized, ordered action rows.

    Version one deliberately excludes multiway hands by default. When
    ``include_multiway`` is enabled their observed decisions are returned as
    invalid inspection records and are therefore excluded from aggregates.
    """

    def build(
        self,
        actions: Sequence[Mapping[str, Any]],
        *,
        node_key: str = "",
        player_ids: Iterable[str] | None = None,
        include_multiway: bool = False,
    ) -> OpportunityBuildResult:
        normalized = [self._normalize(row, index) for index, row in enumerate(actions)]
        normalized.sort(
            key=lambda row: (
                row["hand_id"],
                row["sequence_no"],
                row["source_index"],
            )
        )

        explicit_players = {
            self._player_key(player)
            for player in (player_ids or ())
            if str(player or "").strip()
        }
        players_by_hand: dict[str, set[str]] = {}
        for row in normalized:
            players_by_hand.setdefault(row["hand_id"], set()).add(
                self._player_key(row["player_id"])
            )
        if explicit_players:
            for players in players_by_hand.values():
                players.update(explicit_players)

        opportunities: list[DecisionOpportunity] = []
        warnings: list[str] = []
        seen: set[tuple[str, str, str, int]] = set()
        folded: dict[str, set[str]] = {}
        all_in: dict[str, set[str]] = {}
        street_state: dict[tuple[str, str], dict[str, Any]] = {}

        for row in normalized:
            hand_id = row["hand_id"]
            player_key = self._player_key(row["player_id"])
            action = row["action"]
            street = row["street"]
            is_multiway = len(players_by_hand.get(hand_id, ())) > 2

            if is_multiway and not include_multiway:
                warning = f"{hand_id}: multiway hand excluded."
                if warning not in warnings:
                    warnings.append(warning)
                continue

            if action in NON_DECISION_ACTIONS:
                continue
            if action not in DECISION_ACTIONS:
                warnings.append(
                    f"{hand_id}/{row['sequence_no']}: unknown action "
                    f"{action!r} ignored."
                )
                continue

            raw_identity = (
                hand_id,
                player_key,
                street,
                row["decision_index"],
            )
            if raw_identity in seen:
                warnings.append(
                    f"{hand_id}/{row['decision_index']}: duplicate decision "
                    f"ignored for {row['player_id']}."
                )
                continue

            hand_folded = folded.setdefault(hand_id, set())
            hand_all_in = all_in.setdefault(hand_id, set())
            if player_key in hand_folded:
                warnings.append(
                    f"{hand_id}/{row['sequence_no']}: action after fold ignored "
                    f"for {row['player_id']}."
                )
                continue
            if player_key in hand_all_in:
                warnings.append(
                    f"{hand_id}/{row['sequence_no']}: action after all-in ignored "
                    f"for {row['player_id']}."
                )
                continue

            state = street_state.setdefault(
                (hand_id, street),
                {"facing": None, "aggressor": None, "checked": False},
            )
            facing = state["facing"]

            if facing is None and action in CHECK_OR_BET_ACTIONS:
                decision_type = DecisionType.CHECK_OR_BET
                available_actions = ("CHECK", "BET")
                facing_action = "CHECK" if state["checked"] else "NONE"
            elif facing in {"BET", "RAISE"} and action in FACING_ACTIONS:
                decision_type = DecisionType.FOLD_CALL_OR_RAISE
                available_actions = ("FOLD", "CALL", "RAISE")
                facing_action = str(facing)
            else:
                warnings.append(
                    f"{hand_id}/{row['sequence_no']}: {action} is not legal "
                    f"while facing {facing or 'no action'}; ignored."
                )
                continue

            opportunity = DecisionOpportunity(
                hand_id=hand_id,
                player_id=row["player_id"],
                street=street,
                decision_index=row["decision_index"],
                node_key=str(row.get("node_key") or node_key),
                decision_type=decision_type,
                facing_action=facing_action,
                available_actions=available_actions,
                chosen_action=action,
                amount=row["amount"],
                raise_to=row["raise_to"],
                pot_before_action=row["pot_before_action"],
                is_valid=not is_multiway,
                is_multiway=is_multiway,
                warning=(
                    "Multiway decision is inspection-only in version 1."
                    if is_multiway
                    else None
                ),
            )
            seen.add(opportunity.identity)
            opportunities.append(opportunity)

            if action == "BET":
                state["facing"] = "BET"
                state["aggressor"] = player_key
                state["checked"] = False
            elif action == "CHECK":
                state["checked"] = True
            elif action == "RAISE":
                state["facing"] = "RAISE"
                state["aggressor"] = player_key
                state["checked"] = False
            elif action in {"CALL", "FOLD"}:
                state["facing"] = None
                state["aggressor"] = None
                state["checked"] = False

            if action == "FOLD":
                hand_folded.add(player_key)
            if row["all_in"]:
                hand_all_in.add(player_key)

        return OpportunityBuildResult(
            opportunities=tuple(opportunities),
            warnings=tuple(warnings),
        )

    @staticmethod
    def aggregate_action(
        opportunities: Iterable[DecisionOpportunity],
        action: str,
    ) -> ActionFrequency:
        normalized_action = str(action or "").strip().upper()
        if normalized_action in CHECK_OR_BET_ACTIONS:
            decision_type = DecisionType.CHECK_OR_BET
        elif normalized_action in FACING_ACTIONS:
            decision_type = DecisionType.FOLD_CALL_OR_RAISE
        else:
            supported = ", ".join(sorted(DECISION_ACTIONS))
            raise ValueError(
                f"Unsupported aggregate action {action!r}. "
                f"Supported actions: {supported}."
            )

        unique: dict[
            tuple[str, str, str, int], DecisionOpportunity
        ] = {}
        for opportunity in opportunities:
            if opportunity.is_valid and opportunity.decision_type == decision_type:
                unique.setdefault(opportunity.identity, opportunity)

        eligible = tuple(unique.values())
        chosen = sum(
            opportunity.chosen_action == normalized_action
            for opportunity in eligible
        )
        return ActionFrequency(
            action=normalized_action,
            opportunities=len(eligible),
            action_count=chosen,
            sample_hands=len({item.hand_id for item in eligible}),
            sample_players=len(
                {item.player_id.casefold() for item in eligible}
            ),
        )

    @classmethod
    def aggregate_frequencies(
        cls,
        opportunities: Iterable[DecisionOpportunity],
    ) -> tuple[ActionFrequency, ...]:
        rows = tuple(opportunities)
        return tuple(
            cls.aggregate_action(rows, action)
            for action in ("BET", "CHECK", "FOLD", "CALL", "RAISE")
        )

    @staticmethod
    def _normalize(
        row: Mapping[str, Any],
        source_index: int,
    ) -> dict[str, Any]:
        hand_id = str(row.get("hand_id") or "").strip()
        player_id = str(
            row.get("player_id")
            or row.get("player_name")
            or row.get("player")
            or ""
        ).strip()
        street = str(row.get("street") or "").strip().upper()
        action = str(
            row.get("action") or row.get("action_type") or ""
        ).strip().upper()
        if not hand_id:
            raise ValueError(f"Action row {source_index} has no hand_id.")
        if not player_id:
            raise ValueError(f"Action row {source_index} has no player_id.")
        if not street:
            raise ValueError(f"Action row {source_index} has no street.")

        sequence = row.get("sequence_no")
        if sequence is None:
            sequence = row.get("action_order")
        sequence_no = int(sequence) if sequence is not None else source_index + 1

        decision = row.get("decision_index")
        decision_index = (
            int(decision) if decision is not None else sequence_no
        )

        amount = row.get("amount")
        raise_to = row.get("raise_to")
        if raise_to is None:
            raise_to = row.get("to_amount")

        return {
            "hand_id": hand_id,
            "player_id": player_id,
            "street": street,
            "action": action,
            "sequence_no": sequence_no,
            "decision_index": decision_index,
            "amount": amount,
            "raise_to": raise_to,
            "pot_before_action": row.get("pot_before_action"),
            "all_in": bool(row.get("all_in", False)),
            "node_key": row.get("node_key"),
            "source_index": source_index,
        }

    @staticmethod
    def _player_key(value: Any) -> str:
        return str(value or "").strip().casefold()
