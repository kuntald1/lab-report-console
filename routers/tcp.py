from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.models import Device as DeviceModel
from services.tcp_manager import (
    connect_device, disconnect_device,
    connect_all, disconnect_all,
    get_device_state, get_all_states
)
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class ConnectRequest(BaseModel):
    retry_interval: Optional[int] = 10

class LegacyStartRequest(BaseModel):
    port: int = 5600
    device_type: str = "Hematology"

@router.post("/connect/{device_id}")
def connect_single(device_id: int, req: ConnectRequest = ConnectRequest()):
    ok, msg = connect_device(device_id, req.retry_interval)
    if not ok:
        return {"status": "error", "message": msg}
    return {"status": "started", "device_id": device_id, "message": msg}

@router.post("/disconnect/{device_id}")
def disconnect_single(device_id: int):
    disconnect_device(device_id)
    return {"status": "stopped", "device_id": device_id}

@router.post("/connect-all")
def connect_all_devices(req: ConnectRequest = ConnectRequest()):
    results = connect_all(req.retry_interval)
    return {"status": "started", "devices": results}

@router.post("/disconnect-all")
def disconnect_all_devices():
    disconnect_all()
    return {"status": "all_stopped"}

@router.get("/state/{device_id}")
def device_state(device_id: int):
    return get_device_state(device_id)

@router.get("/states")
def all_states():
    return get_all_states()

# ── Legacy endpoints (backward compat) ──────────────────────────────────────
@router.post("/start")
def legacy_start(config: LegacyStartRequest):
    return {"status": "use /api/tcp/connect-all or /api/tcp/connect/{id}"}

@router.post("/stop")
def legacy_stop():
    disconnect_all()
    return {"status": "stopped"}

@router.get("/status")
def legacy_status():
    states = get_all_states()
    running = any(s["running"] for s in states.values())
    connected = any(s["connected"] for s in states.values())
    all_logs = []
    for s in states.values():
        all_logs.extend(s.get("logs", []))
    all_logs.sort(key=lambda x: x.get("time",""))
    total = sum(s.get("total",0) for s in states.values())
    return {
        "running":        running,
        "connected":      connected,
        "total_received": total,
        "logs":           all_logs[-50:],
        "mode":           "multi-device",
    }

# ── Scan log endpoints ────────────────────────────────────────
from services.tcp_manager import get_scan_log, get_scan_summary

@router.get("/scans")
def scan_log(limit: int = 100):
    """All barcode scan attempts — success, unknown barcode, errors"""
    return get_scan_log(limit)

@router.get("/scans/summary")
def scan_summary():
    """Today's scan counts: total, success, unknown barcode, errors"""
    return get_scan_summary()
