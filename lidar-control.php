<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$action   = $_GET['action'] ?? 'status';
$pidfile  = '/tmp/lidar.pid';
$server   = '/home/root/lidar/lidar-start.py';

function is_alive() {
    global $pidfile;
    if (!file_exists($pidfile)) return false;
    $pid = intval(trim(file_get_contents($pidfile)));
    return $pid > 0 && file_exists("/proc/$pid");
}

if ($action === 'start') {
    if (is_alive()) { echo json_encode(['ok'=>true,'running'=>true]); exit; }
    exec("ps | grep 'lidar' | grep -v grep | awk '{print \$1}' | xargs kill -9 2>/dev/null");
    sleep(1); @unlink($pidfile);
    exec("python3 $server > /tmp/lidar.log 2>&1 & echo \$! > $pidfile");
    for ($i=0;$i<15;$i++) { usleep(300000); $fp=@fsockopen('127.0.0.1',8082,$e,$s,1); if($fp){fclose($fp);break;} }
    echo json_encode(['ok'=>true,'running'=>is_alive()]);
} elseif ($action === 'stop') {
    @file_get_contents('http://127.0.0.1:8082/stop');
    $pid = file_exists($pidfile) ? intval(trim(file_get_contents($pidfile))) : 0;
    if ($pid > 0) exec("kill -9 $pid 2>/dev/null");
    @unlink($pidfile);
    echo json_encode(['ok'=>true,'running'=>false]);
} else {
    echo json_encode(['running'=>is_alive()]);
}
