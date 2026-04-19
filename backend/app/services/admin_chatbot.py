import json
import uuid
import random
import string
import httpx
from datetime import datetime, timedelta
from groq import Groq
from app.core.config import settings
from app.core.security import get_password_hash
from app.api.vpn import revoke_vpn
from app.rag.rag_engine import rag_answer
from app.services.email_service import send_email
from app.services.gitlab_sync import DEFAULT_GITLAB_TEMP_PASSWORD, block_gitlab_user, ensure_gitlab_user, unblock_gitlab_user

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


async def extract_admin_intent(user_message: str, history: list, forced_intent: str = None) -> dict:
    forced_rule = ""
    if forced_intent:
        forced_rule = f"\nCRITICAL: The conversation is locked to the '{forced_intent}' intent. You MUST output intent='{forced_intent}' and extract all accumulated entities from the history and the latest message. DO NOT output 'unknown'.\n"

    system_prompt = forced_rule + """
You are an IAM system assistant. Extract the intent and entities from admin messages.

CRITICAL — CONVERSATION CONTEXT & CONTINUITY:
- Always read the full conversation history.
- If the previous assistant message asked for more details, treat the user's reply as a FOLLOW-UP for that SAME intent. Do NOT switch intents.
- For multi-step forms (joiner, invite_joiner, mover, create_policy), you MUST preserve fields collected in previous turns!
- If the chat history shows the bot already confirmed a value (e.g. "Got it — John Doe", "Invite email recorded: X", "Policy name recorded: Y"), you MUST output that exact value in your JSON entities. DO NOT DROP IT.
- NEVER extract entities (like roles or departments) from the bot's own confirmation messages. Only extract what the user explicitly provided.
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
- joiner:         onboard a new employee by entering all their details directly into the system
- invite_joiner:  send a registration invite email to a new joiner so they can self-register (use when user says "send invite", "email invite", "invite via email", "send registration link")
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

For invite_joiner — REQUIRED fields: email, role, department. The admin provides these and the system emails a registration link to the new joiner.
NEVER guess or infer role from department. ONLY set role if the user explicitly stated it.
Only accept department values from: engineering, finance, hr, sales, security.
{
    "intent": "invite_joiner",
    "entities": {
        "email":      "email ONLY if explicitly given by user, else null",
        "department": "engineering/finance/hr/sales/security or null",
        "role":       "exact role ONLY if explicitly stated by user, else null"
    },
    "missing_fields": ["email", "role", "department" — list whichever are absent],
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

For queries (user lookup / info retrieval):
{
    "intent": "query_users",
    "entities": {
        "filter": "One of: name | user_id | username | department | role | status | null",
        "value":  "The search value — e.g. 'Swaathi B', 'U1004', 'engineering', 'active' — or null",
        "lookup": "What specific info the user wants about the matched user(s): user_id | department | role | status | null (null = just list the users)"
    },
    "confidence": "HIGH",
    "message": "what you understood"
}
Examples:
- "give user id of Swaathi B"         -> filter: name,       value: "Swaathi B",   lookup: user_id
- "what department is U1004 in"        -> filter: user_id,    value: "U1004",       lookup: department
- "what is the role of swaathi b"      -> filter: name,       value: "Swaathi B",   lookup: role
- "show all users in engineering"      -> filter: department, value: "engineering", lookup: null
- "show active users"                  -> filter: status,     value: "active",      lookup: null
- "what is the department of H1002"    -> filter: user_id,    value: "H1002",       lookup: department
- "give department of swaathi"         -> filter: name,       value: "swaathi",     lookup: department

Role mapping guide (ONLY apply if the user is answering a question about their role, or explicitly states their role. DO NOT map names to roles if the bot just asked for a name!):
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
    "- Join (Direct): Onboard a new employee immediately. Provide name, email, department, and role.\n"
    "- Join (Invite): Send a registration invite email to a new joiner. Say 'send invite' or 'invite via email'.\n"
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
    "- Check permissions: View the active permissions for a specific user ID.\n"
    "- General info: Ask factual questions about system stats, available VPNs, or departments.\n\n"
    "Policy Management\n"
    "- Create policy: Guided creation of a new IAM policy. You will be asked for name, type, department, description, and VPN profile.\n"
    "- Show all policies: List all existing IAM policies with their details.\n"
    "- Explain policy: Understand what a specific policy does by providing its name or ID.\n"
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

        # ── Gate 1: Show 2-option menu on fresh request; ask name after choice ──
        if not name:
            _menu_shown = False
            if isinstance(history, list):
                join_start = 0
                for i, h in enumerate(history):
                    _hc = h.get("text") or h.get("content") or ""
                    if isinstance(h, dict) and h.get("role") in ("assistant", "bot") and "has been successfully onboarded!" in _hc:
                        join_start = i + 1
                
                history_slice = history[join_start:]
                for _h in history_slice:
                    _hc2 = _h.get("text") or _h.get("content") or ""
                    if isinstance(_h, dict) and _h.get("role") in ("assistant", "bot") and "Reply with **1** to onboard directly" in _hc2:
                        _menu_shown = True
                        break
            if not _menu_shown:
                return (
                    "To onboard a new joiner, how would you like to proceed?\n\n"
                    "**1️⃣ Onboard directly** — Enter all details (name, email, department, role) and create the account immediately.\n"
                    "**2️⃣ Send invite via email** — Provide email, department and role. The joiner receives a registration link to self-register.\n\n"
                    "Reply with **1** to onboard directly, or **2** to send an invite email."
                )
            # Menu was shown and user chose 1 \u2014 now collect name
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

        # ── Gate 5: Generate internal user_id and validate username ──
        provided_user_id = entities.get("user_id")
        user_id = await generate_user_id(db, dept)
        username = provided_user_id or user_id

        # ── Gate 6: Username uniqueness check ──
        existing_by_id = await db["users"].find_one({"user_id": user_id})
        existing_by_username = await db["users"].find_one({"username": username})
        if existing_by_id or existing_by_username:
            base = username
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
            "username": username,
            "email": email,
            "full_name": name,
            "department": dept,
            "role": role,
            "status": "inactive",
            "disabled": False,
            "hashed_password": get_password_hash(DEFAULT_GITLAB_TEMP_PASSWORD)
        }
        await db["users"].insert_one(new_user)
        gitlab_sync = await ensure_gitlab_user(new_user, DEFAULT_GITLAB_TEMP_PASSWORD)
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
            f"- **Username:** {username}\n"
            f"- **GitLab sync:** {gitlab_sync.status}\n"
            f"- **Department:** {dept}\n"
            f"- **Role:** {role}\n"
            f"- **Email:** {email}\n"
            f"- **Temp Password:** `{DEFAULT_GITLAB_TEMP_PASSWORD}`\n\n"
            f"Welcome to the team, {name.split()[0]}! 🎉"
        )

    elif intent == "invite_joiner":
        # ── State machine: email → department → role ──
        # History is replayed using STRUCTURAL confirmation markers (not question text)
        # to avoid fragile substring matches on markdown-formatted strings like **role**.

        inv_email = None
        inv_dept = None
        inv_role = None
        inv_last_asked = None

        if isinstance(history, list):
            # Find start of current invite session (restart after last completed invite)
            inv_start = 0
            for i, h in enumerate(history):
                _ic = h.get("text") or h.get("content") or ""
                if isinstance(h, dict) and h.get("role") in ("assistant", "bot") and "Invitation sent successfully" in _ic:
                    inv_start = i + 1
            history_slice = history[inv_start:]
            
            # include the current message so the loop can extract the latest answer
            if isinstance(intent_data, dict) and intent_data.get("current_message"):
                history_slice = history_slice + [{"role": "user", "content": intent_data["current_message"]}]

            for h in history_slice:
                if not isinstance(h, dict):
                    continue
                role_h = h.get("role", "")
                content_h = h.get("text") or h.get("content") or ""

                if role_h in ("assistant", "bot"):
                    # ── Extract already-confirmed values from bot confirmation lines ──
                    # NOTE: use "Invite "-prefixed markers to avoid matching the policy wizard's
                    # "Policy department recorded:" (which would contain "Department recorded:" as a substring).
                    if "Invite email recorded:" in content_h:
                        inv_email = content_h.split("Invite email recorded:")[1].split("\n")[0].strip()
                    if "Invite department recorded:" in content_h:
                        inv_dept = content_h.split("Invite department recorded:")[1].split("\n")[0].strip()
                    if "Invite role recorded:" in content_h:
                        inv_role = content_h.split("Invite role recorded:")[1].split("\n")[0].strip()

                    # ── Determine which field the bot was asking for ──
                    # Use structural presence of confirmation lines, NOT the question text,
                    # so markdown asterisks like **role** never cause a mismatch.
                    if "invite email address" in content_h.lower():
                        inv_last_asked = "email"
                    elif "Invite email recorded:" in content_h and "Invite department recorded:" not in content_h:
                        # Bot confirmed email but not dept yet — it was asking for dept
                        inv_last_asked = "department"
                    elif "Invite department recorded:" in content_h and "Invite role recorded:" not in content_h:
                        # Bot confirmed dept but not role yet — it was asking for role
                        inv_last_asked = "role"

                elif role_h in ("user",) and inv_last_asked:
                    user_reply = content_h.strip()
                    if inv_last_asked == "email" and not inv_email:
                        inv_email = user_reply
                    elif inv_last_asked == "department" and not inv_dept:
                        inv_dept = user_reply.lower().strip()
                    elif inv_last_asked == "role" and not inv_role:
                        inv_role = user_reply

        # Fallback: use LLM entities for first-turn single-shot inputs
        if not inv_email and entities.get("email"):
            inv_email = entities["email"]
        if not inv_dept and entities.get("department"):
            inv_dept = (entities["department"] or "").lower().strip()
        if not inv_role and entities.get("role"):
            inv_role = entities["role"]

        dept_list_str = ", ".join(sorted(ALLOWED_DEPARTMENTS))

        # ── Gate 1: Email ──
        if not inv_email:
            return (
                "I'll send a registration invite email to the new joiner.\n\n"
                "What is their **invite email address**?"
            )

        # ── Gate 2: Department ──
        if not inv_dept:
            return (
                f"Invite email recorded: {inv_email}\n\n"
                f"Which **department** are they joining?\n"
                f"Available: **{dept_list_str}**"
            )

        # ── Gate 3: Department allowlist check ──
        if inv_dept not in ALLOWED_DEPARTMENTS:
            return (
                f"Invite email recorded: {inv_email}\n\n"
                f"\u26a0\ufe0f **'{inv_dept}'** is not a registered department.\n\n"
                f"Available departments: **{dept_list_str}**\n\n"
                "Please choose one of the departments listed above."
            )

        # ── Gate 4: Role (with department-specific hints) ──
        if not inv_role:
            _dept_role_hints = {
                "engineering": "e.g. software_engineer, devops_engineer, qa_engineer",
                "finance":     "e.g. financial_analyst, accountant, finance_manager",
                "hr":          "e.g. hr_manager, hr_executive, recruiter",
                "sales":       "e.g. sales_executive, account_manager, sales_analyst",
                "security":    "e.g. security_analyst, security_engineer, soc_lead",
            }
            _hint = _dept_role_hints.get(inv_dept, "e.g. analyst, manager, executive")
            return (
                f"Invite email recorded: {inv_email}\n"
                f"Invite department recorded: {inv_dept}\n\n"
                f"What **role** will they be joining as?\n"
                f"({_hint})"
            )

        # ── All fields collected — run invite logic ──
        # Check if user already exists
        existing_user = await db["users"].find_one({"email": inv_email})
        if existing_user:
            return (
                f"⚠️ A user with email **{inv_email}** already exists in the system.\n\n"
                "No invite was sent. If this is a different person, please use a different email address."
            )

        # Expire any existing pending invite for this email
        existing_invite = await db["invites"].find_one({"email": inv_email, "status": "pending"})
        if existing_invite:
            await db["invites"].update_one({"email": inv_email}, {"$set": {"status": "expired"}})

        # Generate invite token and store
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        invite_doc = {
            "email": inv_email,
            "role": inv_role,
            "department": inv_dept,
            "token": token,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=3),
            "created_by": "admin"
        }
        await db["invites"].insert_one(invite_doc)

        # Send email
        login_link = f"{settings.FRONTEND_URL}/login?invite=true&token={token}"
        try:
            await send_email(
                inv_email,
                "Welcome to CorpOD - Complete Your Registration",
                "invite_email.html",
                {"ROLE": inv_role, "DEPARTMENT": inv_dept, "LOGIN_LINK": login_link}
            )
        except Exception as e:
            # Rollback the invite if email fails
            await db["invites"].delete_one({"token": token})
            return (
                f"❌ Failed to send invite email to **{inv_email}**.\n\n"
                f"Error: {str(e)}\n\n"
                "Please check the email configuration and try again."
            )

        # Audit log
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "invite",
            "target_user": inv_email,
            "details": f"Admin sent registration invite to {inv_email} for role {inv_role} in {inv_dept} department.",
            "timestamp": datetime.utcnow()
        })

        return (
            f"✅ **Invitation sent successfully!**\n\n"
            f"- **To:** {inv_email}\n"
            f"- **Role:** {inv_role}\n"
            f"- **Department:** {inv_dept}\n"
            f"- **Expires in:** 3 days\n\n"
            f"The new joiner will receive a registration link at **{inv_email}** to complete their account setup. 📧"
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
        gitlab_sync = await block_gitlab_user(user)
        return (
            f"✅ **{user.get('full_name', user_id)}** has been offboarded.\n\n"
            f"- **Account:** Disabled\n"
            f"- **Access revoked:** all\n\n"
            f"- **GitLab sync:** {gitlab_sync.status}\n\n"
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
        gitlab_sync = await block_gitlab_user(user)
        return (
            f"✅ **{user.get('full_name', user_id)}** has been disabled.\n\n"
            f"- **Account:** Temporarily suspended\n"
            f"- **Access:** Blocked\n\n"
            f"- **GitLab sync:** {gitlab_sync.status}\n\n"
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
        gitlab_sync = await unblock_gitlab_user(user)
        return (
            f"✅ **{user.get('full_name', user_id)}** has been reinstated!\n\n"
            f"- **Account:** Active\n"
            f"- **Department:** {user.get('department')}\n"
            f"- **GitLab sync:** {gitlab_sync.status}"
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
            username = emp.get("username") or user_id
            email = emp.get("email") or f"{name.lower().replace(' ', '.')}@company.com"
            role = emp.get("role") or None

            if not role:
                results.append(f"⚠️ {name} — skipped: role not specified")
                continue

            existing_user = await db["users"].find_one({"$or": [{"user_id": user_id}, {"username": username}]})
            if existing_user:
                results.append(f"⚠️ {name} — skipped: username {username} already exists")
                continue

            new_user = {
                "user_id": user_id,
                "username": username,
                "email": email,
                "full_name": name,
                "department": dept,
                "role": role,
                "status": "inactive",
                "disabled": False,
    
                "hashed_password": get_password_hash(DEFAULT_GITLAB_TEMP_PASSWORD)
            }
            await db["users"].insert_one(new_user)
            gitlab_sync = await ensure_gitlab_user(new_user, DEFAULT_GITLAB_TEMP_PASSWORD)
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
            results.append(f"✅ {name} ({user_id}, username: {username}) -> {dept} / GitLab: {gitlab_sync.status}")

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
            gitlab_sync = await block_gitlab_user(user)
            results.append(f"✅ {uid} — offboarded / GitLab: {gitlab_sync.status}")

        return (
            f"**Bulk Offboarding Complete — {len(user_ids)} users**\n\n"
            + "\n".join(results)
        )

    elif intent == "query_users":
        filter_by = (entities.get("filter") or "").lower().strip()
        value = (entities.get("value") or "").strip()
        lookup = (entities.get("lookup") or "").lower().strip()

        # ── Build MongoDB query with case-insensitive regex ──
        query = {}
        if filter_by and value:
            if filter_by == "name":
                # Match anywhere in full_name, case-insensitive
                query["full_name"] = {"$regex": value, "$options": "i"}
            elif filter_by == "user_id":
                query["user_id"] = {"$regex": f"^{value}$", "$options": "i"}
            elif filter_by == "username":
                query["username"] = {"$regex": f"^{value}$", "$options": "i"}
            elif filter_by == "department":
                query["department"] = {"$regex": f"^{value}$", "$options": "i"}
            elif filter_by == "role":
                query["role"] = {"$regex": value, "$options": "i"}
            elif filter_by == "status":
                query["status"] = {"$regex": f"^{value}$", "$options": "i"}
            else:
                # Fallback for any other field — still use regex for safety
                query[filter_by] = {"$regex": value, "$options": "i"}

        users = await db["users"].find(query, {"hashed_password": 0}).to_list(length=50)

        if not users:
            search_label = f" matching **{value}**" if value else ""
            return f"❌ No users found{search_label}. Please check the name, ID, or filter and try again."

        # ── Answer specific lookup questions directly ──
        if lookup == "user_id":
            if len(users) == 1:
                u = users[0]
                return (
                    f"The User ID for **{u.get('full_name', value)}** is: **{u.get('user_id', 'N/A')}**\n"
                    f"- Department: {u.get('department', '-')} | Role: {u.get('role', '-')} | Status: {u.get('status', '-')}"
                )
            else:
                lines = [f"Found **{len(users)}** user(s) named **{value}**. Here are their User IDs:\n"]
                for u in users:
                    status_icon = "🟢" if u.get("status") == "active" else "🔴"
                    lines.append(
                        f"{status_icon} **{u.get('user_id', 'N/A')}** — {u.get('full_name', '-')} "
                        f"| {u.get('department', '-')} | {u.get('role', '-')} | {u.get('status', '-')}"
                    )
                return "\n".join(lines)

        if lookup == "department":
            if len(users) == 1:
                u = users[0]
                return (
                    f"**{u.get('full_name', value)}** ({u.get('user_id', 'N/A')}) is in the "
                    f"**{u.get('department', 'N/A')}** department.\n"
                    f"- Role: {u.get('role', '-')} | Status: {u.get('status', '-')}"
                )
            else:
                lines = [f"Found **{len(users)}** user(s) matching **{value}**:\n"]
                for u in users:
                    lines.append(
                        f"- **{u.get('user_id', 'N/A')}** — {u.get('full_name', '-')} → "
                        f"Department: **{u.get('department', '-')}** | Role: {u.get('role', '-')}"
                    )
                return "\n".join(lines)

        if lookup == "role":
            if len(users) == 1:
                u = users[0]
                return (
                    f"**{u.get('full_name', value)}** ({u.get('user_id', 'N/A')}) has the role: "
                    f"**{u.get('role', 'N/A')}**\n"
                    f"- Department: {u.get('department', '-')} | Status: {u.get('status', '-')}"
                )
            else:
                lines = [f"Found **{len(users)}** user(s) matching **{value}**:\n"]
                for u in users:
                    lines.append(
                        f"- **{u.get('user_id', 'N/A')}** — {u.get('full_name', '-')} → "
                        f"Role: **{u.get('role', '-')}** | Dept: {u.get('department', '-')}"
                    )
                return "\n".join(lines)

        if lookup == "status":
            if len(users) == 1:
                u = users[0]
                icon = "🟢" if u.get("status") == "active" else "🔴"
                return (
                    f"{icon} **{u.get('full_name', value)}** ({u.get('user_id', 'N/A')}) is currently "
                    f"**{u.get('status', 'N/A')}**.\n"
                    f"- Department: {u.get('department', '-')} | Role: {u.get('role', '-')}"
                )
            else:
                lines = [f"Found **{len(users)}** user(s) matching **{value}**:\n"]
                for u in users:
                    icon = "🟢" if u.get("status") == "active" else "🔴"
                    lines.append(
                        f"{icon} **{u.get('user_id', 'N/A')}** — {u.get('full_name', '-')} → "
                        f"Status: **{u.get('status', '-')}** | Dept: {u.get('department', '-')}"
                    )
                return "\n".join(lines)

        # ── Default: full listing ──
        filter_label = f" matching **{value}**" if value else ""
        lines = [f"**Found {len(users)} user(s){filter_label}:**\n"]
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

        # Support querying by username as well (e.g., "admin")
        target_user = await db["users"].find_one({
            "$or": [{"user_id": user_id}, {"username": user_id.lower()}]
        })
        resolved_user_id = target_user["user_id"] if target_user else user_id

        perms = await db["permissions"].find(
            {"user_id": resolved_user_id, "granted": True}
        ).to_list(length=None)

        state = await db["access_states"].find_one({"user_id": resolved_user_id})

        if not perms and (not state or not state.get("vpn_access")):
            return f"**{user_id}** has no active permissions."

        display_name = target_user.get('full_name', resolved_user_id) if target_user else user_id
        lines = [f"**Active permissions for {display_name} ({resolved_user_id}):**\n"]
        
        if perms:
            for p in perms:
                lines.append(f"✅ {p.get('resource', 'unknown')}")

        if state and state.get("vpn_access"):
            if perms:
                lines.append("")
            lines.append("**VPN Access Profiles:**")
            active_vpn = state.get("provisioned_vpn")
            
            vpn_map = {
                "vpn_eng": "Engineering VPN",
                "vpn_fin": "Finance VPN",
                "vpn_hr": "HR VPN",
                "vpn_sec": "Security VPN"
            }
            for v_id in state["vpn_access"]:
                v_name = vpn_map.get(v_id, f"VPN Profile {v_id}")
                if v_id == active_vpn:
                    lines.append(f"✅ **{v_name}** (Active)")
                else:
                    lines.append(f"🔄 **{v_name}** (Can be switched)")

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
                _pc = h.get("text") or h.get("content") or ""
                if isinstance(h, dict) and h.get("role") in ("assistant", "bot") and "Policy created successfully" in _pc:
                    start_idx = i + 1

            history_slice = history[start_idx:]

            # FIX 1: Always append the current user message so the loop can assign
            # it to the field that was last asked — even when the frontend sends
            # history *without* the in-flight user reply.
            if intent_data.get("current_message"):
                history_slice = history_slice + [{"role": "user", "content": intent_data["current_message"]}]

            for h in history_slice:
                if not isinstance(h, dict):
                    continue
                role = h.get("role", "")
                content = h.get("text") or h.get("content") or ""

                if role in ("assistant", "bot"):
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
                    if "Policy department recorded:" in content:
                        department = content.split("Policy department recorded:")[1].split("\n")[0].strip()
                    if "Description recorded." in content:
                        # Only set placeholder if description hasn't been captured from a user reply yet
                        if not description:
                            description = "__collected__"

                elif role in ("user",) and last_asked:
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

        # FIX 2: "__collected__" is a truthy sentinel meaning description WAS already
        # captured in a previous turn (the VPN prompt echoes "Description recorded."
        # instead of the raw text).  Do NOT reset it to None — leave it truthy so
        # the description gate never re-fires and the VPN gate runs next.
        # The sentinel is only replaced with a real value when we find the actual
        # user reply in the history loop above; if the reply is missing from history
        # the sentinel still keeps the gate closed so we don't loop forever.
        # (We keep the string as-is; vpn gate and creation block both ignore it.)

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
                f"Policy department recorded: {department}\n\n"
                "Description: Provide a brief description of what this policy enforces."
            )

        if not vpn:
            return (
                f"Policy name recorded: {name}\n"
                f"Policy type recorded: {policy_type}\n"
                f"Policy department recorded: {department}\n"
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
        # ── Multi-step stateful update form ──────────────────────────────────────
        # Structural markers used in bot messages:
        #   "Update policy recorded: {pol_id}"  → policy identified; asking which field
        #   "Update field recorded: {field}"    → field selected; asking for new value
        # These are parsed directly from history to avoid LLM re-classification.

        _upd_pol_id = None
        _upd_field  = None
        _upd_new_val = None
        _last_upd_asked = None   # "policy_id" | "field" | "value"

        _upd_hist = history if isinstance(history, list) else []
        # Find start of current update session (reset after last successful update)
        _upd_start = 0
        for _ui, _uh in enumerate(_upd_hist):
            _uhc = _uh.get("text") or _uh.get("content") or "" if isinstance(_uh, dict) else ""
            if isinstance(_uh, dict) and _uh.get("role") in ("assistant", "bot") and "Policy updated successfully!" in _uhc:
                _upd_start = _ui + 1
        _upd_slice = _upd_hist[_upd_start:]

        # Append current message so the loop can capture the user's latest reply
        _cur_msg = intent_data.get("current_message", "") if isinstance(intent_data, dict) else ""
        if _cur_msg:
            _upd_slice = _upd_slice + [{"role": "user", "content": _cur_msg}]

        for _uh in _upd_slice:
            if not isinstance(_uh, dict):
                continue
            _role_u = _uh.get("role", "")
            _cont_u = _uh.get("text") or _uh.get("content") or ""

            if _role_u in ("assistant", "bot"):
                # Extract confirmed values from structural markers
                if "Update policy recorded:" in _cont_u:
                    _upd_pol_id = _cont_u.split("Update policy recorded:")[1].split("\n")[0].strip()
                if "Update field recorded:" in _cont_u:
                    _upd_field = _cont_u.split("Update field recorded:")[1].split("\n")[0].strip()
                # Detect what the bot was last asking for
                if "policy name to update" in _cont_u or ("Policy ID" in _cont_u and "Update policy recorded:" not in _cont_u):
                    _last_upd_asked = "policy_id"
                elif "Update policy recorded:" in _cont_u and "Update field recorded:" not in _cont_u:
                    _last_upd_asked = "field"
                elif "Update field recorded:" in _cont_u:
                    _last_upd_asked = "value"

            elif _role_u == "user" and _last_upd_asked:
                _reply = _cont_u.strip()
                if _last_upd_asked == "policy_id" and not _upd_pol_id:
                    _upd_pol_id = _reply
                elif _last_upd_asked == "field" and not _upd_field:
                    _upd_field = _reply
                elif _last_upd_asked == "value" and not _upd_new_val:
                    _upd_new_val = _reply

        # Fallback: try LLM-extracted entities for initial single-shot invocation
        if not _upd_pol_id:
            _pid = entities.get("policy_id")
            if _pid:
                _upd_pol_id = _pid
            elif entities.get("name"):
                _pf = await db["policies"].find_one({"name": {"$regex": entities["name"], "$options": "i"}})
                if _pf:
                    _upd_pol_id = _pf["pol_id"]

        # ── Gate 1: Need policy ID ──
        if not _upd_pol_id:
            return "Please provide the **Policy ID** (e.g. POL-XXXXXXXX) or policy name to update."

        # Validate policy exists (try ID first, then name fallback)
        _existing = await db["policies"].find_one({"pol_id": _upd_pol_id})
        if not _existing:
            _existing = await db["policies"].find_one({"name": {"$regex": _upd_pol_id, "$options": "i"}})
            if _existing:
                _upd_pol_id = _existing["pol_id"]
            else:
                return f"❌ Policy **{_upd_pol_id}** not found. Please check the Policy ID or name."

        # ── Gate 2: Need field selection ──
        if not _upd_field:
            _status_str = "Active" if _existing.get("is_active") else "Inactive"
            return (
                f"Update policy recorded: {_upd_pol_id}\n\n"
                f"📋 **Current Policy: {_existing.get('name', 'Unnamed')}**\n"
                f"- **Policy ID:** {_upd_pol_id}\n"
                f"- **Name:** {_existing.get('name', '-')}\n"
                f"- **Type:** {_existing.get('type', '-')}\n"
                f"- **Department:** {_existing.get('department', '-')}\n"
                f"- **VPN Profile:** {_existing.get('vpn', '-')}\n"
                f"- **Description:** {_existing.get('description', 'None')}\n"
                f"- **Status:** {_status_str}\n\n"
                f"Which field would you like to update?\n"
                f"1. Name\n"
                f"2. Type `(jml / access / mfa)`\n"
                f"3. Department\n"
                f"4. VPN Profile\n"
                f"5. Description\n"
                f"6. Status `(active / inactive)`\n\n"
                f"Reply with the **field number** or **field name**."
            )

        # Normalise field selection
        _FIELD_MAP = {
            "1": "name",        "name": "name",
            "2": "type",        "type": "type",
            "3": "department",  "department": "department", "dept": "department",
            "4": "vpn",         "vpn": "vpn",  "vpn profile": "vpn",
            "5": "description", "description": "description", "desc": "description",
            "6": "status",      "status": "status",
        }
        _upd_field_norm = _FIELD_MAP.get(_upd_field.lower().strip())
        if not _upd_field_norm:
            return (
                f"Update policy recorded: {_upd_pol_id}\n\n"
                f"⚠️ **'{_upd_field}'** is not a valid field.\n\n"
                f"Please choose from:\n"
                f"1. Name\n2. Type\n3. Department\n4. VPN Profile\n5. Description\n6. Status"
            )

        # ── Gate 3: Need new value ──
        if not _upd_new_val:
            _cur_val = _existing.get(_upd_field_norm) if _upd_field_norm != "status" else (
                "Active" if _existing.get("is_active") else "Inactive"
            )
            _hints = {
                "name":        "Enter the new policy name",
                "type":        "Enter the type: **jml**, **access**, or **mfa**",
                "department":  f"Enter the department: {', '.join(sorted(ALLOWED_DEPARTMENTS))}",
                "vpn":         "Enter the VPN profile (e.g. vpn_hr, vpn_fin, vpn_eng, vpn_sales, vpn_sec)",
                "description": "Enter a new description for this policy",
                "status":      "Enter **active** or **inactive**",
            }
            return (
                f"Update policy recorded: {_upd_pol_id}\n"
                f"Update field recorded: {_upd_field_norm}\n\n"
                f"Current **{_upd_field_norm}**: `{_cur_val}`\n\n"
                f"{_hints.get(_upd_field_norm, 'Enter the new value')}:"
            )

        # ── All collected — validate and apply the update ──
        _update_doc = {"updated_on": datetime.utcnow()}
        if _upd_field_norm == "type":
            if _upd_new_val.lower() not in ("jml", "access", "mfa"):
                return (
                    f"Update policy recorded: {_upd_pol_id}\n"
                    f"Update field recorded: {_upd_field_norm}\n\n"
                    f"⚠️ Invalid type **'{_upd_new_val}'**. Must be **jml**, **access**, or **mfa**."
                )
            _update_doc["type"] = _upd_new_val.lower()
        elif _upd_field_norm == "status":
            if _upd_new_val.lower() in ("active", "true", "yes", "enable", "1"):
                _update_doc["is_active"] = True
            elif _upd_new_val.lower() in ("inactive", "false", "no", "disable", "0"):
                _update_doc["is_active"] = False
            else:
                return (
                    f"Update policy recorded: {_upd_pol_id}\n"
                    f"Update field recorded: {_upd_field_norm}\n\n"
                    f"⚠️ Invalid status **'{_upd_new_val}'**. Use **active** or **inactive**."
                )
        elif _upd_field_norm == "department":
            if _upd_new_val.lower() not in ALLOWED_DEPARTMENTS:
                return (
                    f"Update policy recorded: {_upd_pol_id}\n"
                    f"Update field recorded: {_upd_field_norm}\n\n"
                    f"⚠️ **'{_upd_new_val}'** is not a valid department.\n"
                    f"Choose from: **{', '.join(sorted(ALLOWED_DEPARTMENTS))}**"
                )
            _update_doc["department"] = _upd_new_val.lower()
        else:
            _update_doc[_upd_field_norm] = _upd_new_val

        await db["policies"].update_one({"pol_id": _upd_pol_id}, {"$set": _update_doc})
        await db["audit_logs"].insert_one({
            "user_id": "admin",
            "action": "update_policy",
            "target_resource": _upd_pol_id,
            "details": f"Admin updated policy '{_existing.get('name', _upd_pol_id)}' — field '{_upd_field_norm}' changed to '{_upd_new_val}'.",
            "timestamp": datetime.utcnow(),
        })
        _updated = {**_existing, **_update_doc}
        return (
            f"✅ **Policy updated successfully!**\n\n"
            f"- **Policy ID:** {_upd_pol_id}\n"
            f"- **Name:** {_updated.get('name')}\n"
            f"- **Type:** {_updated.get('type')}\n"
            f"- **Department:** {_updated.get('department')}\n"
            f"- **VPN Profile:** {_updated.get('vpn')}\n"
            f"- **Status:** {'Active' if _updated.get('is_active') else 'Inactive'}"
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

    def _get_content(h: dict) -> str:
        """Return message text regardless of whether the frontend used 'text' or 'content'."""
        return h.get("text") or h.get("content") or ""

    # ── Trim history at last completed policy/invite to prevent LLM entity leakage ──
    fresh_history = history
    if isinstance(history, list):
        for i, h in enumerate(history):
            if isinstance(h, dict) and h.get("role") in ("assistant", "bot") and (
                "Policy created successfully" in _get_content(h) or
                "Invitation sent successfully" in _get_content(h)
            ):
                fresh_history = history[i + 1:]

    # ── Intent Lock: detect active multi-step policy creation ─────────────────
    # Scan bot messages since the last successful policy creation for BOTH active
    # policy question prompts AND partial-field confirmation markers. This makes
    # the lock survive transient error/interrupt messages that appear mid-session.
    _POLICY_QUESTIONS = [
        "Policy Name: What should this policy be called",
        "Policy Type: Select one of the following",
        "Department: Which department does this policy apply",
        "Description: Provide a brief description",
        "VPN Profile: Specify the VPN profile",
    ]
    _POLICY_SESSION_MARKERS = [
        "Policy creation initiated",
        "Policy name recorded:",
        "Policy type recorded:",
        "Policy department recorded:",
        "Description recorded.",
    ]
    _in_policy_form = False
    if isinstance(history, list):
        _pol_session_start = 0
        for _i, _h in enumerate(history):
            if isinstance(_h, dict) and _h.get("role") in ("assistant", "bot"):
                if "Policy created successfully" in _get_content(_h):
                    _pol_session_start = _i + 1
        _scanned_bots = 0
        for _h in reversed(history[_pol_session_start:]):
            if not isinstance(_h, dict) or _h.get("role") not in ("assistant", "bot"):
                continue
            _bc = _get_content(_h)
            if any(q in _bc for q in _POLICY_QUESTIONS) or any(m in _bc for m in _POLICY_SESSION_MARKERS):
                _in_policy_form = True
                break
            _scanned_bots += 1
            if _scanned_bots >= 10:
                break

    # ── POLICY FORM LOCK — evaluated FIRST (highest priority) ─────────────────
    if _in_policy_form:
        # Only divert away for EXPLICIT abort words or unambiguous "?" questions.
        # Free-form descriptions/names must NEVER trigger LLM re-classification
        # because the LLM may mis-classify them as invite_joiner and corrupt flow.
        msg_lower = user_message.lower().strip()
        _ABORT_WORDS = {"cancel", "abort", "exit", "quit", "stop"}
        _is_explicit_abort = msg_lower in _ABORT_WORDS
        _WH_STARTERS = ("what ", "how ", "who ", "which ", "why ", "where ", "when ")
        _is_clear_question = (
            msg_lower.endswith("?")
            or any(msg_lower.startswith(w) for w in _WH_STARTERS)
        )
        if _is_explicit_abort or _is_clear_question:
            if _is_explicit_abort:
                return "❌ *Policy creation cancelled.*", {"intent": "unknown", "entities": {}}
            q_intent_data = await extract_admin_intent(user_message, fresh_history)
            q_intent = q_intent_data.get("intent", "unknown")
            if q_intent not in ("create_policy", "unknown"):
                q_intent_data["history"] = history
                answer = await execute_admin_intent(q_intent_data, db)
                return (
                    answer + "\n\n---\n📝 *Resuming policy creation — please answer the previous question to continue.*",
                    q_intent_data,
                )
        intent_data = {
            "intent": "create_policy",
            "entities": {},
            "missing_fields": [],
            "history": history,
            "current_message": user_message,
        }
        response = await execute_admin_intent(intent_data, db)
        return response, intent_data
    # ── END POLICY FORM LOCK ───────────────────────────────────────────────────

    # ── Intent Lock: detect active direct joiner onboarding ─────────────────────
    # Scan recent bot messages (since last successful onboarding) for joiner-
    # specific prompts. Prevents field answers like "finance" being classified
    # as help / general_query by the LLM.
    _JOINER_FORM_MARKERS = [
        "Let's onboard a new employee.",
        "Please provide the employee's **full name**",
        "Which **department** will they be joining?",
        "What is their **role** in the organisation?",
        "Please provide the employee's **email address**",
    ]
    _in_joiner_direct_form = False
    if isinstance(history, list):
        _joiner_done_idx = 0
        for _i, _h in enumerate(history):
            if isinstance(_h, dict) and _h.get("role") in ("assistant", "bot"):
                if "has been successfully onboarded!" in _get_content(_h):
                    _joiner_done_idx = _i + 1
        _jscanned = 0
        for _h in reversed(history[_joiner_done_idx:]):
            if not isinstance(_h, dict) or _h.get("role") not in ("assistant", "bot"):
                continue
            _bc = _get_content(_h)
            if any(m in _bc for m in _JOINER_FORM_MARKERS):
                _in_joiner_direct_form = True
                break
            _jscanned += 1
            if _jscanned >= 10:
                break

    if _in_joiner_direct_form:
        msg_lower = user_message.lower().strip()
        if msg_lower in {"cancel", "abort", "exit", "quit", "stop"}:
            return "❌ *Onboarding cancelled.*", {"intent": "unknown", "entities": {}}

        # ── Parse confirmed fields + detect last-asked field from history ──────
        # We bypass the LLM entirely for single-field answers to avoid LLM
        # misclassification (e.g. "hr" mapped to role:hr_manager instead of
        # department:hr, or off-topic messages like "Show all policies" causing
        # the LLM to drop previously-confirmed name/dept).
        # Strategy:
        #   1. Replay bot confirmation messages to recover all confirmed values.
        #   2. Detect which field was LAST asked (from the last bot message).
        #   3. Directly assign the user's current reply to that field.
        #   4. Fall back to LLM only for ambiguous/multi-field inputs.
        _confirmed_name = None
        _confirmed_dept = None
        _confirmed_role = None
        _last_asked = None   # "name" | "department" | "role" | "email"

        if isinstance(history, list):
            _j_done_idx = 0
            for _i, _h in enumerate(history):
                if isinstance(_h, dict) and _h.get("role") in ("assistant", "bot"):
                    if "has been successfully onboarded!" in _get_content(_h):
                        _j_done_idx = _i + 1
            for _h in history[_j_done_idx:]:
                if not isinstance(_h, dict) or _h.get("role") not in ("assistant", "bot"):
                    continue
                _bc = _get_content(_h)
                # "Almost done — **{name}** joining **{dept}** as **{role}**."
                # → all three fields confirmed; bot is now asking for email
                if "Almost done —" in _bc and " joining **" in _bc and " as **" in _bc:
                    try:
                        _parts = _bc.split("Almost done —")[1].split("\n")[0].strip().split("**")
                        if len(_parts) >= 6:
                            _confirmed_name = _parts[1].strip()
                            _confirmed_dept = _parts[3].strip()
                            _confirmed_role = _parts[5].strip()
                    except Exception:
                        pass
                    _last_asked = "email"
                # "Great — **{name}** joining **{dept}**."
                # → name + dept confirmed; bot is now asking for role
                elif "Great —" in _bc and " joining **" in _bc:
                    try:
                        _parts = _bc.split("Great —")[1].split("\n")[0].strip().split("**")
                        if len(_parts) >= 4:
                            _confirmed_name = _parts[1].strip()
                            _confirmed_dept = _parts[3].strip()
                    except Exception:
                        pass
                    _last_asked = "role"
                # "Got it — **{name}**."
                # → name confirmed; bot is now asking for department
                elif "Got it —" in _bc:
                    try:
                        _parts = _bc.split("Got it —")[1].split("\n")[0].strip().split("**")
                        if len(_parts) >= 2:
                            _confirmed_name = _parts[1].strip()
                    except Exception:
                        pass
                    _last_asked = "department"
                # "Let's onboard a new employee. Please provide the employee's **full name**"
                elif "Please provide the employee's **full name**" in _bc:
                    _last_asked = "name"

        # ── Directly assign user reply to the field being collected ──────────
        # This makes the form 100% deterministic for the happy path and immune
        # to LLM role-mapping (e.g. "hr" → hr_manager) or entity-drop bugs.
        _direct_entities: dict = {
            "name":       _confirmed_name,
            "department": _confirmed_dept,
            "role":       _confirmed_role,
            "email":      None,
        }

        if _last_asked == "name":
            _direct_entities["name"] = user_message.strip()
        elif _last_asked == "department":
            _direct_entities["department"] = user_message.strip().lower()
        elif _last_asked == "role":
            _direct_entities["role"] = user_message.strip()
        elif _last_asked == "email":
            _direct_entities["email"] = user_message.strip()
        else:
            # Ambiguous / multi-field message: fall back to LLM extraction
            _jd_llm = await extract_admin_intent(user_message, fresh_history, forced_intent="joiner")
            _llm_ents = _jd_llm.get("entities", {})
            # Merge: history-confirmed values fill gaps the LLM may have dropped
            if _confirmed_name and not _llm_ents.get("name"):
                _llm_ents["name"] = _confirmed_name
            if _confirmed_dept and not _llm_ents.get("department"):
                _llm_ents["department"] = _confirmed_dept
            if _confirmed_role and not _llm_ents.get("role"):
                _llm_ents["role"] = _confirmed_role
            _direct_entities = _llm_ents

        _jd = {
            "intent": "joiner",
            "entities": _direct_entities,
            "missing_fields": [],
            "history": history,
            "current_message": user_message,
        }
        response = await execute_admin_intent(_jd, db)
        return response, _jd

    # ── Intent Lock: detect active mover workflow ─────────────────────────────
    # Scan recent bot messages (since last transfer) for mover-specific prompts.
    _MOVER_FORM_MARKERS = [
        "I need the **User ID** of the employee to transfer",
        "Which **department** should they move to?",
        "What will their **new role** be?",
        "Currently in: **",
    ]
    _in_mover_form = False
    if isinstance(history, list):
        _mover_done_idx = 0
        for _i, _h in enumerate(history):
            if isinstance(_h, dict) and _h.get("role") in ("assistant", "bot"):
                if "has been successfully transferred!" in _get_content(_h):
                    _mover_done_idx = _i + 1
        _mscanned = 0
        for _h in reversed(history[_mover_done_idx:]):
            if not isinstance(_h, dict) or _h.get("role") not in ("assistant", "bot"):
                continue
            _bc = _get_content(_h)
            if any(m in _bc for m in _MOVER_FORM_MARKERS):
                _in_mover_form = True
                break
            _mscanned += 1
            if _mscanned >= 10:
                break

    if _in_mover_form:
        msg_lower = user_message.lower().strip()
        if msg_lower in {"cancel", "abort", "exit", "quit", "stop"}:
            return "❌ *Transfer cancelled.*", {"intent": "unknown", "entities": {}}
        # Run LLM to extract entities, but force intent to "mover"
        _md = await extract_admin_intent(user_message, fresh_history, forced_intent="mover")
        _md["intent"] = "mover"
        _md["history"] = history
        _md["current_message"] = user_message
        response = await execute_admin_intent(_md, db)
        return response, _md

    # ── Intent Lock: detect joiner onboarding menu waiting for choice ──────────
    _JOINER_MENU_MARKER = "Reply with **1** to onboard directly, or **2** to send an invite email."
    _in_joiner_menu = False
    if isinstance(history, list):
        for h in reversed(history):
            if isinstance(h, dict) and h.get("role") in ("assistant", "bot"):
                if _JOINER_MENU_MARKER in _get_content(h):
                    _in_joiner_menu = True
                break

    if _in_joiner_menu:
        msg_lower = user_message.lower().strip()
        _ABORT_WORDS = ["cancel", "abort", "exit", "quit", "stop"]
        if any(w in msg_lower for w in _ABORT_WORDS):
            return "\u274c *Joiner onboarding cancelled.*", {"intent": "unknown", "entities": {}}
        _INVITE_CHOICE = ["2", "two", "invite", "email", "send invite", "via email", "send email"]
        if any(kw in msg_lower for kw in _INVITE_CHOICE):
            _inv_data = await extract_admin_intent(user_message, fresh_history, forced_intent="invite_joiner")
            _inv_data["intent"] = "invite_joiner"
            _inv_data["history"] = history
            _inv_data["current_message"] = user_message
            _resp = await execute_admin_intent(_inv_data, db)
            return _resp, _inv_data
        else:
            _joiner_data = await extract_admin_intent(user_message, fresh_history, forced_intent="joiner")
            _joiner_data["intent"] = "joiner"
            _joiner_data["history"] = history
            _joiner_data["current_message"] = user_message
            _resp = await execute_admin_intent(_joiner_data, db)
            return _resp, _joiner_data

    # ── Intent Lock: detect active invite form ─────────────────────────────────
    _INVITE_MARKERS = [
        "invite email address",
        "Invite email recorded:",
        "Invite department recorded:",
    ]
    _in_invite_form = False
    if isinstance(history, list):
        for h in reversed(history):
            if isinstance(h, dict) and h.get("role") in ("assistant", "bot"):
                last_bot_inv = _get_content(h)
                if any(m in last_bot_inv for m in _INVITE_MARKERS) and "Invitation sent successfully" not in last_bot_inv:
                    _in_invite_form = True
                break

    if _in_invite_form:
        msg_lower = user_message.lower().strip()
        _ABORT_WORDS = ["cancel", "abort", "exit", "quit", "stop"]
        if any(w in msg_lower for w in _ABORT_WORDS):
            return "❌ *Invite cancelled.*", {"intent": "unknown", "entities": {}}
        inv_intent_data = await extract_admin_intent(user_message, fresh_history, forced_intent="invite_joiner")
        inv_intent_data["intent"] = "invite_joiner"
        inv_intent_data["history"] = history
        inv_intent_data["current_message"] = user_message
        response = await execute_admin_intent(inv_intent_data, db)
        return response, inv_intent_data
    # ──────────────────────────────────────────────────────────────────────────

    # ── Intent Lock: detect active update_policy flow ─────────────────────────
    # Structural markers: "Update policy recorded:" and "Update field recorded:"
    # Lock fires as long as the last bot message contains one of these markers
    # and there has been no successful update since.
    _UPDATE_POLICY_MARKERS = ["Update policy recorded:", "Update field recorded:"]
    _in_update_policy_form = False
    if isinstance(history, list):
        for h in reversed(history):
            if isinstance(h, dict) and h.get("role") in ("assistant", "bot"):
                _ubc = _get_content(h)
                if any(m in _ubc for m in _UPDATE_POLICY_MARKERS) and "Policy updated successfully!" not in _ubc:
                    _in_update_policy_form = True
                break

    if _in_update_policy_form:
        msg_lower = user_message.lower().strip()
        if msg_lower in {"cancel", "abort", "exit", "quit", "stop"}:
            return "❌ *Update cancelled.*", {"intent": "unknown", "entities": {}}
        _upd_intent_data = {
            "intent": "update_policy",
            "entities": {},
            "missing_fields": [],
            "history": history,
            "current_message": user_message,
        }
        response = await execute_admin_intent(_upd_intent_data, db)
        return response, _upd_intent_data
    # ── END UPDATE POLICY LOCK ─────────────────────────────────────────────────

    intent_data = await extract_admin_intent(user_message, fresh_history)
    intent_data["history"] = history
    intent = intent_data.get("intent", "unknown")

    # ── Safety guard: if the LLM returns an off-topic intent while we are clearly
    # inside an active multi-step form session, override it to the correct intent.
    # Covers: policy, joiner-direct, and mover sessions.
    _OFF_TOPIC = {"help", "greeting", "general_query", "unknown", "invite_joiner"}
    if intent in _OFF_TOPIC and isinstance(history, list):

        # Policy session guard
        _pg_start = 0
        for _gi, _gh in enumerate(history):
            if isinstance(_gh, dict) and _gh.get("role") in ("assistant", "bot"):
                if "Policy created successfully" in _get_content(_gh):
                    _pg_start = _gi + 1
        for _gh in history[_pg_start:]:
            if isinstance(_gh, dict) and _gh.get("role") in ("assistant", "bot"):
                if any(m in _get_content(_gh) for m in _POLICY_SESSION_MARKERS):
                    intent_data["intent"] = "create_policy"
                    intent_data["entities"] = {}
                    intent = "create_policy"
                    break

        # Joiner direct session guard (only if policy guard didn't fire)
        if intent in _OFF_TOPIC:
            _jg_start = 0
            for _gi, _gh in enumerate(history):
                if isinstance(_gh, dict) and _gh.get("role") in ("assistant", "bot"):
                    if "has been successfully onboarded!" in _get_content(_gh):
                        _jg_start = _gi + 1
            for _gh in history[_jg_start:]:
                if isinstance(_gh, dict) and _gh.get("role") in ("assistant", "bot"):
                    if any(m in _get_content(_gh) for m in _JOINER_FORM_MARKERS):
                        intent_data["intent"] = "joiner"
                        intent = "joiner"
                        break

        # Mover session guard (only if neither policy nor joiner guard fired)
        if intent in _OFF_TOPIC:
            _mg_start = 0
            for _gi, _gh in enumerate(history):
                if isinstance(_gh, dict) and _gh.get("role") in ("assistant", "bot"):
                    if "has been successfully transferred!" in _get_content(_gh):
                        _mg_start = _gi + 1
            for _gh in history[_mg_start:]:
                if isinstance(_gh, dict) and _gh.get("role") in ("assistant", "bot"):
                    if any(m in _get_content(_gh) for m in _MOVER_FORM_MARKERS):
                        intent_data["intent"] = "mover"
                        intent = "mover"
                        break

    # Route RAG/fraud queries directly to the RAG engine unless user is HR
    if intent == "rag_query":
        if "hr" in user_role.lower():
            return "Access Denied: Fraud detection and log analysis tools are restricted to Security Admins only.", intent_data
        response = await rag_answer(user_message, db)
        return response, intent_data

    response = await execute_admin_intent(intent_data, db)
    return response, intent_data
