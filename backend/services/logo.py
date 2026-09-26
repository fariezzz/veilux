"""Layanan pemrosesan dan representasi biner untuk watermark logo (Stage 3A).

Modul ini mengimplementasikan:
1. Normalisasi citra logo (resize ber-aspect-ratio, konversi grayscale, threshold biner).
2. Bit packing / unpacking (1 bit per piksel secara big-endian).
3. Rekonstruksi citra dari representasi biner.
4. Serialisasi dan deserialisasi payload watermark bertipe LOGO & TEXT (Protokol Versi 3).
5. Perhitungan kapasitas dan ukuran data logo.
"""

from __future__ import annotations

from enum import IntEnum
import hashlib
import hmac
import io
import math
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
from PIL import Image

from backend.services.watermark import (
    HMAC_TAG_LEN,
    MAGIC_MARKER,
    CapacityExceededError,
    WatermarkValidationError,
)

# Konfigurasi default binary logo
DEFAULT_MAX_LOGO_SIZE: Tuple[int, int] = (64, 64)
DEFAULT_THRESHOLD: int = 128
MAX_LOGO_DIMENSION: int = 256  # Batas atas dimensi logo yang diperbolehkan

# Protokol Versi 3 (Multi-type: TEXT & LOGO)
PROTOCOL_VERSION_V3: int = 3
HEADER_LEN_V3: int = 11  # 3B magic + 1B version + 1B type + 2B width + 2B height + 2B length
HEADER_STRUCT_V3: str = ">3sBBHHH"
MIN_PACKET_LEN_V3: int = HEADER_LEN_V3 + HMAC_TAG_LEN


class WatermarkType(IntEnum):
    """Tipe watermark yang didukung sistem Veilux."""

    TEXT = 0x01
    LOGO = 0x02


# --- 1. Normalisasi Logo ---
def normalize_logo(
    image: Union[Image.Image, bytes, bytearray],
    max_size: Tuple[int, int] = DEFAULT_MAX_LOGO_SIZE,
    threshold: int = DEFAULT_THRESHOLD,
) -> np.ndarray:
    """Normalisasi citra logo menjadi array biner 2D uint8 (0 atau 1).

    Alur:
    1. Buka berkas / objek citra (jika berupa bytes).
    2. Tangani transparansi (alpha channel) di atas latar putih.
    3. Pertahankan aspect ratio saat melakukan resize (tidak dipaksa persegi).
    4. Konversi ke Grayscale (L).
    5. Thresholding biner: pixel < threshold -> 0, pixel >= threshold -> 1.

    Args:
        image: Objek PIL Image atau bytes berkas citra.
        max_size: Batas maksimum (max_width, max_height). Default (64, 64).
        threshold: Ambang batas biner [0..255]. Default 128.

    Returns:
        np.ndarray: Array 2D uint8 berisi nilai 0 dan 1 dengan bentuk (height, width).

    Raises:
        ValueError: Jika input bukan citra valid atau dimensi tidak valid.
    """
    if isinstance(image, (bytes, bytearray)):
        try:
            pil_img = Image.open(io.BytesIO(image))
            pil_img.load()
        except Exception as exc:
            raise ValueError("Berkas bukan merupakan citra yang valid.") from exc
    elif isinstance(image, Image.Image):
        pil_img = image.copy()
    else:
        raise ValueError("Input logo harus bertipe PIL.Image.Image atau bytes.")

    w, h = pil_img.size
    if w <= 0 or h <= 0:
        raise ValueError(f"Dimensi citra tidak valid: {w}×{h}.")

    max_w, max_h = max_size
    if max_w <= 0 or max_h <= 0:
        raise ValueError(f"Ukuran batas maksimum tidak valid: {max_w}×{max_h}.")

    # Tangani transparansi jika ada (RGBA / LA / mode P dengan transparency)
    if pil_img.mode in ("RGBA", "LA") or (pil_img.mode == "P" and "transparency" in pil_img.info):
        bg = Image.new("RGB", pil_img.size, (255, 255, 255))
        rgba = pil_img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        gray_img = bg.convert("L")
    else:
        gray_img = pil_img.convert("L")

    # Resize dengan mempertahankan aspect ratio hanya jika melebihi batas
    if w > max_w or h > max_h:
        scale = min(max_w / w, max_h / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        gray_img = gray_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    arr = np.array(gray_img, dtype=np.uint8)
    binary_arr = (arr >= threshold).astype(np.uint8)
    return binary_arr


# --- 2. Bit Packing & Unpacking ---
def pack_binary_logo(binary_logo: np.ndarray) -> Tuple[bytes, int, int]:
    """Mengemas array biner 2D menjadi deretan byte ringkas (1 bit per piksel).

    Args:
        binary_logo: Array 2D uint8 bernilai 0 atau 1.

    Returns:
        Tuple[bytes, int, int]: (packed_bytes, width, height).

    Raises:
        ValueError: Jika array bukan 2D, kosong, atau mengandung nilai di luar {0, 1}.
    """
    if not isinstance(binary_logo, np.ndarray):
        raise ValueError("Input binary logo harus berupa numpy.ndarray.")
    if binary_logo.ndim != 2:
        raise ValueError(f"Array binary logo harus 2 dimensi, diterima {binary_logo.ndim} dimensi.")

    height, width = binary_logo.shape
    if width <= 0 or height <= 0:
        raise ValueError(f"Dimensi binary logo tidak valid: {width}×{height}.")
    if not np.all((binary_logo == 0) | (binary_logo == 1)):
        raise ValueError("Seluruh elemen binary logo harus bernilai 0 atau 1.")

    flat = binary_logo.flatten()
    packed_bytes = np.packbits(flat).tobytes()
    return packed_bytes, width, height


def unpack_binary_logo(packed_data: bytes, width: int, height: int) -> np.ndarray:
    """Membongkar bytes terkemas kembali menjadi array biner 2D (height, width).

    Args:
        packed_data: Data byte terkemas.
        width: Lebar citra dalam piksel.
        height: Tinggi citra dalam piksel.

    Returns:
        np.ndarray: Array 2D uint8 bernilai 0 atau 1 dengan bentuk (height, width).

    Raises:
        ValueError: Jika dimensi atau panjang data tidak sesuai.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Dimensi tidak valid: {width}×{height}.")

    expected_bytes = math.ceil((width * height) / 8)
    if len(packed_data) != expected_bytes:
        raise ValueError(
            f"Panjang data biner ({len(packed_data)} byte) tidak sesuai dengan "
            f"dimensi {width}×{height} (diharapkan {expected_bytes} byte)."
        )

    unpacked = np.unpackbits(np.frombuffer(packed_data, dtype=np.uint8))[: width * height]
    return unpacked.reshape((height, width))


# --- 3. Rekonstruksi Citra Logo ---
def reconstruct_logo(
    binary_data: Union[np.ndarray, bytes, bytearray],
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Image.Image:
    """Merekonstruksi objek PIL.Image dari array biner atau bytes terkemas.

    Representasi visual:
    - 0 -> piksel hitam (0)
    - 1 -> piksel putih (255)

    Args:
        binary_data: Array 2D uint8 atau bytes terkemas.
        width: Lebar piksel (wajib jika binary_data berupa bytes).
        height: Tinggi piksel (wajib jika binary_data berupa bytes).

    Returns:
        PIL.Image.Image: Citra grayscale mode 'L'.
    """
    if isinstance(binary_data, (bytes, bytearray)):
        if width is None or height is None:
            raise ValueError("Parameter width dan height wajib disertakan jika input berupa bytes.")
        binary_arr = unpack_binary_logo(bytes(binary_data), width, height)
    elif isinstance(binary_data, np.ndarray):
        if binary_data.ndim != 2:
            raise ValueError("Array binary logo harus berdimensi 2.")
        binary_arr = binary_data
    else:
        raise ValueError("Input binary_data harus berupa numpy.ndarray atau bytes.")

    img_arr = (binary_arr * 255).astype(np.uint8)
    return Image.fromarray(img_arr, mode="L")


# --- 4. Serialisasi & Deserialisasi Payload V3 ---
def serialize_logo_payload(
    logo: Union[Image.Image, np.ndarray, bytes, bytearray],
    secret_key: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    max_size: Tuple[int, int] = DEFAULT_MAX_LOGO_SIZE,
    threshold: int = DEFAULT_THRESHOLD,
) -> bytes:
    """Menyusun struktur paket watermark biner LOGO versi 3 terlindungi HMAC.

    Struktur Paket Protokol Versi 3:
    - magic marker     : 3 byte (b"VLX")
    - version          : 1 byte (3)
    - watermark_type   : 1 byte (0x02 = LOGO)
    - width            : 2 byte unsigned short (big-endian)
    - height           : 2 byte unsigned short (big-endian)
    - payload_length   : 2 byte unsigned short (big-endian)
    - payload          : N byte packed binary pixels
    - integrity tag    : 16 byte pertama HMAC-SHA256(key, header + payload)

    Args:
        logo: Citra PIL Image, array biner 2D, atau bytes biner terkemas.
        secret_key: Kunci rahasia untuk HMAC tag.
        width: Lebar piksel (opsional jika PIL Image atau array).
        height: Tinggi piksel (opsional jika PIL Image atau array).
        max_size: Batas maksimum ukuran logo (default: 64x64).
        threshold: Ambang batas binerisasi (default: 128).

    Returns:
        bytes: Paket biner terstruktur.
    """
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")

    if isinstance(logo, Image.Image):
        bin_arr = normalize_logo(logo, max_size=max_size, threshold=threshold)
        packed_bytes, w, h = pack_binary_logo(bin_arr)
    elif isinstance(logo, np.ndarray):
        packed_bytes, w, h = pack_binary_logo(logo)
    elif isinstance(logo, (bytes, bytearray)):
        if width is None or height is None:
            raise ValueError("Parameter width dan height wajib disertakan jika input berupa bytes.")
        expected_len = math.ceil((width * height) / 8)
        if len(logo) != expected_len:
            raise ValueError(
                f"Panjang bytes ({len(logo)}) tidak cocok untuk logo {width}×{height} "
                f"(diharapkan {expected_len} byte)."
            )
        packed_bytes = bytes(logo)
        w, h = width, height
    else:
        raise ValueError("Input logo harus bertipe PIL.Image, numpy.ndarray, atau bytes.")

    if w > MAX_LOGO_DIMENSION or h > MAX_LOGO_DIMENSION:
        raise ValueError(
            f"Dimensi logo ({w}×{h}) melebihi batas maksimum {MAX_LOGO_DIMENSION}×{MAX_LOGO_DIMENSION} piksel."
        )

    payload_len = len(packed_bytes)
    if payload_len > 0xFFFF:
        raise CapacityExceededError("Ukuran payload logo melebihi batas maksimum 2-byte unsigned short.")

    import struct

    header = struct.pack(
        HEADER_STRUCT_V3,
        MAGIC_MARKER,
        PROTOCOL_VERSION_V3,
        int(WatermarkType.LOGO),
        w,
        h,
        payload_len,
    )
    data_to_auth = header + packed_bytes
    tag = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data_to_auth,
        digestmod=hashlib.sha256,
    ).digest()[:HMAC_TAG_LEN]

    return data_to_auth + tag


def serialize_text_payload_v3(watermark: str, secret_key: str) -> bytes:
    """Menyusun struktur paket watermark teks dengan Protokol Versi 3.

    Struktur Header V3:
    - magic (3B) + version 3 (1B) + type 0x01 (1B) + width 0 (2B) + height 0 (2B) + length (2B)
    """
    if not isinstance(watermark, str) or not watermark.strip():
        raise ValueError("Payload watermark tidak boleh kosong.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")

    import struct

    payload_bytes = watermark.encode("utf-8")
    if len(payload_bytes) > 0xFFFF:
        raise ValueError("Ukuran payload melebihi batas 65535 byte.")

    header = struct.pack(
        HEADER_STRUCT_V3,
        MAGIC_MARKER,
        PROTOCOL_VERSION_V3,
        int(WatermarkType.TEXT),
        0,
        0,
        len(payload_bytes),
    )
    data_to_auth = header + payload_bytes
    tag = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=data_to_auth,
        digestmod=hashlib.sha256,
    ).digest()[:HMAC_TAG_LEN]

    return data_to_auth + tag


def parse_watermark_packet(packet: bytes, secret_key: str) -> Dict[str, Any]:
    """Membongkar dan memvalidasi paket watermark (Mendukung Versi 2 teks & Versi 3 teks/logo).

    Args:
        packet: Deretan byte paket watermark biner.
        secret_key: Kunci rahasia untuk memverifikasi HMAC tag.

    Returns:
        Dict[str, Any] berisi informasi paket yang berhasil divalidasi:
            - 'type': WatermarkType.TEXT atau WatermarkType.LOGO
            - 'version': int (2 atau 3)
            - 'width': int
            - 'height': int
            - 'payload_bytes': bytes
            - 'text': Optional[str] (jika tipe TEXT)
            - 'binary_logo': Optional[np.ndarray] (jika tipe LOGO)
            - 'reconstructed_image': Optional[PIL.Image.Image] (jika tipe LOGO)

    Raises:
        WatermarkValidationError: Jika validasi magic, versi, panjang, atau HMAC gagal.
        ValueError: Jika input parameter tidak valid.
    """
    if not isinstance(packet, (bytes, bytearray)) or len(packet) == 0:
        raise ValueError("Paket data biner tidak boleh kosong.")
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Secret key tidak boleh kosong.")

    # 1. Validasi panjang minimum
    if len(packet) < (6 + HMAC_TAG_LEN):
        raise WatermarkValidationError(
            f"Ukuran paket terlalu pendek ({len(packet)} byte, minimum {6 + HMAC_TAG_LEN} byte)."
        )

    # 2. Validasi Magic Marker
    if packet[:3] != MAGIC_MARKER:
        raise WatermarkValidationError(
            "Magic marker tidak valid: citra bukan keluaran Veilux atau tidak ber-watermark."
        )

    version = packet[3]
    import struct

    # 3. Penanganan Berdasarkan Versi Protokol
    if version == 2:
        # Protokol Versi 2 (Legacy Text: Header 6 byte)
        header_len = 6
        payload_length = struct.unpack(">H", packet[4:header_len])[0]
        expected_total_len = header_len + payload_length + HMAC_TAG_LEN
        if len(packet) != expected_total_len:
            raise WatermarkValidationError(
                f"Panjang paket tidak konsisten: header mencatat {payload_length} byte payload, "
                f"tetapi paket berukuran {len(packet)} byte."
            )

        data_to_auth = packet[: header_len + payload_length]
        provided_tag = packet[header_len + payload_length :]
        computed_tag = hmac.new(
            key=secret_key.encode("utf-8"),
            msg=data_to_auth,
            digestmod=hashlib.sha256,
        ).digest()[:HMAC_TAG_LEN]

        if not hmac.compare_digest(provided_tag, computed_tag):
            raise WatermarkValidationError("Verifikasi integritas gagal: HMAC tag tidak cocok atau secret key salah.")

        payload_bytes = packet[header_len : header_len + payload_length]
        try:
            text = payload_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WatermarkValidationError("Payload bukan format teks UTF-8 yang valid.") from exc

        return {
            "type": WatermarkType.TEXT,
            "version": 2,
            "width": 0,
            "height": 0,
            "payload_bytes": payload_bytes,
            "text": text,
            "binary_logo": None,
            "reconstructed_image": None,
        }

    elif version == PROTOCOL_VERSION_V3:
        # Protokol Versi 3 (Multi-type: Header 11 byte)
        if len(packet) < MIN_PACKET_LEN_V3:
            raise WatermarkValidationError(
                f"Ukuran paket V3 terlalu pendek ({len(packet)} byte, minimum {MIN_PACKET_LEN_V3} byte)."
            )

        magic, ver, wm_type_val, w, h, payload_length = struct.unpack(
            HEADER_STRUCT_V3, packet[:HEADER_LEN_V3]
        )

        try:
            wm_type = WatermarkType(wm_type_val)
        except ValueError as exc:
            raise WatermarkValidationError(f"Tipe watermark tidak dikenal: {wm_type_val}.") from exc

        expected_total_len = HEADER_LEN_V3 + payload_length + HMAC_TAG_LEN
        if len(packet) != expected_total_len:
            raise WatermarkValidationError(
                f"Panjang paket V3 tidak konsisten: header mencatat {payload_length} byte payload "
                f"(total {expected_total_len} byte), tetapi paket berukuran {len(packet)} byte."
            )

        data_to_auth = packet[: HEADER_LEN_V3 + payload_length]
        provided_tag = packet[HEADER_LEN_V3 + payload_length :]
        computed_tag = hmac.new(
            key=secret_key.encode("utf-8"),
            msg=data_to_auth,
            digestmod=hashlib.sha256,
        ).digest()[:HMAC_TAG_LEN]

        if not hmac.compare_digest(provided_tag, computed_tag):
            raise WatermarkValidationError("Verifikasi integritas gagal: HMAC tag tidak cocok atau secret key salah.")

        payload_bytes = packet[HEADER_LEN_V3 : HEADER_LEN_V3 + payload_length]

        if wm_type == WatermarkType.TEXT:
            try:
                text = payload_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WatermarkValidationError("Payload bukan format teks UTF-8 yang valid.") from exc

            return {
                "type": WatermarkType.TEXT,
                "version": 3,
                "width": 0,
                "height": 0,
                "payload_bytes": payload_bytes,
                "text": text,
                "binary_logo": None,
                "reconstructed_image": None,
            }

        elif wm_type == WatermarkType.LOGO:
            if w <= 0 or h <= 0:
                raise WatermarkValidationError(f"Dimensi logo di header tidak valid: {w}×{h}.")

            expected_packed_len = math.ceil((w * h) / 8)
            if payload_length != expected_packed_len:
                raise WatermarkValidationError(
                    f"Panjang payload logo ({payload_length} byte) tidak cocok untuk resolusi {w}×{h} "
                    f"(diharapkan {expected_packed_len} byte)."
                )

            binary_logo = unpack_binary_logo(payload_bytes, width=w, height=h)
            reconstructed = reconstruct_logo(binary_logo)

            return {
                "type": WatermarkType.LOGO,
                "version": 3,
                "width": w,
                "height": h,
                "payload_bytes": payload_bytes,
                "text": None,
                "binary_logo": binary_logo,
                "reconstructed_image": reconstructed,
            }

        raise WatermarkValidationError(f"Tipe watermark tidak didukung: {wm_type}.")

    else:
        raise WatermarkValidationError(
            f"Versi protokol watermark tidak didukung: {version} (diharapkan versi 2 atau 3)."
        )


def parse_logo_payload(packet: bytes, secret_key: str) -> Dict[str, Any]:
    """Membongkar paket watermark khusus tipe LOGO."""
    res = parse_watermark_packet(packet, secret_key)
    if res["type"] != WatermarkType.LOGO:
        raise WatermarkValidationError(f"Paket bukan bertipe LOGO, melainkan {res['type'].name}.")
    return res


# --- 5. Capacity Helpers ---
def calculate_logo_bit_count(width: int, height: int) -> int:
    """Menghitung total bit piksel binary logo (width * height)."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Dimensi logo harus positif, diterima {width}×{height}.")
    return width * height


def calculate_logo_byte_count(width: int, height: int) -> int:
    """Menghitung jumlah byte yang dibutuhkan untuk menyimpan binary logo yang di-pack."""
    return math.ceil(calculate_logo_bit_count(width, height) / 8)


def calculate_logo_packet_size(width: int, height: int) -> int:
    """Menghitung total ukuran paket biner (header V3 + payload + HMAC tag) dalam byte."""
    payload_bytes = calculate_logo_byte_count(width, height)
    return HEADER_LEN_V3 + payload_bytes + HMAC_TAG_LEN


def check_logo_capacity(width: int, height: int, available_channels: int) -> bool:
    """Memeriksa apakah kanal citra yang tersedia mencukupi untuk menampung paket logo."""
    total_bits = calculate_logo_packet_size(width, height) * 8
    return available_channels >= total_bits
