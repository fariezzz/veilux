"""Route handler untuk penyisipan watermark (embed)."""

from __future__ import annotations

import base64
import io
from typing import Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from PIL import Image

from backend.core.config import settings
from backend.services.watermark import (
    CapacityExceededError,
    calculate_mse,
    calculate_psnr,
    embed_watermark,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════
# MODEL RESPONS
# ══════════════════════════════════════════════════════════════════
class EmbedResponse(BaseModel):
    """Skema respons sukses endpoint /api/embed."""

    original_image: str = Field(
        ...,
        description="Data URL citra asli (format data:image/png;base64,...)",
    )
    watermarked_image: str = Field(
        ...,
        description="Data URL citra ber-watermark (format data:image/png;base64,...)",
    )
    psnr: float = Field(
        ...,
        description="Nilai Peak Signal-to-Noise Ratio dalam dB",
    )
    mse: float = Field(
        ...,
        description="Nilai Mean Squared Error",
    )


# ══════════════════════════════════════════════════════════════════
# UTILITAS BANTUAN
# ══════════════════════════════════════════════════════════════════
def image_to_data_url(image: Image.Image, format: str = "PNG") -> str:
    """Mengonversi objek PIL Image menjadi Base64 Data URL.

    Args:
        image: Objek citra PIL Image.
        format: Format citra untuk encoding (default: 'PNG').

    Returns:
        str: String Data URL dengan format 'data:image/png;base64,...'.
    """
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/{format.lower()};base64,{encoded}"


# ══════════════════════════════════════════════════════════════════
# ENDPOINT POST /api/embed
# ══════════════════════════════════════════════════════════════════
@router.post(
    "/embed",
    response_model=EmbedResponse,
    summary="Sisipkan watermark ke dalam citra (LSB Fragile)",
)
async def embed_endpoint(
    image: UploadFile = File(..., description="Berkas citra sampul (PNG atau JPEG)"),
    watermark: str = Form(..., description="Teks payload watermark (maks 64 karakter)"),
    secret_key: str = Form(..., description="Kunci rahasia PRNG"),
) -> Dict[str, object]:
    """Endpoint untuk alur kerja penyisipan watermark (embed).

    Validasi:
    1. Berkas gambar wajib ada dan bertipe image/png atau image/jpeg.
    2. Ukuran berkas maksimum 10 MB dan tidak boleh kosong.
    3. Payload watermark wajib ada, setelah trim tidak kosong, dan maksimal 64 karakter.
    4. Secret key wajib ada dan setelah trim tidak boleh kosong.
    5. Berkas gambar harus valid dan dapat dibuka oleh Pillow.

    Keamanan:
    - Tidak ada file citra atau secret_key yang disimpan ke disk maupun log.
    """
    # 1. Validasi tipe konten (MIME Type)
    content_type = (image.content_type or "").lower()
    if content_type not in settings.ALLOWED_IMAGE_TYPES and content_type != "image/jpg":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format berkas tidak didukung. Hanya citra PNG atau JPEG yang diperbolehkan.",
        )

    # 2. Validasi payload watermark
    clean_watermark = watermark.strip() if watermark else ""
    if not clean_watermark:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload watermark tidak boleh kosong.",
        )

    if len(clean_watermark) > settings.MAX_WATERMARK_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Panjang watermark melebihi batas (maksimal {settings.MAX_WATERMARK_LENGTH} karakter).",
        )

    # 3. Validasi secret key
    clean_secret_key = secret_key.strip() if secret_key else ""
    if not clean_secret_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret key tidak boleh kosong.",
        )

    # 4. Validasi ukuran dan pembacaan berkas citra secara in-memory
    contents = await image.read()
    if len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Berkas citra tidak boleh kosong.",
        )

    if len(contents) > settings.MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ukuran file melebihi batas 10 MB.",
        )

    # 5. Validasi integritas citra dengan Pillow
    try:
        pil_image = Image.open(io.BytesIO(contents))
        pil_image.load()
        if pil_image.format not in ("PNG", "JPEG", "JPG"):
            raise ValueError("Bukan format PNG/JPEG")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Berkas citra rusak atau tidak dapat dibaca.",
        )

    # 6. Normalisasi citra ke format RGB 8-bit
    rgb_original = pil_image.convert("RGB")

    # 7. Eksekusi algoritma embedding LSB
    try:
        embed_result = embed_watermark(
            image=rgb_original,
            watermark=clean_watermark,
            secret_key=clean_secret_key,
        )
    except CapacityExceededError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gagal memproses penyisipan watermark pada citra.",
        )

    stego_image: Image.Image = embed_result["stego_image"]

    # 8. Kalkulasi metrik kualitas citra (MSE dan PSNR)
    mse_val = calculate_mse(rgb_original, stego_image)
    psnr_val = calculate_psnr(rgb_original, stego_image)

    # 9. Encoding citra asli dan stego ke format Base64 Data URL (PNG)
    original_data_url = image_to_data_url(rgb_original, format="PNG")
    watermarked_data_url = image_to_data_url(stego_image, format="PNG")

    return {
        "original_image": original_data_url,
        "watermarked_image": watermarked_data_url,
        "psnr": float(psnr_val),
        "mse": float(mse_val),
    }
