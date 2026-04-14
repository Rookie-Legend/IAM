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
- list_policies:  show/list all existing policies
- delete_policy:  delete a policy by name or ID
- update_policy:  update/edit an existing policy
- unknown:        cannot determine intent

Always respond with valid JSON only. No text outside JSON.

For joiner — REQUIRED fields: name, department. OPTIONAL: user_id, email (auto-generated if absent), role (guess from dept):
{
    "intent": "joiner",
    "entities": {
        "user_id":    "U1001 or null if not given",
        "name":       "full name or null",
        "email":      "email or null",
        "department": "engineering/finance/hr/product or null",
        "role":       "exact role or best guess or null"
    },
    "missing_fields": ["ONLY list name and/or department if they are truly absent — NEVER list user_id or email"],
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

For mover:
{
    "intent": "mover",
    "entities": {"user_id": "U1001", "department": "finance", "role": "analyst"},
    "missing_fields": ["user_id if missing", "department if missing"],
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

For list_policies:
{"intent": "list_policies", "entities": {"filter": "type/department/name or null", "value": "filter value or null"}, "confidence": "HIGH", "message": ""}

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
        if missing and any(f in missing for f in ["name", "department"]):
            return f"I need a few more details to onboard this employee. Missing: **{', '.join(missing)}**. Can you provide them?"

        dept = entities.get("department", "engineering")
        user_id = entities.get("user_id") or await generate_user_id(db, dept)
        name = entities.get("name", "Unknown")
        email = entities.get("email") or f"{name.lower().replace(' ', '.')}@company.com"
        role = entities.get("role", "software_engineer")

        existing = await db["users"].find_one({"user_id": user_id})
        if existing:
            return f"⚠️ User **{user_id}** already exists in the directory."

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
        user_id = entities.get("user_id")
        new_dept = entities.get("department") or entities.get("new_department")
        new_role = entities.get("role") or entities.get("new_role")

        if not user_id:
            return "I need the **User ID** to move an employee. Please provide it (e.g. U1001)."
        if not new_dept:
            return "Which **department** should I move this employee to?"

        user = await db["users"].find_one({"user_id": user_id})
        if not user:
            return f"❌ User **{user_id}** not found in the directory."

        await db["users"].update_one(
            {"user_id": user_id},
            {"$set": {"department": new_dept, "role": new_role or user.get("role", "software_engineer")}}
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
        old_dept = user.get('department', 'unknown')
        old_role = user.get('role', 'unknown')
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "mover",
            "target_user": user_id,
            "details": f"{user.get('full_name', user_id)} ({user_id}) transferred from {old_dept} ({old_role}) to {new_dept} ({new_role or old_role}). VPN access revoked.",
            "timestamp": datetime.utcnow()
        })
        try:
            await revoke_vpn(user_id=user_id, db=db, admin=True)
        except Exception:
            pass
        return (
            f"✅ **{user_id}** has been successfully transferred!\n\n"
            f"- **New Department:** {new_dept}\n"
            f"- **New Role:** {new_role or user.get('role')}\n\n"
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

        results = []
        for emp in employees:
            dept = emp.get("department", "engineering")
            user_id = await generate_user_id(db, dept)
            name = emp.get("name", "Unknown")
            email = emp.get("email") or f"{name.lower().replace(' ', '.')}@company.com"
            role = emp.get("role", "software_engineer")

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
            for h in history:
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
                    # The user's reply answers whatever was last asked
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
                        vpn = user_reply.strip().split()[0]  # take first word e.g. "vpn_eng"

        # Also grab from LLM entities as fallback (only if not already set from history)
        if not name:
            name = entities.get("name")
        if not policy_type:
            policy_type = entities.get("type")
        if not department:
            department = entities.get("department")
        if not description:
            description = entities.get("description")
        if not vpn:
            vpn = entities.get("vpn")

        # Resolve the placeholder
        if description == "__collected__":
            description = None  # fall through to ask again if user message wasn't captured

        # Gate: ask ONE field at a time in order
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
                f"Policy type recorded: {policy_type}\n\n"
                "Department: Which department does this policy apply to?"
            )

        if not description:
            return (
                f"Department recorded: {department}\n\n"
                "Description: Provide a brief description of what this policy enforces."
            )

        if not vpn:
            return (
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
            query[filter_by] = value
        policies = await db["policies"].find(query).to_list(length=50)
        if not policies:
            return "No policies found."
        lines = [f"**{len(policies)} IAM Policies:**\n"]
        for p in policies:
            active_icon = "🟢" if p.get("is_active") else "🔴"
            lines.append(
                f"{active_icon} **{p.get('pol_id', 'N/A')}** — {p.get('name', 'Unnamed')} "
                f"| Type: {p.get('type', '-')} | Dept: {p.get('department', '-')} | VPN: {p.get('vpn', '-')}"
            )
        return "\n".join(lines)

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

    else:
        return ADMIN_HELP_TEXT


async def admin_chat(user_message: str, history: list, db, user_role: str = "admin") -> tuple:

    # ── Intent Lock: detect active multi-step policy creation ─────────────────
    # If the last bot message was a create_policy question, force the intent
    # directly instead of letting the LLM reclassify the user's free-text reply.
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
        # Skip LLM extraction — user is answering a policy creation step
        intent_data = {"intent": "create_policy", "entities": {}, "missing_fields": [], "history": history}
        response = await execute_admin_intent(intent_data, db)
        return response, intent_data
    # ─────────────────────────────────────────────────────────────────────────

    intent_data = await extract_admin_intent(user_message, history)
    intent_data["history"] = history  # make history available to execute_admin_intent
    intent = intent_data.get("intent", "unknown")

    # Route RAG/fraud queries directly to the RAG engine unless user is HR
    if intent == "rag_query":
        if "hr" in user_role.lower():
            return "Access Denied: Fraud detection and log analysis tools are restricted to Security Admins only.", intent_data
        response = await rag_answer(user_message, db)
        return response, intent_data

    response = await execute_admin_intent(intent_data, db)
    return response, intent_data
