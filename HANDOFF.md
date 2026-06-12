# RZ/G2L 智能工业监控系统 - 项目交接文档

## 硬件

- **开发板**: 飞凌 NET-RZG2D-C（瑞萨 RZ/G2L，ARM64）
- **摄像头**: ForwardRGB USB (VID:1817 PID:1130)，1080p 30fps MJPEG
- **激光雷达**: LDROBOT STL-19P，CP2102 USB 转串口（VID:10C4 PID:EA60），230400bps
- **电机驱动**: TB6612（待接线）
- **下位机**: RA8P1（Cortex-M85，已接线，通过 UART 串口 `/dev/ttySC0` 与 RZ/G2L 通信，115200bps）
- **扬声器**: WM8960 声卡，L/R 3.5mm 接口（预留，TTS 方案待定）

## 网络

- 有线 IP: 192.168.2.200（固定，接 dgzn123 路由器）
- WiFi 热点: dgzn123 / 12345678
- mDNS 域名: `renesas.local`
- 实际访问: `http://192.168.2.200/index.html`

## 文件分布

### 桌面 (C:\Users\Heda\Desktop\index)

| 文件 | 作用 |
|------|------|
| `index.html` | 网页主文件，上传到开发板 /www/matrix-gui-2.0/ |
| `capture.py` | 摄像头 V4L2 mmap 直驱推流，端口 8080 |
| `cam-control.php` | PHP，管理 capture.py 进程启停 |
| `lidar-start.py` | STL-19P 雷达一体脚本（HTTP+SSCAN+SSE），端口 8082 |
| `lidar-control.php` | PHP，管理雷达进程启停 |
| `tag-detect.py` | ArUco 标记检测服务，端口 8085 |
| `tag-control.php` | PHP，管理 tag-detect.py 启停 |
| `tag_generate.py` | PC 端生成 ArUco 标记+参数配置 |
| `tags_config.json` | tag ID → 仪表参数映射表 |
| `meter-read.php` | PHP，仪表读数流程编排 |
| `show-image.php` | PHP，图像查看；默认读 `/home/root/ai/capture/`，`source=photo` 时读 `/home/root/camera-server/photos/` |
| `term-proxy.php` | PHP，远程 shell 代理 |
| `meter-fn.js` | 仪表读数前端逻辑（备份参考） |
| `serial-test.py` | 串口双向通信测试（read()+空闲超时，避免 readline 碎片） |
| `serial-scan.py` | 波特率扫描工具（遍历常见速率确认 RA8P1 实际波特率） |
| `arm-ik-sim.py` | 三关节机械臂运动学仿真 PC 端工具（FK+IK，可拖动末端，输出串口指令） |
| `serial_bridge.py` | HTTP↔UART 桥接服务（端口 8084），串口 `/dev/ttySC0` 115200bps |
| `serial-control.php` | PHP 管理 serial_bridge.py 启停 |
| `home.svg` | 网站图标 |
| `design.png` | 首页左下角装饰图 |
| `CuteSeek2.png` | 顶栏用户头像，需随 `index.html` 上传到网页目录 |
| `model_alwaysonline/meter_service.py` | 常驻推理服务，加载 ONNX 模型常驻内存，8086 端口同步返回读数 |
| `meter-service-control.php` | PHP，管理常驻推理服务启停 |
| `HANDOFF.md` | 本文件 |

### 开发板

| 路径 | 作用 |
|------|------|
| `/www/matrix-gui-2.0/index.html` | 网页主文件（lighttpd 根目录） |
| `/www/matrix-gui-2.0/cam-control.php` | 摄像头启停 |
| `/www/matrix-gui-2.0/lidar-control.php` | 雷达启停 |
| `/www/matrix-gui-2.0/tag-control.php` | Tag 检测启停 |
| `/www/matrix-gui-2.0/meter-read.php` | 仪表读数 |
| `/www/matrix-gui-2.0/term-proxy.php` | 远程终端代理 |
| `/www/matrix-gui-2.0/show-image.php` | 仪表图像查看 |
| `/www/matrix-gui-2.0/CuteSeek2.png` | 顶栏用户头像 |
| `/home/root/camera-server/capture.py` | 摄像头服务 |
| `/home/root/camera-server/photos/` | 拍照存储 |
| `/home/root/lidar/lidar-start.py` | 雷达服务（STL-19P） |
| `/home/root/tag/tag-detect.py` | Tag 检测服务（ArUco） |
| `/home/root/tag/tags_config.json` | Tag 配置映射 |
| `/www/matrix-gui-2.0/meter-service-control.php` | 常驻推理服务启停 |
| `/home/root/ai/model_alwaysonline/meter_service.py` | 常驻推理服务 |
| `/home/root/ai/meter_roi.onnx` | 第一阶段模型（表盘 ROI 检测） |
| `/home/root/ai/best_points_320.onnx` | 第二阶段模型（四点检测） |
| `/home/root/ai/capture/` | 仪表读数拍摄照片 |
| `/home/root/ai/output/` | 仪表读数结果 |
| `/tmp/capture.pid` | 摄像头进程 PID |
| `/tmp/lidar.pid` | 雷达进程 PID |
| `/tmp/tag.pid` | Tag 检测进程 PID |
| `/tmp/lidar_scan.json` | 雷达扫描点云数据 |

## 摄像头系统

- **方案**: Python3 直驱 V4L2 mmap IO，零 ffmpeg 依赖
- **架构**: `capture.py:8080` 提供 `/stream` (MJPEG)、`/status` (JSON)、`/photo` (1080p 拍照)、`/snapshot` (当前帧 JPEG)
- **拍照历史**: 实时监控页“拍照”调用 `http://renesas.local:8080/photo`，照片实际保存到开发板 `/home/root/camera-server/photos/`；网页拍照历史通过 `show-image.php?action=list&source=photo` 实时读取该目录，因此会与服务器文件夹对应
- **照片查看/管理**: `show-image.php?source=photo&file=photo_YYYYmmdd_HHMMSS.jpg` 从 `/home/root/camera-server/photos/` 读取；`show-image.php?action=delete&source=photo&file=...` 删除拍照历史照片；不带 `source=photo` 时仍用于仪表读数图像 `/home/root/ai/capture/`
- **启停**: PHP `cam-control.php` 通过 PID 文件管理进程
- **关键参数**: V4L2 ioctl 结构体 88 字节(v4l2_buffer)、208 字节(v4l2_format)
- **故障**:
  - 如果画面黑/按钮状态错，检查 `/tmp/capture.pid`
  - 如果 `cam-control.php?action=status` 显示 running，但 `http://127.0.0.1:8080/status` 里 `fps=0`，优先查看 `/tmp/capture.log`
  - 2026-06-10 出现过 USB 摄像头断开重连后 `/dev/video0` 消失、真实视频节点变为 `/dev/video1` 的情况；当时日志为 `FileNotFoundError: /dev/video0`，内核日志有 `uvcvideo: Failed to resubmit video URB (-19)`
  - 临时恢复方式: 将 `/home/root/camera-server/capture.py` 中 `DEVICE` 指到当前真实节点 `/dev/video1` 并通过 `cam-control.php?action=start` 重启
  - 确认真实节点可用:
    ```bash
    ls -l /dev/video*
    v4l2-ctl -d /dev/video1 --all
    wget -qO- http://127.0.0.1:8080/status
    ```

## 雷达系统 (STL-19P)

- **型号**: LDROBOT STL-19P，360° 扫描，12m 量程，电机上电自启
- **协议**: 47 字节定长帧：header(0x54)+verlen(0x2C)+speed(2B)+start_angle(2B)+12points×3B+distance(2B)+intensity(1B)+end_angle(2B)+timestamp(2B)+CRC(1B)
- **波特率**: 230400，CP2102 只接受 vendor 指令（0x40），不接受 CDC-ACM 类指令（0x21）
- **CP2102 初始化**（关键！不同于 RPLIDAR）:
  ```python
  # 波特率编码 = 直接传 230400 作为 4 字节 LE 数据
  dev.ctrl_transfer(0x40, 0x1E, 0x0001, 0x0000, struct.pack("<I", 230400), 1000)
  dev.ctrl_transfer(0x40, 0x07, 0x0303, 0x0000, None, 1000)  # DTR+RTS
  dev.ctrl_transfer(0x40, 0x03, 0x0800, 0x0000, None, 1000)  # 8N1
  dev.ctrl_transfer(0x40, 0x00, 0x0001, 0x0000, None, 1000)  # enable
  ```
- **架构**: `lidar-start.py:8082`，扫描器作为子进程（pyusb 直驱），看门狗自动重启
- **端点**: `/scan` (JSON点云)、`/start`、`/stop`、`/status`、`/stream` (SSE 推送)
- **SSE**: `/stream` 端点每 40ms 检测文件变化并推送，前端 EventSource + requestAnimationFrame 渲染
- **数据流**: 扫描器→/tmp/lidar_scan.json→HTTP /scan + SSE /stream→网页 Canvas
- **开发板缺 cp210x 内核模块**，无法用 `/dev/ttyUSB*`，必须 pyusb 直驱
- **故障排查**: 先跑 `lidar-scan-baud.py` 确认波特率编码=230400，再跑 `lidar-start.py`

## Tag 检测系统 (ArUco)

- **方案**: OpenCV ArUco DICT_4X4_50，tag 贴在仪表下方用于定位 ROI
- **架构**: `tag-detect.py:8085`，从 capture.py HTTP snapshot 取帧，ArUco 检测后返回 tag 坐标+仪表参数
- **端点**: `/locate` (触发检测)、`/detect`、`/preview` (标注图)、`/config` (参数配置)、`/reload` (热重载)、`/quit` (自毁)
- **配置**: `tags_config.json` 映射 tag ID → {name, min, max, divisions}
- **生成**: PC 端 `tag_generate.py add --name ...` 生成打印用的 tag PNG
- **网页流程**: 仪表读数页→PLAY 开摄像头→点"定位"→PHP 启动 tag-detect.py→实时扫描→检测到 tag→克莱因蓝动画扫入 1.5s→显示参数 1.5s→扫出 1.5s→自动填入 min/max/divisions（带绿色[Auto]标记）→PHP 杀进程
- **依赖**: `opencv-python-headless`（开发板用 headless 版避免 libxcb 依赖）

## 网页界面

- **设计**: 克莱因蓝 `#002FA7` + 灰白 `#F1F2F5`，圆角 8px + 微阴影
- **顶栏**: 右侧显示系统时间、在线状态、退出登录、用户头像 `CuteSeek2.png` 与用户名 `Heda`
- **标签页**: 实时监控、设备控制、环境监测、仪表读数；旧“历史记录”“扩展模块”“激光雷达”独立页已删除，激光雷达画面并入实时监控页
- **实时监控页当前布局**: 三列布局；左侧整列为拍照历史，中间上下叠放实时视频流与激光雷达 Canvas，右侧整列为远程终端；远程终端有刷新按钮
- **拍照历史**: 通过 `show-image.php?action=list&source=photo` 显示开发板 `/home/root/camera-server/photos/` 中的 JPG；固定尺寸卡片竖向滚动展示；鼠标悬停到缩略图时右侧弹出“删除”按钮，删除服务器目录中的对应文件；点击卡片通过 `show-image.php?source=photo&file=...` 查看大图
- **设备控制页当前布局**: 页面横向铺满为近似三列：左侧小车运动控制 + 远程终端，中间独立 IK Canvas 模块（居中显示，略宽一点），右侧机械臂调节模块 + 最终发送指令模块；设备控制页跟随主内容区统一边距，内部模块间距 24px；远程终端与实时监控页终端同步输出，日志过多时仅终端窗口内部滚动，标题栏带刷新按钮
- **小车快捷键**: 仅当“设备控制”标签页激活时，`W/A/S/D` 才控制小车；`Q` 为麦轮原地左旋，`E` 为麦轮原地右旋；松开按键自动 `$CAR,STOP`
- **机械臂 IK**: Canvas 独立成小模块并居中，上方为 X 向侧视图，下方为俯视图显示 BASE 旋转角；侧视图保持 1:1，可用 `-`/`+`/`1:1` 按钮缩放，鼠标滚轮用于调整末端角；调节模块包含末端角、BASE/J1/J2/J3 滑动条和输入框，BASE 滑动条以 0 为中心，范围 -180°~180°，Z/Y 锁定为滑动开关并放在滑动条下方；最终发送指令模块在右下角，显示 `$ARM,<BASE>,<J1>,<J2>,<J3>`，上方有更大的“归零/发送”按钮；绘制理论上半圆边界与关节限位采样可达区域
- **仪表读数页当前布局**: 左侧仪表视频模块与右侧“推理终端”底部对齐；第一行高度固定为 700px，视频流区域设置 `overflow:hidden`，防止视频/占位层偶发撑高；右侧依次为当前读数、参数设定、Tag 定位、推理终端，间距为 24px；推理终端为固定尾部模块并内部滚动；底部为读数历史；读数历史“查看”使用与拍照历史相同的弹窗，不再打开新标签页
- **UI 特性**:
  - 仪表读数进度条：克莱因蓝从左扫入，标签字号 48px，步进 2.5s
  - 读数结束前有白色循环加载条
  - 读数字体当前为 56px（当前读数面板，较早期 72px 已压缩）
  - 推理终端固定 160px 高度
  - Tag 面板常驻在推理终端上方；仪表读数视频模块底部与推理终端底部对齐
  - 所有矩形元素 8px 圆角，面板带阴影
- **重要**: 不要用 sed 大量编辑此文件，CSS 花括号容易出错

## 仪表读数(AI)

- **当前方案**: 两阶段 ONNX Runtime 读数，已切换为“表盘 ROI 检测 + 四点几何读数”，不再依赖 ShuffleNet-UNet 分割。
- **第一阶段模型**: `/home/root/ai/meter_roi.onnx`
  - 来源: 旧版 `/home/root/ai/best.onnx`
  - 输入: `[1, 3, 640, 640]`
  - 输出: `[1, 5, 8400]`
  - 作用: 从整张摄像头照片中检测仪表表盘区域，裁剪出 ROI。
- **第二阶段模型**: `/home/root/ai/best_points_320.onnx`
  - 来源: 本地训练得到的 YOLOv8n-320 四点检测模型，导出自 `C:\Users\Heda\Desktop\index\ai\export\best.onnx`
  - 输入: `[1, 3, 320, 320]`
  - 输出: `[1, 8, 2100]`
  - 类别: `0 base`, `1 end`, `2 start`, `3 tip`
  - 作用: 在表盘 ROI 内检测仪表中心、起始刻度、终止刻度、指针尖端。
- **脚本**: `/home/root/ai/meter_reader_onnx.py`
  - 新版脚本支持 `--roi-yolo` 和 `--yolo` 两个模型。
  - `--unet` 参数仍可被接受但已不再使用，仅用于兼容旧命令。
  - 输出仍包含 `Reading: <number>`，因此 `meter-read.php` 的轮询解析逻辑保持兼容。
- **旧版备份**:
  - 开发板旧 AI 文件已备份到 `/home/root/ai/oldversion/20260610_135140/`
  - 包含旧 `best.onnx`、旧 `meter_reader_onnx.py`、`shuffle_unet.onnx`、`shuffle_unet.onnx.data`
  - 本地旧脚本备份: `C:\Users\Heda\Desktop\index\ai\oldversion\meter_reader_onnx.py`
- **当前开发板 AI 根目录关键文件**:
  - `/home/root/ai/meter_roi.onnx`
  - `/home/root/ai/best_points_320.onnx`
  - `/home/root/ai/meter_reader_onnx.py`
  - `/home/root/ai/readings.json`
  - `/home/root/ai/capture/`
  - `/home/root/ai/output/`
- **网页编排**: `/www/matrix-gui-2.0/meter-read.php`
  - 当前调用命令核心为：
    ```bash
    python3 meter_reader_onnx.py \
      --roi-yolo meter_roi.onnx \
      --yolo best_points_320.onnx \
      --conf 0.05 \
      --roi-conf 0.1 \
      --image capture/<photo>.jpg \
      --min <min> --max <max> --divisions <divisions>
    ```
  - `meter-read.php` 已不再传 `--unet shuffle_unet.onnx`
  - `Reading` 正则已改为支持负数/小数: `/Reading:\s+(-?\d+(?:\.\d+)?)/`
- **读数流程**:
  1. 前端点击读数。
  2. `meter-read.php?action=capture` 调用摄像头 `/photo` 拍照。
  3. 照片从 `/home/root/camera-server/photos/` 复制到 `/home/root/ai/capture/`。
  4. 后台启动 `meter_reader_onnx.py`。
  5. `meter_roi.onnx` 在整张照片上检测表盘 ROI。
  6. 脚本将 ROI 扩框并裁成接近正方形的表盘近景。
  7. `best_points_320.onnx` 在 ROI 内检测 `base/end/start/tip`。
  8. 脚本用 `base → start/end/tip` 的角度关系计算读数。
  9. 输出 `Reading: ...`，前端轮询并写入历史。
- **为什么改成两阶段**:
  - 直接在整张摄像头远景图上检测四个小目标时，`end/tip` 太小，YOLOv8n-320 容易漏检。
  - 两阶段先裁出仪表 ROI，让四点模型看到接近训练集的近景表盘，实际测试中四点置信度显著提高。
- **实测样例**:
  - 测试图: `/home/root/camera-server/photos/photo_20260610_141207.jpg`
  - 第一阶段 ROI: `(498, 65, 790, 357)`, conf `0.727`
  - 第二阶段点检测:
    - `base` conf `0.845`
    - `end` conf `0.883`
    - `start` conf `0.792`
    - `tip` conf `0.675`
  - 输出: `Reading: 5.95`，范围 `0~25`，`divisions=50`
- **本地训练/导出结果**:
  - 数据集: `D:\Code\Qiansai\dataset7000`
  - 格式: YOLO Detection
  - 类别: `base`, `end`, `start`, `tip`
  - 训练环境: conda `route-seg`，Python 3.11，PyTorch 2.11 + CUDA 12.8
  - 已训练模型: YOLOv8n-320，训练到第 90 轮，最佳 epoch 87
  - 验证集指标:
    - Precision `0.8637`
    - Recall `0.8415`
    - mAP50 `0.8390`
    - mAP50-95 `0.4606`
  - 主要短板: `tip` 类 Recall 约 `0.51`，直接远景检测时容易漏。
  - 本地导出:
    - `C:\Users\Heda\Desktop\index\ai\export\best.pt`
    - `C:\Users\Heda\Desktop\index\ai\export\best.onnx`
  - 本地报告:
    - `C:\Users\Heda\Desktop\index\ai\onnx_verify\yolov8n_320_eval_export_report.md`
    - `C:\Users\Heda\Desktop\index\ai\onnx_verify\yolov8n_320_eval_export_report.json`
- **性能注意**:
  - 开发板当前网页每次读数都会新起 Python 进程并加载两个 ONNX 模型。
  - 两阶段功能已跑通，但板端实测单次命令约 3 秒级，主要耗时在 Python/ONNX Runtime 初始化与模型加载。
  - 若目标是稳定 `<500ms`，下一步应改成常驻推理服务：启动时加载 `meter_roi.onnx` 和 `best_points_320.onnx`，网页通过 HTTP 请求传图或文件名。
- **手动测试命令**:
  ```bash
  cd /home/root/ai
  python3 meter_reader_onnx.py \
    --roi-yolo meter_roi.onnx \
    --yolo best_points_320.onnx \
    --conf 0.05 \
    --roi-conf 0.1 \
    --image /home/root/camera-server/photos/photo_20260610_141207.jpg \
    --min 0 --max 25 --divisions 50 \
    --json-out output/two_stage_real.json \
    --debug-image output/two_stage_real.jpg
  ```
- **回退旧流程**:
  - 如需回退旧版分割流程，可从 `/home/root/ai/oldversion/20260610_135140/` 还原：
    ```bash
    cp /home/root/ai/oldversion/20260610_135140/best.onnx /home/root/ai/best.onnx
    cp /home/root/ai/oldversion/20260610_135140/meter_reader_onnx.py /home/root/ai/meter_reader_onnx.py
    cp /home/root/ai/oldversion/20260610_135140/shuffle_unet.onnx /home/root/ai/shuffle_unet.onnx
    cp /home/root/ai/oldversion/20260610_135140/shuffle_unet.onnx.data /home/root/ai/shuffle_unet.onnx.data
    ```
  - 同时需把 `meter-read.php` 调回旧参数 `--yolo best.onnx --unet shuffle_unet.onnx`

## 常驻推理服务（2026-06-11 上线，替代一次性脚本调用）

- **问题**: 旧方案每次读数起新 Python 进程加载两个 ONNX 模型，实测 ~3500ms，其中 ~2500ms 花在冷启动
- **方案**: `ai/model_alwaysonline/meter_service.py`，模型常驻内存，HTTP 同步返回
- **端口**: 8086（和摄像头 8080、雷达 8082、串口 8084 并列）
- **端点**: `/health`（存活）、`/status`（统计+平均延迟）、`/read?image=...&min=...&max=...&divisions=...`（推理）
- **架构**: 导入父目录 `meter_reader_onnx.py` 的 `detect_roi`/`detect_points`/`compute_reading` 等函数，外层包 HTTP server
- **内存**: 空闲 ~160MB RSS（Python + ORT + 双模型权重 + arena）
- **延迟**: 纯推理 ~400-1200ms（vs 旧方案 ~3500ms）
- **PHP 编排**: `meter-read.php?action=capture` 改为 HTTP 同步调用 `127.0.0.1:8086/read`，不再 shell_exec + poll
- **启停控制**: `meter-service-control.php?action=start|stop|status`，模式同 `cam-control.php`
- **网页指示**: 仪表读数标题栏右侧绿/红圆点实时显示服务在线状态
- **PID 文件**: `/tmp/meter_service.pid`（自动清理）
- **手动测试**:
  ```bash
  cd /home/root/ai
  python3 model_alwaysonline/meter_service.py --yolo best_points_320.onnx --roi-yolo meter_roi.onnx &
  curl http://127.0.0.1:8086/health
  curl "http://127.0.0.1:8086/read?image=/home/root/camera-server/photos/photo_20260610_141207.jpg&min=0&max=25&divisions=50&conf=0.05&roi_conf=0.1"
  ```
- **回退旧流程**: 部署老的 `meter-read.php` 和 `index.html` 即可恢复 shell_exec+poll 模式

## 常用命令

```bash
# 手动启动摄像头
curl http://127.0.0.1/cam-control.php?action=start

# 手动启动雷达
cd /home/root/lidar && python3 lidar-start.py &

# 手动启动 tag 检测
cd /home/root/tag && python3 tag-detect.py &

# 检查各服务状态
curl http://127.0.0.1:8082/status   # 雷达
curl http://127.0.0.1:8085/locate   # tag检测
curl http://127.0.0.1:8086/status   # 常驻推理
curl http://127.0.0.1/cam-control.php?action=status  # 摄像头

# 常驻推理服务启停
curl "http://127.0.0.1/meter-service-control.php?action=start"
curl "http://127.0.0.1/meter-service-control.php?action=stop"
curl "http://127.0.0.1/meter-service-control.php?action=status"

# 网页访问
http://192.168.2.200/index.html

# 上传文件模板
scp -oHostKeyAlgorithms=+ssh-rsa C:/Users/Heda/Desktop/index/xxx root@192.168.2.200:/path/

# 当前网页相关常用上传
scp -oHostKeyAlgorithms=+ssh-rsa C:/Users/Heda/Desktop/index/index.html C:/Users/Heda/Desktop/index/show-image.php C:/Users/Heda/Desktop/index/meter-read.php C:/Users/Heda/Desktop/index/CuteSeek2.png root@192.168.2.200:/www/matrix-gui-2.0/
```

## 下位机通信（串口桥接已具备，RA8P1 业务解析待完善）

- **物理连接**: RZ/G2L `/dev/ttySC0` ↔ RA8P1 UART，115200bps，TX/RX/GND 三线交叉接
- **波特率确认**: RA8P1 实际波特率 115200（用 `serial-scan.py` 遍历 9600~460800 确认）
- **协议格式**:
  - 小车: `$CAR,FORWARD,50` / `$CAR,STOP` / `$CAR,LEFT,30` / `$CAR,ROTATE_LEFT,40` / `$CAR,ROTATE_RIGHT,40`（麦轮原地旋转）
  - 机械臂: `$ARM,<BASE>,<J1>,<J2>,<J3>`（BASE 为底座 360° 舵机相对角，-180°~180°，0°居中；J1/J2/J3 为三个舵机关节角，逗号分隔，整数度数；旧 `$ARM,<J1>,<J2>,<J3>` 会由 `serial_bridge.py` 自动补 `BASE=0`）
  - 下位机上报: `$STATE,BAT,11.8` 等
- **RA8P1 现有代码**: 已实现 `UART_CMD_Send/Recv`，hal_entry 中回显测试通过。小车有 `Motor.c`（四路 PWM 麦轮控制），机械臂舵机驱动待写
- **上位机**: `serial_bridge.py`（Python + pyserial，HTTP 端口 8084，桥接 fetch → UART；会 URL 解码并校验/规范化 `$ARM,<BASE>,<J1>,<J2>,<J3>`）
  - 端点: `/send?cmd=...`（发串口）、`/read`（读缓存）、`/stream`（SSE 推送）、`/status`
  - PID 文件: `/tmp/serial_bridge.pid`，配 `serial-control.php` 启停管理
- **JS 层**: `carControl()` 已发送 `$CAR,...` 日志/命令格式，`armSend()` 调用 `fetch('http://renesas.local:8084/send?cmd=...')` 发送 `$ARM,<BASE>,<J1>,<J2>,<J3>`；旧 `armControl(action)` 仅保留提示，不再生成旧动作式 `$ARM,ACTION`
- **RA8P1 TX 引脚问题**: RESET 后 TX 线空闲电平不稳定，首次消息完整但后续丢失首字节、末尾挂移位寄存器残留 `00 80 C0 E0 F0 F8 FC FE`。根因是 TX 脚无上拉。需在 FSP Pin Configuration 给 TXD 开 Pull-up，UART 初始化后加 50ms 延时

## 机械臂运动学仿真

- **结构**: 三关节舵机平面臂，连杆 L1=105mm / L2=100mm / L3=90mm，厚度 25mm，关节半径 12.5mm
- **角度约定**: 0°=竖直向上，正值逆时针(CCW)
- **关节限位**: J1 ±90°, J2 ±150°, J3 -150°~90°
- **PC 仿真工具**: `arm-ik-sim.py`（Tkinter GUI，FK+IK，拖动红点控制末端，支持末端方向切换、Z/Y 轴锁定拖动、一键归零、手动输入角度、记录序列 → 输出 `$ARM,...` 指令）
- **网页移植**: 已嵌入 `index.html` 设备控制标签页（Canvas 渲染 + JS IK 引擎），当前已能显示机械臂；Canvas 独立模块分为 X 向侧视图与 BASE 俯视图，调节模块和最终发送指令模块分离；BASE 为底座 360° 舵机相对角，范围 -180°~180°，输出 `$ARM,<BASE>,<J1>,<J2>,<J3>`
- **逆运动学**: 求腕关节位置（末端退 L3 沿指定方向），二连杆 IK 解析解，选最近解防反转；末端方向 0°=朝上 / 90°=水平 / 180°=朝下

## 已知问题

1. **RZ/G2L 缺 cp210x 内核模块**: STL-19P 必须用 pyusb 直驱，初始化序列见上文
2. **雷达画面闪烁**: SSE+Canvas 渲染偶尔仍有闪烁，当前加 2px 容差缓解，待彻底修复
