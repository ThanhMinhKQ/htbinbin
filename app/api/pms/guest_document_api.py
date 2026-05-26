"""
Guest Document API - Handle upload, listing, and deletion of guest document images.
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .pms_helpers import _require_login
from ...db.session import get_db
from ...db.models import Guest, GuestDocument
from ...services.guest_storage import upload_guest_document, delete_guest_document

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/pms/crm/guests/{guest_id}/documents", tags=["PMS Guest Documents"])
async def upload_document(
    request: Request,
    guest_id: int,
    file: UploadFile = File(..., description="Ảnh giấy tờ tùy thân"),
    doc_type: str = Form(..., description="Loại giấy tờ: cccd_front | cccd_back | passport | visa"),
    db: Session = Depends(get_db),
):
    """
    Tải ảnh giấy tờ lên, lưu trữ và lưu vào DB.
    """
    # 1. Require login
    current_user = _require_login(request)
    user_id = current_user.id if current_user else None

    # 2. Validate doc_type
    doc_type = doc_type.strip().lower()
    if doc_type not in ("cccd_front", "cccd_back", "passport", "visa"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": f"Loại giấy tờ '{doc_type}' không hợp lệ"}
        )

    # 3. Check guest exists
    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at == None).first()
    if not guest:
        return JSONResponse(
            status_code=404,
            content={"success": False, "detail": f"Không tìm thấy khách hàng với ID {guest_id}"}
        )

    # 4. Read file bytes
    try:
        contents = await file.read()
    except Exception as e:
        logger.error(f"Error reading guest document file: {e}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": "Lỗi khi đọc file ảnh"}
        )

    # 5. Check size (max 10MB)
    if len(contents) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": "Kích thước ảnh quá lớn (tối đa 10MB)"}
        )

    # 6. Upload
    try:
        mime = file.content_type or "image/jpeg"
        full_url, thumb_url, width, height, file_size = await upload_guest_document(
            image_bytes=contents,
            mime=mime,
            guest_id=str(guest_id),
            original_filename=file.filename or f"{doc_type}.jpg"
        )
    except Exception as e:
        logger.exception("Failed to upload guest document image")
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Không thể lưu trữ ảnh giấy tờ: {str(e)}"}
        )

    # 7. Check if document of this type already exists for this guest
    existing_doc = db.query(GuestDocument).filter(
        GuestDocument.guest_id == guest_id,
        GuestDocument.doc_type == doc_type
    ).first()

    if existing_doc:
        # Delete old file from storage
        try:
            await delete_guest_document(existing_doc.file_path, existing_doc.thumbnail_path or "")
        except Exception:
            logger.exception("Failed to delete old guest document image from storage")

        # Update existing record
        existing_doc.file_path = full_url
        existing_doc.thumbnail_path = thumb_url
        existing_doc.file_size = file_size
        existing_doc.width = width
        existing_doc.height = height
        existing_doc.uploaded_by = user_id
        doc_obj = existing_doc
    else:
        # Create new record
        new_doc = GuestDocument(
            guest_id=guest_id,
            doc_type=doc_type,
            file_path=full_url,
            thumbnail_path=thumb_url,
            file_size=file_size,
            width=width,
            height=height,
            uploaded_by=user_id
        )
        db.add(new_doc)
        doc_obj = new_doc

    try:
        db.commit()
        db.refresh(doc_obj)
    except Exception as e:
        db.rollback()
        logger.exception("Database error while saving guest document")
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": "Lỗi hệ thống khi lưu trữ thông tin cơ sở dữ liệu"}
        )

    return JSONResponse({
        "success": True,
        "data": {
            "id": doc_obj.id,
            "guest_id": doc_obj.guest_id,
            "doc_type": doc_obj.doc_type,
            "file_path": doc_obj.file_path,
            "thumbnail_path": doc_obj.thumbnail_path,
            "file_size": doc_obj.file_size,
            "width": doc_obj.width,
            "height": doc_obj.height,
            "created_at": doc_obj.created_at.isoformat() if doc_obj.created_at else None
        }
    })


@router.get("/api/pms/crm/guests/{guest_id}/documents", tags=["PMS Guest Documents"])
def get_documents(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách ảnh giấy tờ của một khách hàng.
    """
    _require_login(request)

    # Check guest exists
    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at == None).first()
    if not guest:
        return JSONResponse(
            status_code=404,
            content={"success": False, "detail": f"Không tìm thấy khách hàng với ID {guest_id}"}
        )

    docs = db.query(GuestDocument).filter(GuestDocument.guest_id == guest_id).order_by(GuestDocument.created_at.desc()).all()

    return JSONResponse({
        "success": True,
        "data": [
            {
                "id": doc.id,
                "guest_id": doc.guest_id,
                "doc_type": doc.doc_type,
                "file_path": doc.file_path,
                "thumbnail_path": doc.thumbnail_path,
                "file_size": doc.file_size,
                "width": doc.width,
                "height": doc.height,
                "created_at": doc.created_at.isoformat() if doc.created_at else None
            }
            for doc in docs
        ]
    })


@router.delete("/api/pms/crm/guests/{guest_id}/documents/{doc_id}", tags=["PMS Guest Documents"])
async def delete_document(
    request: Request,
    guest_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
):
    """
    Xóa ảnh giấy tờ của khách hàng.
    """
    _require_login(request)

    # Find document
    doc = db.query(GuestDocument).filter(
        GuestDocument.id == doc_id,
        GuestDocument.guest_id == guest_id
    ).first()

    if not doc:
        return JSONResponse(
            status_code=404,
            content={"success": False, "detail": "Không tìm thấy ảnh giấy tờ để xóa"}
        )

    # Delete from storage
    try:
        await delete_guest_document(doc.file_path, doc.thumbnail_path or "")
    except Exception as e:
        logger.error(f"Failed to delete guest document from storage: {e}")
        # Continue to delete DB record anyway to prevent orphan reference issues

    # Delete from DB
    try:
        db.delete(doc)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete guest document from database")
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": "Lỗi hệ thống khi xóa thông tin cơ sở dữ liệu"}
        )

    return JSONResponse({
        "success": True,
        "message": "Đã xóa ảnh giấy tờ thành công"
    })
