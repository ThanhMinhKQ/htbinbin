import json
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timezone

from ...db.session import get_db
from ...db.models import InventoryAuditLog, User

router = APIRouter()


def log_inventory_action(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    actor_id: Optional[int] = None,
    changes: Optional[dict] = None
):
    entry = InventoryAuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        changes_json=json.dumps(changes, ensure_ascii=False, default=str) if changes else None
    )
    db.add(entry)


@router.get("/audit-log")
async def get_audit_log(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    action: Optional[str] = None,
    actor_id: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db)
):
    query = db.query(InventoryAuditLog).options(
        joinedload(InventoryAuditLog.actor)
    )

    if entity_type:
        query = query.filter(InventoryAuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(InventoryAuditLog.entity_id == entity_id)
    if action:
        query = query.filter(InventoryAuditLog.action == action)
    if actor_id:
        query = query.filter(InventoryAuditLog.actor_id == actor_id)

    total = query.count()
    logs = query.order_by(desc(InventoryAuditLog.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "data": [
            {
                "id": log.id,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "action": log.action,
                "actor_id": log.actor_id,
                "actor_name": log.actor.name if log.actor else None,
                "changes": json.loads(log.changes_json) if log.changes_json else None,
                "created_at": log.created_at.isoformat() if log.created_at else ""
            }
            for log in logs
        ],
        "total": total,
        "pages": (total + per_page - 1) // per_page
    }
