#!/usr/bin/env python3
"""波特率扫描 — 每个波特率监听 5 秒，按 RESET 看哪个不乱码。"""
import serial, time

PORT = '/dev/ttySC0'
RATES = [9600, 14400, 19200, 38400, 56000, 57600, 112500, 115200, 128000, 230400, 256000, 460800]

for rate in RATES:
    try:
        ser = serial.Serial(PORT, rate, timeout=0.3)
        print(f'\n===== {rate} bps ===== (按 RESET，5秒后自动切换)')
        deadline = time.time() + 5
        while time.time() < deadline:
            data = ser.read(ser.in_waiting or 1)
            if data:
                hex_s = data.hex(' ').upper()
                txt = data.decode(errors='replace').strip()
                print(f'  [{rate}] HEX: {hex_s}')
                if txt:
                    print(f'  [{rate}] TXT: {txt}')
        ser.close()
    except Exception as e:
        print(f'  [{rate}] 打不开: {e}')

print('\n扫描完成')
