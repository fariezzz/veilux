# Veilux - Digital Watermarking & Image Integrity Verification

Veilux adalah aplikasi web forensik citra digital untuk penyisipan tanda keaslian (*digital watermarking*) berbasis **Fragile Least Significant Bit (LSB)** yang dilengkapi verifikasi integritas citra dan lokalisasi manipulasi (*tamper detection & localization*) berbasis blok HMAC-SHA256.

Aplikasi ini mendukung dua tipe watermark (teks dan logo biner) serta modul simulasi serangan citra (*attack simulation*) komprehensif lengkap dengan metrik evaluasi imperseptibilitas dan keandalan (PSNR, MSE, NC, BER), visualisasi grafik SVG, serta utilitas ekspor hasil uji ke format Markdown, CSV, dan Excel (.xlsx).

Proyek ini dikembangkan untuk memenuhi Tugas Proyek Aplikasi Kriptografi (Topik C: Digital Watermarking) pada Mata Kuliah Keamanan Informasi, Program Studi Informatika, Fakultas Teknik, Universitas Siliwangi.

---

## Tim Pengembang (Kelompok)

| Nama Anggota | NPM | Kelas |
|---|---|:---:|
| **Muhammad Fariez Riziq Ilham** (Ketua) | 247006111146 | E |
| **Achmad Adil Arasy Darmawan** | 247006111128 | E |
| **Fadhli Fajrial Habibie** | 247006111142 | E |

- **Dosen Pengampu**: Ir. Alam Rahmatulloh, S.T., M.T., MCE., IPM.
- **Institusi**: Universitas Siliwangi

---

## Fitur Utama

1. **Dual Watermark Payload (Protokol v3)**
   - **Teks**: Hingga 64 karakter string UTF-8.
   - **Logo Biner**: Citra logo kustom dinormalisasi otomatis (mempertahankan rasio aspek, *alpha compositing*, konversi grayscale, dan *thresholding* biner 1-bit per piksel) dengan metadata dimensi spasial ($W \times H$).
2. **Penyisipan LSB Pseudo-Random (PRNG)**
   - Penyebaran bit payload watermark secara seragam menggunakan kunci rahasia (*secret key*) berbasis PRNG deterministik (SHA-256 + Fisher-Yates), mencegah ekstraksi unauthorized.
3. **Lokalisasi Manipulasi Blok (32×32 Piksel)**
   - Pembagian citra menjadi grid blok $32 \times 32$ piksel. Setiap blok diautentikasi dengan tag integritas 64-bit HMAC-SHA256 yang disematkan ke kanal LSB yang di-mask (`& 0xFE`).
   - Menghasilkan visualisasi *Tamper Map* presisi (putih = utuh, merah = rusak) dan metrik *Tamper Ratio*.
   - Tampilan status ganda (*Dual Badges*): status keabsahan payload HMAC dipisahkan secara independen dari status integritas blok citra.
4. **Laboratorium Simulasi Serangan & Benchmark**
   - 8 jenis serangan manipulasi citra terkalibrasi:
     - Kompresi JPEG (Kualitas 90, 70, dan 50)
     - Pemotongan Spasial (*Cropping* 15% sudut kanan bawah)
     - *Resizing* / Resampling interpolasi ganda (downsample 50% lalu upsample)
     - *Gaussian Noise* ($\sigma = 25$, seed deterministik 42)
     - Modifikasi Kecerahan (*Brightness* 1.6×)
     - Modifikasi Kontras (*Contrast* 2.0×)
   - Evaluasi otomatis metrik kualitas dan ketahanan:
     - **PSNR** (*Peak Signal-to-Noise Ratio*) & **MSE** (*Mean Squared Error*)
     - **NC** (*Normalized Correlation* berbasis domain bipolar $\{-1, +1\}$) & **BER** (*Bit Error Rate*)
   - Fitur **Benchmark Seluruh Serangan**: Eksekusi batch otomatis 8 serangan secara sekuensial.
   - **Grafik Metrik SVG Interaktif**: Visualisasi perbandingan metrik (PSNR, MSE, NC, BER, Tamper Ratio) berbasis vektor SVG bebas *context loss* dan dapat diunduh sebagai gambar PNG.
   - **Navigasi Inspeksi Skenario (Pills 1–8)**: Beralih memeriksa citra sebelum, setelah, dan tamper map dari setiap skenario secara instan.
   - **Ekspor Forensik**: Opsi ekspor tabel rekapitulasi ke format **Markdown (.md)**, **CSV (.csv)**, dan **Microsoft Excel (.xlsx)** terformat rapi.
5. **Mode Blind Watermarking (Fitur Pengayaan)**
   - Ekstraksi dan deteksi manipulasi berjalan murni tanpa membutuhkan citra asli (*cover image*). Masukan watermark referensi hanya bersifat opsional untuk pengukuran metrik korelasi NC & BER.
6. **Arsitektur Aman & Tanpa Persistensi (In-Memory)**
   - Seluruh pemrosesan citra, payload, dan secret key berlangsung secara *transient* di memori RAM. Tidak ada penyimpanan berkas citra atau kunci rahasia ke hard disk maupun database (*zero disk footprint*).

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
 - Ekstraksi Teks / Logo     - 8 Jenis Serangan
 - Verifikasi HMAC Global    - Evaluasi PSNR & MSE
 - Verifikasi Blok (32×32)   - Evaluasi NC & BER Bipolar
 - Hasil: Tamper Map         - Benchmark, Grafik & XLSX
```

---

## Struktur Direktori

```text
veilux/
├── backend/
│   ├── __init__.py
│   ├── main.py                     # Entrypoint FastAPI, konfigurasi CORS, & registrasi router
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── embed.py            # Endpoint POST /api/embed
│   │       ├── detect.py           # Endpoint POST /api/detect
│   │       └── attack.py           # Endpoint POST /api/attack & /api/benchmark/export-xlsx
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py               # Konfigurasi sistem (ukuran berkas, MIME, CORS)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── watermark.py            # Mesin inti Fragile LSB, PSNR/MSE, NC/BER, Tamper Map
│   │   ├── logo.py                 # Normalisasi citra logo, bit packing, & protokol v3
│   │   └── export_excel.py         # Generator dokumen spreadsheet openpyxl (.xlsx)
│   └── tests/
│       ├── __init__.py
│       ├── test_health.py          # Uji endpoint /api/health
│       ├── test_watermark.py       # Uji LSB engine, manipulasi blok, & tamper map
│       ├── test_detect.py          # Uji deteksi tamper dan verifikasi secret key
│       ├── test_attack.py          # Uji 8 simulasi serangan & ekspor XLSX
│       ├── test_logo.py            # Uji normalisasi & representasi biner logo
│       └── test_logo_integration.py# Uji integrasi end-to-end watermark logo
├── frontend/
│   ├── index.html                  # Antarmuka web pengguna (Workbench forensik)
│   ├── app.js                      # Logika interaktivitas, kanvas, grafik SVG, & API caller
│   └── style.css                   # Tata letak & styling tema (Mode Terang/Gelap)
├── requirements.txt                # Dependensi pustaka Python backend
└── README.md                       # Dokumentasi resmi proyek
```

---

## Persyaratan Lingkungan

- **Python**: Versi 3.10 atau lebih tinggi (direkomendasikan Python 3.11+)
- **Browser Modern**: Google Chrome, Mozilla Firefox, Microsoft Edge, atau Safari dengan dukungan ES6+ dan SVG DOM.

Dependensi utama Python (tercantum di `requirements.txt`):
- `fastapi` & `uvicorn` (REST API framework & server ASGI)
- `pillow` (Pemrosesan citra digital)
- `numpy` (Operasi matriks dan bitwise presisi tinggi)
- `openpyxl` (Generator dokumen spreadsheet Excel .xlsx)
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

## Panduan Deployment (Cloud)

Arsitektur Veilux dirancang terpisah antara Frontend (*Static Web*) dan Backend (*REST API Python*), sehingga sangat ideal dideploy ke kombinasi **Vercel** (Frontend) dan **Render** (Backend).

### A. Deploy Backend ke Render (Web Service)
1. Buat akun dan masuk ke dasbor [Render.com](https://render.com).
2. Klik **New +** $\to$ **Web Service**, hubungkan ke repositori GitHub proyek Veilux.
3. Konfigurasi parameter Web Service:
   - **Name**: `veilux-backend`
   - **Environment**: `Python`
   - **Region**: `Singapore` atau `Oregon`
   - **Branch**: `main`
   - **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: `Free`
4. Tambahkan *Environment Variables*:
   - `PYTHON_VERSION`: `3.11.9`
   - `CORS_ALLOWED_ORIGINS`: URL domain frontend Vercel Anda (misal: `https://veilux.vercel.app`)
5. Klik **Create Web Service**. Backend akan aktif di URL seperti `https://veilux-z3uf.onrender.com`.

*(Alternatif: Gunakan blueprint otomatis berkas `render.yaml` melalui menu **New +** $\to$ **Blueprint** di Render).*

### B. Deploy Frontend ke Vercel
1. Masuk ke dasbor [Vercel.com](https://vercel.com).
2. Klik **Add New...** $\to$ **Project**, impor repositori GitHub proyek Veilux.
3. Konfigurasi pengaturan proyek:
   - **Framework Preset**: `Other`
   - **Root Directory**: `./` (berkas `vercel.json` akan otomatis merutekan ke folder `frontend`)
4. Klik **Deploy**.
5. Setelah selesai, atur alamat backend API jika berbeda dari URL default Render:
   - Buka console browser di domain Vercel Anda, jalankan:
     ```javascript
     localStorage.setItem('veilux_api_base', 'https://nama-backend-anda.onrender.com/api');
     ```
     Atau ubah default URL `DEFAULT_API_BASE` pada baris 5 `frontend/app.js` menjadi URL layanan Render Anda.

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
  - `image` (*File, Required*): Citra yang akan diverifikasi keasliannya (*Blind Mode*).
  - `secret_key` (*String, Required*): Kunci rahasia PRNG yang digunakan saat proses embed.
  - `original_watermark` (*String, Optional*): Teks referensi untuk perhitungan metrik NC & BER.
  - `original_logo` (*File, Optional*): Berkas logo referensi untuk perhitungan NC & BER.
- **Respons (200 OK)**:
  ```json
  {
    "watermark_detected": true,
    "watermark_type": "TEXT",
    "watermark": "247006111146",
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

### 5. Ekspor Lembar Kerja Excel Benchmark (Export XLSX)
- **Endpoint**: `POST /api/benchmark/export-xlsx`
- **Content-Type**: `application/json`
- **Parameter Body**:
  - `watermark_type` (*String, Optional*): `"TEXT"` atau `"LOGO"`.
  - `results` (*Array of Object, Required*): Seluruh data baris hasil pengujian 8 serangan.
- **Respons (200 OK)**: Aliran biner berkas `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` siap unduh.

---

## Pengujian Otomatis (Automated Testing)

Suite pengujian inti (*Core Test Suite*) mencakup **12 unit & integration tests** yang ringkas, terfokus, dan memvalidasi fungsi-fungsi esensial algoritma:
1. Penyisipan LSB Fragile (Teks & Logo Biner)
2. Pembangkitan posisi pseudo-random deterministik (PRNG)
3. Keamanan autentikasi dan integritas data (HMAC-SHA256)
4. Deteksi dan ekstraksi Blind Mode
5. Lokalisasi manipulasi blok (Tamper Map)
6. Metrik kualitas citra & korelasi (PSNR, MSE, NC, BER)
7. Simulasi serangan citra (JPEG) dan ekspor laporan Excel (.xlsx)

Jalankan pengujian menggunakan pytest:

```bash
pytest
```
*Atau menggunakan pemanggilan modul:*
```bash
python -m pytest
```

---

## Kebijakan Privasi & Keamanan Data

- **In-Memory Execution**: Pemrosesan citra digital, hashing, dan payload watermark diproses murni pada memori dinamis (RAM).
- **Zero Disk Footprint**: Tidak ada berkas sementara (*temporary files*), citra pengguna, ataupun *secret key* yang disimpan ke media penyimpanan permanen.
- **Content Security Policy (CSP)**: Frontend dilengkapi konfigurasi CSP ketat untuk memitigasi serangan Cross-Site Scripting (XSS) dan injeksi data eksternal.
