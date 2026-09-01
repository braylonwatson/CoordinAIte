from game_tracker import GameTracker

from tests.conftest import prediction_payload


def test_tracker_state_round_trip_preserves_live_tendencies(model_bundle):
    tracker = GameTracker(model_bundle=model_bundle)
    tracker.set_teams("KC", "BUF")
    payload = prediction_payload("unused")
    payload.pop("game_id")
    tracker.predict_next_play(**payload)
    tracker.log_pending_result("PASS", yards_gained=7)

    restored = GameTracker(
        model_bundle=model_bundle,
        state=tracker.export_state(),
    )

    assert restored.offense == "KC"
    assert restored.defense == "BUF"
    assert restored.prev_play_pass == 1
    assert restored.game_total_plays == 1
    assert restored.game_total_passes == 1
    assert restored.play_log == tracker.play_log
    assert restored.pending_play_context is None
