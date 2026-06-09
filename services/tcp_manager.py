"""
MediCloud Multi-Device TCP Manager
====================================
Connects to ALL lab analysers simultaneously.
Each device runs in its own background thread.

Two connection modes:
  is_client = False → MediCloud connects TO the machine (lab's mode)
  is_client = True  → Machine connects TO MediCloud (server/listen mode)
"""

import socket
import threading
import time
import datetime
from database import SessionLocal
from models.models import LabResult, Patient, Device as DeviceModel
from parsers.astm_parser import auto_parse

# ── Per-device in-memory state ────────────────────────────────
device_states: dict = {}
device_lock   = threading.Lock()

# ── Global scan log (all devices combined) ────────────────────
# Every barcode scan attempt is recorded here
scan_log: list = []
scan_lock = threading.Lock()

# Server sockets for server-mode devices
server_sockets: dict = {}

# ── Deduplication cache ───────────────────────────────────────
# Prevents saving the same barcode twice within DEDUP_WINDOW seconds.
# Key: (device_id, barcode)  Value: timestamp of last save
DEDUP_WINDOW  = 30  # seconds
_dedup_cache: dict = {}
_dedup_lock   = threading.Lock()


# ── Default state ─────────────────────────────────────────────

def _default_state() -> dict:
    return {
        "running":      False,
        "connected":    False,
        "thread":       None,
        "logs":         [],
        "total":        0,          # successful results saved
        "errors":       0,          # failed parse/save attempts
        "unknown":      0,          # barcode not found in DB
        "last_barcode": None,
    }


def _is_duplicate(device_id: int, barcode: str) -> bool:
    """
    Return True if this (device_id, barcode) was already saved
    within DEDUP_WINDOW seconds — i.e. it's a retransmit, skip it.
    If not a duplicate, record the timestamp and return False.
    Also prunes expired entries to keep the cache small.
    """
    if not barcode or barcode == "UNKNOWN":
        return False  # never dedup unknown barcodes — might be different samples

    key = (device_id, barcode)
    now = time.monotonic()

    with _dedup_lock:
        # Prune all expired entries first
        expired = [k for k, ts in _dedup_cache.items() if now - ts > DEDUP_WINDOW]
        for k in expired:
            del _dedup_cache[k]

        if key in _dedup_cache:
            return True  # duplicate — seen within the window, skip

        # First occurrence in this window — record and allow
        _dedup_cache[key] = now
        return False


# ── Logging ───────────────────────────────────────────────────

def add_log(device_id: int, msg: str, level: str = "info"):
    """Add a timestamped log entry for a device (keeps last 100)."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = {"time": ts, "msg": msg, "level": level}
    with device_lock:
        if device_id not in device_states:
            device_states[device_id] = _default_state()
        device_states[device_id]["logs"].append(entry)
        device_states[device_id]["logs"] = device_states[device_id]["logs"][-100:]
    print(f"[TCP/DEV-{device_id}/{level.upper()}] {msg}")


def add_scan(device_id: int, device_name: str, barcode: str,
             status: str, detail: str, params: int = 0):
    """
    Record a barcode scan attempt to the global scan log.

    status values:
      'success'  — parsed and saved successfully
      'unknown'  — barcode not found in patients table
      'error'    — parse/save exception occurred
    """
    ts = datetime.datetime.now()
    entry = {
        "time":        ts.strftime("%H:%M:%S"),
        "date":        ts.strftime("%Y-%m-%d"),
        "datetime":    ts.isoformat(),
        "device_id":   device_id,
        "device_name": device_name,
        "barcode":     barcode,
        "status":      status,
        "detail":      detail,
        "params":      params,
    }
    with scan_lock:
        scan_log.append(entry)
        # Keep last 500 scans in memory
        if len(scan_log) > 500:
            scan_log.pop(0)


# ── DB helpers ────────────────────────────────────────────────

def get_device(device_id: int):
    db = SessionLocal()
    d  = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
    db.close()
    return d


def set_device_online(device_id: int, online: bool):
    db = SessionLocal()
    d  = db.query(DeviceModel).filter(DeviceModel.id == device_id).first()
    if d:
        d.is_online = online
        db.commit()
    db.close()


# ── Save result ───────────────────────────────────────────────

def save_result(device_id: int, raw_data: str, device_type: str = "Hematology"):
    """
    Parse raw ASTM/HL7 data and save to database.
    Reads device.parser from DB and passes it to auto_parse() so each
    machine uses its own dedicated parser function.
    Tracks:
      - success  → result saved, patient found
      - unknown  → result saved but patient not in DB (barcode unknown)
      - error    → parse or DB error
    """
    device = get_device(device_id)
    device_name   = device.name        if device else f"Device {device_id}"
    device_parser = getattr(device, "parser", None) if device else None  # e.g. "erba_xl200"
    patient_name  = None  # Initialize before try block

    try:
        parsed  = auto_parse(raw_data, device_type, parser=device_parser)
        barcode = parsed.get("barcode") or "UNKNOWN"
        params  = len(parsed.get("parameters", []))

        # ── QC / Control sample filter ────────────────────────
        # Skip calibration/control samples — they are not patient results.
        # Patterns: BIORAD, QC, CONTROL, CAL, CALIBRATOR (case-insensitive)
        QC_PREFIXES = ("BIORAD", "QC", "CONTROL", "CAL", "CALIBRAT", "CTRL")
        if any(barcode.upper().startswith(p) for p in QC_PREFIXES):
            add_log(device_id,
                f"🧪 QC sample ignored — Barcode: {barcode} (control/calibration)",
                "info")
            return None
        # ─────────────────────────────────────────────────────

        # ── Deduplication ─────────────────────────────────────
        if _is_duplicate(device_id, barcode):
            add_log(device_id,
                f"⏭️ Duplicate skipped — Barcode: {barcode} already saved within {DEDUP_WINDOW}s",
                "warn")
            add_scan(device_id, device_name, barcode, "duplicate",
                f"Skipped retransmit of {barcode} (within {DEDUP_WINDOW}s window)", params)
            return None
        # ─────────────────────────────────────────────────────

        db      = SessionLocal()
        patient = db.query(Patient).filter(Patient.barcode == barcode).first()

        result  = LabResult(
            patient_id  = patient.id if patient else None,
            device_id   = device_id,
            barcode     = barcode,
            test_name   = f"{parsed.get('device_type', 'Unknown')} ({params} params)",
            raw_data    = raw_data,
            parsed_data = parsed,
            status      = "completed",
        )
        db.add(result)
        db.commit()
        rid = result.id
        patient_name = patient.patient_name if patient else None  # Capture BEFORE db.close()
        db.close()

        with device_lock:
            if device_id in device_states:
                device_states[device_id]["total"]        += 1
                device_states[device_id]["last_barcode"]  = barcode

        if patient_name:
            # ✅ Full success — barcode found, result saved
            add_log(device_id,
                f"✅ Saved Result #{rid} — Barcode: {barcode} — Patient: {patient_name} — {params} params",
                "success")
            add_scan(device_id, device_name, barcode, "success",
                f"Result #{rid} saved for {patient_name} — {params} parameters", params)
        else:
            # ⚠️ Unknown barcode — result saved but no patient linked
            with device_lock:
                if device_id in device_states:
                    device_states[device_id]["unknown"] += 1
            add_log(device_id,
                f"⚠️ Barcode NOT FOUND in patients: {barcode} — Result #{rid} saved without patient",
                "warn")
            add_scan(device_id, device_name, barcode, "unknown",
                f"Barcode {barcode} not registered. Result #{rid} saved without patient link.", params)

        return rid

    except Exception as e:
        # ❌ Error — parse or DB failure
        barcode = "UNKNOWN"
        try:
            # Try to extract barcode even from failed parse
            for line in raw_data.split("\n"):
                if line.startswith("O|"):
                    parts = line.split("|")
                    if len(parts) > 3:
                        barcode = parts[3].replace("^", "").strip() or "UNKNOWN"
                    break
        except Exception:
            pass

        with device_lock:
            if device_id in device_states:
                device_states[device_id]["errors"] += 1

        add_log(device_id, f"❌ Processing error — Barcode: {barcode} — {e}", "error")
        add_scan(device_id, device_name, barcode, "error",
            f"Failed to process: {str(e)[:120]}", 0)
        return None



def handle_em200_connection(sock: socket.socket, device_id: int, device_type: str):
    """
    EM200 IP Urine Analyser — persistent connection handler.
    
    Protocol:
    1. Machine connects to us (once, stays connected)
    2. We send ENQ (0x05)
    3. Machine replies ACK (0x06)
    4. Machine sends ASTM frames for each sample
    5. We ACK each frame, machine sends EOT at end
    6. Loop — wait for next sample on same connection
    7. Only exit if machine disconnects
    """
    ENQ = b'\x05'
    ACK = b'\x06'
    EOT = b'\x04'
    ETX = b'\x03'

    try:
        sock.settimeout(10)
        # Step 1: Send ENQ to initiate
        sock.send(ENQ)
        add_log(device_id, "📤 Sent ENQ to EM200", "info")

        # Step 2: Wait for ACK (optional — some connections skip this)
        try:
            ack = sock.recv(1)
            if not ack:
                add_log(device_id, "⚠️ No ACK — machine disconnected", "warn")
                return
            if ack != ACK:
                add_log(device_id, f"⚠️ Expected ACK (06), got: {ack.hex()} — continuing anyway", "warn")
            else:
                add_log(device_id, "✅ Got ACK from EM200 — connection established, waiting for samples...", "info")
        except socket.timeout:
            add_log(device_id, "⚠️ No ACK in 10s — staying connected, waiting for data...", "warn")

        # Step 3: Loop forever — receive samples as they arrive
        sock.settimeout(86400)  # 24 hour idle timeout — stay connected until machine disconnects
        while True:
            with device_lock:
                if not device_states.get(device_id, {}).get("running"):
                    break

            raw_bytes = b""
            frame_count = 0

            try:
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        add_log(device_id, "⚠️ Machine disconnected", "warn")
                        return

                    # EM200 sends ENQ before each transmission — reply ACK
                    if chunk == ENQ:
                        sock.send(ACK)
                        continue

                    frame_count += 1
                    if EOT in chunk:
                        raw_bytes += chunk.replace(EOT, b"")
                        sock.send(ACK)
                        break
                    raw_bytes += chunk
                    if ETX in chunk:
                        sock.send(ACK)

            except socket.timeout:
                add_log(device_id, "⚠️ EM200 idle timeout — disconnected", "warn")
                return

            if raw_bytes:
                # Strip STX/ETX framing
                cleaned = raw_bytes.replace(b'\x02', b'').replace(b'\x03', b'')
                raw = cleaned.decode("ascii", errors="ignore").strip()
                if raw:
                    add_log(device_id, f"📥 Received {len(raw)} bytes — processing...", "info")
                    save_result(device_id, raw, device_type)
                    add_log(device_id, "⏳ Ready for next sample...", "info")

    except Exception as e:
        add_log(device_id, f"❌ EM200 connection error: {e}", "error")


def handle_xl200_connection(sock: socket.socket, device_id: int, device_type: str):
    """
    XL200 Biochemistry Analyser — persistent bidirectional connection handler.

    Protocol (identical to EM200 — Erba standard bidirectional ASTM):
    1. Machine connects to us (once, stays connected)
    2. We send ENQ (0x05)
    3. Machine replies ACK (0x06)
    4. Machine sends ASTM frames (H/P/O/R/L records)
    5. We ACK each ETX frame
    6. Machine sends EOT — we save result
    7. We send ENQ again — ready for next sample
    8. Loop on same connection until machine disconnects
    """
    ENQ = b'\x05'
    ACK = b'\x06'
    EOT = b'\x04'
    ETX = b'\x03'

    try:
        sock.settimeout(10)

        # Step 1: Send ENQ to initiate
        sock.send(ENQ)
        add_log(device_id, "📤 Sent ENQ to XL200", "info")

        # Step 2: Wait for ACK
        try:
            ack = sock.recv(1)
            if not ack:
                add_log(device_id, "⚠️ No ACK — XL200 disconnected", "warn")
                return
            if ack != ACK:
                add_log(device_id, f"⚠️ Expected ACK (06), got: {ack.hex()} — continuing anyway", "warn")
            else:
                add_log(device_id, "✅ Got ACK from XL200 — ready for samples", "info")
        except socket.timeout:
            add_log(device_id, "⚠️ No ACK in 10s — staying connected, waiting for data...", "warn")

        # Step 3: Loop — receive samples, send ENQ after each EOT
        sock.settimeout(86400)  # 24h idle — stay connected
        while True:
            with device_lock:
                if not device_states.get(device_id, {}).get("running"):
                    break

            raw_bytes = b""

            try:
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        add_log(device_id, "⚠️ XL200 disconnected", "warn")
                        return

                    # XL200 sends ENQ before each new sample transmission
                    if chunk == ENQ:
                        sock.send(ACK)
                        add_log(device_id, "↩️ ENQ received — sent ACK, waiting for frames...", "info")
                        continue

                    if EOT in chunk:
                        raw_bytes += chunk.replace(EOT, b"")
                        sock.send(ACK)  # ACK the EOT
                        break           # Full transmission received

                    raw_bytes += chunk
                    if ETX in chunk:
                        sock.send(ACK)  # ACK each data frame

            except socket.timeout:
                add_log(device_id, "⚠️ XL200 idle timeout — disconnected", "warn")
                return

            if raw_bytes:
                cleaned = raw_bytes.replace(b'\x02', b'').replace(b'\x03', b'')
                raw = cleaned.decode("ascii", errors="ignore").strip()
                if raw:
                    add_log(device_id, f"📥 Received {len(raw)} bytes — processing...", "info")
                    save_result(device_id, raw, device_type)
                    add_log(device_id, "⏳ Ready for next sample...", "info")

                    # Send ENQ to signal ready for next transmission
                    try:
                        sock.settimeout(5)
                        sock.send(ENQ)
                        sock.settimeout(86400)
                    except Exception:
                        pass  # If send fails, machine will reconnect

    except Exception as e:
        add_log(device_id, f"❌ XL200 connection error: {e}", "error")


# ── ASTM receive ──────────────────────────────────────────────

def receive_astm(sock: socket.socket, timeout: int = 30) -> str:
    """
    Read ASTM data from socket with ENQ/ACK handshake support.
    
    Erba EC90 protocol:
    1. Machine sends ENQ (0x05)
    2. We respond ACK (0x06)
    3. Machine sends STX-framed data frames
    4. We ACK each frame
    5. Machine sends EOT (0x04)
    
    Also handles simple ASTM without ENQ/ACK.
    """
    ENQ = b'\x05'
    ACK = b'\x06'
    EOT = b'\x04'
    STX = b'\x02'
    ETX = b'\x03'

    raw_bytes = b""
    sock.settimeout(timeout)
    
    try:
        # Read first byte to check if it's ENQ
        first = sock.recv(1)
        if not first:
            return ""
        
        if first == ENQ:
            # ENQ/ACK mode — send ACK and receive frames
            sock.send(ACK)
            
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                
                # EOT = end of transmission
                if EOT in chunk:
                    raw_bytes += chunk.replace(EOT, b"")
                    break
                
                raw_bytes += chunk
                
                # If chunk ends with ETX + checksum, send ACK
                if ETX in chunk:
                    sock.send(ACK)
                    
        else:
            # Non-ENQ mode — read normally
            raw_bytes = first
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw_bytes += chunk
                decoded = raw_bytes.decode("ascii", errors="ignore")
                if "L|1|N" in decoded or EOT in chunk:
                    break
                    
    except socket.timeout:
        pass
    except Exception:
        pass
    
    return raw_bytes.decode("ascii", errors="ignore").strip()


# ── MODE 1: CLIENT — MediCloud connects TO machine ────────────

def client_thread_fn(device_id: int, ip: str, port: int, device_type: str, retry: int):
    add_log(device_id, f"🔵 CLIENT MODE — Will connect to {ip}:{port}", "info")

    while True:
        with device_lock:
            if not device_states.get(device_id, {}).get("running"):
                break
        try:
            add_log(device_id, f"🔗 Connecting to {ip}:{port}...", "info")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((ip, port))

            with device_lock:
                if device_id in device_states:
                    device_states[device_id]["connected"] = True
            set_device_online(device_id, True)
            add_log(device_id, f"🟢 Connected to {ip}:{port}", "success")
            add_log(device_id, "⏳ Waiting for sample...", "info")

            while True:
                with device_lock:
                    if not device_states.get(device_id, {}).get("running"):
                        break
                raw = receive_astm(sock, timeout=300)
                if not raw:
                    add_log(device_id, "⚠️ Connection closed by machine", "warn")
                    break
                add_log(device_id, f"📥 Received {len(raw)} bytes — processing...", "info")
                save_result(device_id, raw, device_type)
                add_log(device_id, "⏳ Ready for next sample...", "info")

            sock.close()

        except ConnectionRefusedError:
            add_log(device_id, f"❌ Connection refused at {ip}:{port} — machine ON? LIS mode enabled?", "error")
        except socket.timeout:
            add_log(device_id, f"⏱️ Connection timeout to {ip}:{port}", "warn")
        except Exception as e:
            add_log(device_id, f"❌ Error: {e}", "error")

        with device_lock:
            if device_id in device_states:
                device_states[device_id]["connected"] = False
        set_device_online(device_id, False)

        with device_lock:
            if not device_states.get(device_id, {}).get("running"):
                break

        add_log(device_id, f"🔄 Reconnecting in {retry}s...", "info")
        for _ in range(retry):
            time.sleep(1)
            with device_lock:
                if not device_states.get(device_id, {}).get("running"):
                    break

    with device_lock:
        if device_id in device_states:
            device_states[device_id]["connected"] = False
            device_states[device_id]["running"]   = False
    set_device_online(device_id, False)
    add_log(device_id, "⏹ Client stopped", "warn")


# ── MODE 2: SERVER — Machine connects TO MediCloud ────────────

def server_thread_fn(device_id: int, port: int, device_type: str):
    global server_sockets
    add_log(device_id, f"🟢 SERVER MODE — Listening on port {port}", "info")

    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(5)
        srv.settimeout(1.0)
        server_sockets[port] = srv

        while True:
            with device_lock:
                if not device_states.get(device_id, {}).get("running"):
                    break
            try:
                conn, addr = srv.accept()
                with device_lock:
                    if device_id in device_states:
                        device_states[device_id]["connected"] = True
                set_device_online(device_id, True)
                add_log(device_id, f"🔌 Machine connected from {addr[0]}:{addr[1]}", "success")

                # Route to correct handler based on port
                if port == 6006:
                    # EM200: persistent ENQ-first connection
                    handle_em200_connection(conn, device_id, device_type)
                    add_log(device_id, "⏳ Waiting for EM200 to reconnect...", "info")
                elif port == 5001:
                    # XL200: persistent ENQ-first connection (bidirectional)
                    handle_xl200_connection(conn, device_id, device_type)
                    add_log(device_id, "⏳ Waiting for XL200 to reconnect...", "info")
                else:
                    # All other devices: machine initiates, standard ASTM
                    raw = receive_astm(conn)
                    if raw:
                        add_log(device_id, f"📥 Received {len(raw)} bytes — processing...", "info")
                        save_result(device_id, raw, device_type)
                        add_log(device_id, "⏳ Waiting for next sample...", "info")

                conn.close()
                with device_lock:
                    if device_id in device_states:
                        device_states[device_id]["connected"] = False
                set_device_online(device_id, False)

            except socket.timeout:
                continue
            except Exception as e:
                if device_states.get(device_id, {}).get("running"):
                    add_log(device_id, f"❌ Connection error: {e}", "error")

    except Exception as e:
        add_log(device_id, f"❌ Server error: {e}", "error")
    finally:
        try:
            srv.close()
        except Exception:
            pass
        if port in server_sockets:
            del server_sockets[port]

    with device_lock:
        if device_id in device_states:
            device_states[device_id]["running"]   = False
            device_states[device_id]["connected"] = False
    set_device_online(device_id, False)
    add_log(device_id, "⏹ Server stopped", "warn")


# ── Public API ────────────────────────────────────────────────

def connect_device(device_id: int, retry: int = 10):
    device = get_device(device_id)
    if not device:
        return False, "Device not found"
    with device_lock:
        if device_id not in device_states:
            device_states[device_id] = _default_state()
        if device_states[device_id]["running"]:
            return False, "Already running"
        device_states[device_id]["running"]   = True
        device_states[device_id]["connected"] = False
        device_states[device_id]["logs"]      = []

    if not device.is_client:
        t = threading.Thread(
            target=client_thread_fn,
            args=(device_id, device.ip_address, device.port, device.device_type, retry),
            daemon=True,
        )
    else:
        t = threading.Thread(
            target=server_thread_fn,
            args=(device_id, device.port, device.device_type),
            daemon=True,
        )

    with device_lock:
        device_states[device_id]["thread"] = t
    t.start()
    mode = "client" if not device.is_client else "server"
    return True, f"Started {mode} thread for {device.name}"


def disconnect_device(device_id: int):
    with device_lock:
        if device_id in device_states:
            device_states[device_id]["running"]   = False
            device_states[device_id]["connected"] = False
    device = get_device(device_id)
    if device and device.is_client and device.port in server_sockets:
        try:
            server_sockets[device.port].close()
        except Exception:
            pass
    set_device_online(device_id, False)
    add_log(device_id, "⏹ Disconnected by user", "warn")


def connect_all(retry: int = 10):
    db      = SessionLocal()
    devices = db.query(DeviceModel).all()
    db.close()
    results = []
    for d in devices:
        ok, msg = connect_device(d.id, retry)
        results.append({"device_id": d.id, "name": d.name,
                         "status": "started" if ok else "error", "message": msg})
    return results


def disconnect_all():
    db      = SessionLocal()
    devices = db.query(DeviceModel).all()
    db.close()
    for d in devices:
        disconnect_device(d.id)


def get_device_state(device_id: int) -> dict:
    with device_lock:
        return device_states.get(device_id, _default_state())


def get_all_states() -> dict:
    with device_lock:
        return {
            did: {
                "running":      s["running"],
                "connected":    s["connected"],
                "total":        s["total"],
                "errors":       s["errors"],
                "unknown":      s["unknown"],
                "last_barcode": s["last_barcode"],
                "logs":         s["logs"][-20:],
            }
            for did, s in device_states.items()
        }


def get_scan_log(limit: int = 100) -> list:
    """Return recent scan log entries, newest first."""
    with scan_lock:
        return list(reversed(scan_log[-limit:]))


def get_scan_summary() -> dict:
    """Return today's scan counts grouped by status."""
    today = datetime.date.today().isoformat()
    with scan_lock:
        today_scans = [s for s in scan_log if s["date"] == today]
    return {
        "today":     today,
        "total":     len(today_scans),
        "success":   sum(1 for s in today_scans if s["status"] == "success"),
        "unknown":   sum(1 for s in today_scans if s["status"] == "unknown"),
        "error":     sum(1 for s in today_scans if s["status"] == "error"),
        "duplicate": sum(1 for s in today_scans if s["status"] == "duplicate"),
        "scans":     list(reversed(today_scans)),
    }
