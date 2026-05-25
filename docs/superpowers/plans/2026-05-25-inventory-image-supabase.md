# Inventory Image Upload — Supabase Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix inventory image upload persistence bugs and migrate storage from local filesystem to Supabase bucket `inventory`, with local fallback.

**Architecture:** New service `app/services/inventory_storage.py` replaces `ImageOptimizer.save_optimized()` in the two upload API handlers. Images are stored in Supabase bucket `inventory` (full image + thumbnail, both WebP). DB rows continue storing paths — now Supabase public URLs instead of local relative paths. A one-time migration script moves existing local images to Supabase.

**Tech Stack:** Python, FastAPI, httpx (already in project), Pillow (already used), SQLAlchemy, Supabase Storage REST API, vanilla JS (Alpine.js via mixin).

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/core/config.py` | Modify | Add `INVENTORY_STORAGE_BUCKET` setting |
| `app/services/inventory_storage.py` | **Create** | Upload/delete inventory images via Supabase; local fallback |
| `app/api/inventory/transfer_images.py` | Modify | Use new service; fix silent error swallowing |
| `app/api/inventory/imports.py` | Modify | Use new service; fix silent error swallowing |
| `app/static/js/inventory/shared/approvals.js` | Modify | Surface upload errors to user in `uploadReceiptImages` |
| `app/static/js/inventory/shared/imports.js` | Modify | Surface upload errors to user in `submitImport` |
| `scripts/migrate_images_to_supabase.py` | **Create** | One-time migration: local files → Supabase, update DB |
| `tests/test_inventory_storage.py` | **Create** | Unit tests for inventory_storage service |

---

## Task 1: Add `INVENTORY_STORAGE_BUCKET` config

**Files:**
- Modify: `app/core/config.py`

- [ ] **Step 1: Add the config field**

In `app/core/config.py`, after line 21 (`SUPABASE_STORAGE_BUCKET: str = "shift-notifications"`), add:

```python
    INVENTORY_STORAGE_BUCKET: str = "inventory"
```

Result (lines 18–22 after change):
```python
    # Supabase Storage Configuration
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "shift-notifications"
    INVENTORY_STORAGE_BUCKET: str = "inventory"
```

- [ ] **Step 2: Verify import works**

```bash
cd /Users/thanhminh/Desktop/xxx
python -c "from app.core.config import settings; print(settings.INVENTORY_STORAGE_BUCKET)"
```

Expected output: `inventory`

- [ ] **Step 3: Commit**

```bash
git add app/core/config.py
git commit -m "config: add INVENTORY_STORAGE_BUCKET setting for Supabase"
```

---

## Task 2: Create `inventory_storage` service with tests

**Files:**
- Create: `app/services/inventory_storage.py`
- Create: `tests/test_inventory_storage.py`

- [ ] **Step 1: Write failing tests first**

Create `tests/test_inventory_storage.py`:

```python
"""
Tests for app/services/inventory_storage.py

Uses unittest + mock — no live Supabase or filesystem required.
"""
import io
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image


def _make_webp_bytes(width=100, height=100) -> bytes:
    """Generate minimal valid WebP image bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    img.save(buf, format="WEBP")
    return buf.getvalue()


class TestBuildObjectPath(unittest.TestCase):
    def test_import_path_format(self):
        from app.services.inventory_storage import _build_object_path
        path = _build_object_path("imports", "42", "img_abc.webp", is_thumb=False)
        # Should be: imports/YYYY/MM/42/full/img_abc.webp
        parts = path.split("/")
        self.assertEqual(parts[0], "imports")
        self.assertEqual(parts[3], "42")
        self.assertEqual(parts[4], "full")
        self.assertEqual(parts[5], "img_abc.webp")

    def test_transfer_thumb_path_format(self):
        from app.services.inventory_storage import _build_object_path
        path = _build_object_path("transfers", "TR_99", "img_xyz.webp", is_thumb=True)
        parts = path.split("/")
        self.assertEqual(parts[0], "transfers")
        self.assertEqual(parts[3], "TR_99")
        self.assertEqual(parts[4], "thumbnails")


class TestOptimizeToWebp(unittest.TestCase):
    def test_returns_webp_bytes(self):
        from app.services.inventory_storage import _optimize_to_webp
        input_bytes = _make_webp_bytes(200, 200)
        result = _optimize_to_webp(input_bytes, max_size=(1920, 1080))
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.format, "WEBP")

    def test_resizes_large_image(self):
        from app.services.inventory_storage import _optimize_to_webp
        # 3000x2000 image should be resized down
        buf = io.BytesIO()
        Image.new("RGB", (3000, 2000)).save(buf, format="WEBP")
        result = _optimize_to_webp(buf.getvalue(), max_size=(1920, 1080))
        img = Image.open(io.BytesIO(result))
        self.assertLessEqual(img.size[0], 1920)
        self.assertLessEqual(img.size[1], 1080)

    def test_small_image_dimensions_preserved(self):
        from app.services.inventory_storage import _optimize_to_webp
        input_bytes = _make_webp_bytes(100, 100)
        result = _optimize_to_webp(input_bytes, max_size=(1920, 1080))
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (100, 100))


class TestLocalFallback(unittest.IsolatedAsyncioTestCase):
    async def test_local_fallback_writes_file_and_returns_paths(self):
        from app.services.inventory_storage import _save_local
        import tempfile, os

        image_bytes = _make_webp_bytes()
        thumb_bytes = _make_webp_bytes(100, 100)

        with tempfile.TemporaryDirectory() as tmp:
            full_url, thumb_url, w, h = await _save_local(
                image_bytes, thumb_bytes,
                prefix="imports", entity_id="1", filename="test.webp",
                base_dir=Path(tmp)
            )
            # URLs should be relative paths starting with /uploads/inventory/
            self.assertTrue(full_url.startswith("/uploads/inventory/imports/"))
            self.assertTrue(thumb_url.startswith("/uploads/inventory/imports/"))
            # Files should actually exist
            # full_url is like /uploads/inventory/imports/YYYY/MM/1/full/test.webp
            rel = full_url.lstrip("/")
            # base_dir is used as root, so path under tmp
            full_path = Path(tmp) / rel.replace("uploads/inventory/", "")
            self.assertTrue(full_path.exists(), f"Expected file at {full_path}")


class TestUploadInventoryImageSupabasePath(unittest.IsolatedAsyncioTestCase):
    async def test_supabase_upload_returns_public_url(self):
        """When Supabase is configured and upload succeeds, return public URL."""
        image_bytes = _make_webp_bytes(200, 200)

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.inventory_storage.settings") as mock_settings, \
             patch("app.services.inventory_storage.httpx.AsyncClient", return_value=mock_client):
            mock_settings.SUPABASE_URL = "https://abc.supabase.co"
            mock_settings.SUPABASE_SERVICE_KEY = "service_key_xyz"
            mock_settings.INVENTORY_STORAGE_BUCKET = "inventory"

            from app.services.inventory_storage import upload_inventory_image
            full_url, thumb_url, w, h = await upload_inventory_image(
                image_bytes=image_bytes,
                mime="image/jpeg",
                prefix="imports",
                entity_id="10",
                original_filename="photo.jpg"
            )

        self.assertIn("supabase.co", full_url)
        self.assertIn("supabase.co", thumb_url)
        self.assertIn("/full/", full_url)
        self.assertIn("/thumbnails/", thumb_url)
        self.assertIsInstance(w, int)
        self.assertIsInstance(h, int)

    async def test_raises_on_total_failure(self):
        """If Supabase fails AND local write fails, raise ValueError."""
        image_bytes = _make_webp_bytes()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.inventory_storage.settings") as mock_settings, \
             patch("app.services.inventory_storage.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.inventory_storage._save_local", side_effect=OSError("disk full")):
            mock_settings.SUPABASE_URL = "https://abc.supabase.co"
            mock_settings.SUPABASE_SERVICE_KEY = "service_key_xyz"
            mock_settings.INVENTORY_STORAGE_BUCKET = "inventory"

            from app.services.inventory_storage import upload_inventory_image
            with self.assertRaises(ValueError):
                await upload_inventory_image(
                    image_bytes=image_bytes,
                    mime="image/jpeg",
                    prefix="imports",
                    entity_id="10",
                    original_filename="photo.jpg"
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect failures (module not found)**

```bash
cd /Users/thanhminh/Desktop/xxx
python -m pytest tests/test_inventory_storage.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or `ImportError` for `app.services.inventory_storage`.

- [ ] **Step 3: Create `app/services/inventory_storage.py`**

```python
"""
Inventory image storage service.

Uploads full image + thumbnail to Supabase bucket "inventory".
Falls back to local filesystem (absolute path) when Supabase is unconfigured.
"""
import io
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple

import httpx
from PIL import Image

from app.core.config import settings

logger = logging.getLogger("binbin-inventory-storage")

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_SIZE = (1920, 1080)   # Full image max dimensions
THUMB_SIZE = (300, 300)   # Thumbnail max dimensions
WEBP_QUALITY = 85

# Absolute base for local fallback — always resolves from this file's location
_APP_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_BASE = _APP_ROOT / "uploads" / "inventory"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _build_object_path(prefix: str, entity_id: str, filename: str, is_thumb: bool) -> str:
    """
    Build Supabase object path (also used as local relative path).

    Pattern: {prefix}/{year}/{month}/{entity_id}/{full|thumbnails}/{filename}
    Example: imports/2026/05/42/full/img_20260525_abc12345.webp
    """
    now = datetime.now()
    sub = "thumbnails" if is_thumb else "full"
    return f"{prefix}/{now.year}/{now.month:02d}/{entity_id}/{sub}/{filename}"


def _optimize_to_webp(image_bytes: bytes, max_size: Tuple[int, int] = MAX_SIZE) -> bytes:
    """Convert image bytes to WebP, resize if larger than max_size."""
    img = Image.open(io.BytesIO(image_bytes))

    # Normalize mode to RGB
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img.thumbnail(max_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=6)
    buf.seek(0)
    return buf.read()


def _get_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    img = Image.open(io.BytesIO(image_bytes))
    return img.size  # (width, height)


def _unique_filename(original_filename: str, image_bytes: bytes) -> str:
    file_hash = hashlib.md5(image_bytes).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"img_{timestamp}_{file_hash}.webp"


def _supabase_storage_url(object_path: str) -> str:
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.INVENTORY_STORAGE_BUCKET
    return f"{base}/storage/v1/object/{bucket}/{object_path}"


def _supabase_public_url(object_path: str) -> str:
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.INVENTORY_STORAGE_BUCKET
    return f"{base}/storage/v1/object/public/{bucket}/{object_path}"


async def _upload_bytes_to_supabase(object_path: str, data: bytes, mime: str) -> bool:
    """Upload raw bytes to Supabase. Returns True on success."""
    url = _supabase_storage_url(object_path)
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Content-Type": mime,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, content=data, headers=headers)
    if resp.status_code in (200, 201):
        return True
    logger.error(f"Supabase upload failed: status={resp.status_code} body={resp.text[:200]}")
    return False


async def _save_local(
    full_bytes: bytes,
    thumb_bytes: bytes,
    prefix: str,
    entity_id: str,
    filename: str,
    base_dir: Path = _LOCAL_BASE,
) -> Tuple[str, str, int, int]:
    """
    Write full image and thumbnail to local filesystem.
    Returns (full_url, thumb_url, width, height).
    full_url / thumb_url are relative URLs served via /uploads/inventory/...
    """
    full_obj_path = _build_object_path(prefix, entity_id, filename, is_thumb=False)
    thumb_obj_path = _build_object_path(prefix, entity_id, filename, is_thumb=True)

    full_path = base_dir / full_obj_path
    thumb_path = base_dir / thumb_obj_path

    full_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    full_path.write_bytes(full_bytes)
    thumb_path.write_bytes(thumb_bytes)

    w, h = _get_dimensions(full_bytes)

    full_url = f"/uploads/inventory/{full_obj_path}"
    thumb_url = f"/uploads/inventory/{thumb_obj_path}"

    return full_url, thumb_url, w, h


# ── Public API ─────────────────────────────────────────────────────────────────

async def upload_inventory_image(
    image_bytes: bytes,
    mime: str,
    prefix: str,
    entity_id: str,
    original_filename: str,
) -> Tuple[str, str, int, int]:
    """
    Optimize image + generate thumbnail (both WebP), upload to Supabase bucket "inventory".
    Falls back to local filesystem if Supabase is not configured or upload fails.

    Args:
        image_bytes: Raw uploaded image bytes.
        mime: MIME type of original file (e.g. "image/jpeg").
        prefix: "imports" or "transfers".
        entity_id: Receipt ID or ticket ID as string (e.g. "42", "TR_99").
        original_filename: Original filename (for hash generation).

    Returns:
        Tuple of (full_url, thumb_url, width, height).

    Raises:
        ValueError: If both Supabase and local fallback fail.
    """
    full_bytes = _optimize_to_webp(image_bytes, max_size=MAX_SIZE)
    thumb_bytes = _optimize_to_webp(image_bytes, max_size=THUMB_SIZE)
    w, h = _get_dimensions(full_bytes)
    filename = _unique_filename(original_filename, image_bytes)

    full_obj_path = _build_object_path(prefix, entity_id, filename, is_thumb=False)
    thumb_obj_path = _build_object_path(prefix, entity_id, filename, is_thumb=True)

    # Try Supabase first
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
        try:
            full_ok = await _upload_bytes_to_supabase(full_obj_path, full_bytes, "image/webp")
            thumb_ok = await _upload_bytes_to_supabase(thumb_obj_path, thumb_bytes, "image/webp")
            if full_ok and thumb_ok:
                return (
                    _supabase_public_url(full_obj_path),
                    _supabase_public_url(thumb_obj_path),
                    w,
                    h,
                )
            logger.warning("Supabase upload partial failure, falling back to local")
        except Exception:
            logger.exception("Supabase upload exception, falling back to local")

    # Local fallback
    logger.info("Saving inventory image to local filesystem")
    try:
        return await _save_local(full_bytes, thumb_bytes, prefix, entity_id, filename)
    except Exception as exc:
        raise ValueError(f"Failed to save inventory image: {exc}") from exc


async def delete_inventory_image(file_path: str, thumbnail_path: str) -> bool:
    """
    Delete image and thumbnail.
    - If path starts with https:// → delete from Supabase.
    - Otherwise → delete from local filesystem (legacy paths).

    Returns True if deletion succeeded (or files were already gone).
    """
    if file_path.startswith("https://"):
        return await _delete_supabase(file_path, thumbnail_path)
    return _delete_local(file_path, thumbnail_path)


async def _delete_supabase(full_url: str, thumb_url: str) -> bool:
    """Extract object path from public URL and DELETE from Supabase."""
    bucket = settings.INVENTORY_STORAGE_BUCKET
    prefix = f"/storage/v1/object/public/{bucket}/"
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
    }

    async def _del(url: str) -> bool:
        if not url:
            return True
        if prefix not in url:
            logger.warning(f"Unexpected URL format for Supabase delete: {url}")
            return False
        object_path = url.split(prefix, 1)[1]
        delete_url = _supabase_storage_url(object_path)
        # Supabase Storage DELETE uses the /object/{bucket}/{path} endpoint
        base = settings.SUPABASE_URL.rstrip("/")
        delete_url = f"{base}/storage/v1/object/{bucket}/{object_path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(delete_url, headers=headers)
        return resp.status_code in (200, 204, 404)

    try:
        ok1 = await _del(full_url)
        ok2 = await _del(thumb_url)
        return ok1 and ok2
    except Exception:
        logger.exception("Error deleting from Supabase")
        return False


def _delete_local(file_path: str, thumbnail_path: str) -> bool:
    """Delete local filesystem files (legacy paths)."""
    try:
        for p in (file_path, thumbnail_path):
            if not p:
                continue
            path = Path(p)
            if not path.is_absolute():
                path = _APP_ROOT / p.lstrip("/")
            if path.exists():
                path.unlink()
        return True
    except Exception as exc:
        logger.error(f"Error deleting local image files: {exc}")
        return False
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/thanhminh/Desktop/xxx
python -m pytest tests/test_inventory_storage.py -v
```

Expected: All tests PASS. If `TestUploadInventoryImageSupabasePath` fails due to import caching from previous run, run:
```bash
python -m pytest tests/test_inventory_storage.py -v --cache-clear
```

- [ ] **Step 5: Verify local fallback mount exists in main.py**

```bash
grep -n "uploads" /Users/thanhminh/Desktop/xxx/app/main.py | head -10
```

Expected: See `app.mount("/uploads", StaticFiles(directory=uploads_dir), ...)`. The existing mount covers `/uploads` which includes `/uploads/inventory/...` — no change needed.

- [ ] **Step 6: Commit**

```bash
git add app/services/inventory_storage.py tests/test_inventory_storage.py
git commit -m "feat: add inventory_storage service for Supabase image upload with local fallback"
```

---

## Task 3: Update `transfer_images.py` to use new service

**Files:**
- Modify: `app/api/inventory/transfer_images.py`

- [ ] **Step 1: Replace the file content**

Replace `app/api/inventory/transfer_images.py` entirely with:

```python
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
```

- [ ] **Step 2: Verify imports are valid**

```bash
cd /Users/thanhminh/Desktop/xxx
python -c "from app.api.inventory.transfer_images import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/api/inventory/transfer_images.py
git commit -m "feat: use inventory_storage service in transfer_images API, surface per-file errors"
```

---

## Task 4: Update `imports.py` upload endpoint to use new service

**Files:**
- Modify: `app/api/inventory/imports.py`

Only the `upload_import_images` and `delete_import_image` functions change. Leave `create_import_ticket` and other functions untouched.

- [ ] **Step 1: Read current import of ImageOptimizer in imports.py**

```bash
grep -n "ImageOptimizer\|from.*image_optimizer" /Users/thanhminh/Desktop/xxx/app/api/inventory/imports.py
```

Note the line number of `from ...core.image_optimizer import ImageOptimizer`.

- [ ] **Step 2: Update import line and upload/delete functions**

Replace the import:
```python
from ...core.image_optimizer import ImageOptimizer
```
With:
```python
from ...services.inventory_storage import upload_inventory_image, delete_inventory_image
import logging
logger = logging.getLogger("binbin-inventory")
```

Then find the `upload_import_images` function (around line 200+) and replace its body:

```python
@router.post("/import/{receipt_id}/images")
async def upload_import_images(
    receipt_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    from ...db.models import InventoryReceipt, ImportImage
    receipt = db.query(InventoryReceipt).get(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Phiếu nhập không tồn tại")

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
                prefix="imports",
                entity_id=str(receipt_id),
                original_filename=file.filename or "image",
            )
            import_image = ImportImage(
                receipt_id=receipt_id,
                file_path=full_url,
                thumbnail_path=thumb_url,
                file_size=len(image_bytes),
                width=width,
                height=height,
                display_order=len(uploaded),
            )
            db.add(import_image)
            uploaded.append({"filename": file.filename})
        except Exception as exc:
            logger.error(f"Failed to upload import image {file.filename}: {exc}")
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
```

Find `delete_import_image` and replace its body:

```python
@router.delete("/images/{image_id}")
async def delete_import_image(
    image_id: int,
    db: Session = Depends(get_db)
):
    from ...db.models import ImportImage
    img = db.query(ImportImage).get(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Ảnh không tồn tại")

    await delete_inventory_image(img.file_path or "", img.thumbnail_path or "")
    db.delete(img)
    db.commit()
    return {"status": "success", "message": "Đã xoá ảnh"}
```

- [ ] **Step 3: Verify imports are valid**

```bash
cd /Users/thanhminh/Desktop/xxx
python -c "from app.api.inventory.imports import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/api/inventory/imports.py
git commit -m "feat: use inventory_storage service in imports API, surface per-file errors"
```

---

## Task 5: Fix frontend error surfacing — `approvals.js`

**Files:**
- Modify: `app/static/js/inventory/shared/approvals.js`

- [ ] **Step 1: Find exact line of `uploadReceiptImages` function**

```bash
grep -n "async uploadReceiptImages\|uploadReceiptImages" /Users/thanhminh/Desktop/xxx/app/static/js/inventory/shared/approvals.js
```

Note the line where the function body starts and ends.

- [ ] **Step 2: Replace `uploadReceiptImages` body**

Find this function:
```js
    async uploadReceiptImages(ticketId) {
        if (!this.receiptForm.images || this.receiptForm.images.length === 0) return;
        try {
            const formData = new FormData();
            this.receiptForm.images.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/transfer/${ticketId}/images`, {
                method: 'POST',
                body: formData
            });
            return await res.json();
        } catch (error) {
            console.error(error);
        }
    }
```

Replace with:
```js
    async uploadReceiptImages(ticketId) {
        if (!this.receiptForm.images || this.receiptForm.images.length === 0) return;
        try {
            const formData = new FormData();
            this.receiptForm.images.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/transfer/${ticketId}/images`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (!res.ok) {
                alert('Nhận hàng thành công nhưng không lưu được ảnh.\nVui lòng mở lại phiếu để thử upload lại.');
            } else if (data.failed_files && data.failed_files.length > 0) {
                alert(`Đã lưu ${data.images.length} ảnh. ${data.failed_files.length} ảnh lỗi không lưu được.`);
            }
            return data;
        } catch (error) {
            console.error('uploadReceiptImages error:', error);
            alert('Nhận hàng thành công nhưng không kết nối được để lưu ảnh.');
        }
    }
```

- [ ] **Step 3: Verify JS syntax**

```bash
node --input-type=module < /Users/thanhminh/Desktop/xxx/app/static/js/inventory/shared/approvals.js 2>&1 | head -5
```

Expected: No syntax errors (may print nothing or a harmless module warning).

- [ ] **Step 4: Commit**

```bash
git add app/static/js/inventory/shared/approvals.js
git commit -m "fix: surface receipt image upload errors to user in approvals.js"
```

---

## Task 6: Fix frontend error surfacing — `imports.js`

**Files:**
- Modify: `app/static/js/inventory/shared/imports.js`

- [ ] **Step 1: Find exact lines of the image upload alert block in `submitImport`**

```bash
grep -n "imageResult\|Upload.*ảnh\|upload.*image" /Users/thanhminh/Desktop/xxx/app/static/js/inventory/shared/imports.js | head -20
```

- [ ] **Step 2: Replace the image result handling block inside `submitImport`**

Find this block (inside the `if (res.ok)` branch):
```js
                if (this.importForm.images && this.importForm.images.length > 0 && data.receipt_id) {
                    const imageResult = await this.uploadImportImages(data.receipt_id);
                    if (imageResult.success && imageResult.count > 0) {
                        alert(data.message + `\nĐã upload ${imageResult.count} hình ảnh.`);
                    } else {
                        alert(data.message);
                    }
                } else {
                    alert(data.message);
                }
```

Replace with:
```js
                if (this.importForm.images && this.importForm.images.length > 0 && data.receipt_id) {
                    const imageResult = await this.uploadImportImages(data.receipt_id);
                    if (imageResult && imageResult.failed_files && imageResult.failed_files.length > 0) {
                        const saved = (imageResult.images || []).length;
                        const failed = imageResult.failed_files.length;
                        alert(data.message + `\nĐã upload ${saved} ảnh. ${failed} ảnh lỗi không lưu được.`);
                    } else if (imageResult && imageResult.images && imageResult.images.length > 0) {
                        alert(data.message + `\nĐã upload ${imageResult.images.length} hình ảnh.`);
                    } else if (imageResult && !imageResult.images) {
                        alert(data.message + '\nKhông lưu được ảnh. Vui lòng thử lại từ màn hình chi tiết phiếu.');
                    } else {
                        alert(data.message);
                    }
                } else {
                    alert(data.message);
                }
```

- [ ] **Step 3: Update `uploadImportImages` to return raw API response**

Find `uploadImportImages`:
```js
    async uploadImportImages(receiptId) {
        if (!this.importForm.images || this.importForm.images.length === 0) {
            return { success: true, count: 0 };
        }
        try {
            const formData = new FormData();
            this.importForm.images.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/import/${receiptId}/images`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok) {
                return { success: true, count: data.images?.length || 0 };
            } else {
                return { success: false, error: data.detail || 'Upload failed' };
            }
        } catch (error) {
            return { success: false, error: error.message };
        }
    },
```

Replace with:
```js
    async uploadImportImages(receiptId) {
        if (!this.importForm.images || this.importForm.images.length === 0) {
            return { images: [], failed_files: [] };
        }
        try {
            const formData = new FormData();
            this.importForm.images.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/import/${receiptId}/images`, {
                method: 'POST',
                body: formData
            });
            return await res.json();
        } catch (error) {
            console.error('uploadImportImages error:', error);
            return null;
        }
    },
```

- [ ] **Step 4: Verify JS syntax**

```bash
node --input-type=module < /Users/thanhminh/Desktop/xxx/app/static/js/inventory/shared/imports.js 2>&1 | head -5
```

Expected: No syntax errors.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/inventory/shared/imports.js
git commit -m "fix: surface import image upload errors to user in imports.js"
```

---

## Task 7: Create migration script

**Files:**
- Create: `scripts/migrate_images_to_supabase.py`

- [ ] **Step 1: Create the migration script**

```python
#!/usr/bin/env python3
"""
One-time migration: move inventory images from local filesystem to Supabase Storage.

Usage:
    cd /path/to/project
    python scripts/migrate_images_to_supabase.py [--dry-run]

Flags:
    --dry-run   Print what would be done without making any changes.

Safety:
    - Rows already pointing to https:// are skipped (idempotent).
    - Local files are deleted ONLY after DB update is committed.
    - Can be re-run safely after partial failure.
"""
import asyncio
import sys
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import ImportImage, TransferImage
from app.services.inventory_storage import (
    upload_inventory_image,
    _build_object_path,
    _supabase_public_url,
    _APP_ROOT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate-images")

DRY_RUN = "--dry-run" in sys.argv


def resolve_local_path(file_path: str) -> Path:
    """Resolve a local file_path (relative or /uploads/...) to absolute path."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    # Strip leading slash, treat as relative to project root
    stripped = file_path.lstrip("/")
    return _APP_ROOT / stripped


async def migrate_image_row(db, model_instance, prefix: str, entity_id: str, label: str):
    """
    Migrate one image row. Returns "migrated", "skipped", or "failed".
    """
    fp = model_instance.file_path or ""
    tp = model_instance.thumbnail_path or ""

    # Already on Supabase
    if fp.startswith("https://"):
        logger.info(f"SKIP (already Supabase) [{label}] id={model_instance.id}")
        return "skipped"

    full_path = resolve_local_path(fp)
    thumb_path = resolve_local_path(tp)

    if not full_path.exists():
        logger.warning(f"SKIP (file not found) [{label}] id={model_instance.id} path={full_path}")
        return "skipped"

    if DRY_RUN:
        logger.info(f"DRY-RUN would migrate [{label}] id={model_instance.id} from {fp}")
        return "migrated"

    try:
        image_bytes = full_path.read_bytes()
        full_url, thumb_url, w, h = await upload_inventory_image(
            image_bytes=image_bytes,
            mime="image/webp",
            prefix=prefix,
            entity_id=entity_id,
            original_filename=full_path.name,
        )

        # Update DB
        model_instance.file_path = full_url
        model_instance.thumbnail_path = thumb_url
        db.flush()
        db.commit()

        # Delete local files AFTER commit
        if full_path.exists():
            full_path.unlink()
        if thumb_path.exists():
            thumb_path.unlink()

        logger.info(f"MIGRATED [{label}] id={model_instance.id} → {full_url}")
        return "migrated"

    except Exception as exc:
        db.rollback()
        logger.error(f"FAILED [{label}] id={model_instance.id}: {exc}")
        return "failed"


async def main():
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    db = SessionLocal()
    counts = {"migrated": 0, "skipped": 0, "failed": 0}

    try:
        # Migrate ImportImage rows
        import_images = db.query(ImportImage).all()
        logger.info(f"Found {len(import_images)} ImportImage rows")
        for img in import_images:
            result = await migrate_image_row(
                db, img,
                prefix="imports",
                entity_id=str(img.receipt_id),
                label="ImportImage"
            )
            counts[result] += 1

        # Migrate TransferImage rows
        transfer_images = db.query(TransferImage).all()
        logger.info(f"Found {len(transfer_images)} TransferImage rows")
        for img in transfer_images:
            result = await migrate_image_row(
                db, img,
                prefix="transfers",
                entity_id=str(img.transfer_id),
                label="TransferImage"
            )
            counts[result] += 1

    finally:
        db.close()

    logger.info(
        f"\n{'DRY RUN ' if DRY_RUN else ''}Migration complete: "
        f"migrated={counts['migrated']}, skipped={counts['skipped']}, failed={counts['failed']}"
    )
    if counts["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Test script dry-run (no Supabase needed)**

```bash
cd /Users/thanhminh/Desktop/xxx
python scripts/migrate_images_to_supabase.py --dry-run
```

Expected output includes lines like:
```
Found N ImportImage rows
Found N TransferImage rows
DRY RUN Migration complete: migrated=N, skipped=N, failed=0
```

If `SUPABASE_URL` is empty, it will print the error and exit 1. That's correct — set it in `.env` before running.

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_images_to_supabase.py
git commit -m "feat: add migration script to move inventory images to Supabase Storage"
```

---

## Task 8: Create Supabase bucket and run migration

- [ ] **Step 1: Create bucket in Supabase dashboard**

Go to: `https://supabase.com/dashboard/project/<your-project>/storage/buckets`

Create bucket named `inventory`. Set it as **Public** (so public URLs work without auth headers in `<img src>`).

- [ ] **Step 2: Verify `.env` has correct values**

```bash
grep "SUPABASE_URL\|SUPABASE_SERVICE_KEY\|INVENTORY" /Users/thanhminh/Desktop/xxx/.env
```

Expected: All three are set and non-empty.

- [ ] **Step 3: Run migration**

```bash
cd /Users/thanhminh/Desktop/xxx
python scripts/migrate_images_to_supabase.py
```

Expected final line: `Migration complete: migrated=N, skipped=N, failed=0`

If any rows fail, fix the error and re-run (script is idempotent).

- [ ] **Step 4: Verify migrated row in DB**

```bash
cd /Users/thanhminh/Desktop/xxx
python -c "
from app.db.session import SessionLocal
from app.db.models import ImportImage, TransferImage
db = SessionLocal()
row = db.query(ImportImage).first()
if row:
    print('ImportImage file_path:', row.file_path)
row2 = db.query(TransferImage).first()
if row2:
    print('TransferImage file_path:', row2.file_path)
db.close()
"
```

Expected: `file_path` values start with `https://...supabase.co/storage/...`

---

## Task 9: End-to-end verification

- [ ] **Step 1: Start the server**

```bash
cd /Users/thanhminh/Desktop/xxx
uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Test import image upload**

1. Open browser → inventory manager or reception page
2. Open "Nhập hàng" modal
3. Select product, fill supplier name
4. Attach 1-2 photos
5. Click submit
6. Hard reload the page (Ctrl+Shift+R)
7. Open the created receipt detail

Expected: Photos are visible in the receipt detail, URLs are `https://...supabase.co/...` in network tab.

- [ ] **Step 3: Test receive goods image upload**

1. Open a ticket in SHIPPING status
2. Open receipt modal
3. Attach photos
4. Submit receipt
5. Hard reload page
6. Check ticket detail

Expected: Photos visible, Supabase URLs.

- [ ] **Step 4: Test error alert (simulate failure)**

Temporarily set `INVENTORY_STORAGE_BUCKET = "nonexistent-bucket"` in `.env`, restart server, try upload. Expected: Alert shown to user ("không lưu được ảnh"). Restore correct bucket name afterward.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/thanhminh/Desktop/xxx
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All pre-existing tests pass. New `test_inventory_storage.py` tests pass.

- [ ] **Step 6: Run gitnexus detect_changes**

```bash
npx gitnexus detect_changes
```

Review output — expected affected symbols are only within `inventory_storage`, `transfer_images`, `imports`, `approvals`, `imports` JS modules. No unexpected blast radius.

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Root cause 1 (relative UPLOAD_DIR) → fixed by `inventory_storage.py` using `_APP_ROOT` absolute path for local fallback
- ✅ Root cause 2 (silent 2-phase failure) → Task 5 & 6 surface errors to user
- ✅ Root cause 3 (backend swallows per-file errors) → Task 3 & 4 collect `failed_files`, return in response
- ✅ Supabase bucket `inventory` → Task 1 config + Task 8 bucket creation
- ✅ Local fallback → `inventory_storage.py` falls back when Supabase unconfigured
- ✅ Migrate old local images → Task 7 migration script
- ✅ Delete works for both Supabase URLs and legacy local paths → `delete_inventory_image`

**Type consistency:**
- `upload_inventory_image` returns `Tuple[str, str, int, int]` — matches usage in Task 3 (`full_url, thumb_url, width, height`)
- `delete_inventory_image(file_path, thumbnail_path)` — matches calls in Task 3 & 4
- `failed_files` key in response — matches JS check in Task 5 & 6
- `data.images.length` in JS — matches `images` key returned by backend

**Placeholder scan:** No TBD, no TODO, no "similar to above" — all code blocks are complete.
