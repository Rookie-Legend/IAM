from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_database
from app.api.dependencies import get_current_user, get_current_admin
from app.models.policy import PolicyCreate, Policy

router = APIRouter(prefix="/api/policies", tags=["Policies"])

GRANT_POLICY_TYPES = {"access", "start_access"}
BLOCK_POLICY_TYPES = {"block_access"}


def _policy_type(policy: dict) -> str:
    value = policy.get("type", "")
    return value.value if hasattr(value, "value") else str(value)


async def revalidate_access_for_policies(db, admin, changed_policy: dict | None = None) -> dict:
    """Sync current VPN access with active access/start/block policies."""
    changed_department = (changed_policy or {}).get("department") or ""
    changed_vpn = (changed_policy or {}).get("vpn") or ""
    scoped = bool(changed_department and changed_vpn)

    user_query = {"disabled": {"$ne": True}}
    if scoped:
        user_query["department"] = changed_department
    users = await db["users"].find(user_query).to_list(length=1000)

    active_policies = await db["policies"].find({"is_active": True}).to_list(length=1000)
    grants_by_dept: dict[str, set[str]] = {}
    blocks_by_dept: dict[str, set[str]] = {}

    for policy in active_policies:
        department = policy.get("department")
        vpn = policy.get("vpn")
        if not department or not vpn:
            continue
        policy_type = _policy_type(policy)
        if policy_type in GRANT_POLICY_TYPES:
            grants_by_dept.setdefault(department, set()).add(vpn)
        elif policy_type in BLOCK_POLICY_TYPES:
            blocks_by_dept.setdefault(department, set()).add(vpn)

    grants = 0
    revokes = 0
    checked_users = 0
    affected_vpns = {changed_vpn} if scoped else None

    for user in users:
        checked_users += 1
        user_id = user.get("user_id")
        department = user.get("department", "")
        existing_state = await db["access_states"].find_one({"user_id": user_id})
        state = existing_state or {
            "user_id": user_id,
            "vpn_access": [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": None,
        }

        current_vpns = set(state.get("vpn_access", []))
        new_vpns = set(current_vpns)
        department_grants = grants_by_dept.get(department, set())
        department_blocks = blocks_by_dept.get(department, set())
        vpns_to_check = affected_vpns or (current_vpns | department_grants | department_blocks)

        for vpn in vpns_to_check:
            if vpn in department_blocks:
                new_vpns.discard(vpn)
            elif vpn in department_grants:
                new_vpns.add(vpn)

        if new_vpns == current_vpns:
            continue

        update_doc = {"vpn_access": sorted(new_vpns)}
        set_on_insert = {
            "user_id": user_id,
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": None,
        }
        revoked_for_user = current_vpns - new_vpns
        granted_for_user = new_vpns - current_vpns
        grants += len(granted_for_user)
        revokes += len(revoked_for_user)

        active_vpn = state.get("connected_vpn") or state.get("provisioned_vpn")
        if active_vpn in revoked_for_user:
            update_doc.update({
                "has_provisioned": False,
                "provisioned_vpn": None,
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
            })

        await db["access_states"].update_one(
            {"user_id": user_id},
            {"$set": update_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )

    summary = {
        "checked_users": checked_users,
        "grants": grants,
        "revokes": revokes,
        "scope": "scoped" if scoped else "full",
    }

    await db["audit_logs"].insert_one({
        "user_id": getattr(admin, "user_id", "system"),
        "action": "policy_revalidation",
        "target_resource": changed_policy.get("pol_id", "all_policies") if changed_policy else "all_policies",
        "details": (
            f"Policy revalidation completed ({summary['scope']}). "
            f"Users checked: {checked_users}, grants: {grants}, revokes: {revokes}."
        ),
        "timestamp": datetime.utcnow(),
        "summary": summary,
    })
    return summary

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
    summary = await revalidate_access_for_policies(db, admin, doc)
    return {"status": "success", "policy_id": pol_id, "revalidation": summary}

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
    summary = await revalidate_access_for_policies(db, admin, policy)
    return {"status": "success", "message": f"Policy {policy_id} deleted", "revalidation": summary}

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
    policy["is_active"] = new_status
    summary = await revalidate_access_for_policies(db, admin, policy)
    return {"status": "success", "is_active": new_status, "revalidation": summary}

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
    old_summary = await revalidate_access_for_policies(db, admin, existing)
    new_doc = {**doc, "pol_id": policy_id}
    new_summary = await revalidate_access_for_policies(db, admin, new_doc)
    return {
        "status": "success",
        "message": f"Policy {policy_id} updated",
        "revalidation": {
            "previous_scope": old_summary,
            "new_scope": new_summary,
        },
    }
