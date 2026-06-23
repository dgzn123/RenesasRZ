#!/usr/bin/env python3
"""HTTP ↔ UART 桥接 — RZ/G2L ↔ RA8P1。端口 8084，文本行协议。"""
import http.server, serial, threading, json
from urllib.parse import parse_qs, urlsplit
from socketserver import ThreadingMixIn

PORT = 8084
SERIAL_PORT = '/dev/ttySC0'
BAUD = 115200

ser = None

# ── 串口接收缓冲区 ──
rx_lines = []
rx_lock = threading.Lock()
_sse_clients = []
_sse_lock = threading.Lock()

ARM_MIN = [-180, -90, -150, -150]
ARM_MAX = [180, 90, 150, 90]


def normalize_cmd(cmd):
    """Return (ok, normalized_cmd, error). ARM protocol: $ARM,BASE,J1,J2,J3."""
    cmd = (cmd or '').strip()
    if not cmd:
        return False, '', 'empty command'

    parts = [p.strip() for p in cmd.split(',')]
    if parts[0].upper() != '$ARM':
        return True, cmd, ''

    values = parts[1:]
    if len(values) == 3:
        values = ['0'] + values
    if len(values) != 4:
        return False, '', 'ARM command must be $ARM,BASE,J1,J2,J3'

    nums = []
    for idx, raw in enumerate(values):
        try:
            n = int(round(float(raw)))
        except ValueError:
            return False, '', f'ARM field {idx + 1} is not numeric'
        lo, hi = ARM_MIN[idx], ARM_MAX[idx]
        if n < lo or n > hi:
            return False, '', f'ARM field {idx + 1} out of range {lo}..{hi}'
        nums.append(n)

    return True, '$ARM,' + ','.join(str(n) for n in nums), ''

def reader():
    buf = b''
    while True:
        try:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    text = line.decode(errors='replace').strip()
                    if text:
                        with rx_lock:
                            rx_lines.append(text)
                            if len(rx_lines) > 200:
                                rx_lines.pop(0)
                        sse_broadcast(text)
        except Exception:
            pass


def sse_broadcast(msg):
    payload = f'data: {msg}\n\n'.encode()
    with _sse_lock:
        dead = []
        for c in _sse_clients:
            try:
                c.write(payload); c.flush()
            except Exception:
                dead.append(c)
        for d in dead:
            _sse_clients.remove(d)


# ── HTTP Handler ──
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        p = self.path.split('?')[0]
        b = b''

        if p == '/send':
            # /send?cmd=$ARM,180,45,30,10
            qs = parse_qs(urlsplit(self.path).query)
            cmd = qs.get('cmd', [''])[0]
            ok, cmd, err = normalize_cmd(cmd)
            if ok:
                ser.write((cmd + '\n').encode())
                b = json.dumps({'ok': True, 'cmd': cmd}).encode()
            else:
                b = json.dumps({'ok': False, 'error': err}).encode()

        elif p == '/read':
            with rx_lock:
                b = json.dumps({'messages': list(rx_lines)}).encode()

        elif p == '/status':
            b = json.dumps({
                'serial_port': SERIAL_PORT,
                'baud': BAUD,
                'open': ser.is_open
            }).encode()

        elif p == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            wfile = self.wfile
            with _sse_lock:
                _sse_clients.append(wfile)
            try:
                while True:
                    import time
                    time.sleep(1)
            except Exception:
                pass
            finally:
                with _sse_lock:
                    try:
                        _sse_clients.remove(wfile)
                    except Exception:
                        pass
            return

        else:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(b))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


def main():
    global ser
    import os
    ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.05)
    ser.reset_input_buffer()
    os.system(f'stty -F {SERIAL_PORT} -onlcr 2>/dev/null')  # 禁止 \n → \r\n 转换
    threading.Thread(target=reader, daemon=True).start()

    Svr = type('S', (ThreadingMixIn, http.server.HTTPServer), {'daemon_threads': True})
    print(f'serial_bridge: http://0.0.0.0:{PORT}  →  {SERIAL_PORT} @ {BAUD}bps')
    Svr(('0.0.0.0', PORT), H).serve_forever()


if __name__ == '__main__':
    main()
