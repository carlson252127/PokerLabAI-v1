from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(slots=True)
class _StreetState:
    current_bet_to: float = 0.0
    last_aggressor: str | None = None
    contributions: dict[str, float] = field(default_factory=dict)
    players_acted_since_last_aggression: set[str] = field(default_factory=set)
    street_action_index: int = 0
    betting_round_closed: bool = False
    last_action: str | None = None


@dataclass(slots=True)
class _HandState:
    active_players: set[str]
    player_names: dict[str, str]
    folded_players: set[str] = field(default_factory=set)
    all_in_players: set[str] = field(default_factory=set)
    positions: dict[str, str] = field(default_factory=dict)
    starting_stacks: dict[str, float] = field(default_factory=dict)
    total_invested: dict[str, float] = field(default_factory=dict)
    streets: dict[str, _StreetState] = field(default_factory=dict)
    pot: float | None = None


class DecisionOpportunityService:
    """Incrementally derive deterministic opportunities from normalized actions."""

    def extract_from_hand(
        self,
        hand: Mapping[str, Any],
        *,
        include_multiway: bool = True,
    ) -> list[DecisionOpportunity]:
        """Extract opportunities from one parser-style synthetic hand object."""
        hand_data = hand.get("hand", hand)
        hand_id = str(hand_data.get("hand_id") or "").strip()
        site = hand_data.get("site")
        timestamp = hand_data.get("played_at") or hand_data.get("timestamp")
        players = list(hand.get("players", ()))
        player_ids = [
            str(row.get("player_id") or row.get("player_name") or row.get("name") or "")
            for row in players
        ]
        metadata = {
            str(row.get("player_id") or row.get("player_name") or row.get("name") or "").casefold(): row
            for row in players
        }
        actions: list[dict[str, Any]] = []
        for raw in hand.get("actions", ()):
            row = dict(raw)
            row.setdefault("hand_id", hand_id)
            row.setdefault("site", site)
            row.setdefault("timestamp", timestamp)
            player = str(
                row.get("player_id") or row.get("player_name") or row.get("player") or ""
            ).casefold()
            player_meta = metadata.get(player, {})
            row.setdefault("position", player_meta.get("position"))
            row.setdefault(
                "starting_stack",
                player_meta.get("starting_stack", player_meta.get("stack")),
            )
            actions.append(row)
        initial_pot = hand_data.get("pot_before_actions")
        return list(
            self.build(
                actions,
                player_ids=player_ids,
                include_multiway=include_multiway,
                initial_pot=initial_pot,
            ).opportunities
        )

    def extract_from_actions(
        self,
        actions: Sequence[Mapping[str, Any]],
        *,
        node_key: str = "",
        player_ids: Iterable[str] | None = None,
        include_multiway: bool = True,
        initial_pot: float | None = None,
    ) -> list[DecisionOpportunity]:
        """Pure convenience API returning only the opportunity list."""
        return list(
            self.build(
                actions,
                node_key=node_key,
                player_ids=player_ids,
                include_multiway=include_multiway,
                initial_pot=initial_pot,
            ).opportunities
        )

    def build(
        self,
        actions: Sequence[Mapping[str, Any]],
        *,
        node_key: str = "",
        player_ids: Iterable[str] | None = None,
        include_multiway: bool = True,
        initial_pot: float | None = None,
    ) -> OpportunityBuildResult:
        """Build opportunities while preserving the existing result API."""
        normalized = [
            self._normalize(row, index) for index, row in enumerate(actions)
        ]
        normalized.sort(
            key=lambda row: (
                row["hand_id"], row["sequence_no"], row["source_index"]
            )
        )
        explicit_players = {
            self._player_key(player): str(player).strip()
            for player in (player_ids or ())
            if str(player or "").strip()
        }
        rows_by_hand: dict[str, list[dict[str, Any]]] = {}
        for row in normalized:
            rows_by_hand.setdefault(row["hand_id"], []).append(row)

        opportunities: list[DecisionOpportunity] = []
        warnings: list[str] = []
        for hand_id, hand_rows in rows_by_hand.items():
            player_names = dict(explicit_players)
            for row in hand_rows:
                player_names.setdefault(
                    self._player_key(row["player_id"]), row["player_id"]
                )
            positions = {
                self._player_key(row["player_id"]): str(row["position"]).upper()
                for row in hand_rows if row.get("position")
            }
            stacks = {
                self._player_key(row["player_id"]): float(row["starting_stack"])
                for row in hand_rows if row.get("starting_stack") is not None
            }
            state = _HandState(
                active_players=set(player_names),
                player_names=player_names,
                positions=positions,
                starting_stacks=stacks,
                total_invested={player: 0.0 for player in player_names},
                pot=float(initial_pot) if initial_pot is not None else None,
            )
            is_multiway = len(state.active_players) > 2
            if is_multiway and not include_multiway:
                warnings.append(f"{hand_id}: multiway hand excluded.")
                continue
            hand_opportunities, hand_warnings = self._process_hand(
                hand_rows, state, node_key, is_multiway
            )
            opportunities.extend(hand_opportunities)
            warnings.extend(hand_warnings)
        return OpportunityBuildResult(
            opportunities=tuple(opportunities),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _process_hand(
        self,
        rows: Sequence[dict[str, Any]],
        state: _HandState,
        node_key: str,
        is_multiway: bool,
    ) -> tuple[list[DecisionOpportunity], list[str]]:
        opportunities: list[DecisionOpportunity] = []
        warnings: list[str] = []
        seen: set[tuple[str, str, str, int]] = set()
        current_street_rank = -1
        street_ranks = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}
        for row in rows:
            player = self._player_key(row["player_id"])
            street = row["street"]
            if street not in street_ranks:
                raise ValueError(f"Unsupported decision street {street!r}.")
            street_rank = street_ranks[street]
            if street_rank < current_street_rank:
                raise ValueError(
                    f"Street order moved backwards to {street} in "
                    f"hand {row['hand_id']}."
                )
            current_street_rank = max(current_street_rank, street_rank)
            street_state = state.streets.setdefault(street, _StreetState())
            action = self._canonical_action(row, street_state, player)
            row["action"] = action
            identity = (
                row["hand_id"], player, street, row["decision_index"]
            )
            if identity in seen:
                warnings.append(
                    f"{row['hand_id']}/{row['decision_index']}: duplicate "
                    f"decision ignored for {row['player_id']}."
                )
                continue
            if action in NON_DECISION_ACTIONS:
                self._apply_action(state, street_state, row, player)
                continue
            if action not in DECISION_ACTIONS:
                warnings.append(
                    f"{row['hand_id']}/{row['sequence_no']}: unknown action "
                    f"{action!r} ignored."
                )
                continue
            if street_state.betting_round_closed:
                warnings.append(
                    f"{row['hand_id']}/{row['sequence_no']}: action after "
                    f"betting round closed on {street}; ignored."
                )
                continue
            if player in state.folded_players:
                warnings.append(
                    f"{row['hand_id']}/{row['sequence_no']}: action after fold "
                    f"ignored for {row['player_id']}."
                )
                continue
            if player in state.all_in_players:
                warnings.append(
                    f"{row['hand_id']}/{row['sequence_no']}: action after all-in "
                    f"ignored for {row['player_id']}."
                )
                continue

            numeric_to_call = max(
                0.0,
                street_state.current_bet_to
                - street_state.contributions.get(player, 0.0),
            )
            facing = (
                numeric_to_call > 0
                or (
                    street_state.last_aggressor is not None
                    and street_state.last_aggressor != player
                )
            ) and not street_state.betting_round_closed
            amount_to_call: float | None = (
                numeric_to_call
                if numeric_to_call > 0
                else None if facing else 0.0
            )
            legal_actions, decision_type = self._legal_actions(
                row, facing, street, street_state, player
            )
            if action not in legal_actions:
                warnings.append(
                    f"{row['hand_id']}/{row['sequence_no']}: {action} is not "
                    f"legal while facing "
                    f"{amount_to_call if amount_to_call is not None else 'unknown'}; "
                    f"ignored."
                )
                continue

            active = state.active_players - state.folded_players
            actionable = active - state.all_in_players
            opponents = [name for name in active if name != player]
            opponent_key = (
                street_state.last_aggressor
                if facing and street_state.last_aggressor in opponents
                else max(
                    opponents,
                    key=lambda name: street_state.contributions.get(name, 0.0),
                )
                if facing and opponents
                else opponents[0] if len(opponents) == 1 else None
            )
            effective_stack = self._effective_stack(
                state, player, opponent_key, row
            )
            pot_before = (
                float(row["pot_before_action"])
                if row["pot_before_action"] is not None
                else state.pot
            )
            position = state.positions.get(player)
            opponent_position = (
                state.positions.get(opponent_key) if opponent_key else None
            )
            opportunity = DecisionOpportunity(
                hand_id=row["hand_id"],
                player_id=row["player_id"],
                street=street,
                decision_index=row["decision_index"],
                node_key=str(row.get("node_key") or node_key),
                decision_type=decision_type,
                facing_action=(
                    (
                        street_state.last_action
                        if street_state.last_action in {"BET", "RAISE"}
                        else "BET"
                    ) if facing else
                    "CHECK" if street_state.last_action == "CHECK" else "NONE"
                ),
                available_actions=legal_actions,
                chosen_action=action,
                amount=row["amount"],
                raise_to=row["raise_to"],
                pot_before_action=pot_before,
                is_valid=True,
                is_multiway=is_multiway,
                warning=None,
                site=row["site"],
                opponent=(
                    state.player_names.get(opponent_key)
                    if opponent_key else None
                ),
                facing_amount=amount_to_call if facing else 0.0,
                effective_stack=effective_stack,
                position=position,
                opponent_position=opponent_position,
                is_in_position=row["is_in_position"],
                is_heads_up=len(active) == 2,
                players_remaining=len(active),
                action_index=row["sequence_no"],
                timestamp=row["timestamp"],
            )
            seen.add(identity)
            opportunities.append(opportunity)
            self._apply_action(state, street_state, row, player)
            street_state.street_action_index += 1
            self._update_round_closed(state, street_state)
        return opportunities, warnings

    @staticmethod
    def _legal_actions(
        row: Mapping[str, Any],
        facing: bool,
        street: str,
        street_state: _StreetState,
        player: str,
    ) -> tuple[tuple[str, ...], DecisionType]:
        if not facing:
            if (
                street == "PREFLOP"
                and street_state.current_bet_to > 0
                and street_state.contributions.get(player, 0.0)
                >= street_state.current_bet_to
            ):
                return (
                    ("CHECK", "RAISE"),
                    DecisionType.CHECK_OR_RAISE,
                )
            return ("CHECK", "BET"), DecisionType.CHECK_OR_BET
        if row.get("check_allowed"):
            return (
                ("CHECK", "CALL", "RAISE"),
                DecisionType.CHECK_CALL_RAISE,
            )
        if row.get("fold_allowed") is False:
            return ("CALL", "RAISE"), DecisionType.CALL_OR_RAISE
        if row.get("fold_or_continue"):
            return (
                ("FOLD", "CALL", "RAISE"),
                DecisionType.FOLD_OR_CONTINUE,
            )
        return (
            ("FOLD", "CALL", "RAISE"),
            DecisionType.FOLD_CALL_RAISE,
        )

    @staticmethod
    def _canonical_action(
        row: Mapping[str, Any],
        street_state: _StreetState,
        player: str,
    ) -> str:
        raw = str(row.get("raw_action") or "").strip().upper()
        aliases = {
            "RAISES TO": "RAISE", "RAISE_TO": "RAISE",
            "ALL_IN_RAISE": "RAISE", "ALL-IN RAISE": "RAISE",
            "ALL_IN_CALL": "CALL", "ALL-IN CALL": "CALL",
            "ALL_IN_BET": "BET", "ALL-IN BET": "BET",
            "UNCALLED_BET_RETURN": "RETURN", "DEALT": "DEAL",
            "SIT_OUT": "SIT_OUT",
        }
        if raw in aliases:
            return aliases[raw]
        if raw == "ALL_IN" or raw == "ALL-IN":
            current = street_state.contributions.get(player, 0.0)
            target = row.get("raise_to")
            if street_state.current_bet_to <= current:
                return "RAISE" if row.get("street") == "PREFLOP" else "BET"
            if target is not None and float(target) > street_state.current_bet_to:
                return "RAISE"
            return "CALL"
        return raw

    @staticmethod
    def _apply_action(
        state: _HandState,
        street_state: _StreetState,
        row: Mapping[str, Any],
        player: str,
    ) -> None:
        action = str(row["action"])
        amount = float(row["amount"] or 0.0)
        current = street_state.contributions.get(player, 0.0)
        if action in {"POST_SB", "POST_BB"}:
            target = float(row["raise_to"] or amount)
            street_state.contributions[player] = max(current, target)
            street_state.current_bet_to = max(
                street_state.current_bet_to, target
            )
        elif action == "POST_ANTE":
            pass
        elif action == "BET":
            target = float(row["raise_to"] or (current + amount))
            street_state.contributions[player] = target
            street_state.current_bet_to = target
            street_state.last_aggressor = player
            street_state.players_acted_since_last_aggression = {player}
        elif action == "RAISE":
            target = float(row["raise_to"] or (current + amount))
            street_state.contributions[player] = target
            street_state.current_bet_to = target
            street_state.last_aggressor = player
            street_state.players_acted_since_last_aggression = {player}
        elif action == "CALL":
            target = min(
                street_state.current_bet_to,
                current + amount if amount else street_state.current_bet_to,
            )
            street_state.contributions[player] = target
            street_state.players_acted_since_last_aggression.add(player)
        elif action == "CHECK":
            street_state.players_acted_since_last_aggression.add(player)
        elif action == "FOLD":
            state.folded_players.add(player)
            state.active_players.discard(player)
            street_state.players_acted_since_last_aggression.add(player)
        delta = max(
            0.0, street_state.contributions.get(player, current) - current
        )
        state.total_invested[player] = (
            state.total_invested.get(player, 0.0) + delta
        )
        if state.pot is not None:
            state.pot += delta
        if row.get("all_in"):
            state.all_in_players.add(player)
        street_state.last_action = action
    @staticmethod
    def _update_round_closed(
        state: _HandState,
        street_state: _StreetState,
    ) -> None:
        actionable = state.active_players - state.all_in_players
        if not actionable:
            street_state.betting_round_closed = True
            return
        if street_state.last_aggressor is None:
            street_state.betting_round_closed = actionable.issubset(
                street_state.players_acted_since_last_aggression
            )
            return
        responders = actionable - {street_state.last_aggressor}
        street_state.betting_round_closed = responders.issubset(
            street_state.players_acted_since_last_aggression
        )

    @staticmethod
    def _effective_stack(
        state: _HandState,
        player: str,
        opponent: str | None,
        row: Mapping[str, Any],
    ) -> float | None:
        if row.get("effective_stack") is not None:
            return float(row["effective_stack"])
        if opponent is None:
            return None
        if player not in state.starting_stacks or opponent not in state.starting_stacks:
            return None
        player_remaining = max(
            0.0,
            state.starting_stacks[player] - state.total_invested.get(player, 0.0),
        )
        opponent_remaining = max(
            0.0,
            state.starting_stacks[opponent]
            - state.total_invested.get(opponent, 0.0),
        )
        return min(player_remaining, opponent_remaining)

    @staticmethod
    def aggregate_action(
        opportunities: Iterable[DecisionOpportunity],
        action: str,
    ) -> ActionFrequency:
        normalized_action = str(action or "").strip().upper()
        if normalized_action not in DECISION_ACTIONS:
            supported = ", ".join(sorted(DECISION_ACTIONS))
            raise ValueError(
                f"Unsupported aggregate action {action!r}. "
                f"Supported actions: {supported}."
            )
        unique = {
            opportunity.identity: opportunity
            for opportunity in opportunities
            if opportunity.is_valid
            and normalized_action in opportunity.available_actions
        }
        eligible = tuple(unique.values())
        return ActionFrequency(
            action=normalized_action,
            opportunities=len(eligible),
            action_count=sum(
                item.chosen_action == normalized_action for item in eligible
            ),
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
        raw_action = str(
            row.get("action") or row.get("action_type") or ""
        ).strip().upper()
        if not hand_id:
            raise ValueError(f"Action row {source_index} has no hand_id.")
        if not player_id:
            raise ValueError(f"Action row {source_index} has no player_id.")
        if not street:
            raise ValueError(f"Action row {source_index} has no street.")
        sequence = row.get("sequence_no", row.get("action_order"))
        sequence_no = int(sequence) if sequence is not None else source_index + 1
        decision = row.get("decision_index")
        decision_index = int(decision) if decision is not None else sequence_no
        raise_to = row.get("raise_to", row.get("to_amount"))
        return {
            "hand_id": hand_id, "player_id": player_id, "street": street,
            "raw_action": raw_action, "action": raw_action,
            "sequence_no": sequence_no, "decision_index": decision_index,
            "amount": row.get("amount"), "raise_to": raise_to,
            "pot_before_action": row.get("pot_before_action"),
            "effective_stack": row.get("effective_stack"),
            "all_in": bool(row.get("all_in", False)),
            "node_key": row.get("node_key"), "site": row.get("site"),
            "position": row.get("position"),
            "starting_stack": row.get("starting_stack"),
            "is_in_position": row.get("is_in_position"),
            "timestamp": row.get("timestamp"),
            "fold_allowed": row.get("fold_allowed", True),
            "check_allowed": bool(row.get("check_allowed", False)),
            "fold_or_continue": bool(row.get("fold_or_continue", False)),
            "source_index": source_index,
        }

    @staticmethod
    def _player_key(value: Any) -> str:
        return str(value or "").strip().casefold()
