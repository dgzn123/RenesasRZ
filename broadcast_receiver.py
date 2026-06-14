#!/usr/bin/env python3
"""UDP broadcast heartbeat receiver — listens on 0.0.0.0:9999 and prints every message."""
import socket
import json
import time
import argparse
from datetime import datetime, timezone


def fmt_ts(iso_ts):
    """Convert ISO UTC ts to local time for display."""
    try:
        # Strip trailing Z and parse
        t = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        local = t.astimezone()
        return local.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return iso_ts


def main():
    parser = argparse.ArgumentParser(description="UDP broadcast heartbeat receiver")
    parser.add_argument("--port", type=int, default=9999, help="UDP port (default 9999)")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address (default 0.0.0.0)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind, args.port))

    print(f"Listening for UDP broadcasts on {args.bind}:{args.port} ...", flush=True)
    print(f"{'Time':>8}  {'Seq':>8}  {'Host':<12}  {'IP':<16}  {'Latency(ms)':>11}",
          flush=True)
    print("-" * 68, flush=True)

    last_seq = None
    lost = 0
    start_time = time.time()
    received = 0
    last_stats = start_time

    while True:
        data, addr = sock.recvfrom(4096)
        now_ts = time.time()
        received += 1

        # Periodic stats every 10 s
        if now_ts - last_stats >= 10:
            elapsed = now_ts - start_time
            rate = received / elapsed if elapsed > 0 else 0
            print(f"--- STATS: {received} pkts in {elapsed:.0f}s ({rate:.1f}/s), {lost} lost ({100*lost/max(received,1):.1f}%) ---",
                  flush=True)
            last_stats = now_ts

        try:
            msg = json.loads(data.decode("utf-8"))
            seq = msg.get("seq", "?")
            host = msg.get("host", "?")
            ip = msg.get("ip", addr[0])
            ts = msg.get("ts", "")

            # Latency estimate: current time vs message timestamp
            latency = ""
            if ts:
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    latency_ms = (now_ts - t.timestamp()) * 1000
                    latency = f"{latency_ms:9.1f}"
                except (ValueError, AttributeError):
                    latency = "        N/A"

            # Seq gap detection
            gap = ""
            if isinstance(seq, int) and last_seq is not None:
                diff = seq - last_seq
                if diff > 1:
                    gap = f"  ⚠ GAP {diff - 1} lost"
                    lost += diff - 1
            if isinstance(seq, int):
                last_seq = seq

            print(f"{fmt_ts(ts) if ts else '--:--:--':>8}  {seq!s:>8}  {host:<12}  {ip:<16}  {latency}{gap}",
                  flush=True)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"(raw {len(data)}B from {addr[0]}:{addr[1]}) {data[:120]!r}", flush=True)


if __name__ == "__main__":
    main()
