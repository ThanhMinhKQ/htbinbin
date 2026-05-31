# app/api/handbook.py
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import os

from ..db.session import get_db
from ..db.models import HandbookEntry, User
from ..core.permissions import is_manager

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

VALID_SEVERITIES = {"urgent", "serious", "normal", "tip"}
VALID_CATEGORIES = {"general", "checkin", "ota", "security", "technical", "regulation", "surcharge"}


def _is_admin(user_data: dict) -> bool:
    # "admin" ở đây nghĩa là MANAGER trở lên (gồm quanly) — giữ nguyên hành vi cũ
    return is_manager(user_data)


def _serialize(e: HandbookEntry) -> dict:
    return {
        "id": e.id,
        "situation": e.situation,
        "solution": e.solution,
        "severity": e.severity or "normal",
        "category": e.category or "general",
        "shared_by": e.shared_by or "",
        "is_approved": e.is_approved,
        "created_by": e.created_by,
        "creator_name": e.creator.full_name if e.creator else None,
    }


@router.get("/handbook", response_class=HTMLResponse)
async def handbook_page(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("handbook.html", {
        "request": request,
        "user": user_data,
        "active_page": "handbook",
        "is_admin": _is_admin(user_data),
    })


@router.get("/api/handbook/entries")
async def list_entries(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user_id  = user_data.get("id")
    is_admin = _is_admin(user_data)

    approved = (
        db.query(HandbookEntry)
        .filter(HandbookEntry.is_approved == True)
        .order_by(HandbookEntry.severity, HandbookEntry.id)
        .all()
    )

    if is_admin:
        pending = db.query(HandbookEntry).filter(HandbookEntry.is_approved == False).order_by(HandbookEntry.id).all()
    else:
        pending = (
            db.query(HandbookEntry)
            .filter(HandbookEntry.is_approved == False, HandbookEntry.created_by == user_id)
            .order_by(HandbookEntry.id)
            .all()
        )

    return JSONResponse({
        "approved": [_serialize(e) for e in approved],
        "pending":  [_serialize(e) for e in pending],
    })


@router.post("/api/handbook/entries")
async def create_entry(
    request:   Request,
    situation: str           = Form(...),
    solution:  str           = Form(...),
    severity:  str           = Form("normal"),
    category:  str           = Form("general"),
    shared_by: Optional[str] = Form(None),
    db:        Session       = Depends(get_db),
):
    user_data = request.session.get("user")
    if not user_data:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if severity not in VALID_SEVERITIES: severity = "normal"
    if category not in VALID_CATEGORIES: category = "general"

    entry = HandbookEntry(
        situation=situation.strip(),
        solution=solution.strip(),
        severity=severity,
        category=category,
        shared_by=(shared_by or "").strip() or None,
        is_approved=_is_admin(user_data),
        created_by=user_data.get("id"),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return JSONResponse({"ok": True, "id": entry.id, "is_approved": entry.is_approved})


@router.put("/api/handbook/entries/{entry_id}")
async def update_entry(
    entry_id:  int,
    request:   Request,
    situation: str           = Form(...),
    solution:  str           = Form(...),
    severity:  str           = Form("normal"),
    category:  str           = Form("general"),
    shared_by: Optional[str] = Form(None),
    db:        Session       = Depends(get_db),
):
    user_data = request.session.get("user")
    if not user_data or not _is_admin(user_data):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    entry = db.query(HandbookEntry).filter(HandbookEntry.id == entry_id).first()
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)

    if severity not in VALID_SEVERITIES: severity = "normal"
    if category not in VALID_CATEGORIES: category = "general"

    entry.situation = situation.strip()
    entry.solution  = solution.strip()
    entry.severity  = severity
    entry.category  = category
    entry.shared_by = (shared_by or "").strip() or None
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/handbook/entries/{entry_id}/approve")
async def approve_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data or not _is_admin(user_data):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    entry = db.query(HandbookEntry).filter(HandbookEntry.id == entry_id).first()
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)

    entry.is_approved = True
    db.commit()
    return JSONResponse({"ok": True})


@router.delete("/api/handbook/entries/{entry_id}")
async def delete_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    entry = db.query(HandbookEntry).filter(HandbookEntry.id == entry_id).first()
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)

    if not _is_admin(user_data):
        if entry.is_approved or entry.created_by != user_data.get("id"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

    db.delete(entry)
    db.commit()
    return JSONResponse({"ok": True})
