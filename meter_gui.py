#!/usr/bin/env python3
"""
meter_gui.py — 实时优弧指针仪表 GUI

左侧输入参数，右侧 Canvas 即时重绘。右下角一键导出 PNG。

用法:
    python3 meter_gui.py
"""

import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageDraw, ImageFont

# ─── 常量 ───────────────────────────────────────────────────
ARC_START = 315   # 右下起始，劣弧缺口正对底部
ARC_SWEEP = 270   # 跨度
CANVAS_W = 620
CANVAS_H = 620


def value_to_angle(value, min_val, max_val):
    fraction = (value - min_val) / (max_val - min_val)
    fraction = max(0.0, min(1.0, fraction))
    return ARC_START + fraction * ARC_SWEEP


def polar_xy(cx, cy, r, deg):
    rad = math.radians(deg)
    return cx + r * math.cos(rad), cy - r * math.sin(rad)


class MeterGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("优弧仪表生成器 — meter_gui")
        self.root.geometry("920x660")
        self.root.configure(bg="#f0f0f2")

        # ── 左侧控制 ──────────────────────────────────────────
        ctrl = tk.Frame(self.root, bg="#f0f0f2", padx=20, pady=20)
        ctrl.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(ctrl, text="仪表参数", font=("微软雅黑", 16, "bold"),
                 bg="#f0f0f2", fg="#002FA7").pack(anchor=tk.W, pady=(0, 16))

        self.fields = {}
        for label, key, default in [
            ("最小值", "min", 0.0), ("最大值", "max", 25.0),
            ("分度值", "divisions", 50), ("当前值", "value", 5.95),
        ]:
            tk.Label(ctrl, text=label, font=("微软雅黑", 10),
                     bg="#f0f0f2", fg="#333").pack(anchor=tk.W)
            var = tk.StringVar(value=str(default))
            self.fields[key] = var
            spin = tk.Spinbox(
                ctrl, textvariable=var, from_=-999, to=9999,
                increment="0.1" if key != "divisions" else "1",
                width=14, font=("Consolas", 12),
                command=self.on_change, bg="white",
            )
            spin.pack(anchor=tk.W, pady=(2, 10))
            spin.bind("<Return>", lambda e: self.on_change())
            spin.bind("<FocusOut>", lambda e: self.on_change())

        # 标题
        tk.Label(ctrl, text="标题（可选）", font=("微软雅黑", 10),
                 bg="#f0f0f2", fg="#333").pack(anchor=tk.W)
        self.title_var = tk.StringVar(value="")
        tk.Entry(ctrl, textvariable=self.title_var, width=16,
                 font=("微软雅黑", 11), bg="white").pack(anchor=tk.W, pady=(2, 16))
        self.title_var.trace_add("write", lambda *a: self.on_change())

        # 导出按钮
        tk.Button(ctrl, text="导出 PNG", font=("微软雅黑", 12, "bold"),
                  bg="#002FA7", fg="white", activebackground="#001f7a",
                  activeforeground="white", relief=tk.FLAT, padx=30, pady=8,
                  cursor="hand2", command=self.export_png,
                  ).pack(anchor=tk.W, pady=(8, 0))

        # ── 右侧 Canvas ───────────────────────────────────────
        self.canvas = tk.Canvas(self.root, width=CANVAS_W, height=CANVAS_H,
                                bg="white", highlightthickness=0)
        self.canvas.pack(side=tk.RIGHT, padx=(0, 20), pady=20)

        self.root.after(100, self.draw)
        self.root.mainloop()

    # ── 参数读取 ──────────────────────────────────────────────
    def params(self):
        try:
            mn = float(self.fields["min"].get())
            mx = float(self.fields["max"].get())
            dv = int(float(self.fields["divisions"].get()))
            vl = float(self.fields["value"].get())
            title = self.title_var.get().strip()
            return mn, mx, dv, vl, title
        except (ValueError, tk.TclError):
            return None

    def on_change(self):
        self.draw()

    # ── Canvas 绘制 ───────────────────────────────────────────
    def draw(self):
        p = self.params()
        if p is None:
            return
        min_v, max_v, divs, value, title = p
        if min_v >= max_v or divs < 1:
            return

        c = self.canvas
        c.delete("all")
        W, H = CANVAS_W, CANVAS_H
        cx, cy = W / 2, H / 2
        R_outer = 280
        R_inner = 220
        R_major = 238
        R_minor = 228
        R_label = 195
        R_needle = 215
        center_r = 15

        # ── 弧带 ──────────────────────────────────────────────
        c.create_arc(cx - R_outer, cy - R_outer, cx + R_outer, cy + R_outer,
                     start=ARC_START, extent=ARC_SWEEP, style=tk.ARC,
                     outline="#c0c2c8", width=R_outer - R_inner)
        # 内外边线
        for R, w in [(R_outer, 1), (R_inner, 1)]:
            c.create_arc(cx - R, cy - R, cx + R, cy + R,
                         start=ARC_START, extent=ARC_SWEEP, style=tk.ARC,
                         outline="#a0a2a8", width=w)

        # ── 刻度线 ────────────────────────────────────────────
        sub_per = 1  # 仅长刻度
        total = divs * sub_per
        for i in range(total + 1):
            frac = i / total
            ang = ARC_START + frac * ARC_SWEEP
            r_end = R_major if i % sub_per == 0 else R_minor
            x1, y1 = polar_xy(cx, cy, R_outer + 2, ang)
            x2, y2 = polar_xy(cx, cy, r_end, ang)
            color = "#404248" if i % sub_per == 0 else "#a0a2a8"
            w = 2 if i % sub_per == 0 else 1
            c.create_line(x1, y1, x2, y2, fill=color, width=w)

        # ── 数字标签 ──────────────────────────────────────────
        for i in range(divs + 1):
            val = min_v + (max_v - min_v) * i / divs
            ang = value_to_angle(val, min_v, max_v)
            x, y = polar_xy(cx, cy, R_label, ang)
            text = f"{val:.6g}"
            c.create_text(x, y, text=text, fill="#303238",
                          font=("Consolas", 9), angle=ang - 90)

        # ── 指针 ──────────────────────────────────────────────
        needle_ang = value_to_angle(value, min_v, max_v)
        tx, ty = polar_xy(cx, cy, R_needle, needle_ang)
        bw = 10
        blx, bly = polar_xy(cx, cy, bw, needle_ang + 105)
        brx, bry = polar_xy(cx, cy, bw, needle_ang - 105)
        c.create_polygon(blx, bly, tx, ty, brx, bry,
                         fill="#c8281e", outline="#a01a14", width=1)

        # ── 中心圆 ────────────────────────────────────────────
        c.create_oval(cx - center_r, cy - center_r, cx + center_r, cy + center_r,
                      fill="#404248", outline="#2a2c30", width=2)

        # ── 当前值 ────────────────────────────────────────────
        c.create_text(cx, cy + center_r + 52, text=f"{value:.2f}",
                      fill="#1a1c20", font=("Consolas", 28, "bold"))

        # ── 标题 ──────────────────────────────────────────────
        if title:
            c.create_text(cx, cy + center_r + 95, text=title,
                          fill="#808288", font=("微软雅黑", 12))

        # ── 量程端点 ──────────────────────────────────────────
        c.create_text(*polar_xy(cx, cy, R_label - 16, ARC_START),
                      text=f"{min_v:.6g}", fill="#606268", font=("Consolas", 8))
        c.create_text(*polar_xy(cx, cy, R_label - 16, ARC_START + ARC_SWEEP),
                      text=f"{max_v:.6g}", fill="#606268", font=("Consolas", 8))

    # ── 导出 PNG ──────────────────────────────────────────────
    def export_png(self):
        p = self.params()
        if p is None or p[0] >= p[1] or p[2] < 1:
            messagebox.showwarning("参数错误", "请确保 min < max 且 divisions >= 1")
            return
        min_v, max_v, divs, value, title = p

        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")],
            initialfile="meter.png",
        )
        if not path:
            return

        size = 800
        cx = cy = size / 2
        R_outer = size * 0.42
        R_inner = size * 0.34
        R_major = size * 0.36
        R_minor = size * 0.355
        R_label = size * 0.29
        R_needle = size * 0.32
        needle_bw = size * 0.018
        center_r = size * 0.025

        img = Image.new("RGB", (size, size), (248, 248, 250))
        draw = ImageDraw.Draw(img)

        # 弧带
        band_w = R_outer - R_inner
        pil_start = (360 - (ARC_START % 360)) % 360
        pil_end = pil_start - ARC_SWEEP
        draw.arc((cx - R_outer, cy - R_outer, cx + R_outer, cy + R_outer),
                 pil_end, pil_start, fill=(180, 182, 190), width=int(band_w))
        for R in [R_inner, R_outer]:
            draw.arc((cx - R, cy - R, cx + R, cy + R),
                     pil_end, pil_start, fill=(160, 162, 170), width=2)

        # 刻度
        sub_per = 1  # 仅长刻度
        total = divs * sub_per
        for i in range(total + 1):
            frac = i / total
            ang = ARC_START + frac * ARC_SWEEP
            major = (i % sub_per == 0)
            r_end = R_major if major else R_minor
            x1, y1 = polar_xy(cx, cy, R_outer + 2, ang)
            x2, y2 = polar_xy(cx, cy, r_end, ang)
            draw.line([(x1, y1), (x2, y2)],
                      fill=(60, 62, 70) if major else (150, 152, 160),
                      width=max(2, int(size * 0.004)) if major else 1)

        # 标签
        try:
            font_lbl = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", int(size * 0.026))
        except Exception:
            font_lbl = ImageFont.load_default()
        for i in range(divs + 1):
            val = min_v + (max_v - min_v) * i / divs
            ang = value_to_angle(val, min_v, max_v)
            x, y = polar_xy(cx, cy, R_label, ang)
            text = f"{val:.6g}"
            bbox = draw.textbbox((0, 0), text, font=font_lbl)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x - tw / 2, y - th / 2), text, fill=(50, 52, 60), font=font_lbl)

        # 指针
        ang = value_to_angle(value, min_v, max_v)
        tx, ty = polar_xy(cx, cy, R_needle, ang)
        blx, bly = polar_xy(cx, cy, needle_bw, ang + 105)
        brx, bry = polar_xy(cx, cy, needle_bw, ang - 105)
        draw.polygon([(blx, bly), (tx, ty), (brx, bry)], fill=(200, 40, 30))

        # 中心圆
        draw.ellipse((cx - center_r, cy - center_r, cx + center_r, cy + center_r),
                     fill=(60, 62, 70), outline=(40, 42, 50), width=2)

        # 文字
        try:
            font_val = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", int(size * 0.09))
            font_title = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", int(size * 0.04))
        except Exception:
            font_val = font_title = ImageFont.load_default()

        vt = f"{value:.2f}"
        bbox = draw.textbbox((0, 0), vt, font=font_val)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2, cy + center_r + size * 0.06),
                  vt, fill=(30, 32, 40), font=font_val)

        if title:
            bbox = draw.textbbox((0, 0), title, font=font_title)
            tw, _ = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((cx - tw / 2, cy + center_r + size * 0.16),
                      title, fill=(100, 102, 110), font=font_title)

        img.save(path)
        messagebox.showinfo("导出成功", f"已保存: {path}")


if __name__ == "__main__":
    MeterGUI()
