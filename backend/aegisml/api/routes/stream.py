"""Stream simulator API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aegisml.monitoring.stream_simulator import get_simulator

router = APIRouter(prefix="/api/stream", tags=["stream"])


class StreamModeRequest(BaseModel):
    mode: str
    drift_config: dict | None = None


@router.get("/status")
def stream_status():
    return get_simulator().get_state()


@router.post("/start")
def start_stream():
    sim = get_simulator()
    sim.start()
    return {"status": "started", **sim.get_state()}


@router.post("/stop")
def stop_stream():
    sim = get_simulator()
    sim.stop()
    return {"status": "stopped", **sim.get_state()}


@router.post("/mode")
def set_mode(request: StreamModeRequest):
    sim = get_simulator()
    try:
        sim.set_mode(request.mode, request.drift_config)
        return {"status": "mode_set", "mode": request.mode, **sim.get_state()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reset")
def reset_stream():
    sim = get_simulator()
    sim.reset_to_normal()
    return {"status": "reset_to_normal", **sim.get_state()}
