"""Unit test untuk modul layanan digital watermarking LSB Versi 2 (backend/services/watermark.py).

Semua citra dibuat secara sintetis menggunakan Pillow tanpa dependensi berkas eksternal.
Mencakup verifikasi autentikasi integritas per-blok, Tamper Map, serta metrik NC dan BER.
"""

import io
import math
import numpy as np
from PIL import Image
import pytest

from backend.services.watermark import (
    BLOCK_SIZE,
    BLOCK_TAG_BITS,
    MAGIC_MARKER,
    PROTOCOL_VERSION,
    CapacityExceededError,
    WatermarkValidationError,
    bits_to_bytes,
    bytes_to_bits,
    calculate_mse,
    calculate_psnr,
    detect_watermark,
    embed_watermark,
    extract_watermark,
    generate_positions,
    get_image_blocks,
    parse_payload,
    serialize_payload,
)


# Fixtures
@pytest.fixture
def synthetic_image():
    """Membuat citra sintetis RGB berukuran 128x128 piksel (4x4 = 16 blok 32x32)."""
    width, height = 128, 128
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    xx, yy = np.meshgrid(x, y)
    r = xx
    g = yy
    b = ((xx.astype(int) + yy.astype(int)) // 2).astype(np.uint8)
    rgb_array = np.stack([r, g, b], axis=-1)
    return Image.fromarray(rgb_array, mode="RGB")


@pytest.fixture
def grid_96_image():
    """Membuat citra sintetis 96x96 piksel (tepat 3x3 = 9 blok ukuran 32x32)."""
    arr = np.full((96, 96, 3), 150, dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


@pytest.fixture
def small_image():
    """Membuat citra sintetis sangat kecil 4x4 piksel (48 kanal RGB)."""
    return Image.new("RGB", (4, 4), color=(100, 150, 200))


# 1. test serialisasi & parsing payload (versi 2)
def test_serialize_and_parse_payload_roundtrip():
    """Serialisasi dan parsing payload dengan key yang sama menghasilkan watermark asli."""
    original_watermark = "VEILUX-247006111146-AUTHORITY"
    secret_key = "KunciRahasiaUniversitasSiliwangi2026"

    packet = serialize_payload(original_watermark, secret_key)
    assert isinstance(packet, bytes)
    # Header 6B + len(payload) + 16B HMAC
    assert len(packet) == 6 + len(original_watermark.encode("utf-8")) + 16
    assert packet.startswith(MAGIC_MARKER)
    # Versi protokol harus 2
    assert packet[3] == PROTOCOL_VERSION == 2

    recovered_watermark = parse_payload(packet, secret_key)
    assert recovered_watermark == original_watermark


def test_parse_payload_with_wrong_secret_key_fails():
    """Parsing paket dengan secret_key yang salah harus gagal diverifikasi."""
    original_watermark = "VEILUX-WATERMARK-TEST"
    correct_key = "KunciBenar123"
    wrong_key = "KunciSalah456"

    packet = serialize_payload(original_watermark, correct_key)

    with pytest.raises(WatermarkValidationError, match="HMAC tag tidak cocok atau secret key salah"):
        parse_payload(packet, wrong_key)


def test_parse_payload_rejects_corrupted_magic():
    """Parsing paket yang dimodifikasi magic marker-nya harus ditolak."""
    packet = bytearray(serialize_payload("VEILUX", "mykey"))
    packet[0:3] = b"BAD"

    with pytest.raises(WatermarkValidationError, match="Magic marker tidak valid"):
        parse_payload(bytes(packet), "mykey")


def test_parse_payload_rejects_corrupted_data():
    """Parsing paket yang mengalami manipulasi 1 byte data harus ditolak oleh HMAC."""
    packet = bytearray(serialize_payload("VEILUX-TOP-SECRET", "mykey"))
    packet[8] ^= 0x01

    with pytest.raises(WatermarkValidationError, match="HMAC tag tidak cocok"):
        parse_payload(bytes(packet), "mykey")


def test_parse_payload_rejects_version_mismatch():
    """Parsing paket dengan versi di luar versi 2 harus ditolak."""
    packet = bytearray(serialize_payload("VEILUX", "mykey"))
    packet[3] = 1  # ubah ke versi 1

    with pytest.raises(WatermarkValidationError, match="Versi protokol watermark tidak didukung"):
        parse_payload(bytes(packet), "mykey")


# 2. test bit manipulation (big-endian)
def test_bytes_to_bits_and_bits_to_bytes():
    """Uji roundtrip konversi bytes ke bit dan sebaliknya dalam big-endian order."""
    original_bytes = b"Hello, Veilux!\x00\xff\xaa\x55"
    bits = bytes_to_bits(original_bytes)

    assert len(bits) == len(original_bytes) * 8
    byte_128_bits = bytes_to_bits(b"\x80")
    assert np.array_equal(byte_128_bits, [1, 0, 0, 0, 0, 0, 0, 0])

    reconstructed = bits_to_bytes(bits)
    assert reconstructed == original_bytes


def test_bits_to_bytes_rejects_invalid_input():
    """bits_to_bytes harus menolak input kosong, bukan kelipatan 8, atau non-biner."""
    with pytest.raises(ValueError, match="tidak boleh kosong"):
        bits_to_bytes([])

    with pytest.raises(ValueError, match="harus kelipatan 8"):
        bits_to_bytes([1, 0, 1])

    with pytest.raises(ValueError, match="harus bernilai 0 atau 1"):
        bits_to_bytes([0, 1, 2, 0, 0, 0, 0, 0])


# 3. test posisi deterministik & bebas tabrakan (collision-free)
def test_generate_positions_identical_and_unique_for_same_key():
    """Posisi untuk key yang sama harus identik (deterministik) dan setiap indeks unik."""
    total_channels = 10000
    bit_count = 500
    secret_key = "KunciPengacakKripto2026"

    pos1 = generate_positions(total_channels, bit_count, secret_key)
    pos2 = generate_positions(total_channels, bit_count, secret_key)

    assert np.array_equal(pos1, pos2)
    assert len(set(pos1)) == bit_count
    assert np.all(pos1 >= 0)
    assert np.all(pos1 < total_channels)

    pos_sub = generate_positions(total_channels, 50, secret_key)
    assert np.array_equal(pos_sub, pos1[:50])


def test_generate_positions_different_for_different_keys():
    """Posisi untuk secret_key yang berbeda tidak boleh identik."""
    total_channels = 10000
    bit_count = 500

    pos_a = generate_positions(total_channels, bit_count, "KunciA-Ahmad")
    pos_b = generate_positions(total_channels, bit_count, "KunciB-Budi")

    assert not np.array_equal(pos_a, pos_b)


def test_generate_positions_is_not_sequential():
    """Posisi yang dibangkitkan tidak boleh berurutan secara trivial."""
    total_channels = 1000
    bit_count = 100
    pos = generate_positions(total_channels, bit_count, "NonSequentialKey")

    diffs = np.diff(pos)
    assert not np.all(diffs == 1)


def test_generate_positions_rejects_exceeded_capacity():
    """generate_positions harus menolak permintaan bit_count yang melebihi total_channels."""
    with pytest.raises(CapacityExceededError, match="Kapasitas citra tidak mencukupi"):
        generate_positions(total_channels=100, bit_count=101, secret_key="kunci")


def test_tag_positions_and_payload_positions_do_not_collide(synthetic_image):
    """Posisi block tag dan posisi payload utama dijamin tidak boleh bertabrakan."""
    secret_key = "NoCollisionKey123"
    watermark = "VEILUX-COLLISION-TEST"

    embed_result = embed_watermark(synthetic_image, watermark, secret_key)
    payload_pos = embed_result["positions"]
    tag_pos = embed_result["tag_positions"]

    # Pastikan himpunan indeks saling lepas (disjoint)
    intersection = set(payload_pos).intersection(set(tag_pos))
    assert len(intersection) == 0, "Ditemukan tabrakan indeks antara block tag dan payload!"

    # Pastikan tag_pos sendiri unik
    assert len(tag_pos) == len(set(tag_pos))


# 4. test embed dan extract watermark (versi 2)
def test_embed_and_extract_watermark_with_same_key(synthetic_image):
    """Embed lalu extract dengan key yang sama harus menghasilkan watermark asli."""
    original_watermark = "VEILUX-NPM-247006111146"
    secret_key = "MySecureLSBKey!2026"

    # Embed
    embed_result = embed_watermark(synthetic_image, original_watermark, secret_key)
    stego_image = embed_result["stego_image"]

    assert isinstance(stego_image, Image.Image)
    assert embed_result["payload_bits"] > 0
    assert embed_result["block_tag_bits"] == 16 * 64  # 16 blok * 64 bit = 1024 bit
    assert embed_result["num_blocks"] == 16
    assert embed_result["capacity_bits"] == 128 * 128 * 3

    # Extract
    extracted = extract_watermark(stego_image, secret_key)
    assert extracted == original_watermark


def test_embed_and_extract_through_png_bytes(synthetic_image):
    """Hasil embed harus dapat disimpan ke format PNG (lossless) dan diekstrak utuh."""
    original_watermark = "VEILUX-PNG-LOSSLESS-V2"
    secret_key = "PNGCompatibilityKeyV2"

    embed_result = embed_watermark(synthetic_image, original_watermark, secret_key)
    stego_image = embed_result["stego_image"]

    buffer = io.BytesIO()
    stego_image.save(buffer, format="PNG")
    buffer.seek(0)

    loaded_stego = Image.open(buffer)
    extracted = extract_watermark(loaded_stego, secret_key)
    assert extracted == original_watermark


def test_extract_with_wrong_key_fails(synthetic_image):
    """Ekstraksi dengan kunci salah harus gagal diverifikasi."""
    original_watermark = "VEILUX-SECURE-DATA"
    correct_key = "KeyCorrect999"
    wrong_key = "KeyWrong888"

    embed_result = embed_watermark(synthetic_image, original_watermark, correct_key)
    stego_image = embed_result["stego_image"]

    with pytest.raises(WatermarkValidationError):
        extract_watermark(stego_image, wrong_key)


def test_embed_modifies_only_selected_lsb_channels(synthetic_image):
    """Perubahan hanya terjadi pada bit LSB kanal yang terpilih (tag + payload); kanal lain utuh."""
    watermark = "LSB-BIT-ISOLATION-TEST"
    secret_key = "BitIsolationKey"

    embed_result = embed_watermark(synthetic_image, watermark, secret_key)
    stego_image = embed_result["stego_image"]
    all_modified = np.concatenate([embed_result["positions"], embed_result["tag_positions"]])

    orig_flat = np.array(synthetic_image.convert("RGB"), dtype=np.uint8).flatten()
    stego_flat = np.array(stego_image.convert("RGB"), dtype=np.uint8).flatten()

    # 1. Kanal di luar posisi yang dipilih harus 100% identik
    unmodified_mask = np.ones(orig_flat.size, dtype=bool)
    unmodified_mask[all_modified] = False
    assert np.array_equal(orig_flat[unmodified_mask], stego_flat[unmodified_mask])

    # 2. Pada posisi yang disisipi, hanya bit LSB (bit 0) yang boleh berbeda (nilai & 0xFE tetap identik)
    assert np.array_equal(orig_flat[all_modified] & 0xFE, stego_flat[all_modified] & 0xFE)

    # 3. Selisih absolut pada posisi yang disisipi maksimal 1
    diffs = np.abs(orig_flat[all_modified].astype(int) - stego_flat[all_modified].astype(int))
    assert np.all(diffs <= 1)


def test_embed_rejects_payload_exceeding_capacity(small_image):
    """Pesan yang membutuhkan bit melebihi kapasitas kanal citra wajib ditolak."""
    watermark = "A"
    secret_key = "AnyKey"

    with pytest.raises(CapacityExceededError, match="Kapasitas citra tidak mencukupi"):
        embed_watermark(small_image, watermark, secret_key)


# 5. test detect engine & tamper map localization
def test_detect_watermark_untampered_image_all_white_tamper_map(synthetic_image):
    """Gambar stego utuh menghasilkan watermark terdeteksi dan tamper map seluruhnya putih."""
    secret_key = "IntegrityMasterKey2026"
    watermark = "VEILUX-AUTHENTIC-2026"

    embed_res = embed_watermark(synthetic_image, watermark, secret_key)
    stego_image = embed_res["stego_image"]

    detect_res = detect_watermark(stego_image, secret_key)

    # 1. Watermark terdeteksi dan valid
    assert detect_res["watermark_detected"] is True
    assert detect_res["watermark"] == watermark

    # 2. Seluruh blok valid
    assert detect_res["valid_blocks"] == detect_res["total_blocks"] == 16
    assert detect_res["tamper_ratio"] == 0.0

    # 3. Tamper map seluruhnya putih (255, 255, 255)
    tamper_arr = np.array(detect_res["tamper_map"])
    assert tamper_arr.shape == (128, 128, 3)
    assert np.all(tamper_arr == [255, 255, 255])


def test_detect_watermark_wrong_secret_key(synthetic_image):
    """Secret_key salah menghasilkan watermark_detected=False tanpa melempar error internal."""
    secret_key = "CorrectKey123"
    wrong_key = "WrongKey456"
    watermark = "VEILUX-WRONG-KEY-TEST"

    embed_res = embed_watermark(synthetic_image, watermark, secret_key)
    stego_image = embed_res["stego_image"]

    detect_res = detect_watermark(stego_image, wrong_key)

    # Harus aman tanpa exception
    assert detect_res["watermark_detected"] is False
    assert detect_res["watermark"] is None
    # Blok gagal verifikasi sehingga tamper map memiliki blok merah
    assert detect_res["valid_blocks"] < detect_res["total_blocks"]
    assert detect_res["tamper_ratio"] > 0.0


def test_detect_watermark_single_block_tamper_localization(grid_96_image):
    """Ubah pixel pada satu blok dengan perubahan non-LSB, lalu hanya blok tersebut yang merah."""
    secret_key = "TamperLocalizationKey"
    watermark = "LOCALIZE-ME"

    # grid_96_image: 96x96 -> 3x3 = 9 blok ukuran 32x32
    embed_res = embed_watermark(grid_96_image, watermark, secret_key)
    stego_image = embed_res["stego_image"]

    # Lakukan manipulasi non-LSB pada blok baris 1, kolom 1 (koordinat y: 32..63, x: 32..63)
    tampered_arr = np.array(stego_image)
    # Ubah 10x10 piksel di tengah blok (1, 1) dengan perubahan MSB
    tampered_arr[40:50, 40:50, 0] ^= 0b11110000
    tampered_image = Image.fromarray(tampered_arr, mode="RGB")

    detect_res = detect_watermark(tampered_image, secret_key)

    assert detect_res["total_blocks"] == 9
    assert detect_res["valid_blocks"] == 8
    assert math.isclose(detect_res["tamper_ratio"], 1.0 / 9.0)

    tamper_arr = np.array(detect_res["tamper_map"])

    # Blok yang dimanipulasi: baris 1, kolom 1 (y: 32..64, x: 32..64) WAJIB MERAH (255, 0, 0)
    tampered_block_pixels = tamper_arr[32:64, 32:64, :]
    assert np.all(tampered_block_pixels == [255, 0, 0]), "Blok yang dimodifikasi harus berwarna merah!"

    # Blok lain (misal blok 0,0 pada y: 0..32, x: 0..32) WAJIB PUTIH (255, 255, 255)
    unaffected_block_00 = tamper_arr[0:32, 0:32, :]
    assert np.all(unaffected_block_00 == [255, 255, 255]), "Blok yang tidak disentuh harus tetap putih!"

    unaffected_block_22 = tamper_arr[64:96, 64:96, :]
    assert np.all(unaffected_block_22 == [255, 255, 255])


def test_detect_watermark_reference_watermark_correct_ber_nc(synthetic_image):
    """Watermark referensi yang benar menghasilkan BER 0 dan NC 1."""
    secret_key = "NCBERKey2026"
    watermark = "VEILUX-PERFECT-MATCH"

    embed_res = embed_watermark(synthetic_image, watermark, secret_key)
    stego_image = embed_res["stego_image"]

    detect_res = detect_watermark(stego_image, secret_key, original_watermark=watermark)

    assert detect_res["watermark_detected"] is True
    assert detect_res["ber"] == 0.0
    assert math.isclose(detect_res["nc"], 1.0, rel_tol=1e-5)


def test_detect_watermark_reference_watermark_wrong_ber_nc(synthetic_image):
    """Watermark referensi salah menghasilkan BER > 0 dan NC < 1."""
    secret_key = "NCBERKey2026"
    watermark_real = "VEILUX-AUTHENTIC-DATA"
    watermark_fake = "VEILUX-INCORRECT-DATA"

    embed_res = embed_watermark(synthetic_image, watermark_real, secret_key)
    stego_image = embed_res["stego_image"]

    detect_res = detect_watermark(stego_image, secret_key, original_watermark=watermark_fake)

    assert detect_res["ber"] is not None and detect_res["ber"] > 0.0
    assert detect_res["nc"] is not None and detect_res["nc"] < 1.0


def test_detect_watermark_without_reference_returns_none_for_nc_ber(synthetic_image):
    """Bila original_watermark tidak diberikan, NC dan BER harus bernilai None."""
    secret_key = "NoRefKey"
    watermark = "VEILUX-STANDALONE"

    embed_res = embed_watermark(synthetic_image, watermark, secret_key)
    stego_image = embed_res["stego_image"]

    detect_res = detect_watermark(stego_image, secret_key, original_watermark=None)

    assert detect_res["nc"] is None
    assert detect_res["ber"] is None


# 6. test metrik evaluasi (mse & psnr)
def test_calculate_mse_and_psnr_identical_images(synthetic_image):
    """Jika citra asli dan stego identik, MSE = 0.0 dan PSNR = infinity."""
    mse = calculate_mse(synthetic_image, synthetic_image)
    psnr = calculate_psnr(synthetic_image, synthetic_image)

    assert mse == 0.0
    assert math.isinf(psnr)
    assert psnr > 0


def test_calculate_mse_and_psnr_known_values():
    """Uji keakuratan matematis perhitungan MSE dan PSNR dengan nilai sintetis yang diketahui."""
    orig_arr = np.full((10, 10, 3), 100, dtype=np.uint8)
    stego_arr = orig_arr.copy()

    stego_arr[0, :10, 0] = 101
    stego_arr[1, :10, 1] = 101
    stego_arr[2, :10, 2] = 101

    mse = calculate_mse(orig_arr, stego_arr)
    assert math.isclose(mse, 0.1, rel_tol=1e-6)

    expected_psnr = 10.0 * math.log10((255.0 ** 2) / 0.1)
    psnr = calculate_psnr(orig_arr, stego_arr)
    assert math.isclose(psnr, expected_psnr, rel_tol=1e-5)


def test_calculate_mse_avoids_uint8_overflow():
    """Perhitungan MSE tidak boleh mengalami underflow/overflow uint8 saat selisih negatif."""
    arr1 = np.array([[[10]]], dtype=np.uint8)
    arr2 = np.array([[[20]]], dtype=np.uint8)

    mse = calculate_mse(arr1, arr2)
    assert mse == 100.0


def test_metrics_on_watermarked_image(synthetic_image):
    """Citra yang diberi watermark LSB v2 harus memiliki PSNR tinggi (> 50 dB)."""
    embed_result = embed_watermark(synthetic_image, "Veilux-Benchmark-V2", "TestKey")
    stego_image = embed_result["stego_image"]

    mse = calculate_mse(synthetic_image, stego_image)
    psnr = calculate_psnr(synthetic_image, stego_image)

    assert mse > 0.0
    assert mse < 0.1
    assert psnr > 50.0
