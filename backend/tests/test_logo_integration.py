"""Pengujian integrasi dan regresi Logo Watermark (Stage 3D).

Mencakup:
1. Roundtrip embed -> detect logo via API & service.
2. Kesesuaian piksel biner terekonstruksi dengan biner ternormalisasi.
3. Preservasi berbagai variasi dimensi logo (64x64, 64x40, 40x64, 15x13).
4. Verifikasi integritas HMAC: kunci benar, kunci salah, manipulasi payload stego.
5. Regresi watermark teks (alur lama tetap 100% berfungsi).
6. Regresi 8 modul serangan terhadap citra stego ber-watermark logo.
7. Pengujian pembatasan kapasitas kanal (penolakan 422 pada citra terlalu kecil).
8. Validasi input API (parameter kontradiktif atau tidak lengkap).
"""

import base64
import io

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from backend.main import app
from backend.services.logo import (
    WatermarkType,
    normalize_logo,
    pack_binary_logo,
    serialize_logo_payload,
)
from backend.services.watermark import (
    calculate_mse,
    calculate_psnr,
    detect_watermark,
    embed_watermark,
)

client = TestClient(app)


def _create_image_bytes(width: int = 128, height: int = 128, color=(140, 150, 160)) -> bytes:
    """Helper membuat bytes PNG citra sintetis."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_logo_bytes(width: int = 64, height: int = 40) -> bytes:
    """Helper membuat bytes PNG logo sintetis bermotif geometris."""
    # Buat logo dengan pola kontras tinggi
    arr = np.zeros((height, width), dtype=np.uint8)
    arr[: height // 2, : width // 2] = 255
    arr[height // 2 :, width // 2 :] = 255
    logo_img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    logo_img.save(buf, format="PNG")
    return buf.getvalue()


# 1. Roundtrip Embed -> Detect Logo
def test_logo_embed_and_detect_roundtrip_via_api():
    """Logo di-embed via /api/embed lalu dideteksi via /api/detect menghasilkan biner identik."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(64, 40)
    secret_key = "KunciIntegrasiLogo2026"

    # 1. Embed via API
    files = {
        "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
        "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
    }
    data = {
        "secret_key": secret_key,
        "watermark_type": "logo",
    }
    embed_res = client.post("/api/embed", files=files, data=data)
    assert embed_res.status_code == 200
    embed_json = embed_res.json()

    assert embed_json["watermark_type"] == "logo"
    assert embed_json["logo_width"] == 64
    assert embed_json["logo_height"] == 40
    assert embed_json["psnr"] > 40.0
    assert embed_json["mse"] < 1.0

    # 2. Detect via API
    _, stego_b64 = embed_json["watermarked_image"].split(",", 1)
    stego_bytes = base64.b64decode(stego_b64)

    detect_files = {"image": ("stego.png", io.BytesIO(stego_bytes), "image/png")}
    detect_data = {"secret_key": secret_key}

    detect_res = client.post("/api/detect", files=detect_files, data=detect_data)
    assert detect_res.status_code == 200
    detect_json = detect_res.json()

    assert detect_json["watermark_detected"] is True
    assert detect_json["watermark_type"] == "LOGO"
    assert detect_json["logo_width"] == 64
    assert detect_json["logo_height"] == 40
    assert detect_json["logo_image"].startswith("data:image/png;base64,")
    assert detect_json["valid_blocks"] == detect_json["total_blocks"] == 16
    assert detect_json["tamper_ratio"] == 0.0

    # 3. Verifikasi kesesuaian piksel biner hasil ekstraksi dengan biner ternormalisasi asli
    _, logo_b64 = detect_json["logo_image"].split(",", 1)
    extracted_logo_img = Image.open(io.BytesIO(base64.b64decode(logo_b64)))

    original_logo_img = Image.open(io.BytesIO(logo_bytes))
    normalized_expected = normalize_logo(original_logo_img, max_size=(64, 64))

    extracted_arr = (np.array(extracted_logo_img) >= 128).astype(np.uint8)
    assert np.array_equal(extracted_arr, normalized_expected), "Biner logo hasil rekonstruksi harus identik!"


# 2. Preservasi Berbagai Dimensi Logo
@pytest.mark.parametrize(
    "logo_w,logo_h",
    [
        (64, 64),
        (64, 40),
        (40, 64),
        (15, 13),
    ],
)
def test_logo_dimension_preservation_across_aspect_ratios(logo_w, logo_h):
    """Pengujian logo dengan beragam rasio dimensi mempertahankan ukuran asli saat rekonstruksi."""
    cover = Image.new("RGB", (128, 128), (130, 140, 150))
    secret_key = f"KeyRatio_{logo_w}_{logo_h}"

    raw_logo = Image.new("L", (logo_w, logo_h), color=180)
    bin_logo = normalize_logo(raw_logo, max_size=(64, 64))
    assert bin_logo.shape == (logo_h, logo_w)

    packed, lw, lh = pack_binary_logo(bin_logo)
    packet = serialize_logo_payload(packed, secret_key=secret_key, width=lw, height=lh)

    embed_res = embed_watermark(cover, watermark=packet, secret_key=secret_key)
    detect_res = detect_watermark(embed_res["stego_image"], secret_key=secret_key)

    assert detect_res["watermark_detected"] is True
    assert detect_res["watermark_type"] == "LOGO"
    assert detect_res["logo_width"] == logo_w
    assert detect_res["logo_height"] == logo_h
    assert detect_res["logo_image"].size == (logo_w, logo_h)
    assert np.array_equal(detect_res["binary_logo"], bin_logo)


# 3. Pengujian Integritas HMAC (Kunci Salah & Manipulasi)
def test_logo_wrong_secret_key_fails_verification():
    """Deteksi dengan kunci yang salah tidak menganggap logo valid dan menolak ekstraksi."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(32, 32)

    files = {
        "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
        "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
    }
    data = {"secret_key": "KunciBenar123", "watermark_type": "logo"}
    embed_res = client.post("/api/embed", files=files, data=data)
    assert embed_res.status_code == 200

    _, stego_b64 = embed_res.json()["watermarked_image"].split(",", 1)
    stego_bytes = base64.b64decode(stego_b64)

    detect_files = {"image": ("stego.png", io.BytesIO(stego_bytes), "image/png")}
    detect_data = {"secret_key": "KunciSalah999"}  # Kunci salah

    detect_res = client.post("/api/detect", files=detect_files, data=detect_data)
    assert detect_res.status_code == 200
    res_json = detect_res.json()

    assert res_json["watermark_detected"] is False
    assert res_json["watermark_type"] is None
    assert res_json["logo_image"] is None


def test_logo_corrupted_payload_fails_hmac():
    """Manipulasi pada bit kanal payload stego memicu kegagalan HMAC pada logo."""
    cover = Image.new("RGB", (128, 128), (140, 150, 160))
    secret_key = "HMACIntegrityKey"
    raw_logo = Image.new("L", (32, 32), 200)
    bin_logo = normalize_logo(raw_logo, max_size=(64, 64))

    packed, lw, lh = pack_binary_logo(bin_logo)
    packet = serialize_logo_payload(packed, secret_key=secret_key, width=lw, height=lh)

    embed_res = embed_watermark(cover, watermark=packet, secret_key=secret_key)
    stego_arr = np.array(embed_res["stego_image"])

    # Modifikasi bit LSB pada posisi payload
    pos = embed_res["positions"]
    flat = stego_arr.flatten()
    flat[pos[20:30]] ^= 1  # Flip 10 bit payload
    tampered_stego = Image.fromarray(flat.reshape(stego_arr.shape), mode="RGB")

    detect_res = detect_watermark(tampered_stego, secret_key=secret_key)
    assert detect_res["watermark_detected"] is False
    assert detect_res["logo_image"] is None


# 4. Regresi Watermark Teks
def test_existing_text_watermark_workflow_remains_intact():
    """Memastikan alur kerja watermark teks lama tetap berjalan 100% normal."""
    cover_bytes = _create_image_bytes(128, 128)
    text_wm = "VEILUX-NPM-247006111146"
    secret_key = "LegacyTextKey2026"

    # Embed teks
    files = {"image": ("cover.png", io.BytesIO(cover_bytes), "image/png")}
    data = {
        "secret_key": secret_key,
        "watermark_type": "text",
        "watermark": text_wm,
    }
    embed_res = client.post("/api/embed", files=files, data=data)
    assert embed_res.status_code == 200
    assert embed_res.json()["watermark_type"] == "text"

    # Detect teks dengan referensi
    _, stego_b64 = embed_res.json()["watermarked_image"].split(",", 1)
    stego_bytes = base64.b64decode(stego_b64)

    detect_files = {"image": ("stego.png", io.BytesIO(stego_bytes), "image/png")}
    detect_data = {
        "secret_key": secret_key,
        "original_watermark": text_wm,
    }
    detect_res = client.post("/api/detect", files=detect_files, data=detect_data)
    assert detect_res.status_code == 200
    det_json = detect_res.json()

    assert det_json["watermark_detected"] is True
    assert det_json["watermark_type"] == "TEXT"
    assert det_json["watermark"] == text_wm
    assert det_json["logo_image"] is None
    assert det_json["nc"] == pytest.approx(1.0, abs=1e-5)
    assert det_json["ber"] == pytest.approx(0.0, abs=1e-5)


# 5. Regresi Modul Serangan terhadap Citra Ber-watermark Logo
@pytest.mark.parametrize(
    "attack_type",
    ["jpeg_90", "jpeg_70", "jpeg_50", "crop", "resize", "noise", "brightness", "contrast"],
)
def test_all_attacks_execute_successfully_on_logo_watermarked_image(attack_type):
    """Seluruh 8 jenis simulasi serangan dapat dieksekusi sukses terhadap citra ber-watermark logo."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(32, 32)
    secret_key = "AttackLogoKey"

    embed_files = {
        "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
        "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
    }
    embed_data = {"secret_key": secret_key, "watermark_type": "logo"}
    embed_res = client.post("/api/embed", files=embed_files, data=embed_data)
    assert embed_res.status_code == 200

    _, stego_b64 = embed_res.json()["watermarked_image"].split(",", 1)
    stego_bytes = base64.b64decode(stego_b64)

    attack_files = {"image": ("stego.png", io.BytesIO(stego_bytes), "image/png")}
    attack_data = {
        "secret_key": secret_key,
        "attack_type": attack_type,
    }
    attack_res = client.post("/api/attack", files=attack_files, data=attack_data)
    assert attack_res.status_code == 200
    att_json = attack_res.json()

    assert "before_image" in att_json
    assert "after_image" in att_json
    assert "tamper_map" in att_json
    assert isinstance(att_json["psnr"], float)
    assert isinstance(att_json["mse"], float)
    assert "watermark_detected" in att_json


# 6. Pengujian Batas Kapasitas Kanal Citra
def test_embed_logo_rejects_insufficient_cover_capacity_with_422():
    """Citra cover yang terlalu kecil untuk menampung bit logo harus ditolak dengan HTTP 422."""
    # Citra sampul 16x16 hanya memiliki 768 kanal, tidak cukup untuk paket logo 64x64 (4312 bit)
    tiny_cover_bytes = _create_image_bytes(16, 16)
    logo_bytes = _create_logo_bytes(64, 64)

    files = {
        "image": ("tiny.png", io.BytesIO(tiny_cover_bytes), "image/png"),
        "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
    }
    data = {"secret_key": "AnyKey", "watermark_type": "logo"}
    res = client.post("/api/embed", files=files, data=data)

    assert res.status_code == 422
    assert "Kapasitas citra tidak mencukupi" in res.json()["detail"]


# 7. Validasi Input API
def test_embed_rejects_missing_logo_when_type_is_logo():
    """Tipe watermark logo tanpa menyertakan berkas logo harus ditolak dengan HTTP 400."""
    cover_bytes = _create_image_bytes(128, 128)
    files = {"image": ("cover.png", io.BytesIO(cover_bytes), "image/png")}
    data = {"secret_key": "AnyKey", "watermark_type": "logo"}

    res = client.post("/api/embed", files=files, data=data)
    assert res.status_code == 400
    assert "Berkas logo wajib diunggah" in res.json()["detail"]


def test_embed_rejects_both_text_and_logo_simultaneously():
    """Menyertakan teks watermark saat tipe logo dipilih harus ditolak dengan HTTP 400."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(32, 32)

    files = {
        "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
        "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
    }
    data = {
        "secret_key": "AnyKey",
        "watermark_type": "logo",
        "watermark": "ConflictText",  # Konflik: teks dikirim saat tipe logo
    }
    res = client.post("/api/embed", files=files, data=data)
    assert res.status_code == 400
    assert "Jangan sertakan teks watermark saat tipe watermark adalah logo" in res.json()["detail"]


# 8. Pengujian Khusus Flow NC/BER untuk LOGO dan TEXT
def test_logo_nc_ber_with_same_reference_logo_returns_perfect_metrics():
    """LOGO + logo referensi yang sama menghasilkan BER=0.0 dan NC=1.0."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(64, 40)
    secret_key = "NCBERLogoSameKey"

    embed_res = client.post(
        "/api/embed",
        files={
            "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
            "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
        },
        data={"secret_key": secret_key, "watermark_type": "logo"},
    )
    assert embed_res.status_code == 200
    stego_bytes = base64.b64decode(embed_res.json()["watermarked_image"].split(",", 1)[1])

    detect_res = client.post(
        "/api/detect",
        files={
            "image": ("stego.png", io.BytesIO(stego_bytes), "image/png"),
            "original_logo": ("ref.png", io.BytesIO(logo_bytes), "image/png"),
        },
        data={"secret_key": secret_key},
    )
    assert detect_res.status_code == 200
    d = detect_res.json()
    assert d["watermark_detected"] is True
    assert d["watermark_type"] == "LOGO"
    assert d["ber"] == 0.0
    assert d["nc"] == pytest.approx(1.0, abs=1e-5)


def test_logo_nc_ber_with_different_reference_logo_shows_difference():
    """LOGO + logo referensi berbeda menghasilkan BER > 0 dan NC < 1."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_a_bytes = _create_logo_bytes(64, 40)

    # Buat logo B dengan pola warna terbalik (negatif)
    arr_b = np.full((40, 64), 255, dtype=np.uint8)
    arr_b[:20, :32] = 0
    arr_b[20:, 32:] = 0
    img_b = Image.fromarray(arr_b, mode="L")
    buf_b = io.BytesIO()
    img_b.save(buf_b, format="PNG")
    logo_b_bytes = buf_b.getvalue()

    secret_key = "NCBERLogoDiffKey"

    embed_res = client.post(
        "/api/embed",
        files={
            "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
            "logo": ("logo.png", io.BytesIO(logo_a_bytes), "image/png"),
        },
        data={"secret_key": secret_key, "watermark_type": "logo"},
    )
    assert embed_res.status_code == 200
    stego_bytes = base64.b64decode(embed_res.json()["watermarked_image"].split(",", 1)[1])

    detect_res = client.post(
        "/api/detect",
        files={
            "image": ("stego.png", io.BytesIO(stego_bytes), "image/png"),
            "original_logo": ("ref_diff.png", io.BytesIO(logo_b_bytes), "image/png"),
        },
        data={"secret_key": secret_key},
    )
    assert detect_res.status_code == 200
    d = detect_res.json()
    assert d["watermark_detected"] is True
    assert d["watermark_type"] == "LOGO"
    assert d["ber"] is not None and d["ber"] > 0.0
    assert d["nc"] is not None and d["nc"] < 1.0


def test_logo_nc_ber_with_string_reference_returns_none():
    """LOGO + string reference (original_watermark) tidak boleh dihitung; kembalikan NC=None, BER=None."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(32, 32)
    secret_key = "NCBERLogoStringIgnore"

    embed_res = client.post(
        "/api/embed",
        files={
            "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
            "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
        },
        data={"secret_key": secret_key, "watermark_type": "logo"},
    )
    assert embed_res.status_code == 200
    stego_bytes = base64.b64decode(embed_res.json()["watermarked_image"].split(",", 1)[1])

    # User menyuplai teks original_watermark padahal watermark adalah LOGO
    detect_res = client.post(
        "/api/detect",
        files={"image": ("stego.png", io.BytesIO(stego_bytes), "image/png")},
        data={"secret_key": secret_key, "original_watermark": "STRING-NOT-APPLICABLE"},
    )
    assert detect_res.status_code == 200
    d = detect_res.json()
    assert d["watermark_detected"] is True
    assert d["watermark_type"] == "LOGO"
    assert d["nc"] is None, "String reference tidak boleh digunakan untuk watermark LOGO"
    assert d["ber"] is None, "String reference tidak boleh digunakan untuk watermark LOGO"


def test_logo_nc_ber_without_reference_returns_none():
    """LOGO tanpa referensi menghasilkan NC=None, BER=None."""
    cover_bytes = _create_image_bytes(128, 128)
    logo_bytes = _create_logo_bytes(32, 32)
    secret_key = "NCBERLogoNoRef"

    embed_res = client.post(
        "/api/embed",
        files={
            "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
            "logo": ("logo.png", io.BytesIO(logo_bytes), "image/png"),
        },
        data={"secret_key": secret_key, "watermark_type": "logo"},
    )
    assert embed_res.status_code == 200
    stego_bytes = base64.b64decode(embed_res.json()["watermarked_image"].split(",", 1)[1])

    detect_res = client.post(
        "/api/detect",
        files={"image": ("stego.png", io.BytesIO(stego_bytes), "image/png")},
        data={"secret_key": secret_key},
    )
    assert detect_res.status_code == 200
    d = detect_res.json()
    assert d["watermark_detected"] is True
    assert d["watermark_type"] == "LOGO"
    assert d["nc"] is None
    assert d["ber"] is None


def test_logo_nc_ber_with_different_dimension_reference_normalizes_to_same_shape():
    """LOGO reference dengan dimensi berbeda (128x80) dinormalisasi ke (64x40) dan dibandingkan sukses."""
    cover_bytes = _create_image_bytes(128, 128)
    # Buat logo embedding berukuran 64x40
    logo_64x40_bytes = _create_logo_bytes(64, 40)

    # Buat logo referensi berukuran lebih besar 128x80 dengan rasio 1.6 yang sama
    arr_128x80 = np.zeros((80, 128), dtype=np.uint8)
    arr_128x80[:40, :64] = 255
    arr_128x80[40:, 64:] = 255
    img_large = Image.fromarray(arr_128x80, mode="L")
    buf_large = io.BytesIO()
    img_large.save(buf_large, format="PNG")
    ref_large_bytes = buf_large.getvalue()

    secret_key = "NCBERResizePreserve"

    embed_res = client.post(
        "/api/embed",
        files={
            "image": ("cover.png", io.BytesIO(cover_bytes), "image/png"),
            "logo": ("logo.png", io.BytesIO(logo_64x40_bytes), "image/png"),
        },
        data={"secret_key": secret_key, "watermark_type": "logo"},
    )
    assert embed_res.status_code == 200
    stego_bytes = base64.b64decode(embed_res.json()["watermarked_image"].split(",", 1)[1])

    # Kirim referensi 128x80 — pipeline normalize_logo() akan me-resize ke 64x40
    detect_res = client.post(
        "/api/detect",
        files={
            "image": ("stego.png", io.BytesIO(stego_bytes), "image/png"),
            "original_logo": ("ref_large.png", io.BytesIO(ref_large_bytes), "image/png"),
        },
        data={"secret_key": secret_key},
    )
    assert detect_res.status_code == 200
    d = detect_res.json()
    assert d["watermark_detected"] is True
    assert d["watermark_type"] == "LOGO"
    assert d["nc"] is not None
    assert d["ber"] is not None
    # Karena polanya sama persis, NC mendekati 1 dan BER mendekati 0
    assert d["nc"] == pytest.approx(1.0, abs=0.05)
    assert d["ber"] == pytest.approx(0.0, abs=0.05)

