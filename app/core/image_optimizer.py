"""
Image Optimization Module for Import Receipts

Handles image compression, resizing, thumbnail generation, and WebP conversion
to optimize storage and improve query performance.
"""

from PIL import Image
import io
from pathlib import Path
from typing import Tuple, Optional
import hashlib
from datetime import datetime

class ImageOptimizer:
    """
    Image optimization utility for import receipt images.
    
    Features:
    - Resize images to max dimensions
    - Generate thumbnails
    - Convert to WebP format
    - Compress with quality settings
    """
    
    # Configuration
    MAX_SIZE = (1920, 1080)  # Max dimensions for full images
    THUMB_SIZE = (300, 300)   # Thumbnail dimensions
    QUALITY = 85              # WebP quality (0-100)
    THUMB_QUALITY = 80        # Thumbnail quality
    
    # Storage paths
    UPLOAD_DIR = Path("uploads/imports")
    
    @classmethod
    def optimize_image(cls, image_bytes: bytes, max_size: Tuple[int, int] = None) -> bytes:
        """
        Optimize an image by resizing and compressing to WebP format.
        
        Args:
            image_bytes: Original image bytes
            max_size: Maximum dimensions (width, height), defaults to MAX_SIZE
            
        Returns:
            Optimized image bytes in WebP format
        """
        if max_size is None:
            max_size = cls.MAX_SIZE
            
        try:
            # Open image from bytes
            img = Image.open(io.BytesIO(image_bytes))
            
            # Convert RGBA to RGB if necessary (WebP supports RGBA but we'll use RGB for smaller size)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize if larger than max_size (maintain aspect ratio)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save to WebP format
            output = io.BytesIO()
            img.save(output, format='WEBP', quality=cls.QUALITY, method=6)
            output.seek(0)
            
            return output.read()
            
        except Exception as e:
            raise ValueError(f"Failed to optimize image: {str(e)}")
    
    @classmethod
    def create_thumbnail(cls, image_bytes: bytes) -> bytes:
        """
        Create a thumbnail from image bytes.
        
        Args:
            image_bytes: Original or optimized image bytes
            
        Returns:
            Thumbnail bytes in WebP format
        """
        return cls.optimize_image(image_bytes, max_size=cls.THUMB_SIZE)
    
    @classmethod
    def save_optimized(
        cls,
        image_bytes: bytes,
        import_id: int,
        original_filename: str
    ) -> Tuple[str, str, int, int]:
        """
        Save optimized image and thumbnail to filesystem.
        
        Args:
            image_bytes: Original image bytes
            import_id: Import receipt ID
            original_filename: Original filename (for extension detection)
            
        Returns:
            Tuple of (full_path, thumbnail_path, width, height)
        """
        # Create directory structure: /uploads/imports/{year}/{month}/{import_id}/
        now = datetime.now()
        year_month_dir = cls.UPLOAD_DIR / str(now.year) / f"{now.month:02d}" / str(import_id)
        full_dir = year_month_dir / "full"
        thumb_dir = year_month_dir / "thumbnails"
        
        # Create directories
        full_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename using hash + timestamp
        file_hash = hashlib.md5(image_bytes).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        filename = f"img_{timestamp}_{file_hash}.webp"
        
        # Optimize and save full image
        optimized_bytes = cls.optimize_image(image_bytes)
        full_path = full_dir / filename
        with open(full_path, 'wb') as f:
            f.write(optimized_bytes)
        
        # Create and save thumbnail
        thumbnail_bytes = cls.create_thumbnail(image_bytes)
        thumb_path = thumb_dir / filename
        with open(thumb_path, 'wb') as f:
            f.write(thumbnail_bytes)
        
        # Get image dimensions
        img = Image.open(io.BytesIO(optimized_bytes))
        width, height = img.size
        
        # Return relative paths (from project root)
        return (
            str(full_path),
            str(thumb_path),
            width,
            height
        )
    
    @classmethod
    def delete_image(cls, full_path: str, thumbnail_path: str) -> bool:
        """
        Delete image files from filesystem.
        
        Args:
            full_path: Path to full image
            thumbnail_path: Path to thumbnail
            
        Returns:
            True if successful, False otherwise
        """
        try:
            full_file = Path(full_path)
            thumb_file = Path(thumbnail_path)
            
            if full_file.exists():
                full_file.unlink()
            
            if thumb_file.exists():
                thumb_file.unlink()
            
            # Try to remove empty parent directories
            try:
                full_file.parent.rmdir()  # Remove /full if empty
                thumb_file.parent.rmdir()  # Remove /thumbnails if empty
                full_file.parent.parent.rmdir()  # Remove /{import_id} if empty
            except OSError:
                pass  # Directory not empty, that's fine
            
            return True
            
        except Exception as e:
            print(f"Error deleting image files: {e}")
            return False
    
    @classmethod
    def get_image_info(cls, image_bytes: bytes) -> dict:
        """
        Get information about an image.
        
        Args:
            image_bytes: Image bytes
            
        Returns:
            Dict with width, height, format, size
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": len(image_bytes)
            }
        except Exception as e:
            raise ValueError(f"Failed to get image info: {str(e)}")
