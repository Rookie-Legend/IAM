from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
import subprocess, os, socket, uuid
from motor.motor_asyncio import AsyncIOMotorClient

app = FastAPI()

EASYRSA_DIR = "/etc/openvpn/easy-rsa"
CONFIG_OUT_DIR = "/etc/openvpn/client-configs"
CCD_DIR = "/etc/openvpn/ccd"
TEMPLATE_FILE = "/etc/openvpn/client.ovpn"
MGMT_PORT = 7505
STATUS_LOG_PATH = "/var/log/openvpn/status.log"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = os.environ.get("DATABASE_NAME", "iam_db")

_mongo_client = None

def get_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(MONGO_URL)
    return _mongo_client[DB_NAME]

def run_cmd(cmd):
    subprocess.run(cmd, cwd=EASYRSA_DIR, shell=True, check=True, env={**os.environ, "EASYRSA_BATCH": "1"})

def is_temp_openvpn_username(value):
    return bool(value) and value.startswith("/tmp/openvpn_cc_")

def ip_to_int(ip):
    parts = ip.split('.')
    return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])

def int_to_ip(n):
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"

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

async def get_pool_from_db(db, vpn_id):
    pool = await db.vpn_ip_pools.find_one({"pool_id": vpn_id, "is_active": True})
    if not pool:
        raise HTTPException(status_code=404, detail=f"Pool {vpn_id} not found")
    return pool

async def allocate_ip(db, user_id, vpn_id):
    pool = await get_pool_from_db(db, vpn_id)
    
    start_int = ip_to_int(pool["start_ip"])
    end_int = ip_to_int(pool["end_ip"])
    range_size = end_int - start_int + 1
    
    taken = set(pool.get("assigned_ips", []))
    
    for offset in range(range_size):
        ip_int = start_int + offset
        ip = int_to_ip(ip_int)
        if ip not in taken:
            await db.vpn_ip_pools.update_one(
                {"pool_id": vpn_id},
                {"$addToSet": {"assigned_ips": ip}}
            )
            os.makedirs(CCD_DIR, exist_ok=True)
            with open(f"{CCD_DIR}/{user_id}", "w") as f:
                f.write(f"ifconfig-push {ip} 255.255.255.0\n")
            return ip, pool["name"]
    
    raise HTTPException(status_code=503, detail="No IPs available in pool")

async def release_ip_by_username(db, username):
    session = await db.vpn_sessions.find_one({"user_id": username, "is_active": True})
    if not session:
        session = await db.vpn_sessions.find_one({"user_id": username})
    if not session:
        return None
    
    ip = session["assigned_ip"]
    vpn_id = session["vpn_id"]
    
    await db.vpn_ip_pools.update_one(
        {"pool_id": vpn_id},
        {"$pull": {"assigned_ips": ip}}
    )
    
    ccd_path = f"{CCD_DIR}/{username}"
    if os.path.exists(ccd_path):
        os.remove(ccd_path)
    
    return {"ip": ip, "vpn_id": vpn_id}

async def resolve_session_identity(db, username="", vpn_ip=""):
    normalized_username = (username or "").strip()
    if normalized_username and not is_temp_openvpn_username(normalized_username):
        session = await db.vpn_sessions.find_one({"user_id": normalized_username, "is_active": True})
        if not session:
            session = await db.vpn_sessions.find_one({"user_id": normalized_username})
        return normalized_username, session

    if vpn_ip:
        session = await db.vpn_sessions.find_one({"assigned_ip": vpn_ip, "is_active": True})
        if session:
            return session["user_id"], session

        session = await db.vpn_sessions.find_one({"assigned_ip": vpn_ip})
        if session:
            return session["user_id"], session

        session = await db.vpn_sessions.find_one({"vpn_ip": vpn_ip, "is_active": True})
        if session:
            return session["user_id"], session

        session = await db.vpn_sessions.find_one({"vpn_ip": vpn_ip})
        if session:
            return session["user_id"], session

    return normalized_username, None

def _parse_datetime_to_epoch(value):
    try:
        return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())
    except Exception:
        return 0

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
    except Exception as e:
        print(f"Error querying OpenVPN status log: {e}")

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

class ReleaseIPRequest(BaseModel):
    username: str
    vpn_ip: str = ""
    source_ip: str = ""

class AllocateRequest(BaseModel):
    vpn_id: str
    department: str = "Engineering"

class ConnectEventRequest(BaseModel):
    username: str
    vpn_ip: str
    source_ip: str = ""

@app.post("/users/{username}")
async def create_user(username: str, request: AllocateRequest = None):
    db = get_db()
    vpn_id = request.vpn_id if request else "vpn_eng"
    
    try:
        cert_path = f"{EASYRSA_DIR}/pki/issued/{username}.crt"
        if os.path.exists(cert_path):
            pass
        else:
            run_cmd(f"./easyrsa build-client-full {username} nopass")
        
        ip, pool_name = await allocate_ip(db, username, vpn_id)
        
        with open(f"{EASYRSA_DIR}/pki/ca.crt", "r") as f:
            ca_cert = f.read()
        with open(f"{EASYRSA_DIR}/pki/issued/{username}.crt", "r") as f:
            user_cert = f.read()
        with open(f"{EASYRSA_DIR}/pki/private/{username}.key", "r") as f:
            user_key = f.read()
        with open(TEMPLATE_FILE, "r") as f:
            template = f.read()
        
        user_cert_clean = "-----BEGIN CERTIFICATE-----" + user_cert.split("-----BEGIN CERTIFICATE-----")[1]
        ovpn_content = f"{template}\n<ca>\n{ca_cert}</ca>\n<cert>\n{user_cert_clean}</cert>\n<key>\n{user_key}</key>\n"
        
        os.makedirs(CONFIG_OUT_DIR, exist_ok=True)
        config_path = f"{CONFIG_OUT_DIR}/{username}.ovpn"
        with open(config_path, "w") as f:
            f.write(ovpn_content)
        
        await db.vpn_sessions.update_one(
            {"user_id": username},
            {"$set": {
                "session_id": str(uuid.uuid4()),
                "user_id": username,
                "vpn_id": vpn_id,
                "assigned_ip": ip,
                "vpn_ip": None,
                "source_ip": "",
                "connected_at": None,
                "last_activity": datetime.utcnow(),
                "is_active": False
            }},
            upsert=True
        )
        
        await db.access_states.update_one(
            {"user_id": username},
            {"$set": {
                "has_provisioned": True,
                "provisioned_vpn": vpn_id,
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
                "last_disconnected_at": None
            }},
            upsert=True
        )

        await db.users.update_one(
            {"user_id": username, "disabled": {"$ne": True}},
            {"$set": {"status": "inactive"}}
        )
        
        return {"status": "success", "message": f"User {username} provisioned with IP {ip}", "ip": ip, "pool": pool_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")

@app.get("/users/{username}/download")
def download_config(username: str):
    file_path = f"{CONFIG_OUT_DIR}/{username}.ovpn"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Config not found. Please provision a VPN first.")
    return FileResponse(file_path, filename=f"{username}.ovpn", media_type="application/x-openvpn-profile")

@app.post("/users/{username}/revoke")
async def revoke_user(username: str):
    db = get_db()
    try:
        run_cmd(f"./easyrsa revoke {username}")
        for f in [f"pki/reqs/{username}.req", f"pki/issued/{username}.crt", f"pki/private/{username}.key", f"{CONFIG_OUT_DIR}/{username}.ovpn"]:
            if os.path.exists(f"{EASYRSA_DIR}/{f}"):
                os.remove(f"{EASYRSA_DIR}/{f}")
        run_cmd("./easyrsa gen-crl")
        run_cmd("cp pki/crl.pem /etc/openvpn/crl.pem")
        run_cmd("chmod 644 /etc/openvpn/crl.pem")
        
        released = await release_ip_by_username(db, username)
        
        ccd_path = f"{CCD_DIR}/{username}"
        if os.path.exists(ccd_path):
            os.remove(ccd_path)
        
        await db.vpn_sessions.delete_one({"user_id": username})
        
        await db.access_states.update_one(
            {"user_id": username},
            {"$set": {
                "has_provisioned": False,
                "provisioned_vpn": None,
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "last_disconnected_at": datetime.utcnow()
            }}
        )
        
        return {"status": "success", "message": f"User {username} revoked. Their VPN access has been terminated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to revoke user: {str(e)}")

@app.post("/release-ip")
async def release_ip_endpoint(request: ReleaseIPRequest):
    db = get_db()
    try:
        resolved_username, _ = await resolve_session_identity(db, request.username, request.vpn_ip)
        released = await release_ip_by_username(db, resolved_username)
        
        if released:
            await db.vpn_sessions.update_one(
                {"user_id": resolved_username, "is_active": True},
                {"$set": {"is_active": False, "assigned_ip": None, "last_activity": datetime.utcnow()}}
            )
            
            await db.access_states.update_one(
                {"user_id": resolved_username},
                {"$set": {
                    "connected": False,
                    "connected_vpn": None,
                    "connected_ip": None,
                    "last_disconnected_at": datetime.utcnow()
                }}
            )

            await db.users.update_one(
                {"user_id": resolved_username, "disabled": {"$ne": True}},
                {"$set": {"status": "inactive"}}
            )
            
            await insert_vpn_event(
                db,
                "disconnect",
                resolved_username,
                vpn_ip=released["ip"],
                source_ip=request.source_ip,
                vpn_id=released["vpn_id"],
                details=f"Disconnected from {released['vpn_id']}"
            )
            
            return {"status": "success", "message": f"IP {released['ip']} released for {resolved_username}"}
        
        return {"status": "success", "message": "No active session found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to release IP: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.post("/connect-event")
async def connect_event(request: ConnectEventRequest):
    db = get_db()
    try:
        resolved_username, session = await resolve_session_identity(db, request.username, request.vpn_ip)
        if not resolved_username or is_temp_openvpn_username(resolved_username):
            return {"status": "error", "detail": "Unable to resolve VPN identity"}

        vpn_id = session["vpn_id"] if session else ""

        if not vpn_id and request.vpn_ip:
            pool = await db.vpn_ip_pools.find_one({
                "start_ip": {"$lte": request.vpn_ip},
                "end_ip": {"$gte": request.vpn_ip},
                "is_active": True
            })
            if pool:
                vpn_id = pool["pool_id"]

        if session:
            await db.vpn_sessions.update_one(
                {"user_id": resolved_username},
                {"$set": {
                    "is_active": True,
                    "vpn_ip": request.vpn_ip,
                    "source_ip": request.source_ip,
                    "connected_at": datetime.utcnow(),
                    "last_activity": datetime.utcnow()
                }}
            )
        else:
            await db.vpn_sessions.insert_one({
                "session_id": str(uuid.uuid4()),
                "user_id": resolved_username,
                "vpn_id": vpn_id,
                "assigned_ip": request.vpn_ip,
                "vpn_ip": request.vpn_ip,
                "source_ip": request.source_ip,
                "connected_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "is_active": True
            })

        await db.access_states.update_one(
            {"user_id": resolved_username},
            {"$set": {
                "has_provisioned": True,
                "provisioned_vpn": vpn_id,
                "connected": True,
                "connected_vpn": vpn_id,
                "connected_ip": request.vpn_ip,
                "connected_at": datetime.utcnow()
            }},
            upsert=True
        )

        await db.users.update_one(
            {"user_id": resolved_username, "disabled": {"$ne": True}},
            {"$set": {"status": "active"}}
        )

        await insert_vpn_event(
            db,
            "connect",
            resolved_username,
            vpn_ip=request.vpn_ip,
            source_ip=request.source_ip,
            vpn_id=vpn_id,
            details=f"Connected to {vpn_id}"
        )

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/status")
def get_openvpn_status():
    clients = query_openvpn_status()

    return {
        "connected_clients": clients,
        "count": len(clients)
    }

@app.get("/events")
async def get_events(limit: int = 50, event_type: str = "", user_id: str = ""):
    db = get_db()
    query = {}
    if event_type:
        query["event_type"] = event_type.lower()
    if user_id:
        query["user_id"] = {"$regex": user_id, "$options": "i"}

    cursor = db.vpn_events.find(query).sort("timestamp", -1).limit(limit)
    events = await cursor.to_list(length=limit)
    return [
        {
            "event_type": e.get("event_type") or e.get("event", "").lower(),
            "user_id": e.get("user_id") or e.get("username", ""),
            "vpn_ip": e.get("vpn_ip") or e.get("ip", ""),
            "source_ip": e.get("source_ip", ""),
            "details": e.get("details") or e.get("vpn_id", ""),
            "timestamp": e.get("timestamp", "").isoformat() if e.get("timestamp") else ""
        }
        for e in events
    ]
