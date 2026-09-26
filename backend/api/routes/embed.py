"""Route handler untuk penyisipan watermark (embed)."""

from __future__ import annotations

import base64
import io
import logging
from typing import Dict, Optional, Union

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from PIL import Image
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.services.logo import (
    normalize_logo,
    pack_binary_logo,
    reconstruct_logo,
    serialize_logo_payload,
)
from backend.services.watermark import (
    CapacityExceededError,
    bytes_to_bits,
    calculate_mse,
    calculate_psnr,
    embed_watermark,
    get_image_blocks,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class EmbedResponse(BaseModel):
    original_image: str = Field(..., description="Data URL citra asli (PNG base64)")
    watermarked_image: str = Field(..., description="Data URL citra ber-watermark (PNG base64)")
    psnr: float = Field(..., description="Peak Signal-to-Noise Ratio (dB)")
    mse: float = Field(..., description="Mean Squared Error")
    watermark_type: str = Field("text", description="Tipe watermark: 'text' atau 'logo'")
    logo_width: Optional[int] = Field(None, description="Lebar logo jika tipe logo")
    logo_height: Optional[int] = Field(None, description="Tinggi logo jika tipe logo")
    binary_logo_image: Optional[str] = Field(None, description="Data URL binary logo hasil normalisasi (PNG base64)")


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
    secret_key: str = Form(..., description="Kunci rahasia PRNG"),
    watermark_type: str = Form("text", description="Tipe watermark: 'text' atau 'logo'"),
    watermark: Optional[str] = Form(None, description="Teks payload watermark (untuk tipe text)"),
    logo: Optional[UploadFile] = File(None, description="Berkas citra logo (untuk tipe logo)"),
) -> Dict[str, object]:
    clean_key = secret_key.strip() if secret_key else ""
    if not clean_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Secret key tidak boleh kosong.")

    clean_type = (watermark_type or "text").strip().lower()
    if clean_type not in ("text", "logo"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipe watermark '{clean_type}' tidak didukung. Pilihan valid: text, logo.",
        )

    contents = await _read_image_upload(image)
    pil_image = _load_image(contents)
    rgb_original = pil_image.convert("RGB")

    logo_w: Optional[int] = None
    logo_h: Optional[int] = None
    binary_logo_data_url: Optional[str] = None

    if clean_type == "text":
        if logo is not None and getattr(logo, "filename", None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Jangan sertakan berkas logo saat tipe watermark adalah teks.",
            )

        clean_watermark = watermark.strip() if watermark else ""
        if not clean_watermark:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload watermark tidak boleh kosong.")
        if len(clean_watermark) > settings.MAX_WATERMARK_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panjang watermark melebihi batas (maksimal {settings.MAX_WATERMARK_LENGTH} karakter).",
            )

        payload_to_embed: Union[str, bytes] = clean_watermark

    else:
        # Tipe LOGO
        if watermark is not None and watermark.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Jangan sertakan teks watermark saat tipe watermark adalah logo.",
            )

        if logo is None or not getattr(logo, "filename", None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Berkas logo wajib diunggah untuk tipe watermark logo.",
            )

        logo_contents = await _read_image_upload(logo)
        logo_pil = _load_image(logo_contents)

        bin_logo = normalize_logo(logo_pil, max_size=(64, 64), threshold=128)
        packed_bytes, lw, lh = pack_binary_logo(bin_logo)
        packet_bytes = serialize_logo_payload(packed_bytes, secret_key=clean_key, width=lw, height=lh)

        # Pemeriksaan kapasitas kanal citra sampul
        needed_bits = len(bytes_to_bits(packet_bytes))
        total_channels = rgb_original.width * rgb_original.height * 3
        blocks = get_image_blocks(rgb_original.width, rgb_original.height)
        available_channels = total_channels - (len(blocks) * 64)

        if needed_bits > available_channels:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Kapasitas citra tidak mencukupi: logo watermark ({lw}x{lh}, membutuhkan {needed_bits} bit) "
                    f"terlalu besar untuk kapasitas citra cover (tersedia {available_channels} bit)."
                ),
            )

        payload_to_embed = packet_bytes
        logo_w, logo_h = lw, lh
        recon_img = reconstruct_logo(bin_logo)
        binary_logo_data_url = image_to_data_url(recon_img)

    try:
        embed_result = embed_watermark(image=rgb_original, watermark=payload_to_embed, secret_key=clean_key)
    except CapacityExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Kesalahan tidak terduga saat embedding watermark")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal memproses penyisipan watermark pada citra.",
        )

    stego_image: Image.Image = embed_result["stego_image"]

    return {
        "original_image": image_to_data_url(rgb_original),
        "watermarked_image": image_to_data_url(stego_image),
        "psnr": float(calculate_psnr(rgb_original, stego_image)),
        "mse": float(calculate_mse(rgb_original, stego_image)),
        "watermark_type": clean_type,
        "logo_width": logo_w,
        "logo_height": logo_h,
        "binary_logo_image": binary_logo_data_url,
    }
