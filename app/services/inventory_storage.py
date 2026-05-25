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
from typing import Optional, Tuple

import httpx
from PIL import Image

from app.core.config import settings

logger = logging.getLogger("binbin-inventory-storage")

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_SIZE = (1920, 1080)   # Full image max dimensions
THUMB_SIZE = (300, 300)   # Thumbnail max dimensions
WEBP_QUALITY = 85
COMPRESS_THRESHOLD = 500 * 1024

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


def _unique_filename(original_filename: str, image_bytes: bytes, extension: str = ".webp") -> str:
    file_hash = hashlib.md5(image_bytes).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"img_{timestamp}_{file_hash}{extension}"


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
    thumb_filename: Optional[str] = None,
    base_dir: Path = _LOCAL_BASE,
) -> Tuple[str, str, int, int]:
    """
    Write full image and thumbnail to local filesystem.
    Returns (full_url, thumb_url, width, height).
    full_url / thumb_url are relative URLs served via /uploads/inventory/...
    """
    full_obj_path = _build_object_path(prefix, entity_id, filename, is_thumb=False)
    thumb_obj_path = _build_object_path(prefix, entity_id, thumb_filename or filename, is_thumb=True)

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
    thumb_bytes = _optimize_to_webp(image_bytes, max_size=THUMB_SIZE)

    if len(image_bytes) <= COMPRESS_THRESHOLD:
        full_bytes = image_bytes
        w, h = _get_dimensions(full_bytes)
        img = Image.open(io.BytesIO(image_bytes))
        fmt = (img.format or "JPEG").upper()
        ext_map = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
        extension = ext_map.get(fmt, ".jpg")
        full_mime = f"image/{fmt.lower()}"
        if full_mime == "image/jpg":
            full_mime = "image/jpeg"
    else:
        full_bytes = _optimize_to_webp(image_bytes, max_size=MAX_SIZE)
        w, h = _get_dimensions(full_bytes)
        extension = ".webp"
        full_mime = "image/webp"

    filename = _unique_filename(original_filename, image_bytes, extension)
    thumb_filename = _unique_filename(original_filename, thumb_bytes)

    full_obj_path = _build_object_path(prefix, entity_id, filename, is_thumb=False)
    thumb_obj_path = _build_object_path(prefix, entity_id, thumb_filename, is_thumb=True)

    # Try Supabase first
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
        try:
            full_ok = await _upload_bytes_to_supabase(full_obj_path, full_bytes, full_mime)
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
        return await _save_local(full_bytes, thumb_bytes, prefix, entity_id, filename, thumb_filename)
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
