import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.state import state, x_to_angle

client = TestClient(app)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clock():
    fake = FakeClock()
    state.reset(fake)
    yield fake


def see(x, fingers=0, pinch=0.0):
    return client.post("/hand", json={"hand": True, "x": x, "fingers": fingers, "pinch": pinch})


def test_starts_stale_dark_and_centred():
    body = client.get("/hand").json()
    assert body == body | {"angle": 90, "leds": 0, "brightness": 0, "stale": True}


@pytest.mark.parametrize("x, angle", [(0.0, 0), (0.1, 0), (0.5, 90), (0.9, 180), (1.0, 180)])
def test_left_edge_is_0_right_edge_is_180(x, angle):
    assert x_to_angle(x) == angle


def test_invert_flips_direction(monkeypatch):
    monkeypatch.setattr(config, "INVERT", True)
    assert x_to_angle(0.0) == 180
    assert x_to_angle(1.0) == 0


@pytest.mark.parametrize("x", [-0.1, 1.5])
def test_refuses_x_outside_picture(x):
    assert client.post("/hand", json={"hand": True, "x": x}).status_code == 422


def test_refuses_hand_without_x():
    assert client.post("/hand", json={"hand": True}).status_code == 422


def test_refuses_fingers_outside_0_to_5():
    assert client.post("/hand", json={"hand": True, "x": 0.5, "fingers": 6}).status_code == 422


def test_first_sighting_points_straight_at_hand():
    assert see(0.9).json()["angle"] == 180


def test_smoothing_moves_gradually(clock):
    see(0.1)  # 0 degrees
    clock.now += 0.033  # one frame later the hand is at the far right
    angle = see(0.9).json()["angle"]
    assert 0 < angle < 180
    for _ in range(60):  # two seconds of steady hand
        clock.now += 0.033
        angle = see(0.9).json()["angle"]
    assert angle == 180


def test_still_hand_jitter_does_not_move_servo(clock):
    see(0.5)
    start = client.get("/hand").json()["angle"]
    for i in range(100):  # +-1% of the picture is ~2 degrees of noise
        clock.now += 0.033
        see(0.5 + (0.01 if i % 2 else -0.01))
    assert client.get("/hand").json()["angle"] == start


def test_fingers_mode_counts(clock):
    body = see(0.5, fingers=3).json()
    assert (body["leds"], body["brightness"], body["mode"]) == (3, 255, "fingers")


def test_pinch_mode_dims_all_five():
    client.post("/mode", json={"mode": "pinch"})
    closed = see(0.5, pinch=0.1).json()
    open_ = see(0.5, pinch=1.2).json()
    assert (closed["leds"], closed["brightness"]) == (5, 0)
    assert (open_["leds"], open_["brightness"]) == (5, 255)


def test_refuses_unknown_mode():
    assert client.post("/mode", json={"mode": "disco"}).status_code == 422


def test_lost_hand_turns_leds_off_but_servo_holds(clock):
    see(0.9, fingers=5)
    body = client.post("/hand", json={"hand": False}).json()
    assert (body["angle"], body["leds"], body["hand"]) == (180, 0, False)


def test_silent_camera_goes_stale(clock):
    see(0.9, fingers=4)
    clock.now += config.STALE_SECONDS + 0.1
    body = client.get("/hand").json()
    assert (body["stale"], body["leds"], body["angle"]) == (True, 0, 180)


def test_esp32_style_parse():
    """The chip does indexOf("\"angle\":") then toInt() on what follows."""
    see(0.9, fingers=2)
    text = client.get("/hand").text
    assert text.startswith('{"angle":180,"leds":2,"brightness":255,')


def test_history_records_angle():
    see(0.1)
    see(0.9)
    items = client.get("/history?limit=1").json()
    assert len(items) == 1 and items[0]["x"] == 0.9


def test_api_key_required_when_set(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "secret")
    assert see(0.5).status_code == 401
    assert client.post("/mode", json={"mode": "pinch"}).status_code == 401
    ok = client.post("/hand", json={"hand": False}, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200
    assert client.get("/hand").status_code == 200  # the board reads without a key


def test_simulator_page_served():
    r = client.get("/")
    assert r.status_code == 200 and "/hand" in r.text
