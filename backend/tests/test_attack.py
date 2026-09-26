"""Unit test untuk endpoint simulasi serangan watermark (/api/attack)."""

import io
from fastapi.testclient import TestClient
from PIL import Image
import pytest

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
