import argparse
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import onnxruntime as ort
import torch
import yaml
from PIL import Image
from tqdm import tqdm
from ultralytics import YOLO


DATASET = Path(r"D:\Code\Qiansai\dataset7000")
OUT = Path(r"C:\Users\Heda\Desktop\index\ai")
CLASS_NAMES = ["base", "end", "start", "tip"]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def ensure_dirs():
    for rel in [
        "dataset_analysis",
        "dataset_preview",
        "runs",
        "export",
        "onnx_verify",
        "deploy",
        "ultralytics_config",
    ]:
        (OUT / rel).mkdir(parents=True, exist_ok=True)


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rel_to_label(img_path):
    rel = img_path.relative_to(DATASET / "images")
    return DATASET / "labels" / rel.with_suffix(".txt")


def list_images(split=None):
    root = DATASET / "images"
    if split:
        root = root / split
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in IMG_EXTS)


def load_label(label_path):
    rows = []
    if not label_path.exists():
        return rows
    for line_no, raw in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{label_path}:{line_no} has {len(parts)} columns, expected 5")
        cls = int(float(parts[0]))
        vals = [float(v) for v in parts[1:]]
        rows.append((cls, *vals))
    return rows


def write_dataset_yaml():
    data = {
        "path": str(DATASET),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {i: name for i, name in enumerate(CLASS_NAMES)},
    }
    path = OUT / "dataset.yaml"
    write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return path


def run_cmd(cmd, cwd=OUT):
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "seconds": round(time.time() - started, 3),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def env_report():
    report = {
        "python": sys.version,
        "python_executable": sys.executable,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "ultralytics": None,
        "onnxruntime": ort.__version__,
        "gpu": None,
        "gpu_total_vram_mb": None,
        "gpu_free_vram_mb": None,
        "nvidia_smi": None,
    }
    import ultralytics

    report["ultralytics"] = ultralytics.__version__
    if torch.cuda.is_available():
        idx = torch.cuda.current_device()
        prop = torch.cuda.get_device_properties(idx)
        report["gpu"] = prop.name
        report["gpu_total_vram_mb"] = int(prop.total_memory / 1024 / 1024)
        try:
            free, total = torch.cuda.mem_get_info(idx)
            report["gpu_free_vram_mb"] = int(free / 1024 / 1024)
        except Exception:
            pass
    try:
        smi = run_cmd(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free", "--format=csv,noheader"])
        report["nvidia_smi"] = smi["stdout"].strip() if smi["returncode"] == 0 else smi["stderr"].strip()
    except Exception as exc:
        report["nvidia_smi"] = str(exc)
    write_text(OUT / "dataset_analysis" / "environment.json", json.dumps(report, indent=2, ensure_ascii=False))
    return report


def summarize(values):
    if not values:
        return {}
    values = list(values)
    return {
        "min": min(values),
        "p25": float(np.percentile(values, 25)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p75": float(np.percentile(values, 75)),
        "max": max(values),
    }


def analyze_dataset():
    images = list_images()
    split_counts = {}
    image_sizes = []
    class_counts = Counter()
    wh_by_class = defaultdict(list)
    area_by_class = defaultdict(list)
    objects_per_image = []
    missing_labels = []
    bad_labels = []
    all_widths = []
    all_heights = []
    all_areas = []

    for split in ["train", "val", "test"]:
        split_counts[split] = len(list_images(split))

    for img in tqdm(images, desc="analyze dataset"):
        try:
            with Image.open(img) as im:
                w, h = im.size
        except Exception as exc:
            bad_labels.append({"file": str(img), "error": f"image open failed: {exc}"})
            continue
        image_sizes.append((w, h))
        label_path = rel_to_label(img)
        if not label_path.exists():
            missing_labels.append(str(label_path))
            objects_per_image.append(0)
            continue
        try:
            rows = load_label(label_path)
        except Exception as exc:
            bad_labels.append({"file": str(label_path), "error": str(exc)})
            objects_per_image.append(0)
            continue
        objects_per_image.append(len(rows))
        for cls, xc, yc, bw, bh in rows:
            class_counts[cls] += 1
            wh_by_class[cls].append((bw, bh))
            area = bw * bh
            area_by_class[cls].append(area)
            all_widths.append(bw)
            all_heights.append(bh)
            all_areas.append(area)
            if cls < 0 or cls >= len(CLASS_NAMES) or any(v < 0 or v > 1 for v in [xc, yc, bw, bh]):
                bad_labels.append({"file": str(label_path), "error": f"out of range: {(cls, xc, yc, bw, bh)}"})

    width_values = [w for w, _ in image_sizes]
    height_values = [h for _, h in image_sizes]
    size_counter = Counter(f"{w}x{h}" for w, h in image_sizes)
    report = {
        "dataset": str(DATASET),
        "total_images": len(images),
        "split_image_counts": split_counts,
        "class_names": CLASS_NAMES,
        "class_counts": {CLASS_NAMES[k]: class_counts.get(k, 0) for k in range(len(CLASS_NAMES))},
        "objects_total": sum(class_counts.values()),
        "objects_per_image": summarize(objects_per_image),
        "image_width": summarize(width_values),
        "image_height": summarize(height_values),
        "top_image_sizes": size_counter.most_common(20),
        "bbox_width_normalized": summarize(all_widths),
        "bbox_height_normalized": summarize(all_heights),
        "bbox_area_normalized": summarize(all_areas),
        "bbox_by_class": {},
        "missing_labels": missing_labels,
        "bad_labels": bad_labels[:100],
        "bad_label_count": len(bad_labels),
    }
    for cls in range(len(CLASS_NAMES)):
        widths = [w for w, _ in wh_by_class[cls]]
        heights = [h for _, h in wh_by_class[cls]]
        report["bbox_by_class"][CLASS_NAMES[cls]] = {
            "count": class_counts.get(cls, 0),
            "width": summarize(widths),
            "height": summarize(heights),
            "area": summarize(area_by_class[cls]),
        }

    write_text(OUT / "dataset_analysis" / "dataset_analysis.json", json.dumps(report, indent=2, ensure_ascii=False))
    make_analysis_plots(report, all_widths, all_heights, all_areas, objects_per_image)
    write_analysis_md(report)
    return report


def make_analysis_plots(report, widths, heights, areas, objects_per_image):
    cls_counts = report["class_counts"]
    plt.figure(figsize=(8, 4))
    plt.bar(cls_counts.keys(), cls_counts.values())
    plt.title("Class Distribution")
    plt.tight_layout()
    plt.savefig(OUT / "dataset_analysis" / "class_distribution.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.hist(widths, bins=50, alpha=0.7, label="width")
    plt.hist(heights, bins=50, alpha=0.7, label="height")
    plt.legend()
    plt.title("Normalized Box Width/Height")
    plt.tight_layout()
    plt.savefig(OUT / "dataset_analysis" / "bbox_wh_distribution.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.hist(areas, bins=50)
    plt.title("Normalized Box Area")
    plt.tight_layout()
    plt.savefig(OUT / "dataset_analysis" / "bbox_area_distribution.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.hist(objects_per_image, bins=range(0, max(objects_per_image) + 2 if objects_per_image else 2), align="left")
    plt.title("Objects Per Image")
    plt.tight_layout()
    plt.savefig(OUT / "dataset_analysis" / "objects_per_image.png", dpi=160)
    plt.close()


def md_table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


def fmt_stat(stat):
    if not stat:
        return "-"
    return f"min {stat['min']:.5g}, mean {stat['mean']:.5g}, p50 {stat['median']:.5g}, max {stat['max']:.5g}"


def write_analysis_md(report):
    rows = [[k, v] for k, v in report["split_image_counts"].items()]
    cls_rows = [[k, v] for k, v in report["class_counts"].items()]
    bbox_rows = []
    for name, item in report["bbox_by_class"].items():
        bbox_rows.append([name, item["count"], fmt_stat(item["width"]), fmt_stat(item["height"]), fmt_stat(item["area"])])
    text = f"""# Dataset Analysis

Dataset: `{report['dataset']}`

Total images: **{report['total_images']}**

## Splits

{md_table(rows, ['split', 'images'])}

## Classes

{md_table(cls_rows, ['class', 'objects'])}

Objects total: **{report['objects_total']}**

Objects per image: {fmt_stat(report['objects_per_image'])}

## Image Sizes

Width: {fmt_stat(report['image_width'])}

Height: {fmt_stat(report['image_height'])}

Top sizes: `{report['top_image_sizes'][:10]}`

## Box Size Distribution

Normalized width: {fmt_stat(report['bbox_width_normalized'])}

Normalized height: {fmt_stat(report['bbox_height_normalized'])}

Normalized area: {fmt_stat(report['bbox_area_normalized'])}

{md_table(bbox_rows, ['class', 'count', 'width', 'height', 'area'])}

## Integrity

Missing labels: **{len(report['missing_labels'])}**

Bad labels: **{report['bad_label_count']}**
"""
    write_text(OUT / "dataset_analysis" / "dataset_analysis.md", text)


def draw_preview(n=20, seed=42):
    random.seed(seed)
    images = list_images()
    sample = random.sample(images, min(n, len(images)))
    colors = {
        0: (255, 80, 80),
        1: (80, 180, 255),
        2: (80, 220, 120),
        3: (240, 180, 60),
    }
    out_dir = OUT / "dataset_preview"
    for old in out_dir.glob("*.jpg"):
        old.unlink()
    for idx, img_path in enumerate(sample, 1):
        im = cv2.imread(str(img_path))
        if im is None:
            continue
        h, w = im.shape[:2]
        rows = load_label(rel_to_label(img_path))
        for cls, xc, yc, bw, bh in rows:
            x1 = int((xc - bw / 2) * w)
            y1 = int((yc - bh / 2) * h)
            x2 = int((xc + bw / 2) * w)
            y2 = int((yc + bh / 2) * h)
            color = colors.get(cls, (255, 255, 255))
            cv2.rectangle(im, (x1, y1), (x2, y2), color, 2)
            label = CLASS_NAMES[cls] if 0 <= cls < len(CLASS_NAMES) else str(cls)
            cv2.putText(im, label, (x1, max(16, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
        cv2.imwrite(str(out_dir / f"preview_{idx:02d}_{img_path.stem}.jpg"), im)


def choose_batch(imgsz):
    if not torch.cuda.is_available():
        return 8 if imgsz <= 320 else 4
    free_mb = torch.cuda.mem_get_info()[0] / 1024 / 1024
    if imgsz <= 320:
        if free_mb > 9000:
            return 64
        if free_mb > 6000:
            return 48
        return 32
    if free_mb > 9000:
        return 24
    if free_mb > 6000:
        return 16
    return 8


def train_one(imgsz, epochs):
    data_yaml = OUT / "dataset.yaml"
    name = f"yolov8n_{imgsz}"
    model = YOLO("yolov8n.pt")
    batch = choose_batch(imgsz)
    device = 0 if torch.cuda.is_available() else "cpu"
    result = model.train(
        data=str(data_yaml),
        imgsz=imgsz,
        epochs=epochs,
        batch=batch,
        device=device,
        project=str(OUT / "runs"),
        name=name,
        exist_ok=True,
        pretrained=True,
        optimizer="auto",
        mosaic=1.0,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        scale=0.5,
        fliplr=0.5,
        flipud=0.0,
        degrees=10.0,
        verbose=True,
        plots=True,
    )
    return Path(result.save_dir)


def validate_model(run_dir, imgsz):
    model_path = run_dir / "weights" / "best.pt"
    model = YOLO(str(model_path))
    metrics = model.val(data=str(OUT / "dataset.yaml"), imgsz=imgsz, split="val", project=str(OUT / "runs"), name=f"val_{imgsz}", exist_ok=True)
    speed = getattr(metrics, "speed", {})
    box = metrics.box
    return {
        "imgsz": imgsz,
        "model": str(model_path),
        "precision": float(box.mp),
        "recall": float(box.mr),
        "map50": float(box.map50),
        "map50_95": float(box.map),
        "speed": {k: float(v) for k, v in speed.items()},
    }


def recommend(results):
    r320 = next(r for r in results if r["imgsz"] == 320)
    r640 = next(r for r in results if r["imgsz"] == 640)
    # Embedded-first rule: keep 320 unless 640 provides a meaningful accuracy/recall gain.
    gain_map = r640["map50_95"] - r320["map50_95"]
    gain_recall = r640["recall"] - r320["recall"]
    if gain_map > 0.05 or gain_recall > 0.08:
        choice = r640
        reason = "640 has a meaningful accuracy/recall advantage, important for small geometric targets."
    else:
        choice = r320
        reason = "320 is preferred for Cortex-A55 deployment because accuracy is close enough while compute is about 4x lower than 640."
    return choice, reason


def export_onnx(pt_path, imgsz):
    model = YOLO(str(pt_path))
    exported = model.export(format="onnx", opset=12, imgsz=imgsz, simplify=False, dynamic=False)
    exported = Path(exported)
    export_dir = OUT / "export"
    final_pt = export_dir / "best.pt"
    final_onnx = export_dir / "best.onnx"
    shutil.copy2(pt_path, final_pt)
    shutil.copy2(exported, final_onnx)
    return final_pt, final_onnx


def letterbox(img, new_shape, color=(114, 114, 114)):
    shape = img.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    dw /= 2
    dh /= 2
    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def yolo_preprocess(path, imgsz):
    img0 = cv2.imread(str(path))
    img = cv2.cvtColor(img0, cv2.COLOR_BGR2RGB)
    img, ratio, pad = letterbox(img, imgsz)
    arr = img.transpose(2, 0, 1).astype(np.float32) / 255.0
    return np.expand_dims(arr, 0), img0, ratio, pad


def verify_onnx(pt_path, onnx_path, imgsz, n=20):
    images = random.sample(list_images("test") or list_images(), n)
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_meta = [{"name": o.name, "shape": o.shape, "type": o.type} for o in sess.get_outputs()]
    model = YOLO(str(pt_path))
    diffs = []
    nonempty_onnx = 0
    nonempty_torch = 0
    for img in tqdm(images, desc="verify onnx"):
        inp, _, _, _ = yolo_preprocess(img, imgsz)
        out = sess.run(None, {in_name: inp})
        if out and np.isfinite(out[0]).all():
            nonempty_onnx += 1
        pred = model.predict(str(img), imgsz=imgsz, verbose=False, device=0 if torch.cuda.is_available() else "cpu")[0]
        if len(pred.boxes):
            nonempty_torch += 1
        # Compare raw model output with ONNX on preprocessed tensor through torch model.
        with torch.no_grad():
            t = torch.from_numpy(inp).to(model.model.device)
            raw = model.model(t)
            raw0 = raw[0] if isinstance(raw, (tuple, list)) else raw
            raw0 = raw0.detach().cpu().numpy()
        arr0 = out[0]
        if arr0.shape == raw0.shape:
            diffs.append(float(np.max(np.abs(arr0 - raw0))))
    report = {
        "onnx": str(onnx_path),
        "input": {"name": in_name, "shape": sess.get_inputs()[0].shape, "type": sess.get_inputs()[0].type},
        "outputs": out_meta,
        "samples": len(images),
        "onnx_numeric_ok_samples": nonempty_onnx,
        "torch_detected_samples": nonempty_torch,
        "max_abs_diff_raw_output": max(diffs) if diffs else None,
        "mean_abs_diff_raw_output": statistics.mean(diffs) if diffs else None,
        "diff_samples": len(diffs),
    }
    write_text(OUT / "onnx_verify" / "onnx_verify.json", json.dumps(report, indent=2, ensure_ascii=False))
    return report


def model_info(pt_path, onnx_path, imgsz):
    model = YOLO(str(pt_path))
    info = model.info(detailed=False, verbose=False)
    onnx_size = onnx_path.stat().st_size / 1024 / 1024
    return {
        "pt": str(pt_path),
        "onnx": str(onnx_path),
        "onnx_size_mb": round(onnx_size, 2),
        "input_size": [1, 3, imgsz, imgsz],
        "model_info": str(info),
    }


def generate_deploy_code(imgsz):
    py = f'''import cv2
import numpy as np
import onnxruntime as ort

CLASS_NAMES = ["base", "end", "start", "tip"]
IMG_SIZE = {imgsz}


def letterbox(img, new_shape=IMG_SIZE, color=(114, 114, 114)):
    h, w = img.shape[:2]
    r = min(new_shape / h, new_shape / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    img_resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    dw, dh = (new_shape - nw) / 2, (new_shape - nh) / 2
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img_padded = cv2.copyMakeBorder(img_resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img_padded, r, (dw, dh)


def nms(boxes, scores, iou_thres=0.45):
    if len(boxes) == 0:
        return []
    boxes = boxes.astype(np.float32)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
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


def infer(image_path, model_path="best.onnx", conf_thres=0.25, iou_thres=0.45):
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    img0 = cv2.imread(image_path)
    img, ratio, pad = letterbox(img0)
    inp = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1).astype(np.float32) / 255.0
    inp = inp[None]
    out = sess.run(None, {{sess.get_inputs()[0].name: inp}})[0]
    pred = np.squeeze(out)
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T
    boxes_xywh = pred[:, :4]
    class_scores = pred[:, 4:4 + len(CLASS_NAMES)]
    cls_ids = class_scores.argmax(axis=1)
    scores = class_scores.max(axis=1)
    mask = scores >= conf_thres
    boxes_xywh, scores, cls_ids = boxes_xywh[mask], scores[mask], cls_ids[mask]
    boxes = np.empty_like(boxes_xywh)
    boxes[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2
    boxes[:, [0, 2]] -= pad[0]
    boxes[:, [1, 3]] -= pad[1]
    boxes /= ratio
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, img0.shape[1])
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, img0.shape[0])
    results = []
    for cls in range(len(CLASS_NAMES)):
        idx = np.where(cls_ids == cls)[0]
        keep = nms(boxes[idx], scores[idx], iou_thres)
        for k in keep:
            j = idx[k]
            results.append({{
                "class": CLASS_NAMES[int(cls_ids[j])],
                "confidence": float(scores[j]),
                "box_xyxy": [float(x) for x in boxes[j]],
            }})
    return sorted(results, key=lambda x: x["confidence"], reverse=True)


if __name__ == "__main__":
    import sys
    print(infer(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "best.onnx"))
'''
    cpp = f'''// Minimal ONNX Runtime C++ inference skeleton for YOLOv8n meter detector.
// Build on RZ/G2L with ONNX Runtime C++ headers/libs and OpenCV.
#include <algorithm>
#include <iostream>
#include <numeric>
#include <opencv2/opencv.hpp>
#include <onnxruntime_cxx_api.h>

static const int IMG_SIZE = {imgsz};
static const char* CLASS_NAMES[] = {{"base", "end", "start", "tip"}};

struct Detection {{
    int cls;
    float score;
    cv::Rect2f box;
}};

static cv::Mat letterbox(const cv::Mat& src, float& ratio, float& dw, float& dh) {{
    int w = src.cols, h = src.rows;
    ratio = std::min((float)IMG_SIZE / h, (float)IMG_SIZE / w);
    int nw = std::round(w * ratio), nh = std::round(h * ratio);
    cv::Mat resized, out(IMG_SIZE, IMG_SIZE, CV_8UC3, cv::Scalar(114, 114, 114));
    cv::resize(src, resized, cv::Size(nw, nh));
    dw = (IMG_SIZE - nw) / 2.0f;
    dh = (IMG_SIZE - nh) / 2.0f;
    resized.copyTo(out(cv::Rect((int)std::round(dw - 0.1f), (int)std::round(dh - 0.1f), nw, nh)));
    return out;
}}

static float iou(const cv::Rect2f& a, const cv::Rect2f& b) {{
    float inter = (a & b).area();
    return inter / (a.area() + b.area() - inter + 1e-6f);
}}

static std::vector<int> nms(const std::vector<Detection>& dets, float iou_thres) {{
    std::vector<int> order(dets.size());
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) {{ return dets[a].score > dets[b].score; }});
    std::vector<int> keep;
    while (!order.empty()) {{
        int i = order.front();
        keep.push_back(i);
        std::vector<int> rest;
        for (size_t k = 1; k < order.size(); ++k) {{
            if (iou(dets[i].box, dets[order[k]].box) <= iou_thres) rest.push_back(order[k]);
        }}
        order.swap(rest);
    }}
    return keep;
}}

std::vector<Detection> infer(const std::string& model_path, const std::string& image_path, float conf=0.25f, float iou_thres=0.45f) {{
    Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "meter-yolo");
    Ort::SessionOptions opts;
    opts.SetIntraOpNumThreads(4);
    Ort::Session session(env, std::wstring(model_path.begin(), model_path.end()).c_str(), opts);

    cv::Mat bgr = cv::imread(image_path);
    float ratio, dw, dh;
    cv::Mat img = letterbox(bgr, ratio, dw, dh);
    cv::cvtColor(img, img, cv::COLOR_BGR2RGB);
    img.convertTo(img, CV_32F, 1.0 / 255.0);

    std::vector<float> input(1 * 3 * IMG_SIZE * IMG_SIZE);
    std::vector<cv::Mat> chw(3);
    for (int c = 0; c < 3; ++c) chw[c] = cv::Mat(IMG_SIZE, IMG_SIZE, CV_32F, input.data() + c * IMG_SIZE * IMG_SIZE);
    cv::split(img, chw);

    std::array<int64_t, 4> input_shape{{1, 3, IMG_SIZE, IMG_SIZE}};
    Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value tensor = Ort::Value::CreateTensor<float>(mem, input.data(), input.size(), input_shape.data(), input_shape.size());

    Ort::AllocatorWithDefaultOptions alloc;
    auto input_name = session.GetInputNameAllocated(0, alloc);
    auto output_name = session.GetOutputNameAllocated(0, alloc);
    const char* input_names[] = {{input_name.get()}};
    const char* output_names[] = {{output_name.get()}};
    auto outputs = session.Run(Ort::RunOptions{{nullptr}}, input_names, &tensor, 1, output_names, 1);
    float* out = outputs[0].GetTensorMutableData<float>();
    auto shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();

    int channels = (int)shape[1];
    int anchors = (int)shape[2];
    std::vector<Detection> dets;
    for (int i = 0; i < anchors; ++i) {{
        float x = out[0 * anchors + i], y = out[1 * anchors + i], w = out[2 * anchors + i], h = out[3 * anchors + i];
        int best_cls = 0;
        float best = 0.0f;
        for (int c = 0; c < 4; ++c) {{
            float s = out[(4 + c) * anchors + i];
            if (s > best) {{ best = s; best_cls = c; }}
        }}
        if (best < conf) continue;
        float x1 = (x - w / 2 - dw) / ratio;
        float y1 = (y - h / 2 - dh) / ratio;
        float x2 = (x + w / 2 - dw) / ratio;
        float y2 = (y + h / 2 - dh) / ratio;
        x1 = std::clamp(x1, 0.0f, (float)bgr.cols);
        x2 = std::clamp(x2, 0.0f, (float)bgr.cols);
        y1 = std::clamp(y1, 0.0f, (float)bgr.rows);
        y2 = std::clamp(y2, 0.0f, (float)bgr.rows);
        dets.push_back({{best_cls, best, cv::Rect2f(cv::Point2f(x1, y1), cv::Point2f(x2, y2))}});
    }}
    std::vector<Detection> final_dets;
    for (int cls = 0; cls < 4; ++cls) {{
        std::vector<Detection> one;
        for (const auto& d : dets) if (d.cls == cls) one.push_back(d);
        for (int idx : nms(one, iou_thres)) final_dets.push_back(one[idx]);
    }}
    return final_dets;
}}
'''
    write_text(OUT / "deploy" / "infer_onnx.py", py)
    write_text(OUT / "deploy" / "infer_onnx.cpp", cpp)


def write_compare(results, choice, reason, deploy_info, verify):
    rows = []
    for r in sorted(results, key=lambda x: x["imgsz"]):
        rows.append([
            f"YOLOv8n-{r['imgsz']}",
            f"{r['precision']:.4f}",
            f"{r['recall']:.4f}",
            f"{r['map50']:.4f}",
            f"{r['map50_95']:.4f}",
            json.dumps(r["speed"], ensure_ascii=False),
        ])
    text = f"""# Meter YOLO Training Report

## Validation Comparison

{md_table(rows, ['model', 'Precision', 'Recall', 'mAP50', 'mAP50-95', 'speed(ms)'])}

## Recommendation

Recommended: **YOLOv8n-{choice['imgsz']}**

Reason: {reason}

For RZ/G2L Cortex-A55, 320 input has about one quarter of the pixel compute of 640 input. Choose 640 only if its recall gain is necessary for stable tip/start/end detection.

## Export

`{deploy_info['pt']}`

`{deploy_info['onnx']}`

ONNX size: **{deploy_info['onnx_size_mb']} MB**

Input size: `{deploy_info['input_size']}`

Model info: `{deploy_info['model_info']}`

Estimated Cortex-A55 CPU latency: **YOLOv8n-320 roughly 150-450 ms**, **YOLOv8n-640 roughly 600-1600 ms** depending on ONNX Runtime build, NEON, thread count, image decode, and thermal state.

## ONNX Verification

```json
{json.dumps(verify, indent=2, ensure_ascii=False)}
```
"""
    write_text(OUT / "compare_report.md", text)
    write_text(OUT / "final_report.md", text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["all", "prep", "train", "export"], default="all")
    parser.add_argument("--epochs", type=int, default=100)
    args = parser.parse_args()

    os.environ.setdefault("YOLO_CONFIG_DIR", str(OUT / "Ultralytics"))
    ensure_dirs()
    data_yaml = write_dataset_yaml()
    print(f"dataset yaml: {data_yaml}")

    if args.stage in ["all", "prep"]:
        env = env_report()
        print(json.dumps(env, indent=2, ensure_ascii=False))
        analyze_dataset()
        draw_preview(20)
        if args.stage == "prep":
            return

    if args.stage in ["all", "train"]:
        results = []
        run_dirs = {}
        for imgsz in [320, 640]:
            print(f"training YOLOv8n imgsz={imgsz}")
            run_dir = train_one(imgsz, args.epochs)
            run_dirs[imgsz] = run_dir
            result = validate_model(run_dir, imgsz)
            results.append(result)
        write_text(OUT / "runs" / "validation_results.json", json.dumps(results, indent=2, ensure_ascii=False))
    else:
        results = json.loads((OUT / "runs" / "validation_results.json").read_text(encoding="utf-8"))

    if args.stage in ["all", "export"]:
        choice, reason = recommend(results)
        pt_path = Path(choice["model"])
        final_pt, final_onnx = export_onnx(pt_path, choice["imgsz"])
        verify = verify_onnx(final_pt, final_onnx, choice["imgsz"])
        deploy_info = model_info(final_pt, final_onnx, choice["imgsz"])
        generate_deploy_code(choice["imgsz"])
        write_compare(results, choice, reason, deploy_info, verify)
        print(f"recommended YOLOv8n-{choice['imgsz']}: {reason}")
        print(f"exported: {final_onnx}")


if __name__ == "__main__":
    main()
