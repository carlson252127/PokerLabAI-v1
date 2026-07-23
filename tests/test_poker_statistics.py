from __future__ import annotations

import unittest

from services.poker_statistics import percentage
from services.tracker_statistics_service import TrackerStatisticsService


def record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "hand_id": "1",
        "player_name": "Hero",
        "position": "BTN",
        "hand_reached_flop": True,
        "folded_preflop": False,
        "preflop_continue": True,
        "has_flop_action": True,
        "has_turn_action": False,
        "has_river_action": False,
        "won_pot": False,
        "went_showdown": False,
        "flop_aggressive": False,
        "turn_aggressive": False,
        "river_aggressive": False,
        "saw_flop": True,
        "river_bet": False,
    }
    base.update(overrides)
    return base


class PokerStatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = TrackerStatisticsService(":memory:")

    def test_percentage_zero_denominator(self) -> None:
        self.assertEqual(percentage(5, 0), 0.0)

    def test_tracker_metrics_use_correct_denominators(self) -> None:
        rows = [
            # Uncontested postflop win: WWSF win, never a showdown.
            record(hand_id="1", won_pot=True),
            # River bet, explicit showdown, and win.
            record(
                hand_id="2",
                has_turn_action=True,
                has_river_action=True,
                river_aggressive=True,
                river_bet=True,
                went_showdown=True,
                won_pot=True,
            ),
            # River bet and explicit showdown loss.
            record(
                hand_id="3",
                has_turn_action=True,
                has_river_action=True,
                river_aggressive=True,
                river_bet=True,
                went_showdown=True,
            ),
            # Explicit showdown win without a river bet (including split pots).
            record(
                hand_id="4",
                has_turn_action=True,
                has_river_action=True,
                went_showdown=True,
                won_pot=True,
            ),
            # Another player showed in this multiway hand, but Hero did not.
            record(hand_id="5", has_turn_action=True, has_river_action=True),
        ]

        metrics = self.service._metrics(rows)

        self.assertEqual(metrics["flop_seen"], 5)
        self.assertEqual(metrics["showdown"], 3)
        self.assertEqual(metrics["showdown_wins"], 2)
        self.assertAlmostEqual(metrics["wwsf"], 60.0)
        self.assertAlmostEqual(metrics["wtsd"], 60.0)
        self.assertAlmostEqual(metrics["wsd"], 200.0 / 3.0)
        self.assertEqual(metrics["river_bet_showdowns"], 2)
        self.assertEqual(metrics["river_bet_showdown_wins"], 1)
        self.assertAlmostEqual(metrics["river_bet_wsd"], 50.0)


if __name__ == "__main__":
    unittest.main()
