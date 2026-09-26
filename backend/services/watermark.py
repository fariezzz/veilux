"""
Veilux — Fragile LSB Watermarking Service (Protocol v2)

Implementasi custom LSB 1-bit dengan autentikasi integritas per-blok (HMAC-SHA256)
dan paket payload berstruktur. Seluruh pemrosesan dilakukan in-memory; tidak ada
data yang ditulis ke disk atau log.

Catatan desain LSB masking:
  HMAC setiap blok dihitung dari piksel yang sudah di-mask LSB-nya (& 0xFE) agar
  proses penyisipan block-tag tidak membuat citra "merusak dirinya sendiri". Konsekuensinya,
  perubahan murni pada LSB di kanal non-tag tidak memicu tamper deteksi level blok,
  meskipun verifikasi HMAC paket global tetap akan mendeteksi manipulasi payload.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import random
import struct
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
from PIL import Image

# --- Konstanta protokol ---
MAGIC_MARKER: bytes = b"VLX"
PROTOCOL_VERSION: int = 2
HEADER_LEN: int = 6        # 3B magic + 1B version + 2B payload_length
HMAC_TAG_LEN: int = 16     # 16 byte pertama HMAC-SHA256
MIN_PACKET_LEN: int = HEADER_LEN + HMAC_TAG_LEN
MAX_WATERMARK_CHARS: int = 64

BLOCK_SIZE: int = 32       # blok 32×32 piksel
BLOCK_TAG_BYTES: int = 8
BLOCK_TAG_BITS: int = BLOCK_TAG_BYTES * 8  # 64 bit per blok

DOMAIN_BLOCK_TAG: bytes = b"veilux-block-v2"
DOMAIN_PAYLOAD: bytes = b"veilux-payload-v2"


# --- Exception ---
class WatermarkValidationError(ValueError):
    """Validasi magic, versi, panjang, atau HMAC gagal."""
    pass


class CapacityExceededError(ValueError):
    """Jumlah bit payload melebihi kapasitas kanal citra."""
    pass


# --- Bit manipulation ---
def bytes_to_bits(data: bytes) -> np.ndarray:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Input data harus bertipe bytes atau bytearray.")
    if len(data) == 0:
        raise ValueError("Data bytes tidak boleh kosong.")
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: Union[Sequence[int], np.ndarray]) -> bytes:
    if bits is None or len(bits) == 0:
        raise ValueError("Array bit tidak boleh kosong.")
    if len(bits) % 8 != 0:
        raise ValueError(f"Jumlah bit harus kelipatan 8, tetapi diterima {len(bits)} bit.")
    arr = np.asarray(bits, dtype=np.uint8)
    if not np.all((arr == 0) | (arr == 1)):
        raise ValueError("Setiap elemen bit harus bernilai 0 atau 1.")
    return np.packbits(arr).tobytes()


# --- Serialisasi & parsing paket watermark ---
def serialize_payload(watermark: str, secret_key: str) -> bytes:
    """
    Struktur paket VLX v2:
      [magic 3B][version 1B][payload_len 2B][payload NB][HMAC-SHA256[:16] 16B]
    """
    if not isinstance(watermark, str) or not watermark.strip():
        raise ValueError("Payload watermark tidak boleh kosong.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")
    if len(watermark) > MAX_WATERMARK_CHARS:
        raise ValueError(
            f"Panjang watermark ({len(watermark)}) melebihi batas {MAX_WATERMARK_CHARS} karakter."
        )

    payload_bytes = watermark.encode("utf-8")
    header = MAGIC_MARKER + bytes([PROTOCOL_VERSION]) + struct.pack(">H", len(payload_bytes))
    data_to_auth = header + payload_bytes
    tag = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data_to_auth,
        digestmod=hashlib.sha256,
    ).digest()[:HMAC_TAG_LEN]

    return data_to_auth + tag


def parse_payload(packet: bytes, secret_key: str) -> str:
    """Validasi dan dekode paket VLX v2. Melempar WatermarkValidationError jika gagal."""
    if not isinstance(packet, (bytes, bytearray)) or len(packet) == 0:
        raise ValueError("Paket data biner tidak boleh kosong.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")
    if len(packet) < MIN_PACKET_LEN:
        raise WatermarkValidationError(
            f"Ukuran paket terlalu pendek ({len(packet)} byte, minimum {MIN_PACKET_LEN} byte)."
        )

    if packet[:3] != MAGIC_MARKER:
        raise WatermarkValidationError(
            "Magic marker tidak valid: citra bukan keluaran Veilux atau tidak ber-watermark."
        )

    version = packet[3]
    if version != PROTOCOL_VERSION:
        raise WatermarkValidationError(
            f"Versi protokol watermark tidak didukung: {version} (diharapkan {PROTOCOL_VERSION})."
        )

    payload_length = struct.unpack(">H", packet[4:HEADER_LEN])[0]
    expected_total_len = HEADER_LEN + payload_length + HMAC_TAG_LEN
    if len(packet) != expected_total_len:
        raise WatermarkValidationError(
            f"Panjang paket tidak konsisten: header mencatat {payload_length} byte payload "
            f"(total {expected_total_len} byte), tetapi paket berukuran {len(packet)} byte."
        )

    data_to_auth = packet[: HEADER_LEN + payload_length]
    provided_tag = packet[HEADER_LEN + payload_length :]
    computed_tag = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data_to_auth,
        digestmod=hashlib.sha256,
    ).digest()[:HMAC_TAG_LEN]

    if not hmac.compare_digest(provided_tag, computed_tag):
        raise WatermarkValidationError(
            "Verifikasi integritas gagal: HMAC tag tidak cocok atau secret key salah."
        )

    try:
        return packet[HEADER_LEN : HEADER_LEN + payload_length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WatermarkValidationError("Payload bukan format teks UTF-8 yang valid.") from exc


# --- Pembangkit posisi deterministik ---
def _sample_indices_sparse_fisher_yates(
    population_size: int, k: int, rng: random.Random
) -> np.ndarray:
    """
    Sparse Fisher-Yates: pilih k indeks unik dari [0, population_size-1].
    Mempertahankan properti prefix — k elemen pertama identik untuk seed yang sama
    meskipun k bertambah.
    """
    perm: Dict[int, int] = {}
    positions = np.empty(k, dtype=np.int64)
    for i in range(k):
        j = rng.randint(i, population_size - 1)
        val_j = perm.get(j, j)
        perm[j] = perm.get(i, i)
        positions[i] = val_j
    return positions


def generate_positions(total_channels: int, bit_count: int, secret_key: str) -> np.ndarray:
    """Bangkitkan bit_count indeks kanal unik secara deterministik dari secret_key."""
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

    seed_int = int.from_bytes(hashlib.sha256(secret_key.encode("utf-8")).digest(), "big")
    return _sample_indices_sparse_fisher_yates(total_channels, bit_count, random.Random(seed_int))


# --- Partisi blok & integritas blok ---
def get_image_blocks(width: int, height: int, block_size: int = BLOCK_SIZE) -> List[Dict[str, int]]:
    """Bagi citra menjadi grid blok 32×32 (termasuk blok tepi yang lebih kecil)."""
    blocks = []
    block_idx = 0
    for r in range(math.ceil(height / block_size)):
        y_start, y_end = r * block_size, min((r + 1) * block_size, height)
        for c in range(math.ceil(width / block_size)):
            x_start, x_end = c * block_size, min((c + 1) * block_size, width)
            blocks.append({
                "block_idx": block_idx,
                "y_start": y_start, "y_end": y_end,
                "x_start": x_start, "x_end": x_end,
            })
            block_idx += 1
    return blocks


def get_block_global_channel_indices(
    width: int, y_start: int, y_end: int, x_start: int, x_end: int
) -> np.ndarray:
    """Hitung indeks global 1D kanal RGB untuk semua piksel dalam blok."""
    ys = np.arange(y_start, y_end, dtype=np.int64)
    xs = np.arange(x_start, x_end, dtype=np.int64)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    pixel_starts = ((yy * width + xx) * 3)[:, :, None]
    return (pixel_starts + np.array([0, 1, 2], dtype=np.int64)).flatten()


def compute_block_tag(
    block_pixels: np.ndarray,
    block_idx: int,
    image_width: int,
    image_height: int,
    secret_key: str,
) -> bytes:
    """
    Hitung 8-byte HMAC block tag.
    Piksel di-mask LSB (& 0xFE) sebelum di-HMAC agar penyisipan tag tidak
    memodifikasi nilai yang sedang dihitung (self-modification prevention).
    """
    masked_pixels = (block_pixels & 0xFE).astype(np.uint8)
    msg = (
        DOMAIN_BLOCK_TAG
        + struct.pack(">III", block_idx, image_width, image_height)
        + masked_pixels.tobytes()
    )
    return hmac.new(
        key=secret_key.encode("utf-8"), msg=msg, digestmod=hashlib.sha256
    ).digest()[:BLOCK_TAG_BYTES]


def get_block_tag_positions(
    block_global_indices: np.ndarray, block_idx: int, secret_key: str
) -> np.ndarray:
    """Bangkitkan 64 posisi kanal deterministik dalam blok untuk menyimpan block tag."""
    if len(block_global_indices) < BLOCK_TAG_BITS:
        raise CapacityExceededError(
            f"Kapasitas citra tidak mencukupi: blok {block_idx} hanya memiliki "
            f"{len(block_global_indices)} kanal, tidak mencukupi untuk {BLOCK_TAG_BITS} bit tag."
        )
    seed_material = (
        DOMAIN_BLOCK_TAG
        + struct.pack(">I", block_idx)
        + hashlib.sha256(secret_key.encode("utf-8")).digest()
    )
    seed_int = int.from_bytes(hashlib.sha256(seed_material).digest(), "big")
    local_indices = _sample_indices_sparse_fisher_yates(
        len(block_global_indices), BLOCK_TAG_BITS, random.Random(seed_int)
    )
    return block_global_indices[local_indices]


def get_payload_positions(
    available_channels: np.ndarray, bit_count: int, secret_key: str
) -> np.ndarray:
    """Bangkitkan posisi payload dari kanal yang tersedia (di luar posisi block tag)."""
    if bit_count > len(available_channels):
        raise CapacityExceededError(
            f"Kapasitas tidak mencukupi: payload membutuhkan {bit_count} bit, "
            f"kanal tersedia hanya {len(available_channels)}."
        )
    seed_material = DOMAIN_PAYLOAD + hashlib.sha256(secret_key.encode("utf-8")).digest()
    seed_int = int.from_bytes(hashlib.sha256(seed_material).digest(), "big")
    local_indices = _sample_indices_sparse_fisher_yates(
        len(available_channels), bit_count, random.Random(seed_int)
    )
    return available_channels[local_indices]


# --- Embedding ---
def embed_watermark(
    image: Image.Image,
    watermark: Union[str, bytes],
    secret_key: str,
) -> Dict[str, Any]:
    """
    Sisipkan watermark ke dalam citra menggunakan LSB fragile.
    Mendukung payload teks (str) maupun paket biner terstruktur (bytes).

    Alur: normalisasi RGB → partisi blok → hitung & sisipkan block tag per blok →
    kumpulkan kanal sisa → serialisasi payload → sisipkan payload → rekonstruksi stego.

    Returns dict dengan kunci: stego_image, num_blocks, block_tag_bits,
    payload_bits, capacity_bits, positions, tag_positions.
    """
    if not isinstance(image, Image.Image):
        raise TypeError("Input image harus berupa objek PIL.Image.Image.")

    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    img_array = np.array(rgb_image, dtype=np.uint8)
    flat_channels = img_array.flatten()
    total_channels = flat_channels.size

    blocks = get_image_blocks(width=width, height=height)
    all_tag_positions_list: List[np.ndarray] = []
    block_tags_bits_list: List[np.ndarray] = []

    for blk in blocks:
        b_idx = blk["block_idx"]
        y_start, y_end = blk["y_start"], blk["y_end"]
        x_start, x_end = blk["x_start"], blk["x_end"]

        block_pixels = img_array[y_start:y_end, x_start:x_end, :]
        block_indices = get_block_global_channel_indices(width, y_start, y_end, x_start, x_end)

        tag_bytes = compute_block_tag(block_pixels, b_idx, width, height, secret_key)
        tag_pos = get_block_tag_positions(block_indices, b_idx, secret_key)

        all_tag_positions_list.append(tag_pos)
        block_tags_bits_list.append(bytes_to_bits(tag_bytes))

    all_tag_positions = np.concatenate(all_tag_positions_list) if all_tag_positions_list else np.empty(0, dtype=np.int64)
    all_tag_bits = np.concatenate(block_tags_bits_list) if block_tags_bits_list else np.empty(0, dtype=np.uint8)

    if len(all_tag_positions) > 0:
        flat_channels[all_tag_positions] = (flat_channels[all_tag_positions] & 0xFE) | all_tag_bits

    is_tag_channel = np.zeros(total_channels, dtype=bool)
    if len(all_tag_positions) > 0:
        is_tag_channel[all_tag_positions] = True
    available_channels = np.where(~is_tag_channel)[0]

    if isinstance(watermark, bytes):
        packet_bytes = watermark
    else:
        packet_bytes = serialize_payload(watermark=watermark, secret_key=secret_key)
    payload_bits = bytes_to_bits(packet_bytes)

    payload_positions = get_payload_positions(available_channels, len(payload_bits), secret_key)
    flat_channels[payload_positions] = (flat_channels[payload_positions] & 0xFE) | payload_bits

    stego_image = Image.fromarray(flat_channels.reshape(img_array.shape), mode="RGB")

    return {
        "stego_image": stego_image,
        "num_blocks": len(blocks),
        "block_tag_bits": int(len(all_tag_positions)),
        "payload_bits": int(len(payload_bits)),
        "capacity_bits": int(total_channels),
        "positions": payload_positions,
        "tag_positions": all_tag_positions,
    }


# --- Detection ---
def detect_watermark(
    image: Image.Image,
    secret_key: str,
    original_watermark: Optional[str] = None,
    original_logo: Optional[Union[Image.Image, np.ndarray, bytes]] = None,
) -> Dict[str, Any]:
    """
    Deteksi integritas citra, hasilkan tamper map, dan ekstrak watermark (TEXT atau LOGO).

    Tamper map: putih (255,255,255) = blok valid, merah (255,0,0) = blok rusak.
    NC dan BER dihitung terhadap referensi yang sesuai tipenya:
    - TEXT: dibandingkan dengan original_watermark (string).
    - LOGO: dibandingkan antara normalize_logo(original_logo) vs binary logo hasil ekstraksi.
    Kegagalan deteksi tidak melempar exception — dikembalikan sebagai watermark_detected=False.
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

    blocks = get_image_blocks(width=width, height=height)
    tamper_map_arr = np.zeros((height, width, 3), dtype=np.uint8)
    valid_blocks = 0
    all_tag_positions_list: List[np.ndarray] = []

    for blk in blocks:
        b_idx = blk["block_idx"]
        y_start, y_end = blk["y_start"], blk["y_end"]
        x_start, x_end = blk["x_start"], blk["x_end"]

        block_pixels = img_array[y_start:y_end, x_start:x_end, :]
        block_indices = get_block_global_channel_indices(width, y_start, y_end, x_start, x_end)

        try:
            tag_pos = get_block_tag_positions(block_indices, b_idx, secret_key)
            all_tag_positions_list.append(tag_pos)

            read_tag_bytes = bits_to_bytes(flat_channels[tag_pos] & 1)
            recomputed_tag = compute_block_tag(block_pixels, b_idx, width, height, secret_key)
            is_block_valid = hmac.compare_digest(read_tag_bytes, recomputed_tag)
        except Exception:
            is_block_valid = False

        if is_block_valid:
            valid_blocks += 1
            tamper_map_arr[y_start:y_end, x_start:x_end] = [255, 255, 255]
        else:
            tamper_map_arr[y_start:y_end, x_start:x_end] = [255, 0, 0]

    total_blocks = len(blocks)
    tamper_map_image = Image.fromarray(tamper_map_arr, mode="RGB")
    tamper_ratio = float((total_blocks - valid_blocks) / total_blocks) if total_blocks > 0 else 0.0

    all_tag_positions = (
        np.concatenate(all_tag_positions_list)
        if all_tag_positions_list else np.empty(0, dtype=np.int64)
    )
    is_tag_channel = np.zeros(total_channels, dtype=bool)
    if len(all_tag_positions) > 0:
        is_tag_channel[all_tag_positions] = True
    available_channels = np.where(~is_tag_channel)[0]

    watermark_detected = False
    watermark_type: Optional[str] = None
    extracted_watermark: Optional[str] = None
    extracted_logo: Optional[Image.Image] = None
    logo_width: Optional[int] = None
    logo_height: Optional[int] = None
    binary_logo: Optional[np.ndarray] = None
    is_logo_packet = False
    is_text_packet = False
    ver: Optional[int] = None

    try:
        from backend.services.logo import (
            HEADER_LEN_V3,
            HEADER_STRUCT_V3,
            PROTOCOL_VERSION_V3,
            WatermarkType,
            parse_watermark_packet,
        )

        if len(available_channels) >= 32:
            ver_positions = get_payload_positions(available_channels, 32, secret_key)
            ver_bytes = bits_to_bytes(flat_channels[ver_positions] & 1)

            if ver_bytes[:3] == MAGIC_MARKER:
                ver = ver_bytes[3]
                packet_bytes: Optional[bytes] = None

                if ver == PROTOCOL_VERSION:
                    is_text_packet = True
                    if len(available_channels) >= 48:
                        h_pos = get_payload_positions(available_channels, 48, secret_key)
                        h_bytes = bits_to_bytes(flat_channels[h_pos] & 1)
                        payload_len = struct.unpack(">H", h_bytes[4:6])[0]
                        total_bits = (6 + payload_len + HMAC_TAG_LEN) * 8
                        if total_bits <= len(available_channels):
                            pkt_pos = get_payload_positions(available_channels, total_bits, secret_key)
                            packet_bytes = bits_to_bytes(flat_channels[pkt_pos] & 1)

                elif ver == PROTOCOL_VERSION_V3:
                    header_bits_v3 = HEADER_LEN_V3 * 8
                    if len(available_channels) >= header_bits_v3:
                        h_pos = get_payload_positions(available_channels, header_bits_v3, secret_key)
                        h_bytes = bits_to_bytes(flat_channels[h_pos] & 1)
                        _, _, wm_type_raw, _, _, payload_len = struct.unpack(HEADER_STRUCT_V3, h_bytes[:HEADER_LEN_V3])
                        if wm_type_raw == int(WatermarkType.LOGO):
                            is_logo_packet = True
                        elif wm_type_raw == int(WatermarkType.TEXT):
                            is_text_packet = True

                        total_bits = (HEADER_LEN_V3 + payload_len + HMAC_TAG_LEN) * 8
                        if total_bits <= len(available_channels):
                            pkt_pos = get_payload_positions(available_channels, total_bits, secret_key)
                            packet_bytes = bits_to_bytes(flat_channels[pkt_pos] & 1)

                if packet_bytes is not None:
                    parsed_res = parse_watermark_packet(packet_bytes, secret_key)
                    watermark_detected = True
                    if parsed_res["type"] == WatermarkType.TEXT:
                        watermark_type = "TEXT"
                        extracted_watermark = parsed_res["text"]
                    elif parsed_res["type"] == WatermarkType.LOGO:
                        watermark_type = "LOGO"
                        extracted_watermark = f"[LOGO {parsed_res['width']}x{parsed_res['height']}]"
                        extracted_logo = parsed_res["reconstructed_image"]
                        logo_width = parsed_res["width"]
                        logo_height = parsed_res["height"]
                        binary_logo = parsed_res["binary_logo"]
    except Exception:
        pass

    # 5. Evaluasi Kuantitatif NC dan BER (independen dari validasi HMAC)
    nc: Optional[float] = None
    ber: Optional[float] = None

    has_logo_ref = original_logo is not None
    has_text_ref = bool(
        original_watermark
        and isinstance(original_watermark, str)
        and original_watermark.strip()
    )

    if has_logo_ref and not is_text_packet and watermark_type != "TEXT":
        try:
            from backend.services.logo import normalize_logo

            ref_binary = normalize_logo(original_logo, max_size=(64, 64), threshold=128)
            ref_bits = ref_binary.flatten()
            M = len(ref_bits)
            header_offset = 88  # 11 byte header Protokol V3 untuk logo

            if header_offset + M <= len(available_channels):
                positions = get_payload_positions(available_channels, header_offset + M, secret_key)
                content_positions = positions[header_offset : header_offset + M]
                raw_bits = flat_channels[content_positions] & 1

                ber = float(np.sum(raw_bits != ref_bits) / M)
                u = 2.0 * ref_bits.astype(np.float64) - 1.0
                v = 2.0 * raw_bits.astype(np.float64) - 1.0
                denom = np.sqrt(np.sum(u ** 2) * np.sum(v ** 2))
                nc = float(np.sum(u * v) / denom) if denom > 0 else 0.0
        except Exception:
            nc = None
            ber = None

    elif has_text_ref and not is_logo_packet and watermark_type != "LOGO":
        try:
            assert original_watermark is not None
            ref_bits = bytes_to_bits(original_watermark.strip().encode("utf-8"))
            K = len(ref_bits)

            # Tentukan offset header (V3 text: 88 bit / 11 byte; V2 text: 48 bit / 6 byte)
            from backend.services.logo import PROTOCOL_VERSION_V3

            header_offset = 48
            if is_text_packet and ver == PROTOCOL_VERSION_V3:
                header_offset = 88
            elif len(available_channels) >= 32:
                ver_pos = get_payload_positions(available_channels, 32, secret_key)
                ver_bytes = bits_to_bytes(flat_channels[ver_pos] & 1)
                if ver_bytes[:3] == MAGIC_MARKER and ver_bytes[3] == PROTOCOL_VERSION_V3:
                    header_offset = 88

            if header_offset + K <= len(available_channels):
                positions = get_payload_positions(available_channels, header_offset + K, secret_key)
                content_positions = positions[header_offset : header_offset + K]
                raw_bits = flat_channels[content_positions] & 1

                ber = float(np.sum(raw_bits != ref_bits) / K)
                u = 2.0 * ref_bits.astype(np.float64) - 1.0
                v = 2.0 * raw_bits.astype(np.float64) - 1.0
                denom = np.sqrt(np.sum(u ** 2) * np.sum(v ** 2))
                nc = float(np.sum(u * v) / denom) if denom > 0 else 0.0
        except Exception:
            nc = None
            ber = None

    return {
        "watermark_detected": watermark_detected,
        "watermark_type": watermark_type,
        "watermark": extracted_watermark,
        "logo_image": extracted_logo,
        "logo_width": logo_width,
        "logo_height": logo_height,
        "binary_logo": binary_logo,
        "tamper_map": tamper_map_image,
        "valid_blocks": valid_blocks,
        "total_blocks": total_blocks,
        "tamper_ratio": tamper_ratio,
        "nc": nc,
        "ber": ber,
    }


# --- Extract (dipakai unit test) ---
def extract_watermark(image: Image.Image, secret_key: str) -> str:
    """Shortcut ekstraksi — melempar WatermarkValidationError jika tidak terdeteksi."""
    res = detect_watermark(image=image, secret_key=secret_key)
    if not res["watermark_detected"] or res["watermark"] is None:
        raise WatermarkValidationError(
            "Watermark tidak terdeteksi (secret key salah atau citra termanipulasi)."
        )
    return res["watermark"]


# --- Metrik kualitas citra ---
def calculate_mse(
    original: Union[Image.Image, np.ndarray],
    stego: Union[Image.Image, np.ndarray],
) -> float:
    """MSE antara dua citra. Menggunakan float64 untuk menghindari overflow uint8."""
    arr_orig = np.array(original.convert("RGB"), dtype=np.float64) if isinstance(original, Image.Image) else np.asarray(original, dtype=np.float64)
    arr_stego = np.array(stego.convert("RGB"), dtype=np.float64) if isinstance(stego, Image.Image) else np.asarray(stego, dtype=np.float64)

    if arr_orig.shape != arr_stego.shape:
        raise ValueError(f"Dimensi tidak cocok: {arr_orig.shape} vs {arr_stego.shape}.")

    return float(np.mean((arr_orig - arr_stego) ** 2))


def calculate_psnr(
    original: Union[Image.Image, np.ndarray],
    stego: Union[Image.Image, np.ndarray],
) -> float:
    """PSNR dalam dB. Rumus: 10·log10(255² / MSE). Mengembalikan inf jika MSE = 0."""
    mse = calculate_mse(original, stego)
    if mse == 0.0:
        return float("inf")
    return float(10.0 * math.log10((255.0 ** 2) / mse))
