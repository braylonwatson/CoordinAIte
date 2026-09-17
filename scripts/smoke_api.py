"""Exercise model inference against a disposable CI API, without creating accounts."""
import argparse
import json
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("origin")
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
    prediction = request("/predict", {
        "game_id": game["game_id"], "down": 1, "ydstogo": 10,
        "yardline_100": 50, "game_seconds_remaining": 900,
        "qtr": 1, "score_differential": 0,
    }, headers)
    assert prediction["game_id"] == game["game_id"]
    request("/log-play", {
        "game_id": game["game_id"], "actual_play_type": "PASS", "yards_gained": 8,
    }, headers)
    state = request("/state?game_id=" + game["game_id"], headers=headers)
    assert state["game_total_plays"] == 1
    print("API readiness, model inference, and persisted play smoke checks passed.")


if __name__ == "__main__":
    main()
