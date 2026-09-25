"""Layanan Digital Watermarking (Veilux) - Protokol Versi 2.

Modul ini mengimplementasikan logika Fragile Digital Watermarking berbasis Spatial LSB 1-bit
dengan autentikasi integritas per-blok (Block-wise Tamper Map Localization) serta integritas
paket biner berbasis HMAC-SHA256.

PERINGATAN KEAMANAN:
- Seluruh pemrosesan citra, kunci, dan tag dilakukan secara transient di RAM (in-memory).
- Tidak ada data citra, kunci, atau payload yang disimpan ke disk, basis data, maupun log.

KETERBATASAN SISTEM (DOCUMENTED LIMITATIONS):
1. Fragile Design: Sistem ini sengaja dirancang rapuh (fragile) untuk mendeteksi manipulasi
   citra sekunder seperti pemotongan (cropping), penyuntingan (inpainting/cloning), kompresi
   lossy JPEG, resampling/resize, penambahan noise, serta pergeseran kecerahan/kontras.
2. LSB Masking Tolerance: Untuk menghindari self-modification saat penyisipan block-tag,
   HMAC setiap blok dihitung dari nilai piksel yang telah di-mask LSB-nya (nilai & 0xFE).
   Konsekuensinya, perubahan nilai murni pada bit LSB pada kanal yang BUKAN merupakan posisi
   block-tag tidak akan memicu deteksi pada level blok, meskipun manipulasi pada payload
   watermark tetap terdeteksi pada verifikasi paket global.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import random
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from PIL import Image

# ══════════════════════════════════════════════════════════════════
# KONSTANTA PROTOKOL PAKET WATERMARK & INTEGRITAS BLOK
# ══════════════════════════════════════════════════════════════════
MAGIC_MARKER: bytes = b"VLX"
PROTOCOL_VERSION: int = 2
HEADER_LEN: int = 6  # 3 byte magic + 1 byte version + 2 byte payload_length
HMAC_TAG_LEN: int = 16  # 16 byte pertama dari HMAC-SHA256 untuk paket payload
MIN_PACKET_LEN: int = HEADER_LEN + HMAC_TAG_LEN  # 22 byte
MAX_WATERMARK_CHARS: int = 64

# Konfigurasi Autentikasi Blok
BLOCK_SIZE: int = 32  # Ukuran blok 32x32 piksel
BLOCK_TAG_BYTES: int = 8  # 8 byte = 64 bit per blok
BLOCK_TAG_BITS: int = BLOCK_TAG_BYTES * 8  # 64 bit

DOMAIN_BLOCK_TAG: bytes = b"veilux-block-v2"
DOMAIN_PAYLOAD: bytes = b"veilux-payload-v2"


# ══════════════════════════════════════════════════════════════════
# KELAS EKSEPSI
# ══════════════════════════════════════════════════════════════════
class WatermarkValidationError(ValueError):
    """Eksepsi saat validasi magic, versi, panjang, atau HMAC gagal."""

    pass


class CapacityExceededError(ValueError):
    """Eksepsi saat jumlah bit payload melebihi kapasitas kanal citra."""

    pass


# ══════════════════════════════════════════════════════════════════
# 1. BIT MANIPULATION (BIG-ENDIAN)
# ══════════════════════════════════════════════════════════════════
def bytes_to_bits(data: bytes) -> np.ndarray:
    """Mengubah deretan bytes menjadi array bit uint8 dalam urutan big-endian.

    Args:
        data: Data bytes yang akan dipecah menjadi bit.

    Returns:
        np.ndarray: Array 1D uint8 bernilai 0 atau 1 (panjang = len(data) * 8).

    Raises:
        TypeError: Jika input bukan bertipe bytes atau bytearray.
        ValueError: Jika data bytes kosong.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Input data harus bertipe bytes atau bytearray.")
    if len(data) == 0:
        raise ValueError("Data bytes tidak boleh kosong.")

    arr = np.frombuffer(data, dtype=np.uint8)
    return np.unpackbits(arr)


def bits_to_bytes(bits: Union[Sequence[int], np.ndarray]) -> bytes:
    """Mengubah deretan bit (0 atau 1) kembali menjadi bytes (big-endian).

    Args:
        bits: Sequence atau numpy array berisi bit uint8 (0 atau 1).

    Returns:
        bytes: Data byte hasil rekonstruksi.

    Raises:
        ValueError: Jika array bit kosong, panjang bukan kelipatan 8,
                    atau mengandung nilai di luar {0, 1}.
    """
    if bits is None or len(bits) == 0:
        raise ValueError("Array bit tidak boleh kosong.")
    if len(bits) % 8 != 0:
        raise ValueError(
            f"Jumlah bit harus kelipatan 8, tetapi diterima {len(bits)} bit."
        )

    arr = np.asarray(bits, dtype=np.uint8)
    if not np.all((arr == 0) | (arr == 1)):
        raise ValueError("Setiap elemen bit harus bernilai 0 atau 1.")

    return np.packbits(arr).tobytes()


# ══════════════════════════════════════════════════════════════════
# 2. SERIALISASI DAN PARSING PAKET WATERMARK (VERSI 2)
# ══════════════════════════════════════════════════════════════════
def serialize_payload(watermark: str, secret_key: str) -> bytes:
    """Menyusun struktur paket watermark VLX versi 2 dengan header dan tag HMAC.

    Struktur Paket:
    - magic marker     : 3 byte (b"VLX")
    - version          : 1 byte (2)
    - payload_length   : 2 byte unsigned integer (big-endian, network order)
    - payload          : N byte teks watermark berenkode UTF-8
    - integrity tag    : 16 byte pertama HMAC-SHA256(key, header + payload)

    Args:
        watermark: Teks string watermark.
        secret_key: Kunci rahasia untuk HMAC integrity tag.

    Returns:
        bytes: Paket biner terstruktur.

    Raises:
        ValueError: Jika watermark atau secret_key kosong, atau melebihi batas.
    """
    if not isinstance(watermark, str) or not watermark.strip():
        raise ValueError("Payload watermark tidak boleh kosong.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")

    payload_bytes = watermark.encode("utf-8")
    if len(watermark) > MAX_WATERMARK_CHARS:
        raise ValueError(
            f"Panjang watermark ({len(watermark)}) melebihi batas maksimum {MAX_WATERMARK_CHARS} karakter."
        )
    if len(payload_bytes) > 0xFFFF:
        raise ValueError("Ukuran payload melebihi batas 2-byte unsigned short (65535 byte).")

    # Header: Magic (3B) + Version 2 (1B) + Length (2B big-endian)
    header = MAGIC_MARKER + bytes([PROTOCOL_VERSION]) + struct.pack(">H", len(payload_bytes))
    data_to_authenticate = header + payload_bytes

    # Integrity Tag: 16 byte pertama HMAC-SHA256
    tag = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data_to_authenticate,
        digestmod=hashlib.sha256,
    ).digest()[:HMAC_TAG_LEN]

    return data_to_authenticate + tag


def parse_payload(packet: bytes, secret_key: str) -> str:
    """Membongkar dan memvalidasi paket watermark VLX versi 2 dari deretan byte.

    Validasi mencakup:
    1. Panjang minimum paket (>= 22 byte).
    2. Kesesuaian magic marker (b"VLX").
    3. Kesesuaian versi protokol (wajib versi 2).
    4. Kesesuaian ukuran paket dengan panjang payload di header.
    5. Integritas HMAC-SHA256 (constant-time comparison).
    6. Decoding UTF-8 payload.

    Args:
        packet: Deretan bytes paket watermark.
        secret_key: Kunci rahasia untuk memverifikasi HMAC tag.

    Returns:
        str: Teks string watermark yang berhasil diverifikasi.

    Raises:
        WatermarkValidationError: Jika magic, version, length, atau HMAC tidak cocok.
        ValueError: Jika input parameter tidak valid.
    """
    if not isinstance(packet, (bytes, bytearray)) or len(packet) == 0:
        raise ValueError("Paket data biner tidak boleh kosong.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")

    if len(packet) < MIN_PACKET_LEN:
        raise WatermarkValidationError(
            f"Ukuran paket terlalu pendek ({len(packet)} byte, minimum {MIN_PACKET_LEN} byte)."
        )

    # 1. Validasi Magic Marker
    magic = packet[:3]
    if magic != MAGIC_MARKER:
        raise WatermarkValidationError(
            "Magic marker tidak valid: citra bukan keluaran Veilux atau tidak ber-watermark."
        )

    # 2. Validasi Protokol Versi (Harus Versi 2)
    version = packet[3]
    if version != PROTOCOL_VERSION:
        raise WatermarkValidationError(
            f"Versi protokol watermark tidak didukung: {version} (diharapkan {PROTOCOL_VERSION})."
        )

    # 3. Baca Panjang Payload
    payload_length = struct.unpack(">H", packet[4:HEADER_LEN])[0]
    expected_total_len = HEADER_LEN + payload_length + HMAC_TAG_LEN
    if len(packet) != expected_total_len:
        raise WatermarkValidationError(
            f"Panjang paket tidak konsisten: header mencatat {payload_length} byte payload "
            f"(total {expected_total_len} byte), tetapi paket berukuran {len(packet)} byte."
        )

    # 4. Verifikasi HMAC-SHA256 Tag
    data_to_authenticate = packet[: HEADER_LEN + payload_length]
    provided_tag = packet[HEADER_LEN + payload_length :]

    computed_tag = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data_to_authenticate,
        digestmod=hashlib.sha256,
    ).digest()[:HMAC_TAG_LEN]

    if not hmac.compare_digest(provided_tag, computed_tag):
        raise WatermarkValidationError(
            "Verifikasi integritas gagal: HMAC tag tidak cocok atau secret key salah."
        )

    # 5. Decode UTF-8 Payload
    payload_bytes = packet[HEADER_LEN : HEADER_LEN + payload_length]
    try:
        watermark = payload_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WatermarkValidationError("Payload bukan format teks UTF-8 yang valid.") from exc

    return watermark


# ══════════════════════════════════════════════════════════════════
# 3. PEMBANGKIT POSISI PENYISIPAN DETERMINISTIK
# ══════════════════════════════════════════════════════════════════
def _sample_indices_sparse_fisher_yates(
    population_size: int, k: int, rng: random.Random
) -> np.ndarray:
    """Memilih k indeks unik dari rentang [0, population_size - 1] secara efisien.

    Mempertahankan properti prefix: untuk seed yang sama, k elemen pertama
    selalu identik meskipun k bertambah.
    """
    perm: Dict[int, int] = {}
    positions = np.empty(k, dtype=np.int64)
    for i in range(k):
        j = rng.randint(i, population_size - 1)
        val_j = perm.get(j, j)
        perm[j] = perm.get(i, i)
        positions[i] = val_j
    return positions


def generate_positions(
    total_channels: int, bit_count: int, secret_key: str
) -> np.ndarray:
    """Membangkitkan indeks posisi kanal unik secara deterministik dari secret_key.

    Args:
        total_channels: Total kanal RGB datar (lebar * tinggi * 3).
        bit_count: Jumlah posisi unik yang dibutuhkan.
        secret_key: Kunci rahasia pengacak PRNG.

    Returns:
        np.ndarray: Array 1D int64 berisi bit_count indeks unik dalam rentang [0, total_channels - 1].
    """
    if total_channels <= 0:
        raise ValueError("Total kanal harus lebih besar dari 0.")
    if bit_count <= 0:
        raise ValueError("Jumlah bit harus lebih besar dari 0.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")
    if bit_count > total_channels:
        raise CapacityExceededError(
            f"Kapasitas citra tidak mencukupi: payload membutuhkan {bit_count} bit, "
            f"tetapi citra hanya memiliki {total_channels} kanal."
        )

    seed_bytes = hashlib.sha256(secret_key.encode("utf-8")).digest()
    seed_int = int.from_bytes(seed_bytes, byteorder="big")
    rng = random.Random(seed_int)

    return _sample_indices_sparse_fisher_yates(total_channels, bit_count, rng)


# ══════════════════════════════════════════════════════════════════
# 4. PARTISI BLOK DAN INTEGRITAS BLOK (BLOCK-WISE TAMPER AUTH)
# ══════════════════════════════════════════════════════════════════
def get_image_blocks(
    width: int, height: int, block_size: int = BLOCK_SIZE
) -> List[Dict[str, int]]:
    """Membagi dimensi citra menjadi grid blok koordinat (termasuk blok tepi)."""
    num_rows = math.ceil(height / block_size)
    num_cols = math.ceil(width / block_size)
    blocks = []
    block_idx = 0
    for r in range(num_rows):
        y_start = r * block_size
        y_end = min((r + 1) * block_size, height)
        for c in range(num_cols):
            x_start = c * block_size
            x_end = min((c + 1) * block_size, width)
            blocks.append(
                {
                    "block_idx": block_idx,
                    "r": r,
                    "c": c,
                    "y_start": y_start,
                    "y_end": y_end,
                    "x_start": x_start,
                    "x_end": x_end,
                    "h": y_end - y_start,
                    "w": x_end - x_start,
                }
            )
            block_idx += 1
    return blocks


def get_block_global_channel_indices(
    width: int, y_start: int, y_end: int, x_start: int, x_end: int
) -> np.ndarray:
    """Menghitung indeks global 1D kanal RGB yang dimiliki oleh blok tertentu."""
    ys = np.arange(y_start, y_end, dtype=np.int64)
    xs = np.arange(x_start, x_end, dtype=np.int64)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    pixel_starts = ((yy * width + xx) * 3)[:, :, None]
    channels = pixel_starts + np.array([0, 1, 2], dtype=np.int64)
    return channels.flatten()


def compute_block_tag(
    block_pixels: np.ndarray,
    block_idx: int,
    image_width: int,
    image_height: int,
    secret_key: str,
) -> bytes:
    """Menghitung 8-byte HMAC block tag dengan LSB masking (& 0xFE).

    Data yang di-HMAC:
    - DOMAIN_BLOCK_TAG (b"veilux-block-v2")
    - block_idx (4 byte big-endian)
    - image_width (4 byte big-endian)
    - image_height (4 byte big-endian)
    - masked_block_data (nilai piksel kanal dengan LSB = 0)
    """
    masked_pixels = (block_pixels & 0xFE).astype(np.uint8)
    msg = (
        DOMAIN_BLOCK_TAG
        + struct.pack(">III", block_idx, image_width, image_height)
        + masked_pixels.tobytes()
    )
    hmac_digest = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=msg,
        digestmod=hashlib.sha256,
    ).digest()
    return hmac_digest[:BLOCK_TAG_BYTES]


def get_block_tag_positions(
    block_global_indices: np.ndarray,
    block_idx: int,
    secret_key: str,
) -> np.ndarray:
    """Membangkitkan 64 posisi kanal deterministik di dalam blok untuk menyimpan tag."""
    num_channels = len(block_global_indices)
    if num_channels < BLOCK_TAG_BITS:
        raise CapacityExceededError(
            f"Kapasitas citra tidak mencukupi: Blok {block_idx} memiliki {num_channels} kanal, "
            f"tidak mencukupi untuk {BLOCK_TAG_BITS} bit tag."
        )

    seed_material = (
        DOMAIN_BLOCK_TAG
        + struct.pack(">I", block_idx)
        + hashlib.sha256(secret_key.encode("utf-8")).digest()
    )
    seed_int = int.from_bytes(hashlib.sha256(seed_material).digest(), "big")
    rng = random.Random(seed_int)

    local_indices = _sample_indices_sparse_fisher_yates(
        population_size=num_channels,
        k=BLOCK_TAG_BITS,
        rng=rng,
    )
    return block_global_indices[local_indices]


def get_payload_positions(
    available_channels: np.ndarray,
    bit_count: int,
    secret_key: str,
) -> np.ndarray:
    """Membangkitkan posisi payload dari sisa kanal di luar posisi block tag."""
    num_available = len(available_channels)
    if bit_count > num_available:
        raise CapacityExceededError(
            f"Kapasitas citra tidak mencukupi: payload membutuhkan {bit_count} bit, "
            f"tetapi kanal yang tersedia setelah alokasi block tag hanya {num_available} kanal."
        )

    seed_material = (
        DOMAIN_PAYLOAD + hashlib.sha256(secret_key.encode("utf-8")).digest()
    )
    seed_int = int.from_bytes(hashlib.sha256(seed_material).digest(), "big")
    rng = random.Random(seed_int)

    local_indices = _sample_indices_sparse_fisher_yates(
        population_size=num_available,
        k=bit_count,
        rng=rng,
    )
    return available_channels[local_indices]


# ══════════════════════════════════════════════════════════════════
# 5. EMBEDDING LSB FRAGILE DENGAN BLOCK-TAG INTEGRITAS
# ══════════════════════════════════════════════════════════════════
def embed_watermark(
    image: Image.Image, watermark: str, secret_key: str
) -> Dict[str, Any]:
    """Menyisipkan payload watermark VLX v2 dan block tag integritas ke dalam citra.

    Alur proses:
    1. Normalisasi citra ke mode RGB 8-bit.
    2. Bagi citra menjadi blok 32x32 piksel.
    3. Untuk setiap blok, hitung block tag (HMAC atas kanal yang di-mask LSB & 0xFE).
    4. Tentukan 64 posisi kanal per-blok secara deterministik dan sisipkan bit tag.
    5. Kumpulkan sisa kanal di luar posisi block tag sebagai kanal payload.
    6. Serialisasi payload watermark menjadi paket VLX versi 2.
    7. Periksa kapasitas total: jika payload melebihi sisa kanal, tolak dengan CapacityExceededError.
    8. Sisipkan bit payload pada posisi sisa yang dipilih secara deterministik.
    9. Rekonstruksi citra stego sebagai PIL Image.

    Args:
        image: Citra masukan PIL Image.
        watermark: Teks string payload watermark.
        secret_key: Kunci rahasia untuk PRNG dan HMAC.

    Returns:
        dict: Memuat:
            - 'stego_image': PIL.Image.Image (RGB 8-bit)
            - 'num_blocks': int (jumlah blok total)
            - 'block_tag_bits': int (total bit yang dialokasikan untuk tag blok)
            - 'payload_bits': int (jumlah bit payload)
            - 'capacity_bits': int (total kapasitas kanal citra)
            - 'positions': np.ndarray (indeks kanal posisi payload)
            - 'tag_positions': np.ndarray (indeks kanal posisi block tag)
    """
    if not isinstance(image, Image.Image):
        raise TypeError("Input image harus berupa objek PIL.Image.Image.")

    # 1. Normalisasi ke RGB 8-bit
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    img_array = np.array(rgb_image, dtype=np.uint8)
    original_shape = img_array.shape  # (H, W, 3)

    flat_channels = img_array.flatten()
    total_channels = flat_channels.size

    # 2. Partisi Blok
    blocks = get_image_blocks(width=width, height=height, block_size=BLOCK_SIZE)
    total_blocks = len(blocks)

    # 3. Hitung dan tentukan posisi tag untuk setiap blok
    all_tag_positions_list: List[np.ndarray] = []
    block_tags_bits_list: List[np.ndarray] = []

    for blk in blocks:
        b_idx = blk["block_idx"]
        y_start, y_end = blk["y_start"], blk["y_end"]
        x_start, x_end = blk["x_start"], blk["x_end"]

        block_pixels = img_array[y_start:y_end, x_start:x_end, :]
        block_indices = get_block_global_channel_indices(
            width, y_start, y_end, x_start, x_end
        )

        # Hitung tag 8-byte
        tag_bytes = compute_block_tag(
            block_pixels=block_pixels,
            block_idx=b_idx,
            image_width=width,
            image_height=height,
            secret_key=secret_key,
        )
        tag_bits = bytes_to_bits(tag_bytes)

        # Pembangkitan posisi tag di dalam blok
        tag_pos = get_block_tag_positions(block_indices, b_idx, secret_key)
        all_tag_positions_list.append(tag_pos)
        block_tags_bits_list.append(tag_bits)

    all_tag_positions = (
        np.concatenate(all_tag_positions_list)
        if all_tag_positions_list
        else np.empty(0, dtype=np.int64)
    )
    all_tag_bits = (
        np.concatenate(block_tags_bits_list)
        if block_tags_bits_list
        else np.empty(0, dtype=np.uint8)
    )

    # 4. Sisipkan bit tag ke kanal LSB
    if len(all_tag_positions) > 0:
        flat_channels[all_tag_positions] = (
            flat_channels[all_tag_positions] & 0xFE
        ) | all_tag_bits

    # 5. Tentukan kanal yang tersisa untuk payload (100% bebas dari tabrakan dengan tag)
    is_tag_channel = np.zeros(total_channels, dtype=bool)
    if len(all_tag_positions) > 0:
        is_tag_channel[all_tag_positions] = True
    available_channels = np.where(~is_tag_channel)[0]

    # 6. Serialisasi payload watermark VLX v2
    packet_bytes = serialize_payload(watermark=watermark, secret_key=secret_key)
    payload_bits = bytes_to_bits(packet_bytes)
    payload_bits_count = len(payload_bits)

    # 7. Validasi kapasitas & bangkitkan posisi payload
    payload_positions = get_payload_positions(
        available_channels=available_channels,
        bit_count=payload_bits_count,
        secret_key=secret_key,
    )

    # 8. Sisipkan bit payload ke kanal LSB
    flat_channels[payload_positions] = (
        flat_channels[payload_positions] & 0xFE
    ) | payload_bits

    # 9. Rekonstruksi citra stego
    stego_array = flat_channels.reshape(original_shape)
    stego_image = Image.fromarray(stego_array, mode="RGB")

    return {
        "stego_image": stego_image,
        "num_blocks": int(total_blocks),
        "block_tag_bits": int(len(all_tag_positions)),
        "payload_bits": int(payload_bits_count),
        "capacity_bits": int(total_channels),
        "positions": payload_positions,
        "tag_positions": all_tag_positions,
    }


# ══════════════════════════════════════════════════════════════════
# 6. DETECT ENGINE (VERIFIKASI BLOK, TAMPER MAP, NC, & BER)
# ══════════════════════════════════════════════════════════════════
def detect_watermark(
    image: Image.Image,
    secret_key: str,
    original_watermark: Optional[str] = None,
) -> Dict[str, Any]:
    """Mendeteksi integritas citra, membuat Tamper Map, dan mengekstrak watermark.

    Alur proses:
    1. Normalisasi citra ke RGB 8-bit.
    2. Bagi citra menjadi blok 32x32.
    3. Baca kembali block tag dan bandingkan dengan tag yang dihitung ulang dari citra.
    4. Buat tamper map (PIL Image RGB seukuran citra asli):
       - Blok valid: Putih (255, 255, 255)
       - Blok tampered/gagal: Merah (255, 0, 0)
    5. Ekstrak dan validasi paket watermark utama dari kanal di luar block tag.
    6. Jika secret_key salah atau data rusak, kembalikan watermark_detected=False
       tanpa melempar eksepsi internal.
    7. Jika original_watermark diberikan, hitung metrik evaluasi:
       - BER (Bit Error Rate): rasio bit yang berbeda.
       - NC (Normalized Correlation): korelasi ternormalisasi representasi bit {-1, +1}.
       Jika tidak diberikan, NC dan BER bernilai None.

    Args:
        image: Citra uji masukan PIL Image.
        secret_key: Kunci rahasia PRNG dan HMAC.
        original_watermark: Opsional teks watermark asli untuk evaluasi NC/BER.

    Returns:
        dict: Berisi:
            - 'watermark_detected': bool
            - 'watermark': Optional[str]
            - 'tamper_map': PIL.Image.Image (RGB seukuran citra)
            - 'valid_blocks': int
            - 'total_blocks': int
            - 'tamper_ratio': float (proporsi blok yang termanipulasi)
            - 'nc': Optional[float]
            - 'ber': Optional[float]
    """
    if not isinstance(image, Image.Image):
        raise TypeError("Input image harus berupa objek PIL.Image.Image.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")

    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    img_array = np.array(rgb_image, dtype=np.uint8)
    flat_channels = img_array.flatten()
    total_channels = flat_channels.size

    # 1. Partisi grid blok
    blocks = get_image_blocks(width=width, height=height, block_size=BLOCK_SIZE)
    total_blocks = len(blocks)

    tamper_map_arr = np.zeros((height, width, 3), dtype=np.uint8)
    valid_blocks = 0

    all_tag_positions_list: List[np.ndarray] = []

    # 2. Verifikasi Integritas Per Blok
    for blk in blocks:
        b_idx = blk["block_idx"]
        y_start, y_end = blk["y_start"], blk["y_end"]
        x_start, x_end = blk["x_start"], blk["x_end"]

        block_pixels = img_array[y_start:y_end, x_start:x_end, :]
        block_indices = get_block_global_channel_indices(
            width, y_start, y_end, x_start, x_end
        )

        try:
            tag_pos = get_block_tag_positions(block_indices, b_idx, secret_key)
            all_tag_positions_list.append(tag_pos)

            # Baca tag yang tersimpan di LSB
            read_tag_bits = flat_channels[tag_pos] & 1
            read_tag_bytes = bits_to_bytes(read_tag_bits)

            # Hitung ulang tag dari piksel dengan LSB dimask (& 0xFE)
            recomputed_tag = compute_block_tag(
                block_pixels=block_pixels,
                block_idx=b_idx,
                image_width=width,
                image_height=height,
                secret_key=secret_key,
            )

            is_block_valid = hmac.compare_digest(read_tag_bytes, recomputed_tag)
        except Exception:
            is_block_valid = False

        if is_block_valid:
            valid_blocks += 1
            tamper_map_arr[y_start:y_end, x_start:x_end, :] = [255, 255, 255]  # Putih
        else:
            tamper_map_arr[y_start:y_end, x_start:x_end, :] = [255, 0, 0]  # Merah

    tamper_map_image = Image.fromarray(tamper_map_arr, mode="RGB")
    tamper_ratio = (
        float((total_blocks - valid_blocks) / total_blocks) if total_blocks > 0 else 0.0
    )

    # 3. Kumpulkan kanal yang tersedia untuk payload
    all_tag_positions = (
        np.concatenate(all_tag_positions_list)
        if all_tag_positions_list
        else np.empty(0, dtype=np.int64)
    )
    is_tag_channel = np.zeros(total_channels, dtype=bool)
    if len(all_tag_positions) > 0:
        is_tag_channel[all_tag_positions] = True
    available_channels = np.where(~is_tag_channel)[0]

    # 4. Ekstraksi dan Validasi Payload Utama
    watermark_detected = False
    extracted_watermark: Optional[str] = None
    extracted_payload_bits: Optional[np.ndarray] = None

    try:
        header_bits_count = HEADER_LEN * 8  # 48 bit
        if len(available_channels) >= header_bits_count:
            header_positions = get_payload_positions(
                available_channels=available_channels,
                bit_count=header_bits_count,
                secret_key=secret_key,
            )
            header_bits = flat_channels[header_positions] & 1
            header_bytes = bits_to_bytes(header_bits)

            # Validasi Magic & Version 2
            if (
                header_bytes[:3] == MAGIC_MARKER
                and header_bytes[3] == PROTOCOL_VERSION
            ):
                payload_len = struct.unpack(">H", header_bytes[4:HEADER_LEN])[0]
                total_packet_len = HEADER_LEN + payload_len + HMAC_TAG_LEN
                total_packet_bits = total_packet_len * 8

                if total_packet_bits <= len(available_channels):
                    packet_positions = get_payload_positions(
                        available_channels=available_channels,
                        bit_count=total_packet_bits,
                        secret_key=secret_key,
                    )
                    packet_bits = flat_channels[packet_positions] & 1
                    packet_bytes = bits_to_bytes(packet_bits)

                    # Verifikasi HMAC paket & decode UTF-8
                    extracted_watermark = parse_payload(packet_bytes, secret_key)
                    watermark_detected = True
                    extracted_payload_bits = packet_bits
    except Exception:
        watermark_detected = False
        extracted_watermark = None

    # 5. Evaluasi Kuantitatif NC dan BER (Bila original_watermark disediakan)
    nc: Optional[float] = None
    ber: Optional[float] = None

    if original_watermark is not None and isinstance(original_watermark, str):
        try:
            ref_packet_bytes = serialize_payload(
                watermark=original_watermark, secret_key=secret_key
            )
            ref_bits = bytes_to_bits(ref_packet_bytes)
            ref_bit_count = len(ref_bits)

            if len(available_channels) >= ref_bit_count:
                test_positions = get_payload_positions(
                    available_channels=available_channels,
                    bit_count=ref_bit_count,
                    secret_key=secret_key,
                )
                test_bits = flat_channels[test_positions] & 1

                # Hitung BER (Bit Error Rate)
                diff_count = np.sum(test_bits != ref_bits)
                ber = float(diff_count / ref_bit_count)

                # Hitung NC (Normalized Correlation) pada representasi biner {-1, +1}
                u = 2.0 * ref_bits.astype(np.float64) - 1.0
                v = 2.0 * test_bits.astype(np.float64) - 1.0
                denom = np.sqrt(np.sum(u ** 2) * np.sum(v ** 2))
                if denom > 0:
                    nc = float(np.sum(u * v) / denom)
                else:
                    nc = 0.0
        except Exception:
            nc = None
            ber = None

    return {
        "watermark_detected": watermark_detected,
        "watermark": extracted_watermark,
        "tamper_map": tamper_map_image,
        "valid_blocks": valid_blocks,
        "total_blocks": total_blocks,
        "tamper_ratio": tamper_ratio,
        "nc": nc,
        "ber": ber,
    }


# ══════════════════════════════════════════════════════════════════
# 7. EXTRACTION DASAR (BACKWARD COMPATIBILITY & VALIDATION)
# ══════════════════════════════════════════════════════════════════
def extract_watermark(image: Image.Image, secret_key: str) -> str:
    """Mengekstrak dan memverifikasi watermark dari citra stego.

    Jika key salah, citra bukan keluaran Veilux, atau data rusak,
    eksepsi WatermarkValidationError akan dilempar.
    """
    res = detect_watermark(image=image, secret_key=secret_key)
    if not res["watermark_detected"] or res["watermark"] is None:
        raise WatermarkValidationError(
            "Watermark tidak terdeteksi atau citra bukan keluaran Veilux (secret key salah atau citra termanipulasi)."
        )
    return res["watermark"]


# ══════════════════════════════════════════════════════════════════
# 8. METRIK EVALUASI KUALITAS CITRA (MSE & PSNR)
# ══════════════════════════════════════════════════════════════════
def calculate_mse(
    original: Union[Image.Image, np.ndarray],
    stego: Union[Image.Image, np.ndarray],
) -> float:
    """Menghitung Mean Squared Error (MSE) antara citra asli dan citra stego.

    Menggunakan tipe data float64 untuk menghindari masalah underflow/overflow
    pada operasi pengurangan array uint8.
    """
    if isinstance(original, Image.Image):
        arr_orig = np.array(original.convert("RGB"), dtype=np.float64)
    else:
        arr_orig = np.asarray(original, dtype=np.float64)

    if isinstance(stego, Image.Image):
        arr_stego = np.array(stego.convert("RGB"), dtype=np.float64)
    else:
        arr_stego = np.asarray(stego, dtype=np.float64)

    if arr_orig.shape != arr_stego.shape:
        raise ValueError(
            f"Dimensi citra asli {arr_orig.shape} tidak cocok dengan citra stego {arr_stego.shape}."
        )

    diff = arr_orig - arr_stego
    mse = float(np.mean(diff ** 2))
    return mse


def calculate_psnr(
    original: Union[Image.Image, np.ndarray],
    stego: Union[Image.Image, np.ndarray],
) -> float:
    """Menghitung Peak Signal-to-Noise Ratio (PSNR) dalam satuan desibel (dB).

    Rumus: PSNR = 10 * log10(MAX_I^2 / MSE), dengan MAX_I = 255.0 untuk citra 8-bit.
    Jika MSE bernilai 0.0 (kedua citra identik), PSNR mengembalikan infinity (float('inf')).
    """
    mse = calculate_mse(original, stego)
    if mse == 0.0:
        return float("inf")

    max_pixel = 255.0
    psnr = 10.0 * math.log10((max_pixel ** 2) / mse)
    return float(psnr)


# ══════════════════════════════════════════════════════════════════
# COMPATIBILITY PLACEHOLDER
# ══════════════════════════════════════════════════════════════════
def embed_watermark_placeholder(
    image_bytes: bytes, watermark: str, secret_key: str
) -> dict:
    """Placeholder service yang dipertahankan untuk kompatibilitas endpoint HTTP 501."""
    raise NotImplementedError("Algoritma embedding belum diimplementasikan.")
