import pytest
from dataclasses import replace
from types import SimpleNamespace
from fastapi.testclient import TestClient

from app.db.models import User
from tests.conftest import CSRF_HEADERS, create_game, prediction_payload, register


@pytest.fixture
def owner_and_other(app, client):
    owner = register(client, "owner@example.com")
    game_id = create_game(client, "KC", "BUF")
    with TestClient(app, headers=CSRF_HEADERS) as other:
        other_user = register(other, "other@example.com")
        yield client, other, owner, other_user, game_id


@pytest.mark.parametrize("path", ["/state", "/pending", "/play-log", "/summary"])
def test_other_user_cannot_read_live_game(owner_and_other, path):
    owner, other, _, _, game_id = owner_and_other
    assert owner.get(path, params={"game_id": game_id}).status_code == 200
    assert other.get(path, params={"game_id": game_id}).status_code == 404


@pytest.mark.parametrize("path", ["/predict", "/predict-tier2", "/log-play", "/new-drive", "/games"])
def test_other_user_cannot_mutate_or_claim_live_game(owner_and_other, path):
    owner, other, _, _, game_id = owner_and_other
    payload = {"game_id": game_id}
    if path.startswith("/predict"):
        payload = prediction_payload(game_id)
    elif path == "/log-play":
        payload.update(actual_play_type="PASS", yards_gained=7)
    elif path == "/games":
        payload.update(title="Stolen", game_state={})
    assert other.post(path, json=payload).status_code == 404
    assert owner.get("/state", params={"game_id": game_id}).json()["state_version"] == 1


def test_saved_games_are_private_and_user_id_cannot_override_identity(owner_and_other):
    owner, other, owner_user, other_user, game_id = owner_and_other
    saved = owner.post("/games", json={"game_id": game_id, "title": "Private", "game_state": {}})
    assert saved.status_code == 201
    saved_id = saved.json()["game_id"]
    assert len(owner.get("/games").json()) == 1
    assert other.get("/games", params={"user_id": owner_user["user_id"]}).json() == []
    assert other.post("/games/load", json={"game_id": saved_id}).status_code == 404
    assert other.delete(f"/games/{saved_id}", params={"user_id": owner_user["user_id"]}).status_code == 404
    assert other.post("/set-teams", json={"offense": "MIN", "defense": "DET", "user_id": owner_user["user_id"]}).status_code == 422
    assert other.post("/games/load", json={"game_id": saved_id, "user_id": owner_user["user_id"]}).status_code == 422
    assert other.get("/me/subscription", params={"user_id": owner_user["user_id"]}).json()["user_id"] == other_user["user_id"]
    assert owner.delete(f"/games/{saved_id}").status_code == 200


def test_guest_game_needs_secret_and_claim_invalidates_guest_access(client, app):
    response = client.post("/set-teams", json={"offense": "MIN", "defense": "DET"})
    assert response.status_code == 201
    game = response.json()
    params = {"game_id": game["game_id"]}
    token_header = {"X-Game-Token": game["guest_token"]}
    assert client.get("/state", params=params).status_code == 404
    assert client.get("/state", params=params, headers={"X-Game-Token": "wrong"}).status_code == 404
    assert client.get("/state", params=params, headers=token_header).status_code == 200
    assert client.post("/predict", json=prediction_payload(game["game_id"]), headers=token_header).status_code == 200
    payload = {"game_id": game["game_id"], "title": "Guest game", "game_state": {}}
    assert client.post("/games", json=payload, headers=token_header).status_code == 401
    register(client)
    assert client.post("/games", json=payload).status_code == 404
    assert client.post("/games", json=payload, headers=token_header).status_code == 201
    assert client.get("/state", params=params).status_code == 200
    with TestClient(app) as guest:
        assert guest.get("/state", params=params, headers=token_header).status_code == 404


def test_tier2_uses_verified_users_current_subscription(owner_and_other, app, monkeypatch):
    owner, other, owner_user, _, game_id = owner_and_other
    with app.state.session_factory() as db:
        user = db.get(User, owner_user["user_id"])
        user.subscription_status = "active"
        user.tier = "tier2"
        db.commit()
    monkeypatch.setattr("game_tracker.GameTracker.predict_next_play_tier2", lambda self, **kwargs: {"tier": 2})
    assert owner.post("/predict-tier2", json=prediction_payload(game_id)).status_code == 200
    other_game = create_game(other, "GB", "CHI")
    assert other.post("/predict-tier2", json=prediction_payload(other_game)).status_code == 403
    forged = {**prediction_payload(other_game), "user_id": owner_user["user_id"]}
    assert other.post("/predict-tier2", json=forged).status_code == 422
    with app.state.session_factory() as db:
        db.get(User, owner_user["user_id"]).subscription_status = "canceled"
        db.commit()
    assert owner.post("/predict-tier2", json=prediction_payload(game_id)).status_code == 403


def test_billing_rejects_anonymous_and_forged_user_ids(client):
    assert client.post("/create-checkout-session", json={}).status_code == 401
    assert client.get("/me/subscription", params={"user_id": 1}).status_code == 401
    register(client)
    assert client.post("/create-checkout-session", json={"user_id": 999}).status_code == 422


def test_checkout_uses_verified_account_for_stripe_metadata(client, app, monkeypatch):
    user = register(client)
    app.state.settings = replace(app.state.settings, stripe_secret_key="test-placeholder", stripe_price_id_tier2="price_example")
    calls = {}

    def create_customer(**kwargs):
        calls["customer"] = kwargs
        return SimpleNamespace(id="cus_example")

    def create_checkout(**kwargs):
        calls["checkout"] = kwargs
        return SimpleNamespace(url="https://checkout.example/test")

    monkeypatch.setattr("stripe.Customer.create", create_customer)
    monkeypatch.setattr("stripe.checkout.Session.create", create_checkout)
    response = client.post("/create-checkout-session", json={})
    assert response.status_code == 200
    assert calls["customer"]["metadata"]["user_id"] == str(user["user_id"])
    assert calls["checkout"]["client_reference_id"] == str(user["user_id"])
