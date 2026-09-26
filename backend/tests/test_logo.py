"""Unit test untuk pemrosesan dan representasi biner logo watermark (Stage 3A).

Menguji:
1. Konversi biner (normalisasi, grayscale, dan thresholding).
2. Bit packing dan unpacking (reversibility).
3. Preservasi dimensi non-persegi (aspect ratio).
4. Rekonstruksi citra dari representasi biner.
5. Pembedaan tipe payload (TEXT vs LOGO).
6. Penolakan payload yang rusak, tidak lengkap, atau tidak valid.
7. Helper perhitungan kapasitas dan ukuran data logo.
"""

import io
import math

import numpy as np
from PIL import Image
import pytest

from backend.services.logo import (
    DEFAULT_MAX_LOGO_SIZE,
    DEFAULT_THRESHOLD,
    HEADER_LEN_V3,
    PROTOCOL_VERSION_V3,
    WatermarkType,
    calculate_logo_bit_count,
    calculate_logo_byte_count,
    calculate_logo_packet_size,
    check_logo_capacity,
    normalize_logo,
    pack_binary_logo,
    parse_logo_payload,
    parse_watermark_packet,
    reconstruct_logo,
    serialize_logo_payload,
    serialize_text_payload_v3,
    unpack_binary_logo,
)
from backend.services.watermark import (
    MAGIC_MARKER,
    WatermarkValidationError,
    serialize_payload as serialize_payload_v2,
)


# Test 1 — Binary conversion
def test_logo_binary_conversion_with_known_matrix():
    """Uji konversi citra grayscale matriks spesifik menjadi array biner yang tepat."""
    # Matriks uji sesuai spesifikasi Stage 3A:
    # 0   0   255 255
    # 0   255 255 0
    # 255 255 0   0
    # 255 0   0   255
    sample_matrix = np.array(
        [
            [0, 0, 255, 255],
            [0, 255, 255, 0],
            [255, 255, 0, 0],
            [255, 0, 0, 255],
        ],
        dtype=np.uint8,
    )
    img = Image.fromarray(sample_matrix, mode="L")

    # Threshold default = 128: < 128 -> 0, >= 128 -> 1
    binary_arr = normalize_logo(img, max_size=(64, 64), threshold=128)

    expected_binary = np.array(
        [
            [0, 0, 1, 1],
            [0, 1, 1, 0],
            [1, 1, 0, 0],
            [1, 0, 0, 1],
        ],
        dtype=np.uint8,
    )

    assert binary_arr.shape == (4, 4)
    assert np.array_equal(binary_arr, expected_binary)
    assert np.all((binary_arr == 0) | (binary_arr == 1))


def test_logo_binary_conversion_from_bytes():
    """Uji normalisasi dapat menerima bytes berkas PNG/JPEG langsung."""
    img = Image.new("RGB", (32, 32), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    raw_bytes = buf.getvalue()

    binary_arr = normalize_logo(raw_bytes, max_size=(64, 64), threshold=128)
    assert binary_arr.shape == (32, 32)
    assert np.all(binary_arr == 1)


def test_logo_binary_conversion_handles_alpha_channel():
    """Citra RGBA dengan latar belakang transparan harus ditangani dengan latar putih."""
    rgba = Image.new("RGBA", (10, 10), (0, 0, 0, 0))  # Full transparan
    binary_arr = normalize_logo(rgba, threshold=128)
    # Latar belakang transparan di-composite ke putih -> piksel 255 >= 128 -> bernilai 1
    assert np.all(binary_arr == 1)


# Test 2 — Bit packing
@pytest.mark.parametrize(
    "width,height",
    [
        (64, 64),  # 4096 bit = 512 byte (kelipatan 8)
        (64, 40),  # 2560 bit = 320 byte (kelipatan 8)
        (15, 13),  # 195 bit = 25 byte (bukan kelipatan 8, menguji bit padding)
        (7, 5),    # 35 bit = 5 byte
        (1, 1),    # 1 bit = 1 byte
    ],
)
def test_logo_bit_packing_and_unpacking_roundtrip(width, height):
    """Uji roundtrip: binary pixels -> pack -> unpack menghasilkan data identik."""
    rng = np.random.default_rng(seed=42 + width + height)
    original_pixels = rng.integers(0, 2, size=(height, width), dtype=np.uint8)

    packed_bytes, packed_w, packed_h = pack_binary_logo(original_pixels)

    expected_byte_len = math.ceil((width * height) / 8)
    assert len(packed_bytes) == expected_byte_len
    assert packed_w == width
    assert packed_h == height

    unpacked_pixels = unpack_binary_logo(packed_bytes, width=width, height=height)

    assert unpacked_pixels.shape == (height, width)
    assert np.array_equal(original_pixels, unpacked_pixels)


def test_pack_binary_logo_rejects_invalid_inputs():
    """pack_binary_logo harus menolak array non-2D atau nilai di luar {0, 1}."""
    with pytest.raises(ValueError, match="2 dimensi"):
        pack_binary_logo(np.array([0, 1, 0, 1], dtype=np.uint8))

    with pytest.raises(ValueError, match="0 atau 1"):
        pack_binary_logo(np.array([[0, 2], [1, 0]], dtype=np.uint8))


def test_unpack_binary_logo_rejects_length_mismatch():
    """unpack_binary_logo harus menolak data dengan panjang bytes yang tidak cocok."""
    with pytest.raises(ValueError, match="tidak sesuai dengan dimensi"):
        unpack_binary_logo(b"\x00" * 10, width=16, height=16)  # 16x16 butuh 32 byte


# Test 3 — Dimension preservation
def test_logo_dimension_preservation_non_square():
    """Uji logo non-persegi (misal 64x40) mempertahankan dimensi aslinya."""
    # Buat citra berasio 128x80 (rasio 1.6:1)
    original_img = Image.new("L", (128, 80), color=200)

    # Normalisasi dengan batas (64, 64)
    binary_arr = normalize_logo(original_img, max_size=(64, 64))

    # Dimensi harus menjadi 64 x 40 (tidak dipaksa persegi 64x64)
    h, w = binary_arr.shape
    assert w == 64
    assert h == 40

    # Serialisasi dan deserialisasi
    secret_key = "KunciRahasiaPreservasi2026"
    packet = serialize_logo_payload(binary_arr, secret_key=secret_key)
    parsed = parse_logo_payload(packet, secret_key=secret_key)

    assert parsed["width"] == 64
    assert parsed["height"] == 40
    assert parsed["reconstructed_image"].size == (64, 40)


# Test 4 — Reconstruction
def test_logo_reconstruction_produces_identical_binary_image():
    """Uji roundtrip: original binary logo -> serialize -> deserialize -> reconstruct."""
    # Buat logo berpola catur 16x16
    arr = np.zeros((16, 16), dtype=np.uint8)
    arr[::2, ::2] = 1
    arr[1::2, 1::2] = 1

    secret_key = "KunciReconstruct"
    packet = serialize_logo_payload(arr, secret_key=secret_key)
    parsed = parse_logo_payload(packet, secret_key=secret_key)

    reconstructed_img = parsed["reconstructed_image"]
    assert isinstance(reconstructed_img, Image.Image)
    assert reconstructed_img.mode == "L"
    assert reconstructed_img.size == (16, 16)

    # Piksel 1 menjadi putih (255), piksel 0 menjadi hitam (0)
    recon_arr = np.array(reconstructed_img, dtype=np.uint8)
    recon_binary = (recon_arr >= 128).astype(np.uint8)
    assert np.array_equal(arr, recon_binary)


# Test 5 — Payload type (TEXT vs LOGO)
def test_payload_type_distinction_v2_and_v3():
    """Uji bahwa paket TEXT (V2 dan V3) serta paket LOGO (V3) dapat dibedakan dengan benar."""
    secret_key = "TestTypeSecret"

    # 1. Paket V2 legacy (TEXT)
    v2_packet = serialize_payload_v2("VEILUX-LEGACY-TEXT", secret_key)
    parsed_v2 = parse_watermark_packet(v2_packet, secret_key)
    assert parsed_v2["type"] == WatermarkType.TEXT
    assert parsed_v2["version"] == 2
    assert parsed_v2["text"] == "VEILUX-LEGACY-TEXT"

    # 2. Paket V3 TEXT
    v3_text_packet = serialize_text_payload_v3("VEILUX-V3-TEXT", secret_key)
    parsed_v3_text = parse_watermark_packet(v3_text_packet, secret_key)
    assert parsed_v3_text["type"] == WatermarkType.TEXT
    assert parsed_v3_text["version"] == 3
    assert parsed_v3_text["text"] == "VEILUX-V3-TEXT"

    # 3. Paket V3 LOGO
    test_logo = np.eye(8, dtype=np.uint8)
    logo_packet = serialize_logo_payload(test_logo, secret_key)
    parsed_logo = parse_watermark_packet(logo_packet, secret_key)
    assert parsed_logo["type"] == WatermarkType.LOGO
    assert parsed_logo["version"] == 3
    assert parsed_logo["width"] == 8
    assert parsed_logo["height"] == 8
    assert parsed_logo["text"] is None
    assert np.array_equal(parsed_logo["binary_logo"], test_logo)

    # parse_logo_payload harus menerima LOGO dan menolak TEXT
    logo_only = parse_logo_payload(logo_packet, secret_key)
    assert logo_only["type"] == WatermarkType.LOGO

    with pytest.raises(WatermarkValidationError, match="bukan bertipe LOGO"):
        parse_logo_payload(v3_text_packet, secret_key)


# Test 6 — Invalid payload
def test_invalid_logo_payload_rejection():
    """Uji bahwa paket rusak, termanipulasi, atau tidak lengkap ditolak dengan error yang jelas."""
    secret_key = "KeyValidation"
    test_logo = np.ones((8, 8), dtype=np.uint8)
    valid_packet = bytearray(serialize_logo_payload(test_logo, secret_key))

    # 1. Magic marker rusak
    corrupted_magic = bytearray(valid_packet)
    corrupted_magic[:3] = b"BAD"
    with pytest.raises(WatermarkValidationError, match="Magic marker tidak valid"):
        parse_watermark_packet(bytes(corrupted_magic), secret_key)

    # 2. HMAC salah (kunci salah)
    with pytest.raises(WatermarkValidationError, match="HMAC tag tidak cocok"):
        parse_watermark_packet(bytes(valid_packet), "WrongKey123")

    # 3. Payload termanipulasi (bit flipping pada isi data)
    corrupted_data = bytearray(valid_packet)
    corrupted_data[HEADER_LEN_V3] ^= 0x01
    with pytest.raises(WatermarkValidationError, match="HMAC tag tidak cocok"):
        parse_watermark_packet(bytes(corrupted_data), secret_key)

    # 4. Versi protokol tidak didukung
    corrupted_version = bytearray(valid_packet)
    corrupted_version[3] = 99
    with pytest.raises(WatermarkValidationError, match="Versi protokol watermark tidak didukung"):
        parse_watermark_packet(bytes(corrupted_version), secret_key)

    # 5. Paket terpotong (terlalu pendek)
    with pytest.raises(WatermarkValidationError, match="terlalu pendek"):
        parse_watermark_packet(bytes(valid_packet[:8]), secret_key)

    # 6. Secret key kosong
    with pytest.raises(ValueError, match="Secret key tidak boleh kosong"):
        parse_watermark_packet(bytes(valid_packet), "   ")


# Test 7 — Capacity awareness helpers
def test_capacity_awareness_helpers():
    """Uji perhitungan ukuran bit, byte, dan kapasitas paket logo secara dinamis."""
    # 64 x 64: 4096 bit = 512 byte
    assert calculate_logo_bit_count(64, 64) == 4096
    assert calculate_logo_byte_count(64, 64) == 512

    # 64 x 40: 2560 bit = 320 byte
    assert calculate_logo_bit_count(64, 40) == 2560
    assert calculate_logo_byte_count(64, 40) == 320

    # 15 x 15: 225 bit = 29 byte (ceil(225 / 8))
    assert calculate_logo_bit_count(15, 15) == 225
    assert calculate_logo_byte_count(15, 15) == 29

    # Ukuran paket total V3 (Header 11B + payload 512B + HMAC 16B = 539 byte)
    expected_packet_bytes = HEADER_LEN_V3 + 512 + 16
    assert calculate_logo_packet_size(64, 64) == expected_packet_bytes

    # Uji pemeriksaan kapasitas kanal citra
    needed_bits = expected_packet_bytes * 8
    assert check_logo_capacity(64, 64, available_channels=needed_bits) is True
    assert check_logo_capacity(64, 64, available_channels=needed_bits - 1) is False


def test_capacity_helpers_reject_invalid_dimensions():
    """Helper kapasitas harus menolak dimensi nol atau negatif."""
    with pytest.raises(ValueError, match="positif"):
        calculate_logo_bit_count(0, 50)

    with pytest.raises(ValueError, match="positif"):
        calculate_logo_byte_count(-10, 20)
