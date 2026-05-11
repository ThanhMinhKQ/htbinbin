from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from ...db.session import get_db
from ...db.models import Supplier

router = APIRouter()


class SupplierCreate(BaseModel):
    code: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    tax_code: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    tax_code: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/suppliers")
async def get_suppliers(
    active_only: bool = False,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Supplier)
    if active_only:
        query = query.filter(Supplier.is_active == True)
    if search:
        term = f"%{search}%"
        query = query.filter(
            (Supplier.name.ilike(term)) |
            (Supplier.code.ilike(term)) |
            (Supplier.phone.ilike(term)) |
            (Supplier.contact_person.ilike(term))
        )
    suppliers = query.order_by(Supplier.name).all()
    return {
        "data": [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "phone": s.phone,
                "email": s.email,
                "address": s.address,
                "tax_code": s.tax_code,
                "contact_person": s.contact_person,
                "notes": s.notes,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat() if s.created_at else ""
            }
            for s in suppliers
        ]
    }


@router.post("/suppliers")
async def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db)
):
    if payload.code:
        existing = db.query(Supplier).filter(Supplier.code == payload.code).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Mã NCC '{payload.code}' đã tồn tại")

    supplier = Supplier(
        code=payload.code,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        tax_code=payload.tax_code,
        contact_person=payload.contact_person,
        notes=payload.notes
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return {"status": "success", "id": supplier.id, "message": f"Đã tạo NCC: {supplier.name}"}


@router.put("/suppliers/{supplier_id}")
async def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: Session = Depends(get_db)
):
    supplier = db.query(Supplier).get(supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="NCC không tồn tại")

    if payload.name is not None:
        supplier.name = payload.name
    if payload.phone is not None:
        supplier.phone = payload.phone
    if payload.email is not None:
        supplier.email = payload.email
    if payload.address is not None:
        supplier.address = payload.address
    if payload.tax_code is not None:
        supplier.tax_code = payload.tax_code
    if payload.contact_person is not None:
        supplier.contact_person = payload.contact_person
    if payload.notes is not None:
        supplier.notes = payload.notes
    if payload.is_active is not None:
        supplier.is_active = payload.is_active

    db.commit()
    return {"status": "success", "message": f"Đã cập nhật NCC: {supplier.name}"}


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db)
):
    supplier = db.query(Supplier).get(supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="NCC không tồn tại")

    from ...db.models import InventoryReceipt
    used = db.query(InventoryReceipt).filter(InventoryReceipt.supplier_id == supplier_id).first()
    if used:
        supplier.is_active = False
        db.commit()
        return {"status": "success", "message": f"NCC '{supplier.name}' đã được ẩn (đang có phiếu nhập liên kết)"}

    db.delete(supplier)
    db.commit()
    return {"status": "success", "message": f"Đã xóa NCC: {supplier.name}"}
