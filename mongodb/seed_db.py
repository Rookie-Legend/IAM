import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "iam_db"

DEPT_PREFIX_MAP = {
    "engineering": "U",
    "devops": "D",
    "sre": "D",
    "infrastructure": "D",
    "finance": "F",
    "financial": "F",
    "hr": "H",
    "human_resources": "H",
    "product": "P",
    "security": "S",
    "legal": "L",
    "marketing": "M",
    "sales": "S",
}

def get_prefix_for_dept(dept):
    return DEPT_PREFIX_MAP.get(dept.lower(), "U")

async def seed_db():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    await db.users.drop()
    await db.policies.drop()
    await db.access_states.drop()
    await db.audit_logs.drop()

    print("Collections dropped")

    users_data = [
        {
            "user_id": "S1001",
            "username": "admin",
            "hashed_password": pwd_context.hash("admin_pass"),
            "email": "admin@corpod.com",
            "full_name": "Admin",
            "department": "Security",
            "role": "Security Admin",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "H1001",
            "username": "hr_manager",
            "hashed_password": pwd_context.hash("hr_pass"),
            "email": "hr@corpod.com",
            "full_name": "HR Manager",
            "department": "HR",
            "role": "HR Manager",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "U1001",
            "username": "eng_infra",
            "hashed_password": pwd_context.hash("eng_pass"),
            "email": "infra@corpod.com",
            "full_name": "Cloud Infra Engineer",
            "department": "Engineering",
            "role": "devops_engineer",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "U1002",
            "username": "eng_front",
            "hashed_password": pwd_context.hash("eng_pass"),
            "email": "frontend@corpod.com",
            "full_name": "Frontend Engineer",
            "department": "Engineering",
            "role": "software_engineer",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "U1003",
            "username": "eng_back",
            "hashed_password": pwd_context.hash("eng_pass"),
            "email": "backend@corpod.com",
            "full_name": "Backend Engineer",
            "department": "Engineering",
            "role": "software_engineer",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "F1001",
            "username": "audit_payroll",
            "hashed_password": pwd_context.hash("audit_pass"),
            "email": "payroll@corpod.com",
            "full_name": "Payroll Auditor",
            "department": "Finance",
            "role": "financial_analyst",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "F1002",
            "username": "audit_comp",
            "hashed_password": pwd_context.hash("audit_pass"),
            "email": "compliance@corpod.com",
            "full_name": "Compliance Auditor",
            "department": "Finance",
            "role": "financial_analyst",
            "status": "active",
            "disabled": False
        },
        {
            "user_id": "S1002",
            "username": "rookie",
            "hashed_password": pwd_context.hash("password"),
            "email": "rookie@corpod.com",
            "full_name": "Haresh",
            "department": "Security",
            "role": "Security Admin",
            "status": "active",
            "disabled": False
        }
        
    ]
    await db.users.insert_many(users_data)
    print("Seeded Users")

    policies_data = [
        {
            "pol_id": "POL-HR000001",
            "name": "HR Confidential VPN",
            "type": "access",
            "description": "VPN access for HR personnel handling confidential data",
            "department": "HR",
            "vpn": "vpn_hr",
            "is_active": True
        },
        {
            "pol_id": "POL-ENG00001",
            "name": "Engineering VPN",
            "type": "access",
            "description": "VPN access for Engineering staff",
            "department": "Engineering",
            "vpn": "vpn_eng",
            "is_active": True
        },
        {
            "pol_id": "POL-FIN00001",
            "name": "Finance Audit VPN",
            "type": "access",
            "description": "VPN access for Financial Auditors",
            "department": "Finance",
            "vpn": "vpn_fin",
            "is_active": True
        },
        {
            "pol_id": "POL-SEC00001",
            "name": "Security Ops VPN",
            "type": "access",
            "description": "Unrestricted VPN access for Security Admins",
            "department": "Security",
            "vpn": "vpn_sec",
            "is_active": True
        }
    ]
    await db.policies.insert_many(policies_data)
    print("Seeded Policies")

    access_states_data = [
        {
            "user_id": "S1001",
            "vpn_access": ["vpn_sec", "vpn_hr", "vpn_eng", "vpn_fin"]
        },
        {
            "user_id": "H1001",
            "vpn_access": ["vpn_hr"]
        },
        {
            "user_id": "U1001",
            "vpn_access": ["vpn_eng"]
        },
        {
            "user_id": "U1002",
            "vpn_access": []
        },
        {
            "user_id": "U1003",
            "vpn_access": []
        },
        {
            "user_id": "F1001",
            "vpn_access": []
        },
        {
            "user_id": "F1002",
            "vpn_access": ["vpn_fin"]
        },
        {
            "user_id": "S1002",
            "vpn_access": ["vpn_sec"]
        }
    ]
    await db.access_states.insert_many(access_states_data)
    print("Seeded Access States")

    print("Database seeding completed.")


if __name__ == "__main__":
    asyncio.run(seed_db())