"""Exercise model inference against a disposable CI API, without creating accounts."""
import argparse
import json
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("origin")
    parser.add_argument("--ws-url", help="Optional direct WebSocket endpoint to verify")
    parser.add_argument("--ws-origin", default="http://localhost:3000")
    args = parser.parse_args()
    origin = args.origin.rstrip("/")

    def request(path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            origin + path, data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    assert request("/health/ready")["status"] == "ready"
    game = request("/set-teams", {"offense": "KC", "defense": "BUF"})
    headers = {"X-Game-Token": game["guest_token"]}
    payload = {
        "game_id": game["game_id"], "down": 1, "ydstogo": 10,
        "yardline_100": 50, "game_seconds_remaining": 900,
        "qtr": 1, "score_differential": 0,
    }
    prediction = request("/predict", payload, headers)
    assert prediction["game_id"] == game["game_id"]
    if args.ws_url:
        from websockets.sync.client import connect
        with connect(args.ws_url, origin=args.ws_origin, open_timeout=10) as socket:
            socket.send(json.dumps({
                "id": "smoke-live", "type": "predict", "payload": payload,
                "guest_token": game["guest_token"],
            }))
            reply = json.loads(socket.recv(timeout=20))
            assert reply["id"] == "smoke-live" and reply["status"] == 200
            live = reply["data"]
            assert live["state_version"] == prediction["state_version"] + 1
            assert live["pending"] == request("/pending?game_id=" + game["game_id"], headers=headers)
        print("WebSocket upgrade, prediction, and HTTP state readback passed.")
    request("/log-play", {
        "game_id": game["game_id"], "actual_play_type": "PASS", "yards_gained": 8,
    }, headers)
    state = request("/state?game_id=" + game["game_id"], headers=headers)
    assert state["game_total_plays"] == 1
    print("API readiness, model inference, and persisted play smoke checks passed.")


if __name__ == "__main__":
    main()
