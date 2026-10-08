"""Refresh model artifacts from official nflverse season snapshots.

Evaluate on complete recent games, then refit release models on all eligible
plays. Downloads and training never change the running ECS deployment.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, log_loss
from xgboost import XGBClassifier

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "backend"))
from model_wrappers import EncodedClassifier
from feature_builder import build_situational_flags

SEASONS = [2022, 2023, 2024, 2025, 2026]
SEASON_WEIGHTS = {2022: 1.0, 2023: 1.1, 2024: 1.3, 2025: 1.5, 2026: 1.7}
BACKEND_DIR = BASE_DIR / "backend"
SOURCE = "https://github.com/nflverse/nflverse-data/releases/download/pbp"
TEAMS = sorted("ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split())
SOURCE_COLUMNS = [
    "season", "season_type", "game_id", "play_id", "game_date", "week", "desc",
    "drive", "play_type", "posteam", "defteam", "down", "ydstogo", "yardline_100",
    "game_seconds_remaining", "qtr", "score_differential", "run_location", "run_gap",
    "pass_location", "air_yards", "qb_scramble",
]


def make_xgb_classifier(num_classes=None, n_jobs=2):
    params = dict(n_estimators=300, max_depth=5, learning_rate=0.05,
                  subsample=0.9, colsample_bytree=0.9, random_state=42,
                  n_jobs=n_jobs, tree_method="hist", eval_metric="logloss")
    if num_classes and num_classes > 2:
        params.update(objective="multi:softprob", num_class=num_classes, eval_metric="mlogloss")
    return XGBClassifier(**params)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_season_weight(season):
    return SEASON_WEIGHTS[int(season)]


def load_seasons(data_dir, as_of, download_dir):
    frames, sources, skipped = [], [], []
    for season in SEASONS:
        filename = f"play_by_play_{season}.parquet"
        path = (data_dir or download_dir) / filename
        url = f"{SOURCE}/{filename}"
        if data_dir is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urlopen(url, timeout=90) as response, path.with_suffix(".part").open("wb") as out:
                    shutil.copyfileobj(response, out)
                path.with_suffix(".part").replace(path)
            except HTTPError as exc:
                if season == 2026 and exc.code == 404:
                    skipped.append({"season": season, "reason": "not published (HTTP 404)"})
                    continue
                raise
        elif not path.is_file() and season == 2026:
            skipped.append({"season": season, "reason": "not present in supplied data directory"})
            continue
        # Missing required years, network failures, and malformed files are errors.
        raw = pd.read_parquet(path, columns=SOURCE_COLUMNS)
        if raw.empty and season == 2026:
            skipped.append({"season": season, "reason": "published file is empty"})
            continue
        if raw.empty or set(raw.season.dropna().astype(int)) != {season}:
            raise ValueError(f"Unexpected season content in {path.name}")
        raw["game_date"] = pd.to_datetime(raw.game_date, errors="raise")
        eligible = raw[(raw.game_date.dt.date <= as_of) & raw.season_type.isin(["REG", "POST"])].copy()
        # Corrected plays can have IDs after the END GAME record. Presence of
        # that marker establishes completion without discarding corrected games.
        complete = eligible.loc[eligible.desc.fillna("").str.strip().eq("END GAME"), "game_id"]
        eligible = eligible[eligible.game_id.isin(complete)]
        if eligible.empty:
            if season == 2026:
                skipped.append({"season": season, "reason": "no completed games at cutoff"})
                continue
            raise ValueError(f"No completed games for required season {season}")
        sources.append({"season": season, "url": url, "sha256": sha256(path),
                        "raw_rows": len(raw), "included_games": eligible.game_id.nunique(),
                        "excluded_games": raw.game_id.nunique() - eligible.game_id.nunique(),
                        "weeks": sorted(eligible.week.dropna().astype(int).unique().tolist()),
                        "last_game_date": str(eligible.game_date.max().date())})
        frames.append(eligible)
        print(f"Loaded {season}: {eligible.game_id.nunique()} completed games through {eligible.game_date.max().date()}", flush=True)
    return pd.concat(frames, ignore_index=True), sources, skipped


def clean_plays(raw):
    pbp = raw[raw.play_type.isin(["run", "pass"])].copy()
    numeric = ["down", "ydstogo", "yardline_100", "game_seconds_remaining", "qtr", "score_differential"]
    for name in numeric:
        pbp[name] = pd.to_numeric(pbp[name], errors="coerce")
    pbp = pbp.dropna(subset=numeric + ["game_id", "play_id", "drive", "posteam", "defteam", "season"])
    pbp = pbp[pbp.down.between(1, 4) & pbp.ydstogo.between(1, 99)
              & pbp.yardline_100.between(1, 100) & pbp.qtr.between(1, 5)
              & pbp.game_seconds_remaining.between(0, 3600)].copy()
    for team_column in ["posteam", "defteam"]:
        pbp[team_column] = pbp[team_column].replace({"LA": "LAR", "STL": "LAR", "OAK": "LV", "SD": "LAC"})
        unknown = set(pbp[team_column].unique()) - set(TEAMS)
        if unknown:
            raise ValueError(f"Unknown team codes: {unknown}")
    if pbp.duplicated(["game_id", "play_id"]).any():
        raise ValueError("Duplicate play identifiers in the training data")
    pbp["season_weight"] = pbp.season.apply(get_season_weight)
    return add_shared_features(pbp.reset_index(drop=True))


def add_shared_features(pbp):
    """Use prior plays of the selected offense, matching GameTracker rates."""
    # NFL corrections can arrive with larger play IDs; use the game clock to
    # keep prior-play features chronological, including overtime periods.
    pbp = pbp.sort_values(
        ["game_id", "qtr", "game_seconds_remaining", "play_id"],
        ascending=[True, True, False, True], kind="stable",
    ).copy()
    for name in ["down", "ydstogo", "yardline_100", "game_seconds_remaining", "qtr", "score_differential"]:
        pbp[name] = pbp[name].astype(int)
    pbp["is_pass"] = pbp.play_type.eq("pass").astype(int)
    game_keys = ["game_id", "posteam"]
    drive_keys = game_keys + ["drive"]
    offense = pbp.groupby(game_keys, sort=False)
    pbp["prev_play_pass"] = offense.is_pass.shift(1).fillna(0).astype(int)
    for keys, name, minimum in [(game_keys, "game_pass_rate", 8), (drive_keys, "drive_pass_rate", 4)]:
        grouped = pbp.groupby(keys, sort=False)
        plays_before = grouped.cumcount()
        passes_before = grouped.is_pass.cumsum() - pbp.is_pass
        pbp[name] = ((passes_before + 1) / (plays_before + 2)).where(plays_before >= minimum, 0.5)
    flags = pbp.apply(lambda row: build_situational_flags(
        down=row.down, ydstogo=row.ydstogo, yardline_100=row.yardline_100,
        game_seconds_remaining=row.game_seconds_remaining, qtr=row.qtr,
        score_differential=row.score_differential), axis=1, result_type="expand")
    for name in flags:
        pbp[name] = flags[name]
    return pbp


def normalize_direction(value):
    if pd.isna(value):
        return None

    value = str(value).strip().lower()

    mapping = {
        "left": "left",
        "middle": "middle",
        "center": "middle",
        "right": "right",
    }

    return mapping.get(value)


def classify_run_concept(row):
    run_location = normalize_direction(row.get("run_location"))
    run_gap = row.get("run_gap")
    ydstogo = row.get("ydstogo")

    if pd.isna(run_gap):
        return None

    run_gap = str(run_gap).strip().lower()

    if run_location == "middle" and run_gap == "guard" and pd.notna(ydstogo) and float(ydstogo) <= 1:
        return "qb_sneak"

    if run_location == "middle" and run_gap in {"guard", "tackle"}:
        return "inside_zone"

    if run_location in {"left", "right"} and run_gap == "guard":
        return "power_counter"

    if run_location in {"left", "right"} and run_gap == "end":
        return "edge_sweep"

    if run_location in {"left", "right"} and run_gap in {"tackle", "end"}:
        return "outside_zone"

    return None


def classify_pass_concept(row):
    qb_scramble = row.get("qb_scramble", 0)
    air_yards = row.get("air_yards")

    if pd.notna(qb_scramble) and int(qb_scramble) == 1:
        return "qb_scramble"

    if pd.isna(air_yards):
        return None

    air_yards = float(air_yards)

    if air_yards <= 0:
        return "screen"

    if air_yards <= 5:
        return "quick_game"

    if air_yards <= 15:
        return "intermediate"

    return "deep_shot"


def get_feature_columns(include_is_pass=False):
    features = [
        "down",
        "ydstogo",
        "yardline_100",
        "game_seconds_remaining",
        "qtr",
        "score_differential",
        "posteam",
        "defteam",
        "prev_play_pass",
        "game_pass_rate",
        "drive_pass_rate",
        "is_third_down",
        "is_fourth_down",
        "short_yardage",
        "medium_yardage",
        "long_yardage",
        "red_zone",
        "goal_to_go",
        "backed_up",
        "plus_territory",
        "two_minute",
        "leading_team",
        "trailing_team",
        "neutral_score",
    ]

    if include_is_pass:
        features.append("is_pass")

    return features


def chronological_split(pbp, fraction):
    games = pbp[["game_id", "game_date"]].drop_duplicates().sort_values(["game_date", "game_id"])
    if len(games) < 10:
        raise ValueError("Need at least ten complete games to evaluate")
    position = min(len(games) - 1, max(1, int(len(games) * (1 - fraction))))
    cutoff = games.iloc[position].game_date
    train = set(games.loc[games.game_date < cutoff, "game_id"])
    test = set(games.loc[games.game_date >= cutoff, "game_id"])
    if not train or not test or train & test:
        raise ValueError("Could not create a disjoint chronological game split")
    return train, test, str(cutoff.date())


def prepare_encoded_xy(df, features, target):
    working = df.dropna(subset=features + [target, "season_weight"]).copy()
    inputs = working[features].copy()
    for name in ["posteam", "defteam"]:
        inputs[name] = pd.Categorical(inputs[name], categories=TEAMS)
    X = pd.get_dummies(inputs, columns=["posteam", "defteam"], drop_first=True).astype(np.float32)
    if X.columns.duplicated().any():
        raise ValueError("Duplicate feature columns")
    return X, working[target], working.season_weight, working


def labeled_frames(pbp):
    direction = pbp.copy()
    direction["play_direction"] = direction.apply(
        lambda row: normalize_direction(row.run_location if row.play_type == "run" else row.pass_location), axis=1)
    run = pbp[pbp.play_type == "run"].copy()
    run["run_concept"] = run.apply(classify_run_concept, axis=1)
    passes = pbp[pbp.play_type == "pass"].copy()
    passes["pass_concept"] = passes.apply(classify_pass_concept, axis=1)
    return [
        ("tier1", pbp.assign(target_is_pass=pbp.is_pass), "target_is_pass", False, "play_predictor_model.pkl", "model_columns.pkl"),
        ("direction", direction, "play_direction", True, "direction_predictor_model.pkl", "direction_model_columns.pkl"),
        ("run_concept", run, "run_concept", False, "run_concept_predictor_model.pkl", "run_concept_model_columns.pkl"),
        ("pass_concept", passes, "pass_concept", False, "pass_concept_predictor_model.pkl", "pass_concept_model_columns.pkl"),
    ]


def new_model(y, wrapped, n_jobs):
    count = len(y.unique())
    if count < 2:
        raise ValueError("Each model needs at least two training classes")
    estimator = make_xgb_classifier(num_classes=count, n_jobs=n_jobs)
    return EncodedClassifier(estimator) if wrapped else estimator


def metrics(model, X, y):
    prediction = model.predict(X)
    result = {"samples": len(y), "accuracy": float(accuracy_score(y, prediction)),
              "classification_report": classification_report(y, prediction, output_dict=True, zero_division=0)}
    if set(y.unique()).issubset({0, 1}):
        probabilities = model.predict_proba(X)
        result["log_loss"] = float(log_loss(y, probabilities, labels=[0, 1]))
        result["brier_score"] = float(np.mean((probabilities[:, 1] - np.asarray(y)) ** 2))
    return result


def train_models(pbp, train_games, test_games, model_dir, baseline_dir, n_jobs):
    results = {}
    for name, df, target, use_play_type, model_name, columns_name in labeled_frames(pbp):
        X, y, weights, rows = prepare_encoded_xy(df, get_feature_columns(use_play_type), target)
        train = rows.game_id.isin(train_games)
        test = rows.game_id.isin(test_games)
        if not train.any() or not test.any():
            raise ValueError(f"No train/test examples for {name}")
        print(f"Evaluating {name}: {int(train.sum())} training / {int(test.sum())} held-out plays", flush=True)
        candidate = new_model(y[train], name != "tier1", n_jobs)
        candidate.fit(X[train], y[train], sample_weight=weights[train])
        report = metrics(candidate, X[test], y[test])
        report["training_samples"] = int(train.sum())
        report["heldout_games"] = rows.loc[test, "game_id"].nunique()
        report["per_season"] = {}
        for season in sorted(rows.loc[test, "season"].unique()):
            mask = test & rows.season.eq(season)
            report["per_season"][str(int(season))] = metrics(candidate, X[mask], y[mask])
        report["note"] = (
            "Chronological holdout; no games shared with fitting data."
            if name == "tier1" else
            "Conditional evaluation on the actual play type; concept labels are existing heuristics, not charted ground truth."
        )
        if baseline_dir and (baseline_dir / model_name).is_file():
            baseline = joblib.load(baseline_dir / model_name)
            baseline_columns = joblib.load(baseline_dir / columns_name)
            getattr(baseline, "estimator", baseline).set_params(n_jobs=1)
            aligned = X.reindex(columns=baseline_columns, fill_value=0)
            report["previous_model"] = metrics(baseline, aligned[test], y[test])
            report["previous_model"]["per_season"] = {}
            for season in sorted(rows.loc[test, "season"].unique()):
                mask = test & rows.season.eq(season)
                report["previous_model"]["per_season"][str(int(season))] = metrics(baseline, aligned[mask], y[mask])
            report["previous_model_sha256"] = sha256(baseline_dir / model_name)
        print(f"  Held-out accuracy: {report['accuracy']:.4f}; refitting on {len(y)} plays", flush=True)
        # The evaluated model above is discarded. Release models use all eligible
        # games, including 2026. Do not report the holdout as a test of that refit.
        release = new_model(y, name != "tier1", n_jobs)
        release.fit(X, y, sample_weight=weights)
        getattr(release, "estimator", release).set_params(n_jobs=1)
        joblib.dump(release, model_dir / model_name)
        joblib.dump(X.columns.tolist(), model_dir / columns_name)
        report["release_fit_samples"] = len(y)
        report["release_classes"] = sorted(y.unique().tolist())
        report["features"] = X.columns.tolist()
        report["release_model_sha256"] = sha256(model_dir / model_name)
        report["release_columns_sha256"] = sha256(model_dir / columns_name)
        results[name] = report
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Reuse explicitly supplied nflverse parquet snapshots")
    parser.add_argument("--output-dir", type=Path, help="New run directory; defaults to training_runs/<UTC timestamp>")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--baseline-dir", type=Path, default=BACKEND_DIR)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if not 0.05 <= args.holdout_fraction <= 0.5 or args.jobs < 1:
        parser.error("Use a holdout fraction from 0.05 to 0.5 and at least one job")
    output = args.output_dir or BASE_DIR / "training_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=False)
    model_dir = output / "models"
    model_dir.mkdir()
    raw, sources, skipped = load_seasons(args.data_dir, args.as_of, output / "data")
    pbp = clean_plays(raw)
    train_games, test_games, cutoff = chronological_split(pbp, args.holdout_fraction)
    dataset = [{"season": int(season), "plays": len(group), "games": group.game_id.nunique(),
                "last_game_date": str(group.game_date.max().date()),
                "weeks": sorted(group.week.astype(int).unique().tolist())}
               for season, group in pbp.groupby("season")]
    manifest = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(), "as_of": str(args.as_of),
        "requested_seasons": SEASONS, "included_seasons": [item["season"] for item in dataset],
        "skipped_seasons": skipped, "sources": sources, "dataset": dataset,
        "eligible_run_pass_rows_before_cleaning": int(raw.play_type.isin(["run", "pass"]).sum()),
        "training_rows_after_cleaning": len(pbp), "season_weights": SEASON_WEIGHTS,
        "evaluation": {"method": "chronological by complete game, common cutoff for every model",
                       "test_start_date": cutoff, "training_games": len(train_games), "test_games": len(test_games),
                       "train_game_ids": sorted(train_games), "test_game_ids": sorted(test_games)},
        "release_fit": "Refit on all eligible games after evaluation; further unseen games are needed to assess these final artifacts.",
        "feature_history": "Prior offense plays within each game; drive reset; live smoothing (minimum 8 game plays / 4 drive plays).",
        "versions": {package: importlib.metadata.version(package) for package in ["pandas", "numpy", "xgboost", "scikit-learn", "joblib", "pyarrow"]},
        "python": sys.version.split()[0], "jobs": args.jobs,
        "source_code_sha256": {name: sha256(BASE_DIR / name) for name in [
            "train_model.py", "backend/model_wrappers.py", "backend/feature_builder.py",
        ]},
    }
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    manifest["models"] = train_models(pbp, train_games, test_games, model_dir, args.baseline_dir, args.jobs)
    (output / "training_report.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(output / "training_report.json", model_dir / "training_metadata.json")
    print(f"Models and report saved to {output}. Backend files have not been overwritten.", flush=True)


if __name__ == "__main__":
    main()
