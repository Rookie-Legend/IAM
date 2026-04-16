"""
Unified RAG - Policy Context
Fetches the user's department policy from MongoDB with vector-based semantic search.
Returns a structured text context block describing allowed VPNs and resources.

IMPORTANT: Policies in MongoDB use a top-level 'vpn' field (not rules.allowed_vpns).
Always surface the full list of available VPNs from vpn_ip_pools so the LLM
can make correct decisions about what the user is requesting.
"""


async def _get_all_available_vpns(db) -> list[str]:
    """Fetch all active VPN pool IDs from MongoDB."""
    pools = await db["vpn_ip_pools"].find({"is_active": True}).to_list(length=100)
    return [p["pool_id"] for p in pools if p.get("pool_id")]


async def fetch_policy_context(user_id: str, department: str, db, query: str = None) -> str:
    """
    Find policies that match this user's department/team and summarise allowed access.
    Reads the correct 'vpn' field from policy documents (not rules.allowed_vpns).
    Always injects the full list of available VPNs from vpn_ip_pools.
    Returns a formatted string for use as LLM context.
    """
    dept_lower = department.lower().strip() if department else ""

    # Fetch all active VPNs from the pool for grounding the LLM
    all_available_vpns = await _get_all_available_vpns(db)
    vpn_catalog_line = f"- All Available VPNs in System: {', '.join(all_available_vpns) if all_available_vpns else 'none'}"

    all_policies = await db["policies"].find({"is_active": True}).to_list(length=100)

    # Match policy by department field (top-level or inside rules)
    matched = []
    for policy in all_policies:
        rules = policy.get("rules", {})
        policy_dept = (
            policy.get("department", "")
            or rules.get("team", "")
            or rules.get("department", "")
            or policy.get("name", "")
        ).lower()
        if dept_lower and dept_lower in policy_dept:
            matched.append(policy)

    if not matched:
        if all_policies:
            policy_names = ", ".join(p.get("name", p.get("pol_id", "?")) for p in all_policies)
            return (
                "POLICY CONTEXT:\n"
                f"- Department: {department}\n"
                "- Assigned Policy: None found specifically for this department\n"
                f"- Available Policies in System: {policy_names}\n"
                f"{vpn_catalog_line}\n"
                "- Allowed VPNs for this department: not explicitly defined\n"
                "- Allowed Resources: not explicitly defined"
            )
        return (
            "POLICY CONTEXT:\n"
            f"- Department: {department}\n"
            "- Assigned Policy: NONE\n"
            f"{vpn_catalog_line}\n"
            "- Allowed VPNs for this department: none\n"
            "- Allowed Resources: none"
        )

    policy = matched[0]
    rules = policy.get("rules", {})

    # Policies use a top-level 'vpn' field OR rules.allowed_vpns / rules.vpn_access
    # Normalise to a list regardless of schema variant
    raw_vpn = policy.get("vpn") or rules.get("allowed_vpns") or rules.get("vpn_access") or []
    if isinstance(raw_vpn, str):
        allowed_vpns = [raw_vpn]
    else:
        allowed_vpns = list(raw_vpn)

    allowed_resources = rules.get("allowed_resources", rules.get("resources", []))
    mfa_required = rules.get("mfa_required", False)

    lines = [
        "POLICY CONTEXT:",
        f"- Department: {department}",
        f"- Assigned Policy: {policy.get('name', policy.get('pol_id', 'Unknown'))}",
        f"- Policy Type: {policy.get('type', 'access')}",
        f"- Allowed VPNs for this department: {', '.join(allowed_vpns) if allowed_vpns else 'none'}",
        f"- Allowed Resources: {', '.join(allowed_resources) if allowed_resources else 'none'}",
        f"- MFA Required: {mfa_required}",
        f"- Policy Description: {policy.get('description', 'N/A')}",
        vpn_catalog_line,
    ]
    return "\n".join(lines)
