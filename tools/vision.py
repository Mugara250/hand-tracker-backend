"""The brain: webcam -> MediaPipe -> where the hand is -> POST to the backend.

Run on Windows (WSL cannot see the webcam) with Python 3.10-3.12:
  python vision.py                                   # backend on this laptop
  python vision.py --url http://<ip>:8000/hand       # backend elsewhere
  python vision.py --url https://<app>.onrender.com/hand --key <API_KEY>   # hosted

The brain only reports what it sees (hand x, fingers up, pinch). The backend
decides the servo angle, smooths it and picks the LEDs; its answer is drawn on
the video so you can watch the whole chain. Keys in the window: M switches the
LED mode (fingers / pinch), Q quits.
"""

import argparse
import math
import sys
import threading
import time

import cv2
import mediapipe as mp
import requests

FINGERS = [(8, 6), (12, 10), (16, 14), (20, 18)]  # index..little: (tip, middle joint)

# The thumb is up when its tip is clearly farther from the little finger's base (17)
# than the thumb's own base (2) is. Raise if a folded thumb still counts.
THUMB_RATIO = 1.2

PALM = 9  # base of the middle finger: the steadiest "where is the hand" point


def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


class Sender:
    """Posts the latest reading on a background thread; the camera loop never waits."""

    HEARTBEAT = 0.5  # resend an unchanged reading this often (stale rule is 2 s)

    def __init__(self, url, key):
        self.url = url
        self.session = requests.Session()  # keeps the connection open between posts
        if key:
            self.session.headers["X-API-Key"] = key
        self.latest = None
        self.reply = None  # the backend's last answer: what the board will do
        self.online = True
        self.wake = threading.Event()
        self.stopped = False
        threading.Thread(target=self._run, daemon=True).start()

    def update(self, payload):
        if payload != self.latest:
            self.latest = payload
            self.wake.set()  # send a change right away

    def set_mode(self, mode):
        try:
            self.session.post(self.url.rsplit("/", 1)[0] + "/mode",
                              json={"mode": mode}, timeout=5).raise_for_status()
            print("LED mode:", mode)
        except requests.RequestException as e:
            print("Could not switch mode:", e)

    def stop(self):
        self.stopped = True
        self.wake.set()

    def _run(self):
        while not self.stopped:
            self.wake.wait(timeout=self.HEARTBEAT)
            self.wake.clear()
            payload = self.latest
            if payload is None or self.stopped:
                continue
            try:
                r = self.session.post(self.url, json=payload, timeout=5)
                r.raise_for_status()
                self.reply = r.json()
                if not self.online:
                    print("Backend reachable again.")
                self.online = True
            except requests.HTTPError as e:
                if self.online:
                    code = e.response.status_code
                    hint = {401: "wrong or missing --key", 404: "wrong URL path",
                            422: "bad data"}.get(code, "")
                    print(f"Backend refused the reading: HTTP {code} {hint}")
                self.online = False
            except requests.RequestException:
                if self.online:
                    print("Backend unavailable at", self.url,
                          "- is it running? (a sleeping free server takes ~1 min)")
                self.online = False


def draw_servo(frame, angle):
    """A small dial in the corner showing where the backend says the servo points."""
    h, w = frame.shape[:2]
    cx, cy, r = w - 90, 100, 70
    cv2.ellipse(frame, (cx, cy), (r, r), 0, 180, 360, (200, 200, 200), 2)
    # 0 deg points left, 90 up, 180 right (image y grows downwards).
    tip = (int(cx + r * math.cos(math.radians(180 + angle))),
           int(cy + r * math.sin(math.radians(180 + angle))))
    cv2.line(frame, (cx, cy), tip, (0, 200, 255), 4)
    cv2.putText(frame, f"servo {angle}", (cx - 50, cy + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)


def draw_leds(frame, leds, brightness):
    for i in range(5):
        on = i < leds
        level = brightness if on else 0
        colour = (0, int(80 + 175 * level / 255), int(80 + 175 * level / 255)) if on else (60, 60, 60)
        cv2.circle(frame, (30 + i * 40, frame.shape[0] - 30), 14, colour, -1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000/hand")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--key", default="", help="API key if the backend has API_KEY set")
    args = p.parse_args()
    if not args.url.rstrip("/").endswith("/hand"):
        args.url = args.url.rstrip("/") + "/hand"

    # On Windows the default camera backend (MSMF) often stalls; DirectShow is reliable.
    if sys.platform == "win32":
        camera = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    else:
        camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        print("Cannot open webcam. Close other camera apps (Teams, Zoom, Camera) or try --camera 1.")
        return
    print("Camera opened. Sending to", args.url)

    hands_api = mp.solutions.hands
    drawing = mp.solutions.drawing_utils
    sender = Sender(args.url, args.key)
    failed_reads = 0
    window = "Hand tracker brain - M mode, Q quit"
    first_frame = True

    with hands_api.Hands(max_num_hands=1, min_detection_confidence=0.6,
                         min_tracking_confidence=0.6) as detector:
        while True:
            ok, frame = camera.read()
            if not ok:
                failed_reads += 1
                if failed_reads == 1:
                    print("Camera gave no image, retrying...")
                if failed_reads > 100:
                    print("Camera never sent an image. Check Windows Settings > Privacy > Camera "
                          "(allow desktop apps), close other camera apps, or try --camera 1.")
                    break
                time.sleep(0.05)
                continue
            failed_reads = 0
            frame = cv2.flip(frame, 1)  # mirror: move your hand right, it moves right on screen
            h, w = frame.shape[:2]
            result = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            if result.multi_hand_landmarks:
                hand = result.multi_hand_landmarks[0]
                pts = hand.landmark
                wrist = pts[0]

                x = max(0.0, min(1.0, pts[PALM].x))
                thumb_up = distance(pts[4], pts[17]) > THUMB_RATIO * distance(pts[2], pts[17])
                up = [thumb_up] + [distance(pts[t], wrist) > distance(pts[m], wrist)
                                   for t, m in FINGERS]
                # Pinch relative to hand size, so it works near or far from the camera.
                pinch = distance(pts[4], pts[8]) / max(distance(pts[0], pts[9]), 0.001)

                payload = {"hand": True, "x": round(x, 3), "fingers": sum(up),
                           "pinch": round(min(pinch, 5.0), 2)}
                drawing.draw_landmarks(frame, hand, hands_api.HAND_CONNECTIONS)
                px = int(x * w)
                cv2.line(frame, (px, 0), (px, h), (0, 255, 0), 1)
                cv2.putText(frame, f"x {x:.2f}  fingers {sum(up)}  pinch {pinch:.2f}", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            else:
                payload = {"hand": False}
                cv2.putText(frame, "No hand", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            sender.update(payload)

            reply = sender.reply
            if reply:
                draw_servo(frame, reply["angle"])
                draw_leds(frame, reply["leds"], reply["brightness"])
                cv2.putText(frame, f"LED mode: {reply['mode']} (M to switch)", (20, 75),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            if not sender.online:
                cv2.putText(frame, "Backend unavailable", (20, 110),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            cv2.imshow(window, frame)
            if first_frame:
                # Bring the window to the front so it does not hide behind VS Code.
                cv2.setWindowProperty(window, cv2.WND_PROP_TOPMOST, 1)
                print("Window open. M switches LED mode, Q quits.")
                first_frame = False
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("m"):
                current = reply["mode"] if reply else "fingers"
                sender.set_mode("pinch" if current == "fingers" else "fingers")

    sender.stop()
    camera.release()
    cv2.destroyAllWindows()
    print("Stopped.")


if __name__ == "__main__":
    main()
