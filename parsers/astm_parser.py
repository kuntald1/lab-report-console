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
    # Differential — percentages
    "NEUT%":  {"min": 40.0, "max": 75.0,  "unit": "%", "name": "Neutrophils %"},
    "LYMPH%": {"min": 20.0, "max": 50.0,  "unit": "%", "name": "Lymphocytes %"},
    "MONO%":  {"min": 2.0,  "max": 10.0,  "unit": "%", "name": "Monocytes %"},
    "EO%":    {"min": 1.0,  "max": 6.0,   "unit": "%", "name": "Eosinophils %"},
    "BASO%":  {"min": 0.0,  "max": 1.0,   "unit": "%", "name": "Basophils %"},
    "IG%":    {"min": 0.0,  "max": 0.6,   "unit": "%", "name": "Immature Granulocytes %"},
    # Differential — absolute counts
    "NEUT#":  {"min": 2.0,  "max": 7.0,   "unit": "10³/µL", "name": "Neutrophils (Absolute)"},
    "LYMPH#": {"min": 1.0,  "max": 3.0,   "unit": "10³/µL", "name": "Lymphocytes (Absolute)"},
    "MONO#":  {"min": 0.2,  "max": 1.0,   "unit": "10³/µL", "name": "Monocytes (Absolute)"},
    "EO#":    {"min": 0.02, "max": 0.5,   "unit": "10³/µL", "name": "Eosinophils (Absolute)"},
    "BASO#":  {"min": 0.0,  "max": 0.1,   "unit": "10³/µL", "name": "Basophils (Absolute)"},
    "IG#":    {"min": 0.0,  "max": 0.03,  "unit": "10³/µL", "name": "Immature Granulocytes (Absolute)"},
    # Red-cell and platelet indices
    "RDW-SD": {"min": 37.0, "max": 54.0,  "unit": "fL", "name": "RDW-SD"},
    "RDW-CV": {"min": 11.5, "max": 14.5,  "unit": "%",  "name": "RDW-CV"},
    "PDW":    {"min": 9.0,  "max": 17.0,  "unit": "fL", "name": "Platelet Distribution Width"},
    "MPV":    {"min": 9.0,  "max": 13.0,  "unit": "fL", "name": "Mean Platelet Volume"},
    "P-LCR":  {"min": 13.0, "max": 43.0,  "unit": "%",  "name": "Platelet Large Cell Ratio"},
    "PCT":    {"min": 0.17, "max": 0.35,  "unit": "%",  "name": "Plateletcrit"},
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


_RANGE_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(?:-|\u2013|\u2014|to|~|\.\.|\^)\s*(-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE)
_ONE_SIDED_RE = re.compile(r"^\s*([<>])\s*=?\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_ref_range(raw: str):
    """Machine-sent reference range -> (min, max), either side possibly "".

    Handles the forms analysers actually send in ASTM field 6:
      "0.3 - 4.5"  "0.3-4.5"  "0.3 to 4.5"  "0.3^4.5"  "< 5"  "> 10"
    Anything it can't read confidently comes back ("", "") so the caller
    falls back to the built-in table rather than printing a wrong range.
    """
    if not raw:
        return "", ""
    txt = raw.strip()
    m = _RANGE_RE.match(txt)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _ONE_SIDED_RE.match(txt)
    if m:
        return ("", float(m.group(2))) if m.group(1) == "<" else (float(m.group(2)), "")
    return "", ""


def normalise_flag(raw: str, value, ref_min, ref_max, param: str) -> str:
    """Machine-sent abnormal flag -> the H / L / N the web app understands.

    A directional flag from the machine wins. Otherwise ("A" for a bare
    "abnormal", "N", or nothing at all) the value is compared against
    whichever range we have, and only with no range at all do we fall
    back to the built-in table — i.e. exactly the old behaviour.
    """
    f = (raw or "").strip().upper()
    if f in ("H", "HH", "H*", ">", "A>"):
        return "H"
    if f in ("L", "LL", "L*", "<", "A<"):
        return "L"
    lo_ok = isinstance(ref_min, (int, float))
    hi_ok = isinstance(ref_max, (int, float))
    if isinstance(value, (int, float)) and (lo_ok or hi_ok):
        if lo_ok and value < ref_min:
            return "L"
        if hi_ok and value > ref_max:
            return "H"
        return "N"
    return get_flag(param, value) if isinstance(value, (int, float)) else "N"


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
                # The specimen-ID field is ^-delimited: the ID itself, then any
                # modifier the machine tacks on. The Sysmex XN-330 sends
                # "^^      0930^M" — 0930 is the sample number and M is its
                # analysis mode, so stripping every ^ glued them into "0930M".
                # Take the first component that holds anything; an ID sent as
                # one piece (XL200 "1945S", EM200 "HC28956") is unaffected.
                result["barcode"] = next(
                    (c for c in (x.strip() for x in barcode_raw.split("^")) if c), "")

        elif record_type == "R":
            if len(parts) >= 4:
                test_raw  = parts[2] if len(parts) > 2 else ""
                value_raw = (parts[3] if len(parts) > 3 else "").strip()
                unit_raw  = parts[4] if len(parts) > 4 else ""
                # ASTM LIS2-A2 field 6 = reference range, field 7 = abnormal flag.
                # e.g. R|1|^^^TSH II|6.11|uIU/mL|0.3 - 4.5|H
                range_raw = (parts[5] if len(parts) > 5 else "").strip()
                flag_raw  = (parts[6] if len(parts) > 6 else "").strip()

                # Extract param name: ^^^^WBC^1 -> WBC (strip ^ and trailing ^N digit)
                param = re.sub(r"[\^]+", "", test_raw).strip()
                param = re.sub(r"\^\d+$", "", param)   # strip ^1 suffix
                param = re.sub(r"\d+$", "", param).strip().upper()

                # Skip if no param name
                if not param:
                    continue

                # Skip Q-Flag comment records (param names containing ?)
                if "?" in param or "?" in test_raw:
                    continue

                # Skip image/scatter plot records (PNG values)
                if "PNG" in value_raw or param.startswith("SCAT_") or param.startswith("DIST_"):
                    continue

                # Skip internal analyser metrics not shown on machine result screen
                SKIP_PARAMS = {"MICROR", "MACROR", "HYPERCHROMIA", "HYPOCHROMIA"}
                if param in SKIP_PARAMS:
                    continue

                # Skip interpretation/flag records — have no value and are not CBC params
                # e.g. Neutropenia, Lymphopenia, Positive_Diff, Positive_Morph, Positive_Count
                # These are R records with empty value and non-standard param names
                KNOWN_CBC_PARAMS = {
                    "WBC","RBC","HGB","HCT","MCV","MCH","MCHC","PLT",
                    "NEUT","LYMPH","MONO","EO","BASO",
                    "NEUT#","LYMPH#","MONO#","EO#","BASO#",
                    "NEUT%","LYMPH%","MONO%","EO%","BASO%",
                    "RDW-SD","RDW-CV","PDW","MPV","P-LCR","PCT",
                    "IG#","IG%","NRBC#","NRBC%","RET#","RET%",
                    "IRF","LFR","MFR","HFR","IPF",
                }
                # If value is empty AND param not a known CBC param → skip (interpretation flag)
                if not value_raw and param not in KNOWN_CBC_PARAMS:
                    continue

                # "----" means not measured — show as ---- in report
                if value_raw == "----":
                    result["parameters"].append({
                        "param":   param,
                        "name":    param,
                        "value":   None,
                        "unit":    unit_raw,
                        "ref_min": "",
                        "ref_max": "",
                        "flag":    "N",
                        "status":  "----",
                    })
                    continue

                # Empty value for known CBC param — also show as ----
                if not value_raw:
                    result["parameters"].append({
                        "param":   param,
                        "name":    param,
                        "value":   None,
                        "unit":    unit_raw,
                        "ref_min": "",
                        "ref_max": "",
                        "flag":    "N",
                        "status":  "----",
                    })
                    continue

                try:
                    value = float(value_raw)
                except Exception:
                    continue  # Skip non-numeric values (e.g. PNG refs)

                ref  = REFERENCE_RANGES.get(param, {})
                # The machine knows its own assay's range; the table here only
                # covers a handful of common tests, so trust the machine first
                # and fall back to the table when it sends nothing readable.
                ref_min, ref_max = parse_ref_range(range_raw)
                if ref_min == "" and ref_max == "":
                    ref_min, ref_max = ref.get("min", ""), ref.get("max", "")
                flag = normalise_flag(flag_raw, value, ref_min, ref_max, param)

                result["parameters"].append({
                    "param":   param,
                    "name":    param,
                    "value":   value,
                    "unit":    unit_raw or ref.get("unit", ""),
                    "ref_min": ref_min,
                    "ref_max": ref_max,
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

    Format: S<NN>----<NN><BARCODE><36-char header digits><absorption stream>
    The absorption stream starts at the first '.' and consists of
    6-char fixed-width fields (e.g. ".0014" -> 0.0014, "8.2490").

    Barcode = everything between the S-prefix and the fixed 36-char
    header block that immediately precedes the absorption stream.

    HbA1c result is at absorption stream index 11.
    """
    result = {
        "protocol":    "GH900",
        "device_type": "HbA1c",
        "parsed_at":   datetime.now().isoformat(),
        "patient_id":  None,
        "barcode":     None,
        "parameters":  [],
    }

    text = raw_text.strip()

    first_dot = text.find('.')
    if first_dot == -1:
        return result

    m = re.match(r'(S\d+\-+\d{2})', text)
    if not m:
        return result
    prefix_end = m.end()

    before_dot = text[prefix_end:first_dot]
    HEADER_LEN = 36  # fixed-width date/time/reagent header block
    if len(before_dot) <= HEADER_LEN:
        return result

    barcode = before_dot[:-HEADER_LEN].strip()
    result["barcode"] = barcode if barcode else None

    # Parse absorption stream: starts with '.' -> prepend '0' -> 6-char chunks
    absorption_raw = text[first_dot:]
    absorption_fixed = "0" + absorption_raw
    chunks = [absorption_fixed[i:i+6] for i in range(0, len(absorption_fixed), 6)]

    values = []
    for chunk in chunks:
        try:
            values.append(float(chunk))
        except ValueError:
            pass

    # The analyser reports the fractions it worked out itself, as six
    # zero-padded NN.N fields immediately after the twelve 6-char area/height
    # chunks: HbA1a, HbA1b, HbF, LA1c+, HbA1c, HbA0. Reading HbA1c from there
    # is what keeps the report and the analyser's own screen in agreement.
    #
    # It used to be recalculated here from the peak areas with a factor fitted
    # to three samples (HC11015=6.0, 008216226=8.4, 000216326=5.6). It matched
    # those three and drifted elsewhere — 10.1 came out 10.0, 5.8 came out 6.0 —
    # and 0.2 of HbA1c can move a patient across the 5.7 or 6.5 threshold. The
    # formula is kept only as a fallback for a frame this block cannot read,
    # so a malformed field costs a slightly-off number rather than no result.
    SUMMARY_AT = 72              # 12 chunks x 6 chars
    HBA1C_AT   = SUMMARY_AT + 16  # the 5th of the six NN.N fields
    CAL_FACTOR = 1.126
    if len(values) >= 12:
        areas = [values[i] * 10000 for i in range(6, 12)]
        area_total = sum(areas)
        area_hba1c = areas[4]  # index 10 overall -> areas[4]
        if area_total > 0:
            hba1c = None
            reported = absorption_fixed[HBA1C_AT:HBA1C_AT + 4]
            if re.fullmatch(r"\d{2}\.\d", reported):
                as_float = float(reported)
                # A plausible HbA1c only; anything outside it means the field
                # was not where it was expected, so fall through to the formula.
                if 2.0 <= as_float <= 25.0:
                    hba1c = as_float
            if hba1c is None:
                hba1c = round((area_hba1c / area_total) * 100 * CAL_FACTOR, 1)
                result["hba1c_source"] = "calculated"
            else:
                result["hba1c_source"] = "analyser"

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

            # HbA0% via Area-ratio (k=1.0, verified exact on 2 known samples)
            area_hba0 = areas[5]
            hba0_pct = round((area_hba0 / area_total) * 100, 1)

            # IFCC (mmol/mol) derived from NGSP using the standard
            # IFCC<->NGSP relationship: NGSP = 0.0915*IFCC + 2.15
            ifcc = round((hba1c - 2.15) / 0.0915, 1)

            result["gh900_info"] = {
                "ngsp":       hba1c,
                "ifcc":       ifcc,
                "area_total": round(area_total, 1),
                "hba0_pct":   hba0_pct,
            }

            # Chromatogram curve: the absorbance trace is the LONGEST run of
            # consecutive 0.XXXX (4-decimal, <1.0) tokens in the stream. This
            # is robust to the variable-width summary block (e.g. 53.10, 8.61,
            # 54.52) that precedes it — that block's odd length would otherwise
            # knock fixed-width 6-char chunking out of alignment and mangle the
            # curve. The areas/heights are also 0.XXXX but form only short runs
            # that the summary block separates from the main trace.
            chromo_matches = list(re.finditer(r'0\.\d{4}', absorption_raw))
            runs, cur = [], []
            for mt in chromo_matches:
                if cur and mt.start() != cur[-1].end():
                    runs.append(cur)
                    cur = []
                cur.append(mt)
            if cur:
                runs.append(cur)
            if runs:
                longest = max(runs, key=len)
                result["chromatogram"] = [float(mt.group()) for mt in longest]

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
            astm_result = parse_astm(text, device_type)
            # EC90 sends two formats: R|-record (handled above) and
            # OBR/OBX electrolyte panels (Na/K/Cl). If parse_astm found
            # nothing AND this looks like an OBR/OBX frame, retry with
            # the dedicated EC90 parser before giving up.
            if not astm_result.get("parameters"):
                has_standard_o = any(
                    line.lstrip().startswith("O|") or "|O|" in line
                    for line in text.replace("\r", "\n").split("\n")
                )
                if "OBX" in text and "OBR" in text and not has_standard_o:
                    ec90_result = parse_erba_ec90(text)
                    if ec90_result.get("parameters"):
                        return ec90_result
            return astm_result
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
