"""The one truth the backend remembers, and the rules that turn a hand into motion and light."""

import math
import threading
import time
from collections import deque
from datetime import datetime

from app import config
from app.schemas import HistoryItem, Mode, Report, Snapshot


def x_to_angle(x: float) -> float:
    """Left edge -> 0, right edge -> 180, never anything outside that."""
    span = 1 - 2 * config.EDGE_MARGIN
    t = (x - config.EDGE_MARGIN) / span if span > 0 else 0.5
    t = max(0.0, min(1.0, t))
    if config.INVERT:
        t = 1 - t
    return config.ANGLE_MIN + t * (config.ANGLE_MAX - config.ANGLE_MIN)


def pinch_to_brightness(pinch: float) -> int:
    span = max(config.PINCH_MAX - config.PINCH_MIN, 0.001)
    return int(255 * max(0.0, min(1.0, (pinch - config.PINCH_MIN) / span)))


class State:
    def __init__(self, clock=time.monotonic) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self.mode: Mode = config.DEFAULT_MODE
        self.hand = False
        self.fingers = 0
        self.brightness = 0
        self.smooth: float | None = None  # smoothed angle, before the deadband
        self.angle = (config.ANGLE_MIN + config.ANGLE_MAX) // 2  # start pointing ahead
        self.last_hand = 0.0  # when the smoothed angle was last updated
        self.updated = 0.0  # monotonic; 0 means "never reported", so stale at start
        self.history: deque[HistoryItem] = deque(maxlen=config.HISTORY_SIZE)

    def apply(self, report: Report) -> None:
        with self._lock:
            now = self._clock()
            self.hand = report.hand
            self.fingers = report.fingers
            self.brightness = pinch_to_brightness(report.pinch)

            if report.hand:
                target = x_to_angle(report.x)
                if self.smooth is None:
                    self.smooth = target
                else:
                    # Time-based smoothing: same feel at 10 or 30 reports a second.
                    dt = now - self.last_hand
                    alpha = 1 - math.exp(-dt / max(config.SMOOTH_SECONDS, 1e-6))
                    self.smooth += alpha * (target - self.smooth)
                self.last_hand = now

                rounded = round(self.smooth)
                at_end = rounded in (config.ANGLE_MIN, config.ANGLE_MAX)
                if abs(rounded - self.angle) >= config.DEADBAND_DEGREES or at_end:
                    self.angle = rounded
            # No hand: the servo holds where it last pointed instead of snapping away.

            self.updated = now
            self.history.append(
                HistoryItem(
                    at=datetime.now().isoformat(timespec="milliseconds"),
                    hand=report.hand,
                    x=report.x,
                    fingers=report.fingers,
                    pinch=report.pinch,
                    angle=self.angle,
                )
            )

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            self.mode = mode

    def snapshot(self) -> Snapshot:
        with self._lock:
            stale = self._clock() - self.updated > config.STALE_SECONDS
            lit = self.hand and not stale
            if self.mode == "fingers":
                leds, brightness = self.fingers, 255
            else:
                leds, brightness = 5, self.brightness
            return Snapshot(
                angle=self.angle,
                leds=leds if lit else 0,
                brightness=brightness if lit else 0,
                mode=self.mode,
                hand=lit,
                stale=stale,
            )

    def recent(self, limit: int) -> list[HistoryItem]:
        with self._lock:
            return list(self.history)[-limit:]

    def reset(self, clock=time.monotonic) -> None:
        self.__init__(clock)


state = State()
