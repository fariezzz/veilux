"""Pengujian endpoint kesehatan dan endpoint embed Veilux."""

import io
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.main import app
from backend.api.routes.embed import image_to_data_url

client = TestClient(app)


def create_in_memory_image(width: int = 128, height: int = 128, format: str = "PNG") -> io.BytesIO:
    """Membuat buffer berkas citra sintetis di memori."""
    img = Image.new("RGB", (width, height), color=(100, 140, 180))
    buf = io.BytesIO()
    img.save(buf, format=format)
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════════════
# 1. TEST GET /api/health
# ══════════════════════════════════════════════════════════════════
def test_health_check_returns_200_and_expected_payload():
    """Uji bahwa GET /api/health mengembalikan HTTP 200 dan status 'ok'."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "veilux-backend"}


# ══════════════════════════════════════════════════════════════════
# 2. TEST POST /api/embed (VALID REQUEST & RESPONS FORMAT)
# ══════════════════════════════════════════════════════════════════
def test_embed_valid_png_returns_200_and_correct_format():
    """Uji bahwa POST /api/embed dengan PNG valid mengembalikan HTTP 200 dengan struktur lengkap."""
    img_buf = create_in_memory_image(width=120, height=120, format="PNG")
    files = {"image": ("sample.png", img_buf, "image/png")}
    data = {
        "watermark": "VEILUX-247006111146",
        "secret_key": "MySecureSecretKey123",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert "original_image" in json_resp
    assert "watermarked_image" in json_resp
    assert "psnr" in json_resp
    assert "mse" in json_resp

    # Verifikasi prefix Data URL
    assert json_resp["original_image"].startswith("data:image/png;base64,")
    assert json_resp["watermarked_image"].startswith("data:image/png;base64,")

    # Verifikasi nilai metrik
    assert json_resp["mse"] >= 0.0
    assert json_resp["psnr"] > 30.0


def test_embed_valid_jpeg_returns_200():
    """Uji bahwa POST /api/embed juga mendukung citra JPEG yang valid."""
    img_buf = create_in_memory_image(width=128, height=128, format="JPEG")
    files = {"image": ("photo.jpg", img_buf, "image/jpeg")}
    data = {
        "watermark": "VEILUX-JPEG-TEST",
        "secret_key": "JpegKey2026",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["watermarked_image"].startswith("data:image/png;base64,")
    assert json_resp["psnr"] > 30.0


# ══════════════════════════════════════════════════════════════════
# 3. TEST VALIDASI ERROR (HTTP 400 & 422)
# ══════════════════════════════════════════════════════════════════
def test_embed_rejects_empty_watermark():
    """Payload watermark kosong harus ditolak dengan HTTP 400."""
    img_buf = create_in_memory_image(width=80, height=80)
    files = {"image": ("test.png", img_buf, "image/png")}
    data = {
        "watermark": "   ",
        "secret_key": "mysecret",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 400
    assert "Payload watermark tidak boleh kosong" in response.json()["detail"]


def test_embed_rejects_empty_secret_key():
    """Secret key kosong harus ditolak dengan HTTP 400."""
    img_buf = create_in_memory_image(width=80, height=80)
    files = {"image": ("test.png", img_buf, "image/png")}
    data = {
        "watermark": "VEILUX-TEST",
        "secret_key": "   ",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 400
    assert "Secret key tidak boleh kosong" in response.json()["detail"]


def test_embed_rejects_unsupported_file_type():
    """Berkas teks atau non-PNG/JPEG harus ditolak dengan HTTP 400."""
    fake_txt = io.BytesIO(b"Bukan sebuah gambar")
    files = {"image": ("test.txt", fake_txt, "text/plain")}
    data = {
        "watermark": "VEILUX-TEST",
        "secret_key": "mysecret",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 400
    assert "Format berkas tidak didukung" in response.json()["detail"]


def test_embed_rejects_corrupted_image():
    """Berkas citra rusak dengan content-type image/png harus ditolak dengan HTTP 400."""
    corrupted_data = io.BytesIO(b"\x89PNG\r\n\x1a\nCorruptedGarbageBytes...")
    files = {"image": ("corrupted.png", corrupted_data, "image/png")}
    data = {
        "watermark": "VEILUX-TEST",
        "secret_key": "mysecret",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 400
    assert "Berkas citra rusak atau tidak dapat dibaca" in response.json()["detail"]


def test_embed_rejects_insufficient_capacity_with_422():
    """Citra kecil yang tidak mencukupi bit paket harus ditolak dengan HTTP 422."""
    # 4x4 piksel = 16 piksel = 48 kanal RGB.
    # Paket watermark minimum adalah 22 byte = 176 bit.
    small_buf = create_in_memory_image(width=4, height=4, format="PNG")
    files = {"image": ("tiny.png", small_buf, "image/png")}
    data = {
        "watermark": "A",
        "secret_key": "mysecret",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Kapasitas citra tidak mencukupi" in detail
    assert "bit" in detail or "kanal" in detail


def test_embed_rejects_watermark_longer_than_64_chars():
    """Watermark lebih dari 64 karakter harus ditolak dengan HTTP 400."""
    img_buf = create_in_memory_image(width=80, height=80)
    files = {"image": ("test.png", img_buf, "image/png")}
    data = {
        "watermark": "A" * 65,
        "secret_key": "mysecret",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 400
    assert "Panjang watermark melebihi batas" in response.json()["detail"]


def test_embed_rejects_oversized_file():
    """Berkas melebihi 10 MB harus ditolak dengan HTTP 400."""
    oversized = io.BytesIO(b"0" * (10 * 1024 * 1024 + 1))
    files = {"image": ("big.png", oversized, "image/png")}
    data = {
        "watermark": "VEILUX-TEST",
        "secret_key": "mysecret",
    }

    response = client.post("/api/embed", files=files, data=data)
    assert response.status_code == 400
    assert "Ukuran file melebihi batas 10 MB" in response.json()["detail"]


# ══════════════════════════════════════════════════════════════════
# 4. TEST UTILITAS image_to_data_url
# ══════════════════════════════════════════════════════════════════
def test_image_to_data_url_utility():
    """Uji fungsi utilitas konversi PIL Image ke Data URL."""
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    data_url = image_to_data_url(img, format="PNG")
    assert isinstance(data_url, str)
    assert data_url.startswith("data:image/png;base64,")
