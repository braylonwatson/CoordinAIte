from tests.conftest import prediction_payload


def test_saved_game_restores_a_new_live_session(client):
    signup = client.post(
        "/signup",
        json={
            "username": "Coordinator",
            "email": "coach@example.com",
            "password": "strong-pass",
        },
    )
    assert signup.status_code == 201
    user_id = signup.json()["user_id"]

    created = client.post(
        "/set-teams",
        json={"offense": "KC", "defense": "BUF", "user_id": user_id},
    )
    game_id = created.json()["game_id"]
    assert client.post("/predict", json=prediction_payload(game_id)).status_code == 200
    assert client.post(
        "/log-play",
        json={
            "game_id": game_id,
            "actual_play_type": "PASS",
            "yards_gained": 6,
        },
    ).status_code == 200

    saved = client.post(
        "/games",
        json={
            "user_id": user_id,
            "title": "Chiefs vs Bills",
            "game_id": game_id,
            "game_state": {"offense": "KC", "defense": "BUF"},
        },
    )
    assert saved.status_code == 201

    loaded = client.post(
        "/games/load",
        json={"game_id": saved.json()["game_id"], "user_id": user_id},
    )
    assert loaded.status_code == 200
    resumed_game_id = loaded.json()["game_id"]
    assert resumed_game_id != game_id

    resumed_state = client.get(
        "/state",
        params={"game_id": resumed_game_id},
    )
    assert resumed_state.status_code == 200
    assert resumed_state.json()["game_total_plays"] == 1
    assert resumed_state.json()["game_total_passes"] == 1
