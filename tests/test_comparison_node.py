from __future__ import annotations

import json
import unittest

from models.comparison_node import ComparisonNode


def node(**overrides: object) -> ComparisonNode:
    values: dict[str, object] = {
        "site": "CoinPoker", "stake": "NL100", "game_format": "NLHE",
        "table_size": 6, "ante": 0, "effective_stack_bucket": "100bb",
        "hero_position": "BTN", "villain_position": "BB",
        "actor_position": "BTN", "opponent_position": "BB",
        "position_relation": "IP", "preflop_pot_type": "SRP",
        "preflop_action_line": "BTN R2.5 BB C", "street": "FLOP",
        "board": "Ah 7d 2c", "board_family": "A high rainbow",
        "players_remaining": 2, "is_heads_up": True,
        "previous_street_line": "BTN R2.5 BB C", "facing_action": "CHECK",
        "facing_size_bucket": "NONE", "pot_bucket": "SMALL",
        "spr_bucket": "HIGH", "decision_player_role": "PFR",
        "legal_actions": ("CHECK", "BET"), "cohort_axis": "ACTOR",
    }
    values.update(overrides)
    return ComparisonNode(**values)


class ComparisonNodeTests(unittest.TestCase):
    def test_same_node_same_key(self) -> None:
        self.assertEqual(node().to_key(), node().to_key())

    def test_field_order_does_not_change_key(self) -> None:
        data = node().to_dict()
        self.assertEqual(
            ComparisonNode.from_dict(data).to_key(),
            ComparisonNode.from_dict(dict(reversed(list(data.items())))).to_key(),
        )

    def test_case_is_normalized(self) -> None:
        self.assertEqual(
            node().to_key(),
            node(site="coinpoker", street="flop", hero_position="btn").to_key(),
        )

    def test_legal_action_order_does_not_change_key(self) -> None:
        self.assertEqual(
            node(legal_actions=("BET", "CHECK")).to_key(),
            node(legal_actions=("CHECK", "BET")).to_key(),
        )

    def test_duplicate_legal_action_does_not_change_key(self) -> None:
        self.assertEqual(
            node(legal_actions=("CHECK", "BET", "CHECK")).to_key(),
            node(legal_actions=("CHECK", "BET")).to_key(),
        )

    def test_different_board_changes_key(self) -> None:
        self.assertNotEqual(node().to_key(), node(board="Kh 7d 2c").to_key())

    def test_different_preflop_line_changes_key(self) -> None:
        self.assertNotEqual(
            node().to_key(), node(preflop_action_line="CO R2.5 BB C").to_key()
        )

    def test_different_cohort_axis_changes_key(self) -> None:
        self.assertNotEqual(node().to_key(), node(cohort_axis="RESPONDER").to_key())

    def test_dates_are_not_node_fields(self) -> None:
        with self.assertRaises(TypeError):
            ComparisonNode.from_dict({**node().to_dict(), "date_from": "2026-01-01"})

    def test_minimum_sample_is_not_node_field_or_key(self) -> None:
        with self.assertRaises(TypeError):
            ComparisonNode.from_dict({**node().to_dict(), "minimum_sample": 50})

    def test_invalid_position_rejected(self) -> None:
        with self.assertRaises(ValueError):
            node(hero_position="UTG+2")

    def test_showdown_rejected(self) -> None:
        with self.assertRaises(ValueError):
            node(street="SHOWDOWN")

    def test_empty_and_none_normalize_equally(self) -> None:
        self.assertEqual(node(pot_bucket="").to_key(), node(pot_bucket=None).to_key())

    def test_round_trip_preserves_key(self) -> None:
        restored = ComparisonNode.from_dict(json.loads(json.dumps(node().to_dict())))
        self.assertEqual(node(), restored)
        self.assertEqual(node().to_key(), restored.to_key())

    def test_key_payload_survives_json_round_trip(self) -> None:
        original = node()
        restored = ComparisonNode.from_dict(
            json.loads(json.dumps(original.to_dict()))
        )
        self.assertEqual(original.to_key_payload(), restored.to_key_payload())

    def test_each_identity_field_survives_round_trip(self) -> None:
        fields: dict[str, object] = {
            "site": "CoinPoker", "stake": "NL200", "game_format": "NLHE",
            "table_size": 6, "ante": 0, "effective_stack_bucket": "150bb",
            "hero_position": "CO", "villain_position": "BB",
            "actor_position": "CO", "opponent_position": "BB",
            "position_relation": "IP", "preflop_pot_type": "THREE_BET",
            "preflop_action_line": "CO R2.5 BB R10 CO C", "street": "TURN",
            "board": "Ah 7d 2c Ks", "board_key": "Ah 7d 2c Ks",
            "board_family": "A high rainbow", "players_remaining": 2,
            "is_heads_up": True, "previous_street_line": "X B C",
            "facing_action": "BET", "facing_size_bucket": "66PCT",
            "pot_bucket": "MEDIUM", "spr_bucket": "LOW",
            "decision_player_role": "CALLER",
            "legal_actions": ("FOLD", "CALL", "RAISE"),
            "cohort_axis": "RESPONDER",
        }
        baseline = node()
        for field_name, field_value in fields.items():
            with self.subTest(field=field_name):
                original = ComparisonNode.from_dict(
                    {**baseline.to_dict(), field_name: field_value}
                )
                restored = ComparisonNode.from_dict(
                    json.loads(json.dumps(original.to_dict()))
                )
                self.assertEqual(
                    original.to_key_payload(), restored.to_key_payload()
                )

    def test_false_and_none_are_not_merged(self) -> None:
        false_node = node(players_remaining=3, is_heads_up=False)
        none_node = node(players_remaining=3, is_heads_up=None)
        self.assertIs(false_node.is_heads_up, False)
        self.assertIsNone(none_node.is_heads_up)
        self.assertNotEqual(false_node.to_key(), none_node.to_key())

    def test_json_numeric_round_trip_preserves_key(self) -> None:
        original = node(ante=0, table_size=6, players_remaining=2)
        restored = ComparisonNode.from_dict(
            json.loads(json.dumps(original.to_dict()))
        )
        self.assertEqual(original.ante, 0.0)
        self.assertEqual(original.to_key(), restored.to_key())

    def test_legal_actions_round_trip_is_canonical(self) -> None:
        original = node(
            legal_actions=("RAISE", "FOLD", "CALL", "CALL")
        )
        restored = ComparisonNode.from_dict(
            {
                **original.to_dict(),
                "legal_actions": ["call", "raise", "fold"],
            }
        )
        self.assertEqual(original.legal_actions, ("CALL", "FOLD", "RAISE"))
        self.assertEqual(original.to_key_payload(), restored.to_key_payload())


if __name__ == "__main__":
    unittest.main()
