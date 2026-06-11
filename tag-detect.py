#!/usr/bin/env python3
"""ArUco tag detection for meter localization. Fetches frames from capture.py HTTP."""

import http.server
import json
import time
import threading
import urllib.request
from socketserver import ThreadingMixIn

import cv2
import numpy as np

PORT = 8085
CAM_SNAPSHOT_URL = "http://127.0.0.1:8080/snapshot"
CONFIG_FILE = "/home/root/tag/tags_config.json"

# 4x4 50-ID dictionary — small footprint, good for close-range
ARUCO_DICT = cv2.aruco.DICT_4X4_50

# ── Load tag config ─────────────────────────────────────────────
def load_tag_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

_tag_config = load_tag_config()

# ── Shared state ────────────────────────────────────────────────
_lock = threading.Lock()
_latest = {
    "ok": False,
    "tags": [],
    "meter_roi": None,
    "elapsed_ms": 0,
    "timestamp": 0,
    "preview_jpg": None
}


def fetch_frame():
    """Pull one JPEG frame from capture.py snapshot endpoint."""
    try:
        req = urllib.request.urlopen(CAM_SNAPSHOT_URL, timeout=3)
        return req.read()
    except Exception:
        return None


def detect_markers(jpg_bytes):
    """Detect ArUco markers and compute meter ROI above the first tag found."""
    t0 = time.monotonic()
    img = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "error": "decode failed"}, None

    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    params = cv2.aruco.DetectorParameters()
    # Compatible with both OpenCV 4.x and 4.10+
    try:
        corners, ids, _ = cv2.aruco.detectMarkers(img, aruco_dict, parameters=params)
    except AttributeError:
        detector = cv2.aruco.ArucoDetector(aruco_dict, params)
        corners, ids, _ = detector.detectMarkers(img)
    elapsed = (time.monotonic() - t0) * 1000

    tags = []
    meter_roi = None

    if ids is not None and len(corners) > 0:
        for i, corner in enumerate(corners):
            c = corner[0]
            cx = float(np.mean(c[:, 0]))
            cy = float(np.mean(c[:, 1]))
            tag_id = int(ids[i][0])
            pts = [[float(c[j][0]), float(c[j][1])] for j in range(4)]

            # Lookup meter parameters from config
            cfg = _tag_config.get(str(tag_id), {})
            tags.append({
                "id": tag_id,
                "cx": round(cx, 1),
                "cy": round(cy, 1),
                "corners": [[round(p[0], 1), round(p[1], 1)] for p in pts],
                "name": cfg.get("name", ""),
                "min": cfg.get("min", None),
                "max": cfg.get("max", None),
                "divisions": cfg.get("divisions", None)
            })

        # Meter ROI: above the first tag, centered horizontally
        c0 = corners[0][0]
        tag_top = float(np.min(c0[:, 1]))
        tag_left = float(np.min(c0[:, 0]))
        tag_right = float(np.max(c0[:, 0]))
        tag_h = float(np.max(c0[:, 1])) - tag_top

        x1 = max(0, int(tag_left - tag_h * 0.5))
        y1 = max(0, int(tag_top - tag_h * 3.5))
        x2 = min(img.shape[1], int(tag_right + tag_h * 0.5))
        y2 = max(0, int(tag_top - tag_h * 0.5))
        meter_roi = [x1, y1, x2, y2]

        # Annotate preview image
        cv2.aruco.drawDetectedMarkers(img, corners, ids)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 47, 167), 2)
        cv2.putText(img, "METER", (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 47, 167), 2)
        for t in tags:
            label = f"ID:{t['id']}"
            if t.get("name"):
                label += f" {t['name']}"
            cv2.putText(img, label,
                        (int(t['cx']) + 10, int(t['cy'])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)

    ok, preview = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    result = {
        "ok": True,
        "tags": tags,
        "meter_roi": meter_roi,
        "elapsed_ms": round(elapsed, 1),
        "timestamp": time.time()
    }
    preview_jpg = preview.tobytes() if ok else None
    return result, preview_jpg


def do_detect():
    """Fetch frame, run detection, update shared state."""
    global _latest
    jpg = fetch_frame()
    if jpg is None:
        with _lock:
            _latest = {"ok": False, "error": "camera unreachable", "tags": [], "meter_roi": None}
        return

    result, preview = detect_markers(jpg)
    result["preview_jpg"] = preview
    with _lock:
        _latest = result


# ── HTTP handler ─────────────────────────────────────────────────
class TagHandler(http.server.BaseHTTPRequestHandler):

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, default=str)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data.encode())

    def _send_jpeg(self, jpg_bytes):
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(jpg_bytes)))
        self.end_headers()
        self.wfile.write(jpg_bytes)

    def do_GET(self):
        global _tag_config
        path = self.path.split("?")[0]
        if path == "/detect":
            do_detect()
            with _lock:
                resp = {k: _latest[k] for k in ["ok", "tags", "meter_roi", "elapsed_ms", "timestamp"]}
            self._send_json(resp)
        elif path == "/preview":
            with _lock:
                if _latest.get("preview_jpg"):
                    self._send_jpeg(_latest["preview_jpg"])
                else:
                    self.send_error(404)
        elif path == "/locate":
            # Combined: detect + return both JSON and preview in one call
            do_detect()
            with _lock:
                resp = {k: _latest[k] for k in ["ok", "tags", "meter_roi", "elapsed_ms"]}
                preview = _latest.get("preview_jpg")
            resp["has_preview"] = preview is not None
            self._send_json(resp)
        elif path == "/status":
            with _lock:
                resp = {k: _latest[k] for k in ["ok", "tags", "meter_roi", "elapsed_ms"]}
            self._send_json(resp)
        elif path == "/quit":
            self._send_json({"ok": True, "bye": "shutting down"})
            import os as _os
            _os._exit(0)
        elif path == "/config":
            self._send_json({"tags": _tag_config})
        elif path == "/reload":
            _tag_config = load_tag_config()
            self._send_json({"ok": True, "count": len(_tag_config)})
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


def main():
    import sys
    global PORT
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            PORT = int(arg.split("=", 1)[1])

    print(f"Tag detect server: http://0.0.0.0:{PORT}")
    print(f"  /detect  — run detection, return JSON")
    print(f"  /locate  — run detection, return JSON (caller then GETs /preview)")
    print(f"  /preview — last annotated JPEG")
    print(f"  /status  — last cached result (no new detection)")
    print(f"  Frame source: {CAM_SNAPSHOT_URL}")

    Svr = type("S", (ThreadingMixIn, http.server.HTTPServer), {"daemon_threads": True})
    Svr(("0.0.0.0", PORT), TagHandler).serve_forever()


if __name__ == "__main__":
    main()
