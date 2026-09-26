"""Unit test untuk endpoint simulasi serangan watermark (/api/attack)."""

import base64
import io

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from backend.api.routes.attack import VALID_ATTACKS
from backend.main import app
from backend.services.watermark import embed_watermark

client = TestClient(app)


@pytest.fixture
def sample_stego_png_bytes():
    """Membuat citra stego valid dalam bentuk buffer PNG bytes."""
    cover = Image.new("RGB", (128, 128), color=(140, 150, 160))
    stego = embed_watermark(cover, watermark="VEILUX-ATTACK-TEST", secret_key="kunci-rahasia-uji")["stego_image"]
    buf = io.BytesIO()
    stego.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def test_attack_valid_request(sample_stego_png_bytes):
    """Pengujian simulasi serangan jpeg_90 dengan parameter valid menghasilkan 200 OK."""
    files = {"image": ("stego.png", io.BytesIO(sample_stego_png_bytes), "image/png")}
    data = {
        "secret_key": "kunci-rahasia-uji",
        "attack_type": "jpeg_90",
        "original_watermark": "VEILUX-ATTACK-TEST",
    }
    response = client.post("/api/attack", files=files, data=data)
    assert response.status_code == 200
    res = response.json()
    assert "before_image" in res
    assert "after_image" in res
    assert "tamper_map" in res
    assert "psnr" in res
    assert "mse" in res
    assert "watermark_detected" in res


def test_attack_crop_reduces_dimensions_and_preserves_remaining_pixels(sample_stego_png_bytes):
    """
    Pengujian crop attack:
    1. Memotong sebagian citra secara nyata (dimensi berkurang).
    2. Bukan sekadar zeroing/masking dengan padding hitam.
    3. Piksel pada area yang tersisa dipertahankan utuh.
    """
    files = {"image": ("stego.png", io.BytesIO(sample_stego_png_bytes), "image/png")}
    data = {
        "secret_key": "kunci-rahasia-uji",
        "attack_type": "crop",
        "original_watermark": "VEILUX-ATTACK-TEST",
    }
    response = client.post("/api/attack", files=files, data=data)
    assert response.status_code == 200
    res = response.json()

    # Decode after_image
    _, b64_after = res["after_image"].split(",", 1)
    after_img = Image.open(io.BytesIO(base64.b64decode(b64_after)))

    # Dimensi asli 128x128, crop 15% width (19px) dan 15% height (19px) -> 109x109
    expected_w = 128 - max(1, int(128 * 0.15))
    expected_h = 128 - max(1, int(128 * 0.15))
    assert after_img.size == (expected_w, expected_h)
    assert after_img.size != (128, 128)

    # Pastikan piksel pada area hasil crop sama persis dengan bagian kiri-atas stego
    stego_img = Image.open(io.BytesIO(sample_stego_png_bytes))
    expected_crop = stego_img.crop((0, 0, expected_w, expected_h))
    diff = np.array(after_img) - np.array(expected_crop)
    assert np.all(diff == 0), "Piksel area yang tersisa harus identik dengan citra asli"

    # Decode tamper map dan periksa dimensinya
    _, b64_tamper = res["tamper_map"].split(",", 1)
    tamper_img = Image.open(io.BytesIO(base64.b64decode(b64_tamper)))
    assert tamper_img.size == (expected_w, expected_h)

    # Metrik evaluasi tetap terhitung valid
    assert res["mse"] > 0
    assert res["psnr"] > 0
    assert res["watermark_detected"] is False


@pytest.mark.parametrize("attack_type", sorted(VALID_ATTACKS))
def test_all_attack_types_succeed(sample_stego_png_bytes, attack_type):
    """Pengujian memastikan semua jenis serangan yang didukung dapat dieksekusi sukses."""
    files = {"image": ("stego.png", io.BytesIO(sample_stego_png_bytes), "image/png")}
    data = {
        "secret_key": "kunci-rahasia-uji",
        "attack_type": attack_type,
        "original_watermark": "VEILUX-ATTACK-TEST",
    }
    response = client.post("/api/attack", files=files, data=data)
    assert response.status_code == 200
    res = response.json()
    assert res["before_image"].startswith("data:image/png;base64,")
    assert res["after_image"].startswith("data:image/png;base64,")
    assert res["tamper_map"].startswith("data:image/png;base64,")
    assert isinstance(res["psnr"], float)
    assert isinstance(res["mse"], float)


def test_attack_rejects_unsupported_attack_type(sample_stego_png_bytes):
    """Pengujian penolakan jenis serangan tidak dikenal dengan 400 Bad Request."""
    files = {"image": ("stego.png", io.BytesIO(sample_stego_png_bytes), "image/png")}
    data = {
        "secret_key": "kunci-rahasia-uji",
        "attack_type": "invalid_attack_type",
    }
    response = client.post("/api/attack", files=files, data=data)
    assert response.status_code == 400
    assert "tidak didukung" in response.json()["detail"]


def test_attack_rejects_empty_secret_key(sample_stego_png_bytes):
    """Pengujian penolakan secret key kosong dengan 400 Bad Request."""
    files = {"image": ("stego.png", io.BytesIO(sample_stego_png_bytes), "image/png")}
    data = {
        "secret_key": "   ",
        "attack_type": "crop",
    }
    response = client.post("/api/attack", files=files, data=data)
    assert response.status_code == 400
    assert "Secret key tidak boleh kosong" in response.json()["detail"]
