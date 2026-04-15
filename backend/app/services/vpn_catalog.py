import re


DEPARTMENT_ALIASES = {
    "engineering": {"engineering", "engineer", "eng"},
    "finance": {"finance", "financial", "fin"},
    "hr": {"hr", "human resources", "human resource", "humanresources"},
    "security": {"security", "sec"},
}


def _normalize(text: str) -> str:
    value = (text or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _compact(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _pool_aliases(pool: dict) -> set[str]:
    aliases = set()
    pool_id = pool.get("pool_id", "")
    name = pool.get("name", "")
    department = pool.get("department", "")

    for value in (pool_id, name, department):
        normalized = _normalize(value)
        if normalized:
            aliases.add(normalized)
            aliases.update(normalized.split())

    dept_key = _normalize(department)
    if dept_key in DEPARTMENT_ALIASES:
        aliases.update(DEPARTMENT_ALIASES[dept_key])

    pool_suffix = _normalize(pool_id).replace("vpn ", "").replace("vpn_", "").strip()
    if pool_suffix:
        aliases.add(pool_suffix)

    return {alias for alias in aliases if alias}


async def list_active_vpn_pools(db) -> list[dict]:
    return await db["vpn_ip_pools"].find({"is_active": True}).to_list(length=100)


async def resolve_vpn_request(db, text: str) -> tuple[str | None, list[dict]]:
    pools = await list_active_vpn_pools(db)
    if not pools:
        return None, []

    query_norm = _normalize(text)
    query_compact = _compact(text)
    query_words = set(query_norm.split())

    best_pool_id = None
    best_score = 0

    for pool in pools:
        score = 0
        for alias in _pool_aliases(pool):
            alias_norm = _normalize(alias)
            alias_compact = _compact(alias)
            alias_words = set(alias_norm.split())

            if not alias_norm:
                continue
            if alias_norm == query_norm or alias_compact == query_compact:
                score = max(score, 100)
                continue
            if alias_norm in query_norm or (alias_compact and alias_compact in query_compact):
                score = max(score, 80)
                continue
            overlap = len(alias_words & query_words)
            if overlap:
                score = max(score, overlap * 10)

        if score > best_score:
            best_score = score
            best_pool_id = pool.get("pool_id")

    if best_score < 10:
        return None, pools
    return best_pool_id, pools
