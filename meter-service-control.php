<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$action  = $_GET['action'] ?? 'status';
$pidfile = '/tmp/meter_service.pid';
$logfile = '/tmp/meter_service.log';
$port    = 8086;
$script  = '/home/root/ai/model_alwaysonline/meter_service.py';

function pid_is_alive($pid) {
    if (!$pid) return false;
    $out = shell_exec("ps | awk '{print $1}' | grep -x $pid");
    return trim($out) !== '';
}

function get_pid() {
    global $pidfile;
    $p = @file_get_contents($pidfile);
    return $p ? intval(trim($p)) : 0;
}

function is_running() {
    return pid_is_alive(get_pid());
}

if ($action === 'start') {
    if (is_running()) {
        echo json_encode(['ok' => true, 'running' => true, 'pid' => get_pid()]);
        exit;
    }
    $cmd = "cd /home/root/ai && python3 $script "
         . "--yolo best_points_320.onnx --roi-yolo meter_roi.onnx "
         . "> $logfile 2>&1 & echo $! > $pidfile";
    exec($cmd);
    // 等待端口 8086 打开
    for ($i = 0; $i < 30; $i++) {
        usleep(200000);
        $fp = @fsockopen('127.0.0.1', $port, $errno, $errstr, 1);
        if ($fp) { fclose($fp); break; }
    }
    echo json_encode(['ok' => true, 'running' => is_running(), 'pid' => get_pid()]);

} elseif ($action === 'stop') {
    $pid = get_pid();
    if ($pid) {
        exec("kill $pid 2>/dev/null");
        @unlink($pidfile);
    }
    for ($i = 0; $i < 25; $i++) {
        usleep(200000);
        $fp = @fsockopen('127.0.0.1', $port, $errno, $errstr, 1);
        if (!$fp) break;
        fclose($fp);
    }
    if ($pid && pid_is_alive($pid)) {
        exec("kill -9 $pid 2>/dev/null");
    }
    echo json_encode(['ok' => true, 'running' => false]);

} else { // status
    $running = is_running();
    $fp = @fsockopen('127.0.0.1', $port, $errno, $errstr, 1);
    if ($fp) fclose($fp);
    $port_open = $fp !== false;
    $pid = get_pid();
    // 如果端口开着但 PID 文件失效，试着重连
    if ($port_open && !$running && $pid) {
        $running = true;
    }
    echo json_encode([
        'running'    => $running || $port_open,
        'port_open'  => $port_open,
        'pid'        => $pid,
        'status_url' => "http://127.0.0.1:$port/status"
    ]);
}
