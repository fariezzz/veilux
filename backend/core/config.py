"""Konfigurasi aplikasi Veilux backend."""

from typing import List


class Settings:
    PROJECT_NAME: str = "Veilux Digital Watermarking"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"

    # Batasan validasi citra
    MAX_IMAGE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
    ALLOWED_IMAGE_TYPES: List[str] = ["image/png", "image/jpeg"]

    # Batasan validasi watermark
    MAX_WATERMARK_LENGTH: int = 64

    # CORS configuration
    CORS_ORIGINS: List[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:5500",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
        "*",
    ]


settings = Settings()
