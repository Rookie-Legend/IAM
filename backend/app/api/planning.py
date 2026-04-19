from datetime import date, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import get_database
from app.models.user import UserInDB


router = APIRouter(prefix="/api/planning", tags=["Planning"])

ADMIN_ROLES = {"Security Admin", "System Administrator", "HR Manager", "admin"}
STATUSES = {"planned", "active", "blocked", "done"}
PRIORITIES = {"low", "medium", "high"}
ITEM_TYPES = {"task", "milestone", "release", "meeting"}


class PlanningItemRequest(BaseModel):
    title: str
    description: str = ""
    department: str = ""
    owner: str = ""
    start: str
    end: str
    status: str = "planned"
    priority: str = "medium"
    type: str = "task"


def is_admin(user: UserInDB) -> bool:
    return user.role in ADMIN_ROLES


def parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_name} must be YYYY-MM-DD")


def clean_payload(payload: PlanningItemRequest, user: UserInDB) -> dict:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    start_date = parse_date(payload.start, "Start date")
    end_date = parse_date(payload.end, "End date")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="End date cannot be before start date")

    status_value = payload.status.strip().lower()
    priority_value = payload.priority.strip().lower()
    type_value = payload.type.strip().lower()

    if status_value not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if priority_value not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    if type_value not in ITEM_TYPES:
        raise HTTPException(status_code=400, detail="Invalid item type")

    department = payload.department.strip() if is_admin(user) else user.department
    if not department:
        raise HTTPException(status_code=400, detail="Department is required")

    owner = payload.owner.strip() or user.full_name or user.username

    return {
        "title": title,
        "description": payload.description.strip(),
        "department": department,
        "owner": owner,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "status": status_value,
        "priority": priority_value,
        "type": type_value,
    }


def serialize_item(item: dict) -> dict:
    return {
        "id": str(item["_id"]),
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "department": item.get("department", ""),
        "owner": item.get("owner", ""),
        "owner_id": item.get("owner_id", ""),
        "start": item.get("start", ""),
        "end": item.get("end", ""),
        "status": item.get("status", "planned"),
        "priority": item.get("priority", "medium"),
        "type": item.get("type", "task"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def object_id_or_404(item_id: str) -> ObjectId:
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=404, detail="Planning item not found")
    return ObjectId(item_id)


async def get_accessible_item(db, item_id: str, user: UserInDB) -> dict:
    item = await db["planning_items"].find_one({"_id": object_id_or_404(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Planning item not found")
    if not is_admin(user) and item.get("department") != user.department:
        raise HTTPException(status_code=403, detail="You can only manage your department plan")
    return item


@router.get("/departments")
async def get_departments(
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_database),
):
    if not is_admin(current_user):
        return [current_user.department]

    departments = await db["users"].distinct("department", {"disabled": {"$ne": True}})
    return sorted(dept for dept in departments if dept)


@router.get("/items")
async def list_planning_items(
    department: str = Query(default=""),
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_database),
):
    query = {}
    if is_admin(current_user):
        selected_department = department.strip()
        if selected_department and selected_department != "all":
            query["department"] = selected_department
    else:
        query["department"] = current_user.department

    cursor = db["planning_items"].find(query).sort([("start", 1), ("end", 1), ("title", 1)])
    return [serialize_item(item) async for item in cursor]


@router.post("/items")
async def create_planning_item(
    payload: PlanningItemRequest,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_database),
):
    now = datetime.utcnow()
    document = clean_payload(payload, current_user)
    document.update({
        "owner_id": current_user.user_id,
        "created_at": now,
        "updated_at": now,
    })

    result = await db["planning_items"].insert_one(document)
    created = await db["planning_items"].find_one({"_id": result.inserted_id})
    return serialize_item(created)


@router.put("/items/{item_id}")
async def update_planning_item(
    item_id: str,
    payload: PlanningItemRequest,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_database),
):
    await get_accessible_item(db, item_id, current_user)
    update = clean_payload(payload, current_user)
    update["updated_at"] = datetime.utcnow()

    await db["planning_items"].update_one(
        {"_id": object_id_or_404(item_id)},
        {"$set": update},
    )
    updated = await db["planning_items"].find_one({"_id": object_id_or_404(item_id)})
    return serialize_item(updated)


@router.delete("/items/{item_id}")
async def delete_planning_item(
    item_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_database),
):
    await get_accessible_item(db, item_id, current_user)
    await db["planning_items"].delete_one({"_id": object_id_or_404(item_id)})
    return {"status": "deleted"}
