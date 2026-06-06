"""
ASTM / HL7 Parser Service
==========================
Converts raw machine text data into clean structured JSON.
Supports ASTM LIS2-A2 and HL7 v2.x formats.
Auto-detects protocol from the first line.
"""

from datetime import datetime
import re

# ── Reference ranges ──────────────────────────────────────────────────────────
REFERENCE_RANGES = {
    # Hematology (CBC)
    "WBC":  {"min": 4.0,  "max": 11.0,  "unit": "10³/µL",  "name": "White Blood Cells"},
    "RBC":  {"min": 4.5,  "max": 5.5,   "unit": "10⁶/µL",  "name": "Red Blood Cells"},
    "HGB":  {"min": 13.0, "max": 17.0,  "unit": "g/dL",    "name": "Hemoglobin"},
    "HCT":  {"min": 40.0, "max": 52.0,  "unit": "%",        "name": "Hematocrit"},
    "PLT":  {"min": 150,  "max": 400,   "unit": "10³/µL",  "name": "Platelets"},
    "MCV":  {"min": 80.0, "max": 100.0, "unit": "fL",       "name": "Mean Corpuscular Volume"},
    "MCH":  {"min": 27.0, "max": 33.0,  "unit": "pg",       "name": "Mean Corpuscular Hemoglobin"},
    "MCHC": {"min": 32.0, "max": 36.0,  "unit": "g/dL",    "name": "MCHC"},
    # Biochemistry
    "GLU":  {"min": 70,   "max": 110,   "unit": "mg/dL",   "name": "Glucose"},
    "CREA": {"min": 0.6,  "max": 1.2,   "unit": "mg/dL",   "name": "Creatinine"},
    "UREA": {"min": 15,   "max": 45,    "unit": "mg/dL",   "name": "Urea"},
    "ALT":  {"min": 7,    "max": 56,    "unit": "U/L",      "name": "ALT (SGPT)"},
    "AST":  {"min": 10,   "max": 40,    "unit": "U/L",      "name": "AST (SGOT)"},
    "CHOL": {"min": 0,    "max": 200,   "unit": "mg/dL",   "name": "Total Cholesterol"},
    "TRIG": {"min": 0,    "max": 150,   "unit": "mg/dL",   "name": "Triglycerides"},
}


def get_flag(param: str, value: float) -> str:
    ref = REFERENCE_RANGES.get(param)
    if not ref:
        return "N"
    if value < ref["min"]:
        return "L"
    if value > ref["max"]:
        return "H"
    return "N"


def strip_astm_framing(raw_text: str) -> str:
    """
    Strip ASTM framing bytes from raw data.
    Each frame: STX(0x02) + frame_num + data + ETX(0x03) + checksum(2 chars) + CR/LF
    Also handles ENQ/ACK protocol bytes.
    """
    # Remove STX (\x02) + optional frame number digit
    clean = re.sub(r'\x02\d?', '', raw_text)
    # Remove ETX (\x03) + 2-char hex checksum
    clean = re.sub(r'\x03[0-9A-Fa-f]{0,2}', '', clean)
    # Remove ENQ, ACK, EOT control bytes
    clean = re.sub(r'[\x04\x05\x06]', '', clean)
    # Normalize line endings
    clean = clean.replace('\r\n', '\n').replace('\r', '\n')
    return clean.strip()


def parse_astm(raw_text: str, device_type: str = "Hematology") -> dict:
    """Parse ASTM LIS2-A2 formatted text into clean JSON."""
    # Strip framing bytes first
    text = strip_astm_framing(raw_text)
    lines = text.strip().split("\n")
    result = {
        "protocol":    "ASTM",
        "device_type": device_type,
        "parsed_at":   datetime.now().isoformat(),
        "patient_id":  None,
        "barcode":     None,
        "parameters":  [],
        "raw_lines":   len(lines),
    }

    for line in lines:
        line  = line.strip()
        if not line:
            continue
        parts       = line.split("|")
        record_type = parts[0] if parts else ""

        if record_type == "H":
            result["message_type"] = "Header"

        elif record_type == "P":
            if len(parts) > 3:
                result["patient_id"] = parts[3]

        elif record_type == "O":
            if len(parts) > 3:
                barcode_raw    = parts[3]
                result["barcode"] = barcode_raw.replace("^", "").strip()

        elif record_type == "R":
            if len(parts) >= 4:
                test_raw  = parts[2] if len(parts) > 2 else ""
                value_raw = parts[3] if len(parts) > 3 else "0"
                unit_raw  = parts[4] if len(parts) > 4 else ""

                param = re.sub(r'[\^]+', '', test_raw).strip().upper()

                try:
                    value = float(value_raw)
                except Exception:
                    value = 0.0

                ref  = REFERENCE_RANGES.get(param, {})
                flag = get_flag(param, value)

                result["parameters"].append({
                    "param":   param,
                    "name":    ref.get("name", param),
                    "value":   value,
                    "unit":    unit_raw or ref.get("unit", ""),
                    "ref_min": ref.get("min", ""),
                    "ref_max": ref.get("max", ""),
                    "flag":    flag,
                    "status":  "Normal" if flag == "N" else ("High" if flag == "H" else "Low"),
                })

    return result


def parse_hl7(raw_text: str) -> dict:
    """Parse HL7 v2.x format (MSH, PID, OBR, OBX segments)."""
    segments = raw_text.strip().split("\n")
    result = {
        "protocol":    "HL7",
        "parsed_at":   datetime.now().isoformat(),
        "patient_id":  None,
        "barcode":     None,
        "parameters":  [],
    }

    for seg in segments:
        fields   = seg.split("|")
        seg_type = fields[0] if fields else ""

        if seg_type == "PID":
            result["patient_id"] = fields[3] if len(fields) > 3 else None

        elif seg_type == "OBR":
            result["barcode"] = fields[3] if len(fields) > 3 else None

        elif seg_type == "OBX":
            if len(fields) >= 6:
                param = (fields[3] or "").split("^")[0].upper()
                try:
                    value = float(fields[5])
                except Exception:
                    value = 0.0

                ref  = REFERENCE_RANGES.get(param, {})
                flag = get_flag(param, value)

                result["parameters"].append({
                    "param":   param,
                    "name":    ref.get("name", param),
                    "value":   value,
                    "unit":    fields[6] if len(fields) > 6 else ref.get("unit", ""),
                    "ref_min": ref.get("min", ""),
                    "ref_max": ref.get("max", ""),
                    "flag":    flag,
                    "status":  "Normal" if flag == "N" else ("High" if flag == "H" else "Low"),
                })

    return result


def parse_erba_ec90(raw_text: str) -> dict:
    """
    Parse Erba EC90 electrolyte analyser format.
    Strips STX/ETX ASTM framing bytes before parsing.

    Raw format (with framing):
    \x021H|\^&|EC90|....\x03BD
    \x022P|1|00005172|...\x0305
    \x023OBR|1|00005172|000715726S|UserOne|...\x0381
    \x024OBX|1|00005172|TYPE|Na|133.7|mmol/l|...\x03B1
    """
    # Strip ASTM framing bytes first
    text = strip_astm_framing(raw_text)
    lines = text.strip().split("\n")

    result = {
        "protocol":    "ASTM",
        "device_type": "Electrolyte",
        "parsed_at":   datetime.now().isoformat(),
        "barcode":     None,
        "patient_id":  None,
        "parameters":  [],
    }

    elec_refs = {
        "Na": {"min": 136, "max": 145, "unit": "mmol/l", "name": "Sodium"},
        "K":  {"min": 3.5, "max": 5.0, "unit": "mmol/l", "name": "Potassium"},
        "Cl": {"min": 98,  "max": 107, "unit": "mmol/l", "name": "Chloride"},
        "Ca": {"min": 1.1, "max": 1.3, "unit": "mmol/l", "name": "Calcium (ionized)"},
    }

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split("|")
        record = parts[0] if parts else ""

        if record == "OBR":
            if len(parts) > 3 and parts[3].strip():
                result["barcode"] = parts[3].strip()
            elif len(parts) > 2 and parts[2].strip():
                result["barcode"] = parts[2].strip()

        elif record == "P":
            if len(parts) > 2:
                result["patient_id"] = parts[2].strip()

        elif record == "OBX":
            if len(parts) >= 6:
                param   = parts[4].strip() if len(parts) > 4 else ""
                val_str = parts[5].strip() if len(parts) > 5 else "0"
                unit    = parts[6].strip() if len(parts) > 6 else ""

                try:
                    value = float(val_str)
                except Exception:
                    value = 0.0

                ref  = elec_refs.get(param, {})
                flag = "N"
                if ref:
                    if value < ref.get("min", 0):
                        flag = "L"
                    elif value > ref.get("max", 999):
                        flag = "H"

                result["parameters"].append({
                    "param":   param,
                    "name":    ref.get("name", param),
                    "value":   value,
                    "unit":    unit or ref.get("unit", ""),
                    "ref_min": ref.get("min", ""),
                    "ref_max": ref.get("max", ""),
                    "flag":    flag,
                    "status":  "Normal" if flag == "N" else ("High" if flag == "H" else "Low"),
                })

    return result


def auto_parse(raw_text: str, device_type: str = "Hematology") -> dict:
    """
    Auto-detect protocol and parse accordingly.
    HL7       → starts with MSH|
    Erba EC90 → contains OBX records
    ASTM      → everything else
    """
    text = raw_text.strip()
    if text.startswith("MSH|"):
        return parse_hl7(text)
    if "OBX" in text:
        return parse_erba_ec90(text)
    return parse_astm(text, device_type)
