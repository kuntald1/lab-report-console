# MediCloud Local Backend

Runs **inside the lab's local network** on a dedicated PC or laptop.
Connects to lab analysers via TCP/ASTM, saves results to cloud PostgreSQL DB.

---

## Two Ways to Run

| Method | When to use | Command |
|---|---|---|
| **Docker** ✅ Recommended | Lab's dedicated PC, permanent setup | `docker-start.bat` |
| **start.bat** | Your laptop, quick testing | `start.bat` |

---

## Quick Start — Docker (Recommended)

### Step 1 — Make sure Docker Desktop is running
Open Docker Desktop → wait for it to say "Running"

### Step 2 — Check your .env file
```
DATABASE_URL=postgresql://medicloud:medicloud123@187.127.150.252:5433/medicloud_db
HOST=0.0.0.0
PORT=8001
ALLOWED_ORIGINS=https://medicloud.mooo.com,http://localhost:5173
```

### Step 3 — Double-click docker-start.bat
First time takes 2-3 minutes (downloads Python image).
After that starts in under 10 seconds every time.

### Step 4 — Browser opens automatically
```
http://localhost:8001/devices  ← Main working page
http://localhost:8001/status   ← System health monitor
http://localhost:8001/docs     ← API documentation
```

---

## Docker Commands

```bash
docker-compose up -d          # Start in background
docker-compose down           # Stop
docker-compose logs -f        # Watch live logs
docker-compose restart        # Restart
docker-compose up -d --build  # Rebuild after code changes
```

---

## Tomorrow at the Lab

```
1. Connect laptop to lab LAN (cable or WiFi)
2. Double-click docker-start.bat
3. Browser opens at http://localhost:8001/devices
4. Note your LAN IP from status page (e.g. 192.168.0.50)
5. Ask maintenance boy to enable LIS/TCP on each machine
6. Click Connect All
7. Run one test sample
8. Check medicloud.mooo.com → Results ✅
```

---

## Moving to Lab Dedicated PC

```
1. Install Docker Desktop on lab PC
2. Copy this folder to lab PC
3. Double-click docker-start.bat
4. Done — runs 24/7, auto-restarts on reboot
```
