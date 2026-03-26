#!/bin/bash

# 1. Apply Firewall Rules (The Sandbox)
# iptables -t nat -A POSTROUTING -s 125.20.0.0/24 -o eth0 -j MASQUERADE
iptables -A FORWARD -i tun0 -d 125.10.0.0/24 -j ACCEPT
# iptables -A FORWARD -i tun0 -s 125.20.0.0/24 -d 125.10.0.0/24 -j ACCEPT
iptables -A FORWARD -i eth0 -o tun0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i tun0 -j DROP

# 2. Start OpenVPN as a background daemon
echo "Starting OpenVPN..."
openvpn --config /etc/openvpn/server.conf --daemon

# 3. Wait a moment for the 'tun0' interface to initialize
sleep 2

# 4. Start FastAPI as the FOREGROUND process (the heart of the container)
echo "Starting FastAPI Management Server..."
exec uvicorn main:app --host 0.0.0.0 --port 4000
