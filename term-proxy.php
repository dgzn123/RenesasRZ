<?php
$cwd_file = '/tmp/term_cwd';
$cmd = $_GET['cmd'] ?? '';

// Read current working directory
$cwd = '/home/root';
if (file_exists($cwd_file)) {
    $tmp = trim(file_get_contents($cwd_file));
    if ($tmp && is_dir($tmp)) $cwd = $tmp;
}

// Execute: cd to cwd first, then run cmd, then save new pwd
$script  = 'cd ' . escapeshellarg($cwd) . ' 2>/dev/null; ';
$script .= $cmd . ' 2>&1; ';
$script .= 'echo "::PWD::$(pwd)"';
$output = shell_exec($script);

// Extract and save new PWD
$pwd = $cwd;
if (preg_match('/::PWD::(.+)/', $output, $m)) {
    $pwd = trim($m[1]);
    $output = preg_replace('/::PWD::.+/s', '', $output);
}
file_put_contents($cwd_file, $pwd);

// Build prompt
$home = '/home/root';
$display = ($pwd === $home) ? '~' : $pwd;
$display = str_replace($home, '~', $display);
$parts = explode('/', trim($display, '/'));
$prompt_path = $display === '~' ? '~' : (count($parts) > 2 ? '.../' . implode('/', array_slice($parts, -2)) : $display);

echo json_encode([
    'output' => rtrim($output),
    'pwd'    => $display,
    'prompt' => 'root@renesas:' . $prompt_path . '$ '
]);
