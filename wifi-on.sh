#!/bin/sh
echo "Switching to WiFi..."
ip link set eth0 down
ip link set wlan0 up
killall wpa_supplicant 2>/dev/null
sleep 1
wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf
sleep 4
udhcpc -i wlan0
echo "WiFi ready:"
ip -4 addr show wlan0 | grep inet
