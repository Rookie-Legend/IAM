#!/bin/bash
username="${username:-${1:-unknown}}"
vpn_ip="${ifconfig_pool_remote_ip:-${2:-unknown}}"
source_ip="${trusted_ip:-unknown}"

curl -s -X POST "http://localhost:4000/connect-event" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$username\", \"vpn_ip\": \"$vpn_ip\", \"source_ip\": \"$source_ip\"}" || true

echo "$(date '+%Y-%m-%dT%H:%M:%S%z') CONNECT $username $vpn_ip $source_ip" >> /etc/openvpn/connect.log