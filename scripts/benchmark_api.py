"""Measure HTTP and optional WebSocket latency against a deployed API.

Creates private guest games and repeatedly updates their pending predictions.
Does not touch existing games, log plays, or create user accounts.
Install backend/requirements-dev.txt. Run from a client location of interest.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from time import perf_counter, sleep

import httpx
import numpy as np
from websockets.sync.client import connect


def benchmark_worker(args, transport):
    samples = []
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=20) as client:
        created = client.post("/set-teams", json={"offense": "KC", "defense": "BUF"})
        created.raise_for_status()
        game = created.json()
        payload = {"game_id": game["game_id"], "down": 3, "ydstogo": 7, "yardline_100": 50,
                   "game_seconds_remaining": 900, "qtr": 3, "score_differential": -4}

        def request(index, socket=None):
            started = perf_counter()
            if socket:
                socket.send(json.dumps({"id": str(index), "type": "predict", "payload": payload,
                                        "guest_token": game["guest_token"]}))
                reply = json.loads(socket.recv(timeout=20))
                if reply.get("id") != str(index) or reply.get("status") != 200:
                    raise RuntimeError("WebSocket prediction failed; benchmark aborted")
                data = reply["data"]
            else:
                reply = client.post("/predict", json=payload, headers={"X-Game-Token": game["guest_token"]})
                reply.raise_for_status()
                data = reply.json()
            samples.append({"client_round_trip": (perf_counter() - started) * 1000,
                            **data.get("timing_ms", {})})

        if transport == "websocket":
            with connect(args.ws_url, origin=args.origin, open_timeout=10, max_size=65536) as socket:
                for i in range(args.requests):
                    request(i, socket)
                    # Respect the server's per-connection command-rate limit.
                    # Sleep outside the measured request, at football cadence.
                    if i + 1 < args.requests:
                        sleep(0.15)
        else:
            for i in range(args.requests):
                request(i)
                if i + 1 < args.requests:
                    sleep(0.15)
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--ws-url")
    parser.add_argument("--origin", help="An origin allowed by the API's CORS_ORIGINS")
    parser.add_argument("--requests", type=int, default=30, help="Per connection, per transport")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.requests <= 10000 or not 1 <= args.concurrency <= 20:
        parser.error("requests must be 1..10000 and concurrency 1..20")
    if args.ws_url and not args.origin:
        parser.error("--origin is required with --ws-url")
    results = {"concurrency": args.concurrency, "requests_per_connection": args.requests}
    for transport in (["http", "websocket"] if args.ws_url else ["http"]):
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            runs = list(pool.map(lambda _: benchmark_worker(args, transport), range(args.concurrency)))
        first = [run[0]["client_round_trip"] for run in runs]
        # Report first request separately; handshakes are outside WS request timing.
        samples = [sample for run in runs for sample in run[1:]] or [run[0] for run in runs]
        results[transport] = {
            "first_request_ms": first,
            "warm": {key: {f"p{p}_ms": round(float(np.percentile([s[key] for s in samples], p)), 3)
                           for p in (50, 95, 99)} for key in samples[0]},
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
