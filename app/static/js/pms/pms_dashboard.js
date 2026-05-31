// static/js/pms/pms_dashboard.js
// PMS Dashboard - Room map, floor/type view, loading rooms
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// PMS State
// ─────────────────────────────────────────────────────────────────────────────
let PMS_VIEW_MODE = 'floor'; // 'floor' | 'type'
let PMS_CURRENT_TAB = 'map'; // 'map' | 'book'
let PMS_DENSITY_MODE = localStorage.getItem('pms-density') || 'standard';
let PMS_ARRIVAL_ROOM_ID = null;
let PMS_OTA_STATUS = {
    pending: 0,
    total: 0,
    lastPending: null,
    latestEmailAt: null,
    latestEmailStatus: null,
    branchId: null,
    branchName: '',
    loading: true,
    timer: null,
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Auto-select "Bin Bin Hotel 1" if admin and no branch selected
    const branchSelect = document.getElementById('branchSelect');
    if (branchSelect && !branchSelect.value) {
        for (let i = 0; i < branchSelect.options.length; i++) {
            const opt = branchSelect.options[i];
            if (opt.textContent.includes('Bin Bin Hotel 1') || opt.textContent === 'Bin Bin Hotel 1') {
                branchSelect.value = opt.value;
                break;
            }
        }
    }
    if (branchSelect?.value) PMS.branchId = branchSelect.value;
    pmsLoadRooms();
    pmsLoadOtaStatus(true);
    // Periodic refresh: bảo đảm không chồng request nếu load chưa xong.
    // Pause khi tab ẩn để không cạnh tranh DB pool với các tab khác.
    function startDashboardPolling() {
        if (PMS.timer || document.hidden) return;
        PMS.timer = setInterval(() => {
            if (!PMS._loading) pmsLoadRooms(undefined, true);
        }, 45000);
        PMS_OTA_STATUS.timer = setInterval(() => pmsLoadOtaStatus(true), 90000);
    }
    function stopDashboardPolling() {
        if (PMS.timer) { clearInterval(PMS.timer); PMS.timer = null; }
        if (PMS_OTA_STATUS.timer) { clearInterval(PMS_OTA_STATUS.timer); PMS_OTA_STATUS.timer = null; }
    }
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stopDashboardPolling();
        else {
            stopDashboardPolling(); // ensure no leftover interval before restart
            pmsLoadRooms(undefined, true);
            pmsLoadOtaStatus(true);
            startDashboardPolling();
        }
    });
    startDashboardPolling();
    document.addEventListener('keydown', (e) => {
        if (e.key === 'F1' && document.getElementById('ciModal')?.classList?.contains('show')) {
            e.preventDefault();
            pmsCiScanCode();
        }
        if (e.key === 'F1' && document.getElementById('agModal')?.classList?.contains('show')) {
            e.preventDefault();
            if (typeof agScanCode === 'function') agScanCode();
        }
    });
    const ciName = document.getElementById('ci-name');
    if (ciName) ciName.addEventListener('input', pmsCiUpdateCapacityWarn);

    // Init Density & View
    pmsSetDensity(PMS_DENSITY_MODE);
    pmsSetView(PMS_VIEW_MODE);
});

// ─────────────────────────────────────────────────────────────────────────────
// Load Rooms
// ─────────────────────────────────────────────────────────────────────────────
    async function pmsLoadRooms(bid, silent = false) {
    if (PMS._loading) return; // tránh gọi chồng
    // Dedup guard: bỏ qua lần gọi silent nếu vừa load xong < 3s (tránh nhiều caller dồn dập sau check-in/checkout/transfer)
    const now = Date.now();
    if (silent && PMS._lastLoadAt && (now - PMS._lastLoadAt) < 3000 && bid === undefined) return;
    PMS._loading = true;
    PMS._roomsLoaded = false;
    if (bid!==undefined) PMS.branchId=bid;
    const loadEl = document.getElementById('pms-loading');
    const floorsEl = document.getElementById('pms-floors');
    if (loadEl && floorsEl) {
        if (!silent) {
            loadEl.style.display = 'block';
            floorsEl.style.display = 'none';
        } else if (!floorsEl.innerHTML.trim()) {
            loadEl.style.display = 'block';
            floorsEl.style.display = 'none';
        }
    }
    try {
        let url = '/api/pms/rooms';
        if (PMS.branchId) url += `?branch_id=${PMS.branchId}`;
        let rtUrl = '/api/pms/room-types';
        if (PMS.branchId) rtUrl += `?branch_id=${PMS.branchId}`;
        const [data, roomTypesData] = await Promise.all([pmsApi(url), pmsApi(rtUrl)]);
        PMS.floors = data.floors || {};
        PMS.roomTypes = roomTypesData;
        PMS._roomsLoaded = true;
        PMS._lastLoadAt = Date.now();
        // today-arrivals tách độc lập: chỉ refetch nếu chưa có hoặc cache > 60s
        const arrivalsAge = PMS._arrivalsLoadedAt ? (Date.now() - PMS._arrivalsLoadedAt) : Infinity;
        if (!PMS.todayArrivals || arrivalsAge > 60000) {
            await pmsLoadTodayArrivals(true);
        } else {
            pmsUpdateArrivalBadge();
        }
        pmsRender();
    } catch(e) {
        if (loadEl) loadEl.innerHTML=`<div class="pms-empty"><p class="text-danger small">${e.message}</p></div>`;
        else pmsToast(e.message, false);
    } finally {
        PMS._loading = false;
        pmsStartLiveCounters();
    }
}

function pmsChangeBranch(v) {
    PMS.branchId = v || null;
    PMS_OTA_STATUS.pending = 0;
    PMS_OTA_STATUS.total = 0;
    PMS_OTA_STATUS.lastPending = null;
    PMS_OTA_STATUS.latestEmailAt = null;
    PMS_OTA_STATUS.latestEmailStatus = null;
    PMS_OTA_STATUS.branchId = PMS.branchId;
    PMS_OTA_STATUS.branchName = pmsCurrentBranchName();
    PMS_OTA_STATUS.loading = true;
    pmsRenderOtaStatus();
    pmsLoadRooms(PMS.branchId);
    pmsLoadOtaStatus(true);
}

function pmsCurrentBranchName() {
    const branchSelect = document.getElementById('branchSelect');
    if (!branchSelect) return PMS.branchId ? `Chi nhánh #${PMS.branchId}` : 'Tất cả chi nhánh';
    const selected = branchSelect.options[branchSelect.selectedIndex];
    return selected?.textContent?.trim() || (PMS.branchId ? `Chi nhánh #${PMS.branchId}` : 'Tất cả chi nhánh');
}

function pmsDashboardApiData(response, fallback = null) {
    if (response && typeof response === 'object' && response.success === true && Object.prototype.hasOwnProperty.call(response, 'data')) {
        return response.data;
    }
    return response ?? fallback;
}

function pmsArrivalBranchUrl(path) {
    const params = new URLSearchParams();
    if (PMS.branchId) params.set('branch_id', PMS.branchId);
    const qs = params.toString();
    return qs ? `${path}?${qs}` : path;
}

async function pmsLoadOtaStatus(silent = false) {
    const requestBranchId = PMS.branchId || null;
    // Dedup: skip silent calls if just fetched < 5s ago for same branch
    if (silent && PMS_OTA_STATUS._loading) return;
    if (silent && PMS_OTA_STATUS._lastLoadedAt
        && PMS_OTA_STATUS._lastLoadedBranchId === requestBranchId
        && (Date.now() - PMS_OTA_STATUS._lastLoadedAt) < 5000) return;
    const params = new URLSearchParams();
    if (requestBranchId) params.set('branch_id', requestBranchId);
    const url = `/api/pms/reservations/ota/status${params.toString() ? `?${params.toString()}` : ''}`;

    PMS_OTA_STATUS._loading = true;
    try {
        const data = pmsDashboardApiData(await pmsApi(url), {});
        if ((PMS.branchId || null) !== requestBranchId) return;
        const total = Number(data.ota_total || 0);
        const pending = total;
        const previous = PMS_OTA_STATUS.lastPending;
        PMS_OTA_STATUS.pending = pending;
        PMS_OTA_STATUS.total = total;
        PMS_OTA_STATUS.cancelled = Number(data.ota_cancelled || data.cancelled_emails || 0);
        PMS_OTA_STATUS.latestEmailAt = data.latest_email_at || null;
        PMS_OTA_STATUS.latestEmailStatus = data.latest_email_status || null;
        PMS_OTA_STATUS.branchId = data.branch_id ?? requestBranchId;
        PMS_OTA_STATUS.branchName = data.branch_name || pmsCurrentBranchName();
        PMS_OTA_STATUS.loading = false;
        PMS_OTA_STATUS._lastLoadedAt = Date.now();
        PMS_OTA_STATUS._lastLoadedBranchId = requestBranchId;
        pmsRenderOtaStatus();
        if (previous !== null && pending > previous) {
            pmsShowOtaBanner(pending - previous, pending);
            pmsMarkOtaBellActive();
        }
        PMS_OTA_STATUS.lastPending = pending;
    } catch (e) {
        if ((PMS.branchId || null) !== requestBranchId) return;
        PMS_OTA_STATUS.branchId = requestBranchId;
        PMS_OTA_STATUS.branchName = pmsCurrentBranchName();
        PMS_OTA_STATUS.loading = false;
        pmsRenderOtaStatus(e.message || 'Không tải được trạng thái OTA');
        if (!silent) pmsToast(e.message || 'Không tải được trạng thái OTA', false);
    } finally {
        PMS_OTA_STATUS._loading = false;
    }
}

function pmsRenderOtaStatus(errorMessage) {
    const badge = document.getElementById('pms-ota-badge');
    const bell = document.getElementById('pms-ota-bell');
    const latest = document.getElementById('pms-ota-latest');
    const body = document.getElementById('pms-ota-body');
    if (!badge || !bell || !latest || !body) return;

    const pending = PMS_OTA_STATUS.pending || 0;
    badge.hidden = pending <= 0;
    badge.textContent = pending > 99 ? '99+' : String(pending);
    bell.classList.toggle('has-pending', pending > 0);

    if (PMS_OTA_STATUS.loading) {
        latest.textContent = 'Đang tải trạng thái...';
        body.innerHTML = '<div class="pms-ota-skeleton"><span></span><span></span></div>';
        return;
    }

    if (errorMessage) {
        latest.textContent = errorMessage;
        body.innerHTML = '<div class="pms-ota-empty">Không tải được dữ liệu OTA. Bấm làm mới để thử lại.</div>';
        return;
    }

    const branchName = PMS_OTA_STATUS.branchName || pmsCurrentBranchName();
    latest.textContent = PMS_OTA_STATUS.latestEmailAt
        ? `${branchName} · Email mới nhất: ${pmsFormatOtaDateTime(PMS_OTA_STATUS.latestEmailAt)}`
        : `${branchName} · Chưa có email OTA mới`;
    body.innerHTML = `
        <div class="pms-ota-metric">
            <span>Phạm vi</span>
            <strong>${pmsEscapeHtml(branchName)}</strong>
        </div>
        <div class="pms-ota-metric">
            <span>Booking OTA thành công</span>
            <strong>${pending}</strong>
        </div>
        <div class="pms-ota-metric">
            <span>Huỷ OTA</span>
            <strong>${Number(PMS_OTA_STATUS.cancelled || 0)}</strong>
        </div>
        <p>${pending > 0 ? 'Có booking OTA thành công trong phạm vi thống kê.' : 'Chưa có booking OTA thành công trong phạm vi thống kê.'}</p>
    `;
}

function pmsToggleOtaPopover() {
    const popover = document.getElementById('pms-ota-popover');
    const bell = document.getElementById('pms-ota-bell');
    if (!popover || !bell) return;
    const open = popover.hidden;
    popover.hidden = !open;
    bell.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) pmsLoadOtaStatus(false);
}

function pmsCloseOtaPopover() {
    const popover = document.getElementById('pms-ota-popover');
    const bell = document.getElementById('pms-ota-bell');
    if (!popover || !bell) return;
    popover.hidden = true;
    bell.setAttribute('aria-expanded', 'false');
}

// ─────────────────────────────────────────────────────────────────────────────
// DKLT Export (Đăng ký lưu trú) — modal chọn phòng + format
// ─────────────────────────────────────────────────────────────────────────────
const PMS_DKLT = {
    stays: [],          // [{stay_id, room_number, guests:[...], ...}]
    guests: [],         // mảng phẳng: {guest_id, full_name, is_foreign, is_primary, check_in_at, dklt_exported_at, stay_id, room_number}
    selected: new Set(),// guest_id đang chọn — nguồn chân lý
    filter: '',         // search query lowercase
    scope: 'all',       // 'all' | 'vn' | 'foreign' — lọc theo quốc tịch
    viewMode: 'room',   // 'room' | 'guest'
    dateFilter: 'all',  // 'all' | 'today' | 'yesterday' | 'custom' — lọc theo ngày đến
    dateFrom: null,     // 'YYYY-MM-DD' khi custom
    dateTo: null,
    loaded: false,
};

async function pmsOpenDkltModal() {
    const modal = document.getElementById('pms-dklt-modal');
    if (!modal) return;
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');

    document.getElementById('pms-dklt-search').value = '';
    PMS_DKLT.filter = '';
    PMS_DKLT.scope = 'all';
    PMS_DKLT.viewMode = 'room';
    PMS_DKLT.dateFilter = 'all';
    PMS_DKLT.dateFrom = null;
    PMS_DKLT.dateTo = null;
    pmsDkltSyncScopeButtons();
    pmsDkltSyncViewButtons();
    pmsDkltSyncDateButtons();
    const customWrap = document.getElementById('pms-dklt-date-custom');
    if (customWrap) customWrap.style.display = 'none';
    document.getElementById('pms-dklt-select-all').checked = true;

    const list = document.getElementById('pms-dklt-room-list');
    list.innerHTML = '<div class="pms-dklt-empty">Đang tải...</div>';

    try {
        const params = new URLSearchParams();
        if (PMS.branchId) params.set('branch_id', PMS.branchId);
        const url = `/api/pms/dklt/rooms${params.toString() ? '?' + params.toString() : ''}`;
        const data = await pmsApi(url);
        PMS_DKLT.stays = Array.isArray(data?.stays) ? data.stays : [];
        pmsDkltBuildGuests();
        // Auto-tick khách CHƯA xuất; khách đã xuất không auto-tick (tránh khai trùng).
        PMS_DKLT.selected = new Set(
            PMS_DKLT.guests.filter(g => !g.dklt_exported_at).map(g => g.guest_id)
        );
        PMS_DKLT.loaded = true;
        pmsDkltRender();
    } catch (err) {
        console.error('[DKLT] load rooms failed:', err);
        list.innerHTML = `<div class="pms-dklt-empty">Không tải được danh sách phòng: ${err?.message || 'lỗi'}</div>`;
    }
}

function pmsDkltBuildGuests() {
    const out = [];
    (PMS_DKLT.stays || []).forEach(s => {
        (s.guests || []).forEach(g => {
            out.push({
                guest_id: g.guest_id,
                full_name: g.full_name || '',
                is_foreign: !!g.is_foreign,
                is_primary: !!g.is_primary,
                check_in_at: g.check_in_at || s.check_in_at || null,
                dklt_exported_at: g.dklt_exported_at || null,
                stay_id: s.stay_id,
                room_number: s.room_number || '',
            });
        });
    });
    PMS_DKLT.guests = out;
}

function pmsCloseDkltModal() {
    const modal = document.getElementById('pms-dklt-modal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('pms-dklt-modal');
    if (modal && e.target === modal) pmsCloseDkltModal();
});

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const modal = document.getElementById('pms-dklt-modal');
    if (modal?.classList.contains('show')) pmsCloseDkltModal();
});

function pmsDkltDateKey(iso) {
    // Trả về 'YYYY-MM-DD' theo ngày của chuỗi ISO (đã kèm offset VN từ server).
    if (!iso) return '';
    const s = String(iso);
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(s);
    return m ? m[1] : '';
}

function pmsDkltTodayKey(offsetDays = 0) {
    // Ngày hiện tại theo giờ VN (UTC+7), lùi offsetDays ngày.
    const now = new Date();
    const vn = new Date(now.getTime() + 7 * 3600 * 1000);
    vn.setUTCDate(vn.getUTCDate() - offsetDays);
    return vn.toISOString().slice(0, 10);
}

function pmsDkltGuestMatchesDate(g) {
    const mode = PMS_DKLT.dateFilter || 'all';
    if (mode === 'all') return true;
    const key = pmsDkltDateKey(g.check_in_at);
    if (!key) return false;
    if (mode === 'today') return key === pmsDkltTodayKey(0);
    if (mode === 'yesterday') return key === pmsDkltTodayKey(1);
    if (mode === 'custom') {
        const from = PMS_DKLT.dateFrom;
        const to = PMS_DKLT.dateTo;
        if (from && key < from) return false;
        if (to && key > to) return false;
        return true;
    }
    return true;
}

function pmsDkltVisibleGuests() {
    const scope = PMS_DKLT.scope || 'all';
    const q = (PMS_DKLT.filter || '').trim().toLowerCase();
    const filtered = PMS_DKLT.guests.filter(g => {
        if (scope === 'vn' && g.is_foreign) return false;
        if (scope === 'foreign' && !g.is_foreign) return false;
        if (!pmsDkltGuestMatchesDate(g)) return false;
        if (!q) return true;
        const name = (g.full_name || '').toLowerCase();
        const room = (g.room_number || '').toLowerCase();
        return name.includes(q) || room.includes(q);
    });
    // Khách CHƯA xuất lên trước; giữ thứ tự phụ (primary/tên) nhờ sort ổn định.
    filtered.sort((a, b) => (a.dklt_exported_at ? 1 : 0) - (b.dklt_exported_at ? 1 : 0));
    return filtered;
}

function pmsDkltExportedBadge(g) {
    if (!g.dklt_exported_at) return '';
    const key = pmsDkltDateKey(g.dklt_exported_at);
    let label = '';
    if (key) {
        const [, mo, d] = key.split('-');
        label = ` · ${d}/${mo}`;
    }
    return `<span class="pms-dklt-exported-text">Đã xuất${label}</span>`;
}

function pmsDkltGuestRow(g) {
    const checked = PMS_DKLT.selected.has(g.guest_id) ? 'checked' : '';
    const tag = g.is_foreign
        ? '<span class="pms-dklt-tag fn">NN</span>'
        : '<span class="pms-dklt-tag vn">VN</span>';
    const primary = g.is_primary ? '<span class="pms-dklt-primary-dot" title="Khách chính">●</span>' : '';
    const exportedCls = g.dklt_exported_at ? ' exported' : '';
    const exportedBadge = pmsDkltExportedBadge(g);
    // View theo phòng: số phòng đã nằm ở header phòng nên không lặp lại "Phòng X" trong row.
    const isRoomView = PMS_DKLT.viewMode === 'room';
    const roomLabel = isRoomView
        ? ''
        : `<span class="pms-dklt-guest-room-label">Phòng ${pmsEscape(g.room_number || '—')}</span>`;
    // Badge "Đã xuất" đặt cạnh số phòng (dòng meta) để không chèn ép tên khách ở bên phải.
    const meta = (roomLabel || exportedBadge)
        ? `<div class="pms-dklt-guest-meta">${roomLabel}${exportedBadge}</div>`
        : '';
    return `
        <label class="pms-dklt-guest-item${exportedCls}">
            <input type="checkbox" data-guest-id="${g.guest_id}" ${checked}
                onchange="pmsDkltToggleGuest(${g.guest_id}, this.checked)" />
            <div class="pms-dklt-guest-info">
                <div class="pms-dklt-guest-name">${primary}${pmsEscape(g.full_name || '—')}</div>
                ${meta}
            </div>
            <div class="pms-dklt-guest-tags">${tag}</div>
        </label>
    `;
}

function pmsDkltRender() {
    const list = document.getElementById('pms-dklt-room-list');
    if (!list) return;

    if (!PMS_DKLT.guests.length) {
        list.innerHTML = '<div class="pms-dklt-empty">Không có khách nào đang lưu trú (đã loại phòng giờ).</div>';
        pmsDkltUpdateFooter();
        return;
    }

    const visible = pmsDkltVisibleGuests();
    if (!visible.length) {
        list.innerHTML = '<div class="pms-dklt-empty">Không tìm thấy khách phù hợp.</div>';
        pmsDkltUpdateFooter();
        return;
    }

    if (PMS_DKLT.viewMode === 'guest') {
        list.innerHTML = `<div class="pms-dklt-guest-grid">${visible.map(pmsDkltGuestRow).join('')}</div>`;
    } else {
        // View theo phòng: gom guest hiển thị theo stay, guest thụt vào trong mỗi phòng.
        const byStay = new Map();
        visible.forEach(g => {
            if (!byStay.has(g.stay_id)) byStay.set(g.stay_id, []);
            byStay.get(g.stay_id).push(g);
        });
        const order = PMS_DKLT.stays
            .filter(s => byStay.has(s.stay_id))
            .map(s => s.stay_id);
        // Phòng còn khách CHƯA xuất lên trước; phòng đã xuất hết xuống dưới.
        const roomFullyExported = (sid) => byStay.get(sid).every(g => g.dklt_exported_at);
        order.sort((a, b) => (roomFullyExported(a) ? 1 : 0) - (roomFullyExported(b) ? 1 : 0));
        list.innerHTML = order.map(sid => {
            const gs = byStay.get(sid);
            const room = gs[0].room_number || '—';
            const allSel = gs.every(g => PMS_DKLT.selected.has(g.guest_id));
            const someSel = gs.some(g => PMS_DKLT.selected.has(g.guest_id));
            const roomExportedCls = roomFullyExported(sid) ? ' exported' : '';
            return `
                <div class="pms-dklt-room-group${roomExportedCls}">
                    <label class="pms-dklt-room-head">
                        <input type="checkbox" data-stay-id="${sid}" ${allSel ? 'checked' : ''}
                            onchange="pmsDkltToggleStay(${sid}, this.checked)"
                            ref="${!allSel && someSel ? 'ind' : ''}" />
                        <span class="pms-dklt-room-num">Phòng ${pmsEscape(room)}</span>
                        <span class="pms-dklt-room-count">${gs.length} khách</span>
                    </label>
                    <div class="pms-dklt-room-guests">
                        ${gs.map(pmsDkltGuestRow).join('')}
                    </div>
                </div>
            `;
        }).join('');
        // Set indeterminate cho checkbox phòng chọn một phần.
        list.querySelectorAll('input[data-stay-id]').forEach(cb => {
            cb.indeterminate = cb.getAttribute('ref') === 'ind';
        });
    }

    pmsDkltUpdateFooter();
    pmsDkltSyncSelectAll();
}

function pmsDkltUpdateFooter() {
    const counter = document.getElementById('pms-dklt-counter');
    const info = document.getElementById('pms-dklt-foot-info');
    const submit = document.getElementById('pms-dklt-submit');

    const total = PMS_DKLT.guests.length;
    const selectedCount = PMS_DKLT.selected.size;
    if (counter) counter.textContent = `${selectedCount}/${total}`;

    let vn = 0, fn = 0;
    PMS_DKLT.guests.forEach(g => {
        if (PMS_DKLT.selected.has(g.guest_id)) {
            if (g.is_foreign) fn += 1; else vn += 1;
        }
    });
    if (info) {
        const scope = PMS_DKLT.scope || 'all';
        if (!selectedCount) {
            info.textContent = 'Chưa chọn khách nào.';
        } else if (scope === 'vn') {
            info.textContent = `Sẽ xuất ${vn} khách Việt Nam.`;
        } else if (scope === 'foreign') {
            info.textContent = `Sẽ xuất ${fn} khách nước ngoài.`;
        } else {
            info.textContent = `Sẽ xuất ${vn} khách VN + ${fn} khách nước ngoài.`;
        }
    }
    if (submit) submit.disabled = selectedCount === 0;
}

function pmsDkltSyncSelectAll() {
    const visible = pmsDkltVisibleGuests();
    const all = document.getElementById('pms-dklt-select-all');
    if (!all || !visible.length) return;
    const allSelected = visible.every(g => PMS_DKLT.selected.has(g.guest_id));
    const someSelected = visible.some(g => PMS_DKLT.selected.has(g.guest_id));
    all.checked = allSelected;
    all.indeterminate = !allSelected && someSelected;
}

function pmsDkltToggleGuest(guestId, checked) {
    if (checked) PMS_DKLT.selected.add(guestId);
    else PMS_DKLT.selected.delete(guestId);
    // Cập nhật trạng thái phòng cha (checkbox + indeterminate) mà không re-render toàn bộ.
    pmsDkltRefreshRoomHeads();
    pmsDkltUpdateFooter();
    pmsDkltSyncSelectAll();
}

function pmsDkltToggleStay(stayId, checked) {
    // Tick/untick tất cả guest ĐANG HIỂN THỊ trong phòng.
    const visibleIds = new Set(pmsDkltVisibleGuests()
        .filter(g => g.stay_id === stayId)
        .map(g => g.guest_id));
    visibleIds.forEach(id => {
        if (checked) PMS_DKLT.selected.add(id);
        else PMS_DKLT.selected.delete(id);
    });
    const list = document.getElementById('pms-dklt-room-list');
    if (list) {
        list.querySelectorAll('input[data-guest-id]').forEach(cb => {
            const id = Number(cb.dataset.guestId);
            if (visibleIds.has(id)) cb.checked = PMS_DKLT.selected.has(id);
        });
    }
    pmsDkltRefreshRoomHeads();
    pmsDkltUpdateFooter();
    pmsDkltSyncSelectAll();
}

function pmsDkltRefreshRoomHeads() {
    const list = document.getElementById('pms-dklt-room-list');
    if (!list || PMS_DKLT.viewMode !== 'room') return;
    const visible = pmsDkltVisibleGuests();
    list.querySelectorAll('input[data-stay-id]').forEach(cb => {
        const sid = Number(cb.dataset.stayId);
        const gs = visible.filter(g => g.stay_id === sid);
        if (!gs.length) return;
        const allSel = gs.every(g => PMS_DKLT.selected.has(g.guest_id));
        const someSel = gs.some(g => PMS_DKLT.selected.has(g.guest_id));
        cb.checked = allSel;
        cb.indeterminate = !allSel && someSel;
    });
}

function pmsDkltToggleAll(checked) {
    const visible = pmsDkltVisibleGuests();
    visible.forEach(g => {
        if (checked) PMS_DKLT.selected.add(g.guest_id);
        else PMS_DKLT.selected.delete(g.guest_id);
    });
    pmsDkltRender();
}

function pmsDkltFilter(q) {
    PMS_DKLT.filter = q || '';
    pmsDkltRender();
}

function pmsDkltSyncScopeButtons() {
    const scope = PMS_DKLT.scope || 'all';
    document.querySelectorAll('#pms-dklt-scope .pms-dklt-scope-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.scope === scope);
    });
}

function pmsDkltSetScope(scope) {
    PMS_DKLT.scope = scope || 'all';
    pmsDkltSyncScopeButtons();
    pmsDkltRender();
}

function pmsDkltSyncViewButtons() {
    const mode = PMS_DKLT.viewMode || 'room';
    document.querySelectorAll('#pms-dklt-view .pms-dklt-scope-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === mode);
    });
}

function pmsDkltSetViewMode(mode) {
    PMS_DKLT.viewMode = (mode === 'guest') ? 'guest' : 'room';
    pmsDkltSyncViewButtons();
    pmsDkltRender();  // giữ nguyên selected
}

function pmsDkltSyncDateButtons() {
    const mode = PMS_DKLT.dateFilter || 'all';
    document.querySelectorAll('#pms-dklt-date .pms-dklt-scope-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.date === mode);
    });
}

function pmsDkltSetDateFilter(mode) {
    PMS_DKLT.dateFilter = mode || 'all';
    pmsDkltSyncDateButtons();
    const customWrap = document.getElementById('pms-dklt-date-custom');
    if (customWrap) customWrap.style.display = (mode === 'custom') ? 'flex' : 'none';
    pmsDkltRender();
}

function pmsDkltSetDateFrom(v) {
    PMS_DKLT.dateFrom = v || null;
    pmsDkltRender();
}

function pmsDkltSetDateTo(v) {
    PMS_DKLT.dateTo = v || null;
    pmsDkltRender();
}

function pmsEscape(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function pmsDkltSubmit() {
    const submit = document.getElementById('pms-dklt-submit');
    if (!submit || submit.disabled) return;

    const format = document.querySelector('input[name="pms-dklt-format"]:checked')?.value || 'excel';
    const ids = Array.from(PMS_DKLT.selected);
    if (!ids.length) {
        pmsToast('Hãy chọn ít nhất một khách để xuất.', false);
        return;
    }

    // Đếm theo nhóm trên tập guest đã chọn.
    let vn = 0, fn = 0;
    PMS_DKLT.guests.forEach(g => {
        if (PMS_DKLT.selected.has(g.guest_id)) {
            if (g.is_foreign) fn += 1; else vn += 1;
        }
    });

    // VN chỉ hỗ trợ Excel; XML chỉ áp dụng cho khách nước ngoài.
    const scope = PMS_DKLT.scope || 'all';
    const wantVn = scope !== 'foreign';
    const wantForeign = scope !== 'vn';

    const groups = [];
    if (format === 'xml') {
        if (fn && wantForeign) groups.push('foreign');
    } else {
        if (vn && wantVn) groups.push('vn');
        if (fn && wantForeign) groups.push('foreign');
    }

    if (!groups.length) {
        let msg;
        if (format === 'xml') {
            msg = 'XML chỉ xuất khách nước ngoài, nhưng phạm vi/khách đã chọn không có khách nước ngoài.';
        } else if (scope === 'vn') {
            msg = 'Khách đã chọn không có khách Việt Nam.';
        } else if (scope === 'foreign') {
            msg = 'Khách đã chọn không có khách nước ngoài.';
        } else {
            msg = 'Khách đã chọn không hợp lệ.';
        }
        pmsToast(msg, false);
        return;
    }

    submit.disabled = true;
    const labelOriginal = submit.innerHTML;
    submit.innerHTML = 'Đang xuất...';

    try {
        for (const g of groups) {
            await pmsDownloadDkltFile(g, format, ids);
        }
        const fmtLabel = format === 'xml' ? 'XML' : 'Excel';
        pmsToast(`Đã xuất ${groups.length} file ĐKLT (${fmtLabel}).`, true);
        // Đánh dấu đã xuất sau khi tải file thành công.
        await pmsDkltMarkExported(ids);
        pmsCloseDkltModal();
    } catch (err) {
        console.error('[DKLT] export failed:', err);
        pmsToast(err?.message || 'Không xuất được file ĐKLT.', false);
    } finally {
        submit.disabled = false;
        submit.innerHTML = labelOriginal;
    }
}

async function pmsDkltMarkExported(guestIds) {
    if (!Array.isArray(guestIds) || !guestIds.length) return;
    try {
        const params = new URLSearchParams();
        if (PMS.branchId) params.set('branch_id', PMS.branchId);
        const url = `/api/pms/dklt/mark-exported${params.toString() ? '?' + params.toString() : ''}`;
        const res = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guest_ids: guestIds }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        // Cập nhật badge tại chỗ trong state để lần render sau hiển thị đúng.
        const nowIso = new Date().toISOString();
        const idSet = new Set(guestIds);
        PMS_DKLT.guests.forEach(g => {
            if (idSet.has(g.guest_id) && !g.dklt_exported_at) g.dklt_exported_at = nowIso;
        });
        (PMS_DKLT.stays || []).forEach(s => {
            (s.guests || []).forEach(g => {
                if (idSet.has(g.guest_id) && !g.dklt_exported_at) g.dklt_exported_at = nowIso;
            });
        });
    } catch (err) {
        console.error('[DKLT] mark-exported failed:', err);
        pmsToast('Đã xuất file nhưng chưa đánh dấu được trạng thái đã xuất.', false);
    }
}

async function pmsDownloadDkltFile(group, format, guestIds) {
    const params = new URLSearchParams();
    if (PMS.branchId) params.set('branch_id', PMS.branchId);
    params.set('group', group);
    params.set('format', format);
    if (Array.isArray(guestIds) && guestIds.length) {
        params.set('guest_ids', guestIds.join(','));
    }
    const url = `/api/pms/dklt/export?${params.toString()}`;
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
            const j = await res.json();
            if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        } catch (_) { /* ignore */ }
        throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    let filename = '';
    const m1 = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const m2 = /filename="?([^";]+)"?/i.exec(cd);
    if (m1) {
        try { filename = decodeURIComponent(m1[1]); } catch (_) { filename = m1[1]; }
    } else if (m2) {
        filename = m2[1];
    }
    if (!filename) {
        const ext = format === 'xml' ? 'xml' : 'xlsx';
        const tag = group === 'foreign' ? 'NN' : 'VN';
        filename = `DKLT_${tag}.${ext}`;
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
        URL.revokeObjectURL(a.href);
        a.remove();
    }, 0);
}


function pmsShowOtaBanner(delta, pending) {
    const existing = document.getElementById('pms-ota-toast');
    if (existing) existing.remove();
    const banner = document.createElement('div');
    banner.id = 'pms-ota-toast';
    banner.className = 'pms-ota-toast';
    banner.innerHTML = `
        <div class="pms-ota-toast-icon">OTA</div>
        <div>
            <strong>Có ${delta} đặt phòng OTA mới</strong>
            <span>Hiện có ${pending} booking chờ xác nhận.</span>
        </div>
        <button type="button" onclick="pmsOpenOtaReservations()">Xem ngay</button>
        <button class="pms-ota-toast-close" type="button" onclick="this.closest('.pms-ota-toast')?.remove()" aria-label="Đóng">×</button>
    `;
    document.body.appendChild(banner);
    window.setTimeout(() => banner.remove(), 10000);
}

function pmsMarkOtaBellActive() {
    const bell = document.getElementById('pms-ota-bell');
    if (!bell) return;
    bell.classList.add('pulse');
    window.setTimeout(() => bell.classList.remove('pulse'), 3000);
}

function pmsOpenOtaReservations() {
    const params = new URLSearchParams({ tab: 'ota', source: 'OTA' });
    const branchId = PMS_OTA_STATUS.branchId || PMS.branchId;
    if (branchId) params.set('branch_id', branchId);
    window.location.href = `/pms/booking?${params.toString()}`;
}

function pmsFormatOtaDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value || '';
    return date.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
}

async function pmsLoadTodayArrivals(silent = false) {
    // Dedup: skip silent calls if just fetched < 5s ago
    if (silent && PMS._arrivalsLoading) return;
    if (silent && PMS._arrivalsLoadedAt && (Date.now() - PMS._arrivalsLoadedAt) < 5000) return;
    const modalOpen = document.getElementById('pms-arrivals-modal')?.classList.contains('show');
    if (!silent && modalOpen) pmsRenderArrivalsLoading();
    PMS._arrivalsLoading = true;
    try {
        const data = pmsDashboardApiData(await pmsApi(pmsArrivalBranchUrl('/api/pms/reservations/today-arrivals')), {});
        PMS.todayArrivals = Array.isArray(data.items) ? data.items : [];
        PMS._arrivalsLoadedAt = Date.now();
        pmsUpdateArrivalBadge();
        if (!silent && modalOpen) {
            pmsRenderArrivalsModal();
        }
    } catch (e) {
        PMS.todayArrivals = PMS.todayArrivals || [];
        pmsUpdateArrivalBadge();
        if (!silent) pmsToast(e.message || 'Không tải được đặt phòng đến hôm nay', false);
    } finally {
        PMS._arrivalsLoading = false;
    }
}

function pmsUpdateArrivalBadge() {
    const count = (PMS.todayArrivals || []).filter(pmsIsConfirmedArrival).length;
    const el = document.getElementById('pms-arrivals-count');
    if (el) el.textContent = String(count);
}

function pmsIsConfirmedArrival(booking) {
    return String(booking?.reservation_status || '').toUpperCase() === 'CONFIRMED';
}

function pmsRoomTypeMatchesBooking(room, booking) {
    const brt = Number(booking.room_type_id || 0);
    const rrt = Number(room.room_type_id || 0);
    if (brt && rrt) return brt === rrt;
    return String(booking.room_type || '').trim().toLowerCase() === String(room.room_type_name || '').trim().toLowerCase();
}

function pmsGetRoomArrivalMatches(room) {
    if (!room) return [];
    return (PMS.todayArrivals || []).filter((booking) => {
        if (!pmsIsConfirmedArrival(booking)) return false;
        if (!pmsRoomTypeMatchesBooking(room, booking)) return false;
        const assigned = Number(booking.assigned_room_id || 0);
        return !assigned || assigned === Number(room.id);
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab & View Switching
// ─────────────────────────────────────────────────────────────────────────────
function pmsSetTab(tab) {
    PMS_CURRENT_TAB = tab;
    const mapBtn = document.getElementById('tab-map');
    const bookBtn = document.getElementById('tab-book');
    const ACTIVE = 'padding:5px 16px;font-size:13px;border-radius:6px;background:#2563eb;color:#fff;font-weight:600;';
    const IDLE   = 'padding:5px 16px;font-size:13px;border-radius:6px;background:transparent;color:#6b7280;font-weight:600;';
    if (mapBtn && bookBtn) {
        mapBtn.style.cssText = tab === 'map' ? ACTIVE : IDLE;
        bookBtn.style.cssText = tab === 'book' ? ACTIVE : IDLE;
    }

    const ss = document.getElementById('smart-search');
    const sr = document.getElementById('search-results');
    const cal = document.getElementById('calendar-view');
    const floors = document.getElementById('pms-floors');
    const loading = document.getElementById('pms-loading');
    const viewToggles = document.getElementById('view-toggles');

    if (tab === 'book') {
        if (ss) ss.style.display = 'block';
        if (sr) sr.style.display = (sr.style.display !== 'none') ? 'block' : 'none';
        if (cal) cal.classList.remove('show');
        if (floors) floors.style.display = 'none';
        if (loading) loading.style.display = 'none';
        if (viewToggles) viewToggles.style.display = 'none';
    } else {
        if (ss) ss.style.display = 'block';
        if (sr) sr.style.display = 'none';
        if (cal) cal.classList.remove('show');
        if (viewToggles) viewToggles.style.display = 'flex';
        if (floors || loading) pmsRender();
    }
}

function pmsSetView(mode) {
    PMS_VIEW_MODE = mode;
    const floorBtn = document.getElementById('view-floor');
    const typeBtn  = document.getElementById('view-type');
    if (floorBtn && typeBtn) {
        floorBtn.classList.toggle('active', mode === 'floor');
        typeBtn.classList.toggle('active', mode === 'type');
    }
    pmsRender();
}

function pmsSetDensity(mode) {
    PMS_DENSITY_MODE = mode;
    localStorage.setItem('pms-density', mode);
    const floorsEl = document.getElementById('pms-floors');
    if (floorsEl) {
        floorsEl.classList.toggle('pms-view-compact', mode === 'compact');
    }
    const stdBtn = document.getElementById('dens-standard');
    const cmpBtn = document.getElementById('dens-compact');
    if (stdBtn && cmpBtn) {
        stdBtn.classList.toggle('active', mode === 'standard');
        cmpBtn.classList.toggle('active', mode === 'compact');
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// Render Room Map
// ─────────────────────────────────────────────────────────────────────────────
function pmsRender() {
    const loadEl   = document.getElementById('pms-loading');
    const floorsEl = document.getElementById('pms-floors');
    const sortedF  = Object.keys(PMS.floors).map(Number).sort((a,b) => a-b);

    // Build flat room list & roomMap
    const allRooms = sortedF.flatMap(f => PMS.floors[f]);
    PMS.roomMap = {};
    allRooms.forEach(r => PMS.roomMap[r.id] = r);

    if (!floorsEl) return;

    if (!sortedF.length) {
        if (PMS._loading && !PMS._roomsLoaded) {
            if (loadEl) loadEl.style.display = 'block';
            floorsEl.style.display = 'none';
            return;
        }
        floorsEl.innerHTML = `<div class="pms-empty">
            <div class="pms-empty-icon">${PMS_SVG.bed}</div>
            <h3 class="pms-empty-title">Chưa có phòng nào</h3>
            <p class="pms-empty-desc">Thiết lập danh sách phòng để bắt đầu quản lý sơ đồ phòng, nhận khách và theo dõi lưu trú.</p>
            <a class="pms-empty-btn" href="/pms/setup?tab=rooms">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>
              Thiết lập phòng ngay
            </a>
        </div>`;
        ['cnt-occ','cnt-vac','cnt-all'].forEach(id => {
            const el = document.getElementById(id); if (el) el.textContent = '0';
        });
        if (loadEl) loadEl.style.display = 'none'; floorsEl.style.display = 'block'; return;
    }

    const totalOcc = allRooms.filter(r => r.status === 'OCCUPIED').length;
    document.getElementById('cnt-occ').textContent = totalOcc;
    document.getElementById('cnt-vac').textContent = allRooms.length - totalOcc;
    document.getElementById('cnt-all').textContent = allRooms.length;

    let html = '';

    if (PMS_VIEW_MODE === 'floor') {
        // Group by floor
        for (const f of sortedF) {
            const rooms = PMS.floors[f];
            const o = rooms.filter(r => r.status === 'OCCUPIED').length;
            html += `<div class="f-block">
              <div class="f-head">
                <span class="f-name">${PMS_SVG.building} Tầng ${f}</span>
                <span class="f-stat">Đang ở: <b>${o}</b> &nbsp;&bull;&nbsp; Trống: <b>${rooms.length - o}</b></span>
              </div>
              <div class="f-rooms">${rooms.map(r => pmsRoomCard(r)).join('')}</div>
            </div>`;
        }
    } else {
        // Group by room type
        const typeMap = {};
        allRooms.forEach(r => {
            const key = (r.room_type_name && r.room_type_name !== '—') ? r.room_type_name : '— Chưa phân hạng';
            if (!typeMap[key]) typeMap[key] = [];
            typeMap[key].push(r);
        });
        const typeKeys = Object.keys(typeMap).sort((a,b) => {
            if (a.startsWith('—')) return 1;
            if (b.startsWith('—')) return -1;
            return a.localeCompare(b, 'vi');
        });
        const COLORS = [
            ['#dbeafe','#1d4ed8'], ['#dcfce7','#15803d'], ['#fef3c7','#b45309'],
            ['#ede9fe','#7c3aed'], ['#fee2e2','#b91c1c'], ['#f0f9ff','#0369a1'],
        ];
        typeKeys.forEach((typeName, idx) => {
            const rooms = typeMap[typeName];
            const o = rooms.filter(r => r.status === 'OCCUPIED').length;
            
            // Find price for room type
            const rt = (PMS.roomTypes || []).find(t => t.name === typeName);
            const priceHtml = rt ? `<span class="f-price">${pmsMoney(rt.price_per_night)}</span>` : '';

            html += `<div class="f-block">
              <div class="f-head">
                <span class="f-name">${typeName} ${priceHtml}</span>
                <span class="f-stat">${rooms.length} phòng &nbsp;&bull;&nbsp; Đang ở: <b>${o}</b> &nbsp;&bull;&nbsp; Trống: <b>${rooms.length - o}</b></span>
              </div>
              <div class="f-rooms">${rooms.map(r => pmsRoomCard(r)).join('')}</div>
            </div>`;
        });
    }

    floorsEl.innerHTML = html;
    loadEl.style.display = 'none';
    floorsEl.style.display = 'block';
    pmsTickLiveCounters();
}

// ─────────────────────────────────────────────────────────────────────────────
// Font Awesome SVG Icons (solid, from FA 6.7 free)
// ─────────────────────────────────────────────────────────────────────────────
const FA = {
    broom: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 576 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M566.6 54.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0l-192 192-34.7-34.7c-4.2-4.2-10-6.6-16-6.6c-12.5 0-22.6 10.1-22.6 22.6l0 29.1L364.3 320l29.1 0c12.5 0 22.6-10.1 22.6-22.6c0-6-2.4-11.8-6.6-16l-34.7-34.7 192-192zM341.1 353.4L222.6 234.9c-42.7-3.7-85.2 11.7-115.8 42.3l-8 8C76.5 307.5 64 337.7 64 369.2c0 6.8 7.1 11.2 13.2 8.2l51.1-25.5c5-2.5 9.5 4.1 5.4 7.9L7.3 473.4C2.7 477.6 0 483.6 0 489.9C0 502.1 9.9 512 22.1 512l173.3 0c38.8 0 75.9-15.4 103.4-42.8c30.6-30.6 45.9-73.1 42.3-115.8z"/></svg>',
    spraySparkle: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M96 32l0 96 128 0 0-96c0-17.7-14.3-32-32-32L128 0C110.3 0 96 14.3 96 32zm0 128c-53 0-96 43-96 96L0 464c0 26.5 21.5 48 48 48l224 0c26.5 0 48-21.5 48-48l0-208c0-53-43-96-96-96L96 160zm64 96a80 80 0 1 1 0 160 80 80 0 1 1 0-160zM384 48c0-1.4-1-3-2.2-3.6L352 32 339.6 2.2C339 1 337.4 0 336 0s-3 1-3.6 2.2L320 32 290.2 44.4C289 45 288 46.6 288 48c0 1.4 1 3 2.2 3.6L320 64l12.4 29.8C333 95 334.6 96 336 96s3-1 3.6-2.2L352 64l29.8-12.4C383 51 384 49.4 384 48zm76.4 45.8C461 95 462.6 96 464 96s3-1 3.6-2.2L480 64l29.8-12.4C511 51 512 49.4 512 48c0-1.4-1-3-2.2-3.6L480 32 467.6 2.2C467 1 465.4 0 464 0s-3 1-3.6 2.2L448 32 418.2 44.4C417 45 416 46.6 416 48c0 1.4 1 3 2.2 3.6L448 64l12.4 29.8zm7.2 100.4c-.6-1.2-2.2-2.2-3.6-2.2s-3 1-3.6 2.2L448 224l-29.8 12.4c-1.2 .6-2.2 2.2-2.2 3.6c0 1.4 1 3 2.2 3.6L448 256l12.4 29.8c.6 1.2 2.2 2.2 3.6 2.2s3-1 3.6-2.2L480 256l29.8-12.4c1.2-.6 2.2-2.2 2.2-3.6c0-1.4-1-3-2.2-3.6L480 224l-12.4-29.8zM448 144c0-1.4-1-3-2.2-3.6L416 128 403.6 98.2C403 97 401.4 96 400 96s-3 1-3.6 2.2L384 128l-29.8 12.4c-1.2 .6-2.2 2.2-2.2 3.6c0 1.4 1 3 2.2 3.6L384 160l12.4 29.8c.6 1.2 2.2 2.2 3.6 2.2s3-1 3.6-2.2L416 160l29.8-12.4c1.2-.6 2.2-2.2 2.2-3.6z"/></svg>',
    lock: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 448 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M144 144l0 48 160 0 0-48c0-44.2-35.8-80-80-80s-80 35.8-80 80zM80 192l0-48C80 64.5 144.5 0 224 0s144 64.5 144 144l0 48 16 0c35.3 0 64 28.7 64 64l0 192c0 35.3-28.7 64-64 64L64 512c-35.3 0-64-28.7-64-64L0 256c0-35.3 28.7-64 64-64l16 0z"/></svg>',
    lockOpen: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 576 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M352 144c0-44.2 35.8-80 80-80s80 35.8 80 80l0 48c0 17.7 14.3 32 32 32s32-14.3 32-32l0-48C576 64.5 511.5 0 432 0S288 64.5 288 144l0 48L64 192c-35.3 0-64 28.7-64 64L0 448c0 35.3 28.7 64 64 64l320 0c35.3 0 64-28.7 64-64l0-192c0-35.3-28.7-64-64-64l-32 0 0-48z"/></svg>',
    circleCheck: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512zM369 209L241 337c-9.4 9.4-24.6 9.4-33.9 0l-64-64c-9.4-9.4-9.4-24.6 0-33.9s24.6-9.4 33.9 0l47 47L335 175c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9z"/></svg>',
    bellConcierge: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M216 64c-13.3 0-24 10.7-24 24s10.7 24 24 24l16 0 0 33.3C119.6 157.2 32 252.4 32 368l448 0c0-115.6-87.6-210.8-200-222.7l0-33.3 16 0c13.3 0 24-10.7 24-24s-10.7-24-24-24l-40 0-40 0zM24 400c-13.3 0-24 10.7-24 24s10.7 24 24 24l464 0c13.3 0 24-10.7 24-24s-10.7-24-24-24L24 400z"/></svg>',
    wrench: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M352 320c88.4 0 160-71.6 160-160c0-15.3-2.2-30.1-6.2-44.2c-3.1-10.8-16.4-13.2-24.3-5.3l-76.8 76.8c-3 3-7.1 4.7-11.3 4.7L336 192c-8.8 0-16-7.2-16-16l0-57.4c0-4.2 1.7-8.3 4.7-11.3l76.8-76.8c7.9-7.9 5.4-21.2-5.3-24.3C382.1 2.2 367.3 0 352 0C263.6 0 192 71.6 192 160c0 19.1 3.4 37.5 9.5 54.5L19.9 396.1C7.2 408.8 0 426.1 0 444.1C0 481.6 30.4 512 67.9 512c18 0 35.3-7.2 48-19.9L297.5 310.5c17 6.2 35.4 9.5 54.5 9.5zM80 408a24 24 0 1 1 0 48 24 24 0 1 1 0-48z"/></svg>',
    soap: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M64 240c-35.3 0-64 28.7-64 64V448c0 35.3 28.7 64 64 64H320c35.3 0 64-28.7 64-64V304c0-35.3-28.7-64-64-64H64zM240 320a48 48 0 1 1 0 96 48 48 0 1 1 0-96zM464 224a16 16 0 1 1 0 32 16 16 0 1 1 0-32zm48 40a8 8 0 1 1 0 16 8 8 0 1 1 0-16zm-48-80a24 24 0 1 1 0 48 24 24 0 1 1 0-48zm-80-64a32 32 0 1 1 0 64 32 32 0 1 1 0-64zm-56-32c-39.8 0-72-32.2-72-72s32.2-72 72-72s72 32.2 72 72c0 4.4-.4 8.7-1.1 12.9c13.7 2.1 24.1 14 24.1 28.4c0 10.9-6.1 20.4-15.1 25.2c1.7 4.2 2.6 8.7 2.6 13.5c0 19.9-16.1 36-36 36c-11.4 0-21.5-5.3-28-13.6c-4.9 5.8-11.6 9.6-19.2 9.6c-1.1 0-2.3 0-3.4-.1z"/></svg>',
    warn: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M256 32c14.2 0 27.3 7.5 34.5 19.8l216 368c7.3 12.4 7.3 27.7 .2 40.1S486.3 480 472 480L40 480c-14.3 0-27.6-7.7-34.7-20.1s-7-27.8 .3-40.1l216-368C228.7 39.5 241.8 32 256 32zm0 128c-13.3 0-24 10.7-24 24V296c0 13.3 10.7 24 24 24s24-10.7 24-24V184c0-13.3-10.7-24-24-24zm32 224a32 32 0 1 0-64 0 32 32 0 1 0 64 0z"/></svg>',
    ban: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512zM175 175c9.4-9.4 24.6-9.4 33.9 0l128 128c9.4 9.4 9.4 24.6 0 33.9s-24.6 9.4-33.9 0L175 209c-9.4-9.4-9.4-24.6 0-33.9z"/></svg>',
    key: (w,h,cls) => '<svg width="'+w+'" height="'+h+'" viewBox="0 0 512 512" fill="currentColor"'+(cls?' class="'+cls+'"':'')+'><path d="M336 352c97.2 0 176-78.8 176-176S433.2 0 336 0S160 78.8 160 176c0 18.7 2.9 36.8 8.3 53.7L7 391.1C2.5 395.6 0 401.7 0 408.1V448c0 35.3 28.7 64 64 64h40c8.8 0 16-7.2 16-16V480h32c8.8 0 16-7.2 16-16V448h32c8.8 0 16-7.2 16-16V400c0-11.4-6.1-21.7-16-27.3V353.1c11.4-5.6 18.7-17.3 18.7-30.4v-43c22.1 11.4 47.1 17.1 72.8 17.1c0 23.3-10.4 46.1-28.5 62.1c-12.7 11.2-14.1 30.5-2.9 43.1s30.5 14.1 43.1 2.9C314.8 385.9 336 370 336 352zM432 176a48 48 0 1 1 -96 0 48 48 0 1 1 96 0z"/></svg>',
};

// ─────────────────────────────────────────────────────────────────────────────
// Room Card Component
// ─────────────────────────────────────────────────────────────────────────────
function pmsRoomCard(r) {
    const isOcc = r.status === 'OCCUPIED', s = r.stay;
    const cond = r.condition || 'CLEAN';

    // Card class
    let cls = 'rc-vac';
    if (isOcc) {
        cls = 'rc-occ';
        if (cond === 'CLEANING') cls += ' rc-cleaning';
    } else {
        if (cond === 'DIRTY')            cls = 'rc-dirty';
        else if (cond === 'CLEANING')    cls = 'rc-cleaning';
        else if (cond === 'MAINTENANCE') cls = 'rc-maint';
        else                             cls = 'rc-vac';
    }

    // Badge click
    const canCheckin = !isOcc && cond === 'CLEAN';
    const badgeClick = isOcc && s
        ? "openRoomDetail(" + s.id + ",'" + r.room_number + "')"
        : (canCheckin ? "openCI(" + r.id + ")" : (!isOcc && cond !== 'CLEAN' ? "pmsQuickClean(" + r.id + ")" : ''));

    // ── Info section ──
    let info;
    if (isOcc && s) {
        const checkInTime = pmsFdtLong(s.check_in_at);
        const checkOutTime = s.check_out_at ? pmsFdtLong(s.check_out_at) : null;
        const isCheckoutSoon = s.check_out_at && (pmsParseDate(s.check_out_at) - new Date()) < 3600000;
        const checkInMs = pmsParseDate(s.check_in_at).getTime();
        const stayDurationStr = pmsFormatDurLive(Number.isFinite(checkInMs) ? checkInMs : s.check_in_at);
        const checkInMsAttr = Number.isFinite(checkInMs) ? String(checkInMs) : '';
        const pricingConfigJson = r.pricing_config ? pmsEscapeHtml(JSON.stringify(r.pricing_config)) : '';

        // Compact duration string for Ultra-Compact view
        let compactDur = '';
        if (checkInMs) {
            const diffMs = new Date() - checkInMs;
            const diffHrs = diffMs / 3600000;
            if (diffHrs >= 24) {
                compactDur = Math.floor(diffHrs / 24) + 'd';
            } else {
                const h = Math.floor(diffHrs);
                const m = Math.floor((diffMs % 3600000) / 60000);
                compactDur = String(h).padStart(2, '0') + 'h' + String(m).padStart(2, '0');
            }
        }

        info = '<div class="ri-stay-vertical"'
            + ' data-compact-dur="' + compactDur + '"'
            + ' data-checkin-ms="' + checkInMsAttr + '"'
            + ' data-checkin="' + pmsEscapeHtml(String(s.check_in_at || '')) + '"'
            + ' data-checkout="' + pmsEscapeHtml(String(s.check_out_at || '')) + '"'
            + ' data-stay-type="' + (s.stay_type || 'NIGHT') + '"'
            + ' data-pricing-config="' + pricingConfigJson + '">'
            + '<div class="ri-v-row active">'
            +   '<span class="ri-label">Start:</span>'
            +   '<span class="ri-value">' + checkInTime + '</span>'
            + '</div>'
            + (checkOutTime ? '<div class="ri-v-row ri-v-row--co">'
            +   '<span class="ri-label">End:</span>'
            +   '<span class="ri-value checkout ' + (isCheckoutSoon ? 'ri-soon' : '') + '">' + checkOutTime + '</span>'
            + '</div>' : '')
            + '<div class="ri-v-row ri-v-row--live">'
            +   '<span class="ri-label">Time:</span>'
            +   '<span class="ri-value nights live-counter">' + stayDurationStr + '</span>'
            + '</div>'
            + '<div class="ri-v-row ri-v-row--countdown" style="display:none;">'
            +   '<span class="ri-label">Due:</span>'
            +   '<span class="ri-value countdown-counter">—</span>'
            + '</div>'
            + '</div>';
    } else {
        info = '<div class="ri-emp">'
            + '<div class="ri-emp-icon">'
            +   '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16Z"/><path d="M2 10h20"/><path d="M6 6v4"/></svg>'
            + '</div>'
            + '<span class="ri-emp-text">Phòng trống</span>'
            + '</div>';
    }

    // ── Actions (rc-actions) ──
    let acts = '';
    if (isOcc && s) {
        acts = '<button class="ra-btn ra-co" onclick="openCO(' + s.id + ',\'' + r.room_number + '\')" title="Trả phòng">'
            + PMS_SVG.logOut + '</button>'
            + '<button class="ra-btn ra-ag" onclick="openAG(' + s.id + ',\'' + r.room_number + '\')" title="Thêm khách">'
            + PMS_SVG.addUser + '</button>'
            + '<button class="ra-btn ra-tf" onclick="openTF(' + s.id + ',\'' + r.room_number + '\',\'' + (r.room_type_name || '').replace(/'/g, "\\'") + '\',' + (r.price_per_night || 0) + ')" title="Đổi phòng">'
            + PMS_SVG.swap + '</button>';
    } else if (canCheckin) {
        const arrivalMatches = pmsGetRoomArrivalMatches(r);
        acts = '<button class="ra-btn ra-ci" onclick="openCI(' + r.id + ')" title="Check-in">'
            + PMS_SVG.logIn + '</button>';
        if (arrivalMatches.length) {
            acts += '<button class="ra-btn ra-bk" onclick="pmsOpenTodayArrivals(' + r.id + ')" title="Nhận phòng từ đặt trước">'
                + '<span class="ra-bk-count">' + arrivalMatches.length + '</span>'
                + PMS_SVG.calendar + '</button>';
        }
    }

    // ── Residents (rc-residents): condition status OR guest list ──
    let residentsContent = '';
    // Any non-CLEAN condition → show big centered status (same layout for all)
    if (cond !== 'CLEAN') {
        var condCfg = {
            DIRTY:       { icon: FA.soap(20, 20),          text: 'PHÒNG CHƯA DỌN',    cls: 'rc-cond-dirty' },
            CLEANING:    { icon: FA.soap(20, 20),          text: 'Yêu cầu dọn phòng', cls: 'rc-cond-cleaning' },
            MAINTENANCE: { icon: FA.key(20, 20),           text: 'PHÒNG ĐANG KHOÁ',   cls: 'rc-cond-maint' },
        };
        var cfg = condCfg[cond];
        if (cfg) {
            var clickAttr = !isOcc ? ' onclick="pmsQuickClean(' + r.id + ')" style="cursor:pointer;" title="Click để chuyển về Sẵn sàng"' : '';
            residentsContent = '<div class="rc-cond-status rc-cond-status--big ' + cfg.cls + '"' + clickAttr + '>'
                + '<span class="rc-cond-icon">' + cfg.icon + '</span>'
                + '<span class="rc-cond-text">' + cfg.text + '</span>'
                + '</div>';
        }
    } else if (isOcc && s && s.guests && s.guests.length > 0) {
        var sortedGuests = [...s.guests].sort(function(a, b) { return a.id - b.id; });
        residentsContent = sortedGuests.map(function(g) {
            return '<div class="rc-resident">'
                + '<div class="rc-resident-icon">' + pmsGenderIcon(g.gender) + '</div>'
                + '<span class="rc-resident-name">' + pmsEscapeHtml(g.full_name) + '</span>'
                + '<span class="rc-resident-birth">' + PMS_SVG.calendar + ' ' + pmsFdate(g.birth_date) + '</span>'
                + '</div>';
        }).join('');
    } else {
        residentsContent = '<div class="rc-residents-empty"><span>Chưa có khách</span></div>';
    }
    var residentsHtml = '<div class="rc-residents">' + residentsContent + '</div>';

    const compactDurAttr = (isOcc && s && info.includes('data-compact-dur="')) 
        ? info.match(/data-compact-dur="([^"]+)"/)[1] 
        : '';

    // Cleaning icon for compact mode
    const compactCleanIcon = (cond === 'CLEANING') 
        ? '<div class="rc-badge-icon rc-badge-icon--cleaning">' + FA.soap(12, 12) + '</div>' 
        : '';

    const stayIdAttr = (isOcc && s) ? ' data-stay-id="' + s.id + '"' : '';

    return '<div class="rc-wrap" id="room-card-id-' + r.id + '"' + stayIdAttr + ' data-room-num="' + r.room_number + '" oncontextmenu="pmsRoomCtxMenu(event, ' + r.id + ', \'' + cond + '\', ' + isOcc + ')">'
        + '<div class="rc ' + cls + '" data-stay-dur="' + compactDurAttr + '">'
        +   compactCleanIcon
        +   '<div class="rc-top">'
        +     '<div class="rc-badge" onclick="' + badgeClick + '">'
        +       '<div class="rb-num">' + r.room_number + '</div>'
        +       '<div class="rb-type">' + (r.room_type_name || '—') + '</div>'
        +       '<div class="rb-cap">' + PMS_SVG.user + ' ' + (isOcc && s ? s.guest_count : 0) + '/' + r.max_guests + '</div>'
        +     '</div>'
        +     '<div class="rc-info">' + info + '</div>'
        +     '<div class="rc-actions">' + acts + '</div>'
        +   '</div>'
        +   residentsHtml
        + '</div>'
        + '</div>';
}

// Export functions globally
window.pmsLoadRooms = pmsLoadRooms;
window.pmsChangeBranch = pmsChangeBranch;
window.pmsSetTab = pmsSetTab;
window.pmsSetView = pmsSetView;
window.pmsRender = pmsRender;

function pmsQuickClean(roomId) {
    pmsToggleRoomCondition(roomId, 'CLEAN');
}
window.pmsQuickClean = pmsQuickClean;

async function pmsToggleRoomCondition(roomId, condition) {
    try {
        pmsSetRoomLoading(roomId);
        const data = new FormData();
        data.append('condition', condition);
        const res = await fetch('/api/pms/rooms/' + roomId + '/condition', {
            method: 'POST',
            body: data
        });
        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Lỗi hệ thống');
        }
        if (res.ok) {
            const condLabels = { CLEAN:'Phòng dọn xong', DIRTY:'Phòng chưa dọn', CLEANING:'Yêu cầu dọn phòng', MAINTENANCE:'Phòng đang khóa' };
            if (typeof pmsToast === 'function') pmsToast(condLabels[condition] || 'Cập nhật thành công', true);
            // Phản ánh ngay trạng thái server vừa xác nhận và render lại để gỡ overlay,
            // không phụ thuộc vào pmsLoadRooms (có thể bị guard dedup/_loading bỏ qua → overlay treo).
            if (PMS.roomMap && PMS.roomMap[roomId]) PMS.roomMap[roomId].condition = condition;
            pmsRender();
            pmsLoadRooms(undefined, true);
        }
    } catch(err) {
        if (typeof pmsToast === 'function') pmsToast(err.message, false);
        pmsRender();
        pmsLoadRooms(undefined, true);
    }
}
window.pmsToggleRoomCondition = pmsToggleRoomCondition;

// ─────────────────────────────────────────────────────────────────────────────
// Right-click Context Menu for Room Condition
// ─────────────────────────────────────────────────────────────────────────────
function pmsRoomCtxMenu(e, roomId, currentCond, isOcc) {
    e.preventDefault();
    // Remove existing menu
    const old = document.getElementById('pms-ctx-menu');
    if (old) old.remove();

    const items = [];
    if (isOcc) {
        // Occupied: toggle cleaning request
        if (currentCond === 'CLEANING') {
            items.push({ icon: FA.circleCheck(16,16), label: 'Phòng dọn xong', cond: 'CLEAN', color: '#10b981' });
        } else {
            items.push({ icon: FA.soap(16,16), label: 'Yêu cầu dọn phòng', cond: 'CLEANING', color: '#ca8a04' });
        }
    } else {
        // Vacant: show all relevant options
        if (currentCond !== 'CLEAN')       items.push({ icon: FA.circleCheck(16,16), label: 'Phòng sạch sẵn sàng', cond: 'CLEAN',       color: '#10b981' });
        if (currentCond !== 'DIRTY')       items.push({ icon: FA.soap(16,16),        label: 'Phòng chưa dọn',      cond: 'DIRTY',       color: '#ca8a04' });
        if (currentCond !== 'MAINTENANCE') items.push({ icon: FA.key(16,16),         label: 'Phòng đang khóa',     cond: 'MAINTENANCE', color: '#ef4444' });
    }

    if (!items.length) return;

    const menu = document.createElement('div');
    menu.id = 'pms-ctx-menu';
    menu.style.cssText = 'position:fixed;z-index:9999;background:#fff;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.18);padding:6px 0;min-width:210px;animation:pms-ctx-in .15s ease;';
    menu.innerHTML = items.map(it =>
        '<div class="pms-ctx-item" data-room="' + roomId + '" data-cond="' + it.cond + '" style="padding:10px 16px;cursor:pointer;font-size:13px;font-weight:600;color:' + it.color + ';display:flex;align-items:center;gap:10px;transition:background .12s;"'
        + ' onmouseenter="this.style.background=\'#f3f4f6\'" onmouseleave="this.style.background=\'transparent\'">'
        + it.icon + ' <span>' + it.label + '</span></div>'
    ).join('');

    // Dark mode
    if (document.documentElement.classList.contains('dark')) {
        menu.style.background = '#1e293b';
        menu.querySelectorAll('.pms-ctx-item').forEach(el => {
            el.onmouseenter = function(){ this.style.background = '#334155'; };
            el.onmouseleave = function(){ this.style.background = 'transparent'; };
        });
    }

    document.body.appendChild(menu);

    // Position: keep within viewport
    const bw = window.innerWidth, bh = window.innerHeight;
    let x = e.clientX, y = e.clientY;
    const mw = menu.offsetWidth, mh = menu.offsetHeight;
    if (x + mw > bw) x = bw - mw - 8;
    if (y + mh > bh) y = bh - mh - 8;
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';

    // Click handler
    menu.addEventListener('click', function(ev) {
        const item = ev.target.closest('.pms-ctx-item');
        if (!item) return;
        const rid = parseInt(item.dataset.room);
        const cond = item.dataset.cond;
        menu.remove();
        pmsToggleRoomCondition(rid, cond);
    });

    // Close on outside click or scroll
    const closeMenu = () => { menu.remove(); document.removeEventListener('click', closeMenu); document.removeEventListener('scroll', closeMenu, true); };
    setTimeout(() => {
        document.addEventListener('click', closeMenu);
        document.addEventListener('scroll', closeMenu, true);
    }, 50);
}
window.pmsRoomCtxMenu = pmsRoomCtxMenu;

// Smooth loading helper
function pmsSetRoomLoading(roomId, roomNum) {
    let el = null;
    if (roomNum) el = document.querySelector(`.rc-wrap[data-room-num="${roomNum}"]`);
    else if (roomId) el = document.getElementById(`room-card-id-${roomId}`);
    
    if (el) {
        el.style.position = 'relative';
        if (!el.querySelector('.room-loading-overlay')) {
            el.insertAdjacentHTML('beforeend', `
                <div class="room-loading-overlay" style="position: absolute; top:0; left:0; right:0; bottom:0; background:rgba(255,255,255,0.85); display:flex; align-items:center; justify-content:center; border-radius:12px; z-index:10; backdrop-filter:blur(2px);">
                    <svg class="pms-spinner" viewBox="0 0 50 50" style="width:30px; height:30px; animation: pms-rotate 2s linear infinite;">
                        <circle cx="25" cy="25" r="20" fill="none" stroke="#2563eb" stroke-width="4" stroke-linecap="round" style="animation: pms-dash 1.5s ease-in-out infinite;"></circle>
                    </svg>
                </div>
            `);
            // Add keyframes if not exists
            if (!document.getElementById('pms-spinner-style')) {
                const style = document.createElement('style');
                style.id = 'pms-spinner-style';
                style.textContent = `
                    @keyframes pms-rotate { 100% { transform: rotate(360deg); } }
                    @keyframes pms-dash {
                        0% { stroke-dasharray: 1, 150; stroke-dashoffset: 0; }
                        50% { stroke-dasharray: 90, 150; stroke-dashoffset: -35; }
                        100% { stroke-dasharray: 90, 150; stroke-dashoffset: -124; }
                    }
                `;
                document.head.appendChild(style);
            }
        }
    }
}
window.pmsSetRoomLoading = pmsSetRoomLoading;

function pmsTickLiveCounters() {
    const containers = document.querySelectorAll('.ri-stay-vertical');
    if (!containers.length) return;

    const now = Date.now();

    containers.forEach(el => {
        const checkOutAt    = el.dataset.checkout;           // ISO string hoặc rỗng
        const hasCheckOut   = !!(checkOutAt && checkOutAt !== 'null' && checkOutAt !== 'undefined');
        const liveRow       = el.querySelector('.ri-v-row--live');
        const cdRow         = el.querySelector('.ri-v-row--countdown');
        const counterEl     = liveRow?.querySelector('.live-counter');
        const cdEl          = cdRow?.querySelector('.countdown-counter');

        // Toggle: có checkout time → Due countdown | không có → live counter
        if (liveRow) liveRow.style.display  = hasCheckOut ? 'none' : '';
        if (cdRow)   cdRow.style.display    = hasCheckOut ? ''    : 'none';

        // ── Anchor: thời gian check-in ms ─────────────────────────────────
        let anchorMs = NaN;

        const rawMs = el.dataset.checkinMs;
        if (rawMs && rawMs !== '' && rawMs !== 'null' && rawMs !== 'undefined') {
            const n = Number(rawMs);
            if (Number.isFinite(n) && n > 0) anchorMs = n;
        }

        if (!Number.isFinite(anchorMs)) {
            let checkinStr = el.dataset.checkin;
            if (checkinStr && checkinStr !== '' && checkinStr !== 'null') {
                checkinStr = checkinStr.replace(/(Z|[+-]\d{2}(:\d{2})?)$/i, '');
                checkinStr = checkinStr.replace(' ', 'T');
                const parsed = pmsParseDate(checkinStr).getTime();
                if (Number.isFinite(parsed) && parsed > 0) anchorMs = parsed;
            }
        }

        if (!Number.isFinite(anchorMs)) {
            if (counterEl) counterEl.textContent = '—';
            if (cdEl) cdEl.textContent = '—';
            return;
        }

        const p2 = n => String(n).padStart(2, '0');

        // ── Live: đếm giờ đã ở (không có checkout time) ───────────────────
        if (!hasCheckOut && counterEl) {
            const ms = now - anchorMs;
            if (ms < 0) { counterEl.textContent = '00:00:00'; return; }
            const days  = Math.floor(ms / 86400000);
            const remMs = ms % 86400000;
            const h    = Math.floor(remMs / 3600000);
            const m    = Math.floor((remMs % 3600000) / 60000);
            const s    = Math.floor((remMs % 60000) / 1000);
            counterEl.textContent = days > 0 ? `${days}N ${p2(h)}:${p2(m)}:${p2(s)}` : `${p2(h)}:${p2(m)}:${p2(s)}`;
        }

        // ── Due countdown: đếm ngược theo giây đến checkout time ──────────
        if (!hasCheckOut || !cdEl) return;

        const coMs = pmsParseDate(checkOutAt).getTime();
        if (!Number.isFinite(coMs)) { cdEl.textContent = '—'; return; }

        const diffMs = coMs - now;

        if (diffMs > 0) {
            const cd = Math.floor(diffMs / 86400000);
            const cr = diffMs % 86400000;
            const ch = Math.floor(cr / 3600000);
            const cm = Math.floor((cr % 3600000) / 60000);
            const cs = Math.floor((cr % 60000) / 1000);
            cdEl.textContent = cd > 0
                ? `${cd}D ${p2(ch)}:${p2(cm)}:${p2(cs)}`
                : `${p2(ch)}:${p2(cm)}:${p2(cs)}`;
            cdEl.classList.remove('cd-overdue');
        } else {
            // Quá giờ checkout — đếm tiếp giờ quá
            const overMs = Math.abs(diffMs);
            const od = Math.floor(overMs / 86400000);
            const or = overMs % 86400000;
            const oh = Math.floor(or / 3600000);
            const om = Math.floor((or % 3600000) / 60000);
            const os = Math.floor((or % 60000) / 1000);
            cdEl.textContent = od > 0
                ? `+${od}D ${p2(oh)}:${p2(om)}:${p2(os)}`
                : `+${p2(oh)}:${p2(om)}:${p2(os)}`;
            cdEl.classList.add('cd-overdue');
        }
    });
}

function pmsStartLiveCounters() {
    // Clear previous interval to prevent duplicates
    if (PMS.liveInterval) {
        clearInterval(PMS.liveInterval);
        PMS.liveInterval = null;
    }

    // Immediate first tick
    pmsTickLiveCounters();

    // 1-second interval for ticking
    PMS.liveInterval = setInterval(pmsTickLiveCounters, 1000);
}

window.pmsTickLiveCounters = pmsTickLiveCounters;
window.pmsStartLiveCounters = pmsStartLiveCounters;

function pmsEnsureArrivalsModal() {
    let modal = document.getElementById('pms-arrivals-modal');
    if (modal) return modal;
    document.body.insertAdjacentHTML('beforeend', `
        <div id="pms-arrivals-modal" class="pms-arrivals-modal">
          <div class="pms-arrivals-dialog">
            <div class="pms-arrivals-head">
              <div>
                <h3 id="pms-arrivals-title">Đặt phòng đến hôm nay</h3>
                <p id="pms-arrivals-sub">Các đặt phòng có ngày nhận là hôm nay, sẵn sàng gán phòng và nhận ngay.</p>
              </div>
              <button type="button" class="pms-arrivals-close" onclick="pmsCloseTodayArrivals()">×</button>
            </div>
            <div id="pms-arrivals-body" class="pms-arrivals-body">
              <div class="pms-arrivals-skeleton">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>
    `);
    modal = document.getElementById('pms-arrivals-modal');
    modal.addEventListener('click', (event) => {
        if (event.target === modal) pmsCloseTodayArrivals();
    });
    return modal;
}

function pmsArrivalStatusText(status) {
    const map = { PENDING: 'Chờ xác nhận', CONFIRMED: 'Đã xác nhận' };
    return map[String(status || '').toUpperCase()] || status || '—';
}

function pmsArrivalDateText(booking) {
    const ci = booking.check_in ? pmsFdate(booking.check_in) : '—';
    const co = booking.check_out ? pmsFdate(booking.check_out) : '—';
    return `${ci} → ${co}`;
}

function pmsArrivalCard(booking, room) {
    const roomContext = !!room;
    const assignedRoomId = Number(booking.assigned_room_id || 0);
    const assignedLabel = booking.assigned_room_number ? `Đã gán P.${pmsEscapeHtml(booking.assigned_room_number)}` : 'Chưa gán phòng';
    const canUseRoom = roomContext && (!assignedRoomId || assignedRoomId === Number(room.id));
    const canOpenAssigned = !roomContext && assignedRoomId;
    const action = canUseRoom
        ? `<button type="button" class="pms-arrival-primary" onclick="pmsDashboardCheckinBooking(${room.id}, ${booking.id})">Gán P.${pmsEscapeHtml(room.room_number)} & nhận</button>`
        : (canOpenAssigned
            ? `<button type="button" class="pms-arrival-primary" onclick="pmsDashboardOpenAssignedBooking(${booking.id})">Nhận phòng</button>`
            : `<button type="button" class="pms-arrival-secondary" disabled>Chọn phòng trên sơ đồ</button>`);
    const source = booking.booking_type || booking.booking_source || 'DIRECT';
    return `
      <div class="pms-arrival-card">
        <div class="pms-arrival-main">
          <div class="pms-arrival-name">${pmsEscapeHtml(booking.guest_name || 'Khách chưa tên')}</div>
          <div class="pms-arrival-meta">
            <span>${pmsEscapeHtml(booking.room_type || '—')}</span>
            <span>${pmsEscapeHtml(pmsArrivalDateText(booking))}</span>
            <span>${pmsEscapeHtml(source)}</span>
          </div>
          <div class="pms-arrival-tags">
            <span class="pms-arrival-status ${String(booking.reservation_status || '').toUpperCase()}">${pmsEscapeHtml(pmsArrivalStatusText(booking.reservation_status))}</span>
            <span>${pmsEscapeHtml(assignedLabel)}</span>
            ${Number(booking.deposit_amount || 0) > 0 ? `<span>Cọc ${pmsMoney(Number(booking.deposit_amount || 0))}</span>` : ''}
          </div>
        </div>
        <div class="pms-arrival-action">${action}</div>
      </div>
    `;
}

function pmsRenderArrivalsLoading() {
    const body = document.getElementById('pms-arrivals-body');
    if (!body) return;
    body.innerHTML = `
      <div class="pms-arrivals-loading" aria-live="polite" aria-busy="true">
        ${[1, 2, 3].map(() => `
          <div class="pms-arrival-skeleton-card">
            <div class="pms-skel-line w60"></div>
            <div class="pms-skel-row">
              <span></span><span></span><span></span>
            </div>
            <div class="pms-skel-line w40"></div>
          </div>
        `).join('')}
      </div>
    `;
}

function pmsRenderArrivalsModal() {
    const body = document.getElementById('pms-arrivals-body');
    const title = document.getElementById('pms-arrivals-title');
    const sub = document.getElementById('pms-arrivals-sub');
    if (!body) return;
    const room = PMS_ARRIVAL_ROOM_ID ? PMS.roomMap?.[PMS_ARRIVAL_ROOM_ID] : null;
    const items = room ? pmsGetRoomArrivalMatches(room) : (PMS.todayArrivals || []);
    const activeItems = items.filter(pmsIsConfirmedArrival);

    if (title) title.textContent = room ? `Đặt phòng phù hợp P.${room.room_number}` : 'Đặt phòng đến hôm nay';
    if (sub) {
        sub.textContent = room
            ? `${room.room_type_name || '—'} · chọn booking cùng hạng để gán vào phòng này và nhận phòng.`
            : 'Danh sách đặt phòng có ngày nhận hôm nay trên chi nhánh hiện tại.';
    }

    if (!activeItems.length) {
        body.innerHTML = `
          <div class="pms-arrivals-empty">
            <strong>${room ? 'Không có booking phù hợp phòng này' : 'Không có đặt phòng đến hôm nay'}</strong>
            <span>${room ? 'Có thể check-in nhanh bằng nút nhận phòng thường.' : 'Danh sách sẽ tự cập nhật khi có booking hôm nay.'}</span>
          </div>
        `;
        return;
    }
    body.innerHTML = activeItems.map(booking => pmsArrivalCard(booking, room)).join('');
}

async function pmsOpenTodayArrivals(roomId = null) {
    PMS_ARRIVAL_ROOM_ID = roomId ? Number(roomId) : null;
    const modal = pmsEnsureArrivalsModal();
    modal.classList.add('show');
    pmsRenderArrivalsLoading();
    await pmsLoadTodayArrivals(true);
    pmsRenderArrivalsModal();
}

function pmsCloseTodayArrivals() {
    const modal = document.getElementById('pms-arrivals-modal');
    if (modal) modal.classList.remove('show');
    PMS_ARRIVAL_ROOM_ID = null;
}

function pmsReservationToCiContext(data, reservation) {
    const raw = reservation.raw_data || {};
    const bookingType = String(reservation.booking_type || raw.booking_type || '').toUpperCase();
    const bookingSource = reservation.booking_source || raw.ota_channel || raw.booking_source || '';
    const externalId = reservation.external_id || raw.booking_reference_code || raw.ota_group_code || raw.external_id || '';
    return {
        mode: 'checkin',
        booking_id: data.booking_id,
        title: 'Nhận phòng từ đặt trước',
        submit_label: 'Nhận phòng',
        branch_id: data.branch_id || reservation.branch_id,
        room_id: data.room_id,
        room_number: data.room_number,
        room_type_id: data.room_type_id,
        room_type_name: data.room_type_name,
        max_guests: data.max_guests,
        price_per_night: data.price_per_night,
        price_per_hour: data.price_per_hour,
        price_next_hour: data.price_next_hour,
        min_hours: data.min_hours,
        check_in: reservation.check_in,
        check_out: reservation.check_out,
        estimated_arrival: reservation.estimated_arrival || '14:00',
        total_price: reservation.total_price,
        deposit_amount: reservation.deposit_amount,
        deposit_type: reservation.deposit_type || reservation.payment_method,
        deposit_meta: reservation.deposit_meta || {},
        booking_type: bookingType,
        booking_source: bookingSource,
        external_id: externalId,
        raw_data: raw,
        notes: reservation.special_requests || '',
        guest_id: reservation.guest_id || null,
        guest_name: reservation.guest_name || '',
        guest_phone: reservation.guest_phone || '',
        guest_cccd: reservation.guest_cccd || '',
        guest_id_type: reservation.guest_id_type || 'cccd',
        gender: reservation.gender || '',
        date_of_birth: reservation.date_of_birth || '',
        nationality: reservation.nationality || 'VNM - Việt Nam',
        id_expire: reservation.id_expire || '',
        address: reservation.address || '',
        address_detail: reservation.address_detail || '',
        address_type: reservation.address_type || 'new',
        city: reservation.city || '',
        district: reservation.district || '',
        ward: reservation.ward || '',
        new_city: reservation.new_city || '',
        new_ward: reservation.new_ward || '',
        old_city: reservation.old_city || '',
        old_district: reservation.old_district || '',
        old_ward: reservation.old_ward || '',
        group_code: reservation.group_code,
        group_index: reservation.group_index,
        group_total: reservation.group_total,
        group_summary: reservation.group_summary,
    };
}

async function pmsDashboardOpenAssignedBooking(bookingId) {
    try {
        const cached = (PMS.todayArrivals || []).find(b => Number(b.id) === Number(bookingId));
        if (cached && !pmsIsConfirmedArrival(cached)) {
            pmsToast('Chỉ đặt phòng đã xác nhận mới được nhận phòng', false);
            return;
        }
        const data = pmsDashboardApiData(await pmsApi(`/api/pms/reservations/${bookingId}/checkin`, { method: 'POST' }), {});
        const reservation = data.reservation || {};
        if (!pmsIsConfirmedArrival(reservation)) {
            pmsToast('Chỉ đặt phòng đã xác nhận mới được nhận phòng', false);
            return;
        }
        pmsCloseTodayArrivals();
        pmsCiOpenReservationModal(pmsReservationToCiContext(data, reservation));
    } catch (e) {
        pmsToast(e.message || 'Không mở được nhận phòng từ đặt trước', false);
    }
}

async function pmsDashboardCheckinBooking(roomId, bookingId) {
    try {
        const cached = (PMS.todayArrivals || []).find(b => Number(b.id) === Number(bookingId));
        if (cached && !pmsIsConfirmedArrival(cached)) {
            pmsToast('Chỉ đặt phòng đã xác nhận mới được nhận phòng', false);
            return;
        }
        await pmsApi(`/api/pms/reservations/${bookingId}/assign-room`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_id: Number(roomId) }),
        });
        const data = pmsDashboardApiData(await pmsApi(`/api/pms/reservations/${bookingId}/checkin`, { method: 'POST' }), {});
        const reservation = data.reservation || {};
        if (!pmsIsConfirmedArrival(reservation)) {
            pmsToast('Chỉ đặt phòng đã xác nhận mới được nhận phòng', false);
            return;
        }
        pmsCloseTodayArrivals();
        pmsCiOpenReservationModal(pmsReservationToCiContext(data, reservation));
        await pmsLoadRooms(undefined, true);
    } catch (e) {
        pmsToast(e.message || 'Không gán được đặt phòng vào phòng này', false);
    }
}

window.pmsOpenTodayArrivals = pmsOpenTodayArrivals;
window.pmsCloseTodayArrivals = pmsCloseTodayArrivals;
window.pmsDashboardCheckinBooking = pmsDashboardCheckinBooking;
window.pmsDashboardOpenAssignedBooking = pmsDashboardOpenAssignedBooking;
