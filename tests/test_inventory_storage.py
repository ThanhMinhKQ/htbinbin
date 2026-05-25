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


def _make_jpeg_bytes(width=100, height=100) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    img.save(buf, format="JPEG", quality=90)
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
        import tempfile

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

    async def test_small_image_preserves_original_format_for_full_upload(self):
        image_bytes = _make_jpeg_bytes(120, 90)

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

        self.assertTrue(full_url.endswith(".jpg"), full_url)
        self.assertTrue(thumb_url.endswith(".webp"), thumb_url)
        self.assertEqual((w, h), (120, 90))
        first_call = mock_client.post.call_args_list[0]
        self.assertEqual(first_call.kwargs["headers"]["Content-Type"], "image/jpeg")
        uploaded_full = first_call.kwargs["content"]
        self.assertEqual(Image.open(io.BytesIO(uploaded_full)).format, "JPEG")

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
