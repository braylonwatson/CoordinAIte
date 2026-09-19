from dataclasses import replace
from time import sleep

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.api.routes import realtime
from app.factory import create_app
from tests.conftest import CSRF_HEADERS, TEST_JWT_SECRET, create_game, prediction_payload, register


ORIGIN = {"origin": "http://localhost:3000"}


@pytest.fixture
def live_client(app):
    app.state.settings = replace(app.state.settings, realtime_enabled=True)
    with TestClient(app, headers=CSRF_HEADERS) as client:
        yield client


def command(client, game_id, **overrides):
    return {
        "id": "prediction-1", "type": "predict", "payload": prediction_payload(game_id),
        "access_token": client.headers.get("Authorization", "").removeprefix("Bearer ") or None,
        **overrides,
    }


def test_disabled_and_untrusted_origin_are_rejected(client, live_client):
    # Both clients share the fixture app; explicitly disable then restore it.
    app = client.app
    app.state.settings = replace(app.state.settings, realtime_enabled=False)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/predictions", headers=ORIGIN):
            pass
    app.state.settings = replace(app.state.settings, realtime_enabled=True)
    for headers in ({}, {"origin": "https://attacker.example"}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/predictions", headers=headers):
                pass


def test_websocket_prediction_can_be_logged_over_rest(live_client):
    client = live_client
    game = create_game(client, "KC", "BUF")
    with client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
        socket.send_json(command(client, game))
        result = socket.receive_json()
        assert result["status"] == 200
        assert result["data"]["state_version"] == 2
        assert result["data"]["pending"]["predicted_play_type"] == "PASS"
        assert set(result["data"]["timing_ms"]) == {"state_load", "inference", "persist", "prediction_total", "command_total"}
        assert client.get("/pending", params={"game_id": game}).json() == result["data"]["pending"]
        logged = client.post("/log-play", json={"game_id": game, "actual_play_type": "PASS", "yards_gained": 8})
        assert logged.status_code == 200
        socket.send_json(command(client, game, id="prediction-2"))
        assert socket.receive_json()["data"]["state_version"] == 4
    assert len(client.get("/play-log", params={"game_id": game}).json()) == 1


def test_logout_revokes_an_open_socket(live_client):
    client = live_client
    game = create_game(client, "KC", "BUF")
    request = command(client, game)
    with client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
        socket.send_json(request)
        assert socket.receive_json()["status"] == 200
        assert client.post("/auth/logout").status_code == 204
        socket.send_json(request)
        assert socket.receive_json()["status"] == 401


def test_ownership_guest_tokens_and_subscription_checks(live_client):
    client = live_client
    owned = create_game(client, "KC", "BUF")
    first = command(client, owned)
    register(client, "other@example.com")
    with client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
        socket.send_json(command(client, owned))
        assert socket.receive_json()["status"] == 404
        socket.send_json({**first, "type": "predict-tier2"})
        assert socket.receive_json()["status"] == 403
        socket.send_json({**first, "access_token": "invalid"})
        assert socket.receive_json()["status"] == 401
    del client.headers["Authorization"]
    guest = client.post("/set-teams", json={"offense": "MIN", "defense": "DET"}).json()
    with client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
        for token, status in [(None, 404), ("wrong", 404), (guest["guest_token"], 200)]:
            socket.send_json(command(client, guest["game_id"], guest_token=token))
            assert socket.receive_json()["status"] == status


def test_malformed_messages_do_not_leak_credentials_or_mutate_state(live_client):
    game = create_game(live_client, "KC", "BUF")
    with live_client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
        for raw in ("{", "[]", '{"id":"bad","access_token":"private-value"}'):
            socket.send_text(raw)
            response = socket.receive_json()
            assert response["status"] == 422
            assert "private-value" not in str(response)
        socket.send_json(command(live_client, game))
        assert socket.receive_json()["data"]["state_version"] == 2


def test_invalid_messages_cannot_keep_an_unauthenticated_socket_alive(live_client, monkeypatch):
    monkeypatch.setattr(realtime, "FIRST_COMMAND_TIMEOUT", 0.2)
    with live_client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(6):
                socket.send_text("{")
                assert socket.receive_json()["status"] == 422
                sleep(0.06)
        assert closed.value.code == 1008


def test_binary_and_oversized_messages_close_without_mutating(live_client):
    game = create_game(live_client, "KC", "BUF")
    for binary, payload, code in [(True, b"not-text", 1003), (False, "x" * 16385, 1009)]:
        with live_client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
            if binary:
                socket.send_bytes(payload)
            else:
                socket.send_text(payload)
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == code
    assert live_client.get("/pending", params={"game_id": game}).json() == {}


def test_restart_and_second_worker_observe_committed_socket_state(tmp_path, model_bundle):
    settings = Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'shared.db'}",
                        jwt_secret_key=TEST_JWT_SECRET, realtime_enabled=True)
    first = create_app(settings=settings, model_bundle=model_bundle, create_tables=True)
    second = create_app(settings=settings, model_bundle=model_bundle)
    with TestClient(first, headers=CSRF_HEADERS) as client:
        game = create_game(client, "KC", "BUF")
        authorization = client.headers["Authorization"]
        with client.websocket_connect("/ws/predictions", headers=ORIGIN) as socket:
            socket.send_json(command(client, game))
            assert socket.receive_json()["status"] == 200
    with TestClient(second, headers={"Authorization": authorization}) as client:
        assert client.get("/pending", params={"game_id": game}).json()["predicted_play_type"] == "PASS"
