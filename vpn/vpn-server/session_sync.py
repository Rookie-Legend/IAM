#!/usr/bin/env python3
import socket
import time
import os
import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = os.environ.get("DATABASE_NAME", "iam_db")
MGMT_PORT = 7505
STATUS_LOG_PATH = "/var/log/openvpn/status.log"
_indexes_ready = False

def is_temp_openvpn_username(value):
    return bool(value) and value.startswith("/tmp/openvpn_cc_")

def _parse_datetime_to_epoch(value):
    try:
        return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())
    except Exception:
        return 0

def _session_sort_key(session):
    return (
        1 if session.get("is_active") else 0,
        session.get("last_activity") or session.get("connected_at") or datetime.min,
        str(session.get("_id"))
    )

async def ensure_unique_vpn_sessions(db):
    global _indexes_ready
    if _indexes_ready:
        return

    cursor = db.vpn_sessions.find({})
    sessions = await cursor.to_list(length=10000)
    by_user = {}
    for session in sessions:
        user_id = session.get("user_id")
        if not user_id:
            continue
        by_user.setdefault(user_id, []).append(session)

    for user_sessions in by_user.values():
        if len(user_sessions) <= 1:
            continue
        keep = max(user_sessions, key=_session_sort_key)
        remove_ids = [session["_id"] for session in user_sessions if session["_id"] != keep["_id"]]
        if remove_ids:
            await db.vpn_sessions.delete_many({"_id": {"$in": remove_ids}})

    try:
        await db.vpn_sessions.drop_index("user_id_1")
    except OperationFailure:
        pass
    await db.vpn_sessions.create_index("user_id", unique=True)
    await db.vpn_sessions.create_index("is_active")
    _indexes_ready = True

async def insert_vpn_event(db, event_type, user_id, vpn_ip="", source_ip="", vpn_id="", details="", timestamp=None):
    event_time = timestamp or datetime.utcnow()
    normalized_event_type = (event_type or "").lower()
    normalized_details = details or vpn_id or ""

    recent = await db.vpn_events.find_one(
        {
            "event_type": normalized_event_type,
            "user_id": user_id,
            "vpn_ip": vpn_ip,
            "vpn_id": vpn_id,
            "timestamp": {"$gte": event_time.replace(microsecond=0)}
        }
    )
    if recent:
        return

    await db.vpn_events.insert_one({
        "event_type": normalized_event_type,
        "user_id": user_id,
        "vpn_ip": vpn_ip,
        "source_ip": source_ip,
        "vpn_id": vpn_id,
        "details": normalized_details,
        "timestamp": event_time,
        "event": normalized_event_type.upper(),
        "username": user_id,
        "ip": vpn_ip
    })

def query_openvpn_status():
    clients = {}

    try:
        with open(STATUS_LOG_PATH, "r") as status_file:
            for raw_line in status_file:
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                record_type = parts[0]

                if record_type == "CLIENT_LIST" and len(parts) >= 9:
                    common_name = parts[1].strip()
                    if not common_name:
                        continue
                    clients.setdefault(common_name, {})
                    clients[common_name]["username"] = common_name
                    clients[common_name]["source_ip"] = parts[2].strip()
                    clients[common_name]["vpn_ip"] = parts[3].strip()
                    clients[common_name]["connected_since"] = (
                        int(parts[8].strip()) if parts[8].strip().isdigit() else _parse_datetime_to_epoch(parts[7].strip())
                    )
                elif record_type == "ROUTING_TABLE" and len(parts) >= 4:
                    vpn_ip = parts[1].strip()
                    common_name = parts[2].strip()
                    source_ip = parts[3].strip()
                    if not common_name:
                        continue
                    clients.setdefault(common_name, {})
                    clients[common_name]["username"] = common_name
                    clients[common_name]["vpn_ip"] = vpn_ip
                    if source_ip:
                        clients[common_name]["source_ip"] = source_ip
    except Exception:
        pass

    return [
        {
            "username": username,
            "source_ip": data.get("source_ip", ""),
            "vpn_ip": data.get("vpn_ip", ""),
            "connected_since": data.get("connected_since", 0),
        }
        for username, data in clients.items()
        if data.get("username")
    ]

async def sync_sessions():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    await ensure_unique_vpn_sessions(db)

    active_sessions = query_openvpn_status()
    active_usernames = {c['username'] for c in active_sessions if c.get('username')}
    active_ips = {c['vpn_ip'] for c in active_sessions if c.get('vpn_ip')}

    stale_sessions_cursor = db.vpn_sessions.find({"is_active": True})
    stale_sessions = await stale_sessions_cursor.to_list(length=1000)

    for session in stale_sessions:
        if (
            session['user_id'] not in active_usernames and
            session.get('assigned_ip') not in active_ips and
            session.get('vpn_ip') not in active_ips
        ):
            await db.vpn_sessions.update_one(
                {"_id": session['_id']},
                {"$set": {
                    "is_active": False,
                    "connected_at": None,
                    "last_activity": datetime.utcnow()
                }}
            )

            await db.access_states.update_one(
                {"user_id": session['user_id']},
                {"$set": {
                    "connected": False,
                    "connected_vpn": None,
                    "connected_ip": None,
                    "connected_at": None,
                    "last_disconnected_at": datetime.utcnow()
                }}
            )

            await db.users.update_one(
                {"user_id": session["user_id"], "disabled": {"$ne": True}},
                {"$set": {"status": "inactive"}}
            )

            await insert_vpn_event(
                db,
                "disconnect",
                session["user_id"],
                vpn_ip=session.get("vpn_ip") or session.get("assigned_ip", ""),
                source_ip=session.get("source_ip", ""),
                vpn_id=session.get("vpn_id", ""),
                details=f"Disconnected from {session.get('vpn_id', '')}".strip()
            )

    for client_data in active_sessions:
        username = client_data.get('username', '')
        existing = None

        if username and not is_temp_openvpn_username(username):
            existing = await db.vpn_sessions.find_one({
                "user_id": username
            })

        if not existing and client_data.get('vpn_ip'):
            existing = await db.vpn_sessions.find_one({
                "$or": [
                    {"assigned_ip": client_data['vpn_ip'], "is_active": True},
                    {"vpn_ip": client_data['vpn_ip'], "is_active": True}
                ]
            })

        resolved_username = existing["user_id"] if existing else username
        if not resolved_username or is_temp_openvpn_username(resolved_username):
            continue

        vpn_id = existing.get("vpn_id", "") if existing else ""

        was_inactive = not existing or not existing.get("is_active")

        if existing:
            await db.vpn_sessions.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "user_id": resolved_username,
                    "is_active": True,
                    "assigned_ip": client_data['vpn_ip'],
                    "vpn_ip": client_data['vpn_ip'],
                    "source_ip": client_data['source_ip'],
                    "connected_at": existing.get("connected_at") or datetime.utcnow(),
                    "last_activity": datetime.utcnow()
                }}
            )
        else:
            await db.vpn_sessions.update_one(
                {"user_id": resolved_username},
                {
                    "$set": {
                        "is_active": True,
                        "vpn_ip": client_data['vpn_ip'],
                        "source_ip": client_data['source_ip'],
                        "assigned_ip": client_data['vpn_ip'],
                        "vpn_id": vpn_id,
                        "connected_at": datetime.utcnow(),
                        "last_activity": datetime.utcnow()
                    },
                    "$setOnInsert": {"user_id": resolved_username}
                },
                upsert=True
            )

        await db.access_states.update_one(
            {"user_id": resolved_username},
            {"$set": {
                "connected": True,
                "connected_vpn": vpn_id,
                "connected_ip": client_data['vpn_ip'],
                "connected_at": datetime.utcnow()
            }},
            upsert=True
        )

        await db.users.update_one(
            {"user_id": resolved_username, "disabled": {"$ne": True}},
            {"$set": {"status": "active"}}
        )

        if was_inactive:
            await insert_vpn_event(
                db,
                "connect",
                resolved_username,
                vpn_ip=client_data["vpn_ip"],
                source_ip=client_data["source_ip"],
                vpn_id=vpn_id,
                details=f"Connected to {vpn_id}" if vpn_id else "Connected"
            )

async def main():
    while True:
        try:
            await sync_sessions()
        except Exception:
            pass
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
