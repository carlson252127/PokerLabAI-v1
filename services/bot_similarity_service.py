from __future__ import annotations

import math
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb

from services.player_stats_service import PlayerStatsService


class BotSimilarityService:
    _PROFILE_CACHE: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    _PROFILE_CACHE_LOCK = Lock()
    _PROFILE_CACHE_LIMIT = 6

    FEATURE_KEYS = [
        "vpip",
        "pfr",
        "three_bet",
        "fold_to_3bet",
        "flop_cbet",
        "turn_barrel",
        "river_barrel",
        "ep_open_gt_34",
        "mp_open_gt_34",
        "co_open_gt_34",
        "btn_open_gt_34",
        "sb_open_gt_34",
        "turn_cbet_ip_size_25_40",
        "wwsf",
    ]

    FEATURE_LABELS = {
        "vpip": "VPIP",
        "pfr": "PFR",
        "three_bet": "3Bet",
        "fold_to_3bet": "Fold to 3Bet",
        "flop_cbet": "Flop CBet",
        "turn_barrel": "Turn Barrel",
        "river_barrel": "River Barrel",
        "ep_open_gt_34": "EP Open >3.4x",
        "mp_open_gt_34": "MP Open >3.4x",
        "co_open_gt_34": "CO Open >3.4x",
        "btn_open_gt_34": "BTN Open >3.4x",
        "sb_open_gt_34": "SB Open >3.4x",
        "turn_cbet_ip_size_25_40": "Turn CBet IP 25–40 FQ %",
        "wwsf": "WWSF",
    }

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        self.database_path = str(Path(database_path))
        self.player_service = PlayerStatsService(
            self.database_path
        )
        self.last_filter_diagnostics: dict[str, int] = {}

    def get_entities(
        self,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 750,
        minimum_vpip: float = 30.0,
        minimum_pfr: float = 20.0,
        large_open_threshold: float = 3.4,
        turn_size_frequency_target: float | None = None,
        turn_size_frequency_tolerance: float = 2.0,
        wwsf_target: float | None = None,
        wwsf_tolerance: float = 2.0,
        use_aliases: bool = True,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        cache_key = (
            str(Path(self.database_path).resolve()),
            *self._database_version(),
            site,
            stakes,
            max(1, int(minimum_hands)),
            float(minimum_vpip),
            float(minimum_pfr),
            float(large_open_threshold),
            bool(use_aliases),
        )
        with self._PROFILE_CACHE_LOCK:
            cached = self._PROFILE_CACHE.get(cache_key)

        if cached is None:
            base_rows = self.player_service.get_players(
                site=site,
                stakes=stakes,
                name_query="",
                minimum_hands=1,
                limit=100_000,
            )
            rows = (
                self._merge_alias_profiles(base_rows)
                if use_aliases
                else [dict(row, merged_nicks=1) for row in base_rows]
            )
            candidates = [
                row for row in rows
                if int(row.get("hands") or 0) >= max(1, int(minimum_hands))
                and float(row.get("vpip") or 0.0) > float(minimum_vpip)
                and float(row.get("pfr") or 0.0) > float(minimum_pfr)
            ]
            extras = {
                row["player_name"]: row
                for row in self._extra_profiles(
                    site,
                    stakes,
                    use_aliases,
                    large_open_threshold,
                    [str(row["player_name"]) for row in candidates],
                )
            }
            enriched: list[dict[str, Any]] = []
            for row in candidates:
                merged = dict(row)
                merged.update(extras.get(str(row["player_name"]), {}))
                merged["player_name"] = row["player_name"]
                merged["hands"] = int(row.get("hands") or 0)
                merged["merged_nicks"] = int(row.get("merged_nicks") or 1)
                enriched.append(merged)
            enriched.sort(
                key=lambda row: int(row.get("hands") or 0),
                reverse=True,
            )
            with self._PROFILE_CACHE_LOCK:
                if len(self._PROFILE_CACHE) >= self._PROFILE_CACHE_LIMIT:
                    oldest_key = next(iter(self._PROFILE_CACHE))
                    self._PROFILE_CACHE.pop(oldest_key, None)
                self._PROFILE_CACHE[cache_key] = [
                    dict(row) for row in enriched
                ]
        else:
            enriched = [dict(row) for row in cached]

        result: list[dict[str, Any]] = []
        turn_pass = 0
        wwsf_pass = 0
        missing_turn = 0
        missing_wwsf = 0
        for merged in enriched:
            if turn_size_frequency_target is not None:
                frequency = merged.get("turn_cbet_ip_size_25_40")
                if frequency is None:
                    missing_turn += 1
                    continue
                if abs(
                    float(frequency) - float(turn_size_frequency_target)
                ) > max(0.0, float(turn_size_frequency_tolerance)):
                    continue
            turn_pass += 1
            if wwsf_target is not None:
                wwsf = merged.get("wwsf")
                if wwsf is None:
                    missing_wwsf += 1
                    continue
                if abs(
                    float(wwsf) - float(wwsf_target)
                ) > max(0.0, float(wwsf_tolerance)):
                    continue
            wwsf_pass += 1
            result.append(dict(merged))
        self.last_filter_diagnostics = {
            "basic_candidates": len(enriched),
            "turn_pass": turn_pass,
            "wwsf_pass": wwsf_pass,
            "result_count": len(result),
            "missing_turn": missing_turn,
            "missing_wwsf": missing_wwsf,
        }
        return result[:max(1, int(limit))]

    def _database_version(self) -> tuple[int, int]:
        try:
            stat = Path(self.database_path).stat()
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return 0, 0

    def compare(
        self,
        reference_name: str,
        site: str = "",
        stakes: str = "",
        minimum_hands: int = 750,
        minimum_vpip: float = 30.0,
        minimum_pfr: float = 20.0,
        large_open_threshold: float = 3.4,
        turn_size_frequency_target: float | None = None,
        turn_size_frequency_tolerance: float = 2.0,
        wwsf_target: float | None = None,
        wwsf_tolerance: float = 2.0,
        use_aliases: bool = True,
        limit: int = 250,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        entities = self.get_entities(
            site=site,
            stakes=stakes,
            minimum_hands=minimum_hands,
            minimum_vpip=minimum_vpip,
            minimum_pfr=minimum_pfr,
            large_open_threshold=large_open_threshold,
            turn_size_frequency_target=turn_size_frequency_target,
            turn_size_frequency_tolerance=turn_size_frequency_tolerance,
            wwsf_target=wwsf_target,
            wwsf_tolerance=wwsf_tolerance,
            use_aliases=use_aliases,
            limit=5000,
        )

        reference = next(
            (
                row
                for row in entities
                if row["player_name"] == reference_name
            ),
            None,
        )

        if reference is None:
            raise ValueError(
                "Referans oyuncu veya alias bulunamadı."
            )

        reference_vector = self._feature_vector(reference)

        results: list[dict[str, Any]] = []

        for entity in entities:
            if entity["player_name"] == reference_name:
                continue

            vector = self._feature_vector(entity)
            similarity = self._cosine_similarity(
                reference_vector,
                vector,
            )

            distance = self._normalized_distance(
                reference_vector,
                vector,
            )

            confidence = self._confidence(
                reference,
                entity,
            )

            results.append(
                {
                    "player_name": entity["player_name"],
                    "hands": entity["hands"],
                    "merged_nicks": entity.get(
                        "merged_nicks",
                        1,
                    ),
                    "similarity": similarity * 100.0,
                    "distance": distance,
                    "confidence": confidence,
                    "vpip": entity["vpip"],
                    "pfr": entity["pfr"],
                    "three_bet": entity["three_bet"],
                    "fold_to_3bet": entity.get("fold_to_3bet"),
                    "fold_to_3bet_opp": int(entity.get("fold_to_3bet_opp") or 0),
                    "flop_cbet": entity["flop_cbet"],
                    "turn_barrel": entity["turn_barrel"],
                    "river_barrel": entity["river_barrel"],
                    "ep_open_gt_34": entity.get("ep_open_gt_34"),
                    "ep_open_gt_34_opp": int(entity.get("ep_open_gt_34_opp") or 0),
                    "mp_open_gt_34": entity.get("mp_open_gt_34"),
                    "mp_open_gt_34_opp": int(entity.get("mp_open_gt_34_opp") or 0),
                    "co_open_gt_34": entity.get("co_open_gt_34"),
                    "co_open_gt_34_opp": int(entity.get("co_open_gt_34_opp") or 0),
                    "btn_open_gt_34": entity.get("btn_open_gt_34"),
                    "btn_open_gt_34_opp": int(entity.get("btn_open_gt_34_opp") or 0),
                    "sb_open_gt_34": entity.get("sb_open_gt_34"),
                    "sb_open_gt_34_opp": int(entity.get("sb_open_gt_34_opp") or 0),
                    "turn_cbet_ip_size_25_40": entity.get(
                        "turn_cbet_ip_size_25_40"
                    ),
                    "turn_cbet_ip_size_25_40_sample": int(
                        entity.get("turn_cbet_ip_size_25_40_sample") or 0
                    ),
                    "wwsf": entity.get("wwsf"),
                    "wwsf_opp": int(entity.get("wwsf_opp") or 0),
                }
            )

        results.sort(
            key=lambda row: (
                row["similarity"],
                row["hands"],
            ),
            reverse=True,
        )

        return reference, results[:limit]

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path, read_only=True)

    @staticmethod
    def _pct(made: float, opportunity: float) -> float | None:
        if opportunity <= 0:
            return None
        return 100.0 * float(made) / float(opportunity)

    def _alias_map(self) -> dict[str, str]:
        with self._connect() as con:
            exists = bool(con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema='main' AND table_name='player_aliases'
                """
            ).fetchone()[0])
            if not exists:
                return {}
            rows = con.execute(
                """
                SELECT LOWER(TRIM(player_name)), MIN(alias_name)
                FROM player_aliases
                WHERE player_name IS NOT NULL AND alias_name IS NOT NULL
                GROUP BY LOWER(TRIM(player_name))
                """
            ).fetchall()
        return {str(player): str(alias) for player, alias in rows}

    def _merge_alias_profiles(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        aliases = self._alias_map()
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            player_name = str(row.get("player_name") or "")
            profile_name = aliases.get(player_name.strip().lower(), player_name)
            group = groups.setdefault(profile_name, {
                "player_name": profile_name,
                "hands": 0,
                "merged_nicks": 0,
                "vpip_sum": 0.0,
                "pfr_sum": 0.0,
                "three_bet_sum": 0.0,
                "flop_cbet_made": 0,
                "flop_cbet_opp": 0,
                "turn_barrel_made": 0,
                "turn_barrel_opp": 0,
                "river_barrel_made": 0,
                "river_barrel_opp": 0,
            })
            hands = int(row.get("hands") or 0)
            group["hands"] += hands
            group["merged_nicks"] += 1
            group["vpip_sum"] += float(row.get("vpip") or 0.0) * hands
            group["pfr_sum"] += float(row.get("pfr") or 0.0) * hands
            group["three_bet_sum"] += float(row.get("three_bet") or 0.0) * hands
            for key in ("flop_cbet", "turn_barrel", "river_barrel"):
                group[f"{key}_made"] += int(row.get(f"{key}_made") or 0)
                group[f"{key}_opp"] += int(row.get(f"{key}_opp") or 0)

        output: list[dict[str, Any]] = []
        for group in groups.values():
            hands = int(group["hands"])
            item = {
                "player_name": group["player_name"],
                "hands": hands,
                "merged_nicks": int(group["merged_nicks"]),
                "vpip": float(group["vpip_sum"]) / hands if hands else 0.0,
                "pfr": float(group["pfr_sum"]) / hands if hands else 0.0,
                "three_bet": float(group["three_bet_sum"]) / hands if hands else 0.0,
            }
            for key in ("flop_cbet", "turn_barrel", "river_barrel"):
                made = int(group[f"{key}_made"])
                opp = int(group[f"{key}_opp"])
                item[key] = self._pct(made, opp)
                item[f"{key}_made"] = made
                item[f"{key}_opp"] = opp
            output.append(item)
        return output

    def _extra_profiles(
        self,
        site: str,
        stakes: str,
        use_aliases: bool,
        large_open_threshold: float,
        profile_names: list[str],
    ) -> list[dict[str, Any]]:
        if not profile_names:
            return []
        aliases = self._alias_map() if use_aliases else {}
        alias_join = ""
        profile_expr = "hp.player_name"
        if aliases:
            alias_join = """
                LEFT JOIN (
                    SELECT LOWER(TRIM(player_name)) AS player_key,
                           MIN(alias_name) AS alias_name
                    FROM player_aliases
                    GROUP BY LOWER(TRIM(player_name))
                ) pa
                  ON pa.player_key = LOWER(TRIM(hp.player_name))
            """
            profile_expr = "COALESCE(pa.alias_name, hp.player_name)"

        clauses: list[str] = []
        params: list[Any] = []
        if site:
            clauses.append("h.site = ?")
            params.append(site)
        if stakes:
            clauses.append("h.stakes = ?")
            params.append(stakes)
        placeholders = ", ".join("?" for _ in profile_names)
        clauses.append(f"{profile_expr} IN ({placeholders})")
        params.extend(profile_names)
        params.extend([float(large_open_threshold)] * 5)
        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""

        query = f"""
            WITH participants AS (
                SELECT DISTINCT
                    hp.hand_id,
                    hp.player_name,
                    {profile_expr} AS profile_name,
                    UPPER(TRIM(COALESCE(hp.position, ''))) AS position,
                    h.flop,
                    h.turn
                FROM hand_players hp
                JOIN hands h ON h.hand_id = hp.hand_id
                {alias_join}
                {where_sql}
            ),
            preflop_raises AS (
                SELECT
                    a.hand_id,
                    a.player_name,
                    a.sequence_no,
                    a.amount,
                    a.to_amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id ORDER BY a.sequence_no
                    ) AS raise_no,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.hand_id ORDER BY a.sequence_no DESC
                    ) AS reverse_raise_no
                FROM actions a
                JOIN (SELECT DISTINCT hand_id FROM participants) sh
                  ON sh.hand_id = a.hand_id
                WHERE UPPER(TRIM(a.street)) = 'PREFLOP'
                  AND UPPER(TRIM(a.action)) = 'RAISE'
            ),
            big_blinds AS (
                SELECT
                    a.hand_id,
                    MAX(COALESCE(a.amount, a.to_amount)) AS big_blind
                FROM actions a
                JOIN (SELECT DISTINCT hand_id FROM participants) sh
                  ON sh.hand_id = a.hand_id
                WHERE UPPER(TRIM(a.street)) = 'PREFLOP'
                  AND UPPER(TRIM(a.action)) = 'POST_BB'
                GROUP BY a.hand_id
            ),
            opens AS (
                SELECT
                    r.hand_id,
                    r.player_name AS opener,
                    r.sequence_no AS open_seq,
                    p.profile_name,
                    p.position,
                    COALESCE(r.to_amount, r.amount)
                        / NULLIF(bb.big_blind, 0) AS size_bb
                FROM preflop_raises r
                JOIN participants p
                  ON p.hand_id = r.hand_id
                 AND LOWER(TRIM(p.player_name)) = LOWER(TRIM(r.player_name))
                LEFT JOIN big_blinds bb ON bb.hand_id = r.hand_id
                WHERE r.raise_no = 1
            ),
            three_bet_flags AS (
                SELECT
                    o.profile_name,
                    1 AS fold_to_3bet_opp,
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM actions response
                        WHERE response.hand_id = o.hand_id
                          AND LOWER(TRIM(response.player_name)) =
                              LOWER(TRIM(o.opener))
                          AND UPPER(TRIM(response.street)) = 'PREFLOP'
                          AND UPPER(TRIM(response.action)) = 'FOLD'
                          AND response.sequence_no > r2.sequence_no
                    ) THEN 1 ELSE 0 END AS fold_to_3bet_made
                FROM opens o
                JOIN preflop_raises r2
                  ON r2.hand_id = o.hand_id
                 AND r2.raise_no = 2
            ),
            fold_to_3bet_stats AS (
                SELECT
                    profile_name,
                    SUM(fold_to_3bet_made) AS fold_to_3bet_made,
                    SUM(fold_to_3bet_opp) AS fold_to_3bet_opp
                FROM three_bet_flags
                GROUP BY profile_name
            ),
            open_stats AS (
                SELECT
                    profile_name,
                    SUM(CASE WHEN position IN ('UTG', 'UTG+1', 'EP')
                                  AND size_bb IS NOT NULL THEN 1 ELSE 0 END) AS ep_opp,
                    SUM(CASE WHEN position IN ('UTG', 'UTG+1', 'EP')
                                  AND size_bb > ? THEN 1 ELSE 0 END) AS ep_made,
                    SUM(CASE WHEN position IN ('HJ', 'MP')
                                  AND size_bb IS NOT NULL THEN 1 ELSE 0 END) AS mp_opp,
                    SUM(CASE WHEN position IN ('HJ', 'MP')
                                  AND size_bb > ? THEN 1 ELSE 0 END) AS mp_made,
                    SUM(CASE WHEN position = 'CO'
                                  AND size_bb IS NOT NULL THEN 1 ELSE 0 END) AS co_opp,
                    SUM(CASE WHEN position = 'CO'
                                  AND size_bb > ? THEN 1 ELSE 0 END) AS co_made,
                    SUM(CASE WHEN position = 'BTN'
                                  AND size_bb IS NOT NULL THEN 1 ELSE 0 END) AS btn_opp,
                    SUM(CASE WHEN position = 'BTN'
                                  AND size_bb > ? THEN 1 ELSE 0 END) AS btn_made,
                    SUM(CASE WHEN position = 'SB'
                                  AND size_bb IS NOT NULL THEN 1 ELSE 0 END) AS sb_opp,
                    SUM(CASE WHEN position = 'SB'
                                  AND size_bb > ? THEN 1 ELSE 0 END) AS sb_made
                FROM opens
                GROUP BY profile_name
            ),
            last_preflop_raiser AS (
                SELECT hand_id, player_name
                FROM preflop_raises
                WHERE reverse_raise_no = 1
            ),
            street_player AS (
                SELECT
                    a.hand_id,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    MIN(a.sequence_no) AS first_seq
                FROM actions a
                JOIN (SELECT DISTINCT hand_id FROM participants) sh
                  ON sh.hand_id = a.hand_id
                WHERE UPPER(TRIM(a.street)) IN ('FLOP', 'TURN')
                GROUP BY a.hand_id, UPPER(TRIM(a.street)), a.player_name
            ),
            street_meta AS (
                SELECT hand_id, street,
                       COUNT(DISTINCT player_name) AS player_count,
                       MAX(first_seq) AS last_first_seq
                FROM street_player
                GROUP BY hand_id, street
            ),
            action_flow AS (
                SELECT
                    a.hand_id,
                    a.sequence_no,
                    UPPER(TRIM(a.street)) AS street,
                    a.player_name,
                    UPPER(TRIM(a.action)) AS action,
                    a.amount,
                    COALESCE(
                        SUM(
                            CASE
                                WHEN UPPER(TRIM(a.action)) IN (
                                    'POST_ANTE', 'POST_SB', 'POST_BB',
                                    'CALL', 'BET', 'RAISE'
                                ) THEN COALESCE(a.amount, 0)
                                WHEN UPPER(TRIM(a.action)) = 'RETURN'
                                THEN -COALESCE(a.amount, 0)
                                ELSE 0
                            END
                        ) OVER (
                            PARTITION BY a.hand_id
                            ORDER BY a.sequence_no
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                        ),
                        0
                    ) AS pot_before
                FROM actions a
                JOIN (SELECT DISTINCT hand_id FROM participants) sh
                  ON sh.hand_id = a.hand_id
            ),
            postflop_flags AS (
                SELECT
                    p.profile_name,
                    CASE WHEN p.flop IS NOT NULL AND TRIM(p.flop) <> ''
                              AND EXISTS (
                                  SELECT 1 FROM actions fs
                                  WHERE fs.hand_id = p.hand_id
                                    AND LOWER(TRIM(fs.player_name)) =
                                        LOWER(TRIM(p.player_name))
                                    AND UPPER(TRIM(fs.street)) = 'FLOP'
                              )
                         THEN 1 ELSE 0 END AS wwsf_opp,
                    CASE WHEN p.flop IS NOT NULL AND TRIM(p.flop) <> ''
                              AND EXISTS (
                                  SELECT 1 FROM actions fs
                                  WHERE fs.hand_id = p.hand_id
                                    AND LOWER(TRIM(fs.player_name)) =
                                        LOWER(TRIM(p.player_name))
                                    AND UPPER(TRIM(fs.street)) = 'FLOP'
                              )
                              AND EXISTS (
                                  SELECT 1 FROM actions c
                                  WHERE c.hand_id = p.hand_id
                                    AND LOWER(TRIM(c.player_name)) =
                                        LOWER(TRIM(p.player_name))
                                    AND UPPER(TRIM(c.action)) = 'COLLECT'
                              )
                         THEN 1 ELSE 0 END AS wwsf_made,
                    CASE WHEN lpr.player_name = p.player_name
                              AND p.turn IS NOT NULL AND TRIM(p.turn) <> ''
                              AND COALESCE(tm.player_count, 0) = 2
                              AND tsp.first_seq = tm.last_first_seq
                              AND EXISTS (
                                  SELECT 1 FROM actions fa
                                  WHERE fa.hand_id = p.hand_id
                                    AND fa.player_name = p.player_name
                                    AND UPPER(TRIM(fa.street)) = 'FLOP'
                                    AND UPPER(TRIM(fa.action)) = 'BET'
                              )
                              AND EXISTS (
                                  SELECT 1 FROM action_flow taf
                                  WHERE taf.hand_id = p.hand_id
                                    AND taf.player_name = p.player_name
                                    AND taf.street = 'TURN'
                                    AND taf.action = 'BET'
                                    AND COALESCE(taf.amount, 0) > 0
                                    AND taf.pot_before > 0
                              )
                         THEN 1 ELSE 0 END AS turn_cbet_ip_size_opp,
                    CASE WHEN lpr.player_name = p.player_name
                              AND p.turn IS NOT NULL AND TRIM(p.turn) <> ''
                              AND COALESCE(tm.player_count, 0) = 2
                              AND tsp.first_seq = tm.last_first_seq
                              AND EXISTS (
                                  SELECT 1 FROM actions fa
                                  WHERE fa.hand_id = p.hand_id
                                    AND fa.player_name = p.player_name
                                    AND UPPER(TRIM(fa.street)) = 'FLOP'
                                    AND UPPER(TRIM(fa.action)) = 'BET'
                              )
                              AND EXISTS (
                                  SELECT 1 FROM action_flow taf
                                  WHERE taf.hand_id = p.hand_id
                                    AND taf.player_name = p.player_name
                                    AND taf.street = 'TURN'
                                    AND taf.action = 'BET'
                                    AND COALESCE(taf.amount, 0) > 0
                                    AND taf.pot_before > 0
                                    AND 100.0 * taf.amount / taf.pot_before > 25.0
                                    AND 100.0 * taf.amount / taf.pot_before <= 40.0
                              )
                         THEN 1 ELSE 0 END AS turn_cbet_ip_size_25_40_made
                FROM participants p
                LEFT JOIN last_preflop_raiser lpr ON lpr.hand_id = p.hand_id
                LEFT JOIN street_player tsp
                  ON tsp.hand_id = p.hand_id
                 AND tsp.street = 'TURN'
                 AND LOWER(TRIM(tsp.player_name)) = LOWER(TRIM(p.player_name))
                LEFT JOIN street_meta tm
                  ON tm.hand_id = p.hand_id AND tm.street = 'TURN'
            ),
            postflop_stats AS (
                SELECT
                    profile_name,
                    SUM(wwsf_opp) AS wwsf_opp,
                    SUM(wwsf_made) AS wwsf_made,
                    SUM(turn_cbet_ip_size_opp) AS turn_cbet_ip_size_opp,
                    SUM(turn_cbet_ip_size_25_40_made)
                        AS turn_cbet_ip_size_25_40_made
                FROM postflop_flags
                GROUP BY profile_name
            ),
            profile_names AS (
                SELECT DISTINCT profile_name FROM participants
            )
            SELECT
                n.profile_name,
                COALESCE(os.ep_made, 0), COALESCE(os.ep_opp, 0),
                COALESCE(os.mp_made, 0), COALESCE(os.mp_opp, 0),
                COALESCE(os.co_made, 0), COALESCE(os.co_opp, 0),
                COALESCE(os.btn_made, 0), COALESCE(os.btn_opp, 0),
                COALESCE(os.sb_made, 0), COALESCE(os.sb_opp, 0),
                COALESCE(ps.turn_cbet_ip_size_25_40_made, 0),
                COALESCE(ps.turn_cbet_ip_size_opp, 0),
                COALESCE(ps.wwsf_made, 0), COALESCE(ps.wwsf_opp, 0),
                COALESCE(fs.fold_to_3bet_made, 0),
                COALESCE(fs.fold_to_3bet_opp, 0)
            FROM profile_names n
            LEFT JOIN open_stats os ON os.profile_name = n.profile_name
            LEFT JOIN postflop_stats ps ON ps.profile_name = n.profile_name
            LEFT JOIN fold_to_3bet_stats fs ON fs.profile_name = n.profile_name
        """
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()

        output: list[dict[str, Any]] = []
        for row in rows:
            output.append({
                "player_name": str(row[0]),
                "ep_open_gt_34": self._pct(row[1], row[2]),
                "ep_open_gt_34_opp": int(row[2] or 0),
                "mp_open_gt_34": self._pct(row[3], row[4]),
                "mp_open_gt_34_opp": int(row[4] or 0),
                "co_open_gt_34": self._pct(row[5], row[6]),
                "co_open_gt_34_opp": int(row[6] or 0),
                "btn_open_gt_34": self._pct(row[7], row[8]),
                "btn_open_gt_34_opp": int(row[8] or 0),
                "sb_open_gt_34": self._pct(row[9], row[10]),
                "sb_open_gt_34_opp": int(row[10] or 0),
                "turn_cbet_ip_size_25_40": self._pct(row[11], row[12]),
                "turn_cbet_ip_size_25_40_sample": int(row[12] or 0),
                "wwsf": self._pct(row[13], row[14]),
                "wwsf_opp": int(row[14] or 0),
                "fold_to_3bet": self._pct(row[15], row[16]),
                "fold_to_3bet_opp": int(row[16] or 0),
            })
        return output

    def _feature_vector(
        self,
        row: dict[str, Any],
    ) -> list[float]:
        vector: list[float] = []

        for key in self.FEATURE_KEYS:
            value = row.get(key)

            if value is None:
                value = 0.0

            vector.append(float(value) / 100.0)

        return vector

    def _cosine_similarity(
        self,
        left: list[float],
        right: list[float],
    ) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))

        if left_norm == 0 or right_norm == 0:
            return 0.0

        return max(
            0.0,
            min(1.0, dot / (left_norm * right_norm)),
        )

    def _normalized_distance(
        self,
        left: list[float],
        right: list[float],
    ) -> float:
        if not left:
            return 0.0

        squared = sum(
            (a - b) ** 2
            for a, b in zip(left, right)
        )

        return math.sqrt(squared / len(left)) * 100.0

    def _confidence(
        self,
        reference: dict[str, Any],
        entity: dict[str, Any],
    ) -> str:
        sample = min(
            int(reference.get("hands", 0)),
            int(entity.get("hands", 0)),
        )

        postflop_samples = [
            int(reference.get("flop_cbet_opp", 0)),
            int(reference.get("turn_barrel_opp", 0)),
            int(reference.get("river_barrel_opp", 0)),
            int(entity.get("flop_cbet_opp", 0)),
            int(entity.get("turn_barrel_opp", 0)),
            int(entity.get("river_barrel_opp", 0)),
        ]

        postflop_floor = min(postflop_samples)

        if sample >= 10000 and postflop_floor >= 500:
            return "Yüksek"

        if sample >= 2500 and postflop_floor >= 100:
            return "Orta"

        if sample >= 500:
            return "Düşük"

        return "Çok düşük"
