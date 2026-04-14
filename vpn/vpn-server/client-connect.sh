#!/bin/bash
username="${common_name:-${username:-unknown}}"
vpn_ip="${ifconfig_pool_remote_ip:-${2:-unknown}}"
source_ip="${trusted_ip:-unknown}"

curl -s -X POST "http://localhost:4000/connect-event" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$username\", \"vpn_ip\": \"$vpn_ip\", \"source_ip\": \"$source_ip\"}" || true
