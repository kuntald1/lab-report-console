"""
MediCloud Local Backend
========================
Runs on the lab PC inside the local network.
Connects to lab machines via TCP/ASTM on the LAN.
Saves results to the remote cloud PostgreSQL database.

Usage:
    python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload

Or use the start scripts:
    Windows : start.bat
    Linux   : ./start.sh
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import devices, results, patients, simulate, pdf, tcp
from database import engine, Base

# Load environment variables from .env file
load_dotenv()

# Auto-create all DB tables on startup
Base.metadata.create_all(bind=engine)

# ── App ───────────────────────────────────────────────────────
APP_NAME    = os.getenv("APP_NAME",    "MediCloud Local Backend")
APP_VERSION = os.getenv("APP_VERSION", "3.0.0")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="MediCloud backend — runs inside the lab network to connect to lab analysers via TCP/ASTM"
)

# ── CORS ──────────────────────────────────────────────────────
raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
if raw_origins == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [o.strip() for o in raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────
app.include_router(devices.router,  prefix="/api/devices",  tags=["Devices"])
app.include_router(results.router,  prefix="/api/results",  tags=["Results"])
app.include_router(patients.router, prefix="/api/patients", tags=["Patients"])
app.include_router(simulate.router, prefix="/api/simulate", tags=["Simulate"])
app.include_router(pdf.router,      prefix="/api/results",  tags=["PDF"])
app.include_router(tcp.router,      prefix="/api/tcp",      tags=["TCP"])

# ── Auto-connect all devices on startup ───────────────────────
@app.on_event("startup")
async def auto_connect_all_devices():
    """Auto-connect all devices on startup — no need to click Connect All after restart"""
    import asyncio
    from services.tcp_manager import connect_all

    async def delayed_connect():
        await asyncio.sleep(3)
        results = connect_all(retry=10)
        print(f"[STARTUP] Auto-connected {len(results)} devices")
        for r in results:
            print(f"[STARTUP] {r['name']}: {r['status']} — {r['message']}")

    asyncio.create_task(delayed_connect())

# ── Health check ──────────────────────────────────────────────
@app.get("/")
def root():
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unknown"

    return {
        "app":     APP_NAME,
        "version": APP_VERSION,
        "status":  "ok",
        "message": "MediCloud local backend is running.",
        "docs":    "/docs",
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/status")
def status_dashboard():
    from fastapi.responses import FileResponse
    html_path = os.path.join(os.path.dirname(__file__), "status.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, media_type="text/html")
    return {"error": "status.html not found"}

@app.get("/info")
def info():
    """Returns real LAN IP — filters Docker internal IPs"""
    import socket

    hostname = socket.gethostname()
    all_ips  = []

    try:
        for res in socket.getaddrinfo(hostname, None):
            ip = res[4][0]
            if ":" not in ip and not ip.startswith("127."):
                if ip not in all_ips:
                    all_ips.append(ip)
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        outbound_ip = s.getsockname()[0]
        s.close()
        if outbound_ip not in all_ips:
            all_ips.append(outbound_ip)
    except Exception:
        pass

    def ip_priority(ip):
        if ip.startswith("192.168."): return 0
        if ip.startswith("10."):      return 1
        if ip.startswith("172."):     return 2
        return 3

    all_ips_sorted = sorted(all_ips, key=ip_priority)
    primary_ip     = all_ips_sorted[0] if all_ips_sorted else "unknown"
    port           = int(os.getenv("PORT", 8001))

    return {
        "status":      "ok",
        "hostname":    hostname,
        "primary_ip":  primary_ip,
        "all_ips":     all_ips_sorted,
        "port":        port,
        "backend_url": f"http://{primary_ip}:{port}",
        "api_base":    f"http://{primary_ip}:{port}/api",
        "status_url":  f"http://{primary_ip}:{port}/status",
    }

@app.get("/devices")
def devices_page():
    from fastapi.responses import FileResponse
    html_path = os.path.join(os.path.dirname(__file__), "devices.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, media_type="text/html")
    return {"error": "devices.html not found"}
