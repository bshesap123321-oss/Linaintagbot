"""Image post-processing: Instagram wants a JPEG in a supported aspect ratio."""
from __future__ import annotations

import io

from PIL import Image, ImageOps


def to_instagram_jpeg(data: bytes, width: int = 1080, height: int = 1350, quality: int = 92) -> bytes:
    """Center-crop and resize to the exact target size, strip metadata, return JPEG bytes."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()
