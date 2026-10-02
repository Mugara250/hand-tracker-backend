"""Stand-in for the webcam brain: POSTs a pretend hand to the backend.

  python tools/fake_brain.py              # sweep left -> right -> left with a shaky hand, then go silent
  python tools/fake_brain.py --still      # a still hand with camera noise: the servo must not shiver
"""

import argparse
import math
import random
import time

import requests

HEADERS: dict = {}


def post(url: str, payload: dict) -> None:
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=5)
        s = r.json() if r.ok else r.text
        print(f"POST {payload} -> {r.status_code} angle={s['angle'] if r.ok else s}")
    except requests.RequestException as e:
        print(f"backend unreachable: {e}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000/hand")
    p.add_argument("--still", action="store_true")
    p.add_argument("--key", default="", help="API key if the backend has API_KEY set")
    args = p.parse_args()
    if args.key:
        HEADERS["X-API-Key"] = args.key

    fps = 20
    if args.still:
        for _ in range(fps * 5):
            post(args.url, {"hand": True, "x": round(0.5 + random.uniform(-0.01, 0.01), 3),
                            "fingers": 2, "pinch": 0.5})
            time.sleep(1 / fps)
    else:
        for i in range(fps * 8):  # one full sweep there and back in 8 s
            x = 0.5 - 0.5 * math.cos(2 * math.pi * i / (fps * 8))
            x = min(1, max(0, x + random.uniform(-0.01, 0.01)))
            post(args.url, {"hand": True, "x": round(x, 3), "fingers": int(x * 5.99),
                            "pinch": round(x * 1.2, 2)})
            time.sleep(1 / fps)
        post(args.url, {"hand": False})
    print("Brain going silent. The body's LEDs should go dark within 2 s; the servo holds.")


if __name__ == "__main__":
    main()
