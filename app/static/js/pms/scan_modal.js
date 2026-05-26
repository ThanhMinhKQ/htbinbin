// static/js/pms/scan_modal.js
// CCCD QR Scan Modal — RAR-DTA RD23 V2 Optimized
// Architecture: Input-First, Single-Source-of-Truth
// Scanner mode: USB HID Keyboard Wedge with Enter (CR) terminator
'use strict';

/* ═══════════════════════════════════════════════════════════════════
   CONSTANTS — RAR-DTA RD23 V2 tuned
   ═══════════════════════════════════════════════════════════════════ */
const SM_MIN_LEN             = 10;      // min chars for a valid scan
const SM_TIMEOUT_MS          = 90000;   // 90 s overall timeout (generous)
const SM_TERMINATE_MS        = 300;     // silence window → stream complete (backup)
const SM_SCANNER_SPEED_MS    = 30;      // chars faster than this = scanner, not human
const SM_FOCUS_GUARD_MS      = 250;     // re-check focus interval
const SM_MAX_RETRY           = 2;       // auto-retry count for short / corrupt data
const SM_DEBOUNCE_ENTER_MS   = 60;      // debounce after Enter before processing
const SM_REARM_DELAY_MS      = 1200;    // delay before re-arming after error

/* ═══════════════════════════════════════════════════════════════════
   INTERNAL STATE
   ═══════════════════════════════════════════════════════════════════ */
let _smOnSuccess        = null;
let _smParsed           = null;
let _smActive           = false;
let _smProcessing       = false;     // true while an API call is in-flight
let _smTermTimer        = null;      // terminate-silence timer
let _smTimeoutTimer     = null;      // overall safety timeout
let _smFocusGuardId     = null;      // focus guard interval id
let _smRetryCount       = 0;
let _smLastInputTime    = 0;
let _smFirstInputTime   = 0;
let _smStreamDetected   = false;     // true once scanner-speed chars detected
let _smSessionStats     = { ok: 0, fail: 0 };
let _smCameraStream    = null;
let _smCameraRaf       = null;
let _smCameraActive    = false;
let _smBarcodeDetector = null;
let _smLastCameraText  = '';

// --- PHOTO SCANNING VARIABLES ---
let _smOpts             = {};
let _smDocType          = 'passport';
let _smCccdImages       = { front: null, back: null };
let _smCccdPasteActive  = false;   // separate flag for cccd-photo paste
let _smPhotoFile        = null;
let _smPhotoPasteActive = false;

/* ═══════════════════════════════════════════════════════════════════
   ARCHITECTURE: INPUT-FIRST, SINGLE-SOURCE-OF-TRUTH
   ═══════════════════════════════════════════════════════════════════
   RAR-DTA RD23 V2 = USB HID Keyboard Wedge:
     • Scanner types characters into the focused input field
     • Scanner sends Enter (CR) after every scan

   Strategy:
     1. Keep <input> ALWAYS focused  (focus-guard interval)
     2. Listen to 'input' event      (character stream — source of truth)
     3. Listen to 'keydown' for Enter (scanner terminator — primary trigger)
     4. Timeout backup: SM_TERMINATE_MS of silence → auto-process
     5. NO e.preventDefault() on printable chars → browser handles Unicode
     6. NO multi-layer collectors → input.value IS the buffer

   Result:
     ✓ 100 % accurate Unicode / Vietnamese characters
     ✓ Zero double-capture / duplicate data
     ✓ Natural browser input handling
     ✓ Reliable Enter-based termination
   ═══════════════════════════════════════════════════════════════════ */

/* ── helpers ─────────────────────────────────────────────────── */
function _smEl(id) { return document.getElementById(id); }

function _smIsTouchDevice() {
    return (
        'ontouchstart' in window ||
        navigator.maxTouchPoints > 0 ||
        /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
    );
}

/* ═══════════════════════════════════════════════════════════════════
   RAW DATA SANITIZER
   ═══════════════════════════════════════════════════════════════════ */
function _smSanitizeRaw(raw) {
    if (!raw) return '';
    let s = String(raw);
    if (typeof s.normalize === 'function') s = s.normalize('NFKC');
    s = s.replace(/﻿/g, '');
    s = s.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
    s = s.replace(/\r\n|\r|\n/g, '');
    s = s.replace(/[｜¦]/g, '|');
    s = s.replace(/\|{3,}/g, '||');
    if (typeof s.normalize === 'function') s = s.normalize('NFC');
    return s.trim();
}

/* ═══════════════════════════════════════════════════════════════════
   OPEN / CLOSE
   ═══════════════════════════════════════════════════════════════════ */
function openScanModal(onSuccess, opts) {
    _smOnSuccess      = onSuccess || null;
    _smOpts           = opts || {};
    _smDocType        = _smOpts.docType || '';
    _smParsed         = null;
    _smActive         = true;
    _smProcessing     = false;
    _smRetryCount     = 0;
    _smStreamDetected = false;
    _smFirstInputTime = 0;
    _smLastInputTime  = 0;
    _clearAllTimers();
    _smResetCameraUi();
    _smResetPhotoUi();
    _smResetCccdPhotoUi();

    // ── Reset UI ────────────────────────────────────────────────
    _smSetIcon(
        _smEl('sm-icon-wrap'), _smEl('sm-icon-svg'),
        'linear-gradient(135deg, #eff6ff, #dbeafe)', '#3b82f6',
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
      + '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
      + '<line x1="7" y1="12" x2="17" y2="12"/>'
    );

    const isPhoto = (_smOpts.mode === 'photo' || _smDocType === 'passport' || _smDocType === 'visa');

    _smEl('sm-title').textContent = isPhoto
        ? (_smDocType === 'passport' ? 'Quét Passport / Hộ chiếu' : 'Quét Visa email (China)')
        : 'Quét CCCD / Căn cước';

    _smEl('sm-sub').textContent = isPhoto
        ? (_smDocType === 'passport' ? 'Chụp hoặc tải ảnh trang thông tin hộ chiếu để nhận dạng' : 'Chụp hoặc tải ảnh xác nhận Visa China để nhận dạng')
        : 'Đọc mã QR từ thẻ CCCD gắn chip hoặc giấy tờ';

    const tabContainer = _smEl('sm-tabs');
    if (tabContainer) {
        tabContainer.style.display = 'flex';
    }

    _smSetConfirmEnabled(false);
    _smUpdateSessionBadge();

    // ── Clear & show input ──────────────────────────────────────
    const input = _smEl('sm-test-input');
    if (input) { input.value = ''; input.readOnly = false; }

    const modal = _smEl('scanModal');
    if (modal) {
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
    }

    // Switch to initial tab
    if (_smOpts.mode === 'cccd-photo') {
        scanModalSwitchTab('cccd-photo');
    } else if (isPhoto) {
        scanModalSwitchTab('photo');
    } else {
        scanModalSwitchTab('qr');
    }
}

function scanModalClose() {
    _smStopCamera();
    _smDisarmScanner();
    _clearAllTimers();
    _smActive       = false;
    _smProcessing   = false;
    _smParsed       = null;
    _smOnSuccess    = null;

    // Cleanup photo paste listeners
    if (_smCccdPasteActive) {
        _smCccdPasteActive = false;
        document.removeEventListener('paste', _smPasteHandler);
    }
    if (_smPhotoPasteActive) {
        _smPhotoPasteActive = false;
        document.removeEventListener('paste', _smPasteHandler);
    }

    const modal = _smEl('scanModal');
    if (modal) {
        // Blur any focused element inside modal before hiding to avoid aria-hidden warning
        if (document.activeElement && modal.contains(document.activeElement)) {
            document.activeElement.blur();
        }
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
}

function scanModalBack() {
    const tabPhoto = _smEl('sm-tab-photo');
    const isPhotoTab = tabPhoto && tabPhoto.classList.contains('active');

    if (isPhotoTab) {
        _smResetPhotoUi();
        _smRenderPhotoPlaceholder();
        _smSetConfirmEnabled(false);
    } else {
        _smStopCamera();
        _smReset();
        _smToggleScannerPanel(true);
        _smUpdateScannerStatus('scanning');
        _smSetConfirmEnabled(false);
        _smEl('sm-info-panel').innerHTML = '';
        _smRenderPlaceholder();

        const input = _smEl('sm-test-input');
        if (input) { input.value = ''; input.readOnly = false; }

        _armScanner();
        _smFocusInput();
        setTimeout(_smFocusInput, 80);
    }
}

/* ═══════════════════════════════════════════════════════════════════
   FOCUS MANAGEMENT
   ═══════════════════════════════════════════════════════════════════
   USB HID scanner chars ONLY go to the focused element.
   We aggressively keep sm-test-input focused.
   ═══════════════════════════════════════════════════════════════════ */
function _smFocusInput() {
    if (!_smActive || _smCameraActive) return;
    const tabQr = _smEl('sm-tab-qr');
    const isQrActive = tabQr && tabQr.classList.contains('active');
    if (!isQrActive) return;
    const input = _smEl('sm-test-input');
    if (!input) return;
    if (document.activeElement !== input) {
        input.focus({ preventScroll: true });
    }
}

function _smStartFocusGuard() {
    _smStopFocusGuard();

    _smFocusGuardId = setInterval(() => {
        if (!_smActive) { _smStopFocusGuard(); return; }

        const input = _smEl('sm-test-input');
        if (!input) return;

        const indicator = _smEl('sm-focus-indicator');

        if (document.activeElement === input) {
            if (indicator) indicator.classList.remove('sm-focus-lost');
        } else {
            if (indicator) indicator.classList.add('sm-focus-lost');
            // Re-capture only when modal is visible and not processing
            const modal = _smEl('scanModal');
            const tabQr = _smEl('sm-tab-qr');
            const isQrActive = tabQr && tabQr.classList.contains('active');
            if (modal && modal.classList.contains('show') && !_smProcessing && !_smCameraActive && isQrActive) {
                input.focus({ preventScroll: true });
            }
        }
    }, SM_FOCUS_GUARD_MS);

    // Also re-focus on modal body click
    const modal = _smEl('scanModal');
    if (modal) modal.addEventListener('click', _smOnModalClick);
}

function _smOnModalClick(e) {
    if (!_smActive || _smProcessing || _smCameraActive) return;
    if (e.target.closest('button') || e.target.closest('a') || e.target.closest('.sm-cccd-dropzone') || e.target.closest('input')) return;
    _smFocusInput();
}

function _smStopFocusGuard() {
    if (_smFocusGuardId) { clearInterval(_smFocusGuardId); _smFocusGuardId = null; }
    const modal = _smEl('scanModal');
    if (modal) modal.removeEventListener('click', _smOnModalClick);
}

/* ═══════════════════════════════════════════════════════════════════
   ARMING / DISARMING
   ═══════════════════════════════════════════════════════════════════ */
function _armScanner() {
    _smDisarmScanner();           // clean slate
    _smActive         = true;
    _smProcessing     = false;
    _smStreamDetected = false;
    _smFirstInputTime = 0;
    _smLastInputTime  = 0;

    clearTimeout(_smTimeoutTimer);
    _smTimeoutTimer = setTimeout(_smOnTimeout, SM_TIMEOUT_MS);

    // ── Primary: Enter key (scanner terminator) ─────────────────
    document.addEventListener('keydown', _smEnterHandler);

    // ── Primary: input event (source of truth for characters) ───
    const input = _smEl('sm-test-input');
    if (input) input.addEventListener('input', _smInputHandler);

    // ── Backup: paste support ───────────────────────────────────
    document.addEventListener('paste', _smPasteHandler);

    // ── Start focus guard ───────────────────────────────────────
    _smStartFocusGuard();
}

function _smDisarmScanner() {
    _smActive         = false;
    _smStreamDetected = false;

    document.removeEventListener('keydown', _smEnterHandler);
    document.removeEventListener('paste',   _smPasteHandler);

    const input = _smEl('sm-test-input');
    if (input) input.removeEventListener('input', _smInputHandler);

    _smStopFocusGuard();
}

/* ═══════════════════════════════════════════════════════════════════
   ENTER HANDLER — Scanner terminator (PRIMARY trigger)
   ═══════════════════════════════════════════════════════════════════
   RAR-DTA RD23 V2 sends Enter (CR) after every scan.
   A short debounce (SM_DEBOUNCE_ENTER_MS) lets the last characters
   settle into input.value before we read it.
   ═══════════════════════════════════════════════════════════════════ */
function _smEnterHandler(e) {
    if (!_smActive || _smProcessing) return;

    if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();

        clearTimeout(_smTermTimer);
        // Small debounce so the last few chars land in input.value
        setTimeout(() => _smProcessNow('enter'), SM_DEBOUNCE_ENTER_MS);
        return;
    }

    if (e.key === 'Escape') {
        scanModalClose();
    }
}

/* ═══════════════════════════════════════════════════════════════════
   INPUT HANDLER — Single source of truth for character data
   ═══════════════════════════════════════════════════════════════════
   Every char the scanner sends ends up here via the browser's
   native keyboard → input handling.  No interception, no prevent-
   Default, no dead-key issues.

   Responsibilities:
     1. Detect scan speed (fast = scanner, slow = human)
     2. Update live preview
     3. Reset / set terminate timer (backup if Enter is missed)
   ═══════════════════════════════════════════════════════════════════ */
function _smInputHandler() {
    if (!_smActive || _smProcessing) return;

    const input = _smEl('sm-test-input');
    if (!input) return;

    const now = Date.now();
    const val = input.value;

    // ── First char in stream ────────────────────────────────────
    if (!_smFirstInputTime || val.length <= 1) {
        _smFirstInputTime = now;
        _smStreamDetected = false;
    }

    // ── Detect scanner speed ────────────────────────────────────
    if (_smLastInputTime > 0) {
        const gap = now - _smLastInputTime;
        if (gap < SM_SCANNER_SPEED_MS && val.length > 3) {
            _smStreamDetected = true;
        }
    }
    _smLastInputTime = now;

    // ── Live preview ────────────────────────────────────────────
    _updateLivePreview(val);

    // ── Receiving indicator ─────────────────────────────────────
    if (val.length > 0) {
        _smUpdateScannerStatus('scanning');
        const txt = _smEl('sm-status-text');
        if (txt) txt.textContent = `Đang nhận… ${val.length} ký tự`;
    }

    // ── Terminate timer (BACKUP — Enter is primary) ─────────────
    clearTimeout(_smTermTimer);
    _smTermTimer = setTimeout(() => {
        const cur = _smSanitizeRaw(input.value || '');
        if (cur.length >= SM_MIN_LEN) {
            console.log('[SCAN] Terminate timer → auto-process', cur.length, 'chars');
            _smProcessNow('timeout');
        }
    }, SM_TERMINATE_MS);
}

/* ═══════════════════════════════════════════════════════════════════
   PASTE HANDLER — manual testing & some scanner modes
   ═══════════════════════════════════════════════════════════════════ */
function _smPasteHandler(e) {
    // CCCD photo paste — independent of scanner armed state (_smActive)
    if (_smCccdPasteActive && !_smProcessing) {
        const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
        if (items) {
            for (let i = 0; i < items.length; i++) {
                if (items[i].type.indexOf('image') !== -1) {
                    const blob = items[i].getAsFile();
                    if (blob) {
                        e.preventDefault();
                        if (!_smCccdImages.front) {
                            _smSetCccdImage('front', blob);
                        } else {
                            _smSetCccdImage('back', blob);
                        }
                        return;
                    }
                }
            }
        }
        return;
    }

    if (_smPhotoPasteActive && !_smProcessing) {
        const items = (e.clipboardData || e.originalEvent?.clipboardData)?.items;
        if (items) {
            for (let i = 0; i < items.length; i++) {
                if (items[i].type.indexOf('image') !== -1) {
                    const blob = items[i].getAsFile();
                    if (blob) {
                        e.preventDefault();
                        _smSetPhotoImage(blob, 'pasted_document.jpg');
                        return;
                    }
                }
            }
        }
        return;
    }

    if (!_smActive || _smProcessing) return;

    const input = _smEl('sm-test-input');
    if (!input || document.activeElement !== input) return;

    // Let the browser handle paste naturally — input event will fire.
    // For long pastes we also set a quick timeout to process.
    const text = (e.clipboardData || window.clipboardData)?.getData('text');
    if (text && text.length >= SM_MIN_LEN) {
        clearTimeout(_smTermTimer);
        setTimeout(() => _smProcessNow('paste'), SM_DEBOUNCE_ENTER_MS);
    }
}

/* ═══════════════════════════════════════════════════════════════════
   PROCESS NOW — main processing entry point
   ═══════════════════════════════════════════════════════════════════ */
function _smProcessNow(trigger) {
    if (!_smActive || _smProcessing) return;

    clearTimeout(_smTermTimer);

    const input  = _smEl('sm-test-input');
    const raw    = _smSanitizeRaw(input ? input.value : '');

    console.log(`[SCAN] _smProcessNow (${trigger}), ${raw.length} chars`);

    // ── Enough data → process ───────────────────────────────────
    if (raw.length >= SM_MIN_LEN) {
        _smProcessScan(raw);
        return;
    }

    // ── Too short but non-empty → retry logic ───────────────────
    if (raw.length > 0) {
        if (_smRetryCount < SM_MAX_RETRY) {
            _smRetryCount++;
            console.log(`[SCAN] Short (${raw.length}), retry ${_smRetryCount}/${SM_MAX_RETRY}`);
            // Keep input value; give scanner time to finish
            clearTimeout(_smTermTimer);
            _smTermTimer = setTimeout(() => {
                const retry = _smSanitizeRaw(input?.value || '');
                if (retry.length >= SM_MIN_LEN) {
                    _smProcessScan(retry);
                } else {
                    _toastWarn('Chuỗi QR quá ngắn. Vui lòng quét lại.');
                    _smSessionStats.fail++;
                    _smUpdateSessionBadge();
                    if (input) input.value = '';
                    _smRetryCount = 0;
                    _smFocusInput();
                }
            }, SM_TERMINATE_MS * 2);
            return;
        }
        // Retries exhausted
        _toastWarn('Dữ liệu quá ngắn sau nhiều lần thử. Vui lòng quét lại.');
        _smSessionStats.fail++;
        _smUpdateSessionBadge();
        if (input) input.value = '';
        _smRetryCount = 0;
        _smFocusInput();
        return;
    }

    // ── Empty → just keep focus ─────────────────────────────────
    _smFocusInput();
}

function _toastWarn(msg) {
    if (typeof pmsToast === 'function') pmsToast(msg, false);
}

/* Manual submit via button */
function scanModalTestInput() {
    if (!_smActive) return;
    _smProcessNow('manual');
}

/* ═══════════════════════════════════════════════════════════════════
   CAMERA SCAN
   ═══════════════════════════════════════════════════════════════════ */
function _smSetCameraStatus(message, state) {
    const el = _smEl('sm-camera-status');
    if (!el) return;
    el.textContent = message || '';
    el.classList.remove('error', 'ok');
    if (state) el.classList.add(state);
}

function _smResetCameraUi() {
    _smLastCameraText = '';
    _smCameraActive = false;
    _smSetCameraStatus('', '');

    const startBtn = _smEl('sm-camera-start-btn');
    const stopBtn = _smEl('sm-camera-stop-btn');
    const viewport = _smEl('sm-scanner-viewport');
    const video = _smEl('sm-camera-video');

    if (startBtn) startBtn.hidden = false;
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.hidden = true;
    if (viewport) viewport.classList.remove('camera-active');
    if (video) video.srcObject = null;
}

function _smStopCamera() {
    if (_smCameraRaf) {
        cancelAnimationFrame(_smCameraRaf);
        _smCameraRaf = null;
    }

    if (_smCameraStream) {
        _smCameraStream.getTracks().forEach(track => track.stop());
        _smCameraStream = null;
    }

    _smCameraActive = false;

    const startBtn = _smEl('sm-camera-start-btn');
    const stopBtn = _smEl('sm-camera-stop-btn');
    const viewport = _smEl('sm-scanner-viewport');
    const video = _smEl('sm-camera-video');

    if (startBtn) startBtn.hidden = false;
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.hidden = true;
    if (viewport) viewport.classList.remove('camera-active');
    if (video) video.srcObject = null;
}

function scanModalStopCamera() {
    _smStopCamera();
    _smSetCameraStatus('Đã tắt camera. Bạn vẫn có thể quét bằng máy quét hoặc nhập tay.', '');
    if (_smActive && !_smProcessing) _smFocusInput();
}

async function scanModalStartCamera() {
    if (!_smActive || _smProcessing || _smCameraActive) return;

    if (!window.isSecureContext) {
        _smSetCameraStatus('Camera chỉ hoạt động trên HTTPS hoặc localhost.', 'error');
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        _smSetCameraStatus('Trình duyệt này chưa hỗ trợ truy cập camera.', 'error');
        return;
    }
    if (typeof window.BarcodeDetector !== 'function' && typeof window.jsQR !== 'function') {
        _smSetCameraStatus('Trình duyệt chưa hỗ trợ đọc QR bằng camera. Vui lòng dùng máy quét hoặc nhập tay.', 'error');
        return;
    }

    const video = _smEl('sm-camera-video');
    if (!video) return;

    const startBtn = _smEl('sm-camera-start-btn');
    if (startBtn) startBtn.disabled = true;
    _smSetCameraStatus('Đang mở camera…', '');

    try {
        _smStopFocusGuard();
        _smCameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: 'environment' } },
            audio: false,
        });

        video.srcObject = _smCameraStream;
        await video.play();

        _smCameraActive = true;
        _smLastCameraText = '';
        _smUpdateCameraUi(true);
        _smSetCameraStatus('Đưa mã QR CCCD vào khung camera.', 'ok');
        _smStartCameraDecodeLoop();
    } catch (err) {
        _smStopCamera();
        _armScanner();
        _smFocusInput();
        _smSetCameraStatus(_smCameraErrorMessage(err), 'error');
    }
}

function _smUpdateCameraUi(active) {
    const startBtn = _smEl('sm-camera-start-btn');
    const stopBtn = _smEl('sm-camera-stop-btn');
    const viewport = _smEl('sm-scanner-viewport');

    if (startBtn) {
        startBtn.hidden = active;
        startBtn.disabled = false;
    }
    if (stopBtn) stopBtn.hidden = !active;
    if (viewport) viewport.classList.toggle('camera-active', active);
}

function _smCameraErrorMessage(err) {
    const name = err && err.name ? err.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'Bạn chưa cấp quyền camera. Hãy cấp quyền rồi thử lại.';
    if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'Không tìm thấy camera phù hợp trên thiết bị.';
    if (name === 'NotReadableError') return 'Camera đang bận hoặc không thể mở. Hãy đóng ứng dụng khác đang dùng camera.';
    return 'Không mở được camera. Bạn vẫn có thể dùng máy quét hoặc nhập tay.';
}

function _smStartCameraDecodeLoop() {
    if (typeof window.BarcodeDetector === 'function' && !_smBarcodeDetector) {
        try { _smBarcodeDetector = new window.BarcodeDetector({ formats: ['qr_code'] }); }
        catch (_) { _smBarcodeDetector = null; }
    }

    if (!_smBarcodeDetector && typeof window.jsQR !== 'function') {
        _smStopCamera();
        _armScanner();
        _smFocusInput();
        _smSetCameraStatus('Trình duyệt chưa hỗ trợ đọc QR bằng camera. Vui lòng dùng máy quét hoặc nhập tay.', 'error');
        return;
    }

    const loop = async () => {
        if (!_smCameraActive || _smProcessing) return;

        const decoded = await _smDecodeCameraFrame();
        const raw = _smSanitizeRaw(decoded || '');
        if (raw.length >= SM_MIN_LEN && raw !== _smLastCameraText) {
            _smLastCameraText = raw;
            _smSetCameraStatus('Đã đọc QR, đang xử lý…', 'ok');
            _smStopCamera();
            _smProcessScan(raw);
            return;
        }

        _smCameraRaf = requestAnimationFrame(loop);
    };

    _smCameraRaf = requestAnimationFrame(loop);
}

async function _smDecodeCameraFrame() {
    const video = _smEl('sm-camera-video');
    if (!video || video.readyState < 2) return '';

    if (_smBarcodeDetector) {
        try {
            const codes = await _smBarcodeDetector.detect(video);
            if (codes && codes.length) return codes[0].rawValue || '';
        } catch (_) {}
    }

    if (typeof window.jsQR === 'function') {
        return _smDecodeWithJsQr(video);
    }

    return '';
}

function _smDecodeWithJsQr(video) {
    const canvas = _smEl('sm-camera-canvas');
    if (!canvas || !video.videoWidth || !video.videoHeight) return '';

    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return '';

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = window.jsQR(imageData.data, imageData.width, imageData.height);
    return code && code.data ? code.data : '';
}

/* ═══════════════════════════════════════════════════════════════════
   PROCESS SCAN → API  +  LOCAL FALLBACK
   ═══════════════════════════════════════════════════════════════════ */
function _smProcessScan(raw) {
    _smStopCamera();
    _smDisarmScanner();
    clearTimeout(_smTimeoutTimer);
    _smProcessing = true;
    _smRetryCount = 0;

    const input = _smEl('sm-test-input');
    if (input) input.value = '';

    console.log('[SCAN] Processing', raw.length, 'chars');

    // ── Show loading state ──────────────────────────────────────
    _smUpdateScannerStatus('scanning');
    const stxt = _smEl('sm-status-text');
    if (stxt) stxt.textContent = 'Đang xử lý…';
    _smEl('sm-info-panel').innerHTML = `
      <div class="sm-info-empty">
        <div class="sm-info-empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7V5a2 2 0 0 1 2-2h2"/>
            <path d="M17 3h2a2 2 0 0 1 2 2v2"/>
            <path d="M21 17v2a2 2 0 0 1-2 2h-2"/>
            <path d="M7 21H5a2 2 0 0 1-2-2v-2"/>
            <line x1="7" y1="12" x2="17" y2="12"/>
          </svg>
        </div>
        <span class="sm-info-empty-text">Đang xử lý dữ liệu…</span>
      </div>`;

    // ── Call backend API ─────────────────────────────────────────
    pmsApi('/api/pms/scan/cccd?raw=' + encodeURIComponent(raw))
        .then(r => {
            _smProcessing = false;
            if (r.success && r.data) {
                _smShowResult(_backendToLocal(r.data));
            } else {
                _smShowResult(_smLocalFallback(raw));
            }
        })
        .catch(() => {
            _smProcessing = false;
            let parsed;
            try   { parsed = _smLocalFallback(raw); }
            catch { parsed = { is_valid: false, error: 'Lỗi parse', raw_cleaned: raw }; }
            _smShowResult(parsed);
        });
}

/* Local fallback parser */
function _smLocalFallback(raw) {
    if (typeof pmsParseScanCCCD === 'function') return pmsParseScanCCCD(raw);
    return { is_valid: false, error: 'Parser không khả dụng', raw_cleaned: raw };
}

/* Map backend fields → local shape */
function _backendToLocal(data) {
    return {
        is_valid:      data.is_valid,
        error:         data.error || '',
        raw_cleaned:   data.raw_cleaned || '',
        card_type:     data.card_type || '',
        address_mode:  data.address_mode || '',
        id_number:     data.id_number || '',
        old_id:        data.old_id || '',
        cccd:          data.id_number || data.old_id || '',
        name:          typeof pmsTitleCase === 'function'
                           ? pmsTitleCase(data.name || '')
                           : (data.name || ''),
        dob:           data.dob || '',
        gender:        data.gender || '',
        address: {
            raw:       data.address?.raw || '',
            detail:    data.address?.detail || '',
            ward:      data.address?.ward || '',
            district:  data.address?.district || '',
            province:  data.address?.province || '',
        },
        issue_date:    data.issue_date || '',
        expiry_date:   data.expiry_date || '',
        expiry_status: data.expiry_status || 'unknown',
        age:           data.age || null,
    };
}

/* ═══════════════════════════════════════════════════════════════════
   TIMEOUT
   ═══════════════════════════════════════════════════════════════════ */
function _smOnTimeout() {
    if (!_smActive) return;

    // Last chance: check input for data before timing out
    const input = _smEl('sm-test-input');
    const val   = _smSanitizeRaw(input?.value || '');
    if (val.length >= SM_MIN_LEN) { _smProcessScan(val); return; }

    _smUpdateScannerStatus('error');
    _smToggleScannerPanel(true);
    _smRenderError({ error: 'Hết thời gian chờ (90 s). Vui lòng thử lại.', raw_cleaned: '' });
    _smSetConfirmEnabled(false);
    _smSessionStats.fail++;
    _smUpdateSessionBadge();

    setTimeout(() => { if (_smActive) _armScanner(); }, 2000);
}

/* ═══════════════════════════════════════════════════════════════════
   RESET / TIMERS
   ═══════════════════════════════════════════════════════════════════ */
function _smReset() {
    _clearAllTimers();
    _smActive         = true;
    _smProcessing     = false;
    _smStreamDetected = false;
    _smRetryCount     = 0;
    _smFirstInputTime = 0;
    _smLastInputTime  = 0;
}

function _clearAllTimers() {
    clearTimeout(_smTermTimer);    _smTermTimer    = null;
    clearTimeout(_smTimeoutTimer); _smTimeoutTimer = null;
}

/* ═══════════════════════════════════════════════════════════════════
   RESULT FLOW
   ═══════════════════════════════════════════════════════════════════ */
function _smShowResult(parsed) {
    _smParsed = parsed.is_valid ? parsed : _smParsed;

    if (parsed.is_valid) {
        _smToggleScannerPanel(false);
        _smUpdateScannerStatus('done');
        _smRenderInfo(parsed);
        _smSetConfirmEnabled(true, parsed);
        _smSessionStats.ok++;
        _smUpdateSessionBadge();

        // Auto-confirm
        if (_smEl('sm-auto-confirm')?.checked) {
            setTimeout(() => {
                const btn = _smEl('sm-confirm-btn');
                if (btn && !btn.disabled && btn.onclick) btn.click();
            }, 300);
        }
    } else {
        _smToggleScannerPanel(true);
        _smUpdateScannerStatus('error');
        _smRenderError(parsed);
        _smSetConfirmEnabled(false);
        _smSessionStats.fail++;
        _smUpdateSessionBadge();

        // Auto re-arm after error → user can scan again immediately
        setTimeout(() => {
            const modal = _smEl('scanModal');
            if (modal && modal.classList.contains('show')) {
                _smActive = true;
                _armScanner();
                _smFocusInput();
            }
        }, SM_REARM_DELAY_MS);
    }
}

/* ═══════════════════════════════════════════════════════════════════
   UI HELPERS
   ═══════════════════════════════════════════════════════════════════ */
function _smSetIcon(iconWrap, iconSvg, bg, color, svgPath) {
    if (iconWrap) { iconWrap.style.background = bg; iconWrap.style.color = color; }
    if (iconSvg)  { iconSvg.innerHTML = svgPath; }
}

function _smToggleScannerPanel(show) {
    const panel = _smEl('sm-scanner-panel');
    if (panel) panel.classList.toggle('sm-hidden', !show);
}

function _smUpdateScannerStatus(state) {
    const vp    = _smEl('sm-scanner-viewport');
    const label = _smEl('sm-status-text');
    if (!vp) return;

    vp.classList.remove('scanning', 'done', 'error');

    const msgs = {
        scanning: 'Đang chờ quét…',
        done:     'Đã quét xong ✓',
        error:    'Quét thất bại ✗',
    };
    if (['scanning', 'done', 'error'].includes(state)) vp.classList.add(state);
    if (label) label.textContent = msgs[state] || 'Đang chờ quét…';
}

function _smRenderPlaceholder() {
    _smEl('sm-info-panel').innerHTML = `
      <div class="sm-info-empty">
        <div class="sm-info-empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7V5a2 2 0 0 1 2-2h2"/>
            <path d="M17 3h2a2 2 0 0 1 2 2v2"/>
            <path d="M21 17v2a2 2 0 0 1-2 2h-2"/>
            <path d="M7 21H5a2 2 0 0 1-2-2v-2"/>
            <line x1="7" y1="12" x2="17" y2="12"/>
          </svg>
        </div>
        <span class="sm-info-empty-text">Đưa mã QR code CCCD<br>vào vùng quét</span>
      </div>`;
}

function _smSetConfirmEnabled(enabled, parsed) {
    const btn = _smEl('sm-confirm-btn');
    if (!btn) return;
    btn.disabled = !enabled;

    const tabCccdPhoto = _smEl('sm-tab-cccd-photo');
    const tabPhoto = _smEl('sm-tab-photo');
    const isCccdPhotoActive = tabCccdPhoto && tabCccdPhoto.classList.contains('active');

    if (isCccdPhotoActive) {
        if (!parsed || !parsed.is_valid) {
            btn.textContent = 'Nhận diện ảnh CCCD';
            btn.disabled = !_smCccdImages.front;
            btn.onclick = _smCccdImages.front ? () => _smSubmitCccdPhoto() : null;
        } else {
            btn.textContent = 'Xác nhận & điền form';
            btn.onclick = () => {
                if (_smOpts && typeof _smOpts.onImages === 'function') {
                    _smOpts.onImages({
                        cccd_front: _smCccdImages.front,
                        cccd_back: _smCccdImages.back
                    });
                }
                if (_smOnSuccess) _smOnSuccess(parsed);
                scanModalClose();
            };
        }
    } else if (tabPhoto && tabPhoto.classList.contains('active')) {
        if (!parsed || !parsed.is_valid) {
            btn.textContent = 'Nhận diện ảnh Passport/Visa';
            btn.disabled = !_smPhotoFile;
            btn.onclick = _smPhotoFile ? () => _smSubmitPhoto(_smPhotoFile.blob, _smPhotoFile.filename) : null;
        } else {
            btn.textContent = 'Xác nhận & điền form';
            btn.onclick = () => {
                if (_smOnSuccess) _smOnSuccess(parsed);
                if (_smOpts && typeof _smOpts.onImages === 'function' && _smPhotoFile) {
                    const imgs = {};
                    imgs[_smDocType] = _smPhotoFile.blob;
                    console.log('[SCAN] Stashing photo for upload:', _smDocType, 'size:', _smPhotoFile.blob.size);
                    _smOpts.onImages(imgs);
                } else {
                    console.warn('[SCAN] No onImages handler or photo file', { hasHandler: !!(_smOpts && _smOpts.onImages), hasFile: !!_smPhotoFile });
                }
                scanModalClose();
            };
        }
    } else {
        btn.textContent = 'Xác nhận & điền form';
        btn.onclick = enabled && parsed
            ? () => {
                if (_smOnSuccess) _smOnSuccess(parsed);
                scanModalClose();
            }
            : null;
    }
}

function _updateLivePreview(text) {
    const el = _smEl('sm-live-preview');
    if (!el) return;
    const display = text.length > 80 ? text.slice(-80) : text;
    el.textContent = text ? `▶ ${display}` : '';
}

function _smUpdateSessionBadge() {
    const el = _smEl('sm-session-badge');
    if (!el) return;
    const { ok, fail } = _smSessionStats;
    if (ok === 0 && fail === 0) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.innerHTML = `<span class="sm-badge-ok">${ok}</span>`
                 + (fail > 0 ? `<span class="sm-badge-fail">${fail}</span>` : '');
}

/* ═══════════════════════════════════════════════════════════════════
   EXPIRY HELPERS
   ═══════════════════════════════════════════════════════════════════ */
function _expiryStatusAndDays(expiryDate) {
    const status = typeof pmsExpiryStatus === 'function' ? pmsExpiryStatus(expiryDate) : 'unknown';
    let daysLeft = null;

    if (expiryDate && status !== 'unknown' && status !== 'none') {
        try {
            const now   = new Date();
            const parts = expiryDate.match(/(\d{2})\/(\d{2})\/(\d{4})/);
            if (parts) {
                const exp  = new Date(parts[3], parts[2] - 1, parts[1]);
                const diff = Math.ceil((exp - now) / 86400000);
                if (!isNaN(diff)) daysLeft = diff;
            }
        } catch (_) {}
    }

    let daysText = '';
    if (daysLeft !== null) {
        if      (daysLeft < 0)    daysText = `Hết hạn ${Math.abs(daysLeft)} ngày`;
        else if (daysLeft === 0)  daysText = 'Hết hạn hôm nay';
        else                      daysText = `Còn ${daysLeft} ngày`;
    }
    return { status, daysText };
}

function _expiryStripClass(status) {
    if (status === 'valid' || status === 'ok' || status === 'permanent') return 'ok';
    if (status === 'expiring') return 'warn';
    if (status === 'expired')  return 'ex';
    return 'none';
}

function _expiryIcon(status) {
    const icons = {
        ok:   `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
        warn: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
        ex:   `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
        none: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    };
    return icons[status] || icons.none;
}

function _genderLabel(g) {
    if (!g) return { label: '—', cls: '' };
    const v = g.toLowerCase();
    if (v === 'nam' || v === 'male')                   return { label: 'Nam', cls: 'male' };
    if (v === 'nữ' || v === 'nu' || v === 'female')   return { label: 'Nữ', cls: 'female' };
    return { label: g, cls: '' };
}

/* ═══════════════════════════════════════════════════════════════════
   RESULT RENDERERS
   ═══════════════════════════════════════════════════════════════════ */
function _smRenderInfo(p) {
    const panel    = _smEl('sm-info-panel');
    const idVal    = p.id_number || p.old_id || p.cccd || '—';
    const idLabel  = p.card_type === 'CMND' ? 'CMND'
                   : p.card_type === 'CAN_CUOC_MOI' ? 'Căn cước mới' : 'CCCD';
    const idKind   = p.card_type === 'CAN_CUOC_MOI' ? 'Gắn chip'
                   : p.card_type === 'CMND'         ? 'CMND 9 số'
                   : p.card_type === 'CCCD_CU'      ? 'Căn cước (QR cũ)' : 'Căn cước';
    const gender   = _genderLabel(p.gender);
    const { status, daysText } = _expiryStatusAndDays(p.expiry_date);
    const stripCls = _expiryStripClass(status);
    const expiryIcon = _expiryIcon(status);

    const addrDetail   = p.address?.detail || '';
    const addrWard     = p.address?.ward || '';
    const addrDistrict = p.address?.district || '';
    const addrProvince = p.address?.province || '';
    const addrRaw      = (p.address?.raw || '').trim();

    const addrRows = [];
    if (addrProvince) addrRows.push({ k: 'Tỉnh / Thành phố', v: addrProvince });
    if (addrDistrict) addrRows.push({ k: 'Quận / Huyện', v: addrDistrict });
    if (addrWard || addrDetail) {
        const w = [addrWard, addrDetail].filter(Boolean).join(', ');
        if (w) addrRows.push({ k: 'Phường / Xã & địa chỉ', v: w });
    } else if (addrRaw && !addrProvince && !addrDistrict) {
        addrRows.push({ k: 'Địa chỉ', v: addrRaw });
    }

    const addrHtml = addrRows.length ? `
      <div class="sm-sheet-addr">
        <div class="sm-sheet-addr-h">Địa chỉ thường trú</div>
        <dl class="sm-sheet-dl sm-sheet-dl--addr">
          ${addrRows.map(r => `
          <div class="sm-sheet-row">
            <dt>${_esc(r.k)}</dt>
            <dd>${_esc(r.v)}</dd>
          </div>`).join('')}
        </dl>
      </div>` : '';

    const expiryNote = status === 'permanent' ? 'Không thời hạn' : (daysText || '');

    panel.innerHTML = `
      <div class="sm-result-sheet" role="region" aria-label="Thông tin trích từ CCCD">
        <header class="sm-sheet-top">
          <div class="sm-sheet-top-text">
            <span class="sm-sheet-k">Số định danh</span>
            <span class="sm-sheet-id">${_esc(idVal)}</span>
          </div>
          <div class="sm-sheet-top-meta">
            <span class="sm-sheet-pill">${_esc(idLabel)}</span>
            <span class="sm-sheet-pill sm-sheet-pill--muted">${_esc(idKind)}</span>
          </div>
          <div class="sm-sheet-check" title="Đã đọc được dữ liệu">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
        </header>

        <div class="sm-sheet-main">
          <div class="sm-sheet-name-block">
            <span class="sm-sheet-k">Họ và tên</span>
            <div class="sm-sheet-name-line">
              <span class="sm-sheet-name">${_esc(p.name || '—')}</span>
              <span class="sm-sheet-gender ${_esc(gender.cls)}">${_esc(gender.label)}</span>
            </div>
          </div>

          <dl class="sm-sheet-dl sm-sheet-dl--3">
            <div class="sm-sheet-row">
              <dt>Ngày sinh</dt>
              <dd>${_esc(p.dob || '—')}</dd>
            </div>
            <div class="sm-sheet-row">
              <dt>Giới tính</dt>
              <dd>${_esc(gender.label)}</dd>
            </div>
            <div class="sm-sheet-row">
              <dt>Tuổi</dt>
              <dd>${p.age != null ? _esc(String(p.age)) : '—'}</dd>
            </div>
          </dl>

          <div class="sm-sheet-expiry sm-sheet-expiry--${stripCls}">
            <div class="sm-sheet-expiry-inner">
              <span class="sm-sheet-k">Hạn giấy tờ</span>
              <span class="sm-sheet-expiry-date">${_esc(p.expiry_date || '—')}</span>
            </div>
            <div class="sm-sheet-expiry-side">
              ${expiryNote ? `<span class="sm-sheet-expiry-note">${_esc(expiryNote)}</span>` : ''}
              <span class="sm-sheet-expiry-ico">${expiryIcon}</span>
            </div>
          </div>

          ${addrHtml}
        </div>
      </div>
    `;
}

function _smRenderError(p) {
    const panel = _smEl('sm-info-panel');
    panel.innerHTML = `
      <div class="sm-error-block">
        <div class="sm-error-title">${_esc(p.error || 'Không nhận diện được dữ liệu')}</div>
      </div>`;
}

/* ═══════════════════════════════════════════════════════════════════
   ESCAPE HTML
   ═══════════════════════════════════════════════════════════════════ */
function _esc(s) {
    if (!s) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
// _esc is local to this file; pmsEscapeHtml is defined globally in pms_common.js

/* ═══════════════════════════════════════════════════════════════════
   EXPORT
   ═══════════════════════════════════════════════════════════════════ */
window.openScanModal        = openScanModal;
window.scanModalClose       = scanModalClose;
window.scanModalBack        = scanModalBack;
window.scanModalTestInput   = scanModalTestInput;
window.scanModalStartCamera = scanModalStartCamera;
window.scanModalStopCamera  = scanModalStopCamera;
window.scanModalSwitchTab   = scanModalSwitchTab;
window.scanModalFileSelected = scanModalFileSelected;


/* ═══════════════════════════════════════════════════════════════════
   PHOTO SCANNING IMPLEMENTATION
   ═══════════════════════════════════════════════════════════════════ */

function _smResetPhotoUi() {
    _smPhotoFile = null;
    const preview = _smEl('sm-photo-preview');
    const fileInput = _smEl('sm-photo-file');
    const placeholder = _smEl('sm-photo-placeholder');
    const removeBtn = _smEl('sm-photo-remove');

    if (preview) { preview.src = ''; preview.style.display = 'none'; }
    if (fileInput) fileInput.value = '';
    if (placeholder) placeholder.style.display = 'flex';
    if (removeBtn) removeBtn.style.display = 'none';

    _smUpdatePhotoStatus('Đang chờ dán ảnh hoặc chọn tệp…', '');
}

function _smUpdatePhotoStatus(text, state) {
    const statusBox = _smEl('sm-photo-status');
    const statusText = _smEl('sm-photo-status-text');
    if (!statusBox || !statusText) return;

    statusText.textContent = text || 'Đang chờ dán ảnh hoặc chọn tệp…';
    statusBox.classList.remove('processing', 'success', 'error');
    if (state) statusBox.classList.add(state);
}

function scanModalSwitchTab(tab) {
    const tabQr = _smEl('sm-tab-qr');
    const tabCccdPhoto = _smEl('sm-tab-cccd-photo');
    const tabPhoto = _smEl('sm-tab-photo');
    const panelQr = _smEl('sm-scanner-panel');
    const panelCccdPhoto = _smEl('sm-cccd-photo-panel');
    const panelPhoto = _smEl('sm-photo-panel');

    if (tabQr) tabQr.classList.remove('active');
    if (tabCccdPhoto) tabCccdPhoto.classList.remove('active');
    if (tabPhoto) tabPhoto.classList.remove('active');

    if (panelQr) panelQr.style.display = 'none';
    if (panelCccdPhoto) panelCccdPhoto.style.display = 'none';
    if (panelPhoto) panelPhoto.style.display = 'none';

    // Scanner input row only visible on QR tab
    const testRow = document.querySelector('.sm-test-row');
    if (testRow) testRow.style.display = 'none';

    _smStopCamera();
    _smDisarmScanner();
    if (_smCccdPasteActive) {
        _smCccdPasteActive = false;
        document.removeEventListener('paste', _smPasteHandler);
    }

    if (_smPhotoPasteActive) {
        _smPhotoPasteActive = false;
        document.removeEventListener('paste', _smPasteHandler);
    }

    if (tab === 'photo') {
        if (tabPhoto) tabPhoto.classList.add('active');
        if (panelPhoto) panelPhoto.style.display = 'flex';

        if (!_smDocType || (_smDocType !== 'passport' && _smDocType !== 'visa')) {
            const formIdTypeEl = document.getElementById('ci-id-type') || document.getElementById('guest-id-type');
            const formIdType = formIdTypeEl ? formIdTypeEl.value : '';
            if (formIdType === 'passport' || formIdType === 'visa') {
                _smDocType = formIdType;
            } else {
                _smDocType = 'passport';
            }
        }

        _smPhotoPasteActive = true;
        document.addEventListener('paste', _smPasteHandler);

        _smRenderPhotoPlaceholder();
        _smSetConfirmEnabled(_smPhotoFile !== null, _smParsed);
    } else if (tab === 'cccd-photo') {
        if (tabCccdPhoto) tabCccdPhoto.classList.add('active');
        if (panelCccdPhoto) panelCccdPhoto.style.display = 'flex';

        // Enable paste listener for cccd-photo (independent of scanner)
        _smCccdPasteActive = true;
        document.addEventListener('paste', _smPasteHandler);

        if (_smParsed && _smParsed.is_valid) {
            _smRenderInfo(_smParsed);
        } else {
            _smRenderCccdPhotoPlaceholder();
        }
        _smSetConfirmEnabled(_smCccdImages.front !== null, _smParsed);
    } else {
        if (tabQr) tabQr.classList.add('active');
        if (panelQr) panelQr.style.display = 'block';
        if (testRow) testRow.style.display = '';

        _smReset();
        _smToggleScannerPanel(true);
        _smUpdateScannerStatus('scanning');
        _smRenderPlaceholder();
        _smSetConfirmEnabled(false);

        const input = _smEl('sm-test-input');
        if (input) { input.value = ''; input.readOnly = false; }

        _armScanner();
        _smFocusInput();

        if (_smIsTouchDevice()) {
            setTimeout(scanModalStartCamera, 100);
        }
    }
}

function _smSetPhotoImage(fileBlob, filename) {
    if (!fileBlob) return;
    _smPhotoFile = { blob: fileBlob, filename: filename || 'document.jpg' };
    _smParsed = null;

    const preview = _smEl('sm-photo-preview');
    const placeholder = _smEl('sm-photo-placeholder');
    const removeBtn = _smEl('sm-photo-remove');

    if (preview) {
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
        };
        reader.readAsDataURL(fileBlob);
    }
    if (placeholder) placeholder.style.display = 'none';
    if (removeBtn) removeBtn.style.display = 'flex';

    _smRenderPhotoPlaceholder();
    _smSetConfirmEnabled(true, null);
}

function _smClearPhotoImage() {
    _smPhotoFile = null;
    _smParsed = null;

    const preview = _smEl('sm-photo-preview');
    const placeholder = _smEl('sm-photo-placeholder');
    const removeBtn = _smEl('sm-photo-remove');
    const fileInput = _smEl('sm-photo-file');

    if (preview) { preview.src = ''; preview.style.display = 'none'; }
    if (placeholder) placeholder.style.display = 'flex';
    if (removeBtn) removeBtn.style.display = 'none';
    if (fileInput) fileInput.value = '';

    _smRenderPhotoPlaceholder();
    _smSetConfirmEnabled(false, null);
}

function scanModalFileSelected(event) {
    const input = event.target;
    if (!input || !input.files || !input.files.length) return;

    const file = input.files[0];
    _smSetPhotoImage(file, file.name);
}

function _smSubmitPhoto(fileBlob, filename) {
    if (_smProcessing) return;
    _smProcessing = true;
    _smSetConfirmEnabled(false);

    _smUpdatePhotoStatus('Đang gửi và phân tích ảnh OCR…', 'processing');

    _smEl('sm-info-panel').innerHTML = `
      <div class="sm-info-empty">
        <div class="sm-info-empty-icon">
          <svg class="pms-addr-loading-spinner" style="border-width:2px;width:24px;height:24px;" viewBox="0 0 24 24"></svg>
        </div>
        <span class="sm-info-empty-text">Đang nhận diện ký tự OCR…</span>
      </div>`;

    const fd = new FormData();
    fd.append('image', fileBlob, filename);
    fd.append('doc_type', _smDocType);

    fetch('/api/pms/scan/photo', {
        method: 'POST',
        body: fd
    })
    .then(res => {
        if (!res.ok) {
            return res.json().then(err => { throw new Error(err.detail || 'Lỗi kết nối máy chủ'); });
        }
        return res.json();
    })
    .then(res => {
        _smProcessing = false;
        if (res.success && res.data) {
            _smParsed = res.data;
            _smUpdatePhotoStatus('Nhận diện thông tin thành công!', 'success');
            _smRenderPhotoInfo(res.data);
            _smSetConfirmEnabled(true, res.data);
            _smSessionStats.ok++;
            _smUpdateSessionBadge();
        } else {
            throw new Error(res.error || 'Không nhận diện được mã MRZ hoặc thông tin trên ảnh');
        }
    })
    .catch(err => {
        _smProcessing = false;
        _smUpdatePhotoStatus(err.message, 'error');
        _smEl('sm-info-panel').innerHTML = `
          <div class="sm-error-block">
            <div class="sm-error-title">${_esc(err.message)}</div>
          </div>`;
        _smSessionStats.fail++;
        _smUpdateSessionBadge();
    });
}

function _smRenderPhotoPlaceholder() {
    const title = _smDocType === 'passport' ? 'ảnh trang hộ chiếu' : 'ảnh xác nhận Visa';
    _smEl('sm-info-panel').innerHTML = `
      <div class="sm-info-empty">
        <div class="sm-info-empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
            <circle cx="8.5" cy="8.5" r="1.5"/>
            <polyline points="21 15 16 10 5 21"/>
          </svg>
        </div>
        <span class="sm-info-empty-text">Dán ảnh (Ctrl+V) hoặc chọn tệp<br>${title} để xử lý</span>
      </div>`;
}

function _smRenderPhotoInfo(p) {
    const panel    = _smEl('sm-info-panel');
    const idVal    = p.id_number || '—';
    const idLabel  = p.card_type === 'passport' ? 'Passport' : 'Visa email (China)';
    const idKind   = p.nationality || '—';
    const gender   = _genderLabel(p.gender);

    let stripCls = 'none';
    let expiryNote = '';
    let expiryIcon = _expiryIcon('none');

    if (p.expiry_date) {
        let displayExpiry = p.expiry_date;
        if (p.expiry_date.includes('-')) {
            const parts = p.expiry_date.split('-');
            if (parts.length === 3) {
                displayExpiry = `${parts[2]}/${parts[1]}/${parts[0]}`;
            }
        }
        const { status, daysText } = _expiryStatusAndDays(displayExpiry);
        stripCls = _expiryStripClass(status);
        expiryIcon = _expiryIcon(status);
        expiryNote = daysText || '';
    }

    let displayDob = p.dob || '—';
    if (p.dob && p.dob.includes('-')) {
        const parts = p.dob.split('-');
        if (parts.length === 3) {
            displayDob = `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
    }

    let ageVal = '—';
    if (p.dob) {
        try {
            const birth = new Date(p.dob);
            const ageDiff = Date.now() - birth.getTime();
            const ageDate = new Date(ageDiff);
            ageVal = String(Math.abs(ageDate.getUTCFullYear() - 1970));
        } catch (_) {}
    }

    panel.innerHTML = `
      <div class="sm-result-sheet" role="region" aria-label="Thông tin trích xuất từ ảnh">
        <header class="sm-sheet-top">
          <div class="sm-sheet-top-text">
            <span class="sm-sheet-k">Số hộ chiếu / Visa</span>
            <span class="sm-sheet-id">${_esc(idVal)}</span>
          </div>
          <div class="sm-sheet-top-meta">
            <span class="sm-sheet-pill">${_esc(idLabel)}</span>
            <span class="sm-sheet-pill sm-sheet-pill--muted">${_esc(idKind)}</span>
          </div>
          <div class="sm-sheet-check" title="Đã đọc được dữ liệu">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
        </header>

        <div class="sm-sheet-main">
          <div class="sm-sheet-name-block">
            <span class="sm-sheet-k">Họ và tên</span>
            <div class="sm-sheet-name-line">
              <span class="sm-sheet-name">${_esc(p.name || '—')}</span>
              <span class="sm-sheet-gender ${_esc(gender.cls)}">${_esc(gender.label)}</span>
            </div>
          </div>

          <dl class="sm-sheet-dl sm-sheet-dl--3">
            <div class="sm-sheet-row">
              <dt>Ngày sinh</dt>
              <dd>${_esc(displayDob)}</dd>
            </div>
            <div class="sm-sheet-row">
              <dt>Quốc tịch</dt>
              <dd>${_esc(p.nationality || '—')}</dd>
            </div>
            <div class="sm-sheet-row">
              <dt>Tuổi</dt>
              <dd>${_esc(ageVal)}</dd>
            </div>
          </dl>

          <div class="sm-sheet-expiry sm-sheet-expiry--${stripCls}">
            <div class="sm-sheet-expiry-inner">
              <span class="sm-sheet-k">Hạn giấy tờ</span>
              <span class="sm-sheet-expiry-date">${_esc(p.expiry_date || '—')}</span>
            </div>
            <div class="sm-sheet-expiry-side">
              ${expiryNote ? `<span class="sm-sheet-expiry-note">${_esc(expiryNote)}</span>` : ''}
              <span class="sm-sheet-expiry-ico">${expiryIcon}</span>
            </div>
          </div>
        </div>
      </div>
    `;
}

/* ═══════════════════════════════════════════════════════════════════
   CCCD TWO-SIDE PHOTO SCANNING IMPLEMENTATION
   ═══════════════════════════════════════════════════════════════════ */

function _smResetCccdPhotoUi() {
    _smCccdImages = { front: null, back: null };
    _smClearCccdSide('front');
    _smClearCccdSide('back');
}

function _smRenderCccdPhotoPlaceholder() {
    _smEl('sm-info-panel').innerHTML = `
      <div class="sm-info-empty">
        <div class="sm-info-empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
            <circle cx="8.5" cy="8.5" r="1.5"/>
            <polyline points="21 15 16 10 5 21"/>
          </svg>
        </div>
        <span class="sm-info-empty-text">Dán ảnh (Ctrl+V) hoặc Chọn tệp<br>Mặt trước và mặt sau CCCD</span>
      </div>`;
}

function _smCccdFileSelected(event, side) {
    const input = event.target;
    if (!input || !input.files || !input.files.length) return;
    const file = input.files[0];
    _smSetCccdImage(side, file);
}

function _smSetCccdImage(side, fileOrBlob) {
    if (!fileOrBlob) return;
    _smCccdImages[side] = fileOrBlob;
    _smParsed = null;
    _smRenderCccdPhotoPlaceholder();

    const preview = _smEl(`sm-cccd-preview-${side}`);
    const placeholder = _smEl(`sm-cccd-placeholder-${side}`);
    const removeBtn = _smEl(`sm-cccd-remove-${side}`);

    if (preview) {
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
        };
        reader.readAsDataURL(fileOrBlob);
    }
    if (placeholder) placeholder.style.display = 'none';
    if (removeBtn) removeBtn.style.display = 'flex';

    _smSetConfirmEnabled(_smCccdImages.front !== null, _smParsed);
}

function _smClearCccdSide(side) {
    _smCccdImages[side] = null;
    _smParsed = null;
    _smRenderCccdPhotoPlaceholder();

    const preview = _smEl(`sm-cccd-preview-${side}`);
    const placeholder = _smEl(`sm-cccd-placeholder-${side}`);
    const removeBtn = _smEl(`sm-cccd-remove-${side}`);
    const fileInput = _smEl(`sm-cccd-file-${side}`);

    if (preview) { preview.src = ''; preview.style.display = 'none'; }
    if (placeholder) placeholder.style.display = 'flex';
    if (removeBtn) removeBtn.style.display = 'none';
    if (fileInput) fileInput.value = '';

    _smSetConfirmEnabled(_smCccdImages.front !== null, _smParsed);
}

function _smSetupCccdDropzones() {
    ['front', 'back'].forEach(side => {
        const zone = _smEl(`sm-cccd-dropzone-${side}`);
        if (!zone) return;

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.add('dragover');
        });

        zone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('dragover');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('dragover');

            const files = e.dataTransfer?.files;
            if (files && files.length) {
                const file = files[0];
                if (file.type.startsWith('image/')) {
                    _smSetCccdImage(side, file);
                }
            }
        });
    });
}

async function _smSubmitCccdPhoto() {
    if (_smProcessing) return;
    if (!_smCccdImages.front) {
        if (typeof pmsToast === 'function') {
            pmsToast('Vui lòng chọn hoặc dán ảnh mặt trước CCCD', false);
        } else {
            alert('Vui lòng chọn hoặc dán ảnh mặt trước CCCD');
        }
        return;
    }

    _smProcessing = true;
    _smSetConfirmEnabled(false);

    const infoPanel = _smEl('sm-info-panel');
    if (infoPanel) {
        infoPanel.innerHTML = `
          <div class="sm-info-empty">
            <div class="sm-info-empty-icon">
              <svg class="pms-addr-loading-spinner" style="border-width:2px;width:24px;height:24px;" viewBox="0 0 24 24"></svg>
            </div>
            <span class="sm-info-empty-text">Đang gửi và nhận dạng OCR…</span>
          </div>`;
    }

    const fd = new FormData();
    fd.append('front', _smCccdImages.front, 'cccd_front.jpg');
    if (_smCccdImages.back) {
        fd.append('back', _smCccdImages.back, 'cccd_back.jpg');
    }

    try {
        const res = await fetch('/api/pms/scan/cccd-photo', {
            method: 'POST',
            body: fd
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Lỗi kết nối máy chủ');
        }
        const data = await res.json();
        _smProcessing = false;

        if (data.success && data.data) {
            _smParsed = data.data;
            _smRenderInfo(_smParsed);
            _smSetConfirmEnabled(true, _smParsed);
            _smSessionStats.ok++;
            _smUpdateSessionBadge();
        } else {
            throw new Error(data.error || 'Không nhận diện được thông tin trên ảnh CCCD');
        }
    } catch (err) {
        _smProcessing = false;
        _smSetConfirmEnabled(true, null); // Allow retry
        _smSessionStats.fail++;
        _smUpdateSessionBadge();
        _smRenderError({ error: err.message });
    }
}

async function _smUploadGuestDoc(guestId, docType, blob) {
    const fd = new FormData();
    fd.append('file', blob, `${docType}.jpg`);
    fd.append('doc_type', docType);
    const r = await fetch(`/api/pms/crm/guests/${guestId}/documents`, {
        method: 'POST',
        body: fd
    });
    if (!r.ok) {
        let detail = r.statusText;
        try {
            const body = await r.json();
            detail = body.detail || body.error || detail;
        } catch (_) {}
        throw new Error(`Upload ${docType} failed (${r.status}): ${detail}`);
    }
    return r.json();
}

// Window bindings
window._smCccdFileSelected = _smCccdFileSelected;
window._smClearCccdSide    = _smClearCccdSide;
window._smClearPhotoImage  = _smClearPhotoImage;
window.uploadGuestDocument = _smUploadGuestDoc;

// Setup on runtime load
if (document.readyState === 'complete' || document.readyState === 'interactive') {
    _smSetupCccdDropzones();
} else {
    document.addEventListener('DOMContentLoaded', _smSetupCccdDropzones);
}
