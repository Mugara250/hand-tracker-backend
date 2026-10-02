"""The JSON contract shared by the brain (laptop) and the body (ESP32)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["fingers", "pinch"]


class Report(BaseModel):
    """What the brain POSTs: raw observations. The backend decides what they mean.

    `x` is the hand's horizontal position in the (mirrored) picture: 0 = left
    edge, 1 = right edge. It is required when a hand is visible.
    """

    hand: bool
    x: float | None = Field(default=None, ge=0, le=1)
    fingers: int = Field(default=0, ge=0, le=5)
    pinch: float = Field(default=0, ge=0, le=5)

    @model_validator(mode="after")
    def x_needed_with_hand(self) -> "Report":
        if self.hand and self.x is None:
            raise ValueError("x is required when hand is true")
        return self


class ModeIn(BaseModel):
    mode: Mode


class Snapshot(BaseModel):
    """What the body GETs. Flat and small so the chip can parse it with indexOf.

    The board's whole job: servo.write(angle); then for each LED i (0..4)
    analogWrite(pin[i], i < leds ? brightness : 0).
    """

    angle: int
    leds: int
    brightness: int
    mode: Mode
    hand: bool
    stale: bool


class HistoryItem(BaseModel):
    at: str
    hand: bool
    x: float | None
    fingers: int
    pinch: float
    angle: int
