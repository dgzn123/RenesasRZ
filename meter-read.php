<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$action       = $_GET['action'] ?? 'status';
$history_file = '/home/root/ai/readings.json';

function get_history() {
    global $history_file;
    if (!file_exists($history_file)) return [];
    $data = json_decode(file_get_contents($history_file), true);
    return is_array($data) ? $data : [];
}

function save_history($h) {
    global $history_file;
    file_put_contents($history_file,
        json_encode($h, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
}

// ── Status ────────────────────────────────────────────────
if ($action === 'status') {
    $history = get_history();
    $last = count($history) > 0 ? $history[count($history) - 1] : null;
    echo json_encode([
        'ok'      => true,
        'last'    => $last,
        'history' => array_reverse($history)
    ]);
    exit;
}

// ── Delete ────────────────────────────────────────────────
if ($action === 'delete') {
    $index = intval($_GET['index'] ?? -1);
    $history = get_history();
    $rev = array_reverse($history);
    if ($index >= 0 && $index < count($rev)) {
        $real = count($history) - 1 - $index;
        array_splice($history, $real, 1);
        save_history($history);
        echo json_encode(['ok' => true, 'history' => array_reverse($history)]);
    } else {
        echo json_encode(['ok' => false, 'error' => 'invalid index']);
    }
    exit;
}

// ── Capture ────────────────────────────────────────────────
if ($action === 'capture') {
    $photo_json = @file_get_contents('http://127.0.0.1:8080/photo');
    if (!$photo_json) {
        echo json_encode(['ok' => false, 'error' => '相机服务未启动']);
        exit;
    }
    $pd = json_decode($photo_json, true);
    if (!$pd || empty($pd['ok'])) {
        echo json_encode(['ok' => false, 'error' => '拍照失败']);
        exit;
    }

    $filename = $pd['file'];
    $src      = '/home/root/camera-server/photos/' . $filename;
    $dst      = '/home/root/ai/capture/' . $filename;
    if (!copy($src, $dst)) {
        echo json_encode(['ok' => false, 'error' => '文件拷贝失败']);
        exit;
    }

    // 拍照完成后释放摄像头，避免推理期间 V4L2/USB 资源持续占用。
    @file_get_contents('http://127.0.0.1/cam-control.php?action=stop');

    $mn   = floatval($_GET['min']  ?? 0);
    $mx   = floatval($_GET['max']  ?? 6);
    $div  = intval($_GET['divisions'] ?? 29);
    $time = $_GET['time'] ?? date('Y-m-d H:i:s');

    $id       = uniqid('meter_');
    $log_file = "/home/root/ai/output/$id.log";

    $cmd  = "cd /home/root/ai && ";
    $cmd .= "python3 meter_reader_onnx.py ";
    $cmd .= "--roi-yolo meter_roi.onnx --yolo best_points_320.onnx ";
    $cmd .= "--conf 0.05 --roi-conf 0.1 ";
    $cmd .= "--image capture/$filename ";
    $cmd .= "--min $mn --max $mx --divisions $div ";
    $cmd .= "> $log_file 2>&1 & echo $!";

    $pid = intval(trim(shell_exec($cmd)));
    if (!$pid) {
        echo json_encode(['ok' => false, 'error' => '启动推理失败']);
        exit;
    }

    file_put_contents("/tmp/$id.json", json_encode([
        'pid'      => $pid,
        'log_file' => $log_file,
        'image'    => $filename,
        'min'      => $mn,
        'max'      => $mx,
        'divs'     => $div,
        'time'     => $time,
        'started'  => time()
    ]));

    echo json_encode(['ok' => true, 'status' => 'running', 'id' => $id]);
    exit;
}

// ── Poll ───────────────────────────────────────────────────
if ($action === 'poll') {
    $id  = $_GET['id'] ?? '';
    $info_file = "/tmp/$id.json";

    if (!file_exists($info_file)) {
        echo json_encode(['ok' => false, 'error' => 'session not found']);
        exit;
    }

    $info     = json_decode(file_get_contents($info_file), true);
    $log_file = $info['log_file'];
    $pid      = $info['pid'];

    $running = file_exists("/proc/$pid");
    $log     = file_exists($log_file) ? file_get_contents($log_file) : '';

    if ($running) {
        echo json_encode(['status' => 'running', 'log' => $log]);
        exit;
    }

    preg_match('/Reading:\s+(-?\d+(?:\.\d+)?)/', $log, $m);
    $reading = $m ? floatval($m[1]) : null;

    $history    = get_history();
    $entry      = [
        'time'    => $info['time'],
        'reading' => $reading,
        'success' => $reading !== null,
        'image'   => $info['image'],
        'min'     => $info['min'],
        'max'     => $info['max'],
        'divs'    => $info['divs']
    ];
    $history[]  = $entry;
    save_history($history);

    $result_file = '/home/root/ai/output/' . pathinfo($info['image'], PATHINFO_FILENAME) . '.json';
    file_put_contents($result_file,
        json_encode($entry, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));

    @unlink($info_file);

    echo json_encode([
        'status'  => 'done',
        'reading' => $reading,
        'time'    => $info['time'],
        'log'     => $log,
        'history' => array_reverse(get_history())
    ]);
    exit;
}

echo json_encode(['ok' => false, 'error' => 'unknown action']);
