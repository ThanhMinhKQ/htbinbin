from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone

from ...db.session import get_db
from ...db.models import (
    Product, InventoryLevel, StockMovement,
    InventoryReceipt, InventoryReceiptItem,
    TransactionTypeWMS, ImportImage
)
from ...core.image_optimizer import ImageOptimizer

router = APIRouter()

# ====================================================================
# SCHEMAS (Import)
# ====================================================================

class ImportItemSchema(BaseModel):
    product_id: int
    quantity: float      # Số lượng nhập (theo unit chọn)
    unit: str            # Đơn vị nhập (Thùng hoặc Chai)
    unit_price: float = 0

class ImportTicketSchema(BaseModel):
    warehouse_id: int    # Nhập vào kho nào (thường là kho tổng)
    supplier_name: str
    items: List[ImportItemSchema]
    notes: Optional[str] = None

# ====================================================================
# API: IMPORT
# ====================================================================

@router.post("/import")
async def create_import_ticket(
    payload: ImportTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Xử lý nhập hàng từ Nhà Cung Cấp
    """
    user_data = request.session.get("user")
    user_id = user_data.get("id") if user_data else None

    try:
        # 1. Tạo Phiếu Nhập
        code = f"PN_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        ticket = InventoryReceipt(
            code=code,
            warehouse_id=payload.warehouse_id,
            supplier_name=payload.supplier_name,
            creator_id=user_id,
            notes=payload.notes,
            total_amount=0
        )
        db.add(ticket)
        db.flush() 

        total_amount = 0
        stock_cache = {} 

        for item in payload.items:
            product = db.query(Product).get(item.product_id)
            if not product:
                continue

            # --- LOGIC QUY ĐỔI ---
            converted_qty = item.quantity
            if item.unit == product.packing_unit and product.conversion_rate > 1:
                converted_qty = item.quantity * product.conversion_rate
            
            line_total = item.quantity * item.unit_price
            total_amount += line_total

            # 2. Lưu chi tiết phiếu
            ticket_item = InventoryReceiptItem(
                receipt_id=ticket.id,
                product_id=product.id,
                input_quantity=item.quantity,
                input_unit=item.unit,
                converted_quantity=converted_qty,
                unit_price=item.unit_price,
                total_price=line_total
            )
            db.add(ticket_item)

            # 3. Cập nhật/Tạo Tồn Kho (InventoryLevel)
            stock = None
            if product.id in stock_cache:
                stock = stock_cache[product.id]
            else:
                stock = db.query(InventoryLevel).filter(
                    InventoryLevel.warehouse_id == payload.warehouse_id,
                    InventoryLevel.product_id == product.id
                ).first()

                if not stock:
                    stock = InventoryLevel(
                        warehouse_id=payload.warehouse_id,
                        product_id=product.id,
                        quantity=0
                    )
                    db.add(stock)
                
                stock_cache[product.id] = stock
            
            stock.quantity = float(stock.quantity) + converted_qty

            # 4. Ghi Sổ Cái
            trans = StockMovement(
                warehouse_id=payload.warehouse_id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.IMPORT_PO,
                quantity_change=converted_qty,
                balance_after=stock.quantity,
                ref_ticket_id=ticket.id,
                ref_ticket_type="IMPORT",
                actor_id=user_id
            )
            db.add(trans)

        ticket.total_amount = total_amount
        
        db.commit()
        return {
            "status": "success", 
            "message": f"Đã nhập kho thành công. Mã phiếu: {code}",
            "receipt_id": ticket.id  # NEW: Return ID for image upload
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ====================================================================
# API: LIST RECEIPTS (HISTORY)
# ====================================================================

@router.get("/receipts")
async def get_receipts(
    request: Request,
    branch_id: int = 0,    # Deprecated
    warehouse_id: int = 0, # [NEW]
    date_from: str = None, # [NEW]
    date_to: str = None,   # [NEW]
    page: int = 1,
    per_page: int = 10,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: str = None,
    db: Session = Depends(get_db)
):
    """
    Lấy danh sách phiếu nhập kho (InventoryReceipt).
    Lễ tân chỉ thấy phiếu do mình tạo, admin/manager thấy tất cả.
    """
    try:
        # Get user info from session
        user_data = request.session.get("user")
        user_id = user_data.get("id") if user_data else None
        
        query = db.query(InventoryReceipt)

        if warehouse_id > 0:
            query = query.filter(InventoryReceipt.warehouse_id == warehouse_id)
        elif branch_id > 0:
            # [FIX] Resolve Warehouse IDs from Branch ID
            from ...db.models import Branch, Warehouse
            
            branch = db.query(Branch).get(branch_id)
            is_admin = branch and branch.branch_code.upper() in ['ADMIN', 'BOSS', 'HEAD']
            
            wh_query = db.query(Warehouse.id)
            if is_admin:
                wh_query = wh_query.filter(
                    (Warehouse.branch_id == branch_id) | (Warehouse.branch_id.is_(None))
                )
            else:
                wh_query = wh_query.filter(Warehouse.branch_id == branch_id)
                
            warehouse_ids = [w[0] for w in wh_query.all()]
            
            if warehouse_ids:
                query = query.filter(InventoryReceipt.warehouse_id.in_(warehouse_ids))
            else:
                # Branch has no warehouses, return empty
                return {
                    "records": [],
                    "totalRecords": 0,
                    "totalPages": 0,
                    "currentPage": page
                }
        
        # [NEW] Filter by creator role
        # If user is "letan" (receptionist), only show receipts created by them
        if user_id:
            from ...db.models import User, Department
            user = db.query(User).options(joinedload(User.department)).filter(User.id == user_id).first()
            if user and user.department and user.department.role_code == "letan":
                # Lễ tân chỉ thấy phiếu do mình tạo
                query = query.filter(InventoryReceipt.creator_id == user_id)
            # Else: Admin/Manager thấy tất cả phiếu của chi nhánh
        
        # Filter by date range
        start_time = None
        end_time = None
        try:
            from ...core.utils import VN_TZ
            if date_from:
                f_date = datetime.strptime(date_from, "%Y-%m-%d").date()
                start_time = datetime.combine(f_date, datetime.min.time()).replace(tzinfo=VN_TZ)
            if date_to:
                t_date = datetime.strptime(date_to, "%Y-%m-%d").date()
                end_time = datetime.combine(t_date, datetime.max.time()).replace(tzinfo=VN_TZ)
        except ValueError:
            pass # Ignore invalid dates

        if start_time and end_time:
            query = query.filter(InventoryReceipt.created_at.between(start_time, end_time))
        elif start_time:
            query = query.filter(InventoryReceipt.created_at >= start_time)
        elif end_time:
            query = query.filter(InventoryReceipt.created_at <= end_time)

        # Search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (InventoryReceipt.code.ilike(search_term)) |
                (InventoryReceipt.supplier_name.ilike(search_term)) |
                (InventoryReceipt.notes.ilike(search_term))
            )
        
        # Sorting
        if sort_by == "items_count":
            query = query.options(joinedload(InventoryReceipt.creator), selectinload(InventoryReceipt.items))
            # Sort by number of items (requiring join or subquery, but simple count is safer if just property)
            # Since items is a relationship, we can do:
            query = query.outerjoin(InventoryReceiptItem).group_by(InventoryReceipt.id)
            if sort_order == "asc":
                query = query.order_by(func.count(InventoryReceiptItem.id).asc())
            else:
                query = query.order_by(func.count(InventoryReceiptItem.id).desc())
        elif hasattr(InventoryReceipt, sort_by):
            column = getattr(InventoryReceipt, sort_by)
            if sort_order == "asc":
                query = query.order_by(column.asc())
            else:
                query = query.order_by(column.desc())
        else:
            query = query.options(joinedload(InventoryReceipt.creator), selectinload(InventoryReceipt.items)).order_by(InventoryReceipt.created_at.desc())

        total_records = query.count()
        total_pages = (total_records + per_page - 1) // per_page

        offset = (page - 1) * per_page
        receipts = query.offset(offset).limit(per_page).all()

        # Format Response
        data = []
        for r in receipts:
            data.append({
                "id": r.id,
                "code": r.code,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "supplier_name": r.supplier_name,
                "creator_name": r.creator.name if r.creator else "N/A",
                "total_amount": r.total_amount,
                "notes": r.notes,
                "items_count": len(r.items)
            })

        return {
            "records": data,
            "totalRecords": total_records,
            "totalPages": total_pages,
            "currentPage": page
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class DeleteReceiptsSchema(BaseModel):
    ids: List[int]

@router.post("/receipts/delete")
async def delete_receipts(
    payload: DeleteReceiptsSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Xóa phiếu nhập kho (Revert Stock & Delete Data)
    Chỉ admin/manager được xóa, lễ tân không được xóa.
    """
    user_data = request.session.get("user")
    user_id = user_data.get("id") if user_data else None

    # [NEW] Check permission - Lễ tân không được xóa phiếu
    if user_id:
        from ...db.models import User, Department
        user = db.query(User).options(joinedload(User.department)).filter(User.id == user_id).first()
        if user and user.department and user.department.role_code == "letan":
            raise HTTPException(
                status_code=403, 
                detail="Lễ tân không có quyền xóa phiếu nhập. Vui lòng liên hệ quản lý."
            )

    try:
        for receipt_id in payload.ids:
            receipt = db.query(InventoryReceipt).get(receipt_id)
            if not receipt:
                continue
            
            # Revert Stock Logic
            for item in receipt.items:
                # 1. Update InventoryLevel (Subtract)
                stock = db.query(InventoryLevel).filter(
                    InventoryLevel.warehouse_id == receipt.warehouse_id,
                    InventoryLevel.product_id == item.product_id
                ).first()
                
                if stock:
                    stock.quantity = float(stock.quantity) - float(item.converted_quantity)
                
                # 2. Add StockMovement (Correction/Revert)
                trans = StockMovement(
                    warehouse_id=receipt.warehouse_id,
                    product_id=item.product_id,
                    transaction_type=TransactionTypeWMS.ADJUSTMENT, # Using Adjustment for revert
                    quantity_change=-float(item.converted_quantity),
                    balance_after=stock.quantity if stock else 0,
                    ref_ticket_id=receipt.id,
                    ref_ticket_type="IMPORT_DELETE",
                    actor_id=user_id
                )
                db.add(trans)
            
            # Finally delete the receipt (Cascade will delete items)
            db.delete(receipt)
        
        db.commit()
        return {"status": "success", "message": f"Đã xóa {len(payload.ids)} phiếu nhập kho."}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/receipts/{receipt_id}")
async def get_receipt_detail(
    receipt_id: int,
    db: Session = Depends(get_db)
):
    try:
        receipt = db.query(InventoryReceipt).options(
            joinedload(InventoryReceipt.creator),
            selectinload(InventoryReceipt.items).joinedload(InventoryReceiptItem.product).joinedload(Product.category)
        ).get(receipt_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Phiếu nhập không tồn tại")
        
        items_data = []
        for item in receipt.items:
            items_data.append({
                "id": item.id,
                "product_id": item.product_id,
                "product_code": item.product.code,
                "product_name": item.product.name,
                "quantity": item.input_quantity,
                "unit": item.input_unit,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
                "category_id": item.product.category_id,
                "category_name": item.product.category.name if item.product.category else "N/A"
            })
            
        return {
            "id": receipt.id,
            "code": receipt.code,
            "created_at": receipt.created_at.isoformat() if receipt.created_at else "",
            "supplier_name": receipt.supplier_name,
            "creator_name": receipt.creator.name if receipt.creator else "N/A",
            "notes": receipt.notes,
            "total_amount": receipt.total_amount,
            "items": items_data
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/receipts/{receipt_id}")
async def update_receipt(
    receipt_id: int,
    payload: ImportTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Cập nhật phiếu nhập (Revert Old -> Apply New)
    """
    user_data = request.session.get("user")
    user_id = user_data.get("id") if user_data else None

    try:
        receipt = db.query(InventoryReceipt).get(receipt_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Phiếu nhập không tồn tại")

        # 1. REVERT OLD STOCK
        for item in receipt.items:
            stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == receipt.warehouse_id,
                InventoryLevel.product_id == item.product_id
            ).first()
            if stock:
                stock.quantity = float(stock.quantity) - float(item.converted_quantity)
                # Log Revert Movement
                db.add(StockMovement(
                    warehouse_id=receipt.warehouse_id, 
                    product_id=item.product_id,
                    transaction_type=TransactionTypeWMS.ADJUSTMENT,
                    quantity_change=-float(item.converted_quantity),
                    balance_after=stock.quantity,
                    ref_ticket_id=receipt.id,
                    ref_ticket_type="IMPORT_UPDATE_REVERT",
                    actor_id=user_id
                ))
        
        # Delete old items
        for item in receipt.items:
            db.delete(item)
        db.flush()

        # 2. APPLY NEW DATA
        receipt.supplier_name = payload.supplier_name
        receipt.notes = payload.notes
        
        total_amount = 0
        stock_cache = {} 

        for item in payload.items:
            product = db.query(Product).get(item.product_id)
            if not product:
                continue

            converted_qty = item.quantity
            if item.unit == product.packing_unit and product.conversion_rate > 1:
                converted_qty = item.quantity * product.conversion_rate
            
            line_total = item.quantity * item.unit_price
            total_amount += line_total

            # Create Item
            new_item = InventoryReceiptItem(
                receipt_id=receipt.id,
                product_id=product.id,
                input_quantity=item.quantity,
                input_unit=item.unit,
                converted_quantity=converted_qty,
                unit_price=item.unit_price,
                total_price=line_total
            )
            db.add(new_item)

            # Update Stock
            stock = None
            if product.id in stock_cache:
                stock = stock_cache[product.id]
            else:
                stock = db.query(InventoryLevel).filter(
                    InventoryLevel.warehouse_id == payload.warehouse_id,
                    InventoryLevel.product_id == product.id
                ).first()
                if not stock:
                    stock = InventoryLevel(
                        warehouse_id=payload.warehouse_id,
                        product_id=product.id,
                        quantity=0
                    )
                    db.add(stock)
                stock_cache[product.id] = stock
            
            stock.quantity = float(stock.quantity) + converted_qty

            # Log Apply Movement
            db.add(StockMovement(
                warehouse_id=payload.warehouse_id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.IMPORT_PO, # Re-logging as new import
                quantity_change=converted_qty,
                balance_after=stock.quantity,
                ref_ticket_id=receipt.id,
                ref_ticket_type="IMPORT_UPDATE_APPLY",
                actor_id=user_id
            ))

        receipt.total_amount = total_amount
        db.commit()
        return {"status": "success", "message": "Cập nhật phiếu nhập thành công"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ====================================================================
# API: IMAGE UPLOAD FOR IMPORTS
# ====================================================================

@router.post("/import/{receipt_id}/images")
async def upload_import_images(
    receipt_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload multiple images for an import receipt.
    Images will be optimized and thumbnails will be generated.
    """
    try:
        # Verify receipt exists
        receipt = db.query(InventoryReceipt).get(receipt_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Phiếu nhập không tồn tại")
        
        uploaded_images = []
        
        for file in files:
            # Validate file type
            if not file.content_type or not file.content_type.startswith('image/'):
                continue  # Skip non-image files
            
            # Read file bytes
            image_bytes = await file.read()
            
            # Validate file size (max 10MB)
            if len(image_bytes) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File {file.filename} quá lớn (max 10MB)")
            
            try:
                # Save optimized image and thumbnail
                full_path, thumb_path, width, height = ImageOptimizer.save_optimized(
                    image_bytes,
                    receipt_id,
                    file.filename
                )
                
                # Create database record
                import_image = ImportImage(
                    receipt_id=receipt_id,
                    file_path=full_path,
                    thumbnail_path=thumb_path,
                    file_size=len(image_bytes),
                    width=width,
                    height=height,
                    display_order=len(uploaded_images)
                )
                db.add(import_image)
                uploaded_images.append({
                    "filename": file.filename,
                    "size": len(image_bytes),
                    "width": width,
                    "height": height
                })
                
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

@router.get("/import/{receipt_id}/images")
async def get_import_images(
    receipt_id: int,
    db: Session = Depends(get_db)
):
    """
    Get all images for an import receipt.
    """
    try:
        images = db.query(ImportImage).filter(
            ImportImage.receipt_id == receipt_id
        ).order_by(ImportImage.display_order).all()
        
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
                    "display_order": img.display_order
                }
                for img in images
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/images/{image_id}")
async def delete_import_image(
    image_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete an import image and its files.
    """
    try:
        image = db.query(ImportImage).get(image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Hình ảnh không tồn tại")
        
        # Delete files from filesystem
        ImageOptimizer.delete_image(image.file_path, image.thumbnail_path)
        
        # Delete database record
        db.delete(image)
        db.commit()
        
        return {"status": "success", "message": "Đã xóa hình ảnh"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
