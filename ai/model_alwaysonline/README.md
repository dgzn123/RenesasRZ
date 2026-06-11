# meter\_service.py — 常驻仪表读数推理服务

两阶段 ONNX 模型常驻内存，HTTP 接口响应推理请求，消除一键式脚本每次 ~2.5s 的冷启动开销。

## 快速开始

```bash
cd /home/root/ai

# 启动服务（默认监听 127.0.0.1:8086）
python3 model_alwaysonline/meter_service.py \
    --yolo best_points_320.onnx \
    --roi-yolo meter_roi.onnx &

# 检查是否就绪
curl http://127.0.0.1:8086/health
```

## 命令行参数

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--yolo` | 是 | — | 四点检测 ONNX 模型路径 |
| `--roi-yolo` | 否 | — | ROI 检测 ONNX 模型路径，不传则在全图上直接做四点检测 |
| `--port` | 否 | `8086` | HTTP 监听端口 |
| `--host` | 否 | `127.0.0.1` | 绑定地址 |
| `--threads` | 否 | `2` | ONNX Runtime 推理线程数 |
| `--profile` | 否 | — | 仪表参数配置文件（JSON），可在请求中按名称引用 |

## API 端点

### `GET /health`

存活检查。

```json
{"ok": true, "uptime_s": 1234.5}
```

### `GET /status`

运行状态，包含模型路径、请求计数、平均耗时。

```json
{
  "ok": true,
  "uptime_s": 3600.1,
  "roi_model": "../meter_roi.onnx",
  "point_model": "../best_points_320.onnx",
  "requests": 15,
  "total_inference_ms": 8200.0,
  "avg_inference_ms": 546.7,
  "profiles_loaded": ["default", "meter_a"]
}
```

### `GET /read`

执行一次两阶段推理。

**必填参数：**

| 参数 | 说明 |
|------|------|
| `image` | 待读数图片路径（开发板上绝对路径或相对路径） |
| `min` | 仪表量程下限（与 `max`/`divisions` 成组使用） |
| `max` | 仪表量程上限 |
| `divisions` | 量程刻度格数 |

**可选参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `conf` | `0.25` | 四点检测置信度阈值 |
| `roi_conf` | `0.25` | ROI 检测置信度阈值 |
| `roi_expand` | `0.2` | ROI 框扩展比例（正方形化） |
| `iou` | `0.45` | NMS IoU 阈值 |
| `offset` | `0` | 读数修正偏移量 |
| `direction` | `auto` | 表盘扫角方向：`auto` / `cw` / `ccw` |
| `no_clamp` | 无 | 出现此参数时不对 tip 比例做 [0,1] 截断 |
| `debug_image` | 无 | 输出标注图的保存路径 |
| `profile` | 无 | 仪表参数 JSON 文件路径 |
| `profile_name` | `default` | 引用 profile 中的哪个配置 |

**成功响应 (200)：**

```json
{
  "success": true,
  "reading": 5.95,
  "min": 0.0,
  "max": 25.0,
  "divisions": 50,
  "elapsed_ms": 487.3,
  "points": {
    "base": {"center": [149.5, 161.2], "confidence": 0.845},
    "end":   {"center": [215.7, 204.2], "confidence": 0.883},
    "start": {"center": [102.7, 229.7], "confidence": 0.792},
    "tip":   {"center": [70.7, 149.9],  "confidence": 0.675}
  },
  "geometry": {
    "reading": 5.947,
    "fraction": 0.238,
    "direction": "cw",
    "angles_clockwise_deg": {
      "start": 124.3, "end": 33.0, "tip": 188.2,
      "sweep": 268.7, "tip_delta": 63.9
    }
  }
}
```

**失败响应 (422)：**

```json
{
  "success": false,
  "error": "Missing required point(s): tip",
  "present": {"base": 0.845, "end": 0.883, "start": 0.792},
  "detections": [...]
}
```

**使用 profile 的请求示例：**

```
GET /read?image=/home/root/ai/capture/photo_001.jpg&profile=meter_profiles.json&profile_name=gauge_a
```

**手动测试命令：**

```bash
curl -s "http://127.0.0.1:8086/read?image=/home/root/camera-server/photos/photo_20260610_141207.jpg&min=0&max=25&divisions=50" | python3 -m json.tool

# 带调试标注图
curl -s "http://127.0.0.1:8086/read?image=/home/root/camera-server/photos/photo_20260610_141207.jpg&min=0&max=25&divisions=50&debug_image=/tmp/debug.jpg"
```

## 接入 meter-read.php

当前 `meter-read.php` 每次读数都启动新 Python 进程。改为调用本服务后，`action=capture` 环节的改动：

```php
// 旧方式：启动一次性进程
// $cmd = "cd /home/root/ai && python3 meter_reader_onnx.py ... > log 2>&1 & echo $!";

// 新方式：直接 HTTP 调用常驻服务
$url = "http://127.0.0.1:8086/read?"
     . "image=/home/root/ai/capture/$filename"
     . "&min=$mn&max=$mx&divisions=$div"
     . "&conf=0.05&roi_conf=0.1";
$result = json_decode(file_get_contents($url), true);
if ($result && $result['success']) {
    $reading = $result['reading'];
    // 直接写入历史，无需 poll 循环
}
```

改动要点：
- **不再需要后台进程**：去掉 `shell_exec` + PID 管理 + `/tmp/*.json` session 文件
- **不再需要 poll**：`/read` 同步返回结果，前端无需轮询
- **响应时间从 ~3.5s 降到 ~500ms**：前端体验从进度条等待变为几乎即时返回

## 内存与性能

### 内存占用（估算）

| 组件 | RSS |
|------|-----|
| Python + cv2 + numpy | ~55 MB |
| ONNX Runtime 运行时 | ~15 MB |
| 两个模型权重 | ~30 MB |
| ORT Arena（中间张量池） | ~60 MB |
| **空闲时总计** | **~160 MB** |
| 推理峰值（临时张量） | **~180 MB** |

配置策略：
- `graph_optimization_level = BASIC`（而非 EXTENDED/ALL），减少图优化期间的内存分配
- `inter_op_num_threads = 1`，避免线程池冗余
- `intra_op_num_threads = 2`，匹配 Cortex-A55 双核
- Arena 保持启用以保证推理速度，但图优化级别降低减少了常驻内存

如需进一步压缩内存，可改为 `enable_cpu_mem_arena = False`（以牺牲 10-20% 推理速度为代价，arena 从 ~60MB 降到 ~20MB）。

### 推理耗时

| 阶段 | 预估耗时（Cortex-A55） |
|------|----------------------|
| 图像读取 + 预处理 | 30-80 ms |
| ROI 推理 (640×640) | 200-600 ms |
| 裁剪 + 四点预处理 | 15-30 ms |
| 四点推理 (320×320) | 150-450 ms |
| 后处理 + 几何计算 | 10-20 ms |
| **端到端** | **~400-1200 ms** |

实际耗时取决于图像分辨率、检测目标数量、CPU 温控降频等因素。可通过 `/status` 端点查看 `avg_inference_ms` 监控长期趋势。

### CPU

- 空闲：~0%（阻塞在 HTTP accept）
- 推理中：双核 A55 满载约 400-1200ms
- 请求间隔较大时，平均 CPU 占用可忽略

## 进程管理

建议配一个 PHP 控制脚本（参照 `cam-control.php` / `lidar-control.php` 的模式）：

```php
<?php
// meter-service-control.php
$pid_file = '/tmp/meter_service.pid';
$action = $_GET['action'] ?? 'status';

if ($action === 'start') {
    if (file_exists($pid_file) && posix_getsid(file_get_contents($pid_file))) {
        echo json_encode(['ok' => true, 'status' => 'already running']);
        exit;
    }
    $cmd = "cd /home/root/ai && python3 model_alwaysonline/meter_service.py "
         . "--yolo best_points_320.onnx --roi-yolo meter_roi.onnx "
         . ">> /tmp/meter_service.log 2>&1 & echo $!";
    $pid = trim(shell_exec($cmd));
    file_put_contents($pid_file, $pid);
    echo json_encode(['ok' => true, 'status' => 'started', 'pid' => $pid]);
}
elseif ($action === 'stop') {
    $pid = file_exists($pid_file) ? file_get_contents($pid_file) : 0;
    if ($pid) posix_kill($pid, SIGTERM);
    unlink($pid_file);
    echo json_encode(['ok' => true, 'status' => 'stopped']);
}
else {
    $running = file_exists($pid_file) && posix_getsid(file_get_contents($pid_file));
    echo json_encode(['ok' => true, 'running' => $running]);
}
```

## 文件说明

```
model_alwaysonline/
├── meter_service.py   # 常驻推理服务主程序
└── README.md          # 本文件
```

核心推理函数（`detect_roi`、`detect_points`、`compute_reading` 等）通过 `sys.path` 从父目录的 `meter_reader_onnx.py` 导入，不重复实现，保持单一来源。
