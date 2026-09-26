"""Entrypoint utama aplikasi FastAPI Veilux."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import attack, detect, embed
from backend.core.config import settings

# Inisialisasi aplikasi FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API untuk Digital Watermarking Citra (Veilux)",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Konfigurasi middleware CORS agar frontend lokal dapat mengakses backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["Health"])
async def health_check():
    """Endpoint pemantauan kesehatan layanan backend."""
    return {"status": "ok", "service": "veilux-backend"}


# Registrasi router API
app.include_router(embed.router, prefix=settings.API_PREFIX, tags=["Watermark"])
app.include_router(detect.router, prefix=settings.API_PREFIX, tags=["Watermark"])
app.include_router(attack.router, prefix=settings.API_PREFIX, tags=["Watermark"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
