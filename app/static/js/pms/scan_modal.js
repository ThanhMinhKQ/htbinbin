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
function openScanModal(onSuccess) {
    _smOnSuccess      = onSuccess || null;
    _smParsed         = null;
    _smActive         = true;
    _smProcessing     = false;
    _smRetryCount     = 0;
    _smStreamDetected = false;
    _smFirstInputTime = 0;
    _smLastInputTime  = 0;
    _clearAllTimers();
    _smResetCameraUi();

    // ── Reset UI ────────────────────────────────────────────────
    _smSetIcon(
        _smEl('sm-icon-wrap'), _smEl('sm-icon-svg'),
        'linear-gradient(135deg, #eff6ff, #dbeafe)', '#3b82f6',
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
      + '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
      + '<line x1="7" y1="12" x2="17" y2="12"/>'
    );
    _smEl('sm-title').textContent = 'Quét CCCD / Căn cước';
    _smEl('sm-sub').textContent   = 'Đọc mã QR từ thẻ CCCD gắn chip hoặc giấy tờ';

    _smToggleScannerPanel(true);
    _smUpdateScannerStatus('scanning');
    _smRenderPlaceholder();
    _smSetConfirmEnabled(false);
    _smUpdateSessionBadge();

    // ── Clear & show input ──────────────────────────────────────
    const input = _smEl('sm-test-input');
    if (input) { input.value = ''; input.readOnly = false; }

    const modal = _smEl('scanModal');
    if (modal) {
        modal.classList.add('show');
        modal.removeAttribute('aria-hidden');
    }

    // ── Arm scanner & aggressive focus ──────────────────────────
    _armScanner();
    _smFocusInput();
    setTimeout(_smFocusInput, 80);
    setTimeout(_smFocusInput, 200);
}

function scanModalClose() {
    _smStopCamera();
    _smDisarmScanner();
    _clearAllTimers();
    _smActive       = false;
    _smProcessing   = false;
    _smParsed       = null;
    _smOnSuccess    = null;

    const modal = _smEl('scanModal');
    if (modal) {
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
    }
}

function scanModalBack() {
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

/* ═══════════════════════════════════════════════════════════════════
   FOCUS MANAGEMENT
   ═══════════════════════════════════════════════════════════════════
   USB HID scanner chars ONLY go to the focused element.
   We aggressively keep sm-test-input focused.
   ═══════════════════════════════════════════════════════════════════ */
function _smFocusInput() {
    if (!_smActive || _smCameraActive) return;
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
            if (modal && modal.classList.contains('show') && !_smProcessing && !_smCameraActive) {
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
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'BUTTON' || tag === 'A') return; // let buttons work
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
    btn.onclick = enabled && parsed
        ? () => { if (_smOnSuccess) _smOnSuccess(parsed); scanModalClose(); }
        : null;
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
