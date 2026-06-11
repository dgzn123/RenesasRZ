"""
meter_reader_onnx.py - YOLOv8n-320 four-point meter reader.

This version is compatible with the existing PHP launcher arguments:
    python3 meter_reader_onnx.py --yolo best.onnx --unet shuffle_unet.onnx \
        --image capture/test.jpg --min 0 --max 6 --divisions 29

The --unet argument is accepted for backward compatibility but is not used.
Reading is computed from four YOLO classes:
    0 base   - meter center
    1 end    - end scale position
    2 start  - start scale position
    3 tip    - pointer tip position
"""

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


IMG_SIZE = 320
CLASS_NAMES = ["base", "end", "start", "tip"]
REQUIRED = ["base", "end", "start", "tip"]
ROI_IMG_SIZE = 640


def letterbox(img, new_shape=IMG_SIZE, color=(114, 114, 114)):
    h, w = img.shape[:2]
    r = min(new_shape / h, new_shape / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    dw, dh = (new_shape - nw) / 2, (new_shape - nh) / 2
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return padded, r, (dw, dh)


def preprocess(image_bgr):
    img, ratio, pad = letterbox(image_bgr)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    arr = img.transpose(2, 0, 1).astype(np.float32) / 255.0
    return arr[None], ratio, pad


def nms(boxes, scores, iou_thres=0.45):
    if len(boxes) == 0:
        return []
    boxes = boxes.astype(np.float32)
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= iou_thres]
    return keep


def decode_yolov8(output, image_shape, ratio, pad, conf_thres=0.25, iou_thres=0.45):
    pred = np.squeeze(output)
    if pred.ndim != 2:
        raise RuntimeError(f"Unexpected YOLO output ndim: {pred.shape}")
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T

    boxes_xywh = pred[:, :4]
    scores_all = pred[:, 4 : 4 + len(CLASS_NAMES)]
    cls_ids = scores_all.argmax(axis=1)
    scores = scores_all.max(axis=1)
    mask = scores >= conf_thres

    boxes_xywh = boxes_xywh[mask]
    scores = scores[mask]
    cls_ids = cls_ids[mask]
    if len(boxes_xywh) == 0:
        return []

    boxes = np.empty_like(boxes_xywh)
    boxes[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2

    boxes[:, [0, 2]] -= pad[0]
    boxes[:, [1, 3]] -= pad[1]
    boxes /= ratio

    h, w = image_shape[:2]
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)

    detections = []
    for cls in range(len(CLASS_NAMES)):
        idx = np.where(cls_ids == cls)[0]
        for local in nms(boxes[idx], scores[idx], iou_thres):
            j = idx[local]
            x1, y1, x2, y2 = boxes[j]
            detections.append(
                {
                    "class_id": int(cls_ids[j]),
                    "class_name": CLASS_NAMES[int(cls_ids[j])],
                    "confidence": float(scores[j]),
                    "box_xyxy": [float(x1), float(y1), float(x2), float(y2)],
                    "center": [float((x1 + x2) / 2), float((y1 + y2) / 2)],
                }
            )
    return sorted(detections, key=lambda d: d["confidence"], reverse=True)


def detect_points(session, image_bgr, conf_thres=0.25, iou_thres=0.45):
    inp, ratio, pad = preprocess(image_bgr)
    outputs = session.run(None, {session.get_inputs()[0].name: inp})
    detections = decode_yolov8(outputs[0], image_bgr.shape, ratio, pad, conf_thres, iou_thres)

    best = {}
    for det in detections:
        name = det["class_name"]
        if name not in best or det["confidence"] > best[name]["confidence"]:
            best[name] = det
    return best, detections


def resize_preprocess(image_bgr, size):
    img = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (size, size)).astype(np.float32) / 255.0
    img = img.transpose(2, 0, 1)
    return img[None]


def detect_roi(session, image_bgr, conf_thres=0.25, expand=0.2):
    h0, w0 = image_bgr.shape[:2]
    inp = resize_preprocess(image_bgr, ROI_IMG_SIZE)
    out = session.run(None, {session.get_inputs()[0].name: inp})[0]
    pred = np.squeeze(out)
    if pred.ndim != 2:
        raise RuntimeError(f"Unexpected ROI YOLO output shape: {pred.shape}")
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T

    boxes_xywh = pred[:, :4]
    if pred.shape[1] == 5:
        scores = pred[:, 4]
    else:
        scores = pred[:, 4:].max(axis=1)
    best = int(np.argmax(scores))
    conf = float(scores[best])
    if conf < conf_thres:
        return None, conf

    x, y, w, h = boxes_xywh[best]
    x = x / ROI_IMG_SIZE * w0
    y = y / ROI_IMG_SIZE * h0
    w = w / ROI_IMG_SIZE * w0
    h = h / ROI_IMG_SIZE * h0

    x1 = x - w / 2
    y1 = y - h / 2
    x2 = x + w / 2
    y2 = y + h / 2

    # Expand and make the crop square so the second-stage detector sees a
    # training-like meter view instead of a squeezed rectangle.
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * (1.0 + expand)
    x1 = int(round(max(0, cx - side / 2)))
    y1 = int(round(max(0, cy - side / 2)))
    x2 = int(round(min(w0, cx + side / 2)))
    y2 = int(round(min(h0, cy + side / 2)))
    if x2 <= x1 or y2 <= y1:
        return None, conf
    return (x1, y1, x2, y2), conf


def angle_clockwise_degrees(point, center):
    # Image coordinates: x right, y down. atan2(dy, dx) increases clockwise.
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    return math.degrees(math.atan2(dy, dx)) % 360.0


def clockwise_delta(a, b):
    return (b - a) % 360.0


def counterclockwise_delta(a, b):
    return (a - b) % 360.0


def compute_reading(points, min_value, max_value, divisions, direction="auto", offset=0.0, clamp=True):
    base = points["base"]["center"]
    start = points["start"]["center"]
    end = points["end"]["center"]
    tip = points["tip"]["center"]

    a_start = angle_clockwise_degrees(start, base)
    a_end = angle_clockwise_degrees(end, base)
    a_tip = angle_clockwise_degrees(tip, base)

    sweep_cw = clockwise_delta(a_start, a_end)
    sweep_ccw = counterclockwise_delta(a_start, a_end)

    if direction == "auto":
        # Most round industrial gauges use the longer arc between lower-left and
        # lower-right endpoints. Force --direction for unusual short-arc gauges.
        direction = "cw" if sweep_cw >= sweep_ccw else "ccw"

    if direction == "cw":
        sweep = sweep_cw
        tip_delta = clockwise_delta(a_start, a_tip)
    elif direction == "ccw":
        sweep = sweep_ccw
        tip_delta = counterclockwise_delta(a_start, a_tip)
    else:
        raise ValueError("--direction must be auto, cw, or ccw")

    if sweep <= 1e-6:
        raise RuntimeError("start/end angles are too close to compute a scale arc")

    fraction = tip_delta / sweep
    raw_fraction = fraction
    if clamp:
        fraction = max(0.0, min(1.0, fraction))

    reading = min_value + fraction * (max_value - min_value) - offset
    tick_float = fraction * divisions if divisions else None

    return {
        "reading": float(reading),
        "fraction": float(fraction),
        "raw_fraction": float(raw_fraction),
        "tick_float": None if tick_float is None else float(tick_float),
        "direction": direction,
        "angles_clockwise_deg": {
            "start": float(a_start),
            "end": float(a_end),
            "tip": float(a_tip),
            "sweep": float(sweep),
            "tip_delta": float(tip_delta),
        },
    }


def draw_debug(image_bgr, points, detections, output_path, reading_info=None, roi_box=None, crop_origin=(0, 0)):
    img = image_bgr.copy()
    colors = {
        "base": (60, 80, 255),
        "end": (255, 180, 60),
        "start": (80, 220, 120),
        "tip": (80, 80, 255),
    }
    ox, oy = crop_origin
    if roi_box is not None:
        x1, y1, x2, y2 = roi_box
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 255, 0), 2)
        cv2.putText(img, "ROI", (x1, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 0), 2, cv2.LINE_AA)
    for det in detections:
        name = det["class_name"]
        x1, y1, x2, y2 = [int(round(v)) for v in det["box_xyxy"]]
        x1 += ox
        x2 += ox
        y1 += oy
        y2 += oy
        color = colors.get(name, (255, 255, 255))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            img,
            f"{name} {det['confidence']:.2f}",
            (x1, max(18, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    if all(k in points for k in REQUIRED):
        b = tuple(int(round(v + add)) for v, add in zip(points["base"]["center"], (ox, oy)))
        for name in ["start", "end", "tip"]:
            p = tuple(int(round(v + add)) for v, add in zip(points[name]["center"], (ox, oy)))
            cv2.line(img, b, p, colors[name], 2)
            cv2.circle(img, p, 5, colors[name], -1)
        cv2.circle(img, b, 5, colors["base"], -1)
    if reading_info:
        cv2.putText(
            img,
            f"Reading: {reading_info['reading']:.3f}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(output_path), img)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yolo", required=True, help="YOLOv8n-320 four-point ONNX model")
    parser.add_argument("--roi-yolo", help="Optional first-stage meter ROI ONNX model")
    parser.add_argument("--unet", help="Ignored; accepted for backward compatibility")
    parser.add_argument("--image", required=True, help="Input image")
    parser.add_argument("--min", type=float, default=None, help="Minimum meter value")
    parser.add_argument("--max", type=float, default=None, help="Maximum meter value")
    parser.add_argument("--divisions", type=int, default=None, help="Scale divisions between min and max")
    parser.add_argument("--offset", type=float, default=0.0, help="Reading offset correction, subtracted from result")
    parser.add_argument("--profile", type=str, help="Optional profile JSON")
    parser.add_argument("--profile-name", type=str, default="default")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--roi-conf", type=float, default=0.25)
    parser.add_argument("--roi-expand", type=float, default=0.2)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--direction", choices=["auto", "cw", "ccw"], default="auto")
    parser.add_argument("--no-clamp", action="store_true", help="Do not clamp tip fraction to [0, 1]")
    parser.add_argument("--json-out", type=str, help="Optional JSON result path")
    parser.add_argument("--debug-image", type=str, help="Optional annotated debug image path")
    args = parser.parse_args()

    started = time.perf_counter()

    if args.profile:
        with open(args.profile, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        p = profiles.get(args.profile_name, {})
        args.min = args.min if args.min is not None else p.get("min")
        args.max = args.max if args.max is not None else p.get("max")
        args.divisions = args.divisions if args.divisions is not None else p.get("divisions")

    if args.min is None or args.max is None or args.divisions is None:
        print("ERROR: Provide --min/--max/--divisions or --profile")
        return 2

    image = cv2.imread(args.image)
    if image is None:
        raise FileNotFoundError(f"Cannot read: {args.image}")

    print("ONNX model loading...")
    point_session = ort.InferenceSession(args.yolo, providers=["CPUExecutionProvider"])
    roi_session = ort.InferenceSession(args.roi_yolo, providers=["CPUExecutionProvider"]) if args.roi_yolo else None
    print("ONNX model loaded OK")

    roi_box = None
    crop_origin = (0, 0)
    meter_image = image
    if roi_session is not None:
        print("[1/4] Detecting meter ROI...")
        roi_box, roi_conf = detect_roi(roi_session, image, args.roi_conf, args.roi_expand)
        if roi_box is None:
            print(f"ERROR: No meter ROI detected (best conf={roi_conf:.3f})")
            return 1
        x1, y1, x2, y2 = roi_box
        crop_origin = (x1, y1)
        meter_image = image[y1:y2, x1:x2]
        print(f"  ROI bbox: {roi_box}, conf={roi_conf:.3f}, crop={meter_image.shape[1]}x{meter_image.shape[0]}")

    print("[2/4] Detecting base/start/end/tip...")
    points, detections = detect_points(point_session, meter_image, args.conf, args.iou)

    missing = [name for name in REQUIRED if name not in points]
    if missing:
        present = {k: round(v["confidence"], 3) for k, v in points.items()}
        print(f"ERROR: Missing required point(s): {', '.join(missing)}")
        print(f"  Present detections: {present}")
        if args.json_out:
            write = {
                "success": False,
                "error": f"missing points: {missing}",
                "present": present,
                "detections": detections,
            }
            Path(args.json_out).write_text(json.dumps(write, indent=2), encoding="utf-8")
        return 1

    print("[3/4] Computing geometric reading...")
    reading_info = compute_reading(
        points,
        args.min,
        args.max,
        args.divisions,
        direction=args.direction,
        offset=args.offset,
        clamp=not args.no_clamp,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    result = {
        "success": True,
        "reading": reading_info["reading"],
        "min": args.min,
        "max": args.max,
        "divisions": args.divisions,
        "offset": args.offset,
        "elapsed_ms": elapsed_ms,
        "points": points,
        "geometry": reading_info,
    }

    print("[4/4] Done")
    for name in REQUIRED:
        p = points[name]
        print(f"  {name}: center=({p['center'][0]:.1f}, {p['center'][1]:.1f}), conf={p['confidence']:.3f}")
    print(f"  Direction: {reading_info['direction']}")
    print(f"  Fraction: {reading_info['fraction']:.4f}, tick={reading_info['tick_float']:.2f}")
    print(f"  Elapsed: {elapsed_ms:.1f} ms")
    print(f"\n{'=' * 40}")
    print(f"  Reading: {reading_info['reading']:.2f}  (range {args.min}~{args.max})")
    print(f"  Offset correction: {args.offset}")
    print(f"{'=' * 40}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.debug_image:
        draw_debug(image, points, detections, args.debug_image, reading_info, roi_box, crop_origin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
