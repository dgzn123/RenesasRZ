<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$action  = $_GET['action'] ?? 'status';
$script  = '/home/root/tag/tag-detect.py';
$pidfile = '/tmp/tag.pid';

function pid_alive($pid) {
    if (!$pid) return false;
    $out = shell_exec("ps | awk '{print $1}' | grep -x $pid");
    return trim($out) !== '';
}

function get_pid() {
    global $pidfile;
    $p = @file_get_contents($pidfile);
    return $p ? intval(trim($p)) : 0;
}

if ($action === 'start') {
    $pid = get_pid();
    if ($pid && pid_alive($pid)) {
        echo json_encode(['ok' => true, 'running' => true]);
        exit;
    }
    exec("python3 $script > /tmp/tag.log 2>&1 & echo $! > $pidfile");
    for ($i = 0; $i < 20; $i++) {
        usleep(200000);
        $fp = @fsockopen('127.0.0.1', 8085, $errno, $errstr, 1);
        if ($fp) { fclose($fp); break; }
    }
    echo json_encode(['ok' => true, 'running' => pid_alive(get_pid())]);

} elseif ($action === 'stop') {
    $pid = get_pid();
    if ($pid) {
        exec("kill $pid 2>/dev/null");
        @unlink($pidfile);
    }
    echo json_encode(['ok' => true, 'running' => false]);

} else {
    $running = $pid && pid_alive(get_pid());
    echo json_encode(['running' => $running]);
}
