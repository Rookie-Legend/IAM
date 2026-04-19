#!/bin/bash
username="${common_name:-${username:-unknown}}"
vpn_ip="${ifconfig_pool_remote_ip:-${2:-unknown}}"
source_ip="${trusted_ip:-unknown}"
payload="{\"username\": \"$username\", \"vpn_ip\": \"$vpn_ip\", \"source_ip\": \"$source_ip\"}"

echo "OpenVPN disconnect: username=$username vpn_ip=$vpn_ip source_ip=$source_ip"

response_file="$(mktemp)"
http_status="$(curl -s -o "$response_file" -w "%{http_code}" -X POST "http://localhost:4000/release-ip" \
  -H "Content-Type: application/json" \
  -d "$payload")"
curl_exit=$?
response_body="$(cat "$response_file")"
rm -f "$response_file"

if [ "$curl_exit" -ne 0 ]; then
  echo "OpenVPN disconnect callback failed: curl_exit=$curl_exit username=$username vpn_ip=$vpn_ip"
  exit 0
fi

echo "OpenVPN disconnect callback: status=$http_status response=$response_body"
