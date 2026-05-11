from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from ...db.session import get_db
from ...db.models import InventoryTransfer, TransferImage
from ...core.image_optimizer import ImageOptimizer

router = APIRouter()


@router.post("/transfer/{ticket_id}/images")
async def upload_transfer_images(
    ticket_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    try:
        ticket = db.query(InventoryTransfer).get(ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Phiếu không tồn tại")

        uploaded_images = []

        for file in files:
            if not file.content_type or not file.content_type.startswith('image/'):
                continue

            image_bytes = await file.read()
            if len(image_bytes) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File {file.filename} quá lớn (max 10MB)")

            try:
                full_path, thumb_path, width, height = ImageOptimizer.save_optimized(
                    image_bytes,
                    f"TR_{ticket_id}",
                    file.filename
                )

                transfer_image = TransferImage(
                    transfer_id=ticket_id,
                    file_path=full_path,
                    thumbnail_path=thumb_path,
                    file_size=len(image_bytes),
                    width=width,
                    height=height,
                    display_order=len(uploaded_images)
                )
                db.add(transfer_image)
                uploaded_images.append({"filename": file.filename})

            except Exception as e:
                print(f"Error processing image {file.filename}: {e}")
                continue

        db.commit()
        return {
            "status": "success",
            "message": f"Đã upload {len(uploaded_images)} hình ảnh",
            "images": uploaded_images
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


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
                    "file_path": "/" + img.file_path if img.file_path and not img.file_path.startswith("/") else img.file_path,
                    "thumbnail_path": "/" + img.thumbnail_path if img.thumbnail_path and not img.thumbnail_path.startswith("/") else img.thumbnail_path,
                    "file_size": img.file_size,
                    "width": img.width,
                    "height": img.height,
                    "uploaded_at": img.uploaded_at.isoformat() if img.uploaded_at else ""
                }
                for img in images
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
