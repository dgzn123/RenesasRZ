#!/usr/bin/env python3
"""STL-19P LiDAR all-in-one — HTTP server + scanner subprocess + SSE. Port 8082."""
import http.server, subprocess, json, os, time, signal, threading
from socketserver import ThreadingMixIn

PORT = 8082
OUT = '/tmp/lidar_scan.json'
_proc = None
_auto_restart = True

# SSE clients
_sse_clients = []
_sse_lock = threading.Lock()

def sse_broadcast(data):
    payload = f"data: {data}\n\n".encode()
    with _sse_lock:
        dead = []
        for c in _sse_clients:
            try: c.write(payload); c.flush()
            except: dead.append(c)
        for d in dead: _sse_clients.remove(d)

SCANNER_CODE = r'''
import usb.backend.libusb1, usb.core, usb.util, struct, json, time, signal
S = "/tmp/lidar_scan.json"
signal.signal(signal.SIGTERM, lambda *a: None)

def parse_frame(buf):
    pts = []
    i, n = 0, len(buf)
    while i < n - 47:
        if buf[i] != 0x54:
            i += 1; continue
        if i + 47 > n: break
        try:
            if buf[i + 1] != 0x2C:
                i += 1; continue
            speed = struct.unpack_from("<H", buf, i + 2)[0]
            s_angle = struct.unpack_from("<H", buf, i + 4)[0] / 100.0
            e_angle = struct.unpack_from("<H", buf, i + 6 + 36)[0] / 100.0
            if s_angle > 360 or speed > 10000:
                i += 1; continue
            if e_angle < s_angle: e_angle += 360
            for p in range(12):
                off = i + 6 + p * 3
                dist_mm = struct.unpack_from("<H", buf, off)[0]
                if 20 < dist_mm < 16000:
                    alpha = p / 11.0
                    ang = (s_angle + alpha * (e_angle - s_angle)) % 360
                    pts.append([round(ang, 1), dist_mm])
        except: pass
        i += 1
    return pts

while True:
    try:
        be = usb.backend.libusb1.get_backend(find_library=lambda x: "/lib64/libusb-1.0.so")
        dev = usb.core.find(idVendor=0x10c4, idProduct=0xea60, backend=be)
        try: dev.detach_kernel_driver(0)
        except: pass
        try: dev.set_configuration()
        except: pass
        # STL-19P CP2102 init
        dev.ctrl_transfer(0x40, 0x1E, 0x0001, 0x0000, struct.pack("<I", 230400), 1000)
        dev.ctrl_transfer(0x40, 0x07, 0x0303, 0x0000, None, 1000)
        dev.ctrl_transfer(0x40, 0x03, 0x0800, 0x0000, None, 1000)
        dev.ctrl_transfer(0x40, 0x00, 0x0001, 0x0000, None, 1000)
        time.sleep(0.5)
        for _ in range(20):
            try: dev.read(0x81, 64, timeout=80)
            except: break
        buf, bins, last_flush = b"", {}, 0
        while True:
            try: data = bytes(dev.read(0x81, 1024, timeout=200))
            except: data = b""
            if data: buf += data
            if len(buf) > 4000: buf = buf[-2000:]
            pts = parse_frame(buf)
            if pts:
                for a, d in pts:
                    bins[int(a * 10) % 3600] = d
                buf = buf[-300:]
            now = time.time()
            if now - last_flush >= 0.05 and len(bins) > 60:
                out = [[k / 10.0, v] for k, v in sorted(bins.items())]
                with open(S, "w") as f: json.dump(out, f)
                bins = {}; last_flush = now
            time.sleep(0.002)
        try: usb.util.dispose_resources(dev)
        except: pass
    except Exception as e:
        print("Scanner:", e)
    time.sleep(2)
'''


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global _proc, _auto_restart
        p = self.path.split('?')[0]
        if p == '/stream':
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            wfile = self.wfile
            with _sse_lock:
                _sse_clients.append(wfile)
            last_mtime = 0
            try:
                while True:
                    try:
                        mtime = os.stat(OUT).st_mtime
                        if mtime != last_mtime:
                            last_mtime = mtime
                            with open(OUT, "r") as f:
                                data = f.read()
                            wfile.write(f"data: {data}\n\n".encode())
                            wfile.flush()
                    except Exception:
                        pass
                    time.sleep(0.04)
            except Exception:
                pass
            finally:
                with _sse_lock:
                    try: _sse_clients.remove(wfile)
                    except: pass
        elif p == '/scan':
            try: b = open(OUT, 'rb').read()
            except: b = b'[]'
        elif p == '/start':
            _auto_restart = True
            if _proc is None or _proc.poll() is not None:
                _proc = subprocess.Popen(['python3', '-c', SCANNER_CODE], preexec_fn=os.setsid)
            b = b'{"ok":true}'
        elif p == '/stop':
            _auto_restart = False
            if _proc:
                try: os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
                except: pass; _proc = None
            b = b'{"ok":true}'
        elif p == '/status':
            alive = _proc is not None and _proc.poll() is None
            try: pts = len(json.load(open(OUT)))
            except: pts = 0
            b = json.dumps({'scanning': alive, 'points': pts}).encode()
        else: self.send_error(404); return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(b))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass


def watch_scanner():
    global _proc
    while True:
        if _auto_restart and (_proc is None or _proc.poll() is not None):
            _proc = subprocess.Popen(['python3', '-c', SCANNER_CODE], preexec_fn=os.setsid)
        time.sleep(3)
threading.Thread(target=watch_scanner, daemon=True).start()

Svr = type('S', (ThreadingMixIn, http.server.HTTPServer), {'daemon_threads': True})
print(f"STL-19P LiDAR server: http://0.0.0.0:{PORT}")
Svr(("0.0.0.0", PORT), H).serve_forever()
