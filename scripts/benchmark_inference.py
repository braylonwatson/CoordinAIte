"""Compare local inference paths using the actual saved models; no API/DB/WAN.

Run from the root: python scripts/benchmark_inference.py --iterations 1000
The Pandas baseline uses CORRECT team encoding so outputs can be compared.
It duplicates predict + predict_proba like the previous serving path.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np
import pandas as pd

from game_tracker import GameTracker, ModelBundle


class DuplicateInference:
    def __init__(self, model):
        self.model = model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def predict_proba(self, features):
        self.model.predict(features)
        return self.model.predict_proba(features)


class PandasTracker(GameTracker):
    def _prepare_features_for_columns(self, model_columns, **kwargs):
        values, game_rate, drive_rate = self._build_base_feature_values(**kwargs)
        frame = pd.get_dummies(pd.DataFrame([values]), columns=["posteam", "defteam"])
        return frame.reindex(columns=model_columns, fill_value=0), game_rate, drive_rate


def measure(tracker, tier, iterations):
    tracker.set_teams("KC", "BUF")
    method = tracker.predict_next_play if tier == 1 else tracker.predict_next_play_tier2
    for _ in range(30):
        method(3, 7, 50, 900, 3, -4)
    times = []
    for _ in range(iterations):
        started = perf_counter()
        result = method(3, 7, 50, 900, 3, -4)
        times.append((perf_counter() - started) * 1000)
    return result, {f"p{p}_ms": round(float(np.percentile(times, p)), 3) for p in (50, 95, 99)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    models = ModelBundle.load()
    slow_models = replace(models, **{
        name: DuplicateInference(getattr(models, name)) for name in
        ("model", "direction_model", "run_concept_model", "pass_concept_model")
        if getattr(models, name) is not None
    })
    report = {"iterations": args.iterations, "scope": "Warm local inference; excludes database and network", "tiers": {}}
    for tier in (1, 2) if models.tier2_available() else (1,):
        old, baseline = measure(PandasTracker(slow_models), tier, args.iterations)
        new, optimized = measure(GameTracker(models), tier, args.iterations)
        if old != new:
            raise AssertionError("Prediction parity failed against corrected Pandas baseline")
        report["tiers"][str(tier)] = {
            "pandas_double_inference": baseline, "numpy_single_inference": optimized,
            "p50_speedup": round(baseline["p50_ms"] / optimized["p50_ms"], 2),
            "prediction_parity": True,
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
