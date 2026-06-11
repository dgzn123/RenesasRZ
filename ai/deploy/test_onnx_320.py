import argparse
import json
import random
import shutil
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


ROOT = Path(r"C:\Users\Heda\Desktop\index")
AI = ROOT / "ai"
DATA_YAML = AI / "dataset.yaml"
DATASET = Path(r"D:\Code\Qiansai\dataset7000")
PT = AI / "runs" / "yolov8n_320" / "weights" / "best.pt"
EXPORT = AI / "export"
VERIFY = AI / "onnx_verify"
DEPLOY = AI / "deploy"
IMG_SIZE = 320
CLASS_NAMES = ["base", "end", "start", "tip"]


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def list_images(split="test"):
    root = DATASET / "images" / split
    imgs = sorted(p for p in root.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"})
    if imgs:
        return imgs
    return sorted(p for p in (DATASET / "images").rglob("*.jpg"))


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


def preprocess(path):
    img0 = cv2.imread(str(path))
    if img0 is None:
        raise RuntimeError(f"failed to read image: {path}")
    img, ratio, pad = letterbox(img0)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    arr = img.transpose(2, 0, 1).astype(np.float32) / 255.0
    return arr[None], img0, ratio, pad


def nms(boxes, scores, iou_thres=0.45):
    if len(boxes) == 0:
        return []
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


def decode(output, img_shape, ratio, pad, conf_thres=0.25, iou_thres=0.45):
    pred = np.squeeze(output)
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
    h, w = img_shape[:2]
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
    results = []
    for cls in range(len(CLASS_NAMES)):
        idx = np.where(cls_ids == cls)[0]
        for local in nms(boxes[idx], scores[idx], iou_thres):
            j = idx[local]
            results.append(
                {
                    "class_id": int(cls_ids[j]),
                    "class_name": CLASS_NAMES[int(cls_ids[j])],
                    "confidence": float(scores[j]),
                    "box_xyxy": [float(x) for x in boxes[j]],
                }
            )
    return sorted(results, key=lambda x: x["confidence"], reverse=True)



def infer_image(image_path, model_path=r"C:\Users\Heda\Desktop\index\ai\export\best.onnx", conf=0.25, iou=0.45):
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    inp, img0, ratio, pad = preprocess(Path(image_path))
    out = sess.run(None, {input_name: inp})[0]
    return decode(out, img0.shape, ratio, pad, conf, iou)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--model", default=r"C:\Users\Heda\Desktop\index\ai\export\best.onnx")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.45)
    args = parser.parse_args()
    print(json.dumps(infer_image(args.image, args.model, args.conf, args.iou), indent=2, ensure_ascii=False))
