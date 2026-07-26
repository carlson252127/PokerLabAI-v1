from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Iterable, Iterator

import duckdb

from models.open_size_rng_models import OpenSizeRngReport


SIZE_TARGETS = (2.0, 2.25, 2.5, 3.0, 3.5, 4.0)
CONDITIONS = (
    "position", "stack_bucket", "stake", "ante", "sb_profile",
    "bb_profile", "blind_fish_count", "session_id", "table_id",
    "hour_bucket",
)


class OpenSizeRngAnalysisService:
    """Read-only conditional/serial analysis of unopened first-in opens."""

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        self.database_path = str(Path(database_path))

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.database_path, read_only=True)

    def analyze(
        self,
        bot_group: str,
        site: str | None = None,
        stake: str | None = None,
        min_sample: int = 750,
        exclude_players: Iterable[str] | None = None,
        output_dir: str | Path = "analysis_reports",
    ) -> OpenSizeRngReport:
        report = self.analyze_records(
            self._iter_records(bot_group, site, stake),
            min_sample=min_sample,
            exclude_players=exclude_players,
        )
        self.export_report(report, output_dir)
        return report

    @classmethod
    def analyze_records(
        cls,
        records: Iterable[dict[str, Any]],
        min_sample: int = 750,
        exclude_players: Iterable[str] | None = None,
    ) -> OpenSizeRngReport:
        excluded_names = {
            str(value).strip().lower() for value in (exclude_players or ())
        }
        unique: dict[str, dict[str, Any]] = {}
        duplicates = 0
        excluded = 0
        diagnostics: list[str] = []
        for raw in records:
            row = cls._normalize(raw)
            if not row["hand_id"]:
                excluded += 1
                diagnostics.append("hand_id eksik kayıt dışlandı")
                continue
            if row["player"].lower() in excluded_names:
                excluded += 1
                continue
            if row["size_bb"] is None or not row["player"]:
                excluded += 1
                continue
            if row["hand_id"] in unique:
                duplicates += 1
                continue
            unique[row["hand_id"]] = row
        rows = list(unique.values())

        shares = cls._player_shares(rows)
        natural = cls._mean([float(r["high_size"]) for r in rows])
        per_player = defaultdict(list)
        for row in rows:
            per_player[row["player"]].append(float(row["high_size"]))
        equal_player = cls._mean([
            cls._mean(values) or 0.0 for values in per_player.values()
        ])
        low, high = cls._wilson(
            sum(int(r["high_size"]) for r in rows), len(rows)
        )
        distribution = cls._distribution(rows)
        effects = cls._condition_effects(rows)
        serial, transitions = cls._serial(rows)
        stability = cls._session_stability(rows)
        model_metrics, auc, hybrid_gain, within_entropy = cls._models(rows)

        dominant = bool(shares and shares[0]["share"] > 0.25)
        missing_profiles = sum(
            r["sb_profile"] == "unknown" or r["bb_profile"] == "unknown"
            for r in rows
        )
        if dominant:
            diagnostics.append("Bir oyuncu toplam openların %25'inden fazlasını oluşturuyor")
        if rows and missing_profiles / len(rows) > 0.4:
            diagnostics.append("Blind profile kapsamı düşük")

        strongest_v = max(
            (
                float(item["cramers_v"])
                for item in effects
                if float(item["q_value"]) <= 0.05
            ),
            default=0.0,
        )
        serial_dependence = bool(serial.get("serial_dependence"))
        stable = float(stability.get("mean_js_divergence") or 0.0) < 0.08
        if len(rows) < max(1, int(min_sample)):
            classification = "INCONCLUSIVE"
        elif (
            auc is not None
            and auc >= 0.60
            and hybrid_gain > 0.02
            and within_entropy >= 0.45
        ):
            classification = "HYBRID_LEANING"
        elif auc is not None and auc >= 0.65 and strongest_v >= 0.10:
            classification = "STRATEGY_LEANING"
        elif (
            auc is not None
            and auc <= 0.55
            and strongest_v < 0.10
            and not serial_dependence
            and stable
        ):
            classification = "RNG_LEANING"
        else:
            classification = "INCONCLUSIVE"

        limitations = [
            "Sonuçlar fiziksel RNG kullanımını kanıtlamaz.",
            "Gözlenmeyen hole-card, yazılım sürümü ve oyuncu profili etkileri ayrıştırılamaz.",
        ]
        return OpenSizeRngReport(
            classification=classification,
            used_records=len(rows),
            duplicate_records=duplicates,
            excluded_records=excluded,
            player_shares=shares,
            position_distribution=distribution,
            condition_effects=effects,
            transitions=transitions,
            model_metrics=model_metrics,
            serial_metrics=serial,
            session_stability=stability,
            diagnostics=list(dict.fromkeys(diagnostics)),
            limitations=limitations,
            natural_high_size_rate=natural,
            equal_player_high_size_rate=equal_player,
            high_size_ci_low=low,
            high_size_ci_high=high,
        )

    def _iter_records(
        self,
        bot_group: str,
        site: str | None,
        stake: str | None,
        batch_size: int = 20_000,
    ) -> Iterator[dict[str, Any]]:
        filters = ["bg.name = ?"]
        params: list[Any] = [bot_group]
        if site:
            filters.append("h.site = ?")
            params.append(site)
        if stake:
            filters.append("h.stakes = ?")
            params.append(stake)
        where = " AND ".join(filters)
        # A first raise is an open only when no earlier voluntary CALL/RAISE
        # exists. Blind/ante posts are deliberately ignored.
        query = f"""
            WITH candidates AS (
                SELECT a.hand_id, a.player_name, a.sequence_no, a.to_amount,
                       ROW_NUMBER() OVER (
                           PARTITION BY a.hand_id ORDER BY a.sequence_no
                       ) AS raise_no
                FROM actions a
                WHERE UPPER(TRIM(a.street)) = 'PREFLOP'
                  AND UPPER(TRIM(a.action)) = 'RAISE'
            )
            SELECT h.hand_id, h.played_at, h.table_name, h.site, h.stakes,
                   c.player_name, hp.position, hp.starting_stack, c.to_amount,
                   (
                       SELECT COUNT(*)
                       FROM hand_players dealt
                       WHERE dealt.hand_id = h.hand_id
                   ) AS players_dealt
            FROM candidates c
            JOIN hands h USING (hand_id)
            JOIN hand_players hp
              ON hp.hand_id=c.hand_id
             AND LOWER(TRIM(hp.player_name))=LOWER(TRIM(c.player_name))
            JOIN bot_group_members bgm
              ON LOWER(TRIM(bgm.player_name))=LOWER(TRIM(c.player_name))
            JOIN bot_groups bg USING (group_id)
            WHERE {where}
              AND c.raise_no=1
              AND NOT EXISTS (
                  SELECT 1 FROM actions prior
                  WHERE prior.hand_id=c.hand_id
                    AND prior.sequence_no<c.sequence_no
                    AND UPPER(TRIM(prior.street))='PREFLOP'
                    AND UPPER(TRIM(prior.action)) IN ('CALL','RAISE')
              )
            ORDER BY c.player_name, h.played_at, h.hand_id
        """
        with self.connect() as con:
            cursor = con.execute(query, params)
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    break
                for row in batch:
                    bb = self._big_blind(row[4])
                    size = float(row[8]) / bb if bb and row[8] is not None else None
                    stack = float(row[7]) / bb if bb and row[7] is not None else None
                    timestamp = str(row[1] or "")
                    yield {
                        "hand_id": row[0], "timestamp": timestamp,
                        "session_id": f"{row[5]}:{timestamp[:10]}",
                        "table_id": row[2], "site": row[3], "stake": row[4],
                        "player": row[5], "position": row[6],
                        "effective_stack_bb": stack, "open_size_bb": size,
                        "players_dealt": row[9],
                    }

    @classmethod
    def export_report(
        cls, report: OpenSizeRngReport, output_dir: str | Path
    ) -> None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        cls._write_csv(output / "open_size_rng_by_position.csv", report.position_distribution)
        cls._write_csv(output / "open_size_rng_condition_effects.csv", report.condition_effects)
        cls._write_csv(output / "open_size_rng_transitions.csv", report.transitions)
        cls._write_csv(output / "open_size_rng_model_metrics.csv", report.model_metrics)
        strongest = report.condition_effects[:5]
        lines = [
            "# Bot Open Size RNG / Strateji Analizi", "",
            f"- Sınıflandırma: **{report.classification}**",
            f"- Kullanılan kayıt: {report.used_records:,}",
            f"- Duplicate: {report.duplicate_records:,}",
            f"- High-size oranı: {cls._pct(report.natural_high_size_rate)}",
            f"- Wilson %95 CI: {cls._pct(report.high_size_ci_low)} – {cls._pct(report.high_size_ci_high)}",
            f"- Equal-player high-size: {cls._pct(report.equal_player_high_size_rate)}",
            "", "## En güçlü koşul etkileri", "",
        ]
        lines.extend(
            f"- {x['condition']}: Cramér's V={x['cramers_v']:.3f}, q={x['q_value']:.4g}"
            for x in strongest
        )
        lines += ["", "## Limitasyonlar", ""]
        lines.extend(f"- {item}" for item in report.limitations + report.diagnostics)
        (output / "open_size_rng_summary.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        fields = sorted({key for row in rows for key in row})
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def _normalize(cls, raw: dict[str, Any]) -> dict[str, Any]:
        size = cls._number(raw.get("open_size_bb", raw.get("size_bb")))
        stack = cls._number(raw.get("effective_stack_bb", raw.get("stack_bb")))
        timestamp = str(raw.get("timestamp") or raw.get("played_at") or "")
        sb = str(raw.get("sb_profile") or "unknown").lower()
        bb = str(raw.get("bb_profile") or "unknown").lower()
        return {
            "hand_id": str(raw.get("hand_id") or "").strip(),
            "player": str(raw.get("player") or raw.get("player_name") or "").strip(),
            "position": str(raw.get("position") or "unknown").upper(),
            "stake": str(raw.get("stake") or raw.get("stakes") or "unknown"),
            "ante": str(raw.get("ante") if raw.get("ante") is not None else "unknown"),
            "session_id": str(raw.get("session_id") or raw.get("table_id") or timestamp[:10] or "unknown"),
            "table_id": str(raw.get("table_id") or raw.get("table_name") or "unknown"),
            "hour_bucket": str(raw.get("hour_bucket") or (timestamp[11:13] if len(timestamp) >= 13 else "unknown")),
            "sb_profile": sb, "bb_profile": bb,
            "blind_fish_count": int("fish" in sb) + int("fish" in bb),
            "players_dealt": cls._number(raw.get("players_dealt")),
            "stack": stack, "stack_bucket": cls._stack_bucket(stack),
            "size_bb": size, "size_bucket": cls._size_bucket(size),
            "high_size": bool(size is not None and size >= 3.5 - 1e-6),
            "timestamp": timestamp,
        }

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _size_bucket(value: float | None) -> str:
        if value is None:
            return "unknown"
        closest = min(SIZE_TARGETS, key=lambda target: abs(value - target))
        return f"{closest:.2f}" if abs(value - closest) <= 0.06 else "other"

    @staticmethod
    def _stack_bucket(value: float | None) -> str:
        if value is None:
            return "unknown"
        if value < 60: return "<60"
        if value < 90: return "60-89"
        if value <= 110: return "90-110"
        if value <= 150: return "111-150"
        return "150+"

    @classmethod
    def _distribution(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = Counter((r["position"], r["size_bucket"]) for r in rows)
        totals = Counter(r["position"] for r in rows)
        result = []
        for (position, size), count in sorted(counts.items()):
            high_n = sum(
                int(r["high_size"]) for r in rows if r["position"] == position
            )
            low, high = cls._wilson(high_n, totals[position])
            result.append({
                "position": position, "size_bucket": size, "count": count,
                "frequency": count / totals[position],
                "high_size_rate": high_n / totals[position],
                "ci_low": low, "ci_high": high,
            })
        return result

    @classmethod
    def _condition_effects(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raw = []
        for condition in CONDITIONS:
            table: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for row in rows:
                category = str(row.get(condition, "unknown"))
                table[category][int(row["high_size"])] += 1
            table = {k: v for k, v in table.items() if sum(v) >= 2}
            if len(table) < 2:
                continue
            total = sum(sum(v) for v in table.values())
            columns = [sum(v[i] for v in table.values()) for i in (0, 1)]
            chi = 0.0
            for values in table.values():
                row_total = sum(values)
                for i, observed in enumerate(values):
                    expected = row_total * columns[i] / total
                    if expected:
                        chi += (observed - expected) ** 2 / expected
            df = max(1, len(table) - 1)
            v = math.sqrt(chi / max(1, total))
            raw.append({
                "condition": condition, "chi_square": chi, "df": df,
                "p_value": cls._chi_square_sf(chi, df), "cramers_v": v,
                "categories": len(table),
            })
        cls._bh(raw)
        return sorted(raw, key=lambda x: (-x["cramers_v"], x["q_value"]))

    @staticmethod
    def _chi_square_sf(value: float, df: int) -> float:
        if value <= 0:
            return 1.0
        z = ((value / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
        return 0.5 * math.erfc(z / math.sqrt(2))

    @staticmethod
    def _bh(items: list[dict[str, Any]]) -> None:
        ordered = sorted(enumerate(items), key=lambda pair: pair[1]["p_value"])
        q = 1.0
        for rank_index in range(len(ordered) - 1, -1, -1):
            original, item = ordered[rank_index]
            rank = rank_index + 1
            q = min(q, item["p_value"] * len(items) / rank)
            items[original]["q_value"] = q

    @classmethod
    def _serial(cls, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        by_player = defaultdict(list)
        for row in rows:
            by_player[row["player"]].append(row)
        pairs = Counter()
        sequences: list[int] = []
        lag_pairs = {1: [], 2: []}
        streaks = Counter()
        for items in by_player.values():
            items.sort(key=lambda r: (r["timestamp"], r["hand_id"]))
            seq = [int(r["high_size"]) for r in items]
            sequences.extend(seq)
            for a, b in zip(seq, seq[1:]):
                pairs[(a, b)] += 1
            for lag in (1, 2):
                lag_pairs[lag].extend(zip(seq[:-lag], seq[lag:]))
            if seq:
                length = 1
                for a, b in zip(seq, seq[1:]):
                    if a == b: length += 1
                    else: streaks[length] += 1; length = 1
                streaks[length] += 1
        lag1 = cls._corr(lag_pairs[1])
        lag2 = cls._corr(lag_pairs[2])
        transitions = []
        for source in (0, 1):
            denominator = sum(pairs[(source, target)] for target in (0, 1))
            for target in (0, 1):
                transitions.append({
                    "from_high": source, "to_high": target,
                    "count": pairs[(source, target)],
                    "probability": pairs[(source, target)] / denominator if denominator else 0.0,
                })
        alternating = pairs[(0, 1)] + pairs[(1, 0)]
        total_pairs = sum(pairs.values())
        runs_z = cls._runs_z(sequences)
        dependence = (
            abs(lag1 or 0.0) >= 0.15 or abs(lag2 or 0.0) >= 0.15
            or abs(runs_z or 0.0) >= 2.58
        )
        return {
            "lag1_autocorrelation": lag1, "lag2_autocorrelation": lag2,
            "alternation_rate": alternating / total_pairs if total_pairs else None,
            "runs_z": runs_z, "serial_dependence": dependence,
            "streak_distribution": dict(sorted(streaks.items())),
        }, transitions

    @staticmethod
    def _corr(pairs: list[tuple[int, int]]) -> float | None:
        if len(pairs) < 3:
            return None
        xs, ys = zip(*pairs)
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denominator = math.sqrt(
            sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)
        )
        return sum((x - mx) * (y - my) for x, y in pairs) / denominator if denominator else 0.0

    @staticmethod
    def _runs_z(sequence: list[int]) -> float | None:
        n1, n0 = sum(sequence), len(sequence) - sum(sequence)
        if not n1 or not n0 or len(sequence) < 3:
            return None
        runs = 1 + sum(a != b for a, b in zip(sequence, sequence[1:]))
        mean = 1 + 2 * n1 * n0 / (n1 + n0)
        variance = (
            2 * n1 * n0 * (2 * n1 * n0 - n1 - n0)
            / ((n1 + n0) ** 2 * (n1 + n0 - 1))
        )
        return (runs - mean) / math.sqrt(variance) if variance > 0 else None

    @classmethod
    def _session_stability(cls, rows: list[dict[str, Any]]) -> dict[str, Any]:
        global_counts = Counter(r["size_bucket"] for r in rows)
        sessions = defaultdict(Counter)
        for row in rows:
            sessions[row["session_id"]][row["size_bucket"]] += 1
        divergences = [
            cls._js(counter, global_counts)
            for counter in sessions.values() if sum(counter.values()) >= 20
        ]
        return {
            "session_count": len(sessions),
            "comparable_sessions": len(divergences),
            "mean_js_divergence": cls._mean(divergences),
        }

    @staticmethod
    def _js(left: Counter, right: Counter) -> float:
        keys = set(left) | set(right)
        lt, rt = sum(left.values()), sum(right.values())
        if not lt or not rt: return 0.0
        p, q = ({k: left[k] / lt for k in keys}, {k: right[k] / rt for k in keys})
        m = {k: (p[k] + q[k]) / 2 for k in keys}
        kl = lambda a: sum(a[k] * math.log2(a[k] / m[k]) for k in keys if a[k])
        return (kl(p) + kl(q)) / 2

    @classmethod
    def _models(cls, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None, float, float]:
        if len(rows) < 20 or len({r["high_size"] for r in rows}) < 2:
            return [], None, 0.0, 0.0
        features = (
            "position", "stack_bucket", "stake", "ante", "sb_profile",
            "bb_profile", "blind_fish_count", "session_id", "hour_bucket",
            "player",
        )
        labels: list[int] = []
        predictions: list[float] = []
        baseline_predictions: list[float] = []
        position_losses: list[tuple[int, float]] = []
        hybrid_losses: list[tuple[int, float]] = []
        for fold in range(5):
            train = [
                row for row in rows
                if cls._group_fold(row) != fold
            ]
            test = [
                row for row in rows
                if cls._group_fold(row) == fold
            ]
            if not test or len({r["high_size"] for r in train}) < 2:
                continue
            global_p = (
                sum(r["high_size"] for r in train) + 1
            ) / (len(train) + 2)
            condition = defaultdict(lambda: [0, 0])
            for row in train:
                for feature in features:
                    condition[(feature, str(row[feature]))][
                        int(row["high_size"])
                    ] += 1
            for row in test:
                logit = math.log(global_p / (1 - global_p))
                used = 0
                for feature in features:
                    counts = condition[(feature, str(row[feature]))]
                    if sum(counts) >= 5:
                        p = (
                            counts[1] + 2 * global_p
                        ) / (sum(counts) + 2)
                        logit += 0.22 * math.log(p / (1 - p))
                        used += 1
                predictions.append(
                    1 / (
                        1 + math.exp(
                            -max(-20, min(20, logit / max(1, used * 0.22)))
                        )
                    )
                )
                labels.append(int(row["high_size"]))
                baseline_predictions.append(global_p)
            position_losses.append((
                len(test),
                cls._categorical_loss(train, test, ("position",)),
            ))
            hybrid_losses.append((
                len(test),
                cls._categorical_loss(
                    train,
                    test,
                    ("position", "sb_profile", "bb_profile", "stack_bucket"),
                ),
            ))
        if not labels:
            return [], None, 0.0, 0.0
        auc = cls._auc(labels, predictions)
        baseline_loss = cls._log_loss(labels, baseline_predictions)
        conditional_loss = cls._log_loss(labels, predictions)
        calibration = cls._calibration(labels, predictions)

        # Mode-conditional size entropy distinguishes deterministic strategic
        # sizing from a strategic small/large gate followed by mixed sizing.
        mode_sizes = defaultdict(Counter)
        for row in rows:
            mode_sizes[int(row["high_size"])][row["size_bucket"]] += 1
        entropies = []
        for counts in mode_sizes.values():
            total = sum(counts.values())
            if total:
                entropy = -sum((n / total) * math.log2(n / total) for n in counts.values() if n)
                maximum = math.log2(max(1, len(counts)))
                entropies.append(entropy / maximum if maximum else 0.0)
        within_entropy = cls._mean(entropies) or 0.0
        position_loss = sum(n * loss for n, loss in position_losses) / sum(
            n for n, _ in position_losses
        )
        hybrid_loss = sum(n * loss for n, loss in hybrid_losses) / sum(
            n for n, _ in hybrid_losses
        )
        hybrid_gain = max(0.0, position_loss - hybrid_loss)
        metrics = [
            {"model": "BASELINE", "auc": 0.5, "log_loss": baseline_loss, "calibration_error": cls._calibration(labels, baseline_predictions)},
            {"model": "B_CONDITIONAL_HIGH", "auc": auc, "log_loss": conditional_loss, "calibration_error": calibration},
            {"model": "A_POSITION_MIXTURE", "auc": None, "log_loss": position_loss, "calibration_error": None},
            {"model": "C_TWO_STAGE", "auc": auc, "log_loss": hybrid_loss, "calibration_error": calibration, "within_mode_entropy": within_entropy},
        ]
        return metrics, auc, hybrid_gain, within_entropy

    @staticmethod
    def _group_fold(row: dict[str, Any]) -> int:
        key = str(row["session_id"] or row["table_id"])
        return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 5

    @staticmethod
    def _categorical_loss(train: list[dict[str, Any]], test: list[dict[str, Any]], keys: tuple[str, ...]) -> float:
        sizes = [OpenSizeRngAnalysisService._size_bucket(x) for x in SIZE_TARGETS] + ["other"]
        tables = defaultdict(Counter)
        global_counts = Counter(r["size_bucket"] for r in train)
        for row in train:
            tables[tuple(str(row[k]) for k in keys)][row["size_bucket"]] += 1
        losses = []
        for row in test:
            counts = tables[tuple(str(row[k]) for k in keys)]
            total = sum(counts.values())
            probability = (counts[row["size_bucket"]] + global_counts[row["size_bucket"]] / max(1, len(train)) + 0.1) / (total + 0.1 * len(sizes) + 1)
            losses.append(-math.log(max(1e-12, probability)))
        return sum(losses) / len(losses) if losses else 0.0

    @staticmethod
    def _auc(labels: list[int], scores: list[float]) -> float | None:
        positives = sum(labels); negatives = len(labels) - positives
        if not positives or not negatives: return None
        ordered = sorted(zip(scores, labels))
        rank_sum = 0.0; index = 0
        while index < len(ordered):
            end = index + 1
            while end < len(ordered) and ordered[end][0] == ordered[index][0]: end += 1
            average_rank = (index + 1 + end) / 2
            rank_sum += average_rank * sum(label for _, label in ordered[index:end])
            index = end
        return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)

    @staticmethod
    def _log_loss(labels: list[int], predictions: list[float]) -> float:
        return sum(
            -(y * math.log(max(1e-12, p)) + (1-y) * math.log(max(1e-12, 1-p)))
            for y, p in zip(labels, predictions)
        ) / max(1, len(labels))

    @staticmethod
    def _calibration(labels: list[int], predictions: list[float]) -> float:
        bins = defaultdict(list)
        for y, p in zip(labels, predictions): bins[min(9, int(p * 10))].append((y, p))
        return sum(
            len(values) / len(labels) * abs(
                sum(y for y, _ in values) / len(values) -
                sum(p for _, p in values) / len(values)
            ) for values in bins.values()
        ) if labels else 0.0

    @staticmethod
    def _player_shares(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = Counter(r["player"] for r in rows)
        highs = Counter(r["player"] for r in rows if r["high_size"])
        return [
            {"player": player, "opens": count, "share": count / len(rows), "high_size_rate": highs[player] / count}
            for player, count in counts.most_common()
        ] if rows else []

    @staticmethod
    def _wilson(successes: int, total: int) -> tuple[float | None, float | None]:
        if not total: return None, None
        z = 1.959963984540054; p = successes / total
        denominator = 1 + z*z/total
        center = (p + z*z/(2*total)) / denominator
        margin = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
        return center-margin, center+margin

    @staticmethod
    def _mean(values: Iterable[float]) -> float | None:
        items = list(values)
        return sum(items) / len(items) if items else None

    @staticmethod
    def _big_blind(stakes: Any) -> float | None:
        values = re.findall(r"\d+(?:[.,]\d+)?", str(stakes or ""))
        if len(values) < 2: return None
        return float(values[-1].replace(",", "."))

    @staticmethod
    def _pct(value: float | None) -> str:
        return "—" if value is None else f"{100*value:.2f}%"
