"""Stand-in for the ESP32 body: polls GET /hand 5x/second and 'moves' the servo and LEDs.

Parses the response the way the C++ sketch will (find "angle": and read the
number after it, and the same for leds and brightness), so if this works the
chip will too.

  python tools/fake_esp32.py --url http://<laptop-ip>:8000/hand
"""

import argparse
import time

import requests


def parse_int(body: str, key: str) -> int:
    at = body.find(f'"{key}":')
    if at < 0:
        return 0
    digits = ""
    for ch in body[at + len(key) + 3:]:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits or 0)  # Arduino's toInt() returns 0 on garbage


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000/hand")
    args = p.parse_args()

    shown = None
    while True:
        try:
            r = requests.get(args.url, timeout=5)
            code = r.status_code
        except requests.RequestException:
            code = -1  # what HTTPClient returns when no house is found

        if code == 200:
            angle = min(max(parse_int(r.text, "angle"), 0), 180)
            leds = min(max(parse_int(r.text, "leds"), 0), 5)
            brightness = min(max(parse_int(r.text, "brightness"), 0), 255)
            now = (angle, leds, brightness)
            if now != shown:
                dial = "".join("|" if i == angle // 10 else "-" for i in range(19))
                lights = "".join("●" if i < leds else "○" for i in range(5))
                print(f"servo.write({angle:3d})  [{dial}]   LEDs {lights} pwm {brightness:3d}")
                shown = now
        else:
            print(f"backend error {code}")
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
