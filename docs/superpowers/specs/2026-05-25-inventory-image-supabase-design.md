# Inventory Image Upload — Supabase Migration Design

**Date:** 2026-05-25  
**Status:** Approved  
**Scope:** Fix image persistence bugs + migrate inventory image storage from local filesystem to Supabase Storage

---

## Context

Users uploading photos during "nhận hàng" (receive goods) and "nhập trực tiếp" (direct import) see images previewed in the modal, but after submit and page reload, all images are gone.

**Root causes identified:**

1. `ImageOptimizer.UPLOAD_DIR = Path("uploads/imports")` is a relative path — depends on server CWD. If the app starts from a non-project-root directory, files are written to the wrong location.
2. Two-phase upload fail silently: main action (ticket/receipt) is committed first, then images are uploaded in a second request. If that second request fails, the main action succeeds but images are lost with no user feedback.
3. Backend swallows per-file errors (`except Exception: print(...); continue`) and returns HTTP 200 even when 0 images were saved.

**Goal:** Fix all three bugs and migrate inventory image storage to Supabase bucket `inventory` with local filesystem fallback.

---

## Architecture

```
[Frontend JS]
  └── submitReceipt / submitImport
        ├── POST main action → ticket_id / receipt_id
        └── POST images endpoint → await result, surface errors to user

[Backend: app/services/inventory_storage.py]  ← NEW
        ├── upload_inventory_image(bytes, mime, prefix, entity_id, filename)
        │     → optimize (WebP) + upload full image to Supabase bucket "inventory"
        │     → generate thumbnail (Pillow in-memory) + upload thumb
        │     → return (full_url, thumb_url, width, height)
        └── delete_inventory_image(file_path, thumb_path)
              → DELETE from Supabase (or local if legacy path)

[Supabase Storage: bucket "inventory"]
        imports/{year}/{month}/{receipt_id}/full/img_xxx.webp
        imports/{year}/{month}/{receipt_id}/thumbnails/img_xxx.webp
        transfers/{year}/{month}/{ticket_id}/full/img_xxx.webp
        transfers/{year}/{month}/{ticket_id}/thumbnails/img_xxx.webp

[DB: import_images & transfer_images]
        file_path, thumbnail_path = Supabase public URLs
        (previously: relative local filesystem paths)

[scripts/migrate_images_to_supabase.py]  ← NEW
        → reads rows with local paths, uploads to Supabase, updates DB, deletes local files
```

---

## Config Changes

**File:** `app/core/config.py`

Add:
```python
INVENTORY_STORAGE_BUCKET: str = "inventory"
```

Existing `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are reused.

---

## New Service: `app/services/inventory_storage.py`

**Purpose:** Encapsulate all Supabase upload/delete logic for inventory images. Replaces `ImageOptimizer.save_optimized()` calls in API handlers.

**Key functions:**

```python
async def upload_inventory_image(
    image_bytes: bytes,
    mime: str,
    prefix: str,          # "imports" or "transfers"
    entity_id: str,       # receipt_id or ticket_id (e.g. "TR_42")
    original_filename: str
) -> tuple[str, str, int, int]:
    """
    Optimize image + thumbnail in-memory (Pillow/WebP).
    Upload both to Supabase bucket "inventory".
    Falls back to local absolute path if Supabase unconfigured.
    Returns (full_url, thumb_url, width, height).
    Raises ValueError on failure (no silent swallow).
    """

async def delete_inventory_image(file_path: str, thumb_path: str) -> bool:
    """
    Delete from Supabase if path is https://.
    Delete from local filesystem if path is local (legacy).
    """
```

**Local fallback path (absolute):**
```python
APP_ROOT = Path(__file__).resolve().parents[2]
LOCAL_BASE = APP_ROOT / "uploads" / "inventory"
```

---

## Backend Changes

### `app/api/inventory/transfer_images.py`

- Replace `ImageOptimizer.save_optimized(...)` with `await upload_inventory_image(..., prefix="transfers", entity_id=ticket_id, ...)`
- Remove `except Exception: print(...); continue` pattern
- Collect per-file errors; return `failed_files: [...]` in response body
- If **all** files fail → raise HTTP 500
- `delete_inventory_image` replaces `ImageOptimizer.delete_image`

### `app/api/inventory/imports.py`

- Same substitution: `upload_inventory_image(..., prefix="imports", entity_id=receipt_id, ...)`
- Same error handling improvement
- `delete_inventory_image` replaces `ImageOptimizer.delete_image`

### `app/core/image_optimizer.py`

- No changes. Keep for reference / future use.
- `ImageOptimizer` optimize/thumbnail methods are reused internally by `inventory_storage.py`.

---

## Frontend Changes

### `app/static/js/inventory/shared/approvals.js` — `uploadReceiptImages`

Current: errors are silently `console.error`'d, modal closes without user knowing upload failed.

After fix:
```js
async uploadReceiptImages(ticketId) {
    // ... FormData build same as now ...
    const res = await fetch(`/api/inventory/transfer/${ticketId}/images`, { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) {
        alert('Nhận hàng thành công nhưng không lưu được ảnh. Vui lòng mở lại phiếu để thử upload lại.');
    } else if (data.failed_files && data.failed_files.length > 0) {
        alert(`Đã lưu ${data.images.length} ảnh, ${data.failed_files.length} ảnh lỗi.`);
    }
    return data;
}
```

`submitReceipt()`: no change to flow — modal closes regardless, ticket is committed. Image errors are surfaced via alert only.

### `app/static/js/inventory/shared/imports.js` — `uploadImportImages`

Current: checks `res.ok` but only returns result — caller `submitImport` does not surface error to user.

After fix: if upload returns `!res.ok` or `failed_files.length > 0`, show alert with count. Receipt is already committed, not rolled back.

---

## Migration Script: `scripts/migrate_images_to_supabase.py`

**Run once on production after deploy.**

Steps:
1. Query all `ImportImage` + `TransferImage` rows where `file_path` does NOT start with `https://`
2. For each row: read file from local filesystem using absolute path
3. Upload full image + thumbnail to Supabase bucket `inventory` preserving same sub-path structure
4. `UPDATE` DB row: `file_path = supabase_full_url`, `thumbnail_path = supabase_thumb_url`
5. Delete local files after successful DB update
6. Print summary: `migrated: N, skipped: N (file not found), failed: N`

**Safety:** Script is idempotent — rows already pointing to `https://` are skipped. Can be re-run after partial failure.

---

## Files Modified

| File | Action |
|------|--------|
| `app/core/config.py` | Add `INVENTORY_STORAGE_BUCKET` |
| `app/services/inventory_storage.py` | **CREATE** — new storage service |
| `app/api/inventory/transfer_images.py` | Replace ImageOptimizer, fix error handling |
| `app/api/inventory/imports.py` | Replace ImageOptimizer, fix error handling |
| `app/static/js/inventory/shared/approvals.js` | Surface upload errors to user |
| `app/static/js/inventory/shared/imports.js` | Surface upload errors to user |
| `scripts/migrate_images_to_supabase.py` | **CREATE** — one-time migration script |

**Not changed:** `app/core/image_optimizer.py`, templates, DB models, Alembic migrations (schema unchanged — only URL format stored in existing columns changes).

---

## Verification

1. **Local Supabase fallback test:** Set `SUPABASE_URL=""` in `.env`, upload image in dev → confirm file written under `uploads/inventory/` with absolute path, DB row has local URL, image loads on reload.
2. **Supabase upload test:** Set real Supabase credentials, create bucket `inventory` in Supabase dashboard (public), upload image → confirm DB row has `https://...supabase.../storage/...` URL, image loads on reload.
3. **Error surfaced test:** Temporarily misconfigure bucket name → confirm user sees alert after submit, ticket still created.
4. **Migration script test:** On dev with local files, run `python scripts/migrate_images_to_supabase.py` → confirm DB rows updated, local files deleted, images still load.
5. **Delete test:** Delete image from edit modal → confirm Supabase object deleted (check Supabase dashboard) and DB row removed.
