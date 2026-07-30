from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CanonicalWWSResult:
    invested: float
    credit: float
    net: float
    showdown: bool
    non_showdown: float
    bb: float | None
    bb_source: str
    net_bb: float | None
    non_showdown_bb: float | None
    returned: float
    collect: float
    denominator_included: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanonicalWWSEngine:
    """Canonical hand-level WWS accounting shared by every consumer.

    Version 2.1 calculates the actual incremental contribution of RAISE and
    ALL_IN actions.

    In supported hand histories, ``amount`` on a raise may represent the
    raise-by amount rather than the total amount removed from the player's
    stack. ``to_amount`` represents the player's resulting commitment on
    that street.

    Therefore:

        incremental_raise = to_amount - previous_street_commitment

    Antes are invested but do not form part of the betting-street
    commitment. Blinds, calls, bets, raises and all-ins do.

    Rake is not debited separately because collect is the actual post-rake
    award.
    """

    VERSION = "2.1.1"

    ANTE_ACTIONS = frozenset({
        "POST_ANTE",
        "ANTE",
    })

    COMMITMENT_ACTIONS = frozenset({
        "POST_SB",
        "POST_BB",
        "POST_STRADDLE",
        "STRADDLE",
        "CALL",
        "BET",
        "RAISE",
        "ALL_IN",
    })

    RAISE_ACTIONS = frozenset({
        "RAISE",
        "ALL_IN",
    })

    DEBIT_ACTIONS = ANTE_ACTIONS | COMMITMENT_ACTIONS

    CREDIT_ACTIONS = frozenset({
        "COLLECT",
        "COLLECTED",
        "WIN",
        "WINS",
        "WON",
        "AWARD",
        "AWARDED",
        "RETURN",
        "RETURNED",
        "UNCALLED_BET_RETURN",
    })

    RETURN_ACTIONS = frozenset({
        "RETURN",
        "RETURNED",
        "UNCALLED_BET_RETURN",
    })

    COLLECT_ACTIONS = frozenset({
        "COLLECT",
        "COLLECTED",
        "WIN",
        "WINS",
        "WON",
        "AWARD",
        "AWARDED",
    })

    SHOWDOWN_ACTIONS = frozenset({
        "SHOW",
        "SHOWS",
        "REVEAL",
        "REVEALS",
        "MUCK",
        "MUCKS",
        "MUCKED",
    })

    MUCK_ACTIONS = frozenset({
        "MUCK",
        "MUCKS",
        "MUCKED",
    })

    @staticmethod
    def _key(action: Mapping[str, Any]) -> str:
        return str(action.get("action") or "").strip().upper()

    @staticmethod
    def _street(action: Mapping[str, Any]) -> str:
        value = str(action.get("street") or "UNKNOWN").strip().upper()
        return value or "UNKNOWN"

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def calculate(
        cls,
        actions: Iterable[Mapping[str, Any]],
        *,
        header_bb: float | None = None,
        posted_bb: float | None = None,
        summary_showed: bool = False,
        summary_mucked: bool = False,
    ) -> CanonicalWWSResult:
        invested = 0.0
        credit = 0.0
        returned = 0.0
        collect = 0.0
        action_showdown = False

        # Commitment is tracked separately for every street.
        # Antes are intentionally excluded.
        street_commitment: dict[str, float] = {}

        for action in actions:
            key = cls._key(action)
            street = cls._street(action)
            amount = cls._number(action.get("amount"))
            to_amount = cls._number(action.get("to_amount"))

            if key in cls.ANTE_ACTIONS:
                invested += amount

            elif key in cls.COMMITMENT_ACTIONS:
                previous = street_commitment.get(street, 0.0)

                if key in cls.RAISE_ACTIONS and to_amount > 0:
                    incremental = max(to_amount - previous, 0.0)
                    invested += incremental
                    street_commitment[street] = max(previous, to_amount)
                else:
                    invested += amount

                    if to_amount > 0:
                        street_commitment[street] = max(previous, to_amount)
                    else:
                        street_commitment[street] = previous + amount

            if key in cls.CREDIT_ACTIONS:
                credit += amount

            if key in cls.RETURN_ACTIONS:
                returned += amount

            if key in cls.COLLECT_ACTIONS:
                collect += amount

            if key in cls.SHOWDOWN_ACTIONS:
                action_showdown = True

        valid_header = header_bb is not None and float(header_bb) > 0
        valid_posted = posted_bb is not None and float(posted_bb) > 0

        bb = (
            float(header_bb)
            if valid_header
            else float(posted_bb)
            if valid_posted
            else None
        )

        bb_source = (
            "header"
            if valid_header
            else "POST_BB"
            if valid_posted
            else "missing"
        )

        showdown = bool(
            action_showdown
            or summary_showed
            or summary_mucked
        )

        net = credit - invested
        non_showdown = 0.0 if showdown else net
        included = bb is not None and bb > 0

        return CanonicalWWSResult(
            invested=invested,
            credit=credit,
            net=net,
            showdown=showdown,
            non_showdown=non_showdown,
            bb=bb,
            bb_source=bb_source,
            net_bb=net / bb if included else None,
            non_showdown_bb=non_showdown / bb if included else None,
            returned=returned,
            collect=collect,
            denominator_included=included,
        )

    @staticmethod
    def _sql_values(values: frozenset[str]) -> str:
        return ", ".join(
            f"'{value}'"
            for value in sorted(values)
        )

    @classmethod
    def sql_cte(
        cls,
        schema: str = "",
        player_keys: Iterable[str] | None = None,
    ) -> str:
        """Return the canonical all-player-hand CTE body for DuckDB.

        Raise and all-in debits use:

            to_amount - previous street commitment

        The previous commitment is derived from the greatest prior
        ``to_amount`` for that player, hand and street.

        ``schema`` may be ``"prod."`` for services attaching a production
        database read-only.
        """

        ante = cls._sql_values(cls.ANTE_ACTIONS)
        commitment = cls._sql_values(cls.COMMITMENT_ACTIONS)
        raises = cls._sql_values(cls.RAISE_ACTIONS)
        credit = cls._sql_values(cls.CREDIT_ACTIONS)
        returns = cls._sql_values(cls.RETURN_ACTIONS)
        collects = cls._sql_values(cls.COLLECT_ACTIONS)
        showdown = cls._sql_values(cls.SHOWDOWN_ACTIONS)

        keys = [
            str(value).strip().lower().replace("'", "''")
            for value in (player_keys or [])
            if str(value).strip()
        ]

        action_where = (
            "WHERE LOWER(TRIM(player_name)) IN ("
            + ", ".join(f"'{value}'" for value in keys)
            + ")"
            if keys
            else ""
        )

        player_where = (
            "WHERE LOWER(TRIM(hp.player_name)) IN ("
            + ", ".join(f"'{value}'" for value in keys)
            + ")"
            if keys
            else ""
        )

        return f"""
            WITH hand_blinds AS (
                SELECT
                    hand_id,
                    MAX(COALESCE(amount, 0)) FILTER (
                        WHERE UPPER(TRIM(action)) = 'POST_BB'
                    ) AS posted_bb
                FROM {schema}actions
                GROUP BY hand_id
            ),

            normalized_actions AS (
                SELECT
                    hand_id,
                    LOWER(TRIM(player_name)) AS player_key,
                    COALESCE(street, 'UNKNOWN') AS street_key,
                    sequence_no,
                    UPPER(TRIM(action)) AS action_key,
                    COALESCE(amount, 0) AS amount,
                    NULLIF(COALESCE(to_amount, 0), 0) AS action_to_amount
                FROM {schema}actions
                {action_where}
            ),

            actions_with_previous_commitment AS (
                SELECT
                    *,
                    MAX(
                        CASE
                            WHEN action_key IN ({commitment})
                            THEN action_to_amount
                            ELSE NULL
                        END
                    ) OVER (
                        PARTITION BY
                            hand_id,
                            player_key,
                            street_key
                        ORDER BY sequence_no
                        ROWS BETWEEN UNBOUNDED PRECEDING
                             AND 1 PRECEDING
                    ) AS previous_commitment
                FROM normalized_actions
            ),

            action_debits AS (
                SELECT
                    *,
                    CASE
                        WHEN action_key IN ({ante})
                        THEN amount

                        WHEN action_key IN ({raises})
                             AND action_to_amount IS NOT NULL
                        THEN GREATEST(
                            action_to_amount
                            - COALESCE(previous_commitment, 0),
                            0
                        )

                        WHEN action_key IN ({commitment})
                        THEN amount

                        ELSE 0
                    END AS debit
                FROM actions_with_previous_commitment
            ),

            action_rollup AS (
                SELECT
                    hand_id,
                    player_key,

                    SUM(debit) AS invested,

                    SUM(
                        CASE
                            WHEN action_key IN ({credit})
                            THEN amount
                            ELSE 0
                        END
                    ) AS credit,

                    SUM(
                        CASE
                            WHEN action_key IN ({returns})
                            THEN amount
                            ELSE 0
                        END
                    ) AS returned,

                    SUM(
                        CASE
                            WHEN action_key IN ({collects})
                            THEN amount
                            ELSE 0
                        END
                    ) AS collect,

                    BOOL_OR(
                        action_key IN ({showdown})
                    ) AS showdown,

                    BOOL_OR(
                        action_key IN (
                            'MUCK',
                            'MUCKS',
                            'MUCKED'
                        )
                    ) AS mucked_showdown

                FROM action_debits
                GROUP BY
                    hand_id,
                    player_key
            ),

            base AS (
                SELECT
                    hp.hand_id,
                    hp.player_name AS source_player,
                    LOWER(TRIM(hp.player_name)) AS player_key,
                    hp.position,
                    h.site,
                    h.stakes,
                    h.rake,
                    h.flop,
                    h.turn,
                    h.river,
                    h.source_file,
                    COALESCE(ar.invested, 0) AS invested,
                    COALESCE(ar.credit, 0) AS credit,
                    COALESCE(ar.returned, 0) AS returned,
                    COALESCE(ar.collect, 0) AS collect,
                    COALESCE(ar.showdown, FALSE) AS showdown,
                    COALESCE(
                        ar.mucked_showdown,
                        FALSE
                    ) AS mucked_showdown,
                    TRY_CAST(
                        SPLIT_PART(
                            TRIM(h.stakes),
                            '/',
                            2
                        ) AS DOUBLE
                    ) AS header_bb,
                    hb.posted_bb

                FROM {schema}hand_players hp
                JOIN {schema}hands h
                    USING (hand_id)

                LEFT JOIN action_rollup ar
                    ON ar.hand_id = hp.hand_id
                   AND ar.player_key = LOWER(
                       TRIM(hp.player_name)
                   )

                LEFT JOIN hand_blinds hb
                    USING (hand_id)

                {player_where}
            )

            SELECT
                *,
                credit - invested AS net,

                CASE
                    WHEN showdown
                    THEN 0
                    ELSE credit - invested
                END AS non_showdown,

                COALESCE(
                    NULLIF(header_bb, 0),
                    NULLIF(posted_bb, 0)
                ) AS bb,

                CASE
                    WHEN header_bb > 0
                    THEN 'header'
                    WHEN posted_bb > 0
                    THEN 'POST_BB'
                    ELSE 'missing'
                END AS bb_source,

                (credit - invested) / NULLIF(
                    COALESCE(
                        NULLIF(header_bb, 0),
                        NULLIF(posted_bb, 0)
                    ),
                    0
                ) AS net_bb,

                CASE
                    WHEN showdown
                    THEN 0
                    ELSE credit - invested
                END / NULLIF(
                    COALESCE(
                        NULLIF(header_bb, 0),
                        NULLIF(posted_bb, 0)
                    ),
                    0
                ) AS non_showdown_bb,

                COALESCE(
                    NULLIF(header_bb, 0),
                    NULLIF(posted_bb, 0)
                ) > 0 AS denominator_included

            FROM base
        """

    @classmethod
    def source_metadata(cls) -> dict[str, str]:
        return {
            "engine": "CanonicalWWSEngine",
            "version": cls.VERSION,
            "net": "credit - invested",
            "raise": (
                "to_amount - previous street commitment; "
                "amount fallback"
            ),
            "non_showdown": "0 if showdown else net",
            "bb": "header big blind, POST_BB fallback",
        }
