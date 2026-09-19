from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import pytest

from feature_builder import build_feature_values, encode_feature_values
from game_tracker import GameTracker, ModelBundle
from app.services.game_sessions import VALID_TEAMS


@pytest.fixture(scope="module")
def real_models():
    return ModelBundle.load()


def values(offense="KC", defense="BUF"):
    return build_feature_values(3, 7, 35, 110, 4, -4, offense, defense, 1, 0.625, 0.4)


def test_arrays_match_training_columns_for_all_teams(real_models):
    for offense in VALID_TEAMS:
        for defense in VALID_TEAMS:
            row = values(offense, defense)
            # Use saved columns to drop training baseline categories. Dropping
            # the first category of this one-row sample would erase both teams.
            reference = pd.get_dummies(pd.DataFrame([row]), columns=["posteam", "defteam"])
            for columns in (real_models.model_columns, real_models.direction_model_columns,
                            real_models.run_concept_model_columns, real_models.pass_concept_model_columns):
                expected = reference.reindex(columns=columns, fill_value=0).to_numpy(dtype=np.float32)
                np.testing.assert_array_equal(encode_feature_values(row, columns), expected)


def test_team_features_are_present_and_buffers_are_independent():
    columns = ["posteam_KC", "defteam_BUF", "down", "missing_numeric"]
    first = encode_feature_values(values(), columns)
    second = encode_feature_values(values("BUF", "KC"), columns)
    np.testing.assert_array_equal(first, [[1, 1, 3, 0]])
    np.testing.assert_array_equal(second, [[0, 0, 3, 0]])
    first[:] = 9
    np.testing.assert_array_equal(second, [[0, 0, 3, 0]])


def test_saved_models_produce_same_probabilities_on_arrays(real_models):
    tracker = GameTracker(real_models)
    for model, columns in (
        (real_models.model, real_models.model_columns),
        (real_models.direction_model, real_models.direction_model_columns),
        (real_models.run_concept_model, real_models.run_concept_model_columns),
        (real_models.pass_concept_model, real_models.pass_concept_model_columns),
    ):
        for offense, defense in [("KC", "BUF"), ("ARI", "ARI"), ("SEA", "MIN")]:
            frame = pd.get_dummies(pd.DataFrame([values(offense, defense)]), columns=["posteam", "defteam"])
            frame = frame.reindex(columns=columns, fill_value=0)
            array = encode_feature_values(values(offense, defense), columns)
            np.testing.assert_allclose(model.predict_proba(frame), model.predict_proba(array), rtol=1e-6)
            label, confidence = tracker._predict_label_and_confidence(model, array)
            assert label == model.predict(frame)[0]
            assert confidence == pytest.approx(max(model.predict_proba(frame)[0]))


def test_shared_models_are_safe_across_independent_trackers(real_models):
    def infer(index):
        tracker = GameTracker(real_models)
        tracker.set_teams("KC" if index % 2 else "BUF", "MIN")
        return tracker.predict_next_play_tier2(3, 7, 35, 110, 4, -4)
    expected = [infer(i) for i in range(24)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(infer, range(24))) == expected


def test_binary_tie_remains_run(model_bundle):
    model_bundle.model.predict_proba = lambda _: [[0.5, 0.5]]
    tracker = GameTracker(model_bundle)
    tracker.set_teams("KC", "BUF")
    assert tracker.predict_next_play(3, 7, 35, 110, 4, -4)["prediction"] == "RUN"
