from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.models import Patient
from pydantic import BaseModel
from typing import Optional
import random, string

router = APIRouter()

class PatientCreate(BaseModel):
    patient_name: str
    age:          Optional[int] = None
    gender:       Optional[str] = None
    doctor_name:  Optional[str] = None
    sample_type:  Optional[str] = "Blood"
    barcode:      Optional[str] = None

def generate_barcode():
    return "MC" + ''.join(random.choices(string.digits, k=8))

@router.get("/")
def get_patients(db: Session = Depends(get_db)):
    return db.query(Patient).order_by(Patient.created_at.desc()).all()

@router.post("/")
def create_patient(patient: PatientCreate, db: Session = Depends(get_db)):
    barcode = patient.barcode or generate_barcode()
    # ensure unique
    while db.query(Patient).filter(Patient.barcode == barcode).first():
        barcode = generate_barcode()
    data = patient.dict()
    data["barcode"] = barcode
    db_patient = Patient(**data)
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    return db_patient

@router.get("/{barcode}")
def get_patient_by_barcode(barcode: str, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.barcode == barcode).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient
