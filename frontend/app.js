/* ════════════════════════════════════════════
   VEILUX // Frontend Application Logic
   Vanilla JS (No frameworks)
   ════════════════════════════════════════════ */

const API_BASE = 'http://localhost:8000/api';

// ── State ──
const state = {
  embed: { file: null },
  detect: { file: null },
  attack: { file: null, selectedAttack: null },
};

// ══════════════════════════════════════════
// TAB NAVIGATION
// ══════════════════════════════════════════
const tabs = document.querySelectorAll('.tab');
const panels = document.querySelectorAll('.panel');

tabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    const mode = tab.dataset.mode;

    tabs.forEach((t) => {
      t.classList.remove('tab--active');
      t.setAttribute('aria-selected', 'false');
    });
    tab.classList.add('tab--active');
    tab.setAttribute('aria-selected', 'true');

    panels.forEach((p) => (p.hidden = true));
    const targetPanel = document.getElementById(`panel-${mode}`);
    if (targetPanel) {
      targetPanel.hidden = false;
    }
  });
});

// ══════════════════════════════════════════
// FILE UPLOAD (Drag & Drop + Click)
// ══════════════════════════════════════════
function setupUpload(mode) {
  const dropzone = document.getElementById(`dropzone-${mode}`);
  const fileInput = document.getElementById(`file-${mode}`);
  const previewWrap = document.getElementById(`preview-${mode}`);
  const previewImg = document.getElementById(`img-${mode}`);
  const removeBtn = document.getElementById(`remove-${mode}`);
  const infoEl = document.getElementById(`info-${mode}`);

  if (!dropzone || !fileInput) return;

  // Click to browse
  dropzone.addEventListener('click', () => fileInput.click());

  // Keyboard accessibility for dropzone
  dropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });

  // Drag events
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
    if (file && file.type.startsWith('image/')) {
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

  // Remove
  if (removeBtn) {
    removeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      state[mode].file = null;
      fileInput.value = '';
      previewWrap.hidden = true;
      dropzone.hidden = false;
      validateForm(mode);
    });
  }
}

function handleFile(mode, file) {
  // Validate size (10MB)
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

    // Show file info
    const img = new Image();
    img.onload = () => {
      const sizeKB = (file.size / 1024).toFixed(1);
      infoEl.textContent = `${file.name} • ${img.width}×${img.height} px • ${sizeKB} KB`;
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
  validateForm(mode);
}

// Initialize uploads
['embed', 'detect', 'attack'].forEach(setupUpload);

// ══════════════════════════════════════════
// FORM VALIDATION & REQUIREMENTS FEEDBACK
// ══════════════════════════════════════════
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
    const hasWatermark = document.getElementById('watermark-text').value.trim().length > 0;
    const hasKey = document.getElementById('secret-key-embed').value.trim().length > 0;
    const isValid = hasFile && hasWatermark && hasKey;

    const btn = document.getElementById('btn-embed');
    if (btn) btn.disabled = !isValid;

    const missing = [];
    if (!hasFile) missing.push('citra sampul');
    if (!hasWatermark) missing.push('payload watermark');
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

    const missing = [];
    if (!hasFile) missing.push('citra ber-watermark');
    if (!hasKey) missing.push('secret key');
    if (!hasAttack) missing.push('pilihan jenis serangan');
    updateValidationFeedback('attack', isValid, missing);
  }
}

// Bind input listeners for validation
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

// Live counters for optional watermark fields
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

// Initial form validation state setup
validateForm('embed');
validateForm('detect');
validateForm('attack');

// ══════════════════════════════════════════
// SECRET KEY VISIBILITY TOGGLE
// ══════════════════════════════════════════
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

// ══════════════════════════════════════════
// ATTACK SELECTION
// ══════════════════════════════════════════
const attackBtns = document.querySelectorAll('.attack-btn');

attackBtns.forEach((btn) => {
  btn.addEventListener('click', () => {
    attackBtns.forEach((b) => b.classList.remove('attack-btn--active'));
    btn.classList.add('attack-btn--active');
    state.attack.selectedAttack = btn.dataset.attack;
    validateForm('attack');
  });
});

// ══════════════════════════════════════════
// API CALLS
// ══════════════════════════════════════════
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

// ── EMBED ──
const btnEmbed = document.getElementById('btn-embed');
if (btnEmbed) {
  btnEmbed.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('image', state.embed.file);
    formData.append('watermark', document.getElementById('watermark-text').value.trim());
    formData.append('secret_key', document.getElementById('secret-key-embed').value.trim());

    showLoading('Menyisipkan watermark ke bit LSB citra...');

    try {
      const data = await apiCall('/embed', formData);

      document.getElementById('result-original').src = data.original_image;
      document.getElementById('result-watermarked').src = data.watermarked_image;
      document.getElementById('metric-psnr').textContent = data.psnr.toFixed(2);
      document.getElementById('metric-mse').textContent = data.mse.toFixed(5);

      document.getElementById('result-embed').hidden = false;

      // Download button
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

// ── DETECT ──
const btnDetect = document.getElementById('btn-detect');
if (btnDetect) {
  btnDetect.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('image', state.detect.file);
    formData.append('secret_key', document.getElementById('secret-key-detect').value.trim());

    const origWm = document.getElementById('original-watermark-detect').value.trim();
    if (origWm) {
      formData.append('original_watermark', origWm);
    }

    showLoading('Mengekstrak bit LSB & menganalisis integritas...');

    try {
      const data = await apiCall('/detect', formData);

      const statusEl = document.getElementById('detect-status');
      const statusTextEl = statusEl.querySelector('.detect-status__text');
      const wmTextEl = document.getElementById('detected-watermark-text');

      if (data.watermark_detected) {
        statusEl.classList.remove('detect-status--fail');
        statusEl.querySelector('.detect-status__icon').textContent = '✓';
        statusTextEl.textContent = 'Watermark Terdeteksi & Terverifikasi';
        wmTextEl.textContent = `"${data.watermark}"`;
      } else {
        statusEl.classList.add('detect-status--fail');
        statusEl.querySelector('.detect-status__icon').textContent = '✗';
        statusTextEl.textContent = 'Watermark Tidak Terdeteksi / Integritas Rusak';
        wmTextEl.textContent = '';
      }

      document.getElementById('metric-nc').textContent =
        data.nc !== null ? data.nc.toFixed(4) : '--';
      document.getElementById('metric-ber').textContent =
        data.ber !== null ? data.ber.toFixed(4) : '--';

      if (data.input_image) {
        document.getElementById('detect-input-img').src = data.input_image;
      }
      if (data.tamper_map) {
        document.getElementById('detect-tamper-map').src = data.tamper_map;
      }

      document.getElementById('result-detect').hidden = false;
      showToast('Analisis deteksi selesai.', 'success');
    } catch (err) {
      showToast(`Gagal: ${err.message}`, 'error');
    } finally {
      hideLoading();
    }
  });
}

// ── ATTACK ──
const btnAttack = document.getElementById('btn-attack');
if (btnAttack) {
  btnAttack.addEventListener('click', async () => {
    const formData = new FormData();
    formData.append('image', state.attack.file);
    formData.append('secret_key', document.getElementById('secret-key-attack').value.trim());
    formData.append('attack_type', state.attack.selectedAttack);

    const origWm = document.getElementById('original-watermark-attack').value.trim();
    if (origWm) {
      formData.append('original_watermark', origWm);
    }

    const attackNames = {
      jpeg90: 'JPEG Compression (Q90)',
      jpeg70: 'JPEG Compression (Q70)',
      jpeg50: 'JPEG Compression (Q50)',
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
      document.getElementById('attack-after').src = data.after_image;
      document.getElementById('attack-tamper').src = data.tamper_map;

      document.getElementById('attack-psnr').textContent = data.psnr.toFixed(2);
      document.getElementById('attack-mse').textContent = data.mse.toFixed(5);
      document.getElementById('attack-nc').textContent =
        data.nc !== null ? data.nc.toFixed(4) : '--';
      document.getElementById('attack-ber').textContent =
        data.ber !== null ? data.ber.toFixed(4) : '--';

      // Attack detect status
      const statusEl = document.getElementById('attack-detect-status');
      const statusTextEl = document.getElementById('attack-detect-text');
      const wmEl = document.getElementById('attack-detected-watermark');

      if (data.watermark_detected) {
        statusEl.classList.remove('detect-status--fail');
        statusEl.querySelector('.detect-status__icon').textContent = '✓';
        statusTextEl.textContent = 'Watermark Masih Terdeteksi (Toleransi Parsial)';
        wmEl.textContent = `"${data.watermark}"`;
      } else {
        statusEl.classList.add('detect-status--fail');
        statusEl.querySelector('.detect-status__icon').textContent = '✗';
        statusTextEl.textContent = 'Watermark Rusak / Pola LSB Hilang (Fragile)';
        wmEl.textContent = '';
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

// ══════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════
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
  toast.className = `toast toast--${type}`;

  const prefix = document.createElement('span');
  prefix.className = 'toast__prefix';
  prefix.textContent = type === 'success' ? '[OK]' : type === 'error' ? '[GAGAL]' : '[INFO]';

  const body = document.createElement('span');
  body.className = 'toast__body';
  body.textContent = message;

  toast.appendChild(prefix);
  toast.appendChild(body);
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast--fade-out');
    setTimeout(() => toast.remove(), 200);
  }, 4000);
}

function downloadBase64(dataUrl, filename) {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ══════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ══════════════════════════════════════════
document.addEventListener('keydown', (e) => {
  // Alt+1/2/3 to switch tabs
  if (e.altKey && ['1', '2', '3'].includes(e.key)) {
    e.preventDefault();
    const modes = ['embed', 'detect', 'attack'];
    const idx = parseInt(e.key, 10) - 1;
    const targetTab = document.querySelector(`[data-mode="${modes[idx]}"]`);
    if (targetTab) {
      targetTab.click();
      targetTab.focus();
    }
  }
});
