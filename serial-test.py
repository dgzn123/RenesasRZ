#!/usr/bin/env python3
"""串口通信测试 — RZ/G2L ↔ RA8P1 双向通信。按 RESET 看接收，输入命令按回车发送。"""
import serial, threading, time

PORT = '/dev/ttySC0'
BAUD = 115200

def reader():
    """后台线程：read() 累积字节，150ms 无新数据视为一条消息结束"""
    buf = bytearray()
    last = time.time()
    while True:
        chunk = ser.read(1024)
        now = time.time()
        if chunk:
            buf.extend(chunk)
            last = now
        elif buf and (now - last) > 0.15:
            # 空闲 150ms，消息结束
            hex_str = buf.hex(' ').upper()
            txt = buf.decode(errors='replace').strip()
            # 用 print 一次性输出，避免多线程打印穿插
            lines = [f'[RX] {hex_str}']
            if txt:
                lines.append(f'     {txt}')
            print('\n'.join(lines), flush=True)
            buf.clear()
        else:
            time.sleep(0.01)

print(f'打开 {PORT} @ {BAUD}bps...')
ser = serial.Serial(PORT, BAUD, timeout=0.05)
ser.reset_input_buffer()
print('已就绪。按 RA8P1 RESET 看接收，或输入命令发送。q 退出\n')

threading.Thread(target=reader, daemon=True).start()

try:
    while True:
        line = input('>>> ')
        if not line:
            continue
        if line.lower() in ('q', 'quit', 'exit'):
            break
        ser.write((line + '\n').encode())
        print(f'[TX] {line}')
except KeyboardInterrupt:
    pass
finally:
    ser.close()
    print('串口已关闭')
