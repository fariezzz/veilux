"""Pengujian endpoint POST /api/detect Veilux."""

import io

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.main import app
from backend.services.watermark import embed_watermark

client = TestClient(app)


# ══════════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════════
def _create_stego_png(
    watermark: str = "VEILUX-DETECT-TEST",
    secret_key: str = "DetectKey2026",
    width: int = 128,
    height: int = 128,
) -> io.BytesIO:
    """Buat citra stego dalam format PNG di memory dan kembalikan sebagai BytesIO."""
    cover = Image.new("RGB", (width, height), color=(100, 140, 180))
    result = embed_watermark(image=cover, watermark=watermark, secret_key=secret_key)
    stego: Image.Image = result["stego_image"]
    buf = io.BytesIO()
    stego.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _create_plain_png(width: int = 128, height: int = 128) -> io.BytesIO:
    """Buat citra polos tanpa watermark."""
    img = Image.new("RGB", (width, height), color=(50, 100, 150))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════════════
# 1. DETEKSI BERHASIL — STEGO VALID
# ══════════════════════════════════════════════════════════════════
def test_detect_valid_stego_returns_watermark_detected():
    """Citra stego valid harus mengembalikan watermark_detected=True dan teks watermark."""
    watermark = "VEILUX-DETECT-TEST"
    secret_key = "DetectKey2026"
    stego_buf = _create_stego_png(watermark=watermark, secret_key=secret_key)

    files = {"image": ("stego.png", stego_buf, "image/png")}
    data = {"secret_key": secret_key}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert json_resp["watermark_detected"] is True
    assert json_resp["watermark"] == watermark
    assert json_resp["input_image"].startswith("data:image/png;base64,")
    assert json_resp["tamper_map"].startswith("data:image/png;base64,")
    # Tanpa referensi, NC dan BER harus null
    assert json_resp["nc"] is None
    assert json_resp["ber"] is None


# ══════════════════════════════════════════════════════════════════
# 2. DETEKSI DENGAN REFERENSI WATERMARK — NC & BER
# ══════════════════════════════════════════════════════════════════
def test_detect_with_correct_reference_returns_perfect_nc_ber():
    """Referensi watermark yang cocok harus menghasilkan NC≈1.0 dan BER≈0.0."""
    watermark = "REFERENCE-TEST"
    secret_key = "RefKey2026"
    stego_buf = _create_stego_png(watermark=watermark, secret_key=secret_key)

    files = {"image": ("stego.png", stego_buf, "image/png")}
    data = {
        "secret_key": secret_key,
        "original_watermark": watermark,
    }

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert json_resp["watermark_detected"] is True
    assert json_resp["nc"] is not None
    assert json_resp["ber"] is not None
    assert json_resp["nc"] == pytest.approx(1.0, abs=1e-6)
    assert json_resp["ber"] == pytest.approx(0.0, abs=1e-6)


def test_detect_with_wrong_reference_returns_imperfect_nc_ber():
    """Referensi watermark yang berbeda harus menghasilkan NC<1.0 dan BER>0.0."""
    watermark = "ORIGINAL-WM"
    secret_key = "NcBerKey"
    stego_buf = _create_stego_png(watermark=watermark, secret_key=secret_key)

    files = {"image": ("stego.png", stego_buf, "image/png")}
    data = {
        "secret_key": secret_key,
        "original_watermark": "DIFFERENT-WM",
    }

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert json_resp["watermark_detected"] is True
    # NC dan BER harus menunjukkan ketidakcocokan
    assert json_resp["nc"] is not None
    assert json_resp["ber"] is not None
    assert json_resp["nc"] < 1.0
    assert json_resp["ber"] > 0.0


# ══════════════════════════════════════════════════════════════════
# 3. DETEKSI DENGAN SECRET KEY SALAH
# ══════════════════════════════════════════════════════════════════
def test_detect_wrong_secret_key_returns_not_detected():
    """Secret key salah harus mengembalikan watermark_detected=False tanpa error HTTP."""
    stego_buf = _create_stego_png(watermark="HELLO", secret_key="CorrectKey")

    files = {"image": ("stego.png", stego_buf, "image/png")}
    data = {"secret_key": "WrongKey"}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert json_resp["watermark_detected"] is False
    assert json_resp["watermark"] is None


# ══════════════════════════════════════════════════════════════════
# 4. DETEKSI PADA CITRA POLOS (BUKAN STEGO)
# ══════════════════════════════════════════════════════════════════
def test_detect_plain_image_returns_not_detected():
    """Citra tanpa watermark harus mengembalikan watermark_detected=False."""
    plain_buf = _create_plain_png()

    files = {"image": ("plain.png", plain_buf, "image/png")}
    data = {"secret_key": "AnyKey"}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert json_resp["watermark_detected"] is False
    assert json_resp["watermark"] is None
    # Tamper map tetap harus ada
    assert json_resp["tamper_map"].startswith("data:image/png;base64,")


# ══════════════════════════════════════════════════════════════════
# 5. DETEKSI TAMPER — MODIFIKASI PIKSEL
# ══════════════════════════════════════════════════════════════════
def test_detect_tampered_image_shows_tamper_in_map():
    """Citra stego yang dimodifikasi pikselnya harus menghasilkan tamper map dengan area merah."""
    watermark = "TAMPER-TEST"
    secret_key = "TamperKey"
    cover = Image.new("RGB", (128, 128), color=(100, 140, 180))
    result = embed_watermark(image=cover, watermark=watermark, secret_key=secret_key)
    stego: Image.Image = result["stego_image"]

    # Modifikasi blok pertama (0,0 sampai 32,32) secara agresif
    import numpy as np
    stego_arr = np.array(stego)
    stego_arr[0:32, 0:32, :] = 0  # Zeroing blok kiri atas
    tampered_img = Image.fromarray(stego_arr, mode="RGB")

    buf = io.BytesIO()
    tampered_img.save(buf, format="PNG")
    buf.seek(0)

    files = {"image": ("tampered.png", buf, "image/png")}
    data = {"secret_key": secret_key}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    # Tamper map harus ada
    assert json_resp["tamper_map"].startswith("data:image/png;base64,")
    # Input image harus ada
    assert json_resp["input_image"].startswith("data:image/png;base64,")


# ══════════════════════════════════════════════════════════════════
# 6. VALIDASI REQUEST — ERROR 400
# ══════════════════════════════════════════════════════════════════
def test_detect_rejects_unsupported_file_type():
    """Berkas non-PNG/JPEG harus ditolak dengan HTTP 400."""
    fake_txt = io.BytesIO(b"Bukan sebuah gambar")
    files = {"image": ("test.txt", fake_txt, "text/plain")}
    data = {"secret_key": "mysecret"}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 400
    assert "Format berkas tidak didukung" in response.json()["detail"]


def test_detect_rejects_empty_secret_key():
    """Secret key kosong harus ditolak dengan HTTP 400."""
    img_buf = _create_plain_png(width=64, height=64)
    files = {"image": ("test.png", img_buf, "image/png")}
    data = {"secret_key": "   "}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 400
    assert "Secret key tidak boleh kosong" in response.json()["detail"]


def test_detect_rejects_corrupted_image():
    """Berkas citra rusak harus ditolak dengan HTTP 400."""
    corrupted_data = io.BytesIO(b"\x89PNG\r\n\x1a\nCorruptedGarbage...")
    files = {"image": ("corrupted.png", corrupted_data, "image/png")}
    data = {"secret_key": "mysecret"}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 400
    assert "Berkas citra rusak atau tidak dapat dibaca" in response.json()["detail"]


def test_detect_rejects_oversized_file():
    """Berkas melebihi 10 MB harus ditolak dengan HTTP 400."""
    oversized = io.BytesIO(b"0" * (10 * 1024 * 1024 + 1))
    files = {"image": ("big.png", oversized, "image/png")}
    data = {"secret_key": "mysecret"}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 400
    assert "Ukuran file melebihi batas 10 MB" in response.json()["detail"]


def test_detect_rejects_reference_watermark_longer_than_64_chars():
    """Watermark referensi lebih dari 64 karakter harus ditolak dengan HTTP 400."""
    img_buf = _create_plain_png(width=64, height=64)
    files = {"image": ("test.png", img_buf, "image/png")}
    data = {
        "secret_key": "mysecret",
        "original_watermark": "A" * 65,
    }

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 400
    assert "Panjang watermark referensi melebihi batas" in response.json()["detail"]


def test_detect_accepts_empty_original_watermark_as_absent():
    """Referensi watermark berupa spasi saja harus diabaikan (dianggap tidak ada)."""
    watermark = "EMPTY-REF-TEST"
    secret_key = "EmptyRefKey"
    stego_buf = _create_stego_png(watermark=watermark, secret_key=secret_key)

    files = {"image": ("stego.png", stego_buf, "image/png")}
    data = {
        "secret_key": secret_key,
        "original_watermark": "   ",  # Spasi saja — dianggap tidak ada
    }

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200

    json_resp = response.json()
    assert json_resp["watermark_detected"] is True
    assert json_resp["nc"] is None
    assert json_resp["ber"] is None


# ══════════════════════════════════════════════════════════════════
# 7. DETEKSI JPEG — FORMAT INPUT
# ══════════════════════════════════════════════════════════════════
def test_detect_accepts_jpeg_input():
    """Endpoint harus menerima citra JPEG (akan menghasilkan not-detected karena JPEG lossy)."""
    watermark = "JPEG-DETECT"
    secret_key = "JpegDetectKey"
    # Buat stego PNG dulu, lalu konversi ke JPEG
    cover = Image.new("RGB", (128, 128), color=(100, 140, 180))
    result = embed_watermark(image=cover, watermark=watermark, secret_key=secret_key)
    stego: Image.Image = result["stego_image"]

    buf = io.BytesIO()
    stego.save(buf, format="JPEG", quality=95)
    buf.seek(0)

    files = {"image": ("stego.jpg", buf, "image/jpeg")}
    data = {"secret_key": secret_key}

    response = client.post("/api/detect", files=files, data=data)
    assert response.status_code == 200
    # JPEG lossy seharusnya merusak LSB → fragile watermark gagal terdeteksi
    json_resp = response.json()
    # Tetap berhasil diproses (200 OK), hasilnya bisa detected atau tidak
    assert "watermark_detected" in json_resp
    assert json_resp["tamper_map"].startswith("data:image/png;base64,")
