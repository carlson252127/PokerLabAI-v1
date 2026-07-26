from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import math
import random
from typing import Any, Iterable


CLASSES = (
    "2.00", "2.25", "2.50", "3.00", "3.50", "4.00",
    "other_low", "other_high",
)
LOW_CLASSES = frozenset(("2.00", "2.25", "2.50", "3.00", "other_low"))
HIGH_CLASSES = frozenset(("3.50", "4.00", "other_high"))


class ComparableOpenSizeModels:
    """Paired grouped-CV comparison on one multiclass sizing target."""

    MODEL_SPECS = {
        "INTERCEPT": (),
        "POSITION": ("position",),
        "POSITION_STACK_HOUR": ("position", "stack_bucket", "hour_bucket"),
        "FULL_TABLE_SESSION": (
            "position", "stack_bucket", "hour_bucket", "table_id",
            "session_id",
        ),
    }

    @classmethod
    def evaluate(
        cls,
        records: Iterable[dict[str, Any]],
        folds: int = 5,
        bootstrap_iterations: int = 1000,
        permutation_iterations: int = 100,
        seed: int = 20260726,
        group_mode: str = "session",
    ) -> dict[str, Any]:
        rows = []
        for source in records:
            row = dict(source)
            target = str(row.get("size_bucket") or "")
            if target == "other":
                target = "other_high" if row.get("high_size") else "other_low"
            if target not in CLASSES:
                continue
            row["size_bucket"] = target
            rows.append(row)
        fold_map = cls._fold_map(rows, folds, group_mode)
        cls.assert_no_leakage(rows, fold_map, group_mode)
        predictions: dict[str, list[list[float]]] = defaultdict(list)
        observed: list[str] = []
        groups: list[str] = []

        for fold in sorted(set(fold_map.values())):
            train = [r for r in rows if fold_map[cls._group(r, group_mode)] != fold]
            test = [r for r in rows if fold_map[cls._group(r, group_mode)] == fold]
            if not train or not test:
                continue
            direct = {
                name: cls._fit_direct(train, features)
                for name, features in cls.MODEL_SPECS.items()
            }
            two_stage = cls._fit_two_stage(
                train, cls.MODEL_SPECS["FULL_TABLE_SESSION"]
            )
            for row in test:
                observed.append(str(row["size_bucket"]))
                groups.append(cls._group(row, group_mode))
                for name, model in direct.items():
                    predictions[name].append(cls._predict_direct(model, row))
                predictions["TWO_STAGE"].append(
                    cls._predict_two_stage(two_stage, row)
                )

        losses = {
            name: cls._row_losses(observed, values)
            for name, values in predictions.items()
        }
        reference = losses["POSITION"]
        metrics = []
        rng = random.Random(seed)
        for name in (
            "INTERCEPT", "POSITION", "POSITION_STACK_HOUR",
            "FULL_TABLE_SESSION", "TWO_STAGE",
        ):
            row_losses = losses[name]
            delta = cls._mean([
                value - baseline
                for value, baseline in zip(row_losses, reference)
            ])
            ci_low, ci_high = cls._cluster_bootstrap_delta(
                row_losses,
                reference,
                groups,
                bootstrap_iterations,
                rng,
            )
            metrics.append({
                "model": name,
                "target_classes": "|".join(CLASSES),
                "records": len(observed),
                "folds": len(set(fold_map.values())),
                "weighting": "NATURAL_ROW_WEIGHT",
                "log_loss": cls._mean(row_losses),
                "delta_log_loss_vs_position": delta,
                "delta_ci_low": ci_low,
                "delta_ci_high": ci_high,
                "multiclass_brier": cls._brier(observed, predictions[name]),
            })

        permutation = cls._permutation_baseline(
            rows, fold_map, group_mode, permutation_iterations, seed
        )
        for item in metrics:
            baseline = permutation.get(item["model"], {})
            item["permutation_mean_log_loss"] = baseline.get("mean_log_loss")
            item["permutation_ci_low"] = baseline.get("ci_low")
            item["permutation_ci_high"] = baseline.get("ci_high")
        pairwise = []
        for left, right in (
            ("FULL_TABLE_SESSION", "POSITION"),
            ("TWO_STAGE", "POSITION"),
            ("TWO_STAGE", "FULL_TABLE_SESSION"),
        ):
            ci_low, ci_high = cls._cluster_bootstrap_delta(
                losses[left],
                losses[right],
                groups,
                bootstrap_iterations,
                random.Random(seed + len(pairwise) + 101),
            )
            pairwise.append({
                "left": left,
                "right": right,
                "delta_log_loss": cls._mean([
                    a - b for a, b in zip(losses[left], losses[right])
                ]),
                "ci_low": ci_low,
                "ci_high": ci_high,
            })
        return {
            "target_classes": list(CLASSES),
            "records": len(observed),
            "group_mode": group_mode,
            "fold_assignments": fold_map,
            "metrics": metrics,
            "permutation_baseline": permutation,
            "pairwise_deltas": pairwise,
            "same_sample": all(len(v) == len(observed) for v in predictions.values()),
            "same_folds": True,
            "same_weighting": True,
        }

    @classmethod
    def assert_no_leakage(
        cls,
        rows: list[dict[str, Any]],
        fold_map: dict[str, int],
        group_mode: str,
    ) -> None:
        seen: dict[str, int] = {}
        for row in rows:
            group = cls._group(row, group_mode)
            fold = fold_map[group]
            if group in seen and seen[group] != fold:
                raise AssertionError(f"Group leaked across folds: {group}")
            seen[group] = fold
        if group_mode == "player":
            players = defaultdict(set)
            for row in rows:
                players[str(row["player"])].add(
                    fold_map[cls._group(row, group_mode)]
                )
            if any(len(values) != 1 for values in players.values()):
                raise AssertionError("Player leakage detected")
        else:
            sessions = defaultdict(set)
            for row in rows:
                sessions[
                    f"{row.get('player','')}|{row.get('session_id','')}"
                ].add(fold_map[cls._group(row, group_mode)])
            if any(len(values) != 1 for values in sessions.values()):
                raise AssertionError("Session leakage detected")

    @classmethod
    def _fold_map(
        cls, rows: list[dict[str, Any]], folds: int, group_mode: str
    ) -> dict[str, int]:
        groups = sorted({cls._group(row, group_mode) for row in rows})
        return {
            group: int(
                hashlib.sha1(group.encode()).hexdigest()[:8], 16
            ) % max(2, folds)
            for group in groups
        }

    @staticmethod
    def _group(row: dict[str, Any], mode: str) -> str:
        if mode == "player":
            return str(row.get("player") or "unknown")
        return (
            f"{row.get('player','unknown')}|"
            f"{row.get('session_id') or row.get('table_id') or 'unknown'}"
        )

    @classmethod
    def _fit_direct(
        cls, rows: list[dict[str, Any]], features: tuple[str, ...]
    ) -> dict[str, Any]:
        global_counts = Counter(str(r["size_bucket"]) for r in rows)
        feature_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for row in rows:
            for feature in features:
                feature_counts[(feature, str(row.get(feature, "unknown")))][
                    str(row["size_bucket"])
                ] += 1
        return {
            "global": global_counts,
            "features": features,
            "feature_counts": feature_counts,
        }

    @classmethod
    def _predict_direct(
        cls, model: dict[str, Any], row: dict[str, Any]
    ) -> list[float]:
        global_counts: Counter = model["global"]
        total = sum(global_counts.values())
        prior = {
            target: (global_counts[target] + 1) / (total + len(CLASSES))
            for target in CLASSES
        }
        scores = {target: math.log(prior[target]) for target in CLASSES}
        used = 0
        for feature in model["features"]:
            counts = model["feature_counts"][
                (feature, str(row.get(feature, "unknown")))
            ]
            count_total = sum(counts.values())
            if count_total < 10:
                continue
            used += 1
            for target in CLASSES:
                probability = (
                    counts[target] + 5 * prior[target]
                ) / (count_total + 5)
                scores[target] += 0.35 * math.log(
                    probability / prior[target]
                )
        return cls._softmax([scores[target] for target in CLASSES])

    @classmethod
    def _fit_two_stage(
        cls, rows: list[dict[str, Any]], features: tuple[str, ...]
    ) -> dict[str, Any]:
        mode_rows = []
        within: dict[tuple[str, str], Counter] = defaultdict(Counter)
        global_within: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            target = str(row["size_bucket"])
            mode = "LOW" if target in LOW_CLASSES else "HIGH"
            copied = dict(row)
            copied["size_bucket"] = mode
            mode_rows.append(copied)
            within[(mode, str(row.get("position", "unknown")))][target] += 1
            global_within[mode][target] += 1
        return {
            "mode": cls._fit_binary_mode(mode_rows, features),
            "within": within,
            "global_within": global_within,
        }

    @classmethod
    def _fit_binary_mode(
        cls, rows: list[dict[str, Any]], features: tuple[str, ...]
    ) -> dict[str, Any]:
        labels = ("LOW", "HIGH")
        global_counts = Counter(str(r["size_bucket"]) for r in rows)
        feature_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for row in rows:
            for feature in features:
                feature_counts[(feature, str(row.get(feature, "unknown")))][
                    str(row["size_bucket"])
                ] += 1
        return {
            "labels": labels, "global": global_counts,
            "features": features, "feature_counts": feature_counts,
        }

    @classmethod
    def _predict_two_stage(
        cls, model: dict[str, Any], row: dict[str, Any]
    ) -> list[float]:
        mode_model = model["mode"]
        total = sum(mode_model["global"].values())
        mode_prior = {
            label: (mode_model["global"][label] + 1) / (total + 2)
            for label in ("LOW", "HIGH")
        }
        scores = {label: math.log(mode_prior[label]) for label in mode_prior}
        for feature in mode_model["features"]:
            counts = mode_model["feature_counts"][
                (feature, str(row.get(feature, "unknown")))
            ]
            count_total = sum(counts.values())
            if count_total < 10:
                continue
            for label in scores:
                probability = (
                    counts[label] + 5 * mode_prior[label]
                ) / (count_total + 5)
                scores[label] += 0.35 * math.log(
                    probability / mode_prior[label]
                )
        mode_probabilities = cls._softmax([scores["LOW"], scores["HIGH"]])
        result = []
        for target in CLASSES:
            mode = "LOW" if target in LOW_CLASSES else "HIGH"
            candidates = LOW_CLASSES if mode == "LOW" else HIGH_CLASSES
            counts = model["within"][
                (mode, str(row.get("position", "unknown")))
            ]
            fallback = model["global_within"][mode]
            count_total = sum(counts.values())
            fallback_total = sum(fallback.values())
            within_probability = (
                counts[target]
                + (fallback[target] + 1) / (fallback_total + len(candidates))
            ) / (count_total + 1)
            result.append(
                mode_probabilities[0 if mode == "LOW" else 1]
                * within_probability
            )
        normalizer = sum(result)
        return [value / normalizer for value in result]

    @staticmethod
    def _softmax(values: list[float]) -> list[float]:
        maximum = max(values)
        exponentials = [math.exp(value - maximum) for value in values]
        total = sum(exponentials)
        return [value / total for value in exponentials]

    @staticmethod
    def _row_losses(
        observed: list[str], predictions: list[list[float]]
    ) -> list[float]:
        index = {target: position for position, target in enumerate(CLASSES)}
        return [
            -math.log(max(1e-12, prediction[index[target]]))
            for target, prediction in zip(observed, predictions)
        ]

    @classmethod
    def _cluster_bootstrap_delta(
        cls,
        losses: list[float],
        reference: list[float],
        groups: list[str],
        iterations: int,
        rng: random.Random,
    ) -> tuple[float | None, float | None]:
        indices = defaultdict(list)
        for index, group in enumerate(groups):
            indices[group].append(index)
        unique = list(indices)
        if len(unique) < 2 or iterations <= 0:
            return None, None
        values = []
        for _ in range(iterations):
            sampled = [rng.choice(unique) for _ in unique]
            selected = [i for group in sampled for i in indices[group]]
            values.append(cls._mean([
                losses[i] - reference[i] for i in selected
            ]))
        values.sort()
        return (
            values[int(0.025 * (len(values) - 1))],
            values[int(0.975 * (len(values) - 1))],
        )

    @classmethod
    def _permutation_baseline(
        cls,
        rows: list[dict[str, Any]],
        fold_map: dict[str, int],
        group_mode: str,
        iterations: int,
        seed: int,
    ) -> dict[str, Any]:
        rng = random.Random(seed)
        values: dict[str, list[float]] = defaultdict(list)
        labels = [row["size_bucket"] for row in rows]
        for _ in range(iterations):
            shuffled = labels[:]
            rng.shuffle(shuffled)
            permuted = [dict(row, size_bucket=label) for row, label in zip(rows, shuffled)]
            losses: dict[str, list[float]] = defaultdict(list)
            for fold in sorted(set(fold_map.values())):
                train = [
                    r for r in permuted
                    if fold_map[cls._group(r, group_mode)] != fold
                ]
                test = [
                    r for r in permuted
                    if fold_map[cls._group(r, group_mode)] == fold
                ]
                if not train or not test:
                    continue
                observed = [str(r["size_bucket"]) for r in test]
                for name, features in cls.MODEL_SPECS.items():
                    model = cls._fit_direct(train, features)
                    predicted = [
                        cls._predict_direct(model, row) for row in test
                    ]
                    losses[name].extend(
                        cls._row_losses(observed, predicted)
                    )
                two_stage = cls._fit_two_stage(
                    train, cls.MODEL_SPECS["FULL_TABLE_SESSION"]
                )
                predicted = [
                    cls._predict_two_stage(two_stage, row) for row in test
                ]
                losses["TWO_STAGE"].extend(
                    cls._row_losses(observed, predicted)
                )
            for name, model_losses in losses.items():
                values[name].append(cls._mean(model_losses))
        result = {}
        for name, samples in values.items():
            samples.sort()
            result[name] = {
                "iterations": iterations,
                "mean_log_loss": cls._mean(samples),
                "ci_low": samples[int(0.025 * (len(samples) - 1))]
                if samples else None,
                "ci_high": samples[int(0.975 * (len(samples) - 1))]
                if samples else None,
            }
        return result

    @staticmethod
    def _brier(observed: list[str], predictions: list[list[float]]) -> float:
        index = {target: position for position, target in enumerate(CLASSES)}
        values = []
        for target, prediction in zip(observed, predictions):
            actual = index[target]
            values.append(sum(
                (probability - int(position == actual)) ** 2
                for position, probability in enumerate(prediction)
            ))
        return ComparableOpenSizeModels._mean(values)

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else math.nan
