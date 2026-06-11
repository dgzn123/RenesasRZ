<?php
$action = $_GET['action'] ?? 'view';
$file = $_GET['file'] ?? '';
$source = $_GET['source'] ?? 'ai';
$base = ($source === 'photo') ? '/home/root/camera-server/photos/' : '/home/root/ai/capture/';

if ($action === 'list') {
    header('Content-Type: application/json');
    header('Access-Control-Allow-Origin: *');
    $files = [];
    foreach (glob($base . '*.jpg') ?: [] as $path) {
        $files[] = [
            'file' => basename($path),
            'size' => filesize($path),
            'mtime' => filemtime($path)
        ];
    }
    usort($files, function($a, $b) { return $b['mtime'] <=> $a['mtime']; });
    echo json_encode(['ok' => true, 'files' => $files], JSON_UNESCAPED_UNICODE);
    exit;
}

if ($action === 'delete') {
    header('Content-Type: application/json');
    header('Access-Control-Allow-Origin: *');
    if ($source !== 'photo') {
        echo json_encode(['ok' => false, 'error' => 'delete only supports photo source']);
        exit;
    }
    $path = $base . basename($file);
    if (!is_file($path)) {
        echo json_encode(['ok' => false, 'error' => 'file not found']);
        exit;
    }
    echo json_encode(['ok' => @unlink($path)]);
    exit;
}

$path = $base . basename($file);
if (!file_exists($path)) {
    http_response_code(404);
    header('Content-Type: text/plain');
    echo 'File not found';
    exit;
}
header('Content-Type: image/jpeg');
header('Content-Length: ' . filesize($path));
readfile($path);
