"""Route handler untuk penyisipan watermark (embed)."""

from __future__ import annotations

import base64
import io
import logging
from typing import Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from PIL import Image
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.services.watermark import CapacityExceededError, calculate_mse, calculate_psnr, embed_watermark

logger = logging.getLogger(__name__)
router = APIRouter()


class EmbedResponse(BaseModel):
    original_image: str = Field(..., description="Data URL citra asli (PNG base64)")
    watermarked_image: str = Field(..., description="Data URL citra ber-watermark (PNG base64)")
    psnr: float = Field(..., description="Peak Signal-to-Noise Ratio (dB)")
    mse: float = Field(..., description="Mean Squared Error")


def image_to_data_url(image: Image.Image, format: str = "PNG") -> str:
    """Konversi PIL Image ke Base64 Data URL."""
    buf = io.BytesIO()
    image.save(buf, format=format)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/{format.lower()};base64,{encoded}"


def _load_image(contents: bytes) -> Image.Image:
    """Buka dan validasi bytes sebagai citra PNG/JPEG menggunakan Pillow."""
    try:
        img = Image.open(io.BytesIO(contents))
        img.load()
        if img.format not in ("PNG", "JPEG"):
            raise ValueError("Bukan format PNG/JPEG")
        return img
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Berkas citra rusak atau tidak dapat dibaca.",
        )


async def _read_image_upload(image: UploadFile) -> bytes:
    """Baca dan validasi ukuran upload citra."""
    if (image.content_type or "").lower() not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format berkas tidak didukung. Hanya citra PNG atau JPEG yang diperbolehkan.",
        )
    contents = await image.read()
    if len(contents) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Berkas citra tidak boleh kosong.")
    if len(contents) > settings.MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ukuran file melebihi batas 10 MB.")
    return contents


@router.post("/embed", response_model=EmbedResponse, summary="Sisipkan watermark ke dalam citra (LSB Fragile)")
async def embed_endpoint(
    image: UploadFile = File(..., description="Berkas citra sampul (PNG atau JPEG)"),
    watermark: str = Form(..., description="Teks payload watermark (maks 64 karakter)"),
    secret_key: str = Form(..., description="Kunci rahasia PRNG"),
) -> Dict[str, object]:
    clean_watermark = watermark.strip()
    if not clean_watermark:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload watermark tidak boleh kosong.")
    if len(clean_watermark) > settings.MAX_WATERMARK_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Panjang watermark melebihi batas (maksimal {settings.MAX_WATERMARK_LENGTH} karakter).",
        )

    clean_key = secret_key.strip()
    if not clean_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secret key tidak boleh kosong.")

    contents = await _read_image_upload(image)
    pil_image = _load_image(contents)
    rgb_original = pil_image.convert("RGB")

    try:
        embed_result = embed_watermark(image=rgb_original, watermark=clean_watermark, secret_key=clean_key)
    except CapacityExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Kesalahan tidak terduga saat embedding watermark")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal memproses penyisipan watermark pada citra.")

    stego_image: Image.Image = embed_result["stego_image"]

    return {
        "original_image": image_to_data_url(rgb_original),
        "watermarked_image": image_to_data_url(stego_image),
        "psnr": float(calculate_psnr(rgb_original, stego_image)),
        "mse": float(calculate_mse(rgb_original, stego_image)),
    }
