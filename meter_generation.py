#!/usr/bin/env python3
"""
meter_generation.py — 优弧指针仪表生成器

根据传入的最小值、最大值、分度值、当前值生成仪表 PNG 图片。

用法:
    python3 meter_generation.py --min 0 --max 25 --divisions 50 --value 5.95
    python3 meter_generation.py --min 0 --max 6 --divisions 29 --value 3.2 --output my_meter.png
    python3 meter_generation.py --min -10 --max 40 --divisions 25 --value 15 --title "电压表"
"""

import argparse
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# 优弧跨度：270°，底部缺口 90°，起始于左下（约 135° 数学角）
ARC_START_DEG = 225   # 左下起始（数学角度，0°=右，逆时针）
ARC_SWEEP_DEG = 270   # 跨度 270°
ARC_END_DEG = ARC_START_DEG + ARC_SWEEP_DEG  # 495° = 135°


def _font(size):
    """跨平台字体回退。"""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",    # 黑体
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def value_to_angle(value, min_val, max_val):
    """将仪表值映射到优弧上的角度（度）。返回数学角度。"""
    fraction = (value - min_val) / (max_val - min_val)
    fraction = max(0.0, min(1.0, fraction))
    return ARC_START_DEG + fraction * ARC_SWEEP_DEG


def _polar_xy(cx, cy, radius, angle_deg):
    """数学角度 → 像素坐标，0°=右，逆时针。"""
    rad = math.radians(angle_deg)
    return (cx + radius * math.cos(rad), cy - radius * math.sin(rad))


def generate_meter(
    min_val,
    max_val,
    divisions,
    value,
    output_path,
    title=None,
    size=800,
):
    W, H = size, size
    cx, cy = W / 2, H / 2
    R_outer = size * 0.42       # 刻度弧外半径
    R_inner = size * 0.34       # 刻度弧内半径
    R_major_tick = size * 0.36  # 长刻度终点
    R_minor_tick = size * 0.355
    R_label = size * 0.29       # 标签半径
    R_needle = size * 0.32      # 指针长度
    needle_base_w = size * 0.018  # 指针基部半宽（像素）
    center_radius = size * 0.025

    img = Image.new("RGB", (W, H), (248, 248, 250))
    draw = ImageDraw.Draw(img)

    # ── 优弧刻度带（扇形）───────────────────────────────────────
    band_w = R_outer - R_inner
    mid_R = (R_outer + R_inner) / 2
    # 将数学角度 (0°=右, CCW) 转换为 PIL arc 的角度 (0°=3点, CW)
    pil_start = 360 - (ARC_START_DEG % 360)
    if pil_start == 360:
        pil_start = 0
    pil_end = pil_start - ARC_SWEEP_DEG
    draw.arc(
        (cx - R_outer, cy - R_outer, cx + R_outer, cy + R_outer),
        pil_end, pil_start, fill=(180, 182, 190), width=int(band_w),
    )
    # 内边界
    draw.arc(
        (cx - R_inner, cy - R_inner, cx + R_inner, cy + R_inner),
        pil_end + 1, pil_start - 1, fill=(220, 222, 228), width=2,
    )
    # 外边界
    draw.arc(
        (cx - R_outer, cy - R_outer, cx + R_outer, cy + R_outer),
        pil_end, pil_start, fill=(180, 182, 190), width=2,
    )

    # ── 刻度线和标签 ────────────────────────────────────────────
    font_label = _font(int(size * 0.026))
    font_value = _font(int(size * 0.09))

    sub_per_div = 5
    total_sub = divisions * sub_per_div
    for i in range(total_sub + 1):
        fraction = i / total_sub
        sub_angle = ARC_START_DEG + fraction * ARC_SWEEP_DEG
        is_major = (i % sub_per_div == 0)
        r_start = R_outer + 1
        r_end = R_major_tick if is_major else R_minor_tick
        x1, y1 = _polar_xy(cx, cy, r_start, sub_angle)
        x2, y2 = _polar_xy(cx, cy, r_end, sub_angle)
        draw.line([(x1, y1), (x2, y2)],
                  fill=(70, 72, 80) if is_major else (160, 162, 170),
                  width=max(1, int(size * 0.0045)) if is_major else 1)

    # 数字标签
    for i in range(divisions + 1):
        val = min_val + (max_val - min_val) * i / divisions
        angle = value_to_angle(val, min_val, max_val)
        x, y = _polar_xy(cx, cy, R_label, angle)
        text = f"{val:.6g}"
        bbox = draw.textbbox((0, 0), text, font=font_label)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x - tw / 2, y - th / 2), text, fill=(50, 52, 60), font=font_label)

    # ── 指针 ────────────────────────────────────────────────────
    needle_angle = value_to_angle(value, min_val, max_val)
    tx, ty = _polar_xy(cx, cy, R_needle, needle_angle)
    base_left = needle_angle + 105
    base_right = needle_angle - 105
    blx, bly = _polar_xy(cx, cy, needle_base_w, base_left)
    brx, bry = _polar_xy(cx, cy, needle_base_w, base_right)
    draw.polygon([(blx, bly), (tx, ty), (brx, bry)], fill=(200, 40, 30))

    # ── 中心圆 ──────────────────────────────────────────────────
    draw.ellipse(
        (cx - center_radius, cy - center_radius,
         cx + center_radius, cy + center_radius),
        fill=(60, 62, 70), outline=(40, 42, 50),
        width=max(1, int(size * 0.003)),
    )

    # ── 当前值 + 单位 ────────────────────────────────────────────
    value_text = f"{value:.2f}"
    bbox = draw.textbbox((0, 0), value_text, font=font_value)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw / 2, cy + center_radius + size * 0.06),
              value_text, fill=(30, 32, 40), font=font_value)

    # ── 标题 ────────────────────────────────────────────────────
    if title:
        font_title = _font(int(size * 0.04))
        bbox = draw.textbbox((0, 0), title, font=font_title)
        tw, _ = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2, cy + center_radius + size * 0.16),
                  title, fill=(100, 102, 110), font=font_title)

    # ── 保存 ────────────────────────────────────────────────────
    img.save(output_path)
    print(f"仪表已保存: {output_path}")
    print(f"  范围 {min_val} ~ {max_val}, 分度 {divisions}, 当前 {value:.2f}")


def main():
    parser = argparse.ArgumentParser(description="优弧指针仪表生成器")
    parser.add_argument("--min", type=float, required=True, help="量程最小值")
    parser.add_argument("--max", type=float, required=True, help="量程最大值")
    parser.add_argument("--divisions", type=int, required=True, help="分度值（刻度格数）")
    parser.add_argument("--value", type=float, required=True, help="当前读数")
    parser.add_argument("--output", default="meter.png", help="输出图片路径（默认 meter.png）")
    parser.add_argument("--title", help="仪表标题（可选）")
    parser.add_argument("--size", type=int, default=800, help="图片尺寸像素（默认 800）")
    args = parser.parse_args()

    if args.divisions < 1:
        parser.error("divisions 必须 >= 1")
    if args.min >= args.max:
        parser.error("min 必须小于 max")

    generate_meter(
        min_val=args.min,
        max_val=args.max,
        divisions=args.divisions,
        value=args.value,
        output_path=args.output,
        title=args.title,
        size=args.size,
    )


if __name__ == "__main__":
    main()
