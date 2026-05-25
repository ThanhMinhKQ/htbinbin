from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import logging

from ...db.session import get_db
from ...db.models import InventoryTransfer, TransferImage
from ...services.inventory_storage import upload_inventory_image, delete_inventory_image

logger = logging.getLogger("binbin-inventory")
router = APIRouter()


@router.post("/transfer/{ticket_id}/images")
async def upload_transfer_images(
    ticket_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Phiếu không tồn tại")

    uploaded = []
    failed = []

    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            failed.append({"filename": file.filename, "error": "Không phải file ảnh"})
            continue

        image_bytes = await file.read()
        if len(image_bytes) > 10 * 1024 * 1024:
            failed.append({"filename": file.filename, "error": "File quá lớn (max 10MB)"})
            continue

        try:
            full_url, thumb_url, width, height = await upload_inventory_image(
                image_bytes=image_bytes,
                mime=file.content_type,
                prefix="transfers",
                entity_id=str(ticket_id),
                original_filename=file.filename or "image",
            )
            transfer_image = TransferImage(
                transfer_id=ticket_id,
                file_path=full_url,
                thumbnail_path=thumb_url,
                file_size=len(image_bytes),
                width=width,
                height=height,
                display_order=len(uploaded),
            )
            db.add(transfer_image)
            uploaded.append({"filename": file.filename})
        except Exception as exc:
            logger.error(f"Failed to upload transfer image {file.filename}: {exc}")
            failed.append({"filename": file.filename, "error": str(exc)})

    if uploaded:
        db.commit()

    if not uploaded and failed:
        raise HTTPException(
            status_code=500,
            detail=f"Không upload được ảnh nào. Lỗi: {failed[0]['error']}"
        )

    return {
        "status": "success",
        "message": f"Đã upload {len(uploaded)} hình ảnh" + (f", {len(failed)} ảnh lỗi" if failed else ""),
        "images": uploaded,
        "failed_files": failed,
    }


@router.get("/transfer/{ticket_id}/images")
async def get_transfer_images(
    ticket_id: int,
    db: Session = Depends(get_db)
):
    try:
        images = db.query(TransferImage).filter(
            TransferImage.transfer_id == ticket_id
        ).order_by(TransferImage.display_order).all()

        return {
            "images": [
                {
                    "id": img.id,
                    "file_path": img.file_path,
                    "thumbnail_path": img.thumbnail_path,
                    "file_size": img.file_size,
                    "width": img.width,
                    "height": img.height,
                    "uploaded_at": img.uploaded_at.isoformat() if img.uploaded_at else "",
                }
                for img in images
            ]
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/transfer/images/{image_id}")
async def delete_transfer_image(
    image_id: int,
    db: Session = Depends(get_db)
):
    img = db.query(TransferImage).get(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")

    await delete_inventory_image(img.file_path or "", img.thumbnail_path or "")
    db.delete(img)
    db.commit()
    return {"status": "success", "message": "Đã xoá ảnh"}
