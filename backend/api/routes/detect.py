"""Route handler untuk deteksi dan verifikasi watermark (detect)."""

from __future__ import annotations

import io
from typing import Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from PIL import Image

from backend.core.config import settings
from backend.services.watermark import detect_watermark
from backend.api.routes.embed import image_to_data_url

router = APIRouter()


# ══════════════════════════════════════════════════════════════════
# MODEL RESPONS
# ══════════════════════════════════════════════════════════════════
class DetectResponse(BaseModel):
    """Skema respons sukses endpoint /api/detect."""

    watermark_detected: bool = Field(
        ...,
        description="Apakah watermark valid berhasil terdeteksi dan terverifikasi",
    )
    watermark: Optional[str] = Field(
        None,
        description="Teks watermark yang diekstrak, atau null jika tidak terdeteksi",
    )
    nc: Optional[float] = Field(
        None,
        description="Normalized Correlation terhadap watermark referensi (null jika tidak disediakan)",
    )
    ber: Optional[float] = Field(
        None,
        description="Bit Error Rate terhadap watermark referensi (null jika tidak disediakan)",
    )
    input_image: str = Field(
        ...,
        description="Data URL citra masukan (format data:image/png;base64,...)",
    )
    tamper_map: str = Field(
        ...,
        description="Data URL tamper map (format data:image/png;base64,...)",
    )


# ══════════════════════════════════════════════════════════════════
# ENDPOINT POST /api/detect
# ══════════════════════════════════════════════════════════════════
@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Deteksi dan verifikasi watermark pada citra stego",
)
async def detect_endpoint(
    image: UploadFile = File(..., description="Berkas citra stego (PNG atau JPEG)"),
    secret_key: str = Form(..., description="Kunci rahasia PRNG"),
    original_watermark: Optional[str] = Form(
        None, description="Watermark referensi asli (opsional, maks 64 karakter)"
    ),
) -> Dict[str, object]:
    """Endpoint untuk alur kerja deteksi watermark (detect).

    Validasi:
    1. Berkas gambar wajib ada dan bertipe image/png atau image/jpeg.
    2. Ukuran berkas maksimum 10 MB dan tidak boleh kosong.
    3. Secret key wajib ada dan setelah trim tidak boleh kosong.
    4. original_watermark bila tersedia maksimal 64 karakter.
    5. Berkas gambar harus valid dan dapat dibuka oleh Pillow.

    Keamanan:
    - Tidak ada file citra, secret_key, atau watermark yang disimpan ke disk maupun log.
    """
    # 1. Validasi tipe konten (MIME Type)
    content_type = (image.content_type or "").lower()
    if content_type not in settings.ALLOWED_IMAGE_TYPES and content_type != "image/jpg":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format berkas tidak didukung. Hanya citra PNG atau JPEG yang diperbolehkan.",
        )

    # 2. Validasi secret key
    clean_secret_key = secret_key.strip() if secret_key else ""
    if not clean_secret_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Secret key tidak boleh kosong.",
        )

    # 3. Validasi original_watermark (opsional)
    clean_original_watermark: Optional[str] = None
    if original_watermark is not None:
        trimmed = original_watermark.strip()
        if trimmed:
            if len(trimmed) > settings.MAX_WATERMARK_LENGTH:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Panjang watermark referensi melebihi batas (maksimal {settings.MAX_WATERMARK_LENGTH} karakter).",
                )
            clean_original_watermark = trimmed

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
    rgb_input = pil_image.convert("RGB")

    # 7. Jalankan engine deteksi watermark
    try:
        result = detect_watermark(
            image=rgb_input,
            secret_key=clean_secret_key,
            original_watermark=clean_original_watermark,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gagal memproses deteksi watermark pada citra.",
        )

    # 8. Encode citra masukan dan tamper map ke Base64 Data URL
    input_data_url = image_to_data_url(rgb_input, format="PNG")
    tamper_map_data_url = image_to_data_url(result["tamper_map"], format="PNG")

    return {
        "watermark_detected": result["watermark_detected"],
        "watermark": result["watermark"],
        "nc": result["nc"],
        "ber": result["ber"],
        "input_image": input_data_url,
        "tamper_map": tamper_map_data_url,
    }
