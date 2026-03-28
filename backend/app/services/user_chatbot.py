"""
IAM User Chatbot — RAG-powered access decision engine.

Flow for every access request:
  1. extract_user_intent()   → classify intent + extract resource/reason
  2. fetch RAG contexts      → Identity RAG + Policy RAG + Audit RAG (parallel)
  3. make_access_decision()  → LLM decision: ACCEPT / ESCALATE / DENY
  4. execute_decision()      → update DB + log to audit_logs
  5. format_response()       → structured reply for the frontend
"""

import json
import asyncio
from datetime import datetime
from groq import Groq
from app.core.config import settings
from app.rag.identity_context import fetch_identity_context
from app.rag.policy_context import fetch_policy_context
from app.rag.audit_context import fetch_audit_context
from app.rag.user_access_rag import refresh_policy_index

# --------------------------------------------------------------------------- #
#  Groq client (singleton)
# --------------------------------------------------------------------------- #

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


async def _call_groq(messages: list, max_tokens: int = 600) -> dict:
    client = _get_client()

    def _sync_call():
        return client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
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
        return {}


# --------------------------------------------------------------------------- #
#  Help text constant
# --------------------------------------------------------------------------- #

USER_HELP_TEXT = (
    "**❓ IAM Self-Service — Available Commands**\n\n"
    "Here's what you can ask me:\n\n"
    "**🔐 Access & Permissions**\n"
    "• `What access do I currently have?` — View your access profile\n"
    "• `I want access to <resource>` — Request access to any VPN/application/resource\n"
    "• `Do I have access to <resource>?` — Check specific access\n\n"
    "**👤 Profile Information**\n"
    "• `What policy am I assigned?` — View your policy\n"
    "• `Which team/department am I in?` — View your details\n\n"
    "**💡 Tips**\n"
    "• Be specific when requesting access (mention resource name and purpose)\n"
    "• You can ask follow-up questions if needed\n"
    "• Say `help` anytime to see this menu again\n\n"
    "> ⚠️ Note:\n"
    "> I can only assist with IAM-related access requests and information queries."
)

# --------------------------------------------------------------------------- #
#  STEP 1 — Intent extraction
# --------------------------------------------------------------------------- #

_INTENT_SYSTEM_PROMPT = """You are an IAM (Identity and Access Management) self-service gateway.
Your ONLY job is to classify the user's message intent and extract key entities.

STRICTLY ALLOWED intents:
- greeting      : pure hello / hi / good morning (NO task context)
- help          : asking for help, commands, menu, what can you do
- query_self_access : user wants to know their own VPN, role, department, policy, or resources
- access_request : user wants to REQUEST access to a VPN, resource, or application
- out_of_scope  : anything NOT related to IAM access management

For access_request, ALSO extract:
- requested_resource : the exact VPN id or resource name (e.g. vpn_fin, finance_db)
- reason             : the user's stated reason (or null if not given)
- needs_clarification: true if resource name OR reason is completely missing

If needs_clarification is true, YOU MUST provide a specific, context-aware clarification_question.
Example: "What is the specific purpose or task requiring access to vpn_eng?" 
Do NOT ask generic questions. Ask specific questions based on what they already provided.

AVAILABLE VPN IDs for reference: vpn_eng, vpn_hr, vpn_fin, vpn_sec, vpn_admin

Respond ONLY with valid JSON. No text outside JSON. Example:
{"intent": "access_request", "requested_resource": "vpn_fin", "reason": "cross-team project", "needs_clarification": false}
{"intent": "access_request", "requested_resource": "vpn_eng", "reason": null, "needs_clarification": true, "clarification_question": "What is the specific purpose or task requiring access to vpn_eng?"}
{"intent": "query_self_access"}
{"intent": "out_of_scope"}
"""


async def extract_user_intent(user_message: str, history: list) -> dict:
    messages = [{"role": "system", "content": _INTENT_SYSTEM_PROMPT}]
    valid_roles = {"system", "user", "assistant"}
    for h in history[-6:]:
        if isinstance(h, dict):
            role = h.get("role", "user")
            if role == "bot":
                role = "assistant"
            if role not in valid_roles:
                role = "user"
            content = h.get("text") or h.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    data = await _call_groq(messages, max_tokens=200)
    raw = data["choices"][0]["message"]["content"]
    parsed = _parse_json(raw)
    if not parsed or "intent" not in parsed:
        parsed = {"intent": "out_of_scope"}
    return parsed


# --------------------------------------------------------------------------- #
#  STEP 3 — LLM access decision (uses all 3 RAG contexts)
# --------------------------------------------------------------------------- #

_DECISION_SYSTEM_PROMPT = """You are a strict IAM Access Decision Engine.

Using the three RAG context blocks below, decide whether the user's access request should be:
- ACCEPT    : Identity valid + request matches policy + audit is TRUSTED/MODERATE
- ESCALATE  : Identity valid + request is a contextually reasonable POLICY GAP
- DENY      : Identity invalid/inactive OR POLICY VIOLATION OR high risk without ANY justification

Policy classification:
- VALID ACCESS   : resource already allowed by the user's department policy
- POLICY GAP     : resource NOT in policy but the request is contextually reasonable (e.g. cross-team project, temp need)
- POLICY VIOLATION : resource entirely unrelated to user's role/department, high-risk, or no valid justification

DECISION RULES:

- Audit (Risk) Check is used for refinement, NOT blind rejection.

--------------------------------------------------

1. IDENTITY RULE:
- If the user is inactive/disabled → ALWAYS DENY

--------------------------------------------------

2. DIRECT ACCEPT CASE:
- If the user already has the requested resource → ACCEPT immediately

--------------------------------------------------

3. CLEAR DENIAL (STRICT RULE):
- If the request is clearly invalid, unauthorized, or unrelated to the users role/work → DENY

Examples:
- Requesting access to sensitive data (e.g., salaries, personal data,etc) without valid need
- Access unrelated to department or responsibilities
- To change content of data
- Requests with no logical business justification

--------------------------------------------------

4. GENUINE REQUEST (ROLE-BASED CONTEXT):
- A request is considered GENUINE only if:
  - It is directly related to the users role, department, or assigned work
  - It supports a valid business or project need

In such cases:
→ If not already in policy → ESCALATE

--------------------------------------------------

5. POLICY GAP HANDLING:
- If the request is not in policy BUT is role/work-related:
  → ESCALATE (do NOT deny)

--------------------------------------------------

6. AUDIT (RISK) HANDLING:
- Risk must NOT override a genuine request

Rules:
- If a request was DENIED earlier → do NOT overly penalize future requests
- If a new request is GENUINE:
  → Even with HIGH risk → prefer ESCALATE
- Use risk only to strengthen decisions, not dominate them

--------------------------------------------------

7. FINAL DECISION SUMMARY:

- Already has access → ACCEPT
- Role/work-related but not in policy → ESCALATE
- Clearly unrelated / invalid / unjustified → DENY
- Inactive user → DENY

Respond ONLY with valid JSON:
{
  "decision": "ACCEPT",
  "identity_check": "Active user, engineering department, software_engineer role",
  "policy_check": "VALID ACCESS. The requested VPN is approved for this department.",
  "audit_check": "TRUSTED. User has a clean history of approved requests.",
  "explanation": "The requested VPN is allowed by your department policy. Enjoy your access."
}

Ensure "explanation" is a short 1-2 line simple summary. Do NOT mention RAG, "identity check", "policy check", or "audit check" in the explanation. Keep it extremely concise and user-friendly.

Make sure to include a short ". why" explanation in your "policy_check" and "audit_check" fields to justify the classification.
"""


async def make_access_decision(
    user_message: str,
    requested_resource: str,
    reason: str,
    identity_ctx: str,
    policy_ctx: str,
    audit_ctx: str,
) -> dict:
    user_content = (
        f"Access Request:\n"
        f"- Requested Resource: {requested_resource or 'unspecified'}\n"
        f"- User's Stated Reason: {reason or 'not provided'}\n"
        f"- Original Message: {user_message}\n\n"
        f"{identity_ctx}\n\n"
        f"{policy_ctx}\n\n"
        f"{audit_ctx}"
    )
    messages = [
        {"role": "system", "content": _DECISION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    data = await _call_groq(messages, max_tokens=400)
    raw = data["choices"][0]["message"]["content"]
    result = _parse_json(raw)
    if not result or "decision" not in result:
        result = {
            "decision": "DENY",
            "identity_check": "Unable to verify",
            "policy_check": "POLICY VIOLATION",
            "audit_check": "UNKNOWN",
            "explanation": "Could not evaluate the request. Access denied for safety.",
        }
    return result


# --------------------------------------------------------------------------- #
#  STEP 4 — Execute decision (DB mutations + audit log)
# --------------------------------------------------------------------------- #

async def execute_decision(
    decision: str,
    requested_resource: str,
    reason: str,
    current_user,
    db,
    result: dict,
) -> None:
    """Apply DB side-effects and write to audit_logs."""
    user_id = current_user.user_id
    now = datetime.utcnow()

    if decision == "ACCEPT":
        state = await db["access_states"].find_one({"user_id": user_id})
        if state:
            field = "vpn_access" if "vpn" in (requested_resource or "") else "resources"
            existing = state.get(field, [])
            if requested_resource and requested_resource not in existing:
                existing.append(requested_resource)
                await db["access_states"].update_one(
                    {"user_id": user_id},
                    {"$set": {field: existing}},
                )
        else:
            field = "vpn_access" if "vpn" in (requested_resource or "") else "resources"
            await db["access_states"].insert_one(
                {"user_id": user_id, "vpn_access": [], "resources": [], field: [requested_resource]}
            )

    elif decision == "ESCALATE":
        # Insert a pending access request for admin review
        await db["access_requests"].update_one(
            {"user_id": user_id, "resource_type": requested_resource, "status": "pending"},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "resource_type": requested_resource,
                    "reason": reason or "Not provided",
                    "status": "pending",
                    "timestamp": now,
                }
            },
            upsert=True,
        )

    # Always log the decision to audit_logs
    await db["audit_logs"].insert_one(
        {
            "user_id": user_id,
            "action": decision,
            "target_resource": requested_resource or "unspecified",
            "decision": decision,
            "reason": reason or "Not provided",
            "details": f"Requested {requested_resource or 'unspecified'} (Reason: {reason or 'Not provided'}). Decision: {decision}. {result.get('explanation', 'Access request processed')}",
            "rag_details": result,
            "timestamp": now,
        }
    )


# --------------------------------------------------------------------------- #
#  STEP 5 — Format user-facing response
# --------------------------------------------------------------------------- #

_DECISION_ICONS = {"ACCEPT": "✅", "ESCALATE": "⚠️", "DENY": "❌"}
_POLICY_ICONS = {
    "VALID ACCESS": "🟢",
    "POLICY GAP": "🟡",
    "POLICY VIOLATION": "🔴",
}
_AUDIT_ICONS = {"TRUSTED": "🟢", "MODERATE": "🟡", "RISKY": "🔴"}


def format_decision_response(result: dict, requested_resource: str) -> str:
    decision = result.get("decision", "DENY")
    icon = _DECISION_ICONS.get(decision, "❌")

    lines = [
        f"{icon} **Decision: {decision}**\n",
        "**Reason:**",
        result.get("explanation", "Access request processed.")
    ]
    if decision == "ESCALATE":
        lines += [
            "",
            f"📨 Your request for **{requested_resource}** has been sent to an administrator for review.",
        ]
    elif decision == "ACCEPT":
        lines += [
            "",
            f"🔓 **{requested_resource}** has been added to your access profile.",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Non-access intents
# --------------------------------------------------------------------------- #

_PROFILE_QUERY_PROMPT = """You are an IAM Self-Service assistant.
The user is asking a question about their own IAM profile or access.
Answer their question directly and concisely based ONLY on the provided User Profile Information.
If the question asks for details included in the profile (like user ID, policies, VPNs, roles), provide them naturally.
If the question is not related to IAM or the provided profile info, politely decline to answer saying you only assist with IAM-related queries.

User Profile Information:
- User ID: {user_id}
- Role: {role}
- Department: {department}
- VPN Access: {vpns}
- Other Resources: {resources}
"""

async def handle_simple_intent(
    intent: str, user_message: str, current_user, db
) -> str:
    """Handle greeting / help / query_self_access without going through the decision engine."""

    if intent == "help":
        return USER_HELP_TEXT

    if intent == "query_self_access":
        state = await db["access_states"].find_one({"user_id": current_user.user_id}) or {}
        vpns = ", ".join(state.get("vpn_access", [])) or "None"
        resources = ", ".join(state.get("resources", [])) or "None"
        
        system_content = _PROFILE_QUERY_PROMPT.format(
            user_id=current_user.user_id,
            role=current_user.role,
            department=current_user.department,
            vpns=vpns,
            resources=resources
        )
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_message}
        ]
        
        try:
            data = await _call_groq(messages, max_tokens=250)
            return data["choices"][0]["message"]["content"]
        except Exception:
            return "I'm having trouble retrieving your profile right now."

    if intent == "out_of_scope":
        return "🚫 I can only assist with IAM-related access and information queries."

    # Default to greeting
    first = (
        current_user.full_name.split()[0]
        if hasattr(current_user, "full_name") and current_user.full_name
        else current_user.username
    )
    return (
        f"👋 **Hi {first}! Welcome to the IAM Self-Service Portal.**\n\n"
        "I'm here to help you manage your access and VPN.\n\n"
        "Here's what I can do for you:\n"
        "• **Check your access** — see your current VPNs and resources\n"
        "• **Request access** — submit a request for any VPN or resource\n"
        "• **Understand decisions** — review why access was granted or denied\n\n"
        "Type **help** for the full command list, or just tell me what you need! 😊"
    )


# --------------------------------------------------------------------------- #
#  Public entrypoint
# --------------------------------------------------------------------------- #

async def user_chat(
    user_message: str, history: list, current_user, db
) -> tuple:
    """
    Main entrypoint called by the chatbot API router.
    Returns (response_text, intent_data).
    """
    # --- Step 1: extract intent ---
    intent_data = await extract_user_intent(user_message, history)
    intent = intent_data.get("intent", "out_of_scope")

    # --- Short-circuit for non-access intents ---
    if intent != "access_request":
        response = await handle_simple_intent(intent, user_message, current_user, db)
        return response, intent_data

    # --- Needs clarification? ---
    if intent_data.get("needs_clarification"):
        question = intent_data.get("clarification_question")
        if question:
            return question, intent_data
        
        requested_resource = intent_data.get("requested_resource")
        reason = intent_data.get("reason")
        missing = []
        if not requested_resource:
            missing.append("**which VPN or resource** you want (e.g. `vpn_eng`, `vpn_fin`)")
        if not reason:
            missing.append("**the reason** for this access request")
        clarification = "I need a bit more information before I can process your request:\n\n"
        clarification += "\n".join(f"• Please provide {m}" for m in missing)
        return clarification, intent_data

    requested_resource = intent_data.get("requested_resource", "unspecified")
    reason = intent_data.get("reason", "")

    # --- Step 2: Refresh policy index for vector-based search ---
    await refresh_policy_index(db)

    # --- Step 3: fetch all 3 RAG contexts in parallel ---
    search_query = f"{requested_resource} {reason}" if reason else requested_resource
    identity_ctx, policy_ctx, audit_ctx = await asyncio.gather(
        fetch_identity_context(current_user.user_id, db),
        fetch_policy_context(current_user.user_id, current_user.department, db, query=search_query),
        fetch_audit_context(current_user.user_id, db, search_query=search_query),
    )

    # --- Step 4: LLM decision ---
    result = await make_access_decision(
        user_message, requested_resource, reason,
        identity_ctx, policy_ctx, audit_ctx,
    )
    decision = result.get("decision", "DENY")

    # --- Step 5: execute (DB mutations + audit log) ---
    await execute_decision(decision, requested_resource, reason, current_user, db, result)

    # --- Step 6: format and return ---
    response = format_decision_response(result, requested_resource)
    return response, intent_data
