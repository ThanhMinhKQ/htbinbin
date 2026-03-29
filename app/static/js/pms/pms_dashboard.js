// static/js/pms/pms_dashboard.js
// PMS Dashboard - Room map, floor/type view, loading rooms
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// PMS State
// ─────────────────────────────────────────────────────────────────────────────
let PMS_VIEW_MODE = 'floor'; // 'floor' | 'type'
let PMS_CURRENT_TAB = 'map'; // 'map' | 'book'

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
    pmsLoadRooms();
    // Periodic refresh: bảo đảm không chồng request nếu load chưa xong
    PMS.timer = setInterval(() => {
        if (!PMS._loading) pmsLoadRooms(undefined, true);
    }, 45000);
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
});

// ─────────────────────────────────────────────────────────────────────────────
// Load Rooms
// ─────────────────────────────────────────────────────────────────────────────
    async function pmsLoadRooms(bid, silent = false) {
    if (PMS._loading) return; // tránh gọi chồng
    PMS._loading = true;
    if (bid!==undefined) PMS.branchId=bid;
    const loadEl = document.getElementById('pms-loading');
    const floorsEl = document.getElementById('pms-floors');
    if (!silent && loadEl && floorsEl) {
        loadEl.style.display = 'block';
        floorsEl.style.display = 'none';
    }
    try {
        let url='/api/pms/rooms'; if(PMS.branchId) url+=`?branch_id=${PMS.branchId}`;
        const data=await pmsApi(url);
        PMS.floors=data.floors||{};
        let rtUrl='/api/pms/room-types'; if(PMS.branchId) rtUrl+=`?branch_id=${PMS.branchId}`;
        PMS.roomTypes=await pmsApi(rtUrl);
        pmsRender();
    } catch(e) {
        if (loadEl) loadEl.innerHTML=`<span class="text-danger small">${e.message}</span>`;
        else pmsToast(e.message, false);
    } finally {
        PMS._loading = false;
        pmsStartLiveCounters();
    }
}

function pmsChangeBranch(v) { pmsLoadRooms(v||null); }

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
        floorsEl.innerHTML = `<div class="pms-empty">
            ${PMS_SVG.bed}
            <p>Chưa có phòng nào. <a href="/pms/setup?tab=rooms">Thiết lập phòng ngay</a></p>
        </div>`;
        ['cnt-occ','cnt-vac','cnt-all'].forEach(id => {
            const el = document.getElementById(id); if (el) el.textContent = '0';
        });
        loadEl.style.display = 'none'; floorsEl.style.display = 'block'; return;
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
            html += `<div class="f-block">
              <div class="f-head">
                <span class="f-name">${typeName}</span>
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
// Room Card Component
// ─────────────────────────────────────────────────────────────────────────────
function pmsRoomCard(r) {
    const isOcc = r.status === 'OCCUPIED', s = r.stay, cls = isOcc ? 'rc-occ' : 'rc-vac';
    const badgeClick = isOcc && s ? `openRoomDetail(${s.id},'${r.room_number}')` : `openCI(${r.id})`;

    let info;
    if (isOcc && s) {
        const checkInTime = pmsFdtLong(s.check_in_at);
        const checkOutTime = s.check_out_at ? pmsFdtLong(s.check_out_at) : null;
        const isCheckoutSoon = s.check_out_at && (new Date(s.check_out_at) - new Date()) < 3600000;
        const checkInMs = new Date(s.check_in_at).getTime();
        const stayDurationStr = pmsFormatDurLive(Number.isFinite(checkInMs) ? checkInMs : s.check_in_at);
        const checkInMsAttr = Number.isFinite(checkInMs) ? String(checkInMs) : '';

        info = `<div class="ri-stay-vertical" data-checkin-ms="${checkInMsAttr}" data-checkin="${pmsEscapeHtml(String(s.check_in_at || ''))}" data-checkout="${pmsEscapeHtml(String(s.check_out_at || ''))}">
            <div class="ri-v-row active">
                <span class="ri-label">Start:</span>
                <span class="ri-value">${checkInTime}</span>
            </div>
            ${checkOutTime ? `
            <div class="ri-v-row">
                <span class="ri-label">End:</span>
                <span class="ri-value checkout ${isCheckoutSoon ? 'ri-soon' : ''}">${checkOutTime}</span>
            </div>` : ''}
            <div class="ri-v-row live">
                <span class="ri-label">Time:</span>
                <span class="ri-value nights live-counter">${stayDurationStr}</span>
            </div>
        </div>`;
    } else {
        info = `<div class="ri-emp">
            <div class="ri-emp-icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16Z"/><path d="M2 10h20"/><path d="M6 6v4"/></svg>
            </div>
            <span class="ri-emp-text">Phòng trống</span>
        </div>`;
    }

    let acts;
    if (isOcc && s) {
        acts = `
        <button class="ra-btn ra-co" onclick="openCO(${s.id},'${r.room_number}')" title="Trả phòng">
            ${PMS_SVG.logOut}
        </button>
        <button class="ra-btn ra-ag" onclick="openAG(${s.id},'${r.room_number}')" title="Thêm khách">
            ${PMS_SVG.addUser}
        </button>
        <button class="ra-btn ra-tf" onclick="openTF(${s.id},'${r.room_number}')" title="Đổi phòng">
            ${PMS_SVG.swap}
        </button>`;
    } else {
        acts = `<button class="ra-btn ra-ci" onclick="openCI(${r.id})" title="Check-in">
            ${PMS_SVG.logIn}
        </button>`;
    }

    // Guest residents below card
    let residentsContent = '';
    if (isOcc && s && s.guests && s.guests.length > 0) {
        // Sort guests by id ascending (proxy for earliest check-in time)
        const sortedGuests = [...s.guests].sort((a, b) => a.id - b.id);
        residentsContent = sortedGuests.map(g => `
            <div class="rc-resident">
                <div class="rc-resident-icon">${pmsGenderIcon(g.gender)}</div>
                <span class="rc-resident-name">${pmsEscapeHtml(g.full_name)}</span>
                <span class="rc-resident-birth">${PMS_SVG.calendar} ${pmsFdate(g.birth_date)}</span>
            </div>
        `).join('');
    } else {
        residentsContent = `<div class="rc-residents-empty">
            <span>Chưa có khách</span>
        </div>`;
    }
    const residentsHtml = `<div class="rc-residents">${residentsContent}</div>`;

    return `<div class="rc-wrap" id="room-card-id-${r.id}" data-room-num="${r.room_number}">
        <div class="rc ${cls}">
            <div class="rc-top">
                <div class="rc-badge" onclick="${badgeClick}">
                    <div class="rb-num">${r.room_number}</div>
                    <div class="rb-type">${r.room_type_name || '—'}</div>
                    <div class="rb-cap">${PMS_SVG.user} ${isOcc && s ? s.guest_count : 0}/${r.max_guests}</div>
                </div>
                <div class="rc-info">${info}</div>
                <div class="rc-actions">${acts}</div>
            </div>
            ${residentsHtml}
        </div>
    </div>`;
}

// Export functions globally
window.pmsLoadRooms = pmsLoadRooms;
window.pmsChangeBranch = pmsChangeBranch;
window.pmsSetTab = pmsSetTab;
window.pmsSetView = pmsSetView;
window.pmsRender = pmsRender;

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
    document.querySelectorAll('.ri-stay-vertical').forEach(el => {
        const counterEl = el.querySelector('.live-counter');
        if (!counterEl) return;
        const rawMs = el.dataset.checkinMs;
        let anchorMs = rawMs !== undefined && rawMs !== '' ? Number(rawMs) : NaN;
        if (!Number.isFinite(anchorMs)) {
            const checkin = el.dataset.checkin;
            if (!checkin) return;
            anchorMs = new Date(checkin).getTime();
        }
        if (!Number.isFinite(anchorMs)) return;
        counterEl.textContent = pmsFormatDurLive(anchorMs);
    });
}

function pmsStartLiveCounters() {
    if (PMS.liveInterval) clearInterval(PMS.liveInterval);
    pmsTickLiveCounters();
    PMS.liveInterval = setInterval(pmsTickLiveCounters, 1000);
}

window.pmsTickLiveCounters = pmsTickLiveCounters;
window.pmsStartLiveCounters = pmsStartLiveCounters;
