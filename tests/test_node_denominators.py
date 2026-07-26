from __future__ import annotations

import unittest

from models.decision_opportunity import DecisionOpportunity, DecisionType
from services.decision_opportunity_service import DecisionOpportunityService


def action(
    sequence_no: int,
    player: str,
    chosen: str,
    *,
    hand_id: str = "h1",
    street: str = "FLOP",
    **extra: object,
) -> dict[str, object]:
    return {
        "hand_id": hand_id,
        "sequence_no": sequence_no,
        "street": street,
        "player_name": player,
        "action": chosen,
        **extra,
    }


class DecisionOpportunityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DecisionOpportunityService()

    def build(
        self,
        rows: list[dict[str, object]],
        players: tuple[str, ...] = ("Alice", "Bob"),
        **kwargs: object,
    ):
        return self.service.build(
            rows,
            player_ids=players,
            **kwargs,
        )

    def test_first_player_check_is_check_or_bet_opportunity(self) -> None:
        result = self.build([action(1, "Alice", "CHECK")])
        opportunity = result.opportunities[0]
        self.assertEqual(opportunity.decision_type, DecisionType.CHECK_OR_BET)
        self.assertEqual(opportunity.available_actions, ("CHECK", "BET"))
        self.assertEqual(opportunity.chosen_action, "CHECK")

    def test_first_player_bet_uses_same_denominator(self) -> None:
        result = self.build([action(1, "Alice", "BET")])
        bet = self.service.aggregate_action(result.opportunities, "BET")
        check = self.service.aggregate_action(result.opportunities, "CHECK")
        self.assertEqual((bet.action_count, bet.opportunities), (1, 1))
        self.assertEqual((check.action_count, check.opportunities), (0, 1))

    def test_facing_bet_fold(self) -> None:
        result = self.build(
            [action(1, "Alice", "BET"), action(2, "Bob", "FOLD")]
        )
        fold = self.service.aggregate_action(result.opportunities, "FOLD")
        self.assertEqual((fold.action_count, fold.opportunities), (1, 1))

    def test_facing_bet_call(self) -> None:
        result = self.build(
            [action(1, "Alice", "BET"), action(2, "Bob", "CALL")]
        )
        call = self.service.aggregate_action(result.opportunities, "CALL")
        self.assertEqual((call.action_count, call.opportunities), (1, 1))

    def test_facing_bet_raise(self) -> None:
        result = self.build(
            [action(1, "Alice", "BET"), action(2, "Bob", "RAISE")]
        )
        raise_frequency = self.service.aggregate_action(
            result.opportunities, "RAISE"
        )
        self.assertEqual(
            (raise_frequency.action_count, raise_frequency.opportunities),
            (1, 1),
        )

    def test_check_check_creates_two_player_opportunities(self) -> None:
        result = self.build(
            [action(1, "Alice", "CHECK"), action(2, "Bob", "CHECK")]
        )
        check = self.service.aggregate_action(result.opportunities, "CHECK")
        self.assertEqual((check.action_count, check.opportunities), (2, 2))
        self.assertEqual(check.sample_players, 2)
        self.assertEqual(
            [row.facing_action for row in result.opportunities],
            ["NONE", "CHECK"],
        )

    def test_bet_call_line_creates_correct_opportunities(self) -> None:
        result = self.build(
            [action(1, "Alice", "BET"), action(2, "Bob", "CALL")]
        )
        self.assertEqual(len(result.opportunities), 2)
        self.assertEqual(
            [row.decision_type for row in result.opportunities],
            [
                DecisionType.CHECK_OR_BET,
                DecisionType.FOLD_CALL_OR_RAISE,
            ],
        )

    def test_bet_raise_fold_has_distinct_decision_indices(self) -> None:
        result = self.build(
            [
                action(10, "Alice", "BET"),
                action(20, "Bob", "RAISE"),
                action(30, "Alice", "FOLD"),
            ]
        )
        self.assertEqual(
            [row.decision_index for row in result.opportunities],
            [10, 20, 30],
        )
        self.assertEqual(
            [row.facing_action for row in result.opportunities],
            ["NONE", "BET", "RAISE"],
        )

    def test_show_does_not_enter_denominator(self) -> None:
        result = self.build([action(1, "Alice", "SHOW")])
        self.assertEqual(result.opportunities, ())

    def test_collect_does_not_enter_denominator(self) -> None:
        result = self.build([action(1, "Alice", "COLLECT")])
        self.assertEqual(result.opportunities, ())

    def test_return_does_not_enter_denominator(self) -> None:
        result = self.build([action(1, "Alice", "RETURN")])
        self.assertEqual(result.opportunities, ())

    def test_blind_posts_do_not_enter_denominator(self) -> None:
        result = self.build(
            [
                action(1, "Alice", "POST_SB", street="PREFLOP"),
                action(2, "Bob", "POST_BB", street="PREFLOP"),
            ]
        )
        self.assertEqual(result.opportunities, ())

    def test_duplicate_action_is_counted_once(self) -> None:
        rows = [
            action(1, "Alice", "BET", decision_index=7),
            action(1, "Alice", "BET", decision_index=7),
        ]
        result = self.build(rows)
        self.assertEqual(len(result.opportunities), 1)
        self.assertTrue(any("duplicate" in text for text in result.warnings))

    def test_folded_player_gets_no_later_street_opportunity(self) -> None:
        result = self.build(
            [
                action(1, "Alice", "BET"),
                action(2, "Bob", "FOLD"),
                action(3, "Bob", "CHECK", street="TURN"),
            ]
        )
        self.assertEqual(len(result.opportunities), 2)
        self.assertTrue(any("after fold" in text for text in result.warnings))

    def test_all_in_player_gets_no_later_street_opportunity(self) -> None:
        result = self.build(
            [
                action(1, "Alice", "BET", all_in=True),
                action(2, "Bob", "CALL"),
                action(3, "Alice", "CHECK", street="TURN"),
            ]
        )
        self.assertEqual(len(result.opportunities), 2)
        self.assertTrue(any("after all-in" in text for text in result.warnings))

    def test_unknown_pot_produces_no_size_ratio(self) -> None:
        result = self.build(
            [action(1, "Alice", "BET", amount=25)]
        )
        self.assertIsNone(result.opportunities[0].pot_before_action)
        self.assertIsNone(result.opportunities[0].size_ratio)

    def test_zero_opportunities_produces_missing_frequency(self) -> None:
        frequency = self.service.aggregate_action((), "BET")
        self.assertEqual(frequency.opportunities, 0)
        self.assertIsNone(frequency.frequency)

    def test_same_decision_identity_is_aggregated_once(self) -> None:
        opportunity = DecisionOpportunity(
            hand_id="h1",
            player_id="Alice",
            street="FLOP",
            decision_index=1,
            node_key="node",
            decision_type="CHECK_OR_BET",
            facing_action="NONE",
            available_actions=("CHECK", "BET"),
            chosen_action="BET",
        )
        frequency = self.service.aggregate_action(
            (opportunity, opportunity), "BET"
        )
        self.assertEqual((frequency.action_count, frequency.opportunities), (1, 1))

    def test_decision_type_rejects_incompatible_legal_actions(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "CHECK_OR_BET requires available_actions"
        ):
            DecisionOpportunity(
                hand_id="h-invalid-actions",
                player_id="Alice",
                street="FLOP",
                decision_index=0,
                node_key="node",
                decision_type="CHECK_OR_BET",
                facing_action="NONE",
                available_actions=("CHECK", "BET", "FOLD"),
                chosen_action="CHECK",
            )

    def test_multiway_can_be_excluded_or_aggregated_explicitly(self) -> None:
        rows = [
            action(1, "Alice", "BET"),
            action(2, "Bob", "CALL"),
        ]
        excluded = self.build(
            rows,
            players=("Alice", "Bob", "Carol"),
            include_multiway=False,
        )
        self.assertEqual(excluded.opportunities, ())
        self.assertTrue(any("multiway" in text for text in excluded.warnings))

        included = self.build(
            rows,
            players=("Alice", "Bob", "Carol"),
            include_multiway=True,
        )
        self.assertTrue(included.opportunities)
        self.assertTrue(
            all(
                row.is_multiway and row.is_valid
                for row in included.opportunities
            )
        )
        aggregate = self.service.aggregate_action(
            included.opportunities, "BET"
        )
        self.assertEqual(aggregate.opportunities, 1)

    def test_raise_to_and_raise_by_are_not_confused(self) -> None:
        result = self.build(
            [
                action(1, "Alice", "BET", amount=10, pot_before_action=100),
                action(
                    2,
                    "Bob",
                    "RAISE",
                    amount=20,
                    to_amount=30,
                    pot_before_action=100,
                ),
            ]
        )
        raise_opportunity = result.opportunities[1]
        self.assertEqual(raise_opportunity.amount, 20)
        self.assertEqual(raise_opportunity.raise_to, 30)
        self.assertAlmostEqual(raise_opportunity.size_ratio or 0.0, 0.20)


if __name__ == "__main__":
    unittest.main()
