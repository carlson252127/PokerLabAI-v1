from __future__ import annotations

import json
import unittest

from models.decision_opportunity import DecisionOpportunity, DecisionType
from services.decision_opportunity_service import DecisionOpportunityService


def row(
    sequence: int,
    player: str,
    action: str,
    *,
    street: str = "FLOP",
    **extra: object,
) -> dict[str, object]:
    return {
        "hand_id": "h-state",
        "sequence_no": sequence,
        "street": street,
        "player_name": player,
        "action": action,
        **extra,
    }


class DecisionOpportunityStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DecisionOpportunityService()
        self.players = ("Alice", "Bob")

    def extract(self, actions, **kwargs):
        return self.service.build(
            actions, player_ids=self.players, **kwargs
        )

    def test_same_input_is_pure_and_deterministic(self) -> None:
        actions = [row(1, "Alice", "BET", amount=10), row(2, "Bob", "CALL", amount=10)]
        first = self.service.extract_from_actions(actions, player_ids=self.players)
        second = self.service.extract_from_actions(actions, player_ids=self.players)
        self.assertEqual(first, second)
        self.assertEqual([item.to_key() for item in first], [item.to_key() for item in second])

    def test_opportunity_uses_state_before_action(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=10, pot_before_action=20),
                row(2, "Bob", "CALL", amount=10, pot_before_action=30),
            ]
        )
        caller = result.opportunities[1]
        self.assertEqual(caller.facing_action, "BET")
        self.assertEqual(caller.facing_amount, 10)
        self.assertEqual(caller.pot_before_action, 30)
        self.assertEqual(caller.legal_actions, ("FOLD", "CALL", "RAISE"))

    def test_blinds_affect_preflop_amount_to_call_but_are_not_decisions(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "POST_SB", street="PREFLOP", amount=.5),
                row(2, "Bob", "POST_BB", street="PREFLOP", amount=1),
                row(3, "Alice", "CALL", street="PREFLOP", amount=.5),
            ]
        )
        self.assertEqual(len(result.opportunities), 1)
        self.assertEqual(result.opportunities[0].facing_amount, .5)

    def test_new_street_resets_aggression(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=10),
                row(2, "Bob", "CALL", amount=10),
                row(3, "Bob", "CHECK", street="TURN"),
            ]
        )
        turn = result.opportunities[-1]
        self.assertEqual(turn.decision_type, DecisionType.CHECK_OR_BET)
        self.assertEqual(turn.facing_action, "NONE")

    def test_raise_to_is_canonical_raise_and_keeps_amount(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=10),
                row(2, "Bob", "RAISE_TO", amount=20, to_amount=30),
                row(3, "Alice", "FOLD"),
            ]
        )
        raised = result.opportunities[1]
        folded = result.opportunities[2]
        self.assertEqual(raised.chosen_action, "RAISE")
        self.assertEqual((raised.amount, raised.raise_to), (20, 30))
        self.assertEqual(folded.facing_action, "RAISE")
        self.assertEqual(folded.facing_amount, 20)

    def test_all_in_open_action_is_bet(self) -> None:
        result = self.extract(
            [row(1, "Alice", "ALL_IN", amount=25, all_in=True)]
        )
        self.assertEqual(result.opportunities[0].chosen_action, "BET")

    def test_all_in_facing_action_is_call_without_raise_to(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=25),
                row(2, "Bob", "ALL_IN", amount=25, all_in=True),
            ]
        )
        self.assertEqual(result.opportunities[1].chosen_action, "CALL")

    def test_foldless_special_state_uses_call_or_raise(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=10),
                row(2, "Bob", "CALL", amount=10, fold_allowed=False),
            ]
        )
        decision = result.opportunities[1]
        self.assertEqual(decision.decision_type, DecisionType.CALL_OR_RAISE)
        self.assertEqual(decision.legal_actions, ("CALL", "RAISE"))

    def test_non_decision_terminal_actions_do_not_create_opportunities(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "RETURN", amount=5),
                row(2, "Alice", "COLLECT", amount=20),
                row(3, "Alice", "UNCALLED_BET_RETURN", amount=5),
                row(4, "Alice", "SHOW"),
            ]
        )
        self.assertEqual(result.opportunities, ())

    def test_duplicate_action_identity_is_emitted_once(self) -> None:
        duplicate = row(1, "Alice", "CHECK", decision_index=8)
        result = self.extract([duplicate, dict(duplicate)])
        self.assertEqual(len(result.opportunities), 1)
        self.assertTrue(any("duplicate" in warning for warning in result.warnings))

    def test_extract_from_hand_populates_context_fields(self) -> None:
        hand = {
            "hand": {
                "hand_id": "h-context",
                "site": "Synthetic",
                "played_at": "2026-07-24T12:00:00+00:00",
            },
            "players": [
                {"player_name": "Alice", "position": "BTN", "starting_stack": 100},
                {"player_name": "Bob", "position": "BB", "starting_stack": 80},
            ],
            "actions": [
                row(1, "Alice", "BET", amount=10),
                row(2, "Bob", "CALL", amount=10),
            ],
        }
        opportunities = self.service.extract_from_hand(hand)
        first = opportunities[0]
        self.assertEqual(first.site, "Synthetic")
        self.assertEqual(first.actor, "Alice")
        self.assertEqual(first.opponent, "Bob")
        self.assertEqual(first.position, "BTN")
        self.assertEqual(first.opponent_position, "BB")
        self.assertEqual(first.effective_stack, 80)
        self.assertEqual(first.players_remaining, 2)
        self.assertTrue(first.is_heads_up)
        self.assertEqual(first.action_index, 1)
        self.assertIsNotNone(first.timestamp)

    def test_folded_and_all_in_players_cannot_act_later(self) -> None:
        folded = self.extract(
            [
                row(1, "Alice", "BET", amount=10),
                row(2, "Bob", "FOLD"),
                row(3, "Bob", "CHECK", street="TURN"),
            ]
        )
        self.assertEqual(len(folded.opportunities), 2)
        self.assertTrue(any("after fold" in warning for warning in folded.warnings))

        all_in = self.extract(
            [
                row(1, "Alice", "BET", amount=10, all_in=True),
                row(2, "Bob", "CALL", amount=10),
                row(3, "Alice", "CHECK", street="TURN"),
            ]
        )
        self.assertEqual(len(all_in.opportunities), 2)
        self.assertTrue(any("after all-in" in warning for warning in all_in.warnings))

    def test_extended_opportunity_json_round_trip(self) -> None:
        hand = {
            "hand": {
                "hand_id": "h-round-trip",
                "site": "Synthetic",
                "played_at": "2026-07-24T12:00:00+00:00",
            },
            "players": [
                {"player_name": "Alice", "position": "BTN", "starting_stack": 100},
                {"player_name": "Bob", "position": "BB", "starting_stack": 80},
            ],
            "actions": [row(1, "Alice", "BET", amount=10)],
        }
        original = self.service.extract_from_hand(hand)[0]
        restored = DecisionOpportunity.from_dict(
            json.loads(json.dumps(original.to_dict()))
        )
        self.assertEqual(original, restored)
        self.assertEqual(original.to_key(), restored.to_key())

    def test_required_multiway_line_is_valid_and_uses_last_aggressor(self) -> None:
        result = self.service.build(
            [
                row(1, "Alice", "CHECK"),
                row(2, "Bob", "BET", amount=10),
                row(3, "Carol", "CALL", amount=10),
                row(4, "Alice", "FOLD"),
            ],
            player_ids=("Alice", "Bob", "Carol"),
        )
        self.assertEqual(len(result.opportunities), 4)
        self.assertTrue(all(item.is_valid for item in result.opportunities))
        self.assertEqual(
            [item.players_remaining for item in result.opportunities],
            [3, 3, 3, 3],
        )
        self.assertIsNone(result.opportunities[0].opponent)
        self.assertIsNone(result.opportunities[1].opponent)
        self.assertEqual(result.opportunities[2].opponent, "Bob")
        self.assertEqual(result.opportunities[3].opponent, "Bob")
        fold = self.service.aggregate_action(result.opportunities, "FOLD")
        call = self.service.aggregate_action(result.opportunities, "CALL")
        raise_frequency = self.service.aggregate_action(
            result.opportunities, "RAISE"
        )
        self.assertEqual(fold.opportunities, 2)
        self.assertEqual(call.opportunities, 2)
        self.assertEqual(raise_frequency.opportunities, 2)

    def test_preflop_bb_option_is_check_or_raise(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "POST_SB", street="PREFLOP", amount=.5),
                row(2, "Bob", "POST_BB", street="PREFLOP", amount=1),
                row(3, "Alice", "CALL", street="PREFLOP", amount=.5),
                row(4, "Bob", "CHECK", street="PREFLOP"),
            ]
        )
        bb_option = result.opportunities[-1]
        self.assertEqual(
            bb_option.decision_type, DecisionType.CHECK_OR_RAISE
        )
        self.assertEqual(bb_option.legal_actions, ("CHECK", "RAISE"))
        self.assertEqual(bb_option.chosen_action, "CHECK")

    def test_round_closed_rejects_extra_same_street_action(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=10),
                row(2, "Bob", "CALL", amount=10),
                row(3, "Alice", "CHECK"),
            ]
        )
        self.assertEqual(len(result.opportunities), 2)
        self.assertTrue(
            any("round closed" in warning for warning in result.warnings)
        )

    def test_backwards_street_transition_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "moved backwards"):
            self.extract(
                [
                    row(1, "Alice", "CHECK", street="TURN"),
                    row(2, "Bob", "CHECK", street="FLOP"),
                ]
            )

    def test_bet_bet_raise_reraise_line_has_one_opportunity_per_action(self) -> None:
        result = self.extract(
            [
                row(1, "Alice", "BET", amount=10, to_amount=10),
                row(2, "Bob", "RAISE", amount=20, to_amount=30),
                row(3, "Alice", "RAISE", amount=40, to_amount=50),
                row(4, "Bob", "CALL", amount=20),
            ]
        )
        self.assertEqual(len(result.opportunities), 4)
        self.assertEqual(
            [item.chosen_action for item in result.opportunities],
            ["BET", "RAISE", "RAISE", "CALL"],
        )

    def test_three_check_or_bet_opportunities_aggregate_two_thirds_bet(self) -> None:
        opportunities = []
        for index, chosen in enumerate(("CHECK", "BET", "BET"), start=1):
            extracted = self.service.extract_from_actions(
                [row(index, f"P{index}", chosen, hand_id=f"h-{index}")],
                player_ids=(f"P{index}", "Villain"),
            )
            opportunities.extend(extracted)
        frequency = self.service.aggregate_action(opportunities, "BET")
        self.assertEqual(frequency.action_count, 2)
        self.assertEqual(frequency.opportunities, 3)
        self.assertAlmostEqual(frequency.frequency or 0.0, 2 / 3)


if __name__ == "__main__":
    unittest.main()
