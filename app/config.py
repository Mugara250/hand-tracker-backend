"""Runtime settings, overridable with environment variables. These are my rules."""

import os

# Seconds of camera silence before the backend says "stale": LEDs off, servo holds.
STALE_SECONDS = float(os.getenv("STALE_SECONDS", "2"))

# The hand's centre rarely reaches the very edge of the picture, so the outer
# EDGE_MARGIN of each side already counts as the edge: x <= margin -> 0 degrees,
# x >= 1 - margin -> 180 degrees. Nothing outside 0..180 is ever sent.
EDGE_MARGIN = float(os.getenv("EDGE_MARGIN", "0.1"))
ANGLE_MIN = 0
ANGLE_MAX = 180

# Set to 1 if the servo turns the wrong way because of how it is mounted.
INVERT = os.getenv("INVERT", "0") == "1"

# Smoothing: the angle covers ~63% of the way to the hand in SMOOTH_SECONDS.
# Bigger = calmer but laggier.
SMOOTH_SECONDS = float(os.getenv("SMOOTH_SECONDS", "0.15"))

# Anti-shiver: the servo only moves when the smoothed angle is this many degrees
# away from where it already is. A still hand jitters 1-2 degrees; this hides it.
DEADBAND_DEGREES = int(os.getenv("DEADBAND_DEGREES", "3"))

# Pinch = thumb-to-index distance divided by palm size. Below PINCH_MIN is
# "closed" (brightness 0), above PINCH_MAX is "wide open" (brightness 255).
PINCH_MIN = float(os.getenv("PINCH_MIN", "0.15"))
PINCH_MAX = float(os.getenv("PINCH_MAX", "1.0"))

# LED mode at start: "fingers" (count by fingers) or "pinch" (brightness by pinch).
DEFAULT_MODE = os.getenv("DEFAULT_MODE", "fingers")

# How many reports to keep in memory for GET /history.
HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "500"))

# If set, POST requests need the header "X-API-Key: <value>". Leave empty on a LAN.
API_KEY = os.getenv("API_KEY", "")
