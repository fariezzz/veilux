# Veilux - Digital Watermarking & Image Integrity Verification

Veilux adalah aplikasi web forensik citra digital untuk penyisipan tanda keaslian (*digital watermarking*) berbasis **Fragile Least Significant Bit (LSB)** yang dilengkapi verifikasi integritas citra dan lokalisasi manipulasi (*tamper detection & localization*) berbasis blok HMAC-SHA256.

Aplikasi ini mendukung dua tipe watermark (teks dan logo biner) serta modul simulasi serangan citra (*attack simulation*) komprehensif lengkap dengan metrik evaluasi imperseptibilitas dan keandalan (PSNR, MSE, NC, BER).

---

## Fitur Utama

1. **Dual Watermark Payload (Protokol v3)**
   - **Teks**: Hingga 64 karakter string UTF-8.
   - **Logo Biner**: Citra logo kustom dinormalisasi otomatis (mempertahankan rasio aspek, *alpha compositing*, konversi grayscale, dan *thresholding* biner 1-bit per piksel).
2. **Penyisipan LSB Pseudo-Random (PRNG)**
   - Penyebaran bit payload watermark secara seragam menggunakan kunci rahasia (*secret key*) berbasis PRNG deterministik, mencegah ekstraksi unauthorized.
3. **Lokalisasi Manipulasi Blok (32×32 Piksel)**
   - Pembagian citra menjadi grid blok $32 \times 32$ piksel. Setiap blok diautentikasi dengan tag integritas 64-bit HMAC-SHA256 yang disematkan ke kanal LSB.
   - Menghasilkan visualisasi *Tamper Map* presisi untuk mengidentifikasi area spasial yang diubah (*tampered*).
   - Tampilan status ganda (*Dual Badges*): status keabsahan payload HMAC dipisahkan secara independen dari status integritas blok citra.
4. **Laboratorium Simulasi Serangan & Benchmark**
   - 8 jenis serangan manipulasi citra:
     - Kompresi JPEG (Kualitas 90, 70, dan 50)
     - Pemotongan Spasial (*Cropping* 15%)
     - *Resizing* / Resampling interpolasi ganda
     - *Gaussian Noise* ($\sigma = 25$)
     - Modifikasi Kecerahan (*Brightness* 1.6×)
     - Modifikasi Kontras (*Contrast* 2.0×)
   - Evaluasi otomatis metrik kualitas dan ketahanan:
     - **PSNR** (*Peak Signal-to-Noise Ratio*) & **MSE** (*Mean Squared Error*)
     - **NC** (*Normalized Correlation*) & **BER** (*Bit Error Rate*)
   - Fitur **Benchmark Seluruh Serangan**: Eksekusi batch otomatis dengan rekapitulasi tabel dan opsi ekspor hasil ke format **Markdown (.md)** atau **CSV (.csv)**.
5. **Arsitektur Aman & Tanpa Persistensi (In-Memory)**
   - Seluruh pemrosesan citra, payload, dan secret key berlangsung secara *transient* di memori RAM. Tidak ada penyimpanan berkas citra atau kunci rahasia ke hard disk maupun database.

---

## Arsitektur Sistem & Alur Kerja

```text
[Citra Asli] + [Payload: Teks / Logo] + [Secret Key]
                     │
                     ▼
       ┌───────────────────────────┐
       │   Veilux Engine (LSB v3)  │
       │  - Normalisasi Logo       │
       │  - HMAC-SHA256 Packaging  │
       │  - PRNG Shuffling Embed   │
       │  - Block Tagging (32×32)  │
       └─────────────┬─────────────┘
                     │
                     ▼
            [Citra Ber-watermark]
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
[Modul Verifikasi/Detect]   [Modul Simulasi Attack]
 - Ekstraksi Teks / Logo     - JPEG / Crop / Noise / dll
 - Verifikasi HMAC Global    - Evaluasi PSNR & MSE
 - Verifikasi Blok (32×32)   - Evaluasi NC & BER
 - Hasil: Tamper Map         - Benchmark Semua Serangan
```

---

## Struktur Direktori

```text
veilux/
├── backend/
│   ├── __init__.py
│   ├── main.py                     # Entrypoint FastAPI, CORS, & registrasi router
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── embed.py            # Endpoint POST /api/embed
│   │       ├── detect.py           # Endpoint POST /api/detect
│   │       └── attack.py           # Endpoint POST /api/attack
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py               # Konfigurasi sistem (ukuran berkas, MIME, CORS)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── watermark.py            # Mesin inti Fragile LSB, PSNR/MSE, NC/BER, Tamper Map
│   │   └── logo.py                 # Normalisasi citra logo, bit packing, & protokol v3
│   └── tests/
│       ├── __init__.py
│       ├── test_health.py          # Uji endpoint /api/health
│       ├── test_embed.py / ...     # Uji fungsionalitas embed, detect, & attack
│       ├── test_logo.py            # Uji normalisasi & representasi biner logo
│       ├── test_logo_integration.py# Uji integrasi end-to-end watermark logo
│       └── test_watermark.py       # Uji LSB engine, manipulasi blok, & tamper map
├── frontend/
│   ├── index.html                  # Antarmuka web pengguna (Workbench forensik)
│   ├── app.js                      # Logika interaktivitas, kanvas, visualisasi, & API caller
│   └── style.css                   # Tata letak & styling tema (Mode Terang/Gelap)
├── requirements.txt                # Dependensi pustaka Python backend
└── README.md                       # Dokumentasi resmi proyek
```

---

## Persyaratan Lingkungan

- **Python**: Versi 3.10 atau lebih tinggi (direkomendasikan Python 3.11+)
- **Browser Modern**: Google Chrome, Mozilla Firefox, Microsoft Edge, atau Safari dengan dukungan ES6+ dan HTML5 Canvas.

Dependensi utama Python (tercantum di `requirements.txt`):
- `fastapi` & `uvicorn` (REST API framework & server ASGI)
- `pillow` (Pemrosesan citra digital)
- `numpy` (Operasi matriks dan bitwise presisi tinggi)
- `python-multipart` (Penanganan unggahan form berkas multipart)
- `pytest` & `httpx` (Automated testing suite)

---

## Panduan Instalasi & Menjalankan Aplikasi

### 1. Pasang Dependensi Backend

Buka terminal di root direktori proyek `veilux`:

```bash
# Buat virtual environment (disarankan)
python -m venv .venv

# Aktivasi virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat
# Linux / macOS / WSL:
source .venv/bin/activate

# Pasang dependensi pustaka
pip install -r requirements.txt
```

### 2. Jalankan Server Backend

Jalankan perintah berikut untuk mengaktifkan server FastAPI:

```bash
uvicorn backend.main:app --reload --port 8000
```

Server backend aktif di:
- **Base URL API**: `http://localhost:8000/api`
- **Dokumentasi Interaktif (Swagger UI)**: `http://localhost:8000/docs`
- **Dokumentasi Alternatif (ReDoc)**: `http://localhost:8000/redoc`

### 3. Jalankan Antarmuka Pengguna (Frontend)

Antarmuka frontend menggunakan arsitektur Vanilla HTML/CSS/JS tanpa kebutuhan proses build:
- Buka berkas `frontend/index.html` langsung di browser, atau
- Gunakan ekstensi *Live Server* di VS Code, atau
- Jalankan web server lokal sederhana:
  ```bash
  # Dari folder frontend:
  cd frontend
  python -m http.server 5500
  ```
  Kemudian akses `http://localhost:5500` di peramban web.

---

## Dokumentasi API (Endpoints)

### 1. Health Check
- **Endpoint**: `GET /api/health`
- **Deskripsi**: Memeriksa ketersediaan layanan backend.
- **Respons (200 OK)**:
  ```json
  {
    "status": "ok",
    "service": "veilux-backend"
  }
  ```

### 2. Penyisipan Watermark (Embed)
- **Endpoint**: `POST /api/embed`
- **Content-Type**: `multipart/form-data`
- **Parameter**:
  - `image` (*File, Required*): Berkas citra format PNG atau JPEG (maksimal 10 MB).
  - `secret_key` (*String, Required*): Kunci rahasia pembangkit urutan acak PRNG.
  - `watermark_type` (*String, Optional*): `"text"` (default) atau `"logo"`.
  - `watermark` (*String, Opsional jika teks*): String teks watermark (maksimal 64 karakter).
  - `logo` (*File, Opsional jika logo*): Berkas citra logo yang akan disematkan.
- **Respons (200 OK)**:
  ```json
  {
    "original_image": "data:image/png;base64,...",
    "watermarked_image": "data:image/png;base64,...",
    "psnr": 74.85,
    "mse": 0.0021,
    "watermark_type": "text",
    "logo_width": null,
    "logo_height": null,
    "binary_logo_image": null
  }
  ```

### 3. Deteksi & Verifikasi (Detect)
- **Endpoint**: `POST /api/detect`
- **Content-Type**: `multipart/form-data`
- **Parameter**:
  - `image` (*File, Required*): Citra yang akan diverifikasi keasliannya.
  - `secret_key` (*String, Required*): Kunci rahasia PRNG yang digunakan saat proses embed.
  - `original_watermark` (*String, Optional*): Teks referensi untuk perhitungan metrik NC & BER.
  - `original_logo` (*File, Optional*): Berkas logo referensi untuk perhitungan NC & BER.
- **Respons (200 OK)**:
  ```json
  {
    "watermark_detected": true,
    "watermark_type": "TEXT",
    "watermark": "RahasiaNegara",
    "logo_image": null,
    "logo_width": null,
    "logo_height": null,
    "nc": 1.0,
    "ber": 0.0,
    "valid_blocks": 64,
    "total_blocks": 64,
    "tamper_ratio": 0.0,
    "input_image": "data:image/png;base64,...",
    "tamper_map": "data:image/png;base64,..."
  }
  ```

### 4. Simulasi Serangan (Attack)
- **Endpoint**: `POST /api/attack`
- **Content-Type**: `multipart/form-data`
- **Parameter**:
  - `image` (*File, Required*): Citra ber-watermark.
  - `attack_type` (*String, Required*): Salah satu dari `jpeg_90`, `jpeg_70`, `jpeg_50`, `crop`, `resize`, `noise`, `brightness`, `contrast`.
  - `secret_key` (*String, Required*): Kunci rahasia PRNG.
  - `original_watermark` (*String, Optional*): Teks payload asli untuk evaluasi NC/BER.
  - `original_logo` (*File, Optional*): Logo asli untuk evaluasi NC/BER.
- **Respons (200 OK)**: Mengembalikan perbandingan citra sebelum dan sesudah serangan, nilai PSNR/MSE serangan, status deteksi watermark, serta Tamper Map pasca-serangan.

---

## Pengujian Otomatis (Automated Testing)

Suite pengujian mencakup 111 unit & integration tests yang menguji seluruh fungsionalitas algoritma LSB, manipulasi blok, normalisasi logo, ketahanan terhadap serangan, dan penanganan error endpoint.

Jalankan test suite menggunakan pytest:

```bash
pytest
```

---

## Kebijakan Privasi & Keamanan Data

- **In-Memory Execution**: Pemrosesan citra digital, hashing, dan payload watermark diproses murni pada memori dinamis (RAM).
- **Zero Disk Footprint**: Tidak ada berkas sementara (*temporary files*), citra pengguna, ataupun *secret key* yang disimpan ke media penyimpanan permanen.
- **Content Security Policy (CSP)**: Frontend dilengkapi konfigurasi CSP ketat untuk memitigasi serangan Cross-Site Scripting (XSS) dan injeksi data eksternal.
