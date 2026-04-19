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

echo "Configuring VPN DNS for private GitLab hostname..."
grep -q "gitlab.eng.vpn" /etc/hosts || echo "172.30.0.50 gitlab.eng.vpn" >> /etc/hosts

echo "Setting up iptables for department pools..."

# --- VPN internal traffic (client-to-client)
iptables -A FORWARD -i tun0 -o tun0 -j ACCEPT

# --- Allow VPN clients to query dnsmasq on the VPN server
iptables -A INPUT -i tun0 -p udp --dport 53 -j ACCEPT
iptables -A INPUT -i tun0 -p tcp --dport 53 -j ACCEPT

# --- Engineering VPN-only access to GitLab
iptables -A FORWARD -s 100.64.0.0/20 -d 172.30.0.50 -p tcp -m multiport --dports 22,80,443 -j ACCEPT
iptables -A FORWARD -s 100.64.0.0/16 -d 172.30.0.50 -j DROP

# --- Allow VPN clients to access everything (backend, internet)
iptables -A FORWARD -i tun0 -j ACCEPT

iptables -t nat -A POSTROUTING -s 100.64.0.0/16 -o eth0 -j MASQUERADE

iptables -A FORWARD -i eth0 -o tun0 -m state --state RELATED,ESTABLISHED -j ACCEPT

echo "Starting OpenVPN..."
openvpn --config /etc/openvpn/server.conf --daemon

sleep 2

echo "Starting dnsmasq for VPN clients..."
dnsmasq --no-daemon --listen-address=100.64.0.1 --bind-interfaces --except-interface=lo &

echo "Starting session sync background task..."
python /app/session_sync.py &

echo "Starting FastAPI Management Server..."
exec uvicorn main:app --host 0.0.0.0 --port 4000
