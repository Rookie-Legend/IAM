from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


ADMIN_ROLES = {"Security Admin", "System Administrator", "HR Manager", "admin"}
GITLAB_USERNAME_OVERRIDES = {
    "admin": "iam_admin",
}
SEED_PASSWORDS = {
    "admin": "V8#mQ2!sR7@zLp4",
    "hr_manager": "N6@tY9#pK3!vQx2",
    "eng_infra": "R4!wZ8@mC2#nTq7",
    "eng_front": "K9#xP5!bL3@vSd6",
    "eng_back": "T2@qM8#rV6!zWp5",
    "rookie": "P7!dH4@kX9#sJm2",
}
DEFAULT_GITLAB_TEMP_PASSWORD = "Q9@vR4#xT7!mZ2$p"


@dataclass
class GitLabSyncResult:
    username: str
    status: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "status": self.status,
            "detail": self.detail,
        }


def gitlab_sync_enabled() -> bool:
    return bool(settings.GITLAB_SYNC_ENABLED and settings.GITLAB_ADMIN_TOKEN)


def should_sync_user(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    department = (user.get("department") or "").strip().lower()
    role = (user.get("role") or "").strip()
    return department == "engineering" or role in ADMIN_ROLES


def seed_password_for(user: dict[str, Any]) -> str | None:
    username = user.get("username") or user.get("user_id")
    return SEED_PASSWORDS.get(username)


def gitlab_username_for(user: dict[str, Any]) -> str:
    username = user.get("username") or user.get("user_id") or ""
    return GITLAB_USERNAME_OVERRIDES.get(username, username)


def _base_url() -> str:
    return settings.GITLAB_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"PRIVATE-TOKEN": settings.GITLAB_ADMIN_TOKEN}


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        if detail:
            raise RuntimeError(f"{exc}; response={detail}") from exc
        raise


async def _find_gitlab_user(client: httpx.AsyncClient, username: str) -> dict[str, Any] | None:
    response = await client.get(
        f"{_base_url()}/api/v4/users",
        headers=_headers(),
        params={"username": username},
    )
    _raise_for_status(response)
    users = response.json()
    for user in users:
        if user.get("username") == username:
            return user
    return None


def _payload_for(user: dict[str, Any], password: str | None = None) -> dict[str, Any]:
    username = gitlab_username_for(user)
    payload = {
        "email": user.get("email") or f"{username}@corpod.local",
        "username": username,
        "name": user.get("full_name") or username,
        "skip_confirmation": True,
        "can_create_group": False,
    }
    if password:
        payload["password"] = password
    return payload


async def ensure_gitlab_user(user: dict[str, Any], password: str | None = None) -> GitLabSyncResult:
    iam_username = user.get("username") or user.get("user_id") or ""
    gitlab_username = gitlab_username_for(user)
    if not iam_username:
        return GitLabSyncResult("", "skipped", "missing_username")
    if not should_sync_user(user):
        return GitLabSyncResult(gitlab_username, "skipped", "outside_gitlab_scope")
    if not gitlab_sync_enabled():
        return GitLabSyncResult(gitlab_username, "skipped", "gitlab_sync_disabled_or_missing_token")
    if not password:
        return GitLabSyncResult(gitlab_username, "skipped", "missing_plaintext_password")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            existing = await _find_gitlab_user(client, gitlab_username)
            payload = _payload_for(user, password)
            if existing:
                response = await client.put(
                    f"{_base_url()}/api/v4/users/{existing['id']}",
                    headers=_headers(),
                    data=payload,
                )
                _raise_for_status(response)
                if user.get("disabled"):
                    return await block_gitlab_user(user)
                return GitLabSyncResult(gitlab_username, "updated")

            response = await client.post(
                f"{_base_url()}/api/v4/users",
                headers=_headers(),
                data=payload,
            )
            _raise_for_status(response)
            if user.get("disabled"):
                return await block_gitlab_user(user)
            return GitLabSyncResult(gitlab_username, "created")
    except Exception as exc:
        return GitLabSyncResult(gitlab_username, "error", str(exc))


async def update_gitlab_password(user: dict[str, Any], password: str) -> GitLabSyncResult:
    iam_username = user.get("username") or user.get("user_id") or ""
    gitlab_username = gitlab_username_for(user)
    if not iam_username:
        return GitLabSyncResult("", "skipped", "missing_username")
    if not should_sync_user(user):
        return GitLabSyncResult(gitlab_username, "skipped", "outside_gitlab_scope")
    if not gitlab_sync_enabled():
        return GitLabSyncResult(gitlab_username, "skipped", "gitlab_sync_disabled_or_missing_token")
    if not password:
        return GitLabSyncResult(gitlab_username, "skipped", "missing_plaintext_password")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            existing = await _find_gitlab_user(client, gitlab_username)
            if not existing:
                return await ensure_gitlab_user(user, password)

            response = await client.put(
                f"{_base_url()}/api/v4/users/{existing['id']}",
                headers=_headers(),
                data={"password": password},
            )
            _raise_for_status(response)
            return GitLabSyncResult(gitlab_username, "password_updated")
    except Exception as exc:
        return GitLabSyncResult(gitlab_username, "error", str(exc))


async def block_gitlab_user(user: dict[str, Any]) -> GitLabSyncResult:
    return await _set_block_state(user, block=True)


async def unblock_gitlab_user(user: dict[str, Any]) -> GitLabSyncResult:
    return await _set_block_state(user, block=False)


async def _set_block_state(user: dict[str, Any], block: bool) -> GitLabSyncResult:
    iam_username = user.get("username") or user.get("user_id") or ""
    gitlab_username = gitlab_username_for(user)
    if not iam_username:
        return GitLabSyncResult("", "skipped", "missing_username")
    if not should_sync_user(user):
        return GitLabSyncResult(gitlab_username, "skipped", "outside_gitlab_scope")
    if not gitlab_sync_enabled():
        return GitLabSyncResult(gitlab_username, "skipped", "gitlab_sync_disabled_or_missing_token")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            existing = await _find_gitlab_user(client, gitlab_username)
            if not existing:
                return GitLabSyncResult(gitlab_username, "skipped", "gitlab_user_missing")
            action = "block" if block else "unblock"
            response = await client.post(
                f"{_base_url()}/api/v4/users/{existing['id']}/{action}",
                headers=_headers(),
            )
            _raise_for_status(response)
            return GitLabSyncResult(gitlab_username, "blocked" if block else "unblocked")
    except Exception as exc:
        return GitLabSyncResult(gitlab_username, "error", str(exc))


async def backfill_gitlab_users(users: list[dict[str, Any]], db: Any | None = None) -> dict[str, Any]:
    summary = {
        "created": 0,
        "updated": 0,
        "created_with_temp_password": 0,
        "updated_with_temp_password": 0,
        "blocked": 0,
        "unblocked": 0,
        "skipped": 0,
        "errors": 0,
        "results": [],
    }

    for user in users:
        username = user.get("username") or user.get("user_id") or ""
        if not should_sync_user(user):
            result = GitLabSyncResult(username, "skipped", "outside_gitlab_scope")
        else:
            password = seed_password_for(user)
            used_temp_password = False
            if not password:
                password = DEFAULT_GITLAB_TEMP_PASSWORD
                used_temp_password = True

            result = await ensure_gitlab_user(user, password)
            if used_temp_password and result.status in {"created", "updated"}:
                if db is not None:
                    await db["users"].update_one(
                        {"user_id": user.get("user_id")},
                        {"$set": {"gitlab_temp_password_set": True}},
                    )
                result = GitLabSyncResult(
                    result.username,
                    f"{result.status}_with_temp_password",
                    "default temporary GitLab password applied",
                )

        if result.status in summary:
            summary[result.status] += 1
        elif result.status == "error":
            summary["errors"] += 1
        else:
            summary["skipped"] += 1
        summary["results"].append(result.as_dict())

    return summary
