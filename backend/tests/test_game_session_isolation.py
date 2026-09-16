from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app
from tests.conftest import TEST_JWT_SECRET, create_game, prediction_payload


def test_two_games_do_not_share_tracker_state(client):
    chiefs_game = create_game(client, "KC", "BUF")
    packers_game = create_game(client, "GB", "CHI")

    prediction = client.post("/predict", json=prediction_payload(chiefs_game))
    assert prediction.status_code == 200
    logged = client.post(
        "/log-play",
        json={
            "game_id": chiefs_game,
            "actual_play_type": "PASS",
            "yards_gained": 8,
        },
    )
    assert logged.status_code == 200

    chiefs_state = client.get("/state", params={"game_id": chiefs_game}).json()
    packers_state = client.get("/state", params={"game_id": packers_game}).json()
    packers_pending = client.get(
        "/pending", params={"game_id": packers_game}
    ).json()

    assert chiefs_state["offense"] == "KC"
    assert chiefs_state["game_total_plays"] == 1
    assert chiefs_state["game_total_passes"] == 1
    assert packers_state["offense"] == "GB"
    assert packers_state["defense"] == "CHI"
    assert packers_state["game_total_plays"] == 0
    assert packers_pending == {}


def test_separate_api_instances_share_database_state(tmp_path, model_bundle):
    database_path = tmp_path / "shared.db"
    settings = Settings(database_url=f"sqlite+pysqlite:///{database_path}", jwt_secret_key=TEST_JWT_SECRET)

    first_app = create_app(
        settings=settings,
        model_bundle=model_bundle,
        create_tables=True,
    )
    with TestClient(first_app) as first_client:
        game_id = create_game(first_client, "MIN", "DET")
        prediction = first_client.post("/predict", json=prediction_payload(game_id))
        assert prediction.status_code == 200
        authorization = first_client.headers["Authorization"]

    second_app = create_app(settings=settings, model_bundle=model_bundle)
    with TestClient(second_app) as second_client:
        second_client.headers["Authorization"] = authorization
        state = second_client.get("/state", params={"game_id": game_id})
        pending = second_client.get("/pending", params={"game_id": game_id})

    assert state.status_code == 200
    assert state.json()["offense"] == "MIN"
    assert pending.status_code == 200
    assert pending.json()["predicted_play_type"] == "PASS"
