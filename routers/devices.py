from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.models import Device
from services.tcp_manager import get_device_state
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class DeviceCreate(BaseModel):
    name:          str
    device_type:   str
    ip_address:    Optional[str]  = None
    port:          Optional[int]  = None
    parser:        Optional[str]  = None
    protocol:      Optional[str]  = "ASTM"
    bidirectional: Optional[bool] = True
    is_client:     Optional[bool] = False

class DeviceUpdate(BaseModel):
    is_online: bool

@router.get("/")
def get_devices(db: Session = Depends(get_db)):
    devices = db.query(Device).all()
    result  = []
    for d in devices:
        state = get_device_state(d.id)
        result.append({
            "id":           d.id,
            "name":         d.name,
            "device_type":  d.device_type,
            "ip_address":   d.ip_address,
            "port":         d.port,
            "parser":       d.parser,
            "protocol":     d.protocol,
            "bidirectional":d.bidirectional,
            "is_client":    d.is_client,
            "is_online":    d.is_online,
            "created_at":   d.created_at,
            "tcp_running":  state["running"],
            "tcp_connected":state["connected"],
            "total_results":state["total"],
            "last_barcode": state["last_barcode"],
        })
    return result

@router.post("/")
def create_device(device: DeviceCreate, db: Session = Depends(get_db)):
    db_device = Device(**device.dict())
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device

# ── NEW: Edit device ─────────────────────────────────────────
@router.put("/{device_id}")
def update_device(device_id: int, device: DeviceCreate, db: Session = Depends(get_db)):
    db_device = db.query(Device).filter(Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    for field, value in device.dict().items():
        setattr(db_device, field, value)
    db.commit()
    db.refresh(db_device)
    return db_device

@router.patch("/{device_id}/status")
def update_status(device_id: int, update: DeviceUpdate, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_online = update.is_online
    db.commit()
    return {"message": "updated"}

@router.delete("/{device_id}")
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return {"message": "Device deleted"}
