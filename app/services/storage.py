"""Supabase Storage integration via REST API (httpx) with a local fallback."""

import os
import re
import uuid
import shutil
import logging
from pathlib import PurePosixPath
import httpx
from fastapi import UploadFile, HTTPException

from app.core.config import settings

logger = logging.getLogger("binbin-storage")

# ── Constants ──────────────────────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_MIME_TYPES: dict[str, str] = {
    # images
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    # documents
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _storage_url(path: str) -> str:
    """Build Supabase Storage REST endpoint URL."""
    base = settings.SUPABASE_URL.rstrip("/")
    return f"{base}/storage/v1/object/{path}"


def _public_url(object_path: str) -> str:
    """Build the public URL for a stored object."""
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.SUPABASE_STORAGE_BUCKET
    return f"{base}/storage/v1/object/public/{bucket}/{object_path}"


def validate_upload(file: UploadFile, content_length: int | None) -> None:
    """
    Validate MIME type and size before reading the file body.
    Raises HTTPException(400) on failure.
    """
    # MIME type check
    mime = file.content_type or ""
    if mime not in ALLOWED_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_MIME_TYPES.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Loại file '{mime}' không được hỗ trợ. Các loại file hợp lệ: {allowed}",
        )

    # Early size check via Content-Length header (if present)
    if content_length and content_length > MAX_FILE_SIZE:
        mb = MAX_FILE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Dung lượng file vượt quá giới hạn {mb}MB.",
        )


async def upload_to_supabase(file: UploadFile) -> dict:
    """
    Upload a file to Supabase Storage if configured. Falls back to local filesystem otherwise.

    Returns dict with keys: url, filename, size.
    Raises HTTPException on validation or upload failure.
    """
    # Read file bytes
    data = await file.read()
    file_size = len(data)

    if file_size > MAX_FILE_SIZE:
        mb = MAX_FILE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Dung lượng file vượt quá giới hạn {mb}MB."
        )

    # Sanitize and generate safe filename
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not ext:
        mime = file.content_type or "application/octet-stream"
        ext = ALLOWED_MIME_TYPES.get(mime, ".bin")

    clean_name = re.sub(r'[^a-zA-Z0-9_\-.]', '', os.path.splitext(file.filename or "file")[0])
    if not clean_name:
        clean_name = "file"
    unique_filename = f"{clean_name}_{uuid.uuid4().hex[:8]}{ext}"

    # Check if Supabase cloud storage config is present
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
        try:
            object_path = f"shift_notifications/{unique_filename}"
            bucket = settings.SUPABASE_STORAGE_BUCKET
            url = _storage_url(f"{bucket}/{object_path}")

            headers = {
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                "Content-Type": file.content_type or "application/octet-stream",
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, content=data, headers=headers)

            if resp.status_code in (200, 201):
                return {
                    "url": _public_url(object_path),
                    "filename": file.filename or unique_filename,
                    "size": file_size,
                }
            else:
                logger.error(f"Supabase upload failed: status={resp.status_code} body={resp.text}")
        except Exception as e:
            logger.exception("Error uploading file to Supabase")

    # Local fallback logic if Supabase is unconfigured or fails
    logger.info("Falling back to local filesystem storage for upload")
    upload_dir = os.path.join(os.path.dirname(APP_ROOT), "uploads", "shift_notifications")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, unique_filename)

    with open(file_path, "wb") as buffer:
        buffer.write(data)

    return {
        "url": f"/uploads/shift_notifications/{unique_filename}",
        "filename": file.filename or unique_filename,
        "size": file_size
    }
