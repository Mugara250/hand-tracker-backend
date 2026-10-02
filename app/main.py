"""The cloud tier: the brain POSTs where the hand is, the body GETs where to point.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
Hosted (Render etc.): uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse

from app import config
from app.schemas import HistoryItem, ModeIn, Report, Snapshot
from app.state import state

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Hand Tracker Backend", version="1.0.0")

SIMULATOR = Path(__file__).resolve().parent.parent / "static" / "simulator.html"


def check_key(x_api_key: str | None) -> None:
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key")


@app.get("/health")
def health() -> dict:
    # The ESP32 looks for "hand-tracker" when searching the network for this laptop.
    return {"ok": True, "service": "hand-tracker"}


@app.get("/", include_in_schema=False)
def simulator() -> FileResponse:
    """A fake body in the browser: a servo needle and five LEDs, fed by GET /hand."""
    return FileResponse(SIMULATOR)


@app.post("/hand", response_model=Snapshot)
def report(data: Report, x_api_key: str | None = Header(default=None)) -> Snapshot:
    """The camera tells. Returns what the board will now do, so the brain can show it."""
    check_key(x_api_key)
    was_visible = state.hand
    state.apply(data)
    if data.hand != was_visible:
        log.info("hand %s", "found" if data.hand else "lost")
    return state.snapshot()


@app.get("/hand", response_model=Snapshot)
def current() -> Snapshot:
    """The board asks. LEDs go dark after STALE_SECONDS of camera silence; the servo holds."""
    return state.snapshot()


@app.post("/mode", response_model=Snapshot)
def set_mode(data: ModeIn, x_api_key: str | None = Header(default=None)) -> Snapshot:
    """Switch the LEDs between counting fingers and dimming by pinch."""
    check_key(x_api_key)
    state.set_mode(data.mode)
    log.info("LED mode -> %s", data.mode)
    return state.snapshot()


@app.get("/history", response_model=list[HistoryItem])
def history(limit: int = Query(50, ge=1, le=500)) -> list[HistoryItem]:
    """Recent reports with the angle the backend chose for each."""
    return state.recent(limit)
