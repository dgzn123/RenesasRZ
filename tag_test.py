#!/usr/bin/env python3
"""Real-time ArUco tag viewer — PC webcam, press Q to quit."""

import cv2
import numpy as np

ARUCO_DICT = cv2.aruco.DICT_4X4_50
CAM_ID = 0  # default webcam


def main():
    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    params = cv2.aruco.DetectorParameters()

    cap = cv2.VideoCapture(CAM_ID)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    if not cap.isOpened():
        print(f"Cannot open camera {CAM_ID}")
        return

    # Try to load config for meter name lookup
    meter_cfg = {}
    try:
        import json
        with open("tags_config.json", "r") as f:
            meter_cfg = json.load(f)
    except Exception:
        pass

    print("ArUco tag viewer — press Q to quit, S to save snapshot")
    print(f"  Dictionary: {ARUCO_DICT}")
    if meter_cfg:
        print(f"  Meter config loaded: {list(meter_cfg.keys())}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t0 = cv2.getTickCount()
        detector = cv2.aruco.ArucoDetector(aruco_dict, params)
        corners, ids, _ = detector.detectMarkers(frame)
        elapsed = (cv2.getTickCount() - t0) / cv2.getTickFrequency() * 1000

        if ids is not None and len(corners) > 0:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)

            for i, corner in enumerate(corners):
                c = corner[0]
                cx = int(np.mean(c[:, 0]))
                cy = int(np.mean(c[:, 1]))
                tag_id = int(ids[i][0])

                # Meter ROI above tag
                tag_top = int(np.min(c[:, 1]))
                tag_left = int(np.min(c[:, 0]))
                tag_right = int(np.max(c[:, 0]))
                tag_h = int(np.max(c[:, 1])) - tag_top

                x1 = max(0, tag_left - tag_h // 2)
                y1 = max(0, tag_top - tag_h * 7 // 2)
                x2 = min(frame.shape[1], tag_right + tag_h // 2)
                y2 = max(0, tag_top - tag_h // 2)

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 47, 167), 2)
                cv2.putText(frame, "METER", (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 47, 167), 2)

                # Label with meter name if config available
                cfg = meter_cfg.get(str(tag_id), {})
                name = cfg.get("name", "")
                label = f"ID:{tag_id}"
                if name:
                    label += f" {name} (min={cfg['min']} max={cfg['max']} divs={cfg['divisions']})"
                cv2.putText(frame, label, (cx + 12, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)

        # HUD
        cv2.putText(frame, f"{elapsed:.0f}ms", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 47, 167), 2)
        n_tags = len(ids) if ids is not None else 0
        cv2.putText(frame, f"Tags: {n_tags}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)

        cv2.imshow("ArUco Tag Test", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            cv2.imwrite("tag_snapshot.jpg", frame)
            print("Snapshot saved: tag_snapshot.jpg")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
