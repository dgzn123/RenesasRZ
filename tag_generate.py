#!/usr/bin/env python3
"""ArUco tag generator — encode meter parameters into tag ID + config file."""

import cv2
import numpy as np
import json
import os
import sys
import argparse

DICT_NAME = "DICT_4X4_50"
OUT_DIR = "tags_output"
CONFIG_FILE = "tags_config.json"


def generate_tag(tag_id, size_px=400, border_bits=1):
    """Generate a single ArUco tag as a BGR numpy array.

    border_bits: width of white quiet zone in marker-cell units (default 1).
                 OpenCV requires this for detection — do NOT set to 0.
    """
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if tag_id < 0 or tag_id > 49:
        raise ValueError(f"Tag ID must be 0–49 for {DICT_NAME}, got {tag_id}")

    img = np.ones((size_px, size_px), dtype=np.uint8) * 255
    cv2.aruco.generateImageMarker(aruco_dict, tag_id, size_px, img, border_bits)
    out = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return out


def draw_label(img, tag_id, name, params):
    """Add label text below the tag for human reference."""
    h, w = img.shape[:2]
    label_h = 60
    canvas = np.ones((h + label_h, w, 3), dtype=np.uint8) * 255

    # Center the tag
    canvas[:h, :] = img

    # Label area
    lines = [
        f"ID:{tag_id}  {name}",
        f"min={params['min']}  max={params['max']}  divs={params['divisions']}"
    ]
    y = h + 18
    for line in lines:
        cv2.putText(canvas, line, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        y += 20

    return canvas


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            raw = f.read().strip()
            return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def add_tag(tag_id, name, min_val, max_val, divisions, size=400, border=1,
            sheet=False, sheet_cols=3):
    """Generate one tag, update config, return saved paths."""
    os.makedirs(OUT_DIR, exist_ok=True)

    if tag_id is None:
        # Auto-assign next available ID
        config = load_config()
        used = {int(k) for k in config.keys()}
        for i in range(50):
            if i not in used:
                tag_id = i
                break
        if tag_id is None:
            raise ValueError("All 50 tag IDs are used. Clear config or reuse an ID.")

    # Generate tag image (no label, clean — for printing)
    tag_img = generate_tag(tag_id, size, border)
    clean_path = os.path.join(OUT_DIR, f"tag_{tag_id:02d}.png")
    cv2.imwrite(clean_path, tag_img)

    # Generate labeled version (for reference)
    labeled = draw_label(tag_img, tag_id, name,
                         {"min": min_val, "max": max_val, "divisions": divisions})
    labeled_path = os.path.join(OUT_DIR, f"tag_{tag_id:02d}_labeled.png")
    cv2.imwrite(labeled_path, labeled)

    # Update config
    config = load_config()
    config[str(tag_id)] = {
        "name": name,
        "min": min_val,
        "max": max_val,
        "divisions": divisions
    }
    save_config(config)

    print(f"  Tag ID={tag_id:02d}  {name}")
    print(f"    params: min={min_val}, max={max_val}, divisions={divisions}")
    print(f"    clean:   {clean_path}")
    print(f"    labeled: {labeled_path}")

    # Print hint
    size_cm = size / 100  # rough: 100px ≈ 1cm on screen
    print(f"    print at ~{size_cm:.1f}×{size_cm:.1f} cm, cut along border")
    print()

    return tag_id


# ── Sheet mode: arrange multiple tags on one printable page ────
def generate_sheet(config, size=400, border=1, cols=3):
    """Generate a printable A4 sheet with all configured tags."""
    if not config:
        print("No tags in config. Add tags first.")
        return

    entries = [(int(k), v) for k, v in config.items()]
    entries.sort()

    rows = (len(entries) + cols - 1) // cols
    cell_w = size + 40   # tag + padding
    cell_h = size + 100  # tag + label area

    sheet_w = cell_w * cols + 40
    sheet_h = cell_h * rows + 40
    sheet = np.ones((sheet_h, sheet_w, 3), dtype=np.uint8) * 255

    for idx, (tag_id, info) in enumerate(entries):
        r, c = idx // cols, idx % cols
        x = 20 + c * cell_w
        y = 20 + r * cell_h

        tag_img = generate_tag(tag_id, size, border)
        labeled = draw_label(tag_img, tag_id, info["name"], info)

        h, w = labeled.shape[:2]
        # Fit into cell
        sheet[y:y + h, x:x + w] = labeled

    sheet_path = os.path.join(OUT_DIR, "tags_sheet.png")
    cv2.imwrite(sheet_path, sheet)
    print(f"Sheet saved: {sheet_path}")
    print(f"  {len(entries)} tags, {cols} columns, {rows} rows")


# ── CLI ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate ArUco tags with meter parameter encoding"
    )
    sub = parser.add_subparsers(dest="cmd")

    # add
    p_add = sub.add_parser("add", help="Add a single tag")
    p_add.add_argument("--id", type=int, default=None,
                       help="Tag ID (0–49), auto-assigned if omitted")
    p_add.add_argument("--name", required=True, help="Meter name, e.g. WSS-401")
    p_add.add_argument("--min", type=float, required=True, dest="min_val",
                       help="Meter scale minimum")
    p_add.add_argument("--max", type=float, required=True, dest="max_val",
                       help="Meter scale maximum")
    p_add.add_argument("--divisions", type=int, required=True,
                       help="Number of scale divisions")
    p_add.add_argument("--size", type=int, default=400,
                       help="Tag image size in pixels (default 400)")
    p_add.add_argument("--border", type=int, default=1,
                       help="White border width in marker cells (default 1, min 1)")

    # batch
    p_batch = sub.add_parser("batch", help="Batch import from JSON file")
    p_batch.add_argument("file", help="Path to JSON file")
    p_batch.add_argument("--size", type=int, default=400)
    p_batch.add_argument("--border", type=int, default=1)

    # sheet
    p_sheet = sub.add_parser("sheet", help="Generate printable sheet of all tags")
    p_sheet.add_argument("--size", type=int, default=400)
    p_sheet.add_argument("--border", type=int, default=1)
    p_sheet.add_argument("--cols", type=int, default=3,
                         help="Tags per row (default 3)")

    # list
    p_list = sub.add_parser("list", help="List all configured tags")

    # delete
    p_del = sub.add_parser("delete", help="Remove a tag from config")
    p_del.add_argument("id", type=int, help="Tag ID to remove")

    args = parser.parse_args()

    if args.cmd == "add":
        tag_id = add_tag(args.id, args.name, args.min_val, args.max_val,
                         args.divisions, args.size, args.border)
        print(f"Done. Config saved to {CONFIG_FILE}")

    elif args.cmd == "batch":
        with open(args.file, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print("Error: batch file must be a JSON array of tag objects")
            sys.exit(1)
        for item in data:
            add_tag(item.get("id"), item["name"],
                    item["min"], item["max"], item["divisions"],
                    args.size, args.border)
        print(f"Batch done. {len(data)} tags, config saved to {CONFIG_FILE}")

    elif args.cmd == "sheet":
        config = load_config()
        generate_sheet(config, args.size, args.border, args.cols)

    elif args.cmd == "list":
        config = load_config()
        if not config:
            print("No tags configured. Use 'add' to create one.")
        else:
            print(f"{'ID':<5} {'Name':<20} {'min':<8} {'max':<8} {'divisions'}")
            print("-" * 56)
            for tid in sorted(config.keys(), key=int):
                c = config[tid]
                print(f"{tid:<5} {c['name']:<20} {c['min']:<8} {c['max']:<8} {c['divisions']}")

    elif args.cmd == "delete":
        config = load_config()
        tid = str(args.id)
        if tid in config:
            name = config[tid]["name"]
            del config[tid]
            save_config(config)
            print(f"Deleted tag ID={args.id} ({name})")
        else:
            print(f"Tag ID={args.id} not found")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
