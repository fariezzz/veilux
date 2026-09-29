"""Unit test inti (Core Test Suite) Veilux.

Suite pengujian ringkas (~15 test) yang mencakup 5 fitur utama:
1. Penyisipan Watermark (Embedding) LSB (Teks & Logo Biner)
2. Penentuan Posisi Pseudo-Random (PRNG Seeding & Fisher-Yates)
3. Keamanan & Integritas Kriptografis (HMAC-SHA256)
4. Deteksi, Ekstraksi Blind Mode, & Lokalisasi Manipulasi (Tamper Map)
5. Metrik Mutu & Simulasi Serangan (MSE, PSNR, NC, BER, Ekspor XLSX)
"""

from __future__ import annotations

import io
import numpy as np
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.watermark import (
    _sample_indices_sparse_fisher_yates,
    bytes_to_bits,
    calculate_mse,
    calculate_psnr,
    compute_block_tag,
    detect_watermark,
    embed_watermark,
    generate_positions,
    get_payload_positions,
    serialize_payload,
)
from backend.services.logo import (
    normalize_logo,
    pack_binary_logo,
    reconstruct_logo,
    serialize_logo_payload,
    serialize_text_payload_v3,
    parse_watermark_packet,
    parse_logo_payload,
)

client = TestClient(app)


# --- Fixtures Sederhana ---
@pytest.fixture
def sample_image() -> Image.Image:
    """Citra sintetis berukuran 96x96 piksel (tepat 3x3 blok ukuran 32x32)."""
    arr = np.zeros((96, 96, 3), dtype=np.uint8)
    arr[:, :, 0] = 120  # Kanal R
    arr[:, :, 1] = 150  # Kanal G
    arr[:, :, 2] = 180  # Kanal B
    return Image.fromarray(arr, mode="RGB")


@pytest.fixture
def sample_stego_png(sample_image) -> bytes:
    """Citra stego berformat PNG bytes."""
    res = embed_watermark(sample_image, watermark="VEILUX-CORE", secret_key="kunci-rahasia")
    buf = io.BytesIO()
    res["stego_image"].save(buf, format="PNG")
    return buf.getvalue()


# ============================================================================
# KELOMPOK 1: PENYISIPAN WATERMARK LSB (EMBEDDING)
# ============================================================================

def test_01_embed_text_watermark_preserves_dimensions_and_high_psnr(sample_image):
    """1. Penyisipan watermark teks menghasilkan citra stego berdimensi identik dengan PSNR tinggi (>70 dB)."""
    watermark = "RahasiaNegara2026"
    secret_key = "kunci-preservasi"
    result = embed_watermark(sample_image, watermark, secret_key)

    stego = result["stego_image"]
    assert stego.size == sample_image.size
    assert stego.mode == "RGB"

    # Evaluasi mutu: imperseptibilitas tinggi (standar literatur > 30 dB, Veilux > 60 dB)
    psnr = calculate_psnr(sample_image, stego)
    mse = calculate_mse(sample_image, stego)
    assert psnr > 60.0  # Sangat imperceptible
    assert mse < 0.1


def test_02_embed_binary_logo_watermark(sample_image):
    """2. Penyisipan watermark logo biner melalui normalisasi, packing bit, dan rekonstruksi dimensi."""
    # Buat logo buatan 16x16
    logo_arr = np.eye(16, dtype=np.uint8)
    packed_bytes, w, h = pack_binary_logo(logo_arr)
    packet = serialize_logo_payload(packed_bytes, secret_key="kunci-logo", width=w, height=h)

    res = embed_watermark(sample_image, watermark=packet, secret_key="kunci-logo")
    assert res["stego_image"].size == sample_image.size

    # Validasi parsing paket logo protokol v3
    parsed = parse_logo_payload(packet, secret_key="kunci-logo")
    assert parsed["width"] == 16
    assert parsed["height"] == 16

    # Validasi pembuatan paket teks v3
    v3_text = serialize_text_payload_v3("TEXT-V3", secret_key="kunci-teks")
    parsed_v3 = parse_watermark_packet(v3_text, secret_key="kunci-teks")
    assert parsed_v3["text"] == "TEXT-V3"


# ============================================================================
# KELOMPOK 2: SECRET KEY & PENENTUAN POSISI DETERMINISTIK (PRNG)
# ============================================================================

def test_03_positions_deterministic_with_same_key():
    """3. Kunci rahasia yang sama menghasilkan urutan posisi bit kanal yang identik deterministik."""
    channels = np.arange(1000)
    pos1 = get_payload_positions(channels, bit_count=32, secret_key="KunciSama")
    pos2 = get_payload_positions(channels, bit_count=32, secret_key="KunciSama")
    np.testing.assert_array_equal(pos1, pos2)

    # Validasi fungsi generate_positions langsung
    gen_pos = generate_positions(total_channels=1000, bit_count=32, secret_key="KunciSama")
    assert len(gen_pos) == 32
    assert len(np.unique(gen_pos)) == 32


def test_04_positions_different_with_different_keys():
    """4. Kunci rahasia yang berbeda menghasilkan posisi sebaran kanal yang berbeda acak."""
    channels = np.arange(1000)
    pos_a = get_payload_positions(channels, bit_count=32, secret_key="KunciA")
    pos_b = get_payload_positions(channels, bit_count=32, secret_key="KunciB")
    assert not np.array_equal(pos_a, pos_b)


# ============================================================================
# KELOMPOK 3: KEAMANAN & INTEGRITAS KRIPTOGRAFIS (HMAC-SHA256)
# ============================================================================

def test_05_hmac_block_tag_deterministic_and_lsb_masked():
    """5. HMAC tag blok 32x32 dihitung di atas piksel LSB-masked (& 0xFE) untuk mencegah self-modification."""
    block_pixels = np.ones((32, 32, 3), dtype=np.uint8) * 100
    tag1 = compute_block_tag(block_pixels, block_idx=0, image_width=96, image_height=96, secret_key="key1")
    
    # Nilai LSB diubah (+1), tag tetap identik karena masking (& 0xFE)
    block_pixels_lsb = block_pixels | 1
    tag2 = compute_block_tag(block_pixels_lsb, block_idx=0, image_width=96, image_height=96, secret_key="key1")
    
    assert len(tag1) == 8  # 64 bit
    assert tag1 == tag2


def test_06_payload_integrity_detects_data_corruption():
    """6. Manipulasi 1 byte pada paket watermark dideteksi oleh HMAC global."""
    packet = bytearray(serialize_payload("PesanAsli", secret_key="KeyAuth"))
    packet[10] ^= 0xFF  # Balikkan bit data

    from backend.services.watermark import parse_payload, WatermarkValidationError
    with pytest.raises(WatermarkValidationError):
        parse_payload(bytes(packet), secret_key="KeyAuth")


# ============================================================================
# KELOMPOK 4: EKSTRAKSI & DETEKSI BLIND MODE (TAMPER LOCALIZATION)
# ============================================================================

def test_07_detect_blind_mode_recovers_watermark_perfectly(sample_image):
    """7. Ekstraksi Blind Mode: Membaca teks watermark murni dari citra stego tanpa membutuhkan citra asli."""
    from backend.services.watermark import extract_watermark

    res = embed_watermark(sample_image, "RAHASIA-BLIND", "kunci123")
    stego = res["stego_image"]

    det = detect_watermark(stego, secret_key="kunci123")
    assert det["watermark_detected"] is True
    assert det["watermark"] == "RAHASIA-BLIND"
    assert det["tamper_ratio"] == 0.0  # Citra 100% utuh

    # Validasi fungsi shortcut extract_watermark
    assert extract_watermark(stego, secret_key="kunci123") == "RAHASIA-BLIND"


def test_08_detect_wrong_key_fails_cleanly(sample_image):
    """8. Ekstraksi dengan kunci salah menolak akses (watermark_detected=False)."""
    res = embed_watermark(sample_image, "RAHASIA", "kunci-benar")
    det = detect_watermark(res["stego_image"], secret_key="kunci-salah")
    assert det["watermark_detected"] is False


def test_09_tamper_localization_marks_modified_blocks_red(sample_image):
    """9. Modifikasi piksel pada area blok tertentu terdeteksi akurat pada Tamper Map (warna merah)."""
    res = embed_watermark(sample_image, "DATA", "key-tamper")
    stego_arr = np.array(res["stego_image"])

    # Modifikasi blok pojok kiri atas (0..32, 0..32)
    stego_arr[5:25, 5:25, :] = 255
    tampered_img = Image.fromarray(stego_arr)

    det = detect_watermark(tampered_img, secret_key="key-tamper")
    assert det["tamper_ratio"] > 0.0
    assert det["valid_blocks"] < det["total_blocks"]

    # Periksa warna piksel tamper map pada blok termanipulasi adalah merah [255, 0, 0]
    tamper_arr = np.array(det["tamper_map"])
    assert np.array_equal(tamper_arr[10, 10], [255, 0, 0])


# ============================================================================
# KELOMPOK 5: EVALUASI METRIK, SERANGAN, & EKSPOR LAPORAN
# ============================================================================

def test_10_metrics_evaluation_nc_and_ber_bipolar(sample_image):
    """10. Perhitungan metrik korelasi NC Bipolar dan rasio kesalahan BER terhadap referensi."""
    res = embed_watermark(sample_image, "REFERENSI", "key-metrik")
    # Jika referensi identik: NC = 1.0, BER = 0.0
    det = detect_watermark(res["stego_image"], secret_key="key-metrik", original_watermark="REFERENSI")
    assert det["nc"] == pytest.approx(1.0, abs=1e-5)
    assert det["ber"] == pytest.approx(0.0, abs=1e-5)


def test_11_attack_endpoint_executes_distortion_and_detects(sample_stego_png):
    """11. Endpoint simulasi serangan (/api/attack) menjalankan distorsi kompresi JPEG dan mengukur degradasi."""
    files = {"image": ("stego.png", io.BytesIO(sample_stego_png), "image/png")}
    data = {
        "secret_key": "kunci-rahasia",
        "attack_type": "jpeg_70",
        "original_watermark": "VEILUX-CORE",
    }
    resp = client.post("/api/attack", files=files, data=data)
    assert resp.status_code == 200
    res = resp.json()
    assert res["psnr"] > 0
    assert res["mse"] > 0
    assert "tamper_map" in res


def test_12_export_benchmark_xlsx_generates_valid_spreadsheet():
    """12. Endpoint ekspor benchmark menghasilkan berkas Microsoft Excel (.xlsx) yang valid."""
    import openpyxl
    payload = {
        "watermark_type": "TEXT",
        "results": [
            {
                "no": 1,
                "name": "JPEG Q90",
                "category": "Lossy Compression",
                "psnr": 38.5,
                "mse": 9.21,
                "nc": 0.985,
                "ber": 0.012,
                "detected": True,
                "validBlocks": "60/64",
                "tamperRatio": "6.2%",
            }
        ],
    }
    resp = client.post("/api/benchmark/export-xlsx", json=payload)
    assert resp.status_code == 200
    assert "spreadsheetml.sheet" in resp.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Hasil Benchmark" in wb.sheetnames
