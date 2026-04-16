import json
import uuid
import httpx
from datetime import datetime
from groq import Groq
from app.core.config import settings
from app.core.security import get_password_hash
from app.api.vpn import revoke_vpn
from app.rag.rag_engine import rag_answer

_client = None

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

DEFAULT_PREFIX = "U"

# Departments that are registered in this system (must match VPN policy entries)
ALLOWED_DEPARTMENTS = {"engineering", "finance", "hr", "sales", "security"}


def _get_prefix_for_department(department: str) -> str:
    dept_lower = department.lower().replace(" ", "_")
    return DEPT_PREFIX_MAP.get(dept_lower, DEFAULT_PREFIX)


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


async def _call_groq(messages: list) -> dict:
    import asyncio
    client = _get_client()
    def _sync_call():
        return client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.1,
            max_tokens=800
        )
    response = await asyncio.to_thread(_sync_call)
    return {"choices": [{"message": {"content": response.choices[0].message.content}}]}


def _parse_json(raw: str) -> dict:
    if "```" in raw:
        for part in raw.split("```"):
            if "{" in part:
                raw = part.lstrip("json").strip()
                break
    try:
        return json.loads(raw.strip())
    except Exception:
        return {"intent": "unknown", "entities": {}, "missing_fields": []}


async def extract_admin_intent(user_message: str, history: list) -> dict:
    system_prompt = """
You are an IAM system assistant. Extract the intent and entities from admin messages.

CRITICAL — CONVERSATION CONTEXT:
- Always read the full conversation history.
- If the previous assistant message asked for more details (e.g. "Missing: name, department. Can you provide them?"), treat the user's reply as a FOLLOW-UP for that SAME intent. Do NOT switch to greeting/help/unknown.
- A lone ID like "U1001" or "u001" after a joiner/mover/leaver/disable/reinstate context means the user is supplying that entity. Continue the same intent.
- NEVER classify a follow-up reply as "greeting" or "unknown" when there is clearly an active conversation.
- Only classify as "greeting" when it is the very first message and is a pure salutation with no task.
- Only classify as "unknown" if there is truly no recognisable intent and no prior context.

Available intents:
- greeting:       user says hi/hello/hey/greetings/good morning etc. (ONLY at conversation start, no task context)
- help:           user asks for help, commands, features, what can you do, menu
- rag_query:      user asks anything about WHY a user was denied, suspicious behaviour, fraud detection,
                  access logs analysis, risk levels, audit trail questions, "show suspicious users",
                  "why was X denied", "who has high risk", "explain this decision", "show logs for",
                  "detect fraud", "anomaly", "escalations", "multiple denials"
                  NOTE: Do NOT use rag_query for questions about policies themselves (use explain_policy or list_policies)
- joiner:         onboard a new employee
- mover:          transfer employee to new dept/role
- leaver:         offboard employee and revoke all access
- disable:        temporarily disable a user account (keep account but block access)
- reinstate:      re-enable a disabled employee
- bulk_joiner:    onboard multiple employees
- bulk_leaver:    offboard multiple employees
- query_users:    search/list users
- query_audit:    search audit logs
- query_permissions: check user permissions
- create_policy:  create a new IAM policy
- list_policies:  show/list all existing policies, can be filtered by department/type/name
- explain_policy: explain what a specific policy does (by name or ID)
- delete_policy:  delete a policy by name or ID
- update_policy:  update/edit an existing policy
- general_query:  any factual question about the portal, departments, system stats, VPN pools, or
                  "what is this portal?", "list all departments", "how many users?", "what VPNs exist?"
                  Use this ONLY when no other specific intent matches.
- dangerous_action: user attempts harmful/unauthorized operations such as:
                  "drop database", "delete all users", "wipe data", "hack", "bypass security"
- unknown:        cannot determine intent

Always respond with valid JSON only. No text outside JSON.

For joiner — REQUIRED fields: name, department, role, email. OPTIONAL: user_id (auto-generated if absent).
NEVER guess or infer role from department. ONLY set role if the user explicitly stated it.
NEVER auto-generate email. ONLY set email if the user explicitly provided it.
Only accept department values from: engineering, finance, hr, sales, security.
{
    "intent": "joiner",
    "entities": {
        "user_id":    "U1001 or null if not given",
        "name":       "full name or null",
        "email":      "email ONLY if explicitly given by user, else null",
        "department": "engineering/finance/hr/sales/security or null",
        "role":       "exact role ONLY if explicitly stated by user, else null"
    },
    "missing_fields": ["list name, department, role, and/or email if they are truly absent — NEVER list user_id"],
    "confidence": "HIGH/MEDIUM/LOW",
    "message": "what you understood"
}

For disable/reinstate/leaver:
{
    "intent": "disable",
    "entities": {"user_id": "U1001"},
    "missing_fields": ["user_id if not provided"],
    "confidence": "HIGH",
    "message": "what you understood"
}

For mover — REQUIRED fields: user_id, department, role. ALL must be explicitly provided.
NEVER guess or infer role. ONLY set role if the user explicitly stated it.
Only accept department values from: engineering, finance, hr, sales, security.
{
    "intent": "mover",
    "entities": {"user_id": "U1001 or null", "department": "new department or null", "role": "new role ONLY if explicitly stated, else null"},
    "missing_fields": ["user_id if missing", "department if missing", "role if missing"],
    "confidence": "HIGH",
    "message": "what you understood"
}

For bulk operations:
{
    "intent": "bulk_joiner",
    "entities": {
        "employees": [
            {"name": "...", "email": "...", "department": "...", "role": "..."},
            ...
        ]
    },
    "confidence": "HIGH",
    "message": "what you understood"
}

For queries:
{
    "intent": "query_users",
    "entities": {
        "filter": "department/role/status filter or null",
        "value":  "filter value or null"
    },
    "confidence": "HIGH",
    "message": "what you understood"
}

Role mapping guide:
- "software engineer/developer/programmer" → software_engineer
- "devops/sre/infrastructure" → devops_engineer
- "finance/accountant/analyst" → financial_analyst
- "hr/human resources/recruiter" → hr_manager
- "product/pm/product manager" → product_manager

For create_policy — CRITICAL RULE: NEVER infer, guess, or assume any field from partial input.
ONLY set a field to a non-null value if the user has EXPLICITLY stated it in the current OR previous messages.
You MUST read the chat history. If the bot previously said "Department recorded: engineering", you MUST include "department": "engineering" in your output. Do not drop previously collected fields!
{
    "intent": "create_policy",
    "entities": {
        "name":        "exact policy name if explicitly given in history, else null",
        "type":        "jml / access / mfa ONLY if explicitly stated in history, else null",
        "description": "description ONLY if explicitly given in history, else null",
        "department":  "department ONLY if explicitly stated in history, else null",
        "vpn":         "vpn profile ONLY if explicitly given in history (e.g. vpn_hr, vpn_fin), else null",
        "is_active":   true
    },
    "missing_fields": [],
    "confidence": "HIGH",
    "message": "what you understood"
}

For list_policies — extract department, type, or name filter if the user mentions one:
{"intent": "list_policies", "entities": {"filter": "department OR type OR name — use exactly one of these strings as the key, or null if no filter", "value": "the filter value (e.g. hr, finance, access, jml) or null"}, "confidence": "HIGH", "message": ""}
Examples:
- "list hr policies" → {"filter": "department", "value": "hr"}
- "show all access policies" → {"filter": "type", "value": "access"}
- "list all policies" → {"filter": null, "value": null}

For explain_policy — user wants to understand what a specific policy does:
{"intent": "explain_policy", "entities": {"policy_id": "POL-XXXXXXXX or null", "name": "policy name if id not given, else null"}, "confidence": "HIGH", "message": ""}

For general_query — factual questions about the portal, departments, users, stats, VPNs:
{
    "intent": "general_query",
    "entities": {
        "sub_type": "departments | users | stats | vpn | portal_info",
        "filter": "department name or null (for user queries filtered by dept)"
    },
    "confidence": "HIGH",
    "message": "what you understood"
}
Examples:
- "List all departments" → sub_type: departments
- "Show users in engineering" → sub_type: users, filter: engineering
- "How many active users?" → sub_type: stats
- "What VPNs are available?" → sub_type: vpn
- "What is this portal?" → sub_type: portal_info

For dangerous_action — harmful or unauthorized operations:
{"intent": "dangerous_action", "entities": {}, "confidence": "HIGH", "message": "what the user tried"}

For delete_policy:
{"intent": "delete_policy", "entities": {"policy_id": "POL-XXXXXXXX or null", "name": "policy name if id not given"}, "missing_fields": [], "confidence": "HIGH", "message": ""}

For update_policy:
{
    "intent": "update_policy",
    "entities": {
        "policy_id":   "POL-XXXXXXXX or null",
        "name":        "new name or null to keep existing",
        "type":        "jml / access / mfa or null",
        "description": "new description or null",
        "department":  "new department or null",
        "vpn":         "new vpn or null",
        "is_active":   true
    },
    "missing_fields": ["policy_id or name if neither given"],
    "confidence": "HIGH",
    "message": ""
}
"""

    messages = [{"role": "system", "content": system_prompt}]
    valid_roles = {"system", "user", "assistant"}
    for h in history[-8:]:
        if isinstance(h, dict):
            role = h.get("role", "user")
            # Map frontend 'bot' role → 'assistant' (required by LLM API)
            if role == "bot":
                role = "assistant"
            if role not in valid_roles:
                role = "user"
            # Frontend stores text in 'text' key; API uses 'content'
            content = h.get("text") or h.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    data = await _call_groq(messages)
    return _parse_json(data["choices"][0]["message"]["content"])


async def generate_user_id(db, department: str) -> str:
    prefix = _get_prefix_for_department(department)
    pattern = f"^{prefix}\\d+$"
    users = await db["users"].find({}, {"user_id": 1}).to_list(length=None)
    existing = []
    for u in users:
        uid = u.get("user_id", u["_id"])
        if uid.startswith(prefix):
            try:
                num = int(uid[len(prefix):])
                existing.append(num)
            except ValueError:
                pass
    next_num = (max(existing) + 1) if existing else 1001
    return f"{prefix}{next_num}"


ADMIN_HELP_TEXT = (
    "IAM Admin Assistant — Available Commands\n\n"
    "Employee Lifecycle (JML)\n"
    "- Join: Onboard a new employee. Provide name, department, and role.\n"
    "- Move: Transfer an employee to a new department or role. Provide user ID and target department.\n"
    "- Offboard: Deactivate a user and revoke all access. Provide user ID.\n"
    "- Disable: Temporarily suspend a user account. Provide user ID.\n"
    "- Reinstate: Re-enable a suspended or offboarded user. Provide user ID.\n\n"
    "Bulk Operations\n"
    "- Bulk Onboard: Onboard multiple employees in a single request.\n"
    "- Bulk Offboard: Offboard multiple users by providing a list of user IDs.\n\n"
    "Queries and Reports\n"
    "- Show all users: List all users, optionally filtered by department, role, or status.\n"
    "- Show recent audit logs: View the latest security audit events.\n"
    "- Check permissions: View the active permissions for a specific user ID.\n\n"
    "Policy Management\n"
    "- Create policy: Guided creation of a new IAM policy. You will be asked for name, type, department, description, and VPN profile.\n"
    "- Show all policies: List all existing IAM policies with their details.\n"
    "- Delete policy: Remove a policy by its ID or name.\n"
    "- Update policy: Modify an existing policy. Provide the policy ID and the fields to update.\n\n"
    "Security and Fraud Detection (Admin only)\n"
    "- Show suspicious users: List users with anomalous activity in the last 24 hours.\n"
    "- Why was a user denied: Explain a specific access denial using audit log analysis.\n"
    "- Risk level analysis: Rank users by risk level based on recent access patterns.\n"
    "- Detect fraud: Run a full fraud detection scan over recent audit logs.\n\n"
    "Type 'help' at any time to display this menu again."
)


async def execute_admin_intent(intent_data: dict, db) -> str:
    intent = intent_data.get("intent", "unknown")
    entities = intent_data.get("entities", {})
    missing = intent_data.get("missing_fields", [])
    history = intent_data.get("history", [])

    if intent == "greeting":
        return (
            "Welcome to the IAM Admin Assistant.\n\n"
            "I can help you manage the following:\n"
            "- Employee lifecycle: onboard, transfer, offboard, disable, or reinstate users\n"
            "- Policy management: create, update, delete, or list IAM policies\n"
            "- User queries: search users, check permissions, and review audit logs\n"
            "- Security analysis: detect suspicious activity and explain access decisions\n\n"
            "Type 'help' to view the full command reference."
        )

    if intent == "help":
        return ADMIN_HELP_TEXT

    if intent == "joiner":
        name = entities.get("name") or None
        dept_raw = entities.get("department") or None
        dept = dept_raw.lower().strip() if dept_raw else None
        role = entities.get("role") or None

        dept_list_str = ", ".join(sorted(ALLOWED_DEPARTMENTS))

        # ── Gate 1: Ask for name first, alone ──
        if not name:
            return (
                "Let's onboard a new employee.\n\n"
                "Please provide the employee's **full name**."
            )

        # ── Gate 2: Ask for department next, alone — show allowed list upfront ──
        if not dept:
            return (
                f"Got it — **{name}**.\n\n"
                f"Which **department** will they be joining?\n"
                f"Available departments: **{dept_list_str}**"
            )

        # ── Gate 3: Department allowlist check ──
        if dept not in ALLOWED_DEPARTMENTS:
            return (
                f"⚠️ **'{dept_raw}'** is not a registered department in this system.\n\n"
                f"Currently available departments: **{dept_list_str}**\n\n"
                "Please choose one of the departments listed above, or contact the system administrator to add a new one."
            )

        # ── Gate 4: Ask for role next, alone — with department-specific hints ──
        if not role:
            dept_role_hints = {
                "engineering": "e.g. software_engineer, devops_engineer, qa_engineer",
                "finance": "e.g. financial_analyst, accountant, finance_manager",
                "hr": "e.g. hr_manager, hr_executive, recruiter",
                "sales": "e.g. sales_executive, account_manager, sales_analyst",
                "security": "e.g. security_analyst, security_engineer, soc_lead",
            }
            hint = dept_role_hints.get(dept, "e.g. analyst, manager, executive")
            return (
                f"Great — **{name}** joining **{dept}**.\n\n"
                f"What is their **role** in the organisation?\n"
                f"({hint})"
            )

        # ── Gate 5: Generate or validate user_id ──
        provided_user_id = entities.get("user_id")
        if provided_user_id:
            user_id = provided_user_id
        else:
            user_id = await generate_user_id(db, dept)

        # ── Gate 6: Username uniqueness check ──
        existing_by_id = await db["users"].find_one({"user_id": user_id})
        existing_by_username = await db["users"].find_one({"username": user_id})
        if existing_by_id or existing_by_username:
            base = user_id
            suffix = 2
            while await db["users"].find_one({"$or": [{"user_id": f"{base}_{suffix}"}, {"username": f"{base}_{suffix}"}]}):
                suffix += 1
            suggestion = f"{base}_{suffix}"
            return (
                f"⚠️ Username **{user_id}** is already taken in the directory.\n\n"
                f"Suggested alternative: **{suggestion}**\n\n"
                "Please confirm this suggestion or provide a different unique username to proceed."
            )

        # ── Gate 7: Ask for email if not provided ──
        email = entities.get("email") or None
        if not email:
            return (
                f"Almost done — **{name}** joining **{dept}** as **{role}**.\n\n"
                "Please provide the employee's **email address**."
            )

        # ── Gate 8: Email uniqueness check ──
        existing_email = await db["users"].find_one({"email": email})
        if existing_email:
            parts = email.split("@")
            counter = 2
            while await db["users"].find_one({"email": f"{parts[0]}{counter}@{parts[1]}"}):
                counter += 1
            suggested_email = f"{parts[0]}{counter}@{parts[1]}"
            return (
                f"⚠️ Email **{email}** is already registered in the system.\n\n"
                f"Suggested alternative: **{suggested_email}**\n\n"
                "Please confirm this email or provide a different unique one to proceed."
            )

        # ── All checks passed — create the user ──
        new_user = {
            "user_id": user_id,
            "username": user_id,
            "email": email,
            "full_name": name,
            "department": dept,
            "role": role,
            "status": "inactive",
            "disabled": False,
            "hashed_password": get_password_hash("TempPass@123")
        }
        await db["users"].insert_one(new_user)
        await db["access_states"].insert_one({
            "user_id": user_id,
            "vpn_access": [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": None
        })
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "joiner",
            "target_user": user_id,
            "details": f"{name} ({user_id}) joined the {dept} department as {role}. Email: {email}.",
            "timestamp": datetime.utcnow()
        })
        return (
            f"✅ **{name}** has been successfully onboarded!\n\n"
            f"- **User ID:** {user_id}\n"
            f"- **Department:** {dept}\n"
            f"- **Role:** {role}\n"
            f"- **Email:** {email}\n"
            f"- **Temp Password:** `TempPass@123`\n\n"
            f"Welcome to the team, {name.split()[0]}! 🎉"
        )

    elif intent == "mover":
        user_id = entities.get("user_id") or None
        new_dept_raw = entities.get("department") or entities.get("new_department") or None
        new_dept = new_dept_raw.lower().strip() if new_dept_raw else None
        new_role = entities.get("role") or entities.get("new_role") or None

        dept_list_str = ", ".join(sorted(ALLOWED_DEPARTMENTS))

        # ── Gate 1: Ask for user_id ──
        if not user_id:
            return "I need the **User ID** of the employee to transfer. Please provide it (e.g. U1001)."

        # ── Gate 2: Validate user exists ──
        user = await db["users"].find_one({"user_id": user_id})
        if not user:
            return f"❌ User **{user_id}** not found in the directory."

        # ── Gate 3: Ask for new department ──
        if not new_dept:
            return (
                f"Moving **{user.get('full_name', user_id)}** ({user_id}).\n\n"
                f"Currently in: **{user.get('department', 'unknown')}** as **{user.get('role', 'unknown')}**\n\n"
                f"Which **department** should they move to?\n"
                f"Available departments: **{dept_list_str}**"
            )

        # ── Gate 4: Department allowlist check ──
        if new_dept not in ALLOWED_DEPARTMENTS:
            return (
                f"⚠️ **'{new_dept_raw}'** is not a registered department in this system.\n\n"
                f"Currently available departments: **{dept_list_str}**\n\n"
                "Please choose one of the departments listed above, or contact the system administrator to add a new one."
            )

        # ── Gate 5: Same-department check ──
        current_dept = (user.get("department") or "").lower().strip()
        if new_dept == current_dept:
            return (
                f"⚠️ **{user.get('full_name', user_id)}** ({user_id}) is already in the **{current_dept}** department.\n\n"
                "Please specify a different department to transfer them to."
            )

        # ── Gate 6: Ask for new role explicitly ──
        if not new_role:
            dept_role_hints = {
                "engineering": "e.g. software_engineer, devops_engineer, qa_engineer",
                "finance": "e.g. financial_analyst, accountant, finance_manager",
                "hr": "e.g. hr_manager, hr_executive, recruiter",
                "sales": "e.g. sales_executive, account_manager, sales_analyst",
                "security": "e.g. security_analyst, security_engineer, soc_lead",
            }
            hint = dept_role_hints.get(new_dept, "e.g. analyst, manager, executive")
            return (
                f"Moving **{user.get('full_name', user_id)}** to **{new_dept}**.\n\n"
                f"What will their **new role** be?\n"
                f"({hint})"
            )

        # ── All checks passed — execute transfer ──
        old_dept = user.get('department', 'unknown')
        old_role = user.get('role', 'unknown')

        await db["users"].update_one(
            {"user_id": user_id},
            {"$set": {"department": new_dept, "role": new_role}}
        )
        await db["access_states"].update_one(
            {"user_id": user_id},
            {"$set": {
                "vpn_access": [],
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
                "last_disconnected_at": datetime.utcnow()
            }}
        )
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "mover",
            "target_user": user_id,
            "details": f"{user.get('full_name', user_id)} ({user_id}) transferred from {old_dept} ({old_role}) to {new_dept} ({new_role}). VPN access revoked.",
            "timestamp": datetime.utcnow()
        })
        try:
            await revoke_vpn(user_id=user_id, db=db, admin=True)
        except Exception:
            pass
        return (
            f"✅ **{user.get('full_name', user_id)}** has been successfully transferred!\n\n"
            f"- **From:** {old_dept} ({old_role})\n"
            f"- **To:** {new_dept} ({new_role})\n\n"
            f"⚠️ VPN access has been revoked. User must request access for the new department. 🔄"
        )

    elif intent == "leaver":
        user_id = entities.get("user_id")

        if not user_id:
            return "I need the **User ID** to offboard an employee. Please provide it."

        user = await db["users"].find_one({"user_id": user_id})
        if not user:
            return f"❌ User **{user_id}** not found."

        if user.get("disabled"):
            return f"⚠️ **{user_id}** is already disabled/offboarded."

        await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "inactive", "disabled": True}})
        await db["access_states"].update_one({"user_id": user_id}, {"$set": {
            "vpn_access": [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": datetime.utcnow()
        }})
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "leaver",
            "target_user": user_id,
            "details": f"{user.get('full_name', user_id)} ({user_id}) from {user.get('department', 'unknown')} department ({user.get('role', 'unknown')}) was offboarded. All access revoked and account disabled.",
            "timestamp": datetime.utcnow()
        })
        return (
            f"✅ **{user.get('full_name', user_id)}** has been offboarded.\n\n"
            f"- **Account:** Disabled\n"
            f"- **Access revoked:** all\n\n"
            f"All systems access has been terminated. 🔒"
        )

    elif intent == "disable":
        user_id = entities.get("user_id")

        if not user_id:
            return "I need the **User ID** to disable a user. Please provide it."

        user = await db["users"].find_one({"user_id": user_id})
        if not user:
            return f"❌ User **{user_id}** not found."

        if user.get("disabled"):
            return f"⚠️ **{user_id}** is already disabled."

        await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "inactive", "disabled": True}})
        await db["access_states"].update_one({"user_id": user_id}, {"$set": {
            "vpn_access": [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": datetime.utcnow()
        }})
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "disable_user",
            "target_user": user_id,
            "details": f"{user.get('full_name', user_id)} ({user_id}) from {user.get('department', 'unknown')} department ({user.get('role', 'unknown')}) was temporarily disabled. Account suspended and access blocked.",
            "timestamp": datetime.utcnow()
        })
        return (
            f"✅ **{user.get('full_name', user_id)}** has been disabled.\n\n"
            f"- **Account:** Temporarily suspended\n"
            f"- **Access:** Blocked\n\n"
            f"Use 'reinstate' to re-enable this user later. 🔐"
        )

    elif intent == "reinstate":
        user_id = entities.get("user_id")

        if not user_id:
            return "I need the **User ID** to reinstate an employee."

        user = await db["users"].find_one({"user_id": user_id})
        if not user:
            return f"❌ User **{user_id}** not found."

        if user.get("status") == "active" and not user.get("disabled"):
            return f"⚠️ **{user_id}** is already active."

        await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "inactive", "disabled": False}})
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "reinstate",
            "target_user": user_id,
            "details": f"{user.get('full_name', user_id)} ({user_id}) from {user.get('department', 'unknown')} department ({user.get('role', 'unknown')}) was reinstated. Account re-enabled and set to active.",
            "timestamp": datetime.utcnow()
        })
        return (
            f"✅ **{user.get('full_name', user_id)}** has been reinstated!\n\n"
            f"- **Account:** Active\n"
            f"- **Department:** {user.get('department')}"
        )

    elif intent == "bulk_joiner":
        employees = entities.get("employees", [])
        if not employees:
            return "Please provide the employee details. You can list them or upload a CSV."

        dept_list_str = ", ".join(sorted(ALLOWED_DEPARTMENTS))
        results = []
        for emp in employees:
            dept_raw = emp.get("department", "")
            dept = dept_raw.lower().strip() if dept_raw else ""
            name = emp.get("name", "Unknown")

            # Department allowlist check per employee
            if dept not in ALLOWED_DEPARTMENTS:
                results.append(
                    f"⚠️ {name} — skipped: '{dept_raw}' is not a registered department "
                    f"(allowed: {dept_list_str})"
                )
                continue

            user_id = await generate_user_id(db, dept)
            email = emp.get("email") or f"{name.lower().replace(' ', '.')}@company.com"
            role = emp.get("role") or None

            if not role:
                results.append(f"⚠️ {name} — skipped: role not specified")
                continue

            new_user = {
                "user_id": user_id,
                "username": user_id,
                "email": email,
                "full_name": name,
                "department": dept,
                "role": role,
                "status": "inactive",
                "disabled": False,
    
                "hashed_password": get_password_hash("TempPass@123")
            }
            await db["users"].insert_one(new_user)
            await db["access_states"].insert_one({
                "user_id": user_id,
                "vpn_access": [],
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
                "last_disconnected_at": None
            })
            await db["audit_logs"].insert_one({
                "user_id": "admin",
                "action": "joiner",
                "target_user": user_id,
                "details": f"{name} ({user_id}) joined the {dept} department as {role} via bulk onboarding. Email: {email}.",
                "timestamp": datetime.utcnow()
            })
            results.append(f"✅ {name} ({user_id}) -> {dept}")

        return (
            f"**Bulk Onboarding Complete — {len(employees)} employees**\n\n"
            + "\n".join(results)
        )

    elif intent == "bulk_leaver":
        user_ids = entities.get("user_ids", [])
        if not user_ids:
            return "Please provide the User IDs to offboard (e.g. U1001, U1002, U1003)."

        results = []
        for uid in user_ids:
            user = await db["users"].find_one({"user_id": uid})
            if not user:
                results.append(f"⚠️ {uid} — not found")
                continue
            await db["users"].update_one({"user_id": uid}, {"$set": {"status": "inactive", "disabled": True}})
            await db["access_states"].update_one({"user_id": uid}, {"$set": {
                "vpn_access": [],
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
                "last_disconnected_at": datetime.utcnow()
            }})
            await db["audit_logs"].insert_one({
                "user_id": "admin",
                "action": "leaver",
                "target_user": uid,
                "details": f"{user.get('full_name', uid)} ({uid}) from {user.get('department', 'unknown')} department ({user.get('role', 'unknown')}) was offboarded via bulk operation. All access revoked.",
                "timestamp": datetime.utcnow()
            })
            results.append(f"✅ {uid} — offboarded")

        return (
            f"**Bulk Offboarding Complete — {len(user_ids)} users**\n\n"
            + "\n".join(results)
        )

    elif intent == "query_users":
        filter_by = entities.get("filter")
        value = entities.get("value")

        query = {}
        if filter_by and value:
            query[filter_by] = value

        users = await db["users"].find(query, {"hashed_password": 0}).to_list(length=10)

        if not users:
            return "No users found matching your criteria."

        lines = [f"**Found {len(users)} users:**\n"]
        for u in users:
            status_icon = "🟢" if u.get("status") == "active" else "🔴"
            lines.append(
                f"{status_icon} **{u.get('user_id', 'N/A')}** — {u.get('full_name', '')} | "
                f"{u.get('department', '')} | {u.get('role', '')} | {u.get('status', '')}"
            )

        return "\n".join(lines)

    elif intent == "query_audit":
        filter_by = entities.get("filter")
        value = entities.get("value")

        query = {}
        if filter_by == "user_id" and value:
            query["user_id"] = value
        elif filter_by == "decision" and value:
            query["decision"] = value.upper()

        logs = await db["audit_logs"].find(query).sort("timestamp", -1).to_list(length=10)

        if not logs:
            return "No audit logs found."

        lines = [f"**Last {len(logs)} audit events:**\n"]
        for log in logs:
            icon = {"APPROVE": "✅", "DENY": "❌", "ESCALATE": "⚠️", "REVOKE": "🔒"}.get(
                log.get("decision", ""), "📋"
            )
            lines.append(
                f"{icon} **{log.get('user_id')}** → {log.get('target_user', log.get('target_resource', '-'))} "
                f"| {log.get('action')} | {str(log.get('timestamp', ''))[:10]}"
            )

        return "\n".join(lines)

    elif intent == "query_permissions":
        user_id = entities.get("user_id")
        if not user_id:
            return "Which user's permissions would you like to check? Provide the User ID."

        perms = await db["permissions"].find(
            {"user_id": user_id, "granted": True}
        ).to_list(length=None)

        if not perms:
            return f"**{user_id}** has no active permissions."

        lines = [f"**Active permissions for {user_id}:**\n"]
        for p in perms:
            lines.append(f"✅ {p.get('resource', 'unknown')}")

        return "\n".join(lines)

    elif intent == "create_policy":
        # Deterministic state machine — read what field the bot last asked,
        # use the user's latest reply as the answer to THAT field only.
        # Never rely on the LLM to carry state across turns.

        name = None
        policy_type = None
        description = None
        department = None
        vpn = None
        last_asked = None  # which field did the bot most recently ask for?

        if isinstance(history, list):
            # Find the start of the current policy creation session to avoid leaking past session state
            start_idx = 0
            for i, h in enumerate(history):
                if isinstance(h, dict) and h.get("role") == "assistant" and "Policy created successfully" in h.get("content", ""):
                    start_idx = i + 1
                    
            history_slice = history[start_idx:]

            for h in history_slice:
                if not isinstance(h, dict):
                    continue
                role = h.get("role", "")
                content = h.get("content", "")

                if role == "assistant":
                    # Track what field the bot most recently asked
                    if "Policy Name:" in content and "What should this policy be called" in content:
                        last_asked = "name"
                    elif "Policy Type:" in content and "access" in content and "jml" in content:
                        last_asked = "type"
                    elif "Department:" in content and "department does this policy apply" in content:
                        last_asked = "department"
                    elif "Description:" in content and "brief description" in content:
                        last_asked = "description"
                    elif "VPN Profile:" in content and "vpn_" in content:
                        last_asked = "vpn"

                    # Recover confirmed fields from bot confirmation messages
                    if "Policy name recorded:" in content:
                        name = content.split("Policy name recorded:")[1].split("\n")[0].strip()
                    if "Policy type recorded:" in content:
                        policy_type = content.split("Policy type recorded:")[1].split("\n")[0].strip()
                    if "Department recorded:" in content:
                        department = content.split("Department recorded:")[1].split("\n")[0].strip()
                    if "Description recorded." in content:
                        # Only set placeholder if description hasn't been captured from a user reply yet
                        if not description:
                            description = "__collected__"

                elif role == "user" and last_asked:
                    # Skip if this past user message was a correction command,
                    # not an actual answer to the field question.
                    _HIST_CORRECTION_WORDS = [
                        "change", "go back", "fix", "wrong", "incorrect",
                        "redo", "edit", "no wait", "actually", "mistake", "re-enter",
                    ]
                    _HIST_FIELD_KEYWORDS = [
                        "name", "type", "department", "dept",
                        "description", "desc", "vpn",
                    ]
                    _reply_lower = content.strip().lower()
                    _is_hist_correction = (
                        any(w in _reply_lower for w in _HIST_CORRECTION_WORDS)
                        and any(k in _reply_lower for k in _HIST_FIELD_KEYWORDS)
                    )

                    if not _is_hist_correction:
                        # Normal reply — assign to the field that was last asked by the bot
                        user_reply = content.strip()
                        if last_asked == "name" and not name:
                            name = user_reply
                        elif last_asked == "type" and not policy_type:
                            for t in ["access", "jml", "mfa"]:
                                if t in user_reply.lower():
                                    policy_type = t
                                    break
                        elif last_asked == "department" and not department:
                            department = user_reply
                        elif last_asked == "description" and not description:
                            description = user_reply
                        elif last_asked == "vpn" and not vpn:
                            vpn = user_reply.strip().split()[0]

        # Also grab from LLM entities as fallback (only if not already set from history)
        # To prevent the LLM from hallucinating entities from previous, completed policies
        # in the chat history, we only accept an entity if its value (or a close substring)
        # actually appears in the current user message.
        current_msg_lower = (intent_data.get("current_message") or "").lower()
        
        def is_entity_fresh(val):
            if not val: 
                return False
            val_str = str(val).lower()
            # Type and Department might be normalized by the LLM
            if val_str in ("access", "jml", "mfa"):
                return any(w in current_msg_lower for w in [val_str, "vpn", "joiner", "mover", "leaver", "multi"])
            if val_str in ("engineering", "finance", "hr", "sales", "security"):
                return any(w in current_msg_lower for w in [val_str[:3]]) # generic check for eng, fin, hr, sal, sec
            return val_str in current_msg_lower

        if not name and is_entity_fresh(entities.get("name")):
            name = entities.get("name")
        if not policy_type and is_entity_fresh(entities.get("type")):
            policy_type = entities.get("type")
        if not department and is_entity_fresh(entities.get("department")):
            department = entities.get("department")
        if not description and is_entity_fresh(entities.get("description")):
            description = entities.get("description")
        if not vpn and is_entity_fresh(entities.get("vpn")):
            vpn = entities.get("vpn")

        # Resolve the placeholder
        if description == "__collected__":
            description = None

        # ── Correction handling: applied AFTER full history replay ──
        # Detect if the current user message is trying to change a specific field.
        import re as _re
        current_msg = (intent_data.get("current_message") or "").strip()
        if current_msg:
            msg_lower = current_msg.lower()
            _CORRECTION_WORDS = ["change", "go back", "fix", "wrong", "incorrect", "redo",
                                  "edit", "no wait", "actually", "mistake", "re-enter", "previous", "update"]
            _FIELD_MAP = {
                "name":        ["policy name", "the name", "name"],
                "type":        ["policy type", "the type", "type"],
                "department":  ["department", "dept"],
                "description": ["description", "desc"],
                "vpn":         ["vpn profile", "vpn"],
            }
            
            is_correction = any(w in msg_lower for w in _CORRECTION_WORDS)
            
            target_field = None
            if is_correction:
                for field, keywords in _FIELD_MAP.items():
                    if any(kw in msg_lower for kw in keywords):
                        target_field = field
                        break
            
            is_generic_back = msg_lower in ["go back", "wait", "no wait", "wrong", "that's wrong", "mistake", "redo", "fix"]
            
            if target_field or is_generic_back:
                # 1. Reverse the mistaken assignment from the history loop
                # This ensures the bot actually re-asks for the current field instead of saving the correction text
                if last_asked == "name" and name == current_msg: name = None
                elif last_asked == "department" and department == current_msg: department = None
                elif last_asked == "description" and description == current_msg: description = None
                elif last_asked == "vpn" and vpn == current_msg.split()[0]: vpn = None

                # 2. Apply the correction to the target field
                if target_field:
                    new_val_match = _re.search(
                        r'(?:to|as|=)\s+["\']?(.+?)["\']?\s*$', current_msg, _re.IGNORECASE
                    )
                    new_val = new_val_match.group(1).strip() if new_val_match else None

                    # Apply: set the target field to new_val (or clear it if new_val is not found)
                    if target_field == "name":
                        name = new_val if new_val else None
                    elif target_field == "type":
                        if new_val:
                            policy_type = None
                            for t in ["access", "jml", "mfa"]:
                                if t in new_val.lower():
                                    policy_type = t
                                    break
                        else:
                            policy_type = None
                    elif target_field == "department":
                        department = new_val if new_val else None
                    elif target_field == "description":
                        description = new_val if new_val else None
                    elif target_field == "vpn":
                        vpn = new_val.split()[0] if new_val else None

        # Gate: ask ONE field at a time in order
        # IMPORTANT: every gate response echoes ALL previously confirmed fields.
        # This ensures corrections survive across turns — the latest bot message
        # always carries the full authoritative state for history replay.
        if not name:
            return (
                "Policy creation initiated. Please provide the required details one step at a time.\n\n"
                "Policy Name: What should this policy be called?"
            )

        if not policy_type or policy_type not in ("jml", "access", "mfa"):
            return (
                f"Policy name recorded: {name}\n\n"
                "Policy Type: Select one of the following:\n"
                "- access: Controls VPN and resource access permissions\n"
                "- jml: Governs Joiner, Mover, and Leaver workflows\n"
                "- mfa: Enforces Multi-Factor Authentication\n\n"
                "Please respond with: access, jml, or mfa"
            )

        if not department:
            return (
                f"Policy name recorded: {name}\n"
                f"Policy type recorded: {policy_type}\n\n"
                "Department: Which department does this policy apply to?\n"
                f"Available: {', '.join(sorted(ALLOWED_DEPARTMENTS))}"
            )

        if not description:
            return (
                f"Policy name recorded: {name}\n"
                f"Policy type recorded: {policy_type}\n"
                f"Department recorded: {department}\n\n"
                "Description: Provide a brief description of what this policy enforces."
            )

        if not vpn:
            return (
                f"Policy name recorded: {name}\n"
                f"Policy type recorded: {policy_type}\n"
                f"Department recorded: {department}\n"
                f"Description recorded.\n\n"
                "VPN Profile: Specify the VPN profile identifier for this policy.\n"
                "Common profiles: vpn_hr, vpn_fin, vpn_eng, vpn_sec, vpn_admin"
            )

        # All 5 fields collected — create the policy
        is_active = entities.get("is_active", True)
        policy_id = f"POL-{str(uuid.uuid4())[:8].upper()}"
        now = datetime.utcnow()
        doc = {
            "pol_id": policy_id,
            "name": name,
            "type": policy_type,
            "description": description,
            "department": department,
            "vpn": vpn,
            "is_active": is_active,
            "created_on": now,
            "updated_on": now,
        }
        await db["policies"].insert_one(doc)
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "create_policy",
            "target_resource": policy_id,
            "details": f"Admin created policy '{name}' (type: {policy_type}) for {department} department with VPN profile {vpn}.",
            "timestamp": now,
        })
        return (
            f"\u2705 **Policy created successfully!**\n\n"
            f"- **Policy ID:** {policy_id}\n"
            f"- **Name:** {name}\n"
            f"- **Type:** {policy_type}\n"
            f"- **Department:** {department}\n"
            f"- **Description:** {description}\n"
            f"- **VPN Profile:** {vpn}\n"
            f"- **Status:** {'Active' if is_active else 'Inactive'}"
        )

    elif intent == "list_policies":
        filter_by = entities.get("filter")
        value = entities.get("value")
        query = {}
        if filter_by and value:
            # Use case-insensitive regex so "HR", "hr", "Finance" all match
            query[filter_by] = {"$regex": f"^{value}$", "$options": "i"}
        policies = await db["policies"].find(query).to_list(length=50)
        if not policies:
            filter_msg = f" for **{value}**" if value else ""
            return f"No policies found{filter_msg}."
        filter_label = f" (filtered by {filter_by}: {value})" if filter_by and value else ""
        lines = [f"**{len(policies)} IAM Policies{filter_label}:**\n"]
        for p in policies:
            active_icon = "🟢" if p.get("is_active") else "🔴"
            lines.append(
                f"{active_icon} **{p.get('pol_id', 'N/A')}** — {p.get('name', 'Unnamed')} "
                f"| Type: {p.get('type', '-')} | Dept: {p.get('department', '-')} | VPN: {p.get('vpn', '-')}"
            )
        return "\n".join(lines)

    elif intent == "explain_policy":
        policy_id = entities.get("policy_id")
        name_hint = entities.get("name")

        policy = None
        if policy_id:
            policy = await db["policies"].find_one({"pol_id": policy_id})
        if not policy and name_hint:
            policy = await db["policies"].find_one({"name": {"$regex": name_hint, "$options": "i"}})

        if not policy:
            if name_hint or policy_id:
                return f"❌ No policy found matching **'{name_hint or policy_id}'**. Please check the name or ID and try again."
            return "Which policy would you like me to explain? Please provide the **policy name** or **Policy ID** (e.g. POL-XXXXXXXX)."

        type_descriptions = {
            "access": "controls VPN and resource access permissions for the department",
            "jml": "governs Joiner, Mover, and Leaver workflows for employee lifecycle management",
            "mfa": "enforces Multi-Factor Authentication requirements for users in the department",
        }
        type_desc = type_descriptions.get(policy.get("type", ""), "defines access rules")
        status = "Active" if policy.get("is_active") else "Inactive"

        return (
            f"📋 **Policy Explanation — {policy.get('name', 'Unnamed')}**\n\n"
            f"- **Policy ID:** {policy.get('pol_id', 'N/A')}\n"
            f"- **Type:** {policy.get('type', '-')} — this policy {type_desc}\n"
            f"- **Department:** {policy.get('department', '-')}\n"
            f"- **VPN Profile:** {policy.get('vpn', '-')}\n"
            f"- **Status:** {status}\n\n"
            f"**Description:**\n{policy.get('description', 'No description provided.')}"
        )

    elif intent == "delete_policy":
        policy_id = entities.get("policy_id")
        name_hint = entities.get("name")
        if not policy_id and name_hint:
            found = await db["policies"].find_one({"name": {"$regex": name_hint, "$options": "i"}})
            if found:
                policy_id = found["pol_id"]
        if not policy_id:
            return "Please provide the **Policy ID** (e.g. POL-XXXXXXXX) or the exact policy name to delete."
        policy = await db["policies"].find_one({"pol_id": policy_id})
        if not policy:
            return f"❌ Policy **{policy_id}** not found."
        await db["policies"].delete_one({"pol_id": policy_id})
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "delete_policy",
            "target_resource": policy_id,
            "details": f"Admin deleted policy '{policy.get('name', policy_id)}' (type: {policy.get('type', '-')}) for {policy.get('department', '-')} department.",
            "timestamp": datetime.utcnow(),
        })
        return f"✅ Policy **{policy.get('name', policy_id)}** ({policy_id}) has been deleted."

    elif intent == "update_policy":
        policy_id = entities.get("policy_id")
        name_hint = entities.get("name")
        if not policy_id and name_hint:
            found = await db["policies"].find_one({"name": {"$regex": name_hint, "$options": "i"}})
            if found:
                policy_id = found["pol_id"]
        if not policy_id:
            return "Please provide the **Policy ID** (e.g. POL-XXXXXXXX) or policy name to update."
        existing = await db["policies"].find_one({"pol_id": policy_id})
        if not existing:
            return f"❌ Policy **{policy_id}** not found."
        updates = {"updated_on": datetime.utcnow()}
        for field in ("name", "type", "description", "department", "vpn", "is_active"):
            val = entities.get(field)
            if val is not None:
                if field == "type" and val not in ("jml", "access", "mfa"):
                    continue
                updates[field] = val
        await db["policies"].update_one({"pol_id": policy_id}, {"$set": updates})
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "update_policy",
            "target_resource": policy_id,
            "details": f"Admin updated policy '{existing.get('name', policy_id)}' — changes: {list(updates.keys())}.",
            "timestamp": datetime.utcnow(),
        })
        updated = {**existing, **updates}
        return (
            f"✅ **Policy updated successfully!**\n\n"
            f"- **Policy ID:** {policy_id}\n"
            f"- **Name:** {updated.get('name')}\n"
            f"- **Type:** {updated.get('type')}\n"
            f"- **Department:** {updated.get('department')}\n"
            f"- **VPN Profile:** {updated.get('vpn')}\n"
            f"- **Status:** {'Active' if updated.get('is_active') else 'Inactive'}"
        )

    elif intent == "general_query":
        return await _handle_general_query(entities, db)

    elif intent == "dangerous_action":
        return "🚫 Sorry, I cannot do that. Please contact the system administrator directly."

    else:
        return ADMIN_HELP_TEXT


# ─── general_query handler (DB-backed factual answers) ───────────────────────
async def _handle_general_query(entities: dict, db) -> str:
    sub_type = (entities.get("sub_type") or "").lower()
    dept_filter = entities.get("filter") or None

    if sub_type == "departments":
        dept_list = ", ".join(sorted(ALLOWED_DEPARTMENTS))
        return f"**Registered Departments:**\n{dept_list}"

    if sub_type == "users":
        query = {}
        if dept_filter:
            query["department"] = {"$regex": f"^{dept_filter}$", "$options": "i"}
        users = await db["users"].find(query, {"hashed_password": 0}).to_list(length=30)
        if not users:
            label = f" in **{dept_filter}**" if dept_filter else ""
            return f"No users found{label}."
        label = f" in **{dept_filter}**" if dept_filter else ""
        lines = [f"**{len(users)} Users{label}:**\n"]
        for u in users:
            icon = "🟢" if u.get("status") == "active" else "🔴"
            lines.append(
                f"{icon} **{u.get('user_id')}** — {u.get('full_name', '-')} "
                f"| {u.get('department', '-')} | {u.get('role', '-')} | {u.get('status', '-')}"
            )
        return "\n".join(lines)

    if sub_type == "stats":
        total = await db["users"].count_documents({})
        active = await db["users"].count_documents({"status": "active"})
        inactive = total - active
        policies = await db["policies"].count_documents({})
        return (
            f"**📊 System Overview:**\n\n"
            f"- Total Users: **{total}**\n"
            f"- Active Users: **{active}**\n"
            f"- Inactive Users: **{inactive}**\n"
            f"- Total Policies: **{policies}**"
        )

    if sub_type == "vpn":
        pools = await db["vpn_pools"].find({}).to_list(length=30)
        if not pools:
            return "No VPN pools configured."
        lines = ["**Available VPN Pools:**\n"]
        for p in pools:
            lines.append(
                f"- **{p.get('pool_id', '-')}** | Dept: {p.get('department', '-')} "
                f"| Max connections: {p.get('max_connections', '-')}"
            )
        return "\n".join(lines)

    if sub_type == "portal_info":
        return (
            "**🛡️ IAM — Identity and Access Management Portal**\n\n"
            "This portal provides end-to-end employee lifecycle and access management:\n\n"
            "- 👥 **Joiner / Mover / Leaver** — onboard, transfer, and offboard employees\n"
            "- 🔐 **VPN Access Control** — request, grant, and revoke network access\n"
            "- 📌 **Policy Management** — define and enforce access policies per department\n"
            "- 📊 **Audit & Security** — monitor access events and detect anomalies\n\n"
            "Admins manage the full system. Users self-serve for their own access needs."
        )

    # Fallback for unrecognised sub_type
    return (
        "I can answer questions about:\n"
        "- **departments** — list registered departments\n"
        "- **users** — show users (optionally filtered by department)\n"
        "- **stats** — system overview\n"
        "- **VPN pools** — available VPN profiles\n"
        "- **portal info** — what this system does\n\n"
        "What would you like to know?"
    )


async def admin_chat(user_message: str, history: list, db, user_role: str = "admin") -> tuple:

    # ── Trim history at last completed policy to prevent LLM entity leakage ──
    fresh_history = history
    if isinstance(history, list):
        for i, h in enumerate(history):
            if isinstance(h, dict) and h.get("role") == "assistant" and "Policy created successfully" in h.get("content", ""):
                fresh_history = history[i + 1:]

    # ── Intent Lock: detect active multi-step policy creation ─────────────────
    _POLICY_QUESTIONS = [
        "Policy Name: What should this policy be called",
        "Policy Type: Select one of the following",
        "Department: Which department does this policy apply",
        "Description: Provide a brief description",
        "VPN Profile: Specify the VPN profile",
    ]
    _in_policy_form = False
    if isinstance(history, list):
        for h in reversed(history):
            if isinstance(h, dict) and h.get("role") == "assistant":
                last_bot = h.get("content", "")
                if any(q in last_bot for q in _POLICY_QUESTIONS):
                    _in_policy_form = True
                break  # only check the most recent bot message

    if _in_policy_form:
        # Escape hatch: check if the user is asking a question OR trying to run a totally different command
        msg_lower = user_message.lower().strip()
        _QUESTION_INDICATORS = ["what", "how", "who", "which", "list", "show", "count",
                                 "how many", "tell me", "explain", "?", "describe"]
        _ACTION_INDICATORS = ["cancel", "abort", "exit", "quit", "stop",
                              "create ", "delete ", "update ", "remove ", "onboard ", 
                              "offboard ", "transfer ", "disable ", "reinstate ", "help"]
        
        _might_be_question = any(ind in msg_lower for ind in _QUESTION_INDICATORS)
        _might_be_action = any(msg_lower.startswith(ind) or msg_lower == ind.strip() for ind in _ACTION_INDICATORS)

        if _might_be_question or _might_be_action:
            # Let the LLM classify this message using clean history
            q_intent_data = await extract_admin_intent(user_message, fresh_history)
            q_intent = q_intent_data.get("intent", "unknown")
            
            # If the LLM successfully classified it as a DIFFERENT defined intent:
            if q_intent not in ("create_policy", "unknown"):
                q_intent_data["history"] = history
                answer = await execute_admin_intent(q_intent_data, db)
                
                # If it was an action intent, we fully abort the form creation
                _ACTION_INTENTS = {"joiner", "mover", "leaver", "disable", "reinstate", "bulk_joiner", "bulk_leaver", "delete_policy", "update_policy"}
                if q_intent in _ACTION_INTENTS or msg_lower in ("cancel", "abort", "exit", "quit", "stop"):
                    return answer + "\n\n❌ *Previous policy creation aborted.*", q_intent_data
                else:
                    # It was a query/read-only intent — pause and resume the form
                    return answer + "\n\n---\n📝 *Resuming policy creation — please answer the previous question to continue.*", q_intent_data

        # Normal policy form path (user is just answering the form question)
        intent_data = {
            "intent": "create_policy",
            "entities": {},
            "missing_fields": [],
            "history": history,
            "current_message": user_message,
        }
        response = await execute_admin_intent(intent_data, db)
        return response, intent_data
    # ─────────────────────────────────────────────────────────────────────────

    intent_data = await extract_admin_intent(user_message, fresh_history)
    intent_data["history"] = history  # full history still goes to the state machine
    intent = intent_data.get("intent", "unknown")

    # Route RAG/fraud queries directly to the RAG engine unless user is HR
    if intent == "rag_query":
        if "hr" in user_role.lower():
            return "Access Denied: Fraud detection and log analysis tools are restricted to Security Admins only.", intent_data
        response = await rag_answer(user_message, db)
        return response, intent_data

    response = await execute_admin_intent(intent_data, db)
    return response, intent_data
