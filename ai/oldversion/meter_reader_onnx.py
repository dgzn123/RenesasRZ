"""
meter_reader_onnx.py — ONNX Runtime inference for RZ/G2L deployment.

Usage:
    python3 meter_reader_onnx.py --yolo best.onnx --unet shuffle_unet.onnx --image test.jpg --min 0 --max 25 --divisions 50
    python3 meter_reader_onnx.py --yolo best.onnx --unet shuffle_unet.onnx --image test.jpg --profile meter_profiles.json
"""
import argparse
import json
from collections import Counter

import cv2
import numpy as np
import onnxruntime as ort

# ── Constants ──────────────────────────────────────────────────────────────
TARGET_SIZE      = 256
YOLO_IMG_SIZE    = 640
METER_SIZE       = 512
CIRCLE_CENTER    = (256.0, 256.0)
CIRCLE_RADIUS    = 250.0
RECTANGLE_WIDTH  = 600
RECTANGLE_HEIGHT = 140
IMAGENET_MEAN    = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD     = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# ── YOLOv8 detection ──────────────────────────────────────────────────────
def yolo_detect(session, image_bgr):
    h0, w0 = image_bgr.shape[:2]
    img = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (YOLO_IMG_SIZE, YOLO_IMG_SIZE)).astype(np.float32) / 255.0
    img = img.transpose(2, 0, 1)
    img = np.expand_dims(img, 0)

    outputs = session.run(None, {session.get_inputs()[0].name: img})
    data = np.squeeze(outputs[0]).T

    num_classes = data.shape[1] - 4
    boxes_raw = data[:, :4]
    scores = data[:, 4] if num_classes == 1 else (data[:, 4:5] * data[:, 5:]).max(axis=1)
    scores = np.asarray(scores).flatten()

    boxes_xywh = boxes_raw.copy()
    boxes_xywh[:, 0] /= YOLO_IMG_SIZE
    boxes_xywh[:, 1] /= YOLO_IMG_SIZE
    boxes_xywh[:, 2] /= YOLO_IMG_SIZE
    boxes_xywh[:, 3] /= YOLO_IMG_SIZE

    xmin = (boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2) * w0
    ymin = (boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2) * h0
    xmax = (boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2) * w0
    ymax = (boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2) * h0

    best = np.argmax(scores)
    if scores[best] < 0.3:
        return None, scores[best]
    return (int(xmin[best]), int(ymin[best]), int(xmax[best]), int(ymax[best])), scores[best]

# ── ShuffleNet-UNet segmentation ──────────────────────────────────────────
def unet_segment(session, image_bgr):
    img = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (TARGET_SIZE, TARGET_SIZE)).astype(np.float32) / 255.0
    img = (img - IMAGENET_MEAN) / IMAGENET_STD
    img = img.transpose(2, 0, 1)
    img = np.expand_dims(img, 0).astype(np.float32)

    outputs = session.run(None, {session.get_inputs()[0].name: img})
    logits = outputs[0]
    pred = np.argmax(np.squeeze(logits), axis=0).astype(np.uint8)
    return pred

# ── Circle-to-rectangle polar transform ───────────────────────────────────
def circle_to_rectangle(seg_gray, rect_height=RECTANGLE_HEIGHT):
    resized = cv2.resize(seg_gray, (METER_SIZE, METER_SIZE), interpolation=cv2.INTER_NEAREST)
    rect = np.zeros((rect_height, RECTANGLE_WIDTH), dtype=np.uint8)
    xs = np.arange(RECTANGLE_WIDTH)
    ys = np.arange(rect_height)
    X, Y = np.meshgrid(xs, ys)
    theta = np.pi * 2.0 * (X + 1) / RECTANGLE_WIDTH
    rho = CIRCLE_RADIUS - Y - 1
    src_x = (CIRCLE_CENTER[0] - rho * np.sin(theta) + 0.5).astype(np.int32)
    src_y = (CIRCLE_CENTER[1] + rho * np.cos(theta) + 0.5).astype(np.int32)
    valid = (src_x >= 0) & (src_x < METER_SIZE) & (src_y >= 0) & (src_y < METER_SIZE)
    rect[Y[valid], X[valid]] = resized[src_y[valid], src_x[valid]]
    return rect

# ── 1D signal projection ─────────────────────────────────────────────────
def rectangle_to_line(rect_img, target_class):
    return np.sum(rect_img == target_class, axis=0).astype(np.float32)

# ── Peak detection ───────────────────────────────────────────────────────
def detect_scale_positions(signal, min_gap=3):
    threshold = np.max(signal) * 0.3
    peaks = []
    for i in range(1, len(signal) - 1):
        if signal[i] > threshold and signal[i] > signal[i - 1] and signal[i] > signal[i + 1]:
            peaks.append(i)
    filtered = []
    for p in peaks:
        if not filtered or (p - filtered[-1]) >= min_gap:
            filtered.append(p)
    return filtered

def detect_pointer_position(signal):
    idx = np.argmax(signal)
    return [idx] if signal[idx] > 0 else []

# ── Scale correction ─────────────────────────────────────────────────────
def check_scale(arr, final_length):
    if len(arr) < 2:
        return arr
    diffs = [arr[i + 1] - arr[i] for i in range(len(arr) - 1)]
    mode_diff = Counter(diffs).most_common(1)[0][0]

    new_arr = arr[:2]
    for i in range(2, len(arr)):
        diff = arr[i] - arr[i - 1]
        if diff < mode_diff - 2:
            continue
        elif diff > mode_diff + 2:
            insert = arr[i - 1] + mode_diff
            while insert < arr[i]:
                new_arr.append(insert)
                insert += mode_diff
        new_arr.append(arr[i])

    while len(new_arr) < final_length:
        new_arr.append(new_arr[-1] + mode_diff)
    return new_arr[:final_length]

# ── Reading calculation ──────────────────────────────────────────────────
def Reading(scale_locations, point_locations):
    num_scales = 0
    num_PointerinRange = 0
    for i, scale in enumerate(scale_locations):
        if scale > point_locations[0]:
            num_scales = i - 1
            num_PointerinRange = round(
                1 - (scale - point_locations[0]) / (scale - scale_locations[i - 1]), 2
            )
            break
    return num_scales, num_PointerinRange

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--yolo', help='YOLOv8 ONNX model (omit with --no-yolo)')
    parser.add_argument('--unet', required=True, help='ShuffleNet-UNet ONNX model')
    parser.add_argument('--image', required=True, help='Input image')
    parser.add_argument('--min', type=float, default=None, help='Min scale value')
    parser.add_argument('--max', type=float, default=None, help='Max scale value')
    parser.add_argument('--divisions', type=int, default=None,
                        help='Total scale divisions (= (max-min) / per_tick)')
    parser.add_argument('--no-yolo', action='store_true', help='Skip YOLO, use whole image')
    parser.add_argument('--profile', type=str, help='Meter profile JSON file')
    parser.add_argument('--profile-name', type=str, default='default',
                        help='Profile name in JSON (default: "default")')
    parser.add_argument('--offset', type=float, default=0,
                        help='Reading offset correction (subtracted from result)')
    args = parser.parse_args()

    # Load image
    image = cv2.imread(args.image)
    if image is None:
        raise FileNotFoundError(f"Cannot read: {args.image}")

    # Init ONNX sessions
    unet_sess = ort.InferenceSession(args.unet, providers=['CPUExecutionProvider'])
    yolo_sess = None
    if not args.no_yolo and args.yolo:
        yolo_sess = ort.InferenceSession(args.yolo, providers=['CPUExecutionProvider'])
    print("ONNX models loaded OK")

    # Step 1: Detect meter
    if args.no_yolo or yolo_sess is None:
        print("[1/6] Skipping YOLO — using whole image as meter...")
        meter_crop = image
    else:
        print("[1/6] Detecting meter...")
        bbox, conf = yolo_detect(yolo_sess, image)
        if bbox is None:
            print(f"ERROR: No meter detected (best conf={conf:.3f})")
            return
        print(f"  Meter bbox: {bbox}, conf={conf:.3f}")
        xmin, ymin, xmax, ymax = bbox
        meter_crop = image[max(0, ymin):ymax, max(0, xmin):xmax]

    # Step 2: Range — profile > manual args
    if args.profile:
        with open(args.profile) as f:
            profiles = json.load(f)
        p = profiles.get(args.profile_name, {})
        args.min = args.min if args.min is not None else p.get('min')
        args.max = args.max if args.max is not None else p.get('max')
        args.divisions = args.divisions if args.divisions is not None else p.get('divisions')
        print(f"[2/6] Profile '{args.profile_name}': min={args.min}, max={args.max}, divisions={args.divisions}")
    else:
        print("[2/6] Using manual range params")

    if args.min is None or args.max is None or args.divisions is None:
        print("ERROR: Provide --min/--max/--divisions or --profile")
        return

    fenduzhi = (args.max - args.min) / args.divisions

    # Step 3: Segment pointer & scale
    print(f"[3/6] Segmenting (range {args.min}~{args.max}, {args.divisions} divs)...")
    seg_mask = unet_segment(unet_sess, meter_crop)
    h_crop, w_crop = meter_crop.shape[:2]
    if seg_mask.shape != (h_crop, w_crop):
        seg_mask = cv2.resize(seg_mask, (w_crop, h_crop), interpolation=cv2.INTER_NEAREST)

    # Step 4: Erosion
    print("[4/6] Erosion...")
    kernel = np.ones((2, 2), np.uint8)
    seg_mask = cv2.erode(seg_mask, kernel)

    # Step 5: Circle-to-rectangle
    print("[5/6] Polar transform...")
    rect = circle_to_rectangle(seg_mask)
    scale_rect = rect.copy()
    pointer_rect = rect.copy()
    scale_rect[scale_rect == 1] = 0
    pointer_rect[pointer_rect == 2] = 0

    # Step 6: Peak detection + reading
    print("[6/6] Calculating reading...")
    scale_signal = rectangle_to_line(scale_rect, 2)
    pointer_signal = rectangle_to_line(pointer_rect, 1)
    scales = detect_scale_positions(scale_signal)
    pointer = detect_pointer_position(pointer_signal)
    print(f"  Raw scales: {len(scales)}, Pointer: {pointer}")

    if scales and pointer:
        scales = check_scale(scales, args.divisions + 1)
        print(f"  Fixed scales: {len(scales)}")

    if len(scales) < 2 or not pointer:
        print("ERROR: Not enough scale marks or no pointer")
        return

    num_scales, num_in_range = Reading(scales, pointer)
    reading = round((num_scales + 1) * fenduzhi + num_in_range * fenduzhi, 2) - args.offset

    print(f"\n{'='*40}")
    print(f"  Reading: {reading}  (range {args.min}~{args.max})")
    print(f"  Offset correction: {args.offset}")
    print(f"{'='*40}")


if __name__ == '__main__':
    main()
