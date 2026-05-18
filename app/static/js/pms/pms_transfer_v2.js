// static/js/pms/pms_transfer.js
// PMS Transfer Room – Open modal, load rooms, filter chips, submit transfer
'use strict';

// ── Global state ──
window.pmsTfStayId     = null;
window.pmsTfRooms      = [];
window.pmsTfSelectedId = null;
window._pmsTfAllRooms  = [];
window._pmsTfChipFilter = 'all';
window._pmsTfOldCharge  = 0;
window._pmsTfNewPrice   = 0;

// ─────────────────────────────────────────────────────────────────────────────
// Open Transfer Modal
// ─────────────────────────────────────────────────────────────────────────────
async function openTF(stayId, currentRoomNum, currentRoomType, currentPrice) {
    if (!stayId) { pmsToast('Thiếu ID lưu trú.', false); return; }

    window.pmsTfStayId      = stayId;
    window.pmsTfRooms       = [];
    window.pmsTfSelectedId  = null;
    window._pmsTfAllRooms   = [];
    window._pmsTfChipFilter = 'all';
    window._pmsTfOldCharge  = 0;
    window._pmsTfNewPrice   = 0;
    window._pmsTfCurrentPrice = currentPrice || 0;

    // From-box
    const curEl = document.getElementById('tf-current-room');
    if (curEl) curEl.textContent = currentRoomNum || '—';

    const curType = document.getElementById('tf-current-type');
    if (curType) {
        const priceStr = currentPrice ? ` · ${Number(currentPrice).toLocaleString('vi-VN')}đ/đêm` : '';
        curType.textContent = (currentRoomType || '') + priceStr;
    }

    // To-box – reset
    _tfResetTarget();

    // Reset search & chips
    const searchEl = document.getElementById('tf-search');
    if (searchEl) searchEl.value = '';

    const chipsEl = document.getElementById('tf-chips');
    if (chipsEl) chipsEl.innerHTML = '';

    const countEl = document.getElementById('tf-room-count');
    if (countEl) countEl.textContent = '';

    // Show charge preview ngay với loading state — fetch tiền phòng cũ song song
    _tfShowChargePreviewLoading();
    const feeInput = document.getElementById('tf-transfer-fee-input');
    if (feeInput) { feeInput.value = ''; feeInput.placeholder = '0'; }
    const noteInput = document.getElementById('tf-transfer-note-input');
    if (noteInput) noteInput.value = '';

    // Room list – show loader
    const listEl = document.getElementById('tf-room-list');
    if (listEl) listEl.innerHTML = _tfLoaderHtml();

    // Disable confirm
    const btnEl = document.getElementById('tf-submit-btn');
    if (btnEl) btnEl.disabled = true;

    // Mở modal trước rồi fetch song song để UI phản hồi nhanh
    if (typeof openModal === 'function') openModal('tfModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('tfModal');
    else document.getElementById('tfModal').classList.add('show');

    // Fetch song song: rooms + tiền phòng cũ
    await Promise.all([
        pmsTfLoadRooms(),
        pmsTfLoadOldCharge(),
    ]);
}

// ─────────────────────────────────────────────────────────────────────────────
// Load tiền phòng cũ (đã ở) — gọi ngay khi mở modal
// ─────────────────────────────────────────────────────────────────────────────
async function pmsTfLoadOldCharge() {
    if (!window.pmsTfStayId) return;
    try {
        const info = await pmsApi(`/api/pms/checkout/${window.pmsTfStayId}/info`);
        const oldCharge = info.room_charge || 0;
        window._pmsTfOldCharge = oldCharge;
        window._pmsTfDeadZone = !!info.dead_zone;

        // Dead zone (12:00–14:00): ẩn panel phí chuyển phòng — miễn phí
        if (window._pmsTfDeadZone) {
            _tfHideChargePreview();
            return;
        }

        const oldChargeEl = document.getElementById('tf-old-charge');
        if (oldChargeEl) oldChargeEl.textContent = Number(oldCharge).toLocaleString('vi-VN') + 'đ';
    } catch (_) {
        window._pmsTfOldCharge = 0;
        const oldChargeEl = document.getElementById('tf-old-charge');
        if (oldChargeEl) oldChargeEl.textContent = '—';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Load Available Rooms
// ─────────────────────────────────────────────────────────────────────────────
async function pmsTfLoadRooms() {
    if (!window.pmsTfStayId) return;

    try {
        const data = await pmsApi(`/api/pms/rooms/available?stay_id=${window.pmsTfStayId}`);
        window.pmsTfRooms    = data.rooms || [];
        window._pmsTfAllRooms = window.pmsTfRooms;

        // Build type chips
        _tfBuildChips(window.pmsTfRooms);

        // Render list
        _tfRenderList(window.pmsTfRooms);

    } catch (e) {
        const listEl = document.getElementById('tf-room-list');
        if (listEl) listEl.innerHTML = _tfEmptyHtml('Không thể tải dữ liệu phòng', e.message);
        pmsToast(`Không thể tải phòng: ${e.message}`, false);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Build type filter chips
// ─────────────────────────────────────────────────────────────────────────────
function _tfBuildChips(rooms) {
    const chipsEl = document.getElementById('tf-chips');
    if (!chipsEl) return;

    // Collect unique types
    const types = [...new Set(rooms.map(r => r.type_name).filter(Boolean))].sort();

    if (types.length <= 1) {
        chipsEl.innerHTML = '';
        return;
    }

    chipsEl.innerHTML = [
        `<div class="tf-chip active" data-type="all" onclick="pmsTfSetChip(this,'all')">Tất cả (${rooms.length})</div>`,
        ...types.map(t => {
            const cnt = rooms.filter(r => r.type_name === t).length;
            return `<div class="tf-chip" data-type="${t}" onclick="pmsTfSetChip(this,'${t}')">${t} <span style="opacity:.65">${cnt}</span></div>`;
        })
    ].join('');
}

// ─────────────────────────────────────────────────────────────────────────────
// Set chip filter
// ─────────────────────────────────────────────────────────────────────────────
function pmsTfSetChip(el, type) {
    document.querySelectorAll('.tf-chip').forEach(c => c.classList.remove('active'));
    if (el) el.classList.add('active');
    window._pmsTfChipFilter = type;

    // Re-apply with current search query
    const q = (document.getElementById('tf-search')?.value || '').toLowerCase().trim();
    _tfApplyFilter(q);
}

// ─────────────────────────────────────────────────────────────────────────────
// Filter by search + chip
// ─────────────────────────────────────────────────────────────────────────────
function pmsTfFilterRooms(query) {
    const q = (query || '').toLowerCase().trim();
    _tfApplyFilter(q);
}

function _tfApplyFilter(q) {
    const all = window._pmsTfAllRooms || [];
    const chipType = window._pmsTfChipFilter || 'all';

    let filtered = chipType === 'all' ? all : all.filter(r => r.type_name === chipType);
    if (q) {
        filtered = filtered.filter(r =>
            (r.room_number || '').toLowerCase().includes(q) ||
            (r.type_name   || '').toLowerCase().includes(q)
        );
    }

    _tfRenderList(filtered, q);
}

// ─────────────────────────────────────────────────────────────────────────────
// Render room list
// ─────────────────────────────────────────────────────────────────────────────
function _tfRenderList(rooms, query) {
    const listEl = document.getElementById('tf-room-list');
    const countEl = document.getElementById('tf-room-count');
    if (!listEl) return;

    if (rooms.length === 0) {
        listEl.innerHTML = _tfEmptyHtml(
            query ? 'Không tìm thấy phòng phù hợp' : 'Không có phòng trống nào',
            query ? 'Thử thay đổi từ khoá hoặc bộ lọc loại phòng' : 'Tất cả phòng đang được sử dụng'
        );
        if (countEl) countEl.textContent = '';
        return;
    }

    if (countEl) countEl.textContent = `${rooms.length} phòng`;

    listEl.innerHTML = rooms.map((r, i) => `
        <div class="tf-room-card" data-id="${r.id}"
             style="animation-delay:${Math.min(i * 0.035, 0.4)}s"
             onclick="pmsTfSelectRoom(${r.id}, '${r.room_number}', ${r.price_per_night ?? 0}, '${(r.type_name || '').replace(/'/g, "\\'")}')">
          <div class="tf-rc-head">
            <div class="tf-rc-num">${r.room_number}</div>
            <div class="tf-rc-badge">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
          </div>
          <div class="tf-rc-type">${r.type_name || '—'}</div>
          <div class="tf-rc-divider"></div>
          <div class="tf-rc-price">
            ${(r.price_per_night ?? 0).toLocaleString('vi-VN')}<small>đ</small>
          </div>
        </div>
    `).join('');

    // Re-apply selection highlight if any
    if (window.pmsTfSelectedId) {
        const prev = listEl.querySelector(`.tf-room-card[data-id="${window.pmsTfSelectedId}"]`);
        if (prev) prev.classList.add('selected');
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Select Room — chỉ cập nhật UI selection, tiền phòng cũ đã fetch sẵn khi mở modal
// ─────────────────────────────────────────────────────────────────────────────
function pmsTfSelectRoom(roomId, roomNum, price, typeName) {
    // Deselect all
    document.querySelectorAll('.tf-room-card').forEach(el => el.classList.remove('selected'));

    // Select target
    const card = document.querySelector(`.tf-room-card[data-id="${roomId}"]`);
    if (card) card.classList.add('selected');

    window.pmsTfSelectedId = roomId;
    window._pmsTfNewPrice  = price || 0;

    // Update TO box
    const tgtBox  = document.getElementById('tf-target-box');
    const tgtRoom = document.getElementById('tf-target-room');
    const tgtType = document.getElementById('tf-target-type');

    if (tgtBox)  tgtBox.classList.add('selected');
    if (tgtRoom) tgtRoom.innerHTML = `<span style="font-size:22px;font-weight:900;letter-spacing:-0.04em;line-height:1.1;color:inherit">${roomNum}</span>`;
    if (tgtType) {
        const priceStr = price ? ` · ${Number(price).toLocaleString('vi-VN')}đ/đêm` : '';
        tgtType.textContent = (typeName || '') + priceStr;
    }

    // Enable confirm
    const btnEl = document.getElementById('tf-submit-btn');
    if (btnEl) btnEl.disabled = false;
}

// ─────────────────────────────────────────────────────────────────────────────
// Parse số từ string có thể có dấu chấm/phẩy ngàn (vi-VN)
// ─────────────────────────────────────────────────────────────────────────────
function _tfParseAmount(str) {
    if (!str) return 0;
    // Xóa dấu chấm/phẩy ngàn, giữ lại số
    const cleaned = String(str).replace(/[.,\s]/g, '').trim();
    const val = parseFloat(cleaned);
    return isNaN(val) ? 0 : val;
}

// Format realtime khi gõ — hiển thị dấu chấm ngàn ngay lập tức
function pmsTfFormatFeeInput(input) {
    const raw = input.value.replace(/\D/g, '');
    if (!raw) { input.value = ''; return; }
    const num = parseInt(raw, 10);
    const pos = input.selectionStart;
    const oldLen = input.value.length;
    input.value = num.toLocaleString('vi-VN');
    const newLen = input.value.length;
    input.setSelectionRange(pos + (newLen - oldLen), pos + (newLen - oldLen));
}

// ─────────────────────────────────────────────────────────────────────────────
// Submit Transfer
// ─────────────────────────────────────────────────────────────────────────────
async function submitTF() {
    if (!window.pmsTfStayId || !window.pmsTfSelectedId) {
        pmsToast('Vui lòng chọn phòng mới.', false);
        return;
    }

    // Confirm cho mọi trường hợp
    const fromRoom = document.getElementById('tf-current-room')?.textContent?.trim() || '—';
    const fromType = document.getElementById('tf-current-type')?.textContent?.trim() || '';
    const toRoom = document.querySelector('#tf-target-room span')?.textContent?.trim()
        || document.getElementById('tf-target-room')?.textContent?.trim() || '—';
    const toType = document.getElementById('tf-target-type')?.textContent?.trim() || '';

    const feeInput = document.getElementById('tf-transfer-fee-input');
    const fee = _tfParseAmount(feeInput?.value);

    const fromLabel = fromType ? `${fromRoom} (${fromType.split(' ·')[0]})` : fromRoom;
    const toLabel   = toType   ? `${toRoom} (${toType.split(' ·')[0]})`   : toRoom;

    let msg = `Xác nhận chuyển khách từ phòng ${fromLabel} sang phòng ${toLabel}?`;
    if (fee > 0) {
        msg += `\n\nPhụ thu phí chuyển phòng: ${fee.toLocaleString('vi-VN')}đ`;
    }
    if (!confirm(msg)) return;

    const btnEl = document.getElementById('tf-submit-btn');
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `
          <div class="tf-spinner" style="width:15px;height:15px;border-width:2px;border-color:rgba(255,255,255,.25);border-top-color:#fff;flex-shrink:0"></div>
          Đang xử lý...`;
    }

    try {
        const fd = new FormData();
        fd.append('new_room_id', window.pmsTfSelectedId);

        const feeInput = document.getElementById('tf-transfer-fee-input');
        const fee = _tfParseAmount(feeInput?.value);
        fd.append('transfer_charge', fee);

        const noteInput = document.getElementById('tf-transfer-note-input');
        if (noteInput?.value?.trim()) {
            fd.append('transfer_note', noteInput.value.trim());
        }

        const r = await pmsApi(`/api/pms/stays/${window.pmsTfStayId}/transfer`, {
            method: 'PUT',
            body: fd,
        });

        pmsToast(r.message || 'Chuyển phòng thành công!');

        if (typeof closeModal === 'function') closeModal('tfModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('tfModal');
        else document.getElementById('tfModal').classList.remove('show');

        // Refresh folio nếu rd_modal đang mở
        if (typeof rdRefreshFolioAfterCharge === 'function') {
            await rdRefreshFolioAfterCharge(window.pmsTfStayId);
        }

        if (typeof pmsLoadRooms === 'function') pmsLoadRooms(undefined, true);

    } catch (e) {
        pmsToast(e.message || 'Có lỗi xảy ra.', false);
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `
              <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              Xác nhận chuyển`;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function _tfResetTarget() {
    const tgtBox  = document.getElementById('tf-target-box');
    const tgtRoom = document.getElementById('tf-target-room');
    const tgtType = document.getElementById('tf-target-type');

    if (tgtBox)  tgtBox.classList.remove('selected');
    if (tgtRoom) tgtRoom.innerHTML = `
        <div class="tf-flow-room-placeholder">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>
          </svg>
          Chưa chọn
        </div>`;
    if (tgtType) tgtType.textContent = '';
}

function _tfShowChargePreview() {
    const el = document.getElementById('tf-charge-preview');
    if (el) el.style.display = '';
}

function _tfHideChargePreview() {
    const el = document.getElementById('tf-charge-preview');
    if (el) el.style.display = 'none';
    const oldChargeEl = document.getElementById('tf-old-charge');
    if (oldChargeEl) oldChargeEl.textContent = '—';
    const feeInput = document.getElementById('tf-transfer-fee-input');
    if (feeInput) feeInput.value = '';
    const noteInput = document.getElementById('tf-transfer-note-input');
    if (noteInput) noteInput.value = '';
}

function _tfShowChargePreviewLoading() {
    const el = document.getElementById('tf-charge-preview');
    if (el) el.style.display = '';
    const oldChargeEl = document.getElementById('tf-old-charge');
    if (oldChargeEl) oldChargeEl.textContent = '...';
}

function _tfLoaderHtml() {
    return `
      <div class="tf-loader">
        <div class="tf-spinner-wrap">
          <div class="tf-spinner"></div>
          <div class="tf-spinner-dot"></div>
        </div>
        <span class="tf-loader-text">Đang tải danh sách phòng...</span>
      </div>`;
}

function _tfEmptyHtml(title, desc) {
    return `
      <div class="tf-empty-state">
        <div class="tf-empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
        </div>
        <div class="tf-empty-title">${title || ''}</div>
        <div class="tf-empty-desc">${desc || ''}</div>
      </div>`;
}

// ── Export globals ──
window.openTF            = openTF;
window.submitTF          = submitTF;
window.pmsTfSelectRoom   = pmsTfSelectRoom;
window.pmsTfLoadRooms    = pmsTfLoadRooms;
window.pmsTfFilterRooms  = pmsTfFilterRooms;
window.pmsTfSetChip      = pmsTfSetChip;
window.pmsTfFormatFeeInput  = pmsTfFormatFeeInput;
