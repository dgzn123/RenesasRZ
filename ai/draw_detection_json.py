import json
import sys
from pathlib import Path

import cv2

COLORS = {
    "base": (60, 80, 255),
    "end": (255, 180, 60),
    "start": (80, 220, 120),
    "tip": (80, 80, 255),
}

img_path = Path(sys.argv[1])
json_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])

img = cv2.imread(str(img_path))
raw = json_path.read_bytes()
try:
    text = raw.decode("utf-8")
except UnicodeDecodeError:
    text = raw.decode("utf-16")
dets = json.loads(text)

for d in dets:
    name = d["class_name"]
    conf = d["confidence"]
    x1, y1, x2, y2 = [int(round(v)) for v in d["box_xyxy"]]
    color = COLORS.get(name, (255, 255, 255))
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    cv2.putText(img, f"{name} {conf:.2f}", (x1, max(18, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

cv2.imwrite(str(out_path), img)
