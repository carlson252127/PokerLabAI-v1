from __future__ import annotations

"""Canonical tracker-style poker statistic definitions.

Keep action vocabulary here so analytical services cannot silently disagree
about wins and showdowns.  The parser stores normalized uppercase actions, but
the SQL helpers remain defensive for databases created by older builds.
"""

WIN_ACTIONS = frozenset(
    {"COLLECT", "COLLECTED", "WIN", "WINS", "WON", "AWARD", "AWARDED"}
)
SHOW_ACTIONS = frozenset({"SHOW", "SHOWS", "REVEAL", "REVEALS"})
MUCK_ACTIONS = frozenset({"MUCK", "MUCKS", "MUCKED"})
SHOWDOWN_ACTIONS = SHOW_ACTIONS | MUCK_ACTIONS
PREFLOP_CONTINUE_ACTIONS = frozenset({"CALL", "RAISE", "CHECK"})
AGGRESSIVE_ACTIONS = frozenset({"BET", "RAISE"})
CHECK_OR_BET_ACTIONS = frozenset({"CHECK", "BET"})
FACING_ACTIONS = frozenset({"FOLD", "CALL", "RAISE"})
DECISION_ACTIONS = CHECK_OR_BET_ACTIONS | FACING_ACTIONS
NON_DECISION_ACTIONS = frozenset(
    {
        "POST_SB",
        "POST_BB",
        "POST_ANTE",
        "SHOW",
        "MUCK",
        "COLLECT",
        "RETURN",
        "WIN",
        "DEAL",
        "STREET_MARKER",
    }
)


def sql_values(values: frozenset[str]) -> str:
    """Return a safe SQL literal list for trusted, module-owned constants."""
    return ", ".join(f"'{value}'" for value in sorted(values))


def percentage(numerator: int, denominator: int) -> float:
    return numerator / denominator * 100.0 if denominator else 0.0
