"""Small deterministic checks; CI never downloads data or retrains full models."""
from datetime import date
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import train_model as training
from feature_builder import build_feature_values, encode_feature_values
from game_tracker import GameTracker
from model_wrappers import EncodedClassifier


def play(game="game-a", number=1, offense="KC", drive=1, kind="run", **changes):
    row = dict(season=2026, season_type="REG", game_id=game, play_id=number,
               game_date="2026-10-05", week=4, desc="play", drive=drive,
               play_type=kind, posteam=offense, defteam="BUF", down=1,
               ydstogo=10, yardline_100=75, game_seconds_remaining=3600-number*10,
               qtr=1, score_differential=0, run_location="left", run_gap="guard",
               pass_location="middle", air_yards=5, qb_scramble=0)
    row.update(changes)
    return row


def test_history_matches_live_features_and_resets_by_offense_game_and_drive():
    rows = [play(number=i, kind="pass" if i % 3 else "run", drive=1 if i <= 5 else 3)
            for i in range(1, 13)]
    rows += [play(number=50, offense="BUF", kind="pass", drive=2), play(game="game-b")]
    features = training.clean_plays(pd.DataFrame(rows[::-1]))
    # No models are needed to exercise GameTracker's live history calculations.
    bundle = SimpleNamespace(**{key: None for key in [
        "model", "model_columns", "direction_model", "direction_model_columns",
        "run_concept_model", "run_concept_model_columns", "pass_concept_model",
        "pass_concept_model_columns",
    ]})
    tracker = GameTracker(bundle)
    previous_drive = None
    for row in features[(features.game_id == "game-a") & (features.posteam == "KC")].itertuples():
        if previous_drive != row.drive:
            tracker.drive_total_plays = tracker.drive_total_passes = 0
        assert row.prev_play_pass == tracker.prev_play_pass
        assert row.game_pass_rate == pytest.approx(tracker._current_game_pass_rate())
        assert row.drive_pass_rate == pytest.approx(tracker._current_drive_pass_rate())
        tracker.game_total_plays += 1
        tracker.game_total_passes += row.is_pass
        tracker.drive_total_plays += 1
        tracker.drive_total_passes += row.is_pass
        tracker.prev_play_pass = row.is_pass
        previous_drive = row.drive
    first_plays = features.groupby(["game_id", "posteam"]).head(1)
    assert (first_plays.prev_play_pass == 0).all()
    assert (first_plays.game_pass_rate == 0.5).all()
    assert (first_plays.drive_pass_rate == 0.5).all()


def test_current_and_future_labels_cannot_change_earlier_features():
    rows = pd.DataFrame([play(number=i, kind="pass") for i in range(1, 13)])
    original = training.clean_plays(rows)
    rows.loc[rows.play_id >= 9, "play_type"] = "run"
    changed = training.clean_plays(rows)
    history = ["prev_play_pass", "game_pass_rate", "drive_pass_rate"]
    pd.testing.assert_frame_equal(original.loc[original.play_id <= 9, history],
                                  changed.loc[changed.play_id <= 9, history])


def test_late_corrections_use_clock_order_and_normalize_rams():
    rows = pd.DataFrame([
        play(number=500, kind="pass", posteam="LA", game_seconds_remaining=3500),
        play(number=20, posteam="LA", game_seconds_remaining=3400),
    ])
    features = training.clean_plays(rows)
    assert features.play_id.tolist() == [500, 20]
    assert features.prev_play_pass.tolist() == [0, 1]
    assert features.posteam.tolist() == ["LAR", "LAR"]
    X, _, _, _ = training.prepare_encoded_xy(features, training.get_feature_columns(), "is_pass")
    for index, row in features.iterrows():
        values = build_feature_values(**{key: row[key] for key in [
            "down", "ydstogo", "yardline_100", "game_seconds_remaining", "qtr",
            "score_differential", "posteam", "defteam", "prev_play_pass",
            "game_pass_rate", "drive_pass_rate",
        ]})
        np.testing.assert_array_equal(encode_feature_values(values, X.columns), X.loc[[index]].values)


def test_split_keeps_entire_games_and_shared_dates_together():
    games = pd.DataFrame([
        {"game_id": f"g{i}", "game_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=i//2)}
        for i in range(20) for _ in range(3)
    ])
    train, test, cutoff = training.chronological_split(games, 0.2)
    assert not train & test
    assert train | test == set(games.game_id)
    assert games.loc[games.game_id.isin(train), "game_date"].max() < pd.Timestamp(cutoff)
    assert games.loc[games.game_id.isin(test), "game_date"].min() == pd.Timestamp(cutoff)


def test_encoded_classifier_forwards_weights_and_decodes_labels():
    class Estimator:
        def fit(self, X, y, sample_weight):
            self.y, self.weights = y, sample_weight

        def predict(self, X):
            return self.y

    weights = np.array([1.0, 1.5, 1.7])
    model = EncodedClassifier(Estimator()).fit([[0], [1], [2]], ["right", "left", "right"], weights)
    np.testing.assert_array_equal(model.estimator.weights, weights)
    assert model.predict([[0], [1], [2]]).tolist() == ["right", "left", "right"]


def write_season(directory, season, extra=None):
    rows = [play(game=f"{season}_complete", season=season, game_date=f"{season}-09-01"),
            play(game=f"{season}_complete", season=season, game_date=f"{season}-09-01",
                 number=3, desc="END GAME", play_type=None, game_seconds_remaining=0),
            # A stat correction with an ID after the completion marker.
            play(game=f"{season}_complete", season=season, game_date=f"{season}-09-01",
                 number=4, kind="pass", game_seconds_remaining=3500)]
    rows.extend(extra or [])
    pd.DataFrame(rows).to_parquet(directory / f"play_by_play_{season}.parquet")


def test_loader_requires_completed_games_and_allows_only_2026_to_be_absent(tmp_path):
    for year in [2022, 2023, 2024, 2025]:
        write_season(tmp_path, year)
    data, sources, skipped = training.load_seasons(tmp_path, date(2026, 10, 8), tmp_path)
    assert sorted(data.season.unique()) == [2022, 2023, 2024, 2025]
    assert all(source["included_games"] == 1 for source in sources)
    assert [item["season"] for item in skipped] == [2026]
    write_season(tmp_path, 2026, extra=[
        play(game="unfinished", desc="still playing"),
        play(game="future", game_date="2026-10-09", desc="END GAME"),
    ])
    data, _, skipped = training.load_seasons(tmp_path, date(2026, 10, 8), tmp_path)
    assert skipped == []
    assert set(data[data.season == 2026].game_id) == {"2026_complete"}
    (tmp_path / "play_by_play_2025.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        training.load_seasons(tmp_path, date(2026, 10, 8), tmp_path)


def test_release_artifacts_match_their_provenance():
    report = json.loads((training.BACKEND_DIR / "training_metadata.json").read_text())
    assert report["requested_seasons"] == training.SEASONS
    assert 2021 not in report["included_seasons"]
    assert set(report["evaluation"]["train_game_ids"]).isdisjoint(report["evaluation"]["test_game_ids"])
    filenames = {
        "tier1": ("play_predictor_model.pkl", "model_columns.pkl"),
        "direction": ("direction_predictor_model.pkl", "direction_model_columns.pkl"),
        "run_concept": ("run_concept_predictor_model.pkl", "run_concept_model_columns.pkl"),
        "pass_concept": ("pass_concept_predictor_model.pkl", "pass_concept_model_columns.pkl"),
    }
    for name, (model, columns) in filenames.items():
        metadata = report["models"][name]
        assert training.sha256(training.BACKEND_DIR / model) == metadata["release_model_sha256"]
        assert training.sha256(training.BACKEND_DIR / columns) == metadata["release_columns_sha256"]
        assert training.joblib.load(training.BACKEND_DIR / columns) == metadata["features"]
