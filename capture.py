#!/usr/bin/env python3
"""MJPEG stream server — V4L2 mmap (no ffmpeg). PHP manages process lifecycle."""

import http.server
import os
import fcntl
import mmap
import json
import time
import threading
import struct
import glob
import subprocess
from datetime import datetime
from socketserver import ThreadingMixIn

WIDTH = 1280
HEIGHT = 720
DEVICE = os.environ.get("CAMERA_DEVICE", "auto")
PORT = 8080
NUM_BUFS = 4
PHOTO_DIR = "/home/root/camera-server/photos"

# ── V4L2 ioctl ─────────────────────────────────────────────────
def _IOC(dir, ch, nr, size):
    return (dir << 30) | (ord(ch) << 8) | (nr << 0) | (size << 16)
_IOWR = lambda ch, nr, size: _IOC(3, ch, nr, size)
_IOW  = lambda ch, nr, size: _IOC(1, ch, nr, size)

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_FIELD_NONE = 0
V4L2_MEMORY_MMAP = 1

VIDIOC_S_FMT = _IOWR('V', 5, 208)
VIDIOC_REQBUFS = _IOWR('V', 8, 20)
VIDIOC_QUERYBUF = _IOWR('V', 9, 88)
VIDIOC_QBUF = _IOWR('V', 15, 88)
VIDIOC_DQBUF = _IOWR('V', 17, 88)
VIDIOC_STREAMON = _IOW('V', 18, 4)
VIDIOC_STREAMOFF = _IOW('V', 19, 4)


def select_video_device():
    if DEVICE != "auto":
        return DEVICE

    for dev in sorted(glob.glob("/dev/video*")):
        try:
            info = subprocess.run(
                ["v4l2-ctl", "-d", dev, "--all"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=2,
            ).stdout
            if "Device Caps" in info and "Video Capture" in info and "Metadata Capture" not in info.split("Device Caps", 1)[1].splitlines()[1:3]:
                print(f"Selected camera device: {dev}", flush=True)
                return dev
        except Exception as exc:
            print(f"Skipping camera device {dev}: {exc}", flush=True)

    # Fallback for systems without v4l2-ctl.
    for dev in sorted(glob.glob("/dev/video*")):
        print(f"Selected fallback camera device: {dev}", flush=True)
        return dev
    raise FileNotFoundError("No /dev/video* device found")


def v4l2_setup(dev, width, height):
    fd = os.open(dev, os.O_RDWR)

    fmt = bytearray(208)
    struct.pack_into('<I', fmt, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
    struct.pack_into('<I', fmt, 8, width)
    struct.pack_into('<I', fmt, 12, height)
    struct.pack_into('<I', fmt, 16, 0x47504A4D)
    struct.pack_into('<I', fmt, 20, V4L2_FIELD_NONE)
    fcntl.ioctl(fd, VIDIOC_S_FMT, fmt)

    req = bytearray(20)
    struct.pack_into('<I', req, 0, NUM_BUFS)
    struct.pack_into('<I', req, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
    struct.pack_into('<I', req, 8, V4L2_MEMORY_MMAP)
    fcntl.ioctl(fd, VIDIOC_REQBUFS, req)

    buffers = []
    for i in range(NUM_BUFS):
        buf = bytearray(88)
        struct.pack_into('<I', buf, 0, i)
        struct.pack_into('<I', buf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into('<I', buf, 60, V4L2_MEMORY_MMAP)
        fcntl.ioctl(fd, VIDIOC_QUERYBUF, buf)
        offset = struct.unpack_from('<I', buf, 64)[0]
        length = struct.unpack_from('<I', buf, 72)[0]
        m = mmap.mmap(fd, length, mmap.MAP_SHARED,
                      mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
        buffers.append((m, length))

    for i in range(NUM_BUFS):
        qbuf = bytearray(88)
        struct.pack_into('<I', qbuf, 0, i)
        struct.pack_into('<I', qbuf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into('<I', qbuf, 60, V4L2_MEMORY_MMAP)
        fcntl.ioctl(fd, VIDIOC_QBUF, qbuf)

    stype = bytearray(4)
    struct.pack_into('<I', stype, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
    fcntl.ioctl(fd, VIDIOC_STREAMON, stype)

    return fd, buffers


def v4l2_teardown(fd, buffers):
    try:
        stype = bytearray(4)
        struct.pack_into('<I', stype, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(fd, VIDIOC_STREAMOFF, stype)
    except OSError:
        pass
    for m, _ in buffers:
        m.close()
    os.close(fd)


# ── Shared state ───────────────────────────────────────────────
_lock = threading.Lock()
_latest_frame = b''
_fps = 0.0
_running = False
_producer_thread = None
_last_error = ""
_active_device = ""


def producer():
    global _latest_frame, _fps, _last_error, _active_device

    fd = None
    buffers = []
    ts = []
    try:
        _last_error = ""
        _active_device = select_video_device()
        fd, buffers = v4l2_setup(_active_device, WIDTH, HEIGHT)
        while _running:
            dqbuf = bytearray(88)
            struct.pack_into('<I', dqbuf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            struct.pack_into('<I', dqbuf, 60, V4L2_MEMORY_MMAP)
            try:
                fcntl.ioctl(fd, VIDIOC_DQBUF, dqbuf)
            except OSError:
                break

            idx = struct.unpack_from('<I', dqbuf, 0)[0]
            bytesused = struct.unpack_from('<I', dqbuf, 8)[0]
            frame = bytes(buffers[idx][0][:bytesused])

            qbuf = bytearray(88)
            struct.pack_into('<I', qbuf, 0, idx)
            struct.pack_into('<I', qbuf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            struct.pack_into('<I', qbuf, 60, V4L2_MEMORY_MMAP)
            fcntl.ioctl(fd, VIDIOC_QBUF, qbuf)

            soi = frame.find(b'\xff\xd8')
            if soi >= 0:
                frame = frame[soi:]

            now = time.monotonic()
            ts.append(now)
            if len(ts) > 32:
                ts.pop(0)
            fps_val = 0.0
            if len(ts) >= 2:
                fps_val = (len(ts) - 1) / (ts[-1] - ts[0])

            with _lock:
                _latest_frame = frame
                _fps = fps_val
    except Exception as exc:
        _last_error = repr(exc)
        print(f"Camera producer error: {_last_error}", flush=True)
    finally:
        if fd is not None:
            v4l2_teardown(fd, buffers)
        with _lock:
            _latest_frame = b''
            _fps = 0.0


def start_producer():
    global _running, _producer_thread
    with _lock:
        if _running:
            return
        _running = True
    _producer_thread = threading.Thread(target=producer, daemon=True)
    _producer_thread.start()


def stop_producer():
    global _running
    with _lock:
        if not _running:
            return
        _running = False
    if _producer_thread and _producer_thread.is_alive():
        _producer_thread.join(timeout=5.0)


def capture_one_frame(width, height):
    dev = _active_device or select_video_device()
    fd, buffers = v4l2_setup(dev, width, height)
    try:
        for _ in range(10):
            dqbuf = bytearray(88)
            struct.pack_into('<I', dqbuf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            struct.pack_into('<I', dqbuf, 60, V4L2_MEMORY_MMAP)
            fcntl.ioctl(fd, VIDIOC_DQBUF, dqbuf)
            idx = struct.unpack_from('<I', dqbuf, 0)[0]
            bytesused = struct.unpack_from('<I', dqbuf, 8)[0]
            qbuf = bytearray(88)
            struct.pack_into('<I', qbuf, 0, idx)
            struct.pack_into('<I', qbuf, 4, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            struct.pack_into('<I', qbuf, 60, V4L2_MEMORY_MMAP)
            fcntl.ioctl(fd, VIDIOC_QBUF, qbuf)
        frame = bytes(buffers[idx][0][:bytesused])
        soi = frame.find(b'\xff\xd8')
        return frame[soi:] if soi >= 0 else frame
    finally:
        v4l2_teardown(fd, buffers)


class MjpegHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == "/stream":
            self._send_stream()
        elif path == "/snapshot":
            self._send_snapshot()
        elif path == "/status":
            self._send_status()
        elif path == "/photo":
            self._take_photo()
        elif path == "/pause":
            stop_producer()
            self._send_json({"ok": True})
        elif path == "/resume":
            start_producer()
            self._send_json({"ok": True})
        else:
            self.send_error(404)

    def _send_json(self, obj, status=200):
        data = json.dumps(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data.encode())

    def _send_status(self):
        with _lock:
            data = json.dumps({
                "width": WIDTH, "height": HEIGHT,
                "fps": _fps, "running": _running,
                "device": _active_device,
                "error": _last_error
            })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data.encode())

    def _send_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            last = None
            while True:
                with _lock:
                    frame = _latest_frame
                    running = _running
                if running and frame and frame is not last:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    last = frame
                time.sleep(0.005)  # 200 polls/sec, low CPU
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_snapshot(self):
        with _lock:
            data = _latest_frame
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(data) if data else 0)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _take_photo(self):
        if not _running:
            self._send_json({"ok": False, "error": "stream not running"}, 409)
            return

        try:
            os.makedirs(PHOTO_DIR, exist_ok=True)
            filename = datetime.now().strftime("photo_%Y%m%d_%H%M%S.jpg")
            filepath = os.path.join(PHOTO_DIR, filename)

            with _lock:
                frame = _latest_frame
            if not frame:
                self._send_json({"ok": False, "error": "no frame available"}, 503)
                return

            with open(filepath, 'wb') as f:
                f.write(frame)

            fsize = os.path.getsize(filepath)
            self._send_json({"ok": True, "file": filename, "size": fsize})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def log_message(self, format, *args):
        pass


class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    os.makedirs(PHOTO_DIR, exist_ok=True)
    start_producer()

    for _ in range(50):
        with _lock:
            if _latest_frame:
                break
        time.sleep(0.1)

    print(f"Camera server: http://0.0.0.0:{PORT}")
    print(f"  /stream  — MJPEG video (V4L2 mmap)")
    print(f"  /status  — JSON status")
    print(f"  /photo   — 1080p snapshot -> {PHOTO_DIR}")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), MjpegHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
