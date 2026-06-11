"""
ASTM / HL7 Parser Service
==========================
Converts raw machine text data into clean structured JSON.
Supports ASTM LIS2-A2 and HL7 v2.x formats.
Auto-detects protocol from the first line.
"""

from datetime import datetime
import re

# ── Reference ranges ──────────────────────────────────────────
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
    """Return H (High), L (Low), or N (Normal) for a parameter value."""
    ref = REFERENCE_RANGES.get(param)
    if not ref:
        return "N"
    if value < ref["min"]:
        return "L"
    if value > ref["max"]:
        return "H"
    return "N"


def parse_astm(raw_text: str, device_type: str = "Hematology") -> dict:
    """
    Parse ASTM LIS2-A2 formatted text into clean JSON.
    Record types: H (Header), P (Patient), O (Order), R (Result), L (Terminator)
    """
    # Strip framing bytes and normalize line endings first
    text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    # Remove STX/ETX/ENQ/ACK/EOT framing bytes
    import re as _re
    text = _re.sub(r'[\x02\x03\x04\x05\x06]', '', text)
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

        # Strip leading frame number from record type (e.g. "1H" -> "H")
        record_type = record_type.lstrip("0123456789")

        # Skip lines that aren't valid ASTM record types
        if record_type not in ("H", "P", "O", "R", "C", "L", "Q", "M"):
            continue

        if record_type == "H":
            result["message_type"] = "Header"

        elif record_type == "P":
            if len(parts) > 3:
                result["patient_id"] = parts[3]

        elif record_type == "O":
            # Barcode can be at parts[2] or parts[3] depending on format
            barcode_raw = ""
            if len(parts) > 3 and parts[3].strip():
                barcode_raw = parts[3]
            elif len(parts) > 2 and parts[2].strip():
                barcode_raw = parts[2]
            if barcode_raw:
                result["barcode"] = barcode_raw.replace("^", "").strip()

        elif record_type == "R":
            if len(parts) >= 4:
                test_raw  = parts[2] if len(parts) > 2 else ""
                value_raw = parts[3] if len(parts) > 3 else "0"
                unit_raw  = parts[4] if len(parts) > 4 else ""

                # Extract param name: ^^^WBC → WBC
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
    """
    Parse HL7 v2.x format (MSH, PID, OBR, OBX segments).
    Handles Erba H560 HL7 output with LOINC codes.
    """
    # Normalize line endings — HL7 uses \r as segment separator
    text = raw_text.replace('\r\n', '\r').replace('\n', '\r')
    segments = [s.strip() for s in text.strip().split("\r") if s.strip()]

    result = {
        "protocol":    "HL7",
        "device_type": "Hematology",
        "parsed_at":   datetime.now().isoformat(),
        "patient_id":  None,
        "barcode":     None,
        "parameters":  [],
    }

    for seg in segments:
        fields   = seg.split("|")
        seg_type = fields[0] if fields else ""

        if seg_type == "PID":
            # PID|1||HC12011^^^...  — patient barcode in field 3
            raw_pid = fields[3] if len(fields) > 3 else ""
            pid = raw_pid.split("^")[0].strip() if raw_pid else None
            result["patient_id"] = pid
            if pid:
                result["barcode"] = pid  # Use patient ID as barcode for H560

        elif seg_type == "OBR":
            # OBR|1||HC117610| — sample ID (not patient barcode)
            result["sample_id"] = fields[3].strip() if len(fields) > 3 else None
            # Only use as barcode fallback if no patient ID
            if not result.get("barcode"):
                result["barcode"] = result.get("sample_id")

        elif seg_type == "OBX":
            # OBX|7|NM|6690-2^WBC^LN||6.89|10*3/uL|3.50-9.50|~N
            if len(fields) >= 6:
                # Field 3: LOINC^name^system — extract short name
                code_field = fields[3] if len(fields) > 3 else ""
                code_parts = code_field.split("^")
                # Use second part (name) if available, else first (LOINC code)
                param_name = code_parts[1] if len(code_parts) > 1 else code_parts[0]
                param = re.sub(r'[^A-Za-z0-9%#*]', '', param_name).upper()

                # Skip non-numeric types
                obs_type = fields[2] if len(fields) > 2 else ""
                if obs_type not in ("NM",):
                    continue

                try:
                    value = float(fields[5])
                except Exception:
                    continue  # Skip non-numeric values

                unit_raw  = fields[6].strip() if len(fields) > 6 else ""
                ref_range = fields[7].strip() if len(fields) > 7 else ""
                flag_raw  = fields[8].strip() if len(fields) > 8 else "N"

                # Parse ref range "3.50-9.50"
                ref_min, ref_max = "", ""
                if "-" in ref_range:
                    parts = ref_range.split("-")
                    try:
                        ref_min = float(parts[0])
                        ref_max = float(parts[1])
                    except Exception:
                        pass

                # Normalize flag — H560 uses "~N", "H~A", "L~A" format
                flag = "N"
                if "H" in flag_raw:
                    flag = "H"
                elif "L" in flag_raw:
                    flag = "L"

                ref = REFERENCE_RANGES.get(param, {})

                result["parameters"].append({
                    "param":   param,
                    "name":    ref.get("name", param_name),
                    "value":   value,
                    "unit":    unit_raw or ref.get("unit", ""),
                    "ref_min": ref_min or ref.get("min", ""),
                    "ref_max": ref_max or ref.get("max", ""),
                    "flag":    flag,
                    "status":  "Normal" if flag == "N" else ("High" if flag == "H" else "Low"),
                })

    return result

    return result


def parse_erba_ec90(raw_text: str) -> dict:
    """
    Parse Erba EC90 electrolyte analyser format.
    Uses OBX records: Na, K, Cl, Ca
    
    Example:
    1H|\^&|EC90|05217|...
    2P|1|00005172|...
    3OBR|1|00005172|000715726S|...
    4OBX|1|00005172|TYPE|Na|133.7|mmol/l|...
    5OBX|2|00005172|TYPE|K|5.04|mmol/l|...
    6OBX|3|00005172|TYPE|Cl|103.1|mmol/l|...
    """
    # Strip STX/ETX framing and normalize line endings
    import re as _re2
    _text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    _text = _re2.sub(r"[\x02\x03\x04\x05\x06]", "", _text)
    # Strip frame number prefix from start of each line (e.g. "3OBR" -> "OBR")
    lines = [_re2.sub(r"^\d+", "", l) for l in _text.strip().split("\n")]
    result = {
        "protocol":    "ASTM",
        "device_type": "Electrolyte",
        "parsed_at":   datetime.now().isoformat(),
        "barcode":     None,
        "patient_id":  None,
        "parameters":  [],
    }

    # Reference ranges for electrolytes
    elec_refs = {
        "Na": {"min": 136, "max": 145, "unit": "mmol/l", "name": "Sodium"},
        "K":  {"min": 3.5, "max": 5.0, "unit": "mmol/l", "name": "Potassium"},
        "Cl": {"min": 98,  "max": 107, "unit": "mmol/l", "name": "Chloride"},
        "Ca": {"min": 1.1, "max": 1.3, "unit": "mmol/l", "name": "Calcium (ionized)"},
    }

    for line in lines:
        # Remove leading frame number and strip
        line = line.strip()
        if not line:
            continue

        # Remove leading digit (frame number)
        if line and line[0].isdigit():
            line = line[1:]

        parts = line.split("|")
        record = parts[0] if parts else ""

        if record == "OBR":
            # OBR|1|00005172|000715726S|...
            if len(parts) > 3:
                result["barcode"] = parts[3].strip() or (parts[2].strip() if len(parts) > 2 else None)

        elif record == "P":
            if len(parts) > 2:
                result["patient_id"] = parts[2].strip()

        elif record == "OBX":
            # OBX|1|00005172|TYPE|Na|133.7|mmol/l|...
            if len(parts) >= 6:
                param = parts[4].strip() if len(parts) > 4 else ""
                val_str = parts[5].strip() if len(parts) > 5 else "0"
                unit = parts[6].strip() if len(parts) > 6 else ""

                try:
                    value = float(val_str)
                except Exception:
                    value = 0.0

                ref = elec_refs.get(param, {})
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


def parse_xl200(raw_text: str) -> dict:
    """
    Parse Erba XL200 Biochemistry Analyser — ASTM LIS2-A2 over TCP.

    The XL200 sends standard ASTM frames (H/P/O/R/L records) but with
    some quirks:
      - Frame numbers prefix every record (e.g. "1H", "2P", "3O", "4R")
      - Test codes come through as short codes: GLU, CREA, UREA, ALT,
        AST, CHOL, TRIG, TP, ALB, TBIL, DBIL, GGT, ALP, LDH, UA, etc.
      - Values in R records at parts[3], units at parts[4]
      - Barcode in O record at parts[3] (may contain ^ separators)
      - Sample type in O record at parts[11] (S=serum, U=urine, etc.)

    This function is a dedicated wrapper around parse_astm() with
    XL200-specific reference ranges merged in. It will never affect
    EC90 or EM200 parsing.
    """
    # XL200-specific biochemistry reference ranges
    # Merged on top of the global REFERENCE_RANGES in parse_astm
    XL200_REFS = {
        "TP":   {"min": 6.4,  "max": 8.3,  "unit": "g/dL",   "name": "Total Protein"},
        "ALB":  {"min": 3.5,  "max": 5.0,  "unit": "g/dL",   "name": "Albumin"},
        "TBIL": {"min": 0.2,  "max": 1.2,  "unit": "mg/dL",  "name": "Total Bilirubin"},
        "DBIL": {"min": 0.0,  "max": 0.3,  "unit": "mg/dL",  "name": "Direct Bilirubin"},
        "ALP":  {"min": 44,   "max": 147,  "unit": "U/L",    "name": "Alkaline Phosphatase"},
        "GGT":  {"min": 8,    "max": 61,   "unit": "U/L",    "name": "GGT"},
        "LDH":  {"min": 140,  "max": 280,  "unit": "U/L",    "name": "LDH"},
        "UA":   {"min": 3.5,  "max": 7.2,  "unit": "mg/dL",  "name": "Uric Acid"},
        "CA":   {"min": 8.6,  "max": 10.3, "unit": "mg/dL",  "name": "Calcium"},
        "PHOS": {"min": 2.5,  "max": 4.5,  "unit": "mg/dL",  "name": "Phosphorus"},
        "MG":   {"min": 1.6,  "max": 2.6,  "unit": "mg/dL",  "name": "Magnesium"},
        "NA":   {"min": 136,  "max": 145,  "unit": "mmol/L",  "name": "Sodium"},
        "K":    {"min": 3.5,  "max": 5.0,  "unit": "mmol/L",  "name": "Potassium"},
        "CL":   {"min": 98,   "max": 107,  "unit": "mmol/L",  "name": "Chloride"},
        "CO2":  {"min": 22,   "max": 29,   "unit": "mmol/L",  "name": "CO2 (Bicarbonate)"},
        "AMY":  {"min": 28,   "max": 100,  "unit": "U/L",    "name": "Amylase"},
        "LIPA": {"min": 13,   "max": 60,   "unit": "U/L",    "name": "Lipase"},
        "CK":   {"min": 39,   "max": 308,  "unit": "U/L",    "name": "CK (Total)"},
        "CKMB": {"min": 0,    "max": 25,   "unit": "U/L",    "name": "CK-MB"},
        "IRON": {"min": 60,   "max": 170,  "unit": "µg/dL",  "name": "Iron"},
        "TIBC": {"min": 250,  "max": 370,  "unit": "µg/dL",  "name": "TIBC"},
    }

    # Temporarily inject XL200 refs into global table, parse, then restore
    # This keeps parse_astm() untouched and flag logic working correctly
    added_keys = []
    for k, v in XL200_REFS.items():
        if k not in REFERENCE_RANGES:
            REFERENCE_RANGES[k] = v
            added_keys.append(k)
        # If key already exists (e.g. GLU from hematology table), don't overwrite

    result = parse_astm(raw_text, device_type="Biochemistry")
    result["device_type"] = "Biochemistry"
    result["parser"] = "xl200"

    # Clean up any keys we temporarily added
    for k in added_keys:
        del REFERENCE_RANGES[k]

    return result


def parse_gh900(raw_text: str) -> dict:
    """
    Parse Lifotronic GH-900 HbA1c Analyser proprietary format.

    The GH-900 sends a binary-ish stream (no standard ASTM records):
      S06----<NN><BARCODE><DIGITS><ABSORPTION_STREAM>

    Where:
      - <NN>               : 2-digit sample counter (e.g. 11 = sample 11)
      - <BARCODE>          : alphanumeric patient barcode (e.g. HC805072RET)
      - <DIGITS>           : fixed header block (date/time/reagent info), 9+ digits
      - <ABSORPTION_STREAM>: 200+ chromatogram absorption values encoded as
                             6-char fixed-width fields concatenated with a leading '.'
                             e.g. ".00140.00290...8.2490..."

    The HbA1c result is at index 11 (0-based) of the absorption stream,
    which matches the machine's screen display (e.g. 8.249 → 8.2%).

    QC samples (Type D on screen) have barcodes like QC1, QC2 and are
    filtered upstream by save_result() via QC_PREFIXES.
    """
    import re as _re
    result = {
        "protocol":    "GH900",
        "device_type": "HbA1c",
        "parsed_at":   datetime.now().isoformat(),
        "patient_id":  None,
        "barcode":     None,
        "parameters":  [],
    }

    text = raw_text.strip()

    # Extract barcode and absorption stream
    # Pattern: S + digits + dashes + digits + barcode + 9+ digit block + absorption
    m = _re.match(r'S\d+\-+\d+([A-Za-z0-9]+?)(\d{9,})(.*)', text, _re.DOTALL)
    if not m:
        return result

    barcode     = m.group(1).strip()
    absorption_raw = m.group(3)  # starts with '.'

    result["barcode"] = barcode if barcode else None

    # Parse 6-char fixed-width absorption fields
    # The stream starts with '.' so prepend '0' → '0.XXXX'
    absorption_fixed = "0" + absorption_raw
    chunks = [absorption_fixed[i:i+6] for i in range(0, len(absorption_fixed), 6)]

    values = []
    for chunk in chunks:
        try:
            values.append(float(chunk))
        except ValueError:
            pass

    # HbA1c result is at absorption index 11
    HBAIC_INDEX = 11
    if len(values) > HBAIC_INDEX:
        hba1c = round(values[HBAIC_INDEX], 2)
        # Flag: normal <5.7%, prediabetes 5.7-6.4%, diabetes >=6.5%
        if hba1c < 5.7:
            flag, status = "N", "Normal"
        elif hba1c < 6.5:
            flag, status = "H", "Borderline (Pre-diabetic)"
        else:
            flag, status = "H", "High (Diabetic range)"

        result["parameters"].append({
            "param":   "HBA1C",
            "name":    "Glycated Hemoglobin (HbA1c)",
            "value":   hba1c,
            "unit":    "%",
            "ref_min": 4.0,
            "ref_max": 5.6,
            "flag":    flag,
            "status":  status,
        })

    return result


def auto_parse(raw_text: str, device_type: str = "Hematology", parser: str = None) -> dict:
    """
    Route to the correct parser.

    Priority order:
    1. Explicit `parser` field from device DB record  ← new, zero ambiguity
    2. HL7 auto-detect (MSH| prefix)
    3. EC90 heuristic (OBX+OBR without O| records)
    4. Standard ASTM fallback

    parser values (match device.parser DB field):
      "erba_ec90"  → parse_erba_ec90()
      "erba_em200" → parse_astm()          (EM200 sends standard ASTM)
      "erba_xl200" → parse_xl200()
      None         → auto-detect as before  (safe fallback)
    """
    text = raw_text.strip()

    # ── Explicit parser routing (preferred path) ──────────────
    if parser:
        p = parser.lower().strip()
        if p == "erba_ec90":
            return parse_erba_ec90(text)
        if p in ("erba_em200", "astm"):
            return parse_astm(text, device_type)
        if p == "erba_xl200":
            return parse_xl200(text)
        if p in ("erba_h560", "hl7"):
            return parse_hl7(text)
        if p in ("gh900", "lifotronic_gh900"):
            return parse_gh900(text)
        # Unknown parser string — fall through to auto-detect below

    # ── Auto-detect fallback ──────────────────────────────────
    # Strip any leading control bytes before checking format
    clean = text.lstrip('\x00\x01\x02\x03\x04\x05\x06\x0b\x1c')
    if clean.startswith("MSH|"):
        return parse_hl7(clean)
    # EC90 uses OBR/OBX segments (no standard O|/R| records)
    has_standard_o = any(line.startswith("O|") for line in text.replace("\r", "\n").split("\n"))
    if "OBX" in text and "OBR" in text and not has_standard_o:
        return parse_erba_ec90(text)
    # Standard ASTM with O|/R| records (EM200, XL200, etc.)
    return parse_astm(text, device_type)
