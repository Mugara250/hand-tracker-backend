# Hand Tracker Backend (the cloud tier)

The brain (laptop + webcam) `POST`s where the hand is; the body (ESP32) `GET`s where to point.
The brain only reports what it sees. **The backend decides:** it maps x to an angle,
smooths it, ignores small jitter and picks the LEDs.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Fake body in the browser: http://127.0.0.1:8000/ (servo dial + 5 LEDs, polls like the ESP32)
- API docs: http://127.0.0.1:8000/docs

## API

| Method | Path       | Body / response |
|--------|------------|-----------------|
| POST   | `/hand`    | `{"hand": bool, "x"?: 0-1, "fingers"?: 0-5, "pinch"?: 0-5}`; `x` required when `hand` is true; 422 otherwise. Returns the snapshot. |
| GET    | `/hand`    | `{"angle":0-180,"leds":0-5,"brightness":0-255,"mode","hand","stale"}` |
| POST   | `/mode`    | `{"mode": "fingers" \| "pinch"}` |
| GET    | `/history?limit=50` | recent reports with the angle chosen for each |
| GET    | `/health`  | `{"ok": true, "service": "hand-tracker"}` |

**The board's whole job:** `servo.write(angle)`, then for LED `i` in 0..4:
`analogWrite(pin[i], i < leds ? brightness : 0)`.

- `fingers` mode: `leds` = fingers up, `brightness` = 255
- `pinch` mode: `leds` = 5, `brightness` = how wide thumb and index are apart

## The rules (all env vars, see `app/config.py`)

| Rule | Default | What it does |
|------|---------|--------------|
| `EDGE_MARGIN` | 0.1 | x ≤ 0.1 → 0°, x ≥ 0.9 → 180°, clamped; never outside 0..180 |
| `SMOOTH_SECONDS` | 0.15 | time-based smoothing (same feel at any frame rate) |
| `DEADBAND_DEGREES` | 3 | servo moves only if the change is ≥ 3°: no shiver |
| `INVERT` | 0 | `1` if the servo turns the wrong way |
| `PINCH_MIN` / `PINCH_MAX` | 0.15 / 1.0 | pinch range mapped to brightness 0..255 |
| `STALE_SECONDS` | 2 | brain silent this long → LEDs off |
| `DEFAULT_MODE` | fingers | LED mode at start |

## How it fails (know it before they find it)

- **No hand in view** → LEDs off, the servo **holds** its last angle (no snapping to 0).
- **Brain stops / laptop WiFi drops** → after 2 s `stale: true`, LEDs off, servo holds.
- **Two hands** → MediaPipe tracks only one (`max_num_hands=1`); it may jump between them.
- **Bad light / backlight** → detection flickers between hand and no hand, so the LEDs blink.
- **Hand at the very edge** → MediaPipe loses the hand before the palm reaches the edge, which is why `EDGE_MARGIN` exists.
- **Slow network (hosted)** → the servo lags; smoothing hides small delays, not big ones.
- **Backend down** → the board reads an error code and should turn its LEDs off.

## Testing without an ESP32

```bash
pytest -q                                # unit tests
python tools/fake_esp32.py               # terminal 2: polls 5x/s, prints servo.write(...)
python tools/fake_brain.py               # terminal 3: fake hand sweeps left -> right
python tools/fake_brain.py --still       # still hand with noise: angle must not change
```

## Testing with the real camera

WSL cannot see the webcam, so the brain runs on **Windows** (Python 3.10-3.12):

```powershell
pip install -r requirements-vision.txt
python tools\vision.py            # backend running in WSL is reachable at 127.0.0.1:8000
```

Keep http://127.0.0.1:8000/ open beside it to watch the fake body follow your hand.
In the camera window: **M** switches LED mode, **Q** quits.

## Hosting on Render (no shared network needed)

1. Push this folder to a **private** GitHub repo.
2. On render.com: New > Blueprint > pick the repo (uses `render.yaml`).
3. Copy the service URL and the generated `API_KEY` (Environment tab).
4. Brain: `python tools/vision.py --url https://<app>.onrender.com/hand --key <API_KEY>`
5. Body: set `BACKEND_URL = "https://<app>.onrender.com/hand"` in the sketch.
