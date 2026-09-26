/* Logika aplikasi frontend Veilux (JavaScript murni tanpa framework) */

const API_BASE = 'http://localhost:8000/api';

// Status data aplikasi
const state = {
  embed: { file: null, watermarkType: 'text' },
  detect: { file: null, refType: 'text' },
  attack: { file: null, selectedAttack: null, refType: 'text' },
  logo: { file: null },
  'ref-logo-detect': { file: null },
  'ref-logo-attack': { file: null },
};

// Pengaturan tema tampilan (mode gelap dan terang)
const THEME_STORAGE_KEY = 'veilux_theme';

function getPreferredTheme() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') {
      return stored;
    }
  } catch (e) {}

  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

function updateThemeUI(theme) {
  const isDark = theme === 'dark';
  const optLight = document.getElementById('theme-opt-light');
  const optDark = document.getElementById('theme-opt-dark');

  if (optLight) {
    optLight.classList.toggle('theme-switcher-option-active', !isDark);
    optLight.setAttribute('aria-pressed', isDark ? 'false' : 'true');
  }
  if (optDark) {
    optDark.classList.toggle('theme-switcher-option-active', isDark);
    optDark.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  }
}

function applyTheme(theme, save = true) {
  const isDark = theme === 'dark';
  document.documentElement.classList.toggle('dark', isDark);
  document.documentElement.setAttribute('data-theme', theme);
  if (document.body) {
    document.body.classList.toggle('dark', isDark);
  }
  if (save) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (e) {}
  }
  updateThemeUI(theme);
}

function initTheme() {
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme, false);

  const optLight = document.getElementById('theme-opt-light');
  const optDark = document.getElementById('theme-opt-dark');

  if (optLight) {
    optLight.addEventListener('click', (e) => {
      e.preventDefault();
      applyTheme('light', true);
    });
  }

  if (optDark) {
    optDark.addEventListener('click', (e) => {
      e.preventDefault();
      applyTheme('dark', true);
    });
  }

  // Sinkronisasi dinamis jika preferensi sistem operasi berubah
  if (window.matchMedia) {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', (e) => {
      try {
        const stored = localStorage.getItem(THEME_STORAGE_KEY);
        if (!stored) {
          applyTheme(e.matches ? 'dark' : 'light', false);
        }
      } catch (err) {}
    });
  }
}

// Navigasi tab alur kerja
const tabs = document.querySelectorAll('.tab');
const panels = document.querySelectorAll('.panel');

tabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    const mode = tab.dataset.mode;

    tabs.forEach((t) => {
      t.classList.remove('tab-active');
      t.setAttribute('aria-selected', 'false');
    });
    tab.classList.add('tab-active');
    tab.setAttribute('aria-selected', 'true');

    panels.forEach((p) => (p.hidden = true));
    const targetPanel = document.getElementById(`panel-${mode}`);
    if (targetPanel) {
      targetPanel.hidden = false;
    }
  });
});

// Unggah berkas citra (seret & letakkan atau pilih berkas)
function setupUpload(mode) {
  const dropzone = document.getElementById(`dropzone-${mode}`);
  const fileInput = document.getElementById(`file-${mode}`);
  const previewWrap = document.getElementById(`preview-${mode}`);
  const removeBtn = document.getElementById(`remove-${mode}`);

  if (!dropzone || !fileInput) return;

  // Klik untuk memilih berkas dari perangkat
  dropzone.addEventListener('click', () => fileInput.click());

  // Mencegah bubble jika input berada di dalam dropzone
  fileInput.addEventListener('click', (e) => e.stopPropagation());

  // Aksesibilitas keyboard untuk area dropzone
  dropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });

  // Event seret dan letakkan
  ['dragenter', 'dragover'].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files[0];
    const validMimes = ['image/png', 'image/jpeg', 'image/jpg'];
    if (file && validMimes.includes(file.type)) {
      handleFile(mode, file);
    } else {
      showToast('Format file tidak didukung. Gunakan PNG atau JPEG.', 'error');
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) {
      handleFile(mode, fileInput.files[0]);
    }
  });

  // Tombol ganti citra
  if (removeBtn) {
    removeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      state[mode].file = null;
      fileInput.value = '';
      previewWrap.hidden = true;
      dropzone.hidden = false;
      
      // Sembunyikan panel hasil sebelumnya agar tidak misleading
      let parentMode = mode;
      if (mode === 'logo') parentMode = 'embed';
      else if (mode.startsWith('ref-logo-')) parentMode = mode.replace('ref-logo-', '');
      
      const resultPanel = document.getElementById(`result-${parentMode}`);
      if (resultPanel) resultPanel.hidden = true;

      validateForm(mode === 'logo' ? 'embed' : mode);
    });
  }
}

function handleFile(mode, file) {
  // Validasi tipe berkas dan ekstensi dengan ketat (Anti-Spoofing Dasar)
  const validMimes = ['image/png', 'image/jpeg', 'image/jpg'];
  const ext = file.name.split('.').pop().toLowerCase();
  const validExts = ['png', 'jpg', 'jpeg'];
  
  if (!validMimes.includes(file.type) || !validExts.includes(ext)) {
    showToast('Format tidak didukung atau file mencurigakan. Gunakan PNG/JPEG.', 'error');
    return;
  }

  // Validasi ukuran berkas maksimal 10 MB
  if (file.size > 10 * 1024 * 1024) {
    showToast('Ukuran file melebihi batas 10 MB.', 'error');
    return;
  }

  state[mode].file = file;

  const dropzone = document.getElementById(`dropzone-${mode}`);
  const previewWrap = document.getElementById(`preview-${mode}`);
  const previewImg = document.getElementById(`img-${mode}`);
  const infoEl = document.getElementById(`info-${mode}`);

  const reader = new FileReader();
  reader.onload = (e) => {
    previewImg.src = e.target.result;
    dropzone.hidden = true;
    previewWrap.hidden = false;

    // Tampilkan informasi berkas citra
    const img = new Image();
    img.onload = () => {
      const sizeKB = (file.size / 1024).toFixed(1);
      infoEl.textContent = `${file.name} • ${img.width}×${img.height} px • ${sizeKB} KB`;
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
  validateForm(mode === 'logo' ? 'embed' : mode);
}

// Inisialisasi zona unggah untuk seluruh alur kerja (termasuk logo watermark & referensi logo)
['embed', 'detect', 'attack', 'logo', 'ref-logo-detect', 'ref-logo-attack'].forEach(setupUpload);

// Pengalihan tipe watermark: teks atau logo
const WM_TYPE_STORAGE_KEY = 'veilux_watermark_type';
const typeOptText = document.getElementById('type-opt-text');
const typeOptLogo = document.getElementById('type-opt-logo');
const formGroupText = document.getElementById('form-group-text');
const formGroupLogo = document.getElementById('form-group-logo');

function setWatermarkType(type, save = true) {
  state.embed.watermarkType = type;
  if (save) {
    try {
      localStorage.setItem(WM_TYPE_STORAGE_KEY, type);
    } catch (e) {}
  }
  const isText = type === 'text';

  if (typeOptText) {
    typeOptText.classList.toggle('type-selector-btn-active', isText);
    typeOptText.setAttribute('aria-pressed', isText ? 'true' : 'false');
  }
  if (typeOptLogo) {
    typeOptLogo.classList.toggle('type-selector-btn-active', !isText);
    typeOptLogo.setAttribute('aria-pressed', isText ? 'false' : 'true');
  }

  if (formGroupText) {
    formGroupText.hidden = !isText;
    formGroupText.style.display = isText ? '' : 'none';
  }
  if (formGroupLogo) {
    formGroupLogo.hidden = isText;
    formGroupLogo.style.display = isText ? 'none' : '';
  }

  validateForm('embed');
}

function initWatermarkType() {
  let savedType = 'text';
  try {
    const stored = localStorage.getItem(WM_TYPE_STORAGE_KEY);
    if (stored === 'text' || stored === 'logo') {
      savedType = stored;
    }
  } catch (e) {}
  setWatermarkType(savedType, false);
}

if (typeOptText) {
  typeOptText.addEventListener('click', (e) => {
    e.preventDefault();
    setWatermarkType('text', true);
  });
}

if (typeOptLogo) {
  typeOptLogo.addEventListener('click', (e) => {
    e.preventDefault();
    setWatermarkType('logo', true);
  });
}

// Pengalihan tipe referensi watermark pada panel deteksi
const detectRefOptText = document.getElementById('detect-ref-opt-text');
const detectRefOptLogo = document.getElementById('detect-ref-opt-logo');
const formGroupRefTextDetect = document.getElementById('form-group-ref-text-detect');
const formGroupRefLogoDetect = document.getElementById('form-group-ref-logo-detect');

function setDetectRefType(type) {
  state.detect.refType = type;
  const isText = type === 'text';

  if (detectRefOptText) {
    detectRefOptText.classList.toggle('type-selector-btn-active', isText);
    detectRefOptText.setAttribute('aria-pressed', isText ? 'true' : 'false');
  }
  if (detectRefOptLogo) {
    detectRefOptLogo.classList.toggle('type-selector-btn-active', !isText);
    detectRefOptLogo.setAttribute('aria-pressed', isText ? 'false' : 'true');
  }

  if (formGroupRefTextDetect) {
    formGroupRefTextDetect.hidden = !isText;
    formGroupRefTextDetect.style.display = isText ? '' : 'none';
  }
  if (formGroupRefLogoDetect) {
    formGroupRefLogoDetect.hidden = isText;
    formGroupRefLogoDetect.style.display = isText ? 'none' : '';
  }
}

if (detectRefOptText) {
  detectRefOptText.addEventListener('click', (e) => {
    e.preventDefault();
    setDetectRefType('text');
  });
}

if (detectRefOptLogo) {
  detectRefOptLogo.addEventListener('click', (e) => {
    e.preventDefault();
    setDetectRefType('logo');
  });
}

// Pengalihan tipe referensi watermark pada panel uji serangan (attack)
const attackRefOptText = document.getElementById('attack-ref-opt-text');
const attackRefOptLogo = document.getElementById('attack-ref-opt-logo');
const formGroupRefTextAttack = document.getElementById('form-group-ref-text-attack');
const formGroupRefLogoAttack = document.getElementById('form-group-ref-logo-attack');

function setAttackRefType(type) {
  state.attack.refType = type;
  const isText = type === 'text';

  if (attackRefOptText) {
    attackRefOptText.classList.toggle('type-selector-btn-active', isText);
    attackRefOptText.setAttribute('aria-pressed', isText ? 'true' : 'false');
  }
  if (attackRefOptLogo) {
    attackRefOptLogo.classList.toggle('type-selector-btn-active', !isText);
    attackRefOptLogo.setAttribute('aria-pressed', isText ? 'false' : 'true');
  }

  if (formGroupRefTextAttack) {
    formGroupRefTextAttack.hidden = !isText;
    formGroupRefTextAttack.style.display = isText ? '' : 'none';
  }
  if (formGroupRefLogoAttack) {
    formGroupRefLogoAttack.hidden = isText;
    formGroupRefLogoAttack.style.display = isText ? 'none' : '';
  }
}

if (attackRefOptText) {
  attackRefOptText.addEventListener('click', (e) => {
    e.preventDefault();
    setAttackRefType('text');
  });
}

if (attackRefOptLogo) {
  attackRefOptLogo.addEventListener('click', (e) => {
    e.preventDefault();
    setAttackRefType('logo');
  });
}

// Validasi formulir dan indikator kelengkapan parameter
function updateValidationFeedback(mode, isValid, missingItems) {
  const reqEl = document.getElementById(`requirements-${mode}`);
  if (!reqEl) return;

  if (isValid) {
    reqEl.dataset.ready = 'true';
    if (mode === 'embed') {
      reqEl.textContent = 'Parameter lengkap, siap menyisipkan watermark';
    } else if (mode === 'detect') {
      reqEl.textContent = 'Parameter lengkap, siap mengeksekusi deteksi';
    } else if (mode === 'attack') {
      reqEl.textContent = 'Parameter lengkap, siap mengeksekusi serangan & deteksi';
    }
  } else {
    reqEl.dataset.ready = 'false';
    reqEl.textContent = `Memerlukan: ${missingItems.join(', ')}`;
  }
}

function validateForm(mode) {
  if (mode === 'embed') {
    const hasFile = !!state.embed.file;
    const isLogo = state.embed.watermarkType === 'logo';
    const hasWatermark = isLogo
      ? !!state.logo.file
      : document.getElementById('watermark-text').value.trim().length > 0;
    const hasKey = document.getElementById('secret-key-embed').value.trim().length > 0;
    const isValid = hasFile && hasWatermark && hasKey;

    const btn = document.getElementById('btn-embed');
    if (btn) btn.disabled = !isValid;

    const missing = [];
    if (!hasFile) missing.push('citra sampul');
    if (!hasWatermark) missing.push(isLogo ? 'berkas logo' : 'payload watermark');
    if (!hasKey) missing.push('secret key');
    updateValidationFeedback('embed', isValid, missing);
  } else if (mode === 'detect') {
    const hasFile = !!state.detect.file;
    const hasKey = document.getElementById('secret-key-detect').value.trim().length > 0;
    const isValid = hasFile && hasKey;

    const btn = document.getElementById('btn-detect');
    if (btn) btn.disabled = !isValid;

    const missing = [];
    if (!hasFile) missing.push('citra ber-watermark');
    if (!hasKey) missing.push('secret key');
    updateValidationFeedback('detect', isValid, missing);
  } else if (mode === 'attack') {
    const hasFile = !!state.attack.file;
    const hasKey = document.getElementById('secret-key-attack').value.trim().length > 0;
    const hasAttack = !!state.attack.selectedAttack;
    const isValid = hasFile && hasKey && hasAttack;

    const btn = document.getElementById('btn-attack');
    if (btn) btn.disabled = !isValid;

    const btnBench = document.getElementById('btn-benchmark-all');
    if (btnBench) btnBench.disabled = !(hasFile && hasKey);

    const missing = [];
    if (!hasFile) missing.push('citra ber-watermark');
    if (!hasKey) missing.push('secret key');
    if (!hasAttack) missing.push('pilihan jenis serangan');
    updateValidationFeedback('attack', isValid, missing);
  }
}

// Pasang event listener input untuk validasi langsung
const watermarkTextEl = document.getElementById('watermark-text');
const secretKeyEmbedEl = document.getElementById('secret-key-embed');
const secretKeyDetectEl = document.getElementById('secret-key-detect');
const secretKeyAttackEl = document.getElementById('secret-key-attack');

if (watermarkTextEl) {
  watermarkTextEl.addEventListener('input', () => {
    validateForm('embed');
    const counter = document.getElementById('watermark-counter');
    if (counter) counter.textContent = `${watermarkTextEl.value.length}/64`;
  });
}

if (secretKeyEmbedEl) {
  secretKeyEmbedEl.addEventListener('input', () => validateForm('embed'));
}

if (secretKeyDetectEl) {
  secretKeyDetectEl.addEventListener('input', () => validateForm('detect'));
}

if (secretKeyAttackEl) {
  secretKeyAttackEl.addEventListener('input', () => validateForm('attack'));
}

// Penghitung karakter langsung untuk field opsional
const origWmDetect = document.getElementById('original-watermark-detect');
if (origWmDetect) {
  origWmDetect.addEventListener('input', () => {
    const counter = document.getElementById('original-watermark-detect-counter');
    if (counter) counter.textContent = `${origWmDetect.value.length}/64`;
  });
}

const origWmAttack = document.getElementById('original-watermark-attack');
if (origWmAttack) {
  origWmAttack.addEventListener('input', () => {
    const counter = document.getElementById('original-watermark-attack-counter');
    if (counter) counter.textContent = `${origWmAttack.value.length}/64`;
  });
}

// Pengaturan status validasi awal
validateForm('embed');
validateForm('detect');
validateForm('attack');

// Pengalihan visibilitas input kunci rahasia
document.querySelectorAll('.input-toggle-vis').forEach((btn) => {
  btn.addEventListener('click', () => {
    const targetId = btn.dataset.target;
    const input = document.getElementById(targetId);
    if (!input) return;

    if (input.type === 'password') {
      input.type = 'text';
      btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
        <line x1="1" y1="1" x2="23" y2="23"/>
      </svg>`;
    } else {
      input.type = 'password';
      btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
      </svg>`;
    }
  });
});

// Pemilihan jenis simulasi serangan
const attackBtns = document.querySelectorAll('.attack-btn');

attackBtns.forEach((btn) => {
  btn.addEventListener('click', () => {
    attackBtns.forEach((b) => b.classList.remove('attack-btn-active'));
    btn.classList.add('attack-btn-active');
    state.attack.selectedAttack = btn.dataset.attack;
    validateForm('attack');
  });
});

// Panggilan API backend
async function apiCall(endpoint, formData) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Server error: ${response.status}`);
  }

  return response.json();
}

// Alur kerja penyisipan watermark (embed)
const btnEmbed = document.getElementById('btn-embed');
if (btnEmbed) {
  btnEmbed.addEventListener('click', async () => {
    const isLogo = state.embed.watermarkType === 'logo';
    const formData = new FormData();
    formData.append('image', state.embed.file);
    formData.append('secret_key', document.getElementById('secret-key-embed').value.trim());
    formData.append('watermark_type', state.embed.watermarkType);

    if (isLogo) {
      if (!state.logo.file) {
        showToast('Berkas logo wajib dipilih sebelum menyisipkan.', 'error');
        return;
      }
      formData.append('logo', state.logo.file);
    } else {
      const wmText = document.getElementById('watermark-text').value.trim();
      if (!wmText) {
        showToast('Payload watermark teks tidak boleh kosong.', 'error');
        return;
      }
      formData.append('watermark', wmText);
    }

    showLoading(isLogo ? 'Memproses biner logo & menyisipkan ke bit LSB...' : 'Menyisipkan watermark ke bit LSB citra...');

    try {
      const data = await apiCall('/embed', formData);

      document.getElementById('result-original').src = data.original_image;
      const imgWatermarked = document.getElementById('result-watermarked');
      imgWatermarked.src = data.watermarked_image;
      imgWatermarked.style.cursor = 'zoom-in';
      imgWatermarked.title = 'Klik untuk membuka citra di tab baru';
      imgWatermarked.onclick = () => openImageInNewTab(data.watermarked_image);
      document.getElementById('metric-psnr').textContent = data.psnr.toFixed(2);
      document.getElementById('metric-mse').textContent = data.mse.toFixed(5);

      // Perbarui keterangan dinamis sesuai nilai metrik
      const hintPsnr = document.getElementById('hint-metric-psnr');
      if (hintPsnr) {
        hintPsnr.textContent = data.psnr >= 40
          ? `Kualitas imperceptible sangat tinggi (${data.psnr.toFixed(2)} dB >= 40 dB)`
          : (data.psnr >= 30
            ? `Kualitas baik (${data.psnr.toFixed(2)} dB >= 30 dB)`
            : `Kualitas di bawah standar (${data.psnr.toFixed(2)} dB < 30 dB)`);
      }
      const hintMse = document.getElementById('hint-metric-mse');
      if (hintMse) {
        hintMse.textContent = data.mse < 0.1
          ? `Distorsi sangat minimal (${data.mse.toFixed(5)} < 0.1)`
          : `Distorsi terdeteksi (${data.mse.toFixed(5)})`;
      }

      document.getElementById('result-embed').hidden = false;

      // Tombol unduh hasil penyisipan citra
      document.getElementById('btn-download-watermarked').onclick = () => {
        downloadBase64(data.watermarked_image, 'veilux-watermarked.png');
      };

      showToast('Watermark berhasil disisipkan.', 'success');
    } catch (err) {
      showToast(`Gagal: ${err.message}`, 'error');
    } finally {
      hideLoading();
    }
  });
}

// Alur kerja deteksi watermark (detect)
const btnDetect = document.getElementById('btn-detect');
if (btnDetect) {
  btnDetect.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('image', state.detect.file);
    formData.append('secret_key', document.getElementById('secret-key-detect').value.trim());

    if (state.detect.refType === 'logo') {
      if (state['ref-logo-detect'] && state['ref-logo-detect'].file) {
        formData.append('original_logo', state['ref-logo-detect'].file);
      }
    } else {
      const origWm = document.getElementById('original-watermark-detect').value.trim();
      if (origWm) {
        formData.append('original_watermark', origWm);
      }
    }

    showLoading('Mengekstrak bit LSB & menganalisis integritas...');

    try {
      const data = await apiCall('/detect', formData);

      const statusEl = document.getElementById('detect-status');
      const statusTitleEl = document.getElementById('detect-status-title');
      const statusDescEl = document.getElementById('detect-status-desc');
      const badgeIntegrity = document.getElementById('badge-detect-integrity');
      const badgeWatermark = document.getElementById('badge-detect-watermark');
      const wmTextEl = document.getElementById('detected-watermark-text');
      const logoWrap = document.getElementById('detected-logo-wrap');
      const logoImg = document.getElementById('detected-logo-img');
      const logoDims = document.getElementById('detected-logo-dims');

      if (data.watermark_detected) {
        statusEl.classList.remove('detect-status-fail');
        statusEl.querySelector('.detect-status-icon').textContent = '✓';

        if (badgeIntegrity) {
          badgeIntegrity.className = 'status-badge status-badge-ok';
          badgeIntegrity.textContent = 'HMAC: VALID';
        }
        if (badgeWatermark) {
          badgeWatermark.className = 'status-badge status-badge-ok';
          badgeWatermark.textContent = 'WATERMARK: UTUH';
        }
        if (statusTitleEl) statusTitleEl.textContent = 'Watermark Terdeteksi & Integritas Autentik';
        if (statusDescEl) statusDescEl.textContent = 'Tag HMAC blok cocok sempurna, payload terekstrak tanpa manipulasi.';

        if (data.watermark_type === 'LOGO' && data.logo_image) {
          if (wmTextEl) wmTextEl.style.display = 'none';
          if (logoWrap) logoWrap.hidden = false;
          if (logoImg) logoImg.src = data.logo_image;
          if (logoDims) logoDims.textContent = `${data.logo_width} × ${data.logo_height} px`;
        } else {
          if (logoWrap) logoWrap.hidden = true;
          if (wmTextEl) {
            wmTextEl.style.display = 'block';
            wmTextEl.textContent = `"${data.watermark}"`;
          }
        }
      } else {
        statusEl.classList.add('detect-status-fail');
        statusEl.querySelector('.detect-status-icon').textContent = '✗';

        if (badgeIntegrity) {
          badgeIntegrity.className = 'status-badge status-badge-fail';
          badgeIntegrity.textContent = 'HMAC: TIDAK VALID';
        }
        if (badgeWatermark) {
          badgeWatermark.className = data.nc !== null && data.nc > 0
            ? 'status-badge status-badge-warn'
            : 'status-badge status-badge-fail';
          badgeWatermark.textContent = data.nc !== null && data.nc > 0
            ? 'WATERMARK: RUSAK / TERDEGRADASI'
            : 'WATERMARK: TIDAK DITEMUKAN';
        }
        if (statusTitleEl) statusTitleEl.textContent = 'Integritas Rusak atau Secret Key Salah';
        if (statusDescEl) {
          statusDescEl.textContent = data.nc !== null
            ? 'Otentikasi HMAC gagal. Metrik NC & BER dihitung dari pembandingan bit LSB spasial terhadap referensi.'
            : 'Verifikasi HMAC gagal dan tidak ada referensi pembanding untuk membaca korelasi LSB.';
        }

        if (wmTextEl) {
          wmTextEl.style.display = 'block';
          wmTextEl.textContent = '';
        }
        if (logoWrap) logoWrap.hidden = true;
      }

      document.getElementById('detect-input-img').src = data.input_image;
      const imgDetectTamper = document.getElementById('detect-tamper-map');
      imgDetectTamper.src = data.tamper_map;
      imgDetectTamper.style.cursor = 'zoom-in';
      imgDetectTamper.title = 'Klik untuk membuka citra di tab baru';
      imgDetectTamper.onclick = () => openImageInNewTab(data.tamper_map);

      document.getElementById('metric-nc').textContent =
        data.nc !== null ? data.nc.toFixed(4) : '--';
      document.getElementById('metric-ber').textContent =
        data.ber !== null ? data.ber.toFixed(4) : '--';

      // Perbarui keterangan dinamis pada metric card hint (detect)
      const hintNc = document.getElementById('hint-metric-nc');
      if (hintNc) {
        if (data.nc === null) {
          hintNc.textContent = 'Memerlukan watermark/logo referensi asli untuk evaluasi NC';
        } else if (data.nc >= 0.99) {
          hintNc.textContent = `Watermark identik sempurna (NC: ${data.nc.toFixed(4)} ≈ 1.0000)`;
        } else if (data.nc >= 0.8) {
          hintNc.textContent = `Korelasi tinggi di atas ambang batas (NC: ${data.nc.toFixed(4)} >= 0.8000)`;
        } else {
          hintNc.textContent = `Degradasi korelasi terdeteksi (NC: ${data.nc.toFixed(4)} < 0.8000)`;
        }
      }

      const hintBer = document.getElementById('hint-metric-ber');
      if (hintBer) {
        if (data.ber === null) {
          hintBer.textContent = 'Memerlukan watermark/logo referensi asli untuk evaluasi BER';
        } else if (data.ber === 0) {
          hintBer.textContent = 'Bebas galat: 0.0000 (seluruh bit cocok 100%)';
        } else if (data.ber <= 0.15) {
          hintBer.textContent = `Galat rendah dalam batas toleransi (BER: ${(data.ber * 100).toFixed(2)}%)`;
        } else {
          hintBer.textContent = `Galat bit tinggi melebihi ambang batas kritis (BER: ${(data.ber * 100).toFixed(2)}%)`;
        }
      }

      // Tampilkan statistik integritas blok
      const validBlocksEl = document.getElementById('detect-valid-blocks');
      const totalBlocksEl = document.getElementById('detect-total-blocks');
      const tamperRatioEl = document.getElementById('detect-tamper-ratio');
      if (validBlocksEl) validBlocksEl.textContent = data.valid_blocks;
      if (totalBlocksEl) totalBlocksEl.textContent = data.total_blocks;
      if (tamperRatioEl) tamperRatioEl.textContent = (data.tamper_ratio * 100).toFixed(1) + '%';

      const hintValidBlocks = document.getElementById('hint-detect-valid-blocks');
      if (hintValidBlocks) {
        hintValidBlocks.textContent = data.valid_blocks === data.total_blocks
          ? `Seluruh blok (${data.valid_blocks}/${data.total_blocks}) utuh & terverifikasi HMAC`
          : `${data.total_blocks - data.valid_blocks} dari ${data.total_blocks} blok terindikasi rusak/termodifikasi`;
      }

      const hintTamperRatio = document.getElementById('hint-detect-tamper-ratio');
      if (hintTamperRatio) {
        hintTamperRatio.textContent = data.tamper_ratio === 0
          ? 'Integritas 100% utuh tanpa manipulasi'
          : `Area termodifikasi: ${(data.tamper_ratio * 100).toFixed(1)}% dari total citra`;
      }

      // Tombol unduh hasil tamper map
      const btnDownloadTamperMap = document.getElementById('btn-download-tamper-map');
      if (btnDownloadTamperMap) {
        btnDownloadTamperMap.onclick = () => {
          downloadBase64(data.tamper_map, 'veilux-tamper-map.png');
        };
      }

      document.getElementById('result-detect').hidden = false;
      showToast('Analisis deteksi watermark selesai.', 'success');
    } catch (err) {
      showToast(`Gagal: ${err.message}`, 'error');
    } finally {
      hideLoading();
    }
  });
}

// Alur kerja simulasi serangan (attack)
const btnAttack = document.getElementById('btn-attack');
if (btnAttack) {
  btnAttack.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('image', state.attack.file);
    formData.append('secret_key', document.getElementById('secret-key-attack').value.trim());
    formData.append('attack_type', state.attack.selectedAttack);

    if (state.attack.refType === 'logo') {
      if (state['ref-logo-attack'] && state['ref-logo-attack'].file) {
        formData.append('original_logo', state['ref-logo-attack'].file);
      }
    } else {
      const origWm = document.getElementById('original-watermark-attack').value.trim();
      if (origWm) {
        formData.append('original_watermark', origWm);
      }
    }

    const attackNames = {
      jpeg_90: 'JPEG (Kualitas 90)',
      jpeg_70: 'JPEG (Kualitas 70)',
      jpeg_50: 'JPEG (Kualitas 50)',
      crop: 'Cropping',
      resize: 'Resize',
      noise: 'Gaussian Noise',
      brightness: 'Brightness Adjustment',
      contrast: 'Contrast Adjustment',
    };

    showLoading(`Menjalankan simulasi serangan ${attackNames[state.attack.selectedAttack]}...`);

    try {
      const data = await apiCall('/attack', formData);

      document.getElementById('attack-result-header').textContent =
        `SERANGAN: ${attackNames[state.attack.selectedAttack].toUpperCase()}`;

      document.getElementById('attack-before').src = data.before_image;
      const imgAttackAfter = document.getElementById('attack-after');
      imgAttackAfter.src = data.after_image;
      imgAttackAfter.style.cursor = 'zoom-in';
      imgAttackAfter.title = 'Klik untuk membuka citra di tab baru';
      imgAttackAfter.onclick = () => openImageInNewTab(data.after_image);

      const imgAttackTamper = document.getElementById('attack-tamper');
      imgAttackTamper.src = data.tamper_map;
      imgAttackTamper.style.cursor = 'zoom-in';
      imgAttackTamper.title = 'Klik untuk membuka citra di tab baru';
      imgAttackTamper.onclick = () => openImageInNewTab(data.tamper_map);

      document.getElementById('attack-psnr').textContent = data.psnr.toFixed(2);
      document.getElementById('attack-mse').textContent = data.mse.toFixed(5);

      // Statistik integritas blok pasca-serangan
      const attackValidBlocksEl = document.getElementById('attack-valid-blocks');
      const attackTotalBlocksEl = document.getElementById('attack-total-blocks');
      const attackTamperRatioEl = document.getElementById('attack-tamper-ratio');
      if (attackValidBlocksEl) attackValidBlocksEl.textContent = data.valid_blocks;
      if (attackTotalBlocksEl) attackTotalBlocksEl.textContent = data.total_blocks;
      if (attackTamperRatioEl) attackTamperRatioEl.textContent = (data.tamper_ratio * 100).toFixed(1) + '%';
      document.getElementById('attack-nc').textContent =
        data.nc !== null ? data.nc.toFixed(4) : '--';
      document.getElementById('attack-ber').textContent =
        data.ber !== null ? data.ber.toFixed(4) : '--';

      // Perbarui keterangan dinamis pada metric card hint (attack)
      const hintAttPsnr = document.getElementById('hint-attack-psnr');
      if (hintAttPsnr) {
        hintAttPsnr.textContent = data.psnr >= 35
          ? `Distorsi visual rendah (${data.psnr.toFixed(2)} dB)`
          : (data.psnr >= 25
            ? `Distorsi visual sedang (${data.psnr.toFixed(2)} dB)`
            : `Distorsi visual berat (${data.psnr.toFixed(2)} dB)`);
      }

      const hintAttMse = document.getElementById('hint-attack-mse');
      if (hintAttMse) {
        hintAttMse.textContent = `Deviasi kuadratik piksel rata-rata: ${data.mse.toFixed(4)}`;
      }

      const hintAttNc = document.getElementById('hint-attack-nc');
      if (hintAttNc) {
        if (state.attack.selectedAttack === 'crop') {
          hintAttNc.textContent = 'Desinkronisasi spasial: dimensi berubah akibat cropping, NC tidak valid';
        } else if (data.nc === null) {
          hintAttNc.textContent = 'Tidak ada watermark referensi untuk mengukur korelasi';
        } else if (data.nc >= 0.99) {
          hintAttNc.textContent = `Watermark bertahan sempurna pasca-serangan (NC: ${data.nc.toFixed(4)})`;
        } else if (data.nc >= 0.7) {
          hintAttNc.textContent = `Korelasi watermark bertahan moderat (NC: ${data.nc.toFixed(4)})`;
        } else {
          hintAttNc.textContent = `Korelasi rusak parah akibat serangan (NC: ${data.nc.toFixed(4)})`;
        }
      }

      const hintAttBer = document.getElementById('hint-attack-ber');
      if (hintAttBer) {
        if (state.attack.selectedAttack === 'crop') {
          hintAttBer.textContent = 'Desinkronisasi spasial: koordinat LSB terpotong, BER tidak valid';
        } else if (data.ber === null) {
          hintAttBer.textContent = 'Tidak ada watermark referensi untuk mengukur bit error';
        } else if (data.ber === 0) {
          hintAttBer.textContent = '0% bit berubah (seluruh bit watermark utuh)';
        } else {
          hintAttBer.textContent = `${(data.ber * 100).toFixed(2)}% bit LSB rusak akibat manipulasi`;
        }
      }

      const hintAttValidBlocks = document.getElementById('hint-attack-valid-blocks');
      if (hintAttValidBlocks) {
        hintAttValidBlocks.textContent = data.valid_blocks === data.total_blocks
          ? `Seluruh blok (${data.valid_blocks}/${data.total_blocks}) bertahan dari serangan`
          : `${data.total_blocks - data.valid_blocks} dari ${data.total_blocks} blok rusak akibat serangan`;
      }

      const hintAttTamperRatio = document.getElementById('hint-attack-tamper-ratio');
      if (hintAttTamperRatio) {
        hintAttTamperRatio.textContent = data.tamper_ratio === 0
          ? 'Kerusakan 0.0% (struktur blok utuh)'
          : `${(data.tamper_ratio * 100).toFixed(1)}% blok citra terindikasi rusak`;
      }

      const statusEl = document.getElementById('attack-detect-status');
      const statusTextEl = document.getElementById('attack-detect-text');
      const statusDescEl = document.getElementById('attack-detect-desc');
      const badgeIntegrity = document.getElementById('badge-attack-integrity');
      const badgeWatermark = document.getElementById('badge-attack-watermark');
      const wmEl = document.getElementById('attack-detected-watermark');
      const attackLogoWrap = document.getElementById('attack-detected-logo-wrap');
      const attackLogoImg = document.getElementById('attack-detected-logo-img');
      const attackLogoDims = document.getElementById('attack-detected-logo-dims');

      if (data.watermark_detected) {
        statusEl.classList.remove('detect-status-fail');
        statusEl.querySelector('.detect-status-icon').textContent = '✓';

        if (badgeIntegrity) {
          badgeIntegrity.className = 'status-badge status-badge-ok';
          badgeIntegrity.textContent = 'HMAC: VALID';
        }
        if (badgeWatermark) {
          badgeWatermark.className = 'status-badge status-badge-ok';
          badgeWatermark.textContent = 'WATERMARK: UTUH';
        }
        if (statusTextEl) statusTextEl.textContent = 'Watermark Masih Utuh / Bertahan';
        if (statusDescEl) statusDescEl.textContent = 'Otentikasi HMAC lolos verifikasi pasca-manipulasi.';

        if (data.watermark_type === 'LOGO' && data.logo_image) {
          if (wmEl) wmEl.style.display = 'none';
          if (attackLogoWrap) attackLogoWrap.hidden = false;
          if (attackLogoImg) attackLogoImg.src = data.logo_image;
          if (attackLogoDims) attackLogoDims.textContent = `${data.logo_width} × ${data.logo_height} px`;
        } else {
          if (attackLogoWrap) attackLogoWrap.hidden = true;
          if (wmEl) {
            wmEl.style.display = 'block';
            wmEl.textContent = `"${data.watermark}"`;
          }
        }
      } else {
        statusEl.classList.add('detect-status-fail');
        statusEl.querySelector('.detect-status-icon').textContent = '✗';

        if (badgeIntegrity) {
          badgeIntegrity.className = 'status-badge status-badge-fail';
          badgeIntegrity.textContent = 'HMAC: RUSAK';
        }
        if (badgeWatermark) {
          if (state.attack.selectedAttack === 'crop') {
            badgeWatermark.className = 'status-badge status-badge-fail';
            badgeWatermark.textContent = 'WATERMARK: DESINKRONISASI';
          } else {
            badgeWatermark.className = data.nc !== null && data.nc > 0
              ? 'status-badge status-badge-warn'
              : 'status-badge status-badge-fail';
            badgeWatermark.textContent = data.nc !== null && data.nc > 0
              ? 'WATERMARK: TERDEGRADASI'
              : 'WATERMARK: HILANG (FRAGILE)';
          }
        }

        if (statusTextEl) statusTextEl.textContent = 'Integritas Rusak Akibat Serangan (Fragile LSB)';
        if (statusDescEl) {
          if (state.attack.selectedAttack === 'crop') {
            statusDescEl.textContent = 'Pemotongan geometri memutus koordinat spasial LSB, memicu kegagalan HMAC total.';
          } else {
            statusDescEl.textContent = data.nc !== null
              ? 'Otentikasi HMAC gagal. Metrik NC & BER dihitung dari pembandingan bit LSB spasial terhadap referensi.'
              : 'Otentikasi HMAC gagal. Pola bit LSB terdistorsi oleh serangan manipulasi.';
          }
        }

        if (wmEl) {
          wmEl.style.display = 'block';
          wmEl.textContent = '';
        }
        if (attackLogoWrap) attackLogoWrap.hidden = true;
      }

      // Tombol unduh hasil attack
      const btnDownloadAttackAfter = document.getElementById('btn-download-attack-after');
      if (btnDownloadAttackAfter) {
        btnDownloadAttackAfter.onclick = () => {
          downloadBase64(data.after_image, 'veilux-attack-result.png');
        };
      }

      const btnDownloadAttackTamper = document.getElementById('btn-download-attack-tamper');
      if (btnDownloadAttackTamper) {
        btnDownloadAttackTamper.onclick = () => {
          downloadBase64(data.tamper_map, 'veilux-attack-tamper-map.png');
        };
      }

      document.getElementById('result-attack').hidden = false;
      showToast('Uji serangan dan deteksi selesai.', 'success');
    } catch (err) {
      showToast(`Gagal: ${err.message}`, 'error');
    } finally {
      hideLoading();
    }
  });
}

// Data cache benchmark seluruh serangan
let currentBenchmarkResults = [];

// Alur kerja benchmark semua 8 jenis serangan
const btnBenchmarkAll = document.getElementById('btn-benchmark-all');
if (btnBenchmarkAll) {
  btnBenchmarkAll.addEventListener('click', async () => {
    const file = state.attack.file;
    const secretKey = document.getElementById('secret-key-attack').value.trim();

    if (!file || !secretKey) {
      showToast('Pilih citra ber-watermark dan masukkan secret key terlebih dahulu.', 'error');
      return;
    }

    const attacks = [
      { key: 'jpeg_90', name: 'JPEG Q90', category: 'Lossy Compression' },
      { key: 'jpeg_70', name: 'JPEG Q70', category: 'Lossy Compression' },
      { key: 'jpeg_50', name: 'JPEG Q50', category: 'Lossy Compression' },
      { key: 'noise', name: 'Gaussian Noise', category: 'Additive Noise' },
      { key: 'brightness', name: 'Brightness Shift', category: 'Luminance Adjustment' },
      { key: 'contrast', name: 'Contrast Adjustment', category: 'Dynamic Range' },
      { key: 'resize', name: 'Resize (50% scale)', category: 'Resampling Scale' },
      { key: 'crop', name: 'Cropping (15% corner)', category: 'Geometric Cropping' },
    ];

    currentBenchmarkResults = [];
    const tbody = document.getElementById('benchmark-table-body');
    if (tbody) tbody.innerHTML = '';
    const section = document.getElementById('benchmark-section');
    if (section) section.hidden = false;

    showLoading('Memulai pengujian 8 serangan (1/8)...');

    try {
      for (let i = 0; i < attacks.length; i++) {
        const atk = attacks[i];
        showLoading(`Menguji serangan ${i + 1}/8: ${atk.name}...`);

        const formData = new FormData();
        formData.append('image', file);
        formData.append('secret_key', secretKey);
        formData.append('attack_type', atk.key);

        if (state.attack.refType === 'logo') {
          if (state['ref-logo-attack'] && state['ref-logo-attack'].file) {
            formData.append('original_logo', state['ref-logo-attack'].file);
          }
        } else {
          const origWm = document.getElementById('original-watermark-attack').value.trim();
          if (origWm) {
            formData.append('original_watermark', origWm);
          }
        }

        const data = await apiCall('/attack', formData);

        const row = {
          no: i + 1,
          name: atk.name,
          category: atk.category,
          psnr: data.psnr.toFixed(2),
          mse: data.mse.toFixed(4),
          nc: data.nc !== null ? data.nc.toFixed(4) : (atk.key === 'crop' ? 'N/A (Crop)' : '--'),
          ber: data.ber !== null ? data.ber.toFixed(4) : (atk.key === 'crop' ? 'N/A (Crop)' : '--'),
          detected: data.watermark_detected,
          validBlocks: `${data.valid_blocks}/${data.total_blocks}`,
          tamperRatio: `${(data.tamper_ratio * 100).toFixed(1)}%`,
        };
        currentBenchmarkResults.push(row);

        if (tbody) {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td>${row.no}</td>
            <td>${row.name}</td>
            <td>${row.category}</td>
            <td>${row.psnr}</td>
            <td>${row.mse}</td>
            <td>${row.nc}</td>
            <td>${row.ber}</td>
            <td><span class="${row.detected ? 'benchmark-badge-ok' : 'benchmark-badge-fail'}">${row.detected ? 'Terdeteksi' : 'Rusak'}</span></td>
            <td>${row.validBlocks}</td>
            <td>${row.tamperRatio}</td>
          `;
          tbody.appendChild(tr);
        }
      }

      document.getElementById('result-attack').hidden = false;
      section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      showToast('Seluruh 8 pengujian serangan selesai.', 'success');
    } catch (err) {
      showToast(`Gagal saat benchmark: ${err.message}`, 'error');
    } finally {
      hideLoading();
    }
  });
}

// Tombol salin hasil benchmark ke format Markdown
const btnCopyBenchmarkMd = document.getElementById('btn-copy-benchmark-md');
if (btnCopyBenchmarkMd) {
  btnCopyBenchmarkMd.addEventListener('click', async () => {
    if (!currentBenchmarkResults.length) {
      showToast('Belum ada data benchmark untuk disalin.', 'info');
      return;
    }

    let md = '| No | Jenis Serangan | Kategori | PSNR (dB) | MSE | NC | BER | Status Watermark | Blok Valid | Tamper Ratio |\n';
    md += '|---|---|---|---|---|---|---|---|---|---|\n';
    currentBenchmarkResults.forEach((r) => {
      const statusText = r.detected ? 'Terdeteksi' : 'Rusak (Fragile)';
      md += `| ${r.no} | ${r.name} | ${r.category} | ${r.psnr} | ${r.mse} | ${r.nc} | ${r.ber} | ${statusText} | ${r.validBlocks} | ${r.tamperRatio} |\n`;
    });

    try {
      await navigator.clipboard.writeText(md);
      showToast('Tabel Markdown berhasil disalin ke clipboard!', 'success');
    } catch (err) {
      // Fallback salin via textarea jika clipboard API diblokir
      const ta = document.createElement('textarea');
      ta.value = md;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('Tabel Markdown berhasil disalin ke clipboard!', 'success');
    }
  });
}

// Tombol unduh hasil benchmark format CSV
const btnDownloadBenchmarkCsv = document.getElementById('btn-download-benchmark-csv');
if (btnDownloadBenchmarkCsv) {
  btnDownloadBenchmarkCsv.addEventListener('click', () => {
    if (!currentBenchmarkResults.length) {
      showToast('Belum ada data benchmark untuk diunduh.', 'info');
      return;
    }

    let csv = 'No,Jenis Serangan,Kategori,PSNR (dB),MSE,NC,BER,Status Watermark,Blok Valid,Tamper Ratio\n';
    currentBenchmarkResults.forEach((r) => {
      const statusText = r.detected ? 'Terdeteksi' : 'Rusak';
      csv += `${r.no},"${r.name}","${r.category}",${r.psnr},${r.mse},${r.nc},${r.ber},"${statusText}","${r.validBlocks}","${r.tamperRatio}"\n`;
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `veilux-benchmark-serangan-${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Berkas CSV benchmark berhasil diunduh.', 'success');
  });
}

// Fungsi utilitas pendukung
function showLoading(text = 'Memproses...') {
  const loadingText = document.getElementById('loading-text');
  const loading = document.getElementById('loading');
  if (loadingText) loadingText.textContent = text;
  if (loading) loading.hidden = false;
}

function hideLoading() {
  const loading = document.getElementById('loading');
  if (loading) loading.hidden = true;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  const prefix = document.createElement('span');
  prefix.className = 'toast-prefix';
  prefix.textContent = type === 'success' ? '[OK]' : type === 'error' ? '[GAGAL]' : '[INFO]';

  const body = document.createElement('span');
  body.className = 'toast-body';
  body.textContent = message;

  toast.appendChild(prefix);
  toast.appendChild(body);
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-fade-out');
    setTimeout(() => toast.remove(), 200);
  }, 4000);
}

function downloadBase64(dataUrl, filename) {
  try {
    // Konversi Data URL menjadi binary Blob agar pengunduhan hemat memori dan instan
    const parts = dataUrl.split(',');
    const mimeMatch = parts[0].match(/:(.*?);/);
    const mime = mimeMatch ? mimeMatch[1] : 'image/png';
    const bstr = atob(parts[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    const blob = new Blob([u8arr], { type: mime });
    const blobUrl = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
  } catch (e) {
    // Fallback direct href jika decoding gagal
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}

// Utilitas untuk membuka citra hasil di tab baru secara aman menggunakan Blob URL
function openImageInNewTab(dataUrl) {
  try {
    const parts = dataUrl.split(',');
    const mimeMatch = parts[0].match(/:(.*?);/);
    const mime = mimeMatch ? mimeMatch[1] : 'image/png';
    const bstr = atob(parts[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    const blob = new Blob([u8arr], { type: mime });
    const blobUrl = URL.createObjectURL(blob);
    window.open(blobUrl, '_blank');
  } catch (e) {
    const win = window.open();
    if (win) {
      win.document.write(`<iframe src="${dataUrl}" frameborder="0" style="border:0; top:0px; left:0px; bottom:0px; right:0px; width:100%; height:100%;" allowfullscreen></iframe>`);
    }
  }
}

// Inisialisasi tema dan tipe watermark saat aplikasi pertama kali dimuat
initTheme();
initWatermarkType();

// Klien live reload (mode pengembangan lokal)
(function initLiveReload() {
  const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
  if (!isLocal || window.location.protocol === 'file:') return;

  const watchedFiles = ['index.html', 'style.css', 'app.js'];
  const fileTimestamps = {};
  let isChecking = false;

  async function checkFile(file) {
    try {
      const res = await fetch(`${file}?_t=${Date.now()}`, { method: 'HEAD', cache: 'no-store' });
      if (!res.ok) return;
      const lastMod = res.headers.get('Last-Modified') || res.headers.get('ETag');
      if (!lastMod) return;

      if (!fileTimestamps[file]) {
        fileTimestamps[file] = lastMod;
      } else if (fileTimestamps[file] !== lastMod) {
        fileTimestamps[file] = lastMod;
        if (file === 'style.css') {
          const links = document.querySelectorAll('link[rel="stylesheet"]');
          links.forEach((link) => {
            const href = link.getAttribute('href') || '';
            if (href.includes('style.css')) {
              link.setAttribute('href', `style.css?_t=${Date.now()}`);
            }
          });
        } else {
          setTimeout(() => window.location.reload(), 300);
        }
      }
    } catch (e) {}
  }

  setInterval(() => {
    if (isChecking) return;
    isChecking = true;
    Promise.all(watchedFiles.map(checkFile)).finally(() => {
      isChecking = false;
    });
  }, 2500);
})();
