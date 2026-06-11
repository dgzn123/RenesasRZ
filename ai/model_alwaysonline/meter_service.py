#!/usr/bin/env python3
"""
meter_service.py — Resident two-stage meter reading inference service.

Loads ROI + four-point YOLO ONNX models once at startup, then serves
inference requests over HTTP. Eliminates the ~2.5 s cold-start penalty
of the one-shot meter_reader_onnx.py script.

Usage:
    python3 meter_service.py --yolo ../best_points_320.onnx --roi-yolo ../meter_roi.onnx
    python3 meter_service.py --yolo ../best_points_320.onnx --roi-yolo ../meter_roi.onnx --port 8086 --profile ../meter_profiles.json

Endpoints:
    GET /health   → {"ok": true, "uptime_s": ...}
    GET /status   → model info, request stats, loaded profiles
    GET /read     → run inference (see inline docs for params)
"""

import argparse
import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
import onnxruntime as ort

# Allow import from parent ai/ directory
_AI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AI_DIR not in sys.path:
    sys.path.insert(0, _AI_DIR)
from meter_reader_onnx import (  # noqa: E402
    CLASS_NAMES, IMG_SIZE, REQUIRED, ROI_IMG_SIZE,
    compute_reading, decode_yolov8, detect_points, detect_roi,
    draw_debug, letterbox, nms, preprocess, resize_preprocess,
)

# ─── Globals (populated at startup) ─────────────────────────────────────────
roi_session = None
point_session = None
profiles = {}
started = 0.0
config = {}
request_count = 0
total_inference_ms = 0.0


def build_session(model_path, num_threads=2):
    """Create an ONNX Runtime session with memory-conscious defaults."""
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = num_threads
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    opts.enable_cpu_mem_arena = True
    return ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])


def do_inference(image_path, min_val, max_val, divisions,
                 offset=0.0, conf=0.25, roi_conf=0.25, roi_expand=0.2,
                 iou=0.45, direction="auto", clamp=True, debug_image=None):
    """Run two-stage inference. Returns dict — always has 'success' key."""
    global request_count, total_inference_ms
    t0 = time.perf_counter()

    image = cv2.imread(image_path)
    if image is None:
        return {"success": False, "error": f"Cannot read image: {image_path}"}

    roi_box = None
    crop_origin = (0, 0)
    meter_image = image

    if roi_session is not None:
        roi_box, rc = detect_roi(roi_session, image, roi_conf, roi_expand)
        if roi_box is None:
            return {"success": False, "error": f"No meter ROI detected (best conf={rc:.3f})"}
        x1, y1, x2, y2 = roi_box
        crop_origin = (x1, y1)
        meter_image = image[y1:y2, x1:x2]

    points, detections = detect_points(point_session, meter_image, conf, iou)

    missing = [n for n in REQUIRED if n not in points]
    if missing:
        return {
            "success": False,
            "error": f"Missing required point(s): {', '.join(missing)}",
            "present": {k: round(v["confidence"], 3) for k, v in points.items()},
            "detections": detections,
        }

    reading_info = compute_reading(points, min_val, max_val, divisions,
                                   direction=direction, offset=offset, clamp=clamp)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    request_count += 1
    total_inference_ms += elapsed_ms

    result = {
        "success": True,
        "reading": reading_info["reading"],
        "min": min_val,
        "max": max_val,
        "divisions": divisions,
        "offset": offset,
        "elapsed_ms": round(elapsed_ms, 1),
        "points": points,
        "geometry": reading_info,
    }

    if debug_image:
        draw_debug(image, points, detections, debug_image, reading_info, roi_box, crop_origin)
        result["debug_image"] = debug_image

    return result


class MeterHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the meter reading service."""

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}", file=sys.stderr, flush=True)

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _ok(self, data):
        self._json(200, data)

    def _err(self, status, msg):
        self._json(status, {"ok": False, "error": msg})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        # ── /health ──────────────────────────────────────────────────
        if path == "/health":
            self._ok({"ok": True, "uptime_s": round(time.time() - started, 1)})
            return

        # ── /status ──────────────────────────────────────────────────
        if path == "/status":
            avg = round(total_inference_ms / request_count, 1) if request_count else 0
            self._ok({
                "ok": True,
                "uptime_s": round(time.time() - started, 1),
                "roi_model": config.get("roi_yolo", "none"),
                "point_model": config.get("yolo", "none"),
                "requests": request_count,
                "total_inference_ms": round(total_inference_ms, 1),
                "avg_inference_ms": avg,
                "profiles_loaded": list(profiles.keys()) if profiles else [],
            })
            return

        # ── /read ────────────────────────────────────────────────────
        if path == "/read":
            image = params.get("image", [None])[0]
            if not image:
                self._err(400, "Missing required param: image")
                return

            # Resolve range: explicit params take priority, then profile
            profile_file = params.get("profile", [None])[0]
            profile_name = params.get("profile_name", ["default"])[0]

            p = {}
            if profile_file:
                if profile_file not in profiles:
                    try:
                        with open(profile_file, "r") as f:
                            profiles[profile_file] = json.load(f)
                    except Exception as e:
                        self._err(400, f"Failed to load profile: {e}")
                        return
                p = profiles[profile_file].get(profile_name, {})

            try:
                mn = float(params.get("min", [p.get("min")])[0])
                mx = float(params.get("max", [p.get("max")])[0])
                dv = int(params.get("divisions", [p.get("divisions")])[0])
            except (TypeError, ValueError):
                self._err(400, "min/max/divisions required (or provide profile/profile_name)")
                return

            # Optional parameters
            offset = float(params.get("offset", [0])[0])
            conf = float(params.get("conf", [0.25])[0])
            roi_conf = float(params.get("roi_conf", [0.25])[0])
            roi_expand = float(params.get("roi_expand", [0.2])[0])
            iou = float(params.get("iou", [0.45])[0])
            direction = params.get("direction", ["auto"])[0]
            clamp = "no_clamp" not in params
            debug = params.get("debug_image", [None])[0]

            result = do_inference(
                image, mn, mx, dv,
                offset=offset, conf=conf, roi_conf=roi_conf,
                roi_expand=roi_expand, iou=iou,
                direction=direction, clamp=clamp, debug_image=debug,
            )

            if result["success"]:
                self._ok(result)
            else:
                self._json(422, result)
            return

        self._err(404, f"Unknown endpoint: {path}")


def main():
    global roi_session, point_session, profiles, started, config

    parser = argparse.ArgumentParser(description="Resident meter reading inference service")
    parser.add_argument("--yolo", required=True, help="Four-point YOLOv8n-320 ONNX model path")
    parser.add_argument("--roi-yolo", help="First-stage meter ROI ONNX model path (optional)")
    parser.add_argument("--port", type=int, default=8086, help="HTTP listen port (default: 8086)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--threads", type=int, default=2, help="ORT intra-op threads (default: 2)")
    parser.add_argument("--profile", help="Optional meter profiles JSON file")
    args = parser.parse_args()

    config = vars(args)

    print("=" * 50, flush=True)
    print("Meter Reading Inference Service", flush=True)
    print("=" * 50, flush=True)

    # ── Load models ──────────────────────────────────────────────────
    print(f"\nLoading point model: {args.yolo}", flush=True)
    t0 = time.perf_counter()
    point_session = build_session(args.yolo, args.threads)
    print(f"  OK ({1000 * (time.perf_counter() - t0):.0f} ms)", flush=True)

    if args.roi_yolo:
        print(f"Loading ROI model:   {args.roi_yolo}", flush=True)
        t0 = time.perf_counter()
        roi_session = build_session(args.roi_yolo, args.threads)
        print(f"  OK ({1000 * (time.perf_counter() - t0):.0f} ms)", flush=True)
    else:
        print("No ROI model; four-point detection will run on full image", flush=True)

    # ── Load profiles (optional) ─────────────────────────────────────
    if args.profile:
        try:
            with open(args.profile, "r") as f:
                profiles[args.profile] = json.load(f)
            names = list(profiles[args.profile].keys())
            print(f"Profiles loaded: {names}", flush=True)
        except Exception as e:
            print(f"WARNING: Could not load profiles: {e}", flush=True)

    # ── Warmup: allocate arena, warm CPU caches ──────────────────────
    print("\nWarmup inference...", flush=True)
    detect_points(point_session, np.zeros((320, 320, 3), dtype=np.uint8), 0.9, 0.45)
    if roi_session:
        detect_roi(roi_session, np.zeros((640, 640, 3), dtype=np.uint8), 0.9)
    print("  OK\n", flush=True)

    # ── Start server ─────────────────────────────────────────────────
    started = time.time()
    server = ThreadingHTTPServer((args.host, args.port), MeterHandler)
    print(f"Listening on http://{args.host}:{args.port}", flush=True)
    print("Endpoints: /health  /status  /read\n", flush=True)

    def shutdown(sig, frame):
        print("\nShutting down...", flush=True)
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
