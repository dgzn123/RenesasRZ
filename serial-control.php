<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$action  = $_GET['action'] ?? 'status';
$script  = '/home/root/serial_bridge.py';
$pidfile = '/tmp/serial_bridge.pid';

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
        echo json_encode(['ok' => true, 'running' => true]);
        exit;
    }
    exec("python3 $script > /tmp/serial_bridge.log 2>&1 & echo $! > $pidfile");
    for ($i = 0; $i < 20; $i++) {
        usleep(200000);
        $fp = @fsockopen('127.0.0.1', 8084, $errno, $errstr, 1);
        if ($fp) { fclose($fp); break; }
    }
    echo json_encode(['ok' => true, 'running' => is_running()]);

} elseif ($action === 'stop') {
    $pid = get_pid();
    if ($pid) {
        exec("kill $pid 2>/dev/null");
        @unlink($pidfile);
    }
    for ($i = 0; $i < 20; $i++) {
        usleep(200000);
        $fp = @fsockopen('127.0.0.1', 8084, $errno, $errstr, 1);
        if (!$fp) break;
        fclose($fp);
    }
    if ($pid && pid_is_alive($pid)) {
        exec("kill -9 $pid 2>/dev/null");
    }
    echo json_encode(['ok' => true, 'running' => false]);

} else {
    $running = is_running();
    $fp = @fsockopen('127.0.0.1', 8084, $errno, $errstr, 1);
    if ($fp) fclose($fp);
    echo json_encode(['running' => $running || ($fp !== false)]);
}
