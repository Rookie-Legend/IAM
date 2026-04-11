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

def ip_to_int(ip):
    parts = ip.split('.')
    return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])

def int_to_ip(n):
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"

async def get_pool_from_db(db, vpn_id):
    pool = await db.vpn_ip_pools.find_one({"pool_id": vpn_id, "is_active": True})
    if not pool:
        raise HTTPException(status_code=404, detail=f"Pool {vpn_id} not found")
    return pool

async def allocate_ip(db, user_id, vpn_id):
    pool = await get_pool_from_db(db, vpn_id)
    
    start_int = ip_to_int(pool["start_ip"])
    end_int = ip_to_int(pool["end_ip"])
    
    taken = set(pool.get("assigned_ips", []))
    
    for ip_int in range(start_int, end_int + 1):
        ip = int_to_ip(ip_int)
        if ip not in taken:
            await db.vpn_ip_pools.update_one(
                {"pool_id": vpn_id},
                {"$addToSet": {"assigned_ips": ip}}
            )
            os.makedirs(CCD_DIR, exist_ok=True)
            with open(f"{CCD_DIR}/{user_id}", "w") as f:
                f.write(f"ifconfig-push {ip} {pool['gateway']}\n")
            return ip, pool["name"]
    
    raise HTTPException(status_code=503, detail="No IPs available in pool")

async def release_ip_by_username(db, username):
    session = await db.vpn_sessions.find_one({"user_id": username, "is_active": True})
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

async def log_audit(db, event_type, user_id, vpn_id, vpn_ip, source_ip="", details=""):
    await db.vpn_audit_logs.insert_one({
        "event_type": event_type,
        "user_id": user_id,
        "vpn_id": vpn_id,
        "vpn_ip": vpn_ip,
        "source_ip": source_ip,
        "timestamp": datetime.utcnow(),
        "details": details
    })

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
        
        await db.vpn_sessions.insert_one({
            "session_id": str(uuid.uuid4()),
            "user_id": username,
            "vpn_id": vpn_id,
            "assigned_ip": ip,
            "source_ip": "",
            "connected_at": None,
            "last_activity": datetime.utcnow(),
            "is_active": True
        })
        
        await db.access_states.update_one(
            {"user_id": username},
            {"$set": {
                "connected": False,
                "connected_vpn": vpn_id,
                "connected_ip": ip,
                "connected_at": None
            }},
            upsert=True
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
        raise HTTPException(status_code=404, detail="Config not found. Did you create the user?")
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
        
        if released:
            await db.vpn_sessions.update_one(
                {"user_id": username},
                {"$set": {"is_active": False, "connected_at": None}}
            )
            await log_audit(db, "revoke", username, released["vpn_id"], released["ip"])
        
        return {"status": "success", "message": f"User {username} revoked. Their VPN access has been terminated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to revoke user: {str(e)}")

@app.post("/release-ip")
async def release_ip_endpoint(request: ReleaseIPRequest):
    db = get_db()
    try:
        released = await release_ip_by_username(db, request.username)
        
        if released:
            await db.vpn_sessions.update_one(
                {"user_id": request.username, "is_active": True},
                {"$set": {"is_active": False, "last_activity": datetime.utcnow()}}
            )
            
            await db.access_states.update_one(
                {"user_id": request.username},
                {"$set": {
                    "connected": False,
                    "last_disconnected_at": datetime.utcnow()
                }}
            )
            
            await log_audit(db, "disconnect", request.username, released["vpn_id"], released["ip"], request.source_ip)
            
            return {"status": "success", "message": f"IP {released['ip']} released for {request.username}"}
        
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
        session = await db.vpn_sessions.find_one({"user_id": request.username, "is_active": True})
        vpn_id = session["vpn_id"] if session else ""

        if not vpn_id and request.vpn_ip:
            pool = await db.vpn_ip_pools.find_one({
                "start_ip": {"$lte": request.vpn_ip},
                "end_ip": {"$gte": request.vpn_ip},
                "is_active": True
            })
            if pool:
                vpn_id = pool["pool_id"]

        await db.vpn_sessions.update_one(
            {"user_id": request.username, "is_active": True},
            {"$set": {
                "vpn_ip": request.vpn_ip,
                "source_ip": request.source_ip,
                "connected_at": datetime.utcnow(),
                "last_activity": datetime.utcnow()
            }}
        )

        await db.access_states.update_one(
            {"user_id": request.username},
            {"$set": {
                "connected": True,
                "connected_vpn": vpn_id,
                "connected_ip": request.vpn_ip,
                "connected_at": datetime.utcnow()
            }},
            upsert=True
        )

        await log_audit(db, "connect", request.username, vpn_id, request.vpn_ip, request.source_ip)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/status")
def get_openvpn_status():
    clients = query_openvpn_status()

    recent_events = []
    log_path = "/etc/openvpn/connect.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
                recent_events = [line.strip() for line in lines[-50:]]
        except Exception:
            pass

    return {
        "connected_clients": clients,
        "count": len(clients),
        "recent_events": recent_events
    }