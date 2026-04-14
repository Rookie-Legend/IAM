from datetime import datetime


def _is_vpn_resource(resource: str) -> bool:
    return "vpn" in (resource or "").lower()


def _normalize_policy(policy: dict) -> dict:
    rules = policy.get("rules", {}) if isinstance(policy.get("rules"), dict) else {}
    policy_vpn = policy.get("vpn")
    allowed_vpns = []
    if policy_vpn:
        allowed_vpns.append(policy_vpn)
    for vpn_id in rules.get("allowed_vpns", rules.get("vpn_access", [])):
        if vpn_id and vpn_id not in allowed_vpns:
            allowed_vpns.append(vpn_id)

    allowed_resources = list(rules.get("allowed_resources", rules.get("resources", [])))

    return {
        "policy_id": policy.get("pol_id"),
        "name": policy.get("name", policy.get("pol_id", "Unknown")),
        "department": policy.get("department", ""),
        "type": policy.get("type", "access"),
        "description": policy.get("description", ""),
        "allowed_vpns": allowed_vpns,
        "allowed_resources": allowed_resources,
        "mfa_required": rules.get("mfa_required", False),
        "raw": policy,
    }


async def resolve_matching_policies(db, department: str, requested_resource: str) -> list[dict]:
    query = {"is_active": True, "type": "access"}
    if department:
        query["department"] = department

    policies = await db["policies"].find(query).to_list(length=100)
    normalized = [_normalize_policy(policy) for policy in policies]

    if not requested_resource:
        return normalized

    requested = requested_resource.lower()
    matches = []
    for policy in normalized:
        if requested in {vpn.lower() for vpn in policy["allowed_vpns"]}:
            matches.append(policy)
            continue
        if requested in {resource.lower() for resource in policy["allowed_resources"]}:
            matches.append(policy)
    return matches


async def resolve_primary_policy(db, department: str, requested_resource: str) -> dict | None:
    matches = await resolve_matching_policies(db, department, requested_resource)
    return matches[0] if matches else None


async def has_prior_grants(db, user_id: str) -> bool:
    state = await db["access_states"].find_one({"user_id": user_id}) or {}
    if state.get("vpn_access") or state.get("resources"):
        return True

    approved_request = await db["access_requests"].find_one({
        "user_id": user_id,
        "status": "approved"
    })
    return approved_request is not None


async def sync_granted_access_state(db, user_id: str, requested_resource: str) -> None:
    field = "vpn_access" if _is_vpn_resource(requested_resource) else "resources"
    state = await db["access_states"].find_one({"user_id": user_id})

    if state:
        existing = list(state.get(field, []))
        if requested_resource and requested_resource not in existing:
            existing.append(requested_resource)
        await db["access_states"].update_one(
            {"user_id": user_id},
            {"$set": {field: existing}},
        )
    else:
        await db["access_states"].insert_one({
            "user_id": user_id,
            "vpn_access": [requested_resource] if field == "vpn_access" else [],
            "resources": [requested_resource] if field == "resources" else [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": None
        })


async def finalize_access_decision(
    db,
    current_user,
    requested_resource: str,
    rag_result: dict,
    wants_escalation: bool = False,
) -> tuple[str, dict]:
    state = await db["access_states"].find_one({"user_id": current_user.user_id}) or {}
    policy = await resolve_primary_policy(db, current_user.department, requested_resource)
    prior_grants = await has_prior_grants(db, current_user.user_id)

    granted_resources = set(state.get("vpn_access", [])) | set(state.get("resources", []))
    rag_decision = (rag_result.get("decision") or "DENY").upper()

    meta = {
        "rag_decision": rag_decision,
        "policy_match": bool(policy),
        "policy_id": policy.get("policy_id") if policy else None,
        "policy_name": policy.get("name") if policy else None,
        "forced_reason": None,
    }

    if requested_resource in granted_resources:
        meta["forced_reason"] = "already_granted"
        return "ACCEPT", meta

    if wants_escalation:
        meta["forced_reason"] = "user_requested_escalation"
        return "ESCALATE", meta

    if not prior_grants:
        meta["forced_reason"] = "first_time_user"
        return "ESCALATE", meta

    if rag_decision == "ACCEPT" and not policy:
        meta["forced_reason"] = "no_matching_policy"
        return "ESCALATE", meta

    return rag_decision, meta


async def approve_access_request_with_policy(db, access_req: dict) -> tuple[dict | None, str]:
    user_id = access_req.get("user_id")
    resource_type = access_req.get("resource_type", "")
    user = await db["users"].find_one({"user_id": user_id})
    department = user.get("department", "") if user else ""
    policy = await resolve_primary_policy(db, department, resource_type)

    await sync_granted_access_state(db, user_id, resource_type)

    if policy:
        return policy, "policy"
    return None, "exception"


def build_policy_context_text(department: str, policy: dict | None, all_policies: list[dict]) -> str:
    if not policy:
        if all_policies:
            policy_names = ", ".join(p.get("name", p.get("policy_id", "?")) for p in all_policies)
            return (
                "POLICY CONTEXT:\n"
                f"- Department: {department}\n"
                "- Assigned Policy: None found specifically for this request\n"
                f"- Available Policies in System: {policy_names}\n"
                "- Allowed VPNs: not explicitly defined\n"
                "- Allowed Resources: not explicitly defined"
            )
        return (
            "POLICY CONTEXT:\n"
            f"- Department: {department}\n"
            "- Assigned Policy: NONE\n"
            "- Allowed VPNs: none\n"
            "- Allowed Resources: none"
        )

    lines = [
        "POLICY CONTEXT:",
        f"- Department: {department}",
        f"- Assigned Policy: {policy.get('name', policy.get('policy_id', 'Unknown'))}",
        f"- Policy Type: {policy.get('type', 'access')}",
        f"- Allowed VPNs: {', '.join(policy.get('allowed_vpns', [])) or 'none'}",
        f"- Allowed Resources: {', '.join(policy.get('allowed_resources', [])) or 'none'}",
        f"- MFA Required: {policy.get('mfa_required', False)}",
        f"- Policy Description: {policy.get('description', 'N/A')}",
    ]
    return "\n".join(lines)


def access_request_metadata(final_decision: str, decision_meta: dict, requested_resource: str) -> dict:
    return {
        "final_decision": final_decision,
        "policy_id": decision_meta.get("policy_id"),
        "policy_name": decision_meta.get("policy_name"),
        "forced_reason": decision_meta.get("forced_reason"),
        "requested_resource": requested_resource,
        "evaluated_at": datetime.utcnow(),
    }
