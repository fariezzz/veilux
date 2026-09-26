"""Route handler untuk deteksi dan verifikasi watermark (detect)."""

from __future__ import annotations

import io
import logging
from typing import Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from PIL import Image
from pydantic import BaseModel, Field

from backend.api.routes.embed import _load_image, _read_image_upload, image_to_data_url
from backend.core.config import settings
from backend.services.watermark import detect_watermark

logger = logging.getLogger(__name__)
router = APIRouter()


class DetectResponse(BaseModel):
    watermark_detected: bool = Field(..., description="Apakah watermark valid berhasil terdeteksi")
    watermark_type: Optional[str] = Field(None, description="Tipe watermark: 'TEXT', 'LOGO', atau null")
    watermark: Optional[str] = Field(None, description="Teks watermark yang diekstrak")
    logo_image: Optional[str] = Field(None, description="Data URL citra logo hasil rekonstruksi (PNG base64)")
    logo_width: Optional[int] = Field(None, description="Lebar logo dalam piksel jika tipe LOGO")
    logo_height: Optional[int] = Field(None, description="Tinggi logo dalam piksel jika tipe LOGO")
    nc: Optional[float] = Field(None, description="Normalized Correlation (null jika referensi tidak disediakan)")
    ber: Optional[float] = Field(None, description="Bit Error Rate (null jika referensi tidak disediakan)")
    valid_blocks: int = Field(..., description="Jumlah blok yang lolos verifikasi integritas")
    total_blocks: int = Field(..., description="Total blok pada citra")
    tamper_ratio: float = Field(..., description="Proporsi blok yang terdeteksi berubah (0.0–1.0)")
    input_image: str = Field(..., description="Data URL citra masukan (PNG base64)")
    tamper_map: str = Field(..., description="Data URL tamper map (PNG base64)")


@router.post("/detect", response_model=DetectResponse, summary="Deteksi dan verifikasi watermark pada citra stego")
async def detect_endpoint(
    image: UploadFile = File(..., description="Berkas citra stego (PNG atau JPEG)"),
    secret_key: str = Form(..., description="Kunci rahasia PRNG"),
    original_watermark: Optional[str] = Form(None, description="Watermark referensi teks untuk kalkulasi NC & BER (opsional)"),
    original_logo: Optional[UploadFile] = File(None, description="Berkas citra logo referensi untuk kalkulasi NC & BER (opsional)"),
) -> Dict[str, object]:
    clean_key = secret_key.strip()
    if not clean_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secret key tidak boleh kosong.")

    clean_original_watermark: Optional[str] = None
    if original_watermark:
        trimmed = original_watermark.strip()
        if trimmed:
            if len(trimmed) > settings.MAX_WATERMARK_LENGTH:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Panjang watermark referensi melebihi batas (maksimal {settings.MAX_WATERMARK_LENGTH} karakter).",
                )
            clean_original_watermark = trimmed

    contents = await _read_image_upload(image)
    pil_image = _load_image(contents)
    rgb_input = pil_image.convert("RGB")

    original_logo_pil: Optional[Image.Image] = None
    if original_logo is not None and getattr(original_logo, "filename", None):
        logo_contents = await _read_image_upload(original_logo)
        original_logo_pil = _load_image(logo_contents)

    try:
        result = detect_watermark(
            image=rgb_input,
            secret_key=clean_key,
            original_watermark=clean_original_watermark,
            original_logo=original_logo_pil,
        )
    except Exception:
        logger.exception("Kesalahan tidak terduga saat deteksi watermark")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal memproses deteksi watermark pada citra.")

    logo_data_url: Optional[str] = None
    if result.get("logo_image") is not None:
        logo_data_url = image_to_data_url(result["logo_image"])

    return {
        "watermark_detected": result["watermark_detected"],
        "watermark_type": result.get("watermark_type"),
        "watermark": result["watermark"],
        "logo_image": logo_data_url,
        "logo_width": result.get("logo_width"),
        "logo_height": result.get("logo_height"),
        "nc": result["nc"],
        "ber": result["ber"],
        "valid_blocks": result["valid_blocks"],
        "total_blocks": result["total_blocks"],
        "tamper_ratio": result["tamper_ratio"],
        "input_image": image_to_data_url(rgb_input),
        "tamper_map": image_to_data_url(result["tamper_map"]),
    }
