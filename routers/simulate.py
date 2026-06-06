from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.models import Patient
import random

router = APIRouter()

def generate_cbc_astm(barcode: str, patient_id: str = "P001") -> str:
    """Generate a realistic CBC (Complete Blood Count) ASTM string"""
    wbc  = round(random.uniform(3.5, 13.0), 1)
    rbc  = round(random.uniform(3.8, 6.0),  2)
    hgb  = round(random.uniform(10.0, 18.0),1)
    hct  = round(random.uniform(35.0, 55.0),1)
    plt  = round(random.uniform(100, 450),   0)
    mcv  = round(random.uniform(75, 105),    1)
    mch  = round(random.uniform(25, 35),     1)
    mchc = round(random.uniform(30, 38),     1)

    return f"""H|\\^&|||Erba H560|||||||P|1
P|1||{patient_id}|||||M
O|1|{barcode}||^^^CBC|R
R|1|^^^WBC|{wbc}|10^3/uL|4.0-11.0|N
R|2|^^^RBC|{rbc}|10^6/uL|4.5-5.5|N
R|3|^^^HGB|{hgb}|g/dL|13.0-17.0|N
R|4|^^^HCT|{hct}|%|40.0-52.0|N
R|5|^^^PLT|{plt}|10^3/uL|150-400|N
R|6|^^^MCV|{mcv}|fL|80.0-100.0|N
R|7|^^^MCH|{mch}|pg|27.0-33.0|N
R|8|^^^MCHC|{mchc}|g/dL|32.0-36.0|N
L|1|N"""

def generate_biochem_astm(barcode: str, patient_id: str = "P001") -> str:
    """Generate a realistic Biochemistry ASTM string"""
    glu  = round(random.uniform(60, 200),  1)
    crea = round(random.uniform(0.4, 2.0), 2)
    urea = round(random.uniform(10, 60),   1)
    alt  = round(random.uniform(5, 80),    1)
    ast  = round(random.uniform(5, 60),    1)
    chol = round(random.uniform(120, 280), 1)
    trig = round(random.uniform(50, 250),  1)

    return f"""H|\\^&|||XL200|||||||P|1
P|1||{patient_id}|||||M
O|1|{barcode}||^^^BIOCHEM|R
R|1|^^^GLU|{glu}|mg/dL|70-110|N
R|2|^^^CREA|{crea}|mg/dL|0.6-1.2|N
R|3|^^^UREA|{urea}|mg/dL|15-45|N
R|4|^^^ALT|{alt}|U/L|7-56|N
R|5|^^^AST|{ast}|U/L|10-40|N
R|6|^^^CHOL|{chol}|mg/dL|0-200|N
R|7|^^^TRIG|{trig}|mg/dL|0-150|N
L|1|N"""

@router.get("/astm/cbc")
def simulate_cbc(barcode: str = "MC00000001", db: Session = Depends(get_db)):
    """Generate a sample CBC ASTM raw data string for testing"""
    patient = db.query(Patient).filter(Patient.barcode == barcode).first()
    pid = patient.patient_name[:6].upper() if patient else "TEST01"
    raw = generate_cbc_astm(barcode, pid)
    return {
        "message":     "Sample CBC ASTM data generated",
        "device_type": "Hematology",
        "barcode":     barcode,
        "raw_data":    raw,
        "hint":        "Copy raw_data and paste into /api/results/parse to test parsing"
    }

@router.get("/astm/biochem")
def simulate_biochem(barcode: str = "MC00000001", db: Session = Depends(get_db)):
    """Generate a sample Biochemistry ASTM raw data string for testing"""
    patient = db.query(Patient).filter(Patient.barcode == barcode).first()
    pid = patient.patient_name[:6].upper() if patient else "TEST01"
    raw = generate_biochem_astm(barcode, pid)
    return {
        "message":     "Sample Biochemistry ASTM data generated",
        "device_type": "Biochemistry",
        "barcode":     barcode,
        "raw_data":    raw,
        "hint":        "Copy raw_data and paste into /api/results/parse to test parsing"
    }
