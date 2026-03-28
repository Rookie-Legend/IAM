"""
Unified RAG - Policy Context
Fetches the user's department policy from MongoDB with vector-based semantic search.
Returns a structured text context block describing allowed VPNs and resources.
"""
from app.rag.vector_store import search_similar_policies


async def fetch_policy_context(user_id: str, department: str, db, query: str = None) -> str:
    """
    Find policies that match this user's department/team and summarise allowed access.
    Uses vector similarity search when a query is provided for better context matching.
    Returns a formatted string for use as LLM context.
    """
    dept_lower = department.lower().strip() if department else ""

    if query:
        policy_chunks = await search_similar_policies(query, db, top_k=5)
        if policy_chunks:
            return "POLICY CONTEXT (semantic search):\n" + "\n".join(f"- {c}" for c in policy_chunks)

    all_policies = await db["policies"].find({"is_active": True}).to_list(length=100)

    matched = []
    for policy in all_policies:
        rules = policy.get("rules", {})
        policy_team = (
            rules.get("team", "")
            or rules.get("department", "")
            or policy.get("name", "")
        ).lower()
        if dept_lower and dept_lower in policy_team:
            matched.append(policy)

    if not matched:
        if all_policies:
            policy_names = ", ".join(p.get("name", p.get("pol_id", "?")) for p in all_policies)
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

    policy = matched[0]
    rules = policy.get("rules", {})

    allowed_vpns = rules.get("allowed_vpns", rules.get("vpn_access", []))
    allowed_resources = rules.get("allowed_resources", rules.get("resources", []))
    mfa_required = rules.get("mfa_required", False)

    lines = [
        "POLICY CONTEXT:",
        f"- Department: {department}",
        f"- Assigned Policy: {policy.get('name', policy.get('pol_id', 'Unknown'))}",
        f"- Policy Type: {policy.get('type', 'access')}",
        f"- Allowed VPNs: {', '.join(allowed_vpns) if allowed_vpns else 'none'}",
        f"- Allowed Resources: {', '.join(allowed_resources) if allowed_resources else 'none'}",
        f"- MFA Required: {mfa_required}",
        f"- Policy Description: {policy.get('description', 'N/A')}",
    ]
    return "\n".join(lines)
