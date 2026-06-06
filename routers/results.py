from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.models import LabResult, Patient, Device
from parsers.astm_parser import auto_parse
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class RawDataSubmit(BaseModel):
    raw_data:    str
    device_id:   Optional[int] = None
    barcode:     Optional[str] = None
    device_type: Optional[str] = "Hematology"

@router.get("/")
def get_all_results(db: Session = Depends(get_db)):
    results = db.query(LabResult).order_by(LabResult.created_at.desc()).limit(100).all()
    output = []
    for r in results:
        output.append({
            "id":           r.id,
            "barcode":      r.barcode,
            "test_name":    r.test_name,
            "status":       r.status,
            "parsed_data":  r.parsed_data,
            "created_at":   r.created_at,
            "patient_name": r.patient.patient_name if r.patient else "Unknown",
            "device_name":  r.device.name if r.device else "Manual",
        })
    return output

@router.post("/parse")
def parse_raw_data(payload: RawDataSubmit, db: Session = Depends(get_db)):
    """
    Submit raw ASTM/HL7 text data → parse → save to DB
    This is the core middleware function
    """
    try:
        parsed = auto_parse(payload.raw_data, payload.device_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Parse error: {str(e)}")

    # Find patient by barcode
    barcode = payload.barcode or parsed.get("barcode") or "UNKNOWN"
    patient = db.query(Patient).filter(Patient.barcode == barcode).first()

    # Find device
    device = None
    if payload.device_id:
        device = db.query(Device).filter(Device.id == payload.device_id).first()

    # Determine test name from parameters
    params = parsed.get("parameters", [])
    test_name = payload.device_type or "Unknown Test"
    if params:
        test_name = f"{payload.device_type} ({len(params)} parameters)"

    db_result = LabResult(
        patient_id  = patient.id if patient else None,
        device_id   = device.id if device else None,
        barcode     = barcode,
        test_name   = test_name,
        raw_data    = payload.raw_data,
        parsed_data = parsed,
        status      = "completed"
    )
    db.add(db_result)
    db.commit()
    db.refresh(db_result)

    return {
        "message":    "Data parsed and saved successfully",
        "result_id":  db_result.id,
        "barcode":    barcode,
        "patient":    patient.patient_name if patient else None,
        "parameters": len(params),
        "parsed":     parsed
    }

@router.get("/{result_id}")
def get_result(result_id: int, db: Session = Depends(get_db)):
    result = db.query(LabResult).filter(LabResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return {
        "id":          result.id,
        "barcode":     result.barcode,
        "raw_data":    result.raw_data,
        "parsed_data": result.parsed_data,
        "status":      result.status,
        "created_at":  result.created_at,
        "patient":     result.patient,
        "device":      result.device,
    }
