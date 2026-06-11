#!/bin/sh
echo "Switching to Wired..."
ip addr flush dev wlan0 2>/dev/null
killall wpa_supplicant 2>/dev/null
ip link set wlan0 down
ip link set eth0 up
sleep 2
echo "Wired ready: 192.168.2.200"
