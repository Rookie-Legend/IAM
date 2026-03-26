#!/bin/sh

# Add the route to the VPN network via the Gateway
# We use || true so the container doesn't crash if the route already exists
ip route add 125.20.0.0/24 via 125.10.0.2 || true

# Start the FastAPI server
# 'exec' makes uvicorn the main process so the container stays alive
exec uvicorn main:app --host 0.0.0.0 --port 8000