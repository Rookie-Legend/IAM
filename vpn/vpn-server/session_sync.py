#!/usr/bin/env python3
import socket
import time
import os
import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = os.environ.get("DATABASE_NAME", "iam_db")
MGMT_PORT = 7505

def query_openvpn_status():
    clients = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', MGMT_PORT))
        sock.sendall(b"status 2\n")
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk or b"END" in data:
                break
            data += chunk
        sock.sendall(b"quit\n")
        sock.close()

        for line in data.decode('utf-8', errors='ignore').split('\n'):
            if line.startswith('CLIENT_LIST'):
                parts = line.split(',')
                if len(parts) >= 6:
                    clients.append({
                        'username': parts[1],
                        'source_ip': parts[2],
                        'vpn_ip': parts[3],
                        'connected_since': int(parts[5])
                    })
    except Exception as e:
        print(f"Error querying OpenVPN: {e}")
    return clients

async def sync_sessions():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    active_sessions = query_openvpn_status()
    active_usernames = {c['username'] for c in active_sessions}

    stale_sessions_cursor = db.vpn_sessions.find({"is_active": True})
    stale_sessions = await stale_sessions_cursor.to_list(length=1000)
    
    for session in stale_sessions:
        if session['user_id'] not in active_usernames:
            await db.vpn_sessions.update_one(
                {"_id": session['_id']},
                {"$set": {"is_active": False, "last_activity": datetime.utcnow()}}
            )

            await db.access_states.update_one(
                {"user_id": session['user_id']},
                {"$set": {
                    "connected": False,
                    "connected_vpn": None,
                    "connected_ip": None,
                    "last_disconnected_at": datetime.utcnow()
                }}
            )

            await db.vpn_audit_logs.insert_one({
                "event_type": "disconnect_force",
                "user_id": session['user_id'],
                "vpn_id": session['vpn_id'],
                "vpn_ip": session['assigned_ip'],
                "source_ip": session.get('source_ip', ''),
                "timestamp": datetime.utcnow(),
                "details": "Detected stale session via OpenVPN polling"
            })
            print(f"Force disconnected stale session for {session['user_id']}")

    for client_data in active_sessions:
        existing = await db.vpn_sessions.find_one({"user_id": client_data['username'], "is_active": True})
        if not existing:
            await db.vpn_audit_logs.insert_one({
                "event_type": "connect",
                "user_id": client_data['username'],
                "vpn_id": "",
                "vpn_ip": client_data['vpn_ip'],
                "source_ip": client_data.get('source_ip', ''),
                "timestamp": datetime.utcnow(),
                "details": "Detected via OpenVPN polling (fallback)"
            })

        await db.vpn_sessions.update_one(
            {"user_id": client_data['username'], "is_active": True},
            {"$set": {
                "vpn_ip": client_data['vpn_ip'],
                "source_ip": client_data['source_ip'],
                "last_activity": datetime.utcnow()
            }},
            upsert=True
        )

async def main():
    while True:
        try:
            await sync_sessions()
        except Exception as e:
            print(f"Sync error: {e}")
        await asyncio.sleep(30)

if __name__ == "__main__":
    print("Session sync started")
    asyncio.run(main())