import subprocess, os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

app = FastAPI()

EASYRSA_DIR = "/etc/openvpn/easy-rsa"
CONFIG_OUT_DIR = "/etc/openvpn/client-configs"
TEMPLATE_FILE = "/app/client.ovpn.template"

def run_cmd(cmd):
    # EASYRSA_BATCH=1 ensures it doesn't ask for manual confirmation when making/revoking users
    subprocess.run(cmd, cwd=EASYRSA_DIR, shell=True, check=True, env={**os.environ, "EASYRSA_BATCH": "1"})

@app.post("/users/{username}")
def create_user(username: str):
    try:
        run_cmd(f"./easyrsa build-client-full {username} nopass")
        with open(f"{EASYRSA_DIR}/pki/ca.crt", "r") as f: ca_cert = f.read()
        with open(f"{EASYRSA_DIR}/pki/issued/{username}.crt", "r") as f: user_cert = f.read()
        with open(f"{EASYRSA_DIR}/pki/private/{username}.key", "r") as f: user_key = f.read()
        with open(TEMPLATE_FILE, "r") as f: template = f.read()

        user_cert_clean = "-----BEGIN CERTIFICATE-----" + user_cert.split("-----BEGIN CERTIFICATE-----")[1]

        ovpn_content = f"{template}\n<ca>\n{ca_cert}</ca>\n<cert>\n{user_cert_clean}</cert>\n<key>\n{user_key}</key>\n"
        
        config_path = f"{CONFIG_OUT_DIR}/{username}.ovpn"
        with open(config_path, "w") as f: f.write(ovpn_content)
        return {"status": "success", "message": f"User {username} created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")

@app.get("/users/{username}/download")
def download_config(username: str):
    file_path = f"{CONFIG_OUT_DIR}/{username}.ovpn"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Config not found. Did you create the user?")
    return FileResponse(file_path, filename=f"{username}.ovpn")

@app.post("/users/{username}/revoke")
def revoke_user(username: str):
    try:
        run_cmd(f"./easyrsa revoke {username}")
        run_cmd("./easyrsa gen-crl")
        run_cmd("cp pki/crl.pem /etc/openvpn/crl.pem")
        run_cmd("chmod 644 /etc/openvpn/crl.pem")
        config_path = f"{CONFIG_OUT_DIR}/{username}.ovpn"
        if os.path.exists(config_path):
            os.remove(config_path)

        return {"status": "success", "message": f"User {username} revoked. Their VPN access has been terminated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to revoke user: {str(e)}")