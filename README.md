# Veilux - Digital Watermarking & Integrity Verification

Veilux adalah aplikasi web untuk penyisipan tanda keaslian citra digital menggunakan teknik **Fragile Watermarking berbasis LSB (Least Significant Bit)** dan deteksi manipulasi citra (*tamper localization*).

---

## Arsitektur Sistem

- **Frontend**: Vanilla JavaScript (ES6+), Semantic HTML5, Vanilla CSS Modern (Workbench UI).
- **Backend**: Python 3.10+, FastAPI, Uvicorn, Pydantic.
- **Pengujian**: Pytest, HTTPX TestClient.

---

## Struktur Direktori

```text
veilux/
├── backend/
│   ├── __init__.py
│   ├── main.py                  # Entrypoint aplikasi FastAPI & konfigurasi CORS
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── embed.py         # Route handler POST /api/embed & validasi input
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py            # Konfigurasi sistem (ukuran file, tipe MIME, CORS)
│   ├── services/
│   │   ├── __init__.py
│   │   └── watermark.py         # Engine fragile watermarking LSB v2 & Tamper Map
│   └── tests/
│       ├── __init__.py
│       ├── test_health.py       # Unit test endpoint /api/health dan /api/embed
│       └── test_watermark.py    # Unit test engine watermarking LSB v2, block tag & tamper map
├── frontend/
│   ├── index.html               # Antarmuka web pengguna
│   ├── app.js                   # Logika interaksi frontend dan pemanggilan API
│   └── style.css                # Desain visual workbench
├── requirements.txt             # Dependensi pustaka Python
├── .gitignore                   # Daftar pengabaian berkas Git
└── README.md                    # Dokumentasi proyek
```

---

## Backend

Backend Veilux menyediakan REST API berbasis FastAPI yang berjalan pada `http://localhost:8000`.

### 1. Prasyarat Sistem
- Python 3.10 atau versi yang lebih baru
- Pip (Python Package Manager)

### 2. Instalasi Dependensi
Jalankan perintah berikut di root repositori:

```bash
# Opsional: Buat dan aktifkan virtual environment
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Pasang pustaka yang diperlukan
pip install -r requirements.txt
```

### 3. Menjalankan Backend
Jalankan server pengembangan FastAPI dari root direktori proyek:

```bash
uvicorn backend.main:app --reload --port 8000
```
*Atau menggunakan pemanggilan modul Python:*
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

Backend akan aktif di:
- **API Base**: `http://localhost:8000/api`
- **Interactive Swagger Docs**: `http://localhost:8000/docs`
- **Alternative ReDoc**: `http://localhost:8000/redoc`

### 4. Menjalankan Pengujian (Testing)
Untuk menjalankan seluruh unit test otomatis:

```bash
pytest
```
*Atau menggunakan modul Python:*
```bash
python -m pytest
```

---

## Daftar Endpoint API

### 1. `GET /api/health`
Memeriksa status ketersediaan backend.
- **Respons (200 OK):**
  ```json
  {
    "status": "ok",
    "service": "veilux-backend"
  }
  ```

### 2. `POST /api/embed`
Penyisipan watermark ke dalam bit LSB kanal RGB citra.
- **Content-Type**: `multipart/form-data`
- **Parameter Form:**
  - `image` (*File*): Berkas citra format `image/png` atau `image/jpeg` (maksimal 10 MB).
  - `watermark` (*String*): Teks payload watermark (maksimal 64 karakter, tidak boleh kosong).
  - `secret_key` (*String*): Kunci rahasia pembangkit urutan acak PRNG (tidak boleh kosong).
- **Validasi & Penanganan Error:**
  - Format selain PNG/JPEG ditolak dengan HTTP 400.
  - Berkas rusak atau tidak dapat dibaca Pillow ditolak dengan HTTP 400.
  - Berkas melebihi 10 MB atau kosong ditolak dengan HTTP 400.
  - Watermark kosong atau melebihi 64 karakter ditolak dengan HTTP 400.
  - Secret key kosong ditolak dengan HTTP 400.
  - Kapasitas kanal citra tidak mencukupi ditolak dengan HTTP 422.
- **Respons Sukses (200 OK):**
  ```json
  {
    "original_image": "data:image/png;base64,...",
    "watermarked_image": "data:image/png;base64,...",
    "psnr": 75.12,
    "mse": 0.002
  }
  ```

---

## Kebijakan Keamanan Data
- **Pemrosesan Transient**: Seluruh berkas citra dan kunci rahasia diproses murni di dalam RAM (in-memory) selama siklus *request-response*.
- **Tanpa Persistensi**: Berkas unggahan dan *secret key* tidak pernah disimpan ke hard disk, basis data, file log, maupun repositori kode sumber.
