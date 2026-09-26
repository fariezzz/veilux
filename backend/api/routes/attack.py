"""Route handler untuk simulasi serangan terhadap citra ber-watermark."""

from __future__ import annotations

import io
import logging
from typing import Dict, Optional

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from PIL import Image, ImageEnhance
from pydantic import BaseModel, Field

from backend.api.routes.embed import _load_image, _read_image_upload, image_to_data_url
from backend.core.config import settings
from backend.services.watermark import calculate_mse, calculate_psnr, detect_watermark

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_ATTACKS = {"jpeg_90", "jpeg_70", "jpeg_50", "crop", "resize", "noise", "brightness", "contrast"}


class AttackResponse(BaseModel):
    before_image: str = Field(..., description="Data URL citra sebelum serangan")
    after_image: str = Field(..., description="Data URL citra setelah serangan")
    tamper_map: str = Field(..., description="Data URL tamper map hasil deteksi")
    psnr: float = Field(..., description="PSNR antara citra sebelum dan sesudah serangan (dB)")
    mse: float = Field(..., description="MSE antara citra sebelum dan sesudah serangan")
    nc: Optional[float] = Field(None, description="Normalized Correlation")
    ber: Optional[float] = Field(None, description="Bit Error Rate")
    watermark_detected: bool = Field(..., description="Apakah watermark masih terdeteksi pasca-serangan")
    watermark: Optional[str] = Field(None, description="Teks watermark yang diekstrak")
    valid_blocks: int = Field(..., description="Jumlah blok yang lolos verifikasi integritas")
    total_blocks: int = Field(..., description="Total blok pada citra")
    tamper_ratio: float = Field(..., description="Proporsi blok yang terdeteksi berubah (0.0–1.0)")


def apply_image_attack(image: Image.Image, attack_type: str) -> Image.Image:
    """
    Terapkan simulasi serangan sesuai PRD.

    Intensitas serangan dipilih agar efek visual jelas terlihat saat demo,
    sekaligus cukup untuk merusak LSB fragile watermark.
    """
    img = image.copy()

    if attack_type == "jpeg_90":
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    if attack_type == "jpeg_70":
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    if attack_type == "jpeg_50":
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=50)
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    if attack_type == "crop":
        # Zeroing 15% area kanan-bawah; dimensi citra tetap sama
        w, h = img.size
        arr = np.array(img, dtype=np.uint8)
        arr[h - max(1, int(h * 0.15)):, w - max(1, int(w * 0.15)):] = 0
        return Image.fromarray(arr, mode="RGB")

    if attack_type == "resize":
        # Downsample 50% → upsample kembali; interpolasi ganda merusak LSB secara merata
        w, h = img.size
        small = img.resize((max(1, w // 2), max(1, h // 2)), Image.Resampling.BILINEAR)
        return small.resize((w, h), Image.Resampling.BILINEAR)

    if attack_type == "noise":
        # Gaussian noise std=25, seed deterministik agar reproducible
        rng = np.random.default_rng(seed=42)
        arr = np.array(img, dtype=np.int16)
        arr = np.clip(arr + rng.normal(0, 25, arr.shape).astype(np.int16), 0, 255).astype(np.uint8)
        return Image.fromarray(arr, mode="RGB")

    if attack_type == "brightness":
        return ImageEnhance.Brightness(img).enhance(1.6)

    if attack_type == "contrast":
        return ImageEnhance.Contrast(img).enhance(2.0)

    raise ValueError(f"Jenis serangan tidak dikenal: {attack_type}")


@router.post("/attack", response_model=AttackResponse, summary="Simulasi serangan citra dan verifikasi ketahanan watermark (Fragile LSB)")
async def attack_endpoint(
    image: UploadFile = File(..., description="Berkas citra ber-watermark (PNG atau JPEG)"),
    secret_key: str = Form(..., description="Kunci rahasia PRNG"),
    attack_type: str = Form(..., description="Jenis serangan yang akan disimulasikan"),
    original_watermark: Optional[str] = Form(None, description="Watermark referensi untuk kalkulasi NC & BER (opsional)"),
) -> Dict[str, object]:
    clean_key = secret_key.strip()
    if not clean_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secret key tidak boleh kosong.")

    clean_attack = attack_type.strip()
    if clean_attack not in VALID_ATTACKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Jenis serangan '{clean_attack}' tidak didukung. Pilihan valid: {', '.join(sorted(VALID_ATTACKS))}.",
        )

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
    rgb_before = pil_image.convert("RGB")

    try:
        rgb_after = apply_image_attack(rgb_before, clean_attack)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Kesalahan tidak terduga saat menerapkan serangan")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal melakukan simulasi serangan pada citra.")

    try:
        detect_result = detect_watermark(image=rgb_after, secret_key=clean_key, original_watermark=clean_original_watermark)
    except Exception:
        logger.exception("Kesalahan tidak terduga saat deteksi watermark pasca-serangan")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal memproses deteksi watermark pasca-serangan.")

    return {
        "before_image": image_to_data_url(rgb_before),
        "after_image": image_to_data_url(rgb_after),
        "tamper_map": image_to_data_url(detect_result["tamper_map"]),
        "psnr": float(calculate_psnr(rgb_before, rgb_after)),
        "mse": float(calculate_mse(rgb_before, rgb_after)),
        "nc": detect_result["nc"],
        "ber": detect_result["ber"],
        "watermark_detected": detect_result["watermark_detected"],
        "watermark": detect_result["watermark"],
        "valid_blocks": detect_result["valid_blocks"],
        "total_blocks": detect_result["total_blocks"],
        "tamper_ratio": detect_result["tamper_ratio"],
    }
