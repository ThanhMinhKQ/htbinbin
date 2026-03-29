// static/js/pms/scan_modal.js
// CCCD QR Scan Modal Controller
'use strict';

/* ── State ──────────────────────────────────────────────────── */
let _smOnSuccess      = null;
let _smBuffer         = '';
let _smFlushTimer     = null;
let _smTimeoutTimer   = null;
let _smAutoStartTimer = null;
let _smParsed         = null;   // last valid parsed result

const _SM_MIN_LEN    = 10;
const _SM_TIMEOUT_MS = 45000;

/* ── Helpers ────────────────────────────────────────────────── */
function _smEl(id) { return document.getElementById(id); }

function _smSetIcon(iconWrap, iconSvg, bg, color, svgPath) {
    if (iconWrap) { iconWrap.style.background = bg; iconWrap.style.color = color; }
    if (iconSvg)  { iconSvg.innerHTML = svgPath; }
}

function _smToggleScannerPanel(show) {
    const panel = _smEl('sm-scanner-panel');
    if (!panel) return;
    if (show) {
        panel.classList.remove('sm-hidden');
    } else {
        panel.classList.add('sm-hidden');
    }
}

function _smUpdateScannerStatus(state) {
    const vp    = _smEl('sm-scanner-viewport');
    const label = _smEl('sm-status-text');
    if (!vp) return;

    vp.classList.remove('scanning', 'done', 'error');

    if (state === 'scanning') {
        vp.classList.add('scanning');
        if (label) label.textContent = 'Đang chờ quét…';
    } else if (state === 'done') {
        vp.classList.add('done');
        if (label) label.textContent = 'Đã quét xong';
    } else if (state === 'error') {
        vp.classList.add('error');
        if (label) label.textContent = 'Quét thất bại';
    } else {
        if (label) label.textContent = 'Đang chờ quét…';
    }
}

/* ── Open / Close ───────────────────────────────────────────── */
function openScanModal(onSuccess) {
    _smOnSuccess = onSuccess || null;
    _smParsed     = null;
    _smReset();

    _smSetIcon(
        _smEl('sm-icon-wrap'), _smEl('sm-icon-svg'),
        'linear-gradient(135deg, #eff6ff, #dbeafe)', '#3b82f6',
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><line x1="7" y1="12" x2="17" y2="12"/>'
    );
    _smEl('sm-title').textContent = 'Quét CCCD / Căn cước';
    _smEl('sm-sub').textContent   = 'Đọc mã QR từ thẻ CCCD gắn chip hoặc giấy tờ';

    _smToggleScannerPanel(true);
    _smUpdateScannerStatus('idle');
    _smRenderPlaceholder();
    _smSetConfirmEnabled(false);

    const modal = _smEl('scanModal');
    if (modal) {
        modal.classList.add('show');
        modal.removeAttribute('aria-hidden');
    }

    clearTimeout(_smAutoStartTimer);
    _smAutoStartTimer = setTimeout(() => scanModalStart(), 600);
}

function scanModalClose() {
    _smCleanup();
    _smEl('scanModal')?.classList.remove('show');
    _smOnSuccess = null;
    _smParsed    = null;
}

function scanModalBack() {
    _smReset();
    _smToggleScannerPanel(true);
    _smUpdateScannerStatus('idle');
    _smSetConfirmEnabled(false);
    _smEl('sm-info-panel').innerHTML = '';
    _smRenderPlaceholder();
}

/* ── Scanner ─────────────────────────────────────────────────── */
function scanModalStart() {
    _smBuffer = '';
    _smUpdateScannerStatus('scanning');

    clearTimeout(_smTimeoutTimer);
    _smTimeoutTimer = setTimeout(() => {
        _smUpdateScannerStatus('error');
        _smToggleScannerPanel(true);
        _smRenderError({
            error: 'Hết thời gian chờ (45s). Vui lòng quét lại.',
            raw_cleaned: ''
        });
    }, _SM_TIMEOUT_MS);

    clearListeners();
    window.addEventListener('keydown', _smKeyHandler, { capture: true });

    setTimeout(() => {
        const ti = _smEl('sm-test-input');
        if (ti) { ti.value = ''; ti.focus(); }
    }, 120);
}

function scanModalTestInput() {
    const input = _smEl('sm-test-input');
    if (!input) return;
    const raw = input.value.trim();
    if (!raw || raw.length < _SM_MIN_LEN) {
        typeof pmsToast === 'function' && pmsToast('Chuỗi QR quá ngắn. Vui lòng dán chuỗi đầy đủ.', false);
        return;
    }
    clearTimeout(_smTimeoutTimer);
    clearListeners();
    input.value = '';
    _processScan(raw);
}

/* ── Keyboard collector ─────────────────────────────────────── */
function _smKeyHandler(e) {
    const tag = e.target.tagName;
    const isFormInput = (tag === 'INPUT' || tag === 'TEXTAREA') && !e.target.closest('#scanModal');

    if (e.key === 'Escape') {
        e.preventDefault();
        scanModalClose();
        return;
    }
    if (e.key === 'Enter') {
        e.preventDefault();
        _smFlush();
        return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (!isFormInput || document.activeElement === document.body) {
            clearTimeout(_smFlushTimer);
            _smBuffer += e.key;
            _smFlushTimer = setTimeout(() => {
                _smBuffer = '';
                _updateLivePreview('');
            }, 600);
            _updateLivePreview(_smBuffer);
        }
    }
}

function _smFlush() {
    clearTimeout(_smFlushTimer);
    clearTimeout(_smTimeoutTimer);

    if (_smBuffer.length >= _SM_MIN_LEN) {
        const raw = _smBuffer;
        _smBuffer = '';
        _processScan(raw);
    } else {
        const input = document.activeElement;
        if (input && (input.tagName === 'INPUT' || input.tagName === 'TEXTAREA')) {
            const val = input.value.trim();
            if (val.length >= _SM_MIN_LEN) {
                _processScan(val);
                input.value = '';
            }
        }
    }
}

/* ── Parse & process ─────────────────────────────────────────── */
function _processScan(raw) {
    _smCleanup();

    pmsApi('/api/pms/scan/cccd?raw=' + encodeURIComponent(raw))
        .then(r => {
            if (r.success && r.data) {
                _showResult(_backendToLocal(r.data));
            } else {
                _showResult({ is_valid: false, error: r.data?.error || 'Parse thất bại', raw_cleaned: raw });
            }
        })
        .catch(() => {
            let parsed;
            try {
                parsed = pmsParseScanCCCD(raw);
            } catch (err) {
                parsed = { is_valid: false, error: 'Lỗi parse: ' + (err.message || 'Unknown'), raw_cleaned: raw };
            }
            _showResult(parsed);
        });
}

/* Map backend API fields → same shape as pmsParseScanCCCD */
function _backendToLocal(data) {
    return {
        is_valid:      data.is_valid,
        error:         data.error || '',
        raw_cleaned:   data.raw_cleaned || '',
        card_type:     data.card_type || '',
        id_number:     data.id_number || '',
        old_id:        data.old_id || '',
        cccd:          data.id_number || data.old_id || '',
        name:          pmsTitleCase(data.name || ''),
        dob:           data.dob || '',
        gender:        data.gender || '',
        address: {
            raw:      data.address?.raw || '',
            detail:   data.address?.detail || '',
            ward:     data.address?.ward || '',
            district: data.address?.district || '',
            province: data.address?.province || '',
        },
        issue_date:    data.issue_date || '',
        expiry_date:   data.expiry_date || '',
        expiry_status: data.expiry_status || 'unknown',
        age:           data.age || null,
    };
}

/* ── Render helpers ───────────────────────────────────────────── */
function _smRenderPlaceholder() {
    _smEl('sm-info-panel').innerHTML = `
      <div class="sm-info-empty">
        <div class="sm-info-empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
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
    btn.onclick = enabled && parsed ? () => {
        if (_smOnSuccess) _smOnSuccess(parsed);
        scanModalClose();
    } : null;
}

/* ── Expiry helpers ─────────────────────────────────────────── */
function _expiryStatusAndDays(expiryDate) {
    const status = typeof pmsExpiryStatus === 'function' ? pmsExpiryStatus(expiryDate) : 'unknown';
    let daysLeft = null;

    if (expiryDate && status !== 'unknown' && status !== 'none') {
        try {
            const now  = new Date();
            const parts = expiryDate.match(/(\d{2})\/(\d{2})\/(\d{4})/);
            if (parts) {
                const exp = new Date(parts[3], parts[2] - 1, parts[1]);
                const diff = Math.ceil((exp - now) / (1000 * 60 * 60 * 24));
                if (!isNaN(diff)) daysLeft = diff;
            }
        } catch (_) {}
    }

    let daysText = '';
    if (daysLeft !== null) {
        if (daysLeft < 0)       daysText = `Hết hạn ${Math.abs(daysLeft)} ngày`;
        else if (daysLeft === 0) daysText = 'Hết hạn hôm nay';
        else if (daysLeft <= 30) daysText = `Còn ${daysLeft} ngày`;
        else                    daysText = `Còn ${daysLeft} ngày`;
    }

    return { status, daysText };
}

function _expiryStripClass(status) {
    if (status === 'valid' || status === 'ok' || status === 'permanent') return 'ok';
    if (status === 'expiring') return 'warn';
    if (status === 'expired') return 'ex';
    return 'none';
}

function _expiryIcon(status) {
    if (status === 'valid' || status === 'ok' || status === 'permanent') {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
    }
    if (status === 'expiring') {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
    }
    if (status === 'expired') {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
}

function _genderLabel(g) {
    if (!g) return { label: '—', cls: '' };
    const v = g.toLowerCase();
    if (v === 'nam' || v === 'male')   return { label: 'Nam', cls: 'male' };
    if (v === 'nữ' || v === 'nu' || v === 'female') return { label: 'Nữ', cls: 'female' };
    return { label: g, cls: '' };
}

/* ── Main result renderer ───────────────────────────────────── */
function _showResult(parsed) {
    _smParsed = parsed.is_valid ? parsed : _smParsed;

    if (parsed.is_valid) {
        _smToggleScannerPanel(false);   // ← ẩn scanner
        _smUpdateScannerStatus('done');
        _smRenderInfo(parsed);
        _smSetConfirmEnabled(true, parsed);
    } else {
        _smToggleScannerPanel(true);
        _smUpdateScannerStatus('error');
        _smRenderError(parsed);
        _smSetConfirmEnabled(false);
    }
}

function _smRenderInfo(p) {
    const panel    = _smEl('sm-info-panel');
    const idVal    = p.id_number || p.old_id || p.cccd || '—';
    const idLabel  = p.card_type === 'CMND' ? 'CMND'
        : p.card_type === 'CAN_CUOC_MOI' ? 'Căn cước mới'
            : 'CCCD';
    const idKind   = p.card_type === 'CAN_CUOC_MOI' ? 'Gắn chip'
        : p.card_type === 'CMND' ? 'CMND 9 số'
            : p.card_type === 'CCCD_CU' ? 'Căn cước (QR cũ)' : 'Căn cước';
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

    const addrHtml = addrRows.length
        ? `
      <div class="sm-sheet-addr">
        <div class="sm-sheet-addr-h">Địa chỉ thường trú</div>
        <dl class="sm-sheet-dl sm-sheet-dl--addr">
          ${addrRows.map(r => `
          <div class="sm-sheet-row">
            <dt>${pmsEscapeHtml(r.k)}</dt>
            <dd>${pmsEscapeHtml(r.v)}</dd>
          </div>`).join('')}
        </dl>
      </div>`
        : '';

    const expiryNote = status === 'permanent'
        ? 'Không thời hạn'
        : (daysText || '');

    panel.innerHTML = `
      <div class="sm-result-sheet" role="region" aria-label="Thông tin trích từ CCCD">
        <header class="sm-sheet-top">
          <div class="sm-sheet-top-text">
            <span class="sm-sheet-k">Số định danh</span>
            <span class="sm-sheet-id">${pmsEscapeHtml(idVal)}</span>
          </div>
          <div class="sm-sheet-top-meta">
            <span class="sm-sheet-pill">${pmsEscapeHtml(idLabel)}</span>
            <span class="sm-sheet-pill sm-sheet-pill--muted">${pmsEscapeHtml(idKind)}</span>
          </div>
          <div class="sm-sheet-check" title="Đã đọc được dữ liệu">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
        </header>

        <div class="sm-sheet-main">
          <div class="sm-sheet-name-block">
            <span class="sm-sheet-k">Họ và tên</span>
            <div class="sm-sheet-name-line">
              <span class="sm-sheet-name">${pmsEscapeHtml(p.name || '—')}</span>
              <span class="sm-sheet-gender ${pmsEscapeHtml(gender.cls)}">${pmsEscapeHtml(gender.label)}</span>
            </div>
          </div>

          <dl class="sm-sheet-dl sm-sheet-dl--3">
            <div class="sm-sheet-row">
              <dt>Ngày sinh</dt>
              <dd>${pmsEscapeHtml(p.dob || '—')}</dd>
            </div>
            <div class="sm-sheet-row">
              <dt>Giới tính</dt>
              <dd>${pmsEscapeHtml(gender.label)}</dd>
            </div>
            <div class="sm-sheet-row">
              <dt>Tuổi</dt>
              <dd>${p.age != null ? pmsEscapeHtml(String(p.age)) : '—'}</dd>
            </div>
          </dl>

          <div class="sm-sheet-expiry sm-sheet-expiry--${stripCls}">
            <div class="sm-sheet-expiry-inner">
              <span class="sm-sheet-k">Hạn giấy tờ</span>
              <span class="sm-sheet-expiry-date">${pmsEscapeHtml(p.expiry_date || '—')}</span>
            </div>
            <div class="sm-sheet-expiry-side">
              ${expiryNote ? `<span class="sm-sheet-expiry-note">${pmsEscapeHtml(expiryNote)}</span>` : ''}
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
        <div class="sm-error-title">${pmsEscapeHtml(p.error || 'Không nhận diện được dữ liệu')}</div>
        ${p.raw_cleaned ? `
        <div class="sm-error-raw">${pmsEscapeHtml(p.raw_cleaned.slice(0, 120))}${p.raw_cleaned.length > 120 ? '…' : ''}</div>
        ` : ''}
      </div>`;
}

/* ── Live preview ───────────────────────────────────────────── */
function _updateLivePreview(text) {
    const el = _smEl('sm-live-preview');
    if (el) el.textContent = text ? `▶ ${text.slice(-60)}` : '';
}

/* ── Reset / cleanup ─────────────────────────────────────────── */
function _smReset() {
    _smBuffer = '';
    clearTimeout(_smFlushTimer);
    clearTimeout(_smTimeoutTimer);
    _smCleanup();

    const btn = _smEl('sm-confirm-btn');
    if (btn) { btn.disabled = true; btn.onclick = null; }
}

function _smCleanup() {
    clearListeners();
    clearTimeout(_smTimeoutTimer);
}

function clearListeners() {
    window.removeEventListener('keydown', _smKeyHandler, { capture: true });
}

/* ── Export globally ─────────────────────────────────────────── */
window.openScanModal       = openScanModal;
window.scanModalClose     = scanModalClose;
window.scanModalBack      = scanModalBack;
window.scanModalStart     = scanModalStart;
window.scanModalTestInput = scanModalTestInput;
