"""
Policy RAG — fetches the user's department policy from MongoDB.
Returns a structured text context block describing allowed VPNs and resources.
"""


async def fetch_policy_context(user_id: str, department: str, db) -> str:
    """
    Find policies that match this user's department/team and summarise allowed access.
    Returns a formatted string for use as LLM context.
    """
    dept_lower = department.lower().strip() if department else ""

    # Search all active policies and find ones that cover this department / team
    all_policies = await db["policies"].find({"is_active": True}).to_list(length=100)

    matched = []
    for policy in all_policies:
        rules = policy.get("rules", {})
        # Policies can store team/department in various keys
        policy_team = (
            rules.get("team", "")
            or rules.get("department", "")
            or policy.get("name", "")
        ).lower()
        if dept_lower and dept_lower in policy_team:
            matched.append(policy)

    if not matched:
        # Fallback: return all policies as generic context
        if all_policies:
            policy_names = ", ".join(p.get("name", p.get("_id", "?")) for p in all_policies)
            return (
                "POLICY CONTEXT:\n"
                f"- Department: {department}\n"
                "- Assigned Policy: None found specifically for this department\n"
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

    # Use the first (most specific) matched policy
    policy = matched[0]
    rules = policy.get("rules", {})

    allowed_vpns = rules.get("allowed_vpns", rules.get("vpn_access", []))
    allowed_resources = rules.get("allowed_resources", rules.get("resources", []))
    mfa_required = rules.get("mfa_required", False)

    lines = [
        "POLICY CONTEXT:",
        f"- Department: {department}",
        f"- Assigned Policy: {policy.get('name', policy.get('_id', 'Unknown'))}",
        f"- Policy Type: {policy.get('type', 'access')}",
        f"- Allowed VPNs: {', '.join(allowed_vpns) if allowed_vpns else 'none'}",
        f"- Allowed Resources: {', '.join(allowed_resources) if allowed_resources else 'none'}",
        f"- MFA Required: {mfa_required}",
        f"- Policy Description: {policy.get('description', 'N/A')}",
    ]
    return "\n".join(lines)
