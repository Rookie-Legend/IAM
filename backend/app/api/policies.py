from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_database
from app.api.dependencies import get_current_user, get_current_admin
from app.models.policy import PolicyCreate, Policy

router = APIRouter(prefix="/api/policies", tags=["Policies"])

@router.get("/")
async def list_policies(db=Depends(get_database), current_user=Depends(get_current_user)):
    cursor = db["policies"].find()
    policies = await cursor.to_list(length=100)
    for p in policies:
        p.pop("_id", None)
        if "pol_id" in p:
            p["pol_id"] = str(p["pol_id"])
    return policies

@router.get("/{policy_id}")
async def get_policy(policy_id: str, db=Depends(get_database), current_user=Depends(get_current_user)):
    policy = await db["policies"].find_one({"pol_id": policy_id})
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    policy.pop("_id", None)
    return policy

@router.post("/")
async def create_policy(policy: PolicyCreate, db=Depends(get_database), admin=Depends(get_current_admin)):
    now = datetime.utcnow()
    import uuid
    pol_id = f"POL-{str(uuid.uuid4())[:8].upper()}"
    doc = policy.model_dump()
    doc["pol_id"] = pol_id
    doc["created_on"] = now
    doc["updated_on"] = now
    doc["type"] = doc["type"].value if hasattr(doc["type"], "value") else doc["type"]
    await db["policies"].insert_one(doc)
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "create_policy",
        "target_resource": pol_id,
        "details": f"Admin {admin.user_id} ({admin.role}) created policy '{doc.get('name', pol_id)}' of type {doc.get('type', 'unknown')}",
        "timestamp": now
    })
    return {"status": "success", "policy_id": pol_id}

@router.delete("/{policy_id}")
async def delete_policy(policy_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    policy = await db["policies"].find_one({"pol_id": policy_id})
    result = await db["policies"].delete_one({"pol_id": policy_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "delete_policy",
        "target_resource": policy_id,
        "details": f"Admin {admin.user_id} ({admin.role}) deleted policy '{policy.get('name', policy_id)}' of type {policy.get('type', 'unknown')}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": f"Policy {policy_id} deleted"}

@router.patch("/{policy_id}/toggle")
async def toggle_policy(policy_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    policy = await db["policies"].find_one({"pol_id": policy_id})
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    new_status = not policy.get("is_active", True)
    await db["policies"].update_one({"pol_id": policy_id}, {"$set": {"is_active": new_status, "updated_on": datetime.utcnow()}})
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "policy_status",
        "target_resource": policy_id,
        "details": f"Admin {admin.user_id} ({admin.role}) set policy '{policy.get('name', policy_id)}' to {'active' if new_status else 'inactive'}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "is_active": new_status}

@router.put("/{policy_id}")
async def update_policy(policy_id: str, policy: PolicyCreate, db=Depends(get_database), admin=Depends(get_current_admin)):
    existing = await db["policies"].find_one({"pol_id": policy_id})
    doc = policy.model_dump()
    doc["updated_on"] = datetime.utcnow()
    doc["type"] = doc["type"].value if hasattr(doc["type"], "value") else doc["type"]
    result = await db["policies"].update_one({"pol_id": policy_id}, {"$set": doc})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "update_policy",
        "target_resource": policy_id,
        "details": f"Admin {admin.user_id} ({admin.role}) updated policy '{doc.get('name', policy_id)}' - type: {doc.get('type', 'unknown')}, active: {doc.get('is_active', True)}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": f"Policy {policy_id} updated"}
