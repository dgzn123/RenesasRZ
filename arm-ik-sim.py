#!/usr/bin/env python3
"""
三关节平面臂运动学仿真 — 拖动红点直接控制末端。
角度约定: 0°=竖直向上, 正值=逆时针, Z轴=竖直向上。
"""
import math
import tkinter as tk
from tkinter import ttk

# ─── 机械臂参数 ───
L1 = 105.0   # 肩 → 肘 (mm)
L2 = 100.0   # 肘 → 腕 (mm)
L3 = 90.0    # 腕 → 末端 (mm)
THICK = 25.0        # 连杆宽度 (mm)
JOINT_R = 12.5      # 关节半径 (mm)

# 关节限位
J1_MIN, J1_MAX = -90, 90
J2_MIN, J2_MAX = -150, 150
J3_MIN, J3_MAX = -150, 90


def fk(j1, j2, j3):
    a1, a2, a3 = math.radians(j1), math.radians(j1 + j2), math.radians(j1 + j2 + j3)
    s0 = (0.0, 0.0)
    s1 = (L1 * math.sin(a1),                    L1 * math.cos(a1))
    s2 = (s1[0] + L2 * math.sin(a2),            s1[1] + L2 * math.cos(a2))
    s3 = (s2[0] + L3 * math.sin(a3),            s2[1] + L3 * math.cos(a3))
    return [s0, s1, s2, s3], s3


def ik(ty, tz, gripper_angle=180.0, current=None):
    """current=(j1,j2,j3) 可选，用于在多个解中选离当前位姿最近的，避免突变"""
    phi = math.radians(gripper_angle)
    wy = ty - L3 * math.sin(phi)
    wz = tz - L3 * math.cos(phi)
    d = math.hypot(wy, wz)
    if d > L1 + L2 + 0.01 or d < abs(L1 - L2) - 0.01:
        return None
    cos_a2 = (wy**2 + wz**2 - L1**2 - L2**2) / (2 * L1 * L2)
    cos_a2 = max(-1.0, min(1.0, cos_a2))
    a2_pos = math.acos(cos_a2)
    solutions = []
    for a2 in (a2_pos, -a2_pos):
        alpha = math.atan2(wy, wz)
        beta = math.atan2(L2 * math.sin(a2), L1 + L2 * math.cos(a2))
        a1 = alpha - beta
        a3 = phi - (a1 + a2)

        def wrap(x):
            while x > 180: x -= 360
            while x < -180: x += 360
            return x

        j1, j2, j3 = wrap(math.degrees(a1)), wrap(math.degrees(a2)), wrap(math.degrees(a3))
        if (J1_MIN <= j1 <= J1_MAX and
            J2_MIN <= j2 <= J2_MAX and
            J3_MIN <= j3 <= J3_MAX):
            if current:
                c1, c2, c3 = current
                dist = abs(j1-c1) + abs(j2-c2) + abs(j3-c3)
                solutions.append((dist, (j1, j2, j3)))
            else:
                solutions.append((0, (j1, j2, j3)))
    if not solutions:
        return None
    solutions.sort(key=lambda x: x[0])
    return solutions[0][1]


# ─── GUI ───
root = tk.Tk()
root.title("三关节机械臂 IK 仿真  |  拖动红点控制末端  |  滚轮改末端方向")

W, H = 700, 580
OX, OY = 300, 500  # 肩原点(画布坐标)
_drag = False

canvas = tk.Canvas(root, width=W, height=H, bg='#F1F2F5')
canvas.pack(side=tk.LEFT, padx=10, pady=10)

# ── 控制面板 ──
ctrl = ttk.Frame(root)
ctrl.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

grip_var = tk.DoubleVar(value=180.0)
ttk.Label(ctrl, text='末端方向（滚轮/滑块）', font=('', 11, 'bold')).pack()
grip_frame = ttk.Frame(ctrl)
grip_frame.pack(pady=5)
ttk.Button(grip_frame, text='↑ 0°', command=lambda: set_grip(0)).pack(side=tk.LEFT)
ttk.Button(grip_frame, text='→ 90°', command=lambda: set_grip(90)).pack(side=tk.LEFT)
ttk.Button(grip_frame, text='↓ 180°', command=lambda: set_grip(180)).pack(side=tk.LEFT)
ttk.Scale(ctrl, from_=-180, to=180, variable=grip_var, orient=tk.HORIZONTAL, length=220,
          command=lambda v: apply_ik()).pack()
grip_val_label = ttk.Label(ctrl, text='180°', font=('Consolas', 14, 'bold'), foreground='#002FA7')
grip_val_label.pack()

def set_grip(v):
    grip_var.set(v)
    grip_val_label.config(text=f'{v}°')
    apply_ik()

ttk.Separator(ctrl, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)

base_var = tk.DoubleVar(value=0.0)
j1_var = tk.DoubleVar(value=0.0)
j2_var = tk.DoubleVar(value=0.0)
j3_var = tk.DoubleVar(value=0.0)

# ── 归零按钮 ──
def go_home():
    base_var.set(0); j1_var.set(0); j2_var.set(0); j3_var.set(0)
    draw()
ttk.Button(ctrl, text='一键归零 (↑)', command=go_home).pack(pady=(8, 4))

# ── 关节控制（滑块 + 手动输入） ──
def make_joint_row(name, var, lo, hi):
    row = ttk.Frame(ctrl)
    row.pack(fill=tk.X, pady=4)

    ttk.Label(row, text=f'{name}', font=('', 10, 'bold'), width=6).pack(side=tk.LEFT)

    # 值显示
    ttk.Label(row, textvariable=var, width=5, font=('Consolas', 10)).pack(side=tk.RIGHT)

    # 滑块
    s = ttk.Scale(row, from_=lo, to=hi, variable=var, orient=tk.HORIZONTAL, length=120,
                  command=lambda v: draw())
    s.pack(side=tk.RIGHT, padx=5)

    # 手动输入框
    sv = tk.StringVar(value='0')
    entry = ttk.Entry(row, width=6, font=('Consolas', 11), textvariable=sv)
    entry.pack(side=tk.RIGHT, padx=(5, 0))

    _updating = False
    def on_var_write(*args):
        nonlocal _updating
        if _updating: return
        _updating = True
        sv.set(f'{var.get():.0f}')
        _updating = False

    def on_entry_write(*args):
        nonlocal _updating
        if _updating: return
        try:
            v = float(sv.get())
            v = max(lo, min(hi, v))
            _updating = True
            var.set(v)
            _updating = False
            draw()
        except ValueError:
            pass

    var.trace_add('write', on_var_write)
    sv.trace_add('write', on_entry_write)

    return s, entry

make_joint_row('BASE', base_var, -180, 180)
make_joint_row('J1 肩', j1_var, J1_MIN, J1_MAX)
make_joint_row('J2 肘', j2_var, J2_MIN, J2_MAX)
make_joint_row('J3 腕', j3_var, J3_MIN, J3_MAX)

# ── 轴锁定 ──
ttk.Separator(ctrl, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)
ttk.Label(ctrl, text='拖动约束', font=('', 10, 'bold')).pack()
lock_frame = ttk.Frame(ctrl)
lock_frame.pack(pady=5)

lock_z = tk.BooleanVar(value=False)
lock_y = tk.BooleanVar(value=False)
lock_z_val = 0.0  # 锁定时记录的 Z 值
lock_y_val = 0.0  # 锁定时记录的 Y 值

def toggle_lock(axis):
    """锁定轴时记录当前位置"""
    _, end = fk(j1_var.get(), j2_var.get(), j3_var.get())
    global lock_z_val, lock_y_val
    if axis == 'z' and lock_z.get():
        lock_z_val = end[1]
    if axis == 'y' and lock_y.get():
        lock_y_val = end[0]
    # 互斥样式
    z_cb.config(text='Z 锁定' if lock_z.get() else 'Z 自由')
    y_cb.config(text='Y 锁定' if lock_y.get() else 'Y 自由')

z_cb = ttk.Checkbutton(lock_frame, text='Z 自由', variable=lock_z, command=lambda: toggle_lock('z'))
z_cb.pack(side=tk.LEFT, padx=5)
y_cb = ttk.Checkbutton(lock_frame, text='Y 自由', variable=lock_y, command=lambda: toggle_lock('y'))
y_cb.pack(side=tk.LEFT, padx=5)

ttk.Separator(ctrl, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)
ttk.Label(ctrl, text='末端 (Y, Z) mm', font=('', 11, 'bold')).pack()
pos_label = ttk.Label(ctrl, text='', font=('Consolas', 14))
pos_label.pack()
ttk.Label(ctrl, text='串口指令', font=('', 11, 'bold')).pack(pady=(8, 0))
cmd_label = ttk.Label(ctrl, text='', font=('Consolas', 13), foreground='#002FA7')
cmd_label.pack()

# 用于随时输出指令到文件，方便外部读取
ttk.Separator(ctrl, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)
ttk.Label(ctrl, text='记录序列', font=('', 10, 'bold')).pack()
history_text = tk.Text(ctrl, height=8, width=30, font=('Consolas', 9))
history_text.pack(pady=5)
def record_cmd():
    base, j1, j2, j3 = base_var.get(), j1_var.get(), j2_var.get(), j3_var.get()
    cmd = f'$ARM,{base:.0f},{j1:.0f},{j2:.0f},{j3:.0f}'
    history_text.insert('end', cmd + '\n')
    history_text.see('end')
ttk.Button(ctrl, text='记录当前位置', command=record_cmd).pack()


def world_to_canvas(wy, wz):
    return OX + wy, OY - wz


def canvas_to_world(cx, cy):
    return cx - OX, OY - cy


def draw():
    j1, j2, j3 = j1_var.get(), j2_var.get(), j3_var.get()
    pts, end = fk(j1, j2, j3)

    canvas.delete('all')
    # 网格
    for gy in range(-100, 500, 50):
        y = OY - gy
        canvas.create_line(0, int(y), W, int(y), fill='#D6DAE0', dash=(2, 4))
    for gz in range(-300, 400, 50):
        x = OX + gz
        canvas.create_line(int(x), 0, int(x), H, fill='#D6DAE0', dash=(2, 4))

    # 工作空间边界圆
    r_max, r_min = L1 + L2 + L3, abs(L1 - L2) - L3
    # 外边界
    canvas.create_oval(int(OX - r_max), int(OY - r_max),
                       int(OX + r_max), int(OY + r_max), outline='#D6DAE0', width=1)

    # 坐标轴
    canvas.create_line(OX, 0, OX, H, fill='#B82830', width=1, dash=(4, 6))
    canvas.create_line(0, OY, W, OY, fill='#1F7A4F', width=1, dash=(4, 6))
    canvas.create_text(OX+8, 12, text='Z↑', fill='#B82830', font=('', 9), anchor='w')
    canvas.create_text(W-12, OY-10, text='Y→', fill='#1F7A4F', font=('', 9), anchor='se')

    # 连杆（矩形，厚度按 THICK）
    for i in range(len(pts)-1):
        p1, p2 = pts[i], pts[i+1]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 1:
            continue
        # 单位方向向量
        ux, uy = dx / length, dy / length
        # 法向量（垂直方向）
        nx, ny = -uy, ux
        half_t = THICK / 2
        # 矩形四个顶点
        corners = [
            (p1[0] + nx * half_t, p1[1] + ny * half_t),
            (p1[0] - nx * half_t, p1[1] - ny * half_t),
            (p2[0] - nx * half_t, p2[1] - ny * half_t),
            (p2[0] + nx * half_t, p2[1] + ny * half_t),
        ]
        # 转为画布坐标
        cpts = [world_to_canvas(*c) for c in corners]
        flat = []
        for c in cpts:
            flat.extend([int(c[0]), int(c[1])])
        canvas.create_polygon(*flat, fill='#002FA7', outline='')

    # 关节圆（半径 JOINT_R）
    for i in range(len(pts)):
        x, y = world_to_canvas(*pts[i])
        r = JOINT_R
        color = '#1A5BDB' if i == 0 else '#002FA7'
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline='')

    # 肩部基座
    sx, sy = world_to_canvas(0, 0)
    canvas.create_rectangle(sx-12, sy, sx+12, sy+14, fill='#5C606A', outline='')
    canvas.create_text(sx, sy+20, text='肩', fill='#5C606A', font=('', 9))

    # 末端方向指示器（灰色棍，从红点伸出）
    angle = j1 + j2 + j3 + grip_var.get()  # 绝对角度（从竖直向上）
    edx = math.sin(math.radians(angle)) * 30
    edz = math.cos(math.radians(angle)) * 30
    ex, ey = world_to_canvas(*end)
    ix, iy = world_to_canvas(end[0] + edx, end[1] + edz)
    canvas.create_line(int(ex), int(ey), int(ix), int(iy), fill='#5C606A', width=3, arrow='last')

    # 末端红点 + 夹爪示意
    R = JOINT_R + 1
    canvas.create_oval(ex-R, ey-R, ex+R, ey+R, fill='#B82830', outline='#FFFFFF', width=2, tags='end')
    # 夹爪两条线
    canvas.create_line(int(ix), int(iy), int(ix-6), int(iy+8), fill='#B82830', width=2)
    canvas.create_line(int(ix), int(iy), int(ix+6), int(iy+8), fill='#B82830', width=2)

    pos_label.config(text=f'BASE={base_var.get():.0f}  Y={end[0]:.0f}  Z={end[1]:.0f}')
    cmd_label.config(text=f'$ARM,{base_var.get():.0f},{j1:.0f},{j2:.0f},{j3:.0f}')


def apply_ik(*args):
    grip_val_label.config(text=f'{grip_var.get():.0f}°')
    cur = (j1_var.get(), j2_var.get(), j3_var.get())
    _, end = fk(*cur)
    result = ik(end[0], end[1], grip_var.get(), current=cur)
    if result:
        j1_var.set(result[0])
        j2_var.set(result[1])
        j3_var.set(result[2])
        cmd_label.config(text=f'$ARM,{base_var.get():.0f},{result[0]:.0f},{result[1]:.0f},{result[2]:.0f}')
    else:
        cmd_label.config(text='[不可达—换末端方向或先拖动]')
    draw()


def update_fk():
    draw()


# ── 鼠标拖动：点住画布任意位置，拖到哪末端跟到哪 ──
_drag = False
_status_id = None  # 画布上的状态提示文字 ID

def on_press(event):
    global _drag
    _drag = True
    canvas.config(cursor='fleur')

def on_move(event):
    if not _drag:
        return
    wy, wz = canvas_to_world(event.x, event.y)
    if lock_z.get():
        wz = lock_z_val
    if lock_y.get():
        wy = lock_y_val
    cur = (j1_var.get(), j2_var.get(), j3_var.get())
    result = ik(wy, wz, grip_var.get(), current=cur)
    if result:
        j1_var.set(result[0])
        j2_var.set(result[1])
        j3_var.set(result[2])
        draw()

def on_release(event):
    global _drag
    _drag = False
    canvas.config(cursor='')

canvas.bind('<ButtonPress-1>', on_press)
canvas.bind('<B1-Motion>', on_move)
canvas.bind('<ButtonRelease-1>', on_release)

# ── 滚轮调末端方向 ──
def on_wheel(event):
    delta = 15 if event.delta > 0 else -15
    grip_var.set(grip_var.get() + delta)
    apply_ik()
canvas.bind('<MouseWheel>', on_wheel)
canvas.bind('<Control-MouseWheel>', on_wheel)

draw()
root.mainloop()
