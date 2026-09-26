"""Watermarking service package."""

from backend.services.logo import (
    WatermarkType,
    normalize_logo,
    pack_binary_logo,
    parse_logo_payload,
    parse_watermark_packet,
    reconstruct_logo,
    serialize_logo_payload,
    unpack_binary_logo,
)
from backend.services.watermark import (
    CapacityExceededError,
    WatermarkValidationError,
    calculate_mse,
    calculate_psnr,
    detect_watermark,
    embed_watermark,
    extract_watermark,
)
