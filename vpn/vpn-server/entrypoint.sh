#!/bin/bash

SERVER_IP=${VPN_SERVER_IP:-10.35.156.201}
EASYRSA_DIR="/etc/openvpn/easy-rsa"
export TZ=Asia/Kolkata

mkdir -p /etc/openvpn/easy-rsa
mkdir -p /etc/openvpn/client-configs
mkdir -p /etc/openvpn/ccd

if [ ! -d "$EASYRSA_DIR/pki" ]; then
    cp -r /usr/share/easy-rsa/* $EASYRSA_DIR/
fi

echo "Generating client.ovpn template with server IP: $SERVER_IP"
sed "s/YOUR_SERVER_IP/$SERVER_IP/g" /app/client.ovpn.template > /etc/openvpn/client.ovpn

echo "Copying server.conf to /etc/openvpn/"
cp /app/server.conf /etc/openvpn/server.conf

echo "Setting up iptables for department pools..."

iptables -A FORWARD -i tun0 -d 125.20.0.0/16 -j ACCEPT

iptables -A FORWARD -i eth0 -o tun0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i tun0 -j DROP

echo "Starting OpenVPN..."
openvpn --config /etc/openvpn/server.conf --daemon

sleep 2

echo "Starting session sync background task..."
python /app/session_sync.py &

echo "Starting FastAPI Management Server..."
exec uvicorn main:app --host 0.0.0.0 --port 4000