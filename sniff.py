"""
GH-900 TCP Sniffer v3 — ENQ/ACK ASTM handler
Protocol confirmed from official Lifotronic GH-900 Plus LIS document:
  Machine → ENQ (0x05) : ready to send
  PC → ACK (0x06)      : go ahead
  Machine → STX frames : ASTM data (H/P/O/R/L records)
  PC → ACK each ETX frame
  Machine → EOT (0x04) : done
"""
import socket
import threading
import time

LISTEN_PORT  = 8080
FORWARD_HOST = "127.0.0.1"
FORWARD_PORT = 7777

ENQ = b'\x05'
ACK = b'\x06'
EOT = b'\x04'
ETX = b'\x03'
STX = b'\x02'
NAK = b'\x15'


def handle(conn, addr):
    print(f"\n[{time.strftime('%H:%M:%S')}] ✅ Connected from {addr[0]}:{addr[1]}")

    try:
        fwd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        fwd.settimeout(3)
        fwd.connect((FORWARD_HOST, FORWARD_PORT))
        print(f"[{time.strftime('%H:%M:%S')}] 🔀 Forwarding to Docker:{FORWARD_PORT}")
    except Exception as e:
        fwd = None
        print(f"[{time.strftime('%H:%M:%S')}] ⚠️  Docker unreachable — sniff only: {e}")

    raw_bytes = b""
    all_received = b""

    try:
        conn.settimeout(300)  # 5 min — operator needs time to upload

        print(f"[{time.strftime('%H:%M:%S')}] 👂 Waiting for ENQ from machine...")

        while True:
            chunk = conn.recv(4096)
            if not chunk:
                print(f"[{time.strftime('%H:%M:%S')}] 🔌 Disconnected")
                break

            all_received += chunk
            print(f"[{time.strftime('%H:%M:%S')}] 📨 {len(chunk)}B: hex={chunk.hex()} txt={repr(chunk[:60])}")

            if fwd:
                try:
                    fwd.sendall(chunk)
                except Exception:
                    pass

            # ENQ — machine wants to send, reply ACK
            if ENQ in chunk:
                print(f"[{time.strftime('%H:%M:%S')}] ↩️  ENQ received → sending ACK")
                conn.sendall(ACK)
                if fwd:
                    try: fwd.sendall(ACK)
                    except: pass
                continue

            # ETX — end of frame, ACK it
            if ETX in chunk:
                print(f"[{time.strftime('%H:%M:%S')}] ↩️  ETX frame → sending ACK")
                conn.sendall(ACK)
                raw_bytes += chunk

            # EOT — end of full transmission
            if EOT in chunk:
                print(f"[{time.strftime('%H:%M:%S')}] ✅ EOT — full transmission received!")
                raw_bytes += chunk
                cleaned = (raw_bytes
                           .replace(STX, b"").replace(ETX, b"")
                           .replace(EOT, b"").replace(ENQ, b"").replace(ACK, b""))
                text = cleaned.decode("ascii", errors="ignore").strip()
                print(f"\n{'='*60}")
                print(f"PARSED ASTM DATA:")
                print(text)
                print(f"{'='*60}\n")
                raw_bytes = b""
                continue

            if chunk not in (ENQ, ACK):
                raw_bytes += chunk

    except socket.timeout:
        print(f"[{time.strftime('%H:%M:%S')}] ⏰ 5min timeout")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ {e}")
    finally:
        print(f"\nTotal bytes seen: {len(all_received)}B | hex: {all_received.hex() or 'EMPTY'}")
        conn.close()
        if fwd:
            fwd.close()


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", LISTEN_PORT))
    srv.listen(10)
    print(f"[{time.strftime('%H:%M:%S')}] 🟢 GH-900 sniffer v3 on port {LISTEN_PORT}")
    print(f"[{time.strftime('%H:%M:%S')}] Protocol: wait for ENQ → ACK → receive ASTM frames")
    print("Press Ctrl+C to stop\n")
    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
