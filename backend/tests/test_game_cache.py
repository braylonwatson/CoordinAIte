from fastapi.testclient import TestClient

from tests.conftest import CSRF_HEADERS, prediction_payload, register


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.reads = []

    def get(self, key):
        self.reads.append(key)
        return self.values.get(key)

    def setex(self, key, ttl, value):
        assert ttl > 0
        self.values[key] = value


def test_snapshot_hits_and_new_versions_do_not_reuse_old_state(app, client):
    cache = MemoryCache()
    app.state.game_cache = cache
    created = client.post("/set-teams", json={"offense": "KC", "defense": "BUF"}).json()
    game_id = created["game_id"]
    headers = {"X-Game-Token": created["guest_token"]}

    first = client.get("/state", params={"game_id": game_id}, headers=headers).json()
    assert first["state_version"] == 1
    assert len(cache.values) == 1
    second = client.get("/state", params={"game_id": game_id}, headers=headers).json()
    assert second == first
    assert cache.reads[-1] in cache.values

    predicted = client.post("/predict", json=prediction_payload(game_id), headers=headers)
    assert predicted.status_code == 200
    after = client.get("/state", params={"game_id": game_id}, headers=headers).json()
    assert after["state_version"] == 2
    assert cache.reads[-1] != cache.reads[0]
    assert client.get("/pending", params={"game_id": game_id}, headers=headers).json()


def test_cached_guest_state_still_requires_database_ownership(app, client):
    app.state.game_cache = MemoryCache()
    created = client.post("/set-teams", json={"offense": "MIN", "defense": "DET"}).json()
    game_id = created["game_id"]
    headers = {"X-Game-Token": created["guest_token"]}
    assert client.get("/state", params={"game_id": game_id}, headers=headers).status_code == 200
    assert client.get("/state", params={"game_id": game_id}).status_code == 404
    register(client)
    assert client.post("/games", json={"game_id": game_id, "title": "Claimed", "game_state": {}}, headers=headers).status_code == 201
    with TestClient(app, headers=CSRF_HEADERS) as guest:
        assert guest.get("/state", params={"game_id": game_id}, headers=headers).status_code == 404
    assert client.get("/state", params={"game_id": game_id}).status_code == 200


def test_cache_outage_falls_back_to_postgres(app, client):
    class Unavailable:
        def get(self, key):
            from redis.exceptions import ConnectionError
            raise ConnectionError("unavailable")

    app.state.game_cache = Unavailable()
    created = client.post("/set-teams", json={"offense": "KC", "defense": "BUF"}).json()
    response = client.get("/state", params={"game_id": created["game_id"]}, headers={"X-Game-Token": created["guest_token"]})
    assert response.status_code == 200
