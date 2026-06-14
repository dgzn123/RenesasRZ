#!/usr/bin/env python3
"""UDP broadcast heartbeat sender for RZ/G2L — one JSON message per second."""
import socket
import json
import time
import argparse
import struct
from datetime import datetime, timezone

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


def get_broadcast_addr():
    """Auto-detect LAN broadcast address. Returns '255.255.255.255' as fallback."""
    candidates = []
    if _HAS_FCNTL:
        try:
            # SIOCGIFCONF: enumerate IPv4 interfaces on Linux
            import array
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            buf = array.array("B", b"\0" * 4096)
            ifconf = struct.pack("iP", 4096, buf.buffer_info()[0])
            _out = fcntl.ioctl(sock.fileno(), 0x8912, ifconf)  # SIOCGIFCONF
            size = struct.unpack("i", _out[:4])[0]
            data = buf.tobytes()[:size]
            idx = 0
            while idx < len(data):
                name_bytes = data[idx : idx + 16].split(b"\0", 1)[0]
                idx += 16
                addr = socket.inet_ntoa(data[idx : idx + 4])
                idx += 4
                if addr == "127.0.0.1":
                    continue
                # Get broadcast for this interface
                try:
                    info = fcntl.ioctl(sock.fileno(), 0x8919,
                                       struct.pack("256s", name_bytes))  # SIOCGIFBRDADDR
                    bcast = socket.inet_ntoa(info[20:24])
                    if bcast != "0.0.0.0":
                        candidates.append((name_bytes.decode(), addr, bcast))
                except OSError:
                    pass
            sock.close()
        except OSError:
            pass

    # Prefer 192.168.x.x subnet (matches wired IP from HANDOFF)
    for name, addr, bcast in candidates:
        if addr.startswith("192.168."):
            print(f"Broadcast: {bcast} (iface {name}, addr {addr})", flush=True)
            return bcast

    if candidates:
        name, addr, bcast = candidates[0]
        print(f"Broadcast: {bcast} (iface {name}, addr {addr})", flush=True)
        return bcast

    fallback = "255.255.255.255"
    print(f"Broadcast: {fallback} (fallback — no usable interface found)", flush=True)
    return fallback


def get_local_ip():
    """Get the board's primary LAN IP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a public address to force kernel to pick the default-route source IP.
        # No actual packets are sent (UDP connect is local-only).
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
    except OSError:
        ip = "0.0.0.0"
    finally:
        s.close()
    return ip


def main():
    parser = argparse.ArgumentParser(description="UDP broadcast heartbeat sender")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between sends (default 1.0)")
    parser.add_argument("--port", type=int, default=9999, help="UDP port (default 9999)")
    parser.add_argument("--host", default="renesas", help="Hostname in payload (default renesas)")
    parser.add_argument("--bcast", default=None, help="Broadcast address (auto-detected if omitted)")
    args = parser.parse_args()

    bcast = args.bcast or get_broadcast_addr()
    local_ip = get_local_ip()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # Allow multiple senders on the same port (safe reuse)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    seq = 0
    print(f"UDP heartbeat → {bcast}:{args.port}  interval={args.interval}s  host={args.host}  ip={local_ip}",
          flush=True)

    while True:
        payload = {
            "host": args.host,
            "ip": local_ip,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
            "seq": seq,
        }
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sock.sendto(data, (bcast, args.port))
        print(f"[{seq:06d}] sent {len(data)}B → {bcast}:{args.port}", flush=True)
        seq += 1
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
