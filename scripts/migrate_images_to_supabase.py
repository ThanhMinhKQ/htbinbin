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
