(function(){
'use strict';

const S = { bid: null, bname: '', types: [], rooms: [], roomView: 'all' };

const SVGI = {
    edit: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
    del:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>`,
    toggle: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="5" width="22" height="14" rx="7" ry="7"/><circle cx="8" cy="12" r="3"/></svg>`,
    user: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    plus: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
    bed:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>`,
};


function applyBaseTheme() {
    document.body.classList.toggle('rs-dark-mode', document.documentElement.classList.contains('dark'));
}

function fmt(n){ return new Intl.NumberFormat('vi-VN').format(n||0)+'đ'; }
function toast(msg, ok=true) {
    const el=document.getElementById('s-toast');
    el.textContent=msg; el.style.background=ok?'#16a34a':'#dc2626'; el.style.opacity='1';
    clearTimeout(el._t); el._t=setTimeout(()=>el.style.opacity='0',3500);
}

// ── Modal Toggle ───────────────────────────────────────────────────────
function openModal(id) {
    const el = document.getElementById(id);
    el.style.display='flex';
    setTimeout(()=>el.classList.add('show'), 10);
}
function closeModal(id) {
    const el = document.getElementById(id);
    el.classList.remove('show');
    setTimeout(()=>el.style.display='none', 200);
}
// Close on backdrop click
function updateBranchSummary() {
    // Update summary cards
    document.getElementById('bs-total-rooms').textContent = S.rooms.length;
    document.getElementById('bs-total-types').textContent = S.types.length;
    document.getElementById('bs-active-rooms').textContent = S.rooms.filter(r => r.is_active).length;
    
    // Calculate average price
    if (S.types.length > 0) {
        const totalPrice = S.types.reduce((sum, t) => sum + (t.price_per_night || 0), 0);
        const avg = Math.round(totalPrice / S.types.length);
        document.getElementById('bs-avg-price').textContent = new Intl.NumberFormat('vi-VN').format(avg);
    } else {
        document.getElementById('bs-avg-price').textContent = '0';
    }
}

function showTab(name, btn) {
    document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.s-tab').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-${name}`).classList.add('active');
    btn.classList.add('active');
}

async function loadAll() { 
    await Promise.all([loadTypes(), loadRooms()]);
    updateBranchSummary();
}

// ── Room Types ─────────────────────────────────────────────────────────
async function loadTypes() {
    const r = await fetch(`/api/pms/admin/room-types?branch_id=${S.bid}`, {credentials:'same-origin'});
    if (!r.ok) { toast('Lỗi tải hạng phòng', false); return; }
    S.types = await r.json();
    renderTypes();
}

function normText(v) { return String(v ?? '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
function time5(v, fallback='—') { return v ? String(v).substring(0,5) : fallback; }
function escapeHtml(v) {
    return String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function renderTypeInsights(types) {
    const box = document.getElementById('type-insights');
    if (!types.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    const avgNight = Math.round(types.reduce((s,t)=>s+(Number(t.price_per_night)||0),0)/types.length);
    const avgHour = Math.round(types.reduce((s,t)=>s+(Number(t.price_per_hour)||0),0)/types.length);
    const promoCount = types.filter(t => Number(t.promo_discount_amount) > 0).length;
    const guestsMax = Math.max(...types.map(t => Number(t.max_guests)||0));
    box.style.display = 'grid';
    box.innerHTML = `
        <div class="insight-chip"><span>Giá đêm TB</span><strong>${fmt(avgNight)}</strong></div>
        <div class="insight-chip"><span>Giờ đầu TB</span><strong>${fmt(avgHour)}</strong></div>
        <div class="insight-chip"><span>Có ưu đãi đêm</span><strong>${promoCount}/${types.length}</strong></div>
        <div class="insight-chip"><span>Sức chứa cao nhất</span><strong>${guestsMax} khách</strong></div>`;
}

function renderTypes() {
    const grid = document.getElementById('types-grid');
    const q = normText(document.getElementById('type-search')?.value || '');
    const filtered = q ? S.types.filter(t => normText(`${t.name} ${t.description} ${t.price_per_night} ${t.price_per_hour}`).includes(q)) : S.types;
    document.getElementById('types-count').textContent = `(${filtered.length}/${S.types.length})`;
    renderTypeInsights(filtered);

    if (!S.types.length) {
        grid.innerHTML = `<div class="s-empty" style="width:100%;">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
            <p>Chưa có hạng phòng nào. Tạo hạng đầu tiên để bắt đầu gán phòng và kiểm soát giá.</p>
        </div>
        <button class="tc-add-btn" onclick="PmsRoomSetup.openAddType()">
            <span style="width:24px;height:24px;display:block;">${SVGI.plus}</span>
            Thêm hạng phòng đầu tiên
        </button>`;
        return;
    }
    if (!filtered.length) {
        grid.innerHTML = `<div class="s-empty" style="width:100%;"><p>Không tìm thấy hạng phòng phù hợp với bộ lọc.</p></div>`;
        return;
    }

    grid.innerHTML = filtered.map(t => {
        const ci = time5(t.standard_checkin_time, '14:00');
        const co = time5(t.standard_checkout_time, '12:00');
        const promoOn = Number(t.promo_discount_amount) > 0;
        const desc = escapeHtml(t.description || 'Chưa có mô tả vận hành cho hạng phòng này.');
        return `
        <article class="type-card-item" onclick="PmsRoomSetup.editType(${t.id})">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom: 8px;">
                <div>
                    <div class="tc-name">${escapeHtml(t.name)}</div>
                    <div class="tc-cap">
                        <span style="width:14px;height:14px;display:inline-block;margin-right:2px;vertical-align:middle;">${SVGI.user}</span>
                        Tối đa ${t.max_guests || 2} khách · Tối thiểu ${t.min_hours || 1}h
                    </div>
                </div>
                <button class="tc-edit-btn" onclick="event.stopPropagation(); PmsRoomSetup.editType(${t.id})" title="Sửa hạng phòng">${SVGI.edit}</button>
            </div>
            <div class="tc-badges">
                <span class="tc-badge blue">${ci} → ${co}</span>
                <span class="tc-badge amber">Ngưỡng ngày ${t.day_threshold_hours || 8}h</span>
                <span class="tc-badge green">Grace ${t.grace_minutes ?? 10} phút</span>
                ${promoOn ? `<span class="tc-badge green">Giảm đêm ${fmt(t.promo_discount_amount)}</span>` : `<span class="tc-badge gray">Chưa bật promo</span>`}
            </div>
            <div class="tc-prices">
                <div class="price-tile primary"><span class="p-label">Giá / đêm</span><span class="p-val">${fmt(t.price_per_night)}</span></div>
                <div class="price-tile"><span class="p-label">Giờ đầu</span><span class="p-val">${fmt(t.price_per_hour)}</span></div>
                <div class="price-tile"><span class="p-label">Giờ sau</span><span class="p-val">${fmt(t.price_next_hour)}</span></div>
                <div class="price-tile"><span class="p-label">Nhận sớm</span><span class="p-val">${fmt(t.early_checkin_fee_per_hour || 50000)}/h</span></div>
                <div class="price-tile"><span class="p-label">Trả muộn</span><span class="p-val">${fmt(t.late_checkout_fee_per_hour || 50000)}/h</span></div>
            </div>
            <div class="tc-desc">${desc}</div>
        </article>`;
    }).join('') + `
        <button class="tc-add-btn" onclick="PmsRoomSetup.openAddType()">
            <span style="width:24px;height:24px;display:block;">${SVGI.plus}</span>
            Thêm hạng phòng
        </button>`;
}

function openAddType() {
    document.getElementById('tm-id').value='';
    document.getElementById('tm-title').textContent='Thêm hạng phòng mới';
    document.getElementById('tm-name').value='';
    document.getElementById('tm-desc').value='';
    document.getElementById('tm-night').value='0';
    document.getElementById('tm-hour').value='0';
    document.getElementById('tm-next-hour').value='0';
    document.getElementById('tm-promo-start').value='';
    document.getElementById('tm-promo-end').value='';
    document.getElementById('tm-promo-amount').value='0';
    document.getElementById('tm-guests').value='2';
    document.getElementById('tm-minhours').value='1';
    document.getElementById('tm-std-checkin').value='14:00';
    document.getElementById('tm-std-checkout').value='12:00';
    document.getElementById('tm-early-fee').value='50000';
    document.getElementById('tm-late-fee').value='50000';
    document.getElementById('tm-day-threshold').value='8';
    document.getElementById('tm-grace').value='10';
    document.getElementById('tm-sort').value = S.types.length;
    // Reset to first tab, hide preview
    showMTab('basic', document.querySelector('.m-tab'));
    document.getElementById('pp-panel').style.display='none';
    updateRuleCards();
    updateConfigScore();
    openModal('typeModal');
}

function editType(id) {
    const t = S.types.find(x => x.id === id); if (!t) return;
    document.getElementById('tm-id').value = t.id;
    document.getElementById('tm-title').textContent = `Sửa hạng: ${t.name}`;
    document.getElementById('tm-name').value = t.name||'';
    document.getElementById('tm-night').value = t.price_per_night||0;
    document.getElementById('tm-hour').value  = t.price_per_hour||0;
    document.getElementById('tm-next-hour').value  = t.price_next_hour||0;
    document.getElementById('tm-promo-start').value = t.promo_start_time ? t.promo_start_time.substring(0,5) : '';
    document.getElementById('tm-promo-end').value = t.promo_end_time ? t.promo_end_time.substring(0,5) : '';
    document.getElementById('tm-promo-amount').value = t.promo_discount_amount||0;
    document.getElementById('tm-guests').value= t.max_guests||2;
    document.getElementById('tm-minhours').value = t.min_hours||1;
    document.getElementById('tm-sort').value  = t.sort_order||0;
    document.getElementById('tm-desc').value  = t.description||'';
    document.getElementById('tm-std-checkin').value = t.standard_checkin_time ? t.standard_checkin_time.substring(0,5) : '14:00';
    document.getElementById('tm-std-checkout').value = t.standard_checkout_time ? t.standard_checkout_time.substring(0,5) : '12:00';
    document.getElementById('tm-early-fee').value = t.early_checkin_fee_per_hour||50000;
    document.getElementById('tm-late-fee').value = t.late_checkout_fee_per_hour||50000;
    document.getElementById('tm-day-threshold').value = t.day_threshold_hours||8;
    document.getElementById('tm-grace').value = t.grace_minutes||10;
    // Reset to first tab, show preview for existing types
    showMTab('basic', document.querySelector('.m-tab'));
    document.getElementById('pp-panel').style.display='block';
    // Set default preview times
    const now = new Date();
    const ci = new Date(now); ci.setHours(10,0,0,0);
    const co = new Date(now); co.setHours(15,0,0,0);
    document.getElementById('pp-checkin').value = ci.toISOString().slice(0,16);
    document.getElementById('pp-checkout').value = co.toISOString().slice(0,16);
    document.getElementById('pp-result').innerHTML = '<div class="pp-empty">Nhấn "Tính giá" để xem kết quả</div>';
    updateRuleCards();
    updateConfigScore();
    openModal('typeModal');
}

async function saveType() {
    const id   = document.getElementById('tm-id').value;
    const name = document.getElementById('tm-name').value.trim();
    if (!name) { toast('Nhập tên hạng phòng', false); return; }

    const fd = new FormData();
    fd.append('name', name);
    fd.append('price_per_night', document.getElementById('tm-night').value||0);
    fd.append('price_per_hour',  document.getElementById('tm-hour').value||0);
    fd.append('price_next_hour', document.getElementById('tm-next-hour').value||0);
    fd.append('promo_start_time', document.getElementById('tm-promo-start').value||'');
    fd.append('promo_end_time',   document.getElementById('tm-promo-end').value||'');
    fd.append('promo_discount_amount', document.getElementById('tm-promo-amount').value||0);
    fd.append('max_guests',      document.getElementById('tm-guests').value||2);
    fd.append('min_hours',       document.getElementById('tm-minhours').value||1);
    fd.append('sort_order',      document.getElementById('tm-sort').value||0);
    fd.append('description',     document.getElementById('tm-desc').value||'');
    // Pricing config (Standard Time Frame)
    fd.append('standard_checkin_time',  document.getElementById('tm-std-checkin').value||'14:00');
    fd.append('standard_checkout_time',  document.getElementById('tm-std-checkout').value||'12:00');
    fd.append('early_checkin_fee_per_hour',  document.getElementById('tm-early-fee').value||50000);
    fd.append('late_checkout_fee_per_hour',  document.getElementById('tm-late-fee').value||50000);
    fd.append('grace_minutes',       document.getElementById('tm-grace').value||10);
    fd.append('day_threshold_hours', document.getElementById('tm-day-threshold').value||8);
    if (!id) fd.append('branch_id', S.bid);

    const url = id ? `/api/pms/admin/room-types/${id}` : '/api/pms/admin/room-types';
    const r = await fetch(url, { method: id ? 'PUT' : 'POST', body: fd, credentials:'same-origin' });
    const d = await r.json();
    if (r.ok) {
        closeModal('typeModal');
        toast(d.message || 'Đã lưu');
        await loadTypes();
        updateBranchSummary();
    } else { toast(d.detail || 'Lỗi', false); }
}

// ── Rooms ──────────────────────────────────────────────────────────────
async function loadRooms() {
    const r = await fetch(`/api/pms/admin/rooms?branch_id=${S.bid}`, {credentials:'same-origin'});
    if (!r.ok) { toast('Lỗi tải danh sách phòng', false); return; }
    S.rooms = await r.json();
    renderRooms();
}

function roomGroupKey(rm, view) {
    if (view === 'floor') return `Tầng ${rm.floor ?? '—'}`;
    if (view === 'type') return rm.room_type_name || 'Chưa phân hạng';
    return '';
}

function roomGroupSort(a, b) {
    const an = Number(String(a).replace(/[^\d.-]/g, ''));
    const bn = Number(String(b).replace(/[^\d.-]/g, ''));
    if (!Number.isNaN(an) && !Number.isNaN(bn) && an !== bn) return an - bn;
    return String(a).localeCompare(String(b), 'vi');
}

function renderRoomCard(rm) {
    const active = rm.is_active !== false;
    const occupied = rm.is_occupied || rm.status === 'OCCUPIED';
    const typeName = rm.room_type_name || 'Chưa phân hạng';
    const notes = rm.notes || 'Chưa có ghi chú vận hành cho phòng này.';
    const statusClass = occupied ? 'occupied' : (active ? 'active' : 'inactive');
    const statusText = occupied ? 'Đang có khách' : (active ? 'Đang mở trên sơ đồ' : 'Ngừng dùng');
    const disableActions = occupied ? ' disabled aria-disabled="true"' : '';
    return `
    <article class="room-card${occupied ? ' is-occupied' : ''}">
        <div class="room-card-head">
            <div>
                <div class="room-number">Phòng ${escapeHtml(rm.room_number)}</div>
                <div class="room-meta">Tầng ${escapeHtml(rm.floor)} · Thứ tự ${escapeHtml(rm.sort_order ?? 0)}</div>
            </div>
            <span class="room-status-badge ${statusClass}">${statusText}</span>
        </div>
        <div class="room-type-line">
            <span class="rtype-badge ${rm.room_type_name ? 'blue' : 'gray'}">${escapeHtml(typeName)}</span>
            ${occupied && rm.active_stay_id ? `<span class="rtype-badge amber">Stay #${escapeHtml(rm.active_stay_id)}</span>` : ''}
        </div>
        <div class="room-price-strip">
            <div><span>Giá đêm</span><strong>${rm.price_per_night ? fmt(rm.price_per_night) : '—'}</strong></div>
            <div><span>Giờ đầu</span><strong>${rm.price_per_hour ? fmt(rm.price_per_hour) : '—'}</strong></div>
            <div><span>Giờ sau</span><strong>${rm.price_next_hour ? fmt(rm.price_next_hour) : '—'}</strong></div>
        </div>
        <div class="room-notes">${escapeHtml(notes)}</div>
        <div class="room-actions">
            <button class="rs-v-btn light sm"${disableActions} onclick="PmsRoomSetup.editRoom(${rm.id})">${occupied ? 'Không thể sửa' : 'Sửa phòng'}</button>
            <button class="rs-v-btn danger sm"${disableActions} onclick="PmsRoomSetup.delRoom(${rm.id})">Ngừng dùng</button>
        </div>
    </article>`;
}

function renderRooms() {
    const count = document.getElementById('rooms-count');
    if (count) count.textContent = `(${S.rooms.length})`;
    const grid = document.getElementById('rooms-grid');
    if (!grid) return;

    document.querySelectorAll('.room-view-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.view === S.roomView));

    if (!S.rooms.length) {
        grid.innerHTML = `<div class="s-empty">${SVGI.bed}<p>Chưa có phòng nào trong chi nhánh này</p></div>`;
        return;
    }

    if (S.roomView === 'all') {
        grid.className = 'rooms-grid';
        grid.innerHTML = S.rooms.map(renderRoomCard).join('');
        return;
    }

    const groups = S.rooms.reduce((acc, rm) => {
        const key = roomGroupKey(rm, S.roomView);
        if (!acc[key]) acc[key] = [];
        acc[key].push(rm);
        return acc;
    }, {});
    grid.className = 'rooms-grouped';
    grid.innerHTML = Object.keys(groups).sort(roomGroupSort).map(key => `
        <section class="room-group-section">
            <div class="room-group-head">
                <strong>${escapeHtml(key)}</strong>
                <span>${groups[key].length} phòng</span>
            </div>
            <div class="rooms-grid room-group-grid">
                ${groups[key].map(renderRoomCard).join('')}
            </div>
        </section>`).join('');
}

function setRoomView(view) {
    S.roomView = ['all', 'floor', 'type'].includes(view) ? view : 'all';
    renderRooms();
}

function populateTypeSelect(selId) {
    const sel = document.getElementById('rm-type');
    sel.innerHTML = '<option value="">— Không phân loại —</option>' +
        S.types.map(t => `<option value="${t.id}"${t.id==selId?' selected':''}>${escapeHtml(t.name)}</option>`).join('');
}

function setRoomInputMode(mode) {
    const nextMode = mode === 'multi' ? 'multi' : 'single';
    document.getElementById('rm-mode').value = nextMode;
    document.getElementById('rm-single-number-wrap').style.display = nextMode === 'single' ? '' : 'none';
    document.getElementById('rm-multi-number-wrap').style.display = nextMode === 'multi' ? '' : 'none';
    document.querySelectorAll('.room-mode-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.mode === nextMode));
    const save = document.getElementById('rm-save-btn');
    if (save) save.textContent = nextMode === 'multi' ? 'Tạo nhiều phòng' : 'Lưu phòng';
}

function parseRoomNumbers(value) {
    const items = String(value || '').split(/[\s,;]+/).map(x => x.trim()).filter(Boolean);
    const seen = new Set();
    const duplicates = new Set();
    const numbers = [];
    for (const item of items) {
        const key = item.toLowerCase();
        if (seen.has(key)) {
            duplicates.add(item);
            continue;
        }
        seen.add(key);
        numbers.push(item);
    }
    return { numbers, duplicates: Array.from(duplicates) };
}

function openAddRoom() {
    if (!S.types.length) {
        toast('Hãy thêm hạng phòng trước!', false);
        showTab('types', document.querySelector('.s-tab[data-tab="types"]'));
        return;
    }
    document.getElementById('rm-id').value='';
    document.getElementById('rm-title').textContent='Thêm phòng mới';
    document.getElementById('rm-subtitle').textContent='Tạo một hoặc nhiều phòng cho chi nhánh hiện tại.';
    document.getElementById('rm-number').value='';
    document.getElementById('rm-number-list').value='';
    document.getElementById('rm-floor').value='1';
    document.getElementById('rm-notes').value='';
    document.getElementById('rm-sort').value = S.rooms.length;
    document.getElementById('rm-add-mode').style.display = 'grid';
    document.getElementById('rm-edit-note').style.display = 'none';
    populateTypeSelect(null);
    setRoomInputMode('single');
    openModal('roomModal');
}

function editRoom(id) {
    const rm = S.rooms.find(x => x.id === id); if (!rm) return;
    if (rm.is_occupied || rm.status === 'OCCUPIED') {
        toast('Phòng đang có khách ở, chỉ được sửa khi phòng trống', false);
        return;
    }
    document.getElementById('rm-id').value    = rm.id;
    document.getElementById('rm-title').textContent = `Sửa phòng ${rm.room_number}`;
    document.getElementById('rm-subtitle').textContent = 'Cập nhật thông tin phòng trống trong chi nhánh hiện tại.';
    document.getElementById('rm-number').value = rm.room_number;
    document.getElementById('rm-number-list').value = '';
    document.getElementById('rm-floor').value  = rm.floor;
    document.getElementById('rm-notes').value  = rm.notes||'';
    document.getElementById('rm-sort').value   = rm.sort_order||0;
    document.getElementById('rm-add-mode').style.display = 'none';
    document.getElementById('rm-edit-note').style.display = 'block';
    populateTypeSelect(rm.room_type_id);
    setRoomInputMode('single');
    openModal('roomModal');
}

async function saveMultipleRooms() {
    const parsed = parseRoomNumbers(document.getElementById('rm-number-list').value);
    if (!parsed.numbers.length) { toast('Nhập danh sách số phòng', false); return; }
    if (parsed.duplicates.length) {
        toast(`Trùng số phòng trong danh sách: ${parsed.duplicates.join(', ')}`, false);
        return;
    }

    const baseSort = Number(document.getElementById('rm-sort').value || S.rooms.length) || 0;
    const tid = document.getElementById('rm-type').value;
    const results = [];
    for (const [idx, num] of parsed.numbers.entries()) {
        const fd = new FormData();
        fd.append('room_number', num);
        fd.append('floor', document.getElementById('rm-floor').value||1);
        fd.append('notes', document.getElementById('rm-notes').value||'');
        fd.append('sort_order', String(baseSort + idx));
        fd.append('branch_id', S.bid);
        if (tid) fd.append('room_type_id', tid);
        const r = await fetch('/api/pms/admin/rooms', { method: 'POST', body: fd, credentials:'same-origin' });
        const d = await r.json();
        results.push({ ok: r.ok, room: num, detail: d.detail || d.message || 'Lỗi' });
    }

    const okCount = results.filter(x => x.ok).length;
    const failed = results.filter(x => !x.ok);
    closeModal('roomModal');
    await loadRooms();
    updateBranchSummary();
    if (failed.length) {
        toast(`Tạo ${okCount}/${results.length} phòng. Lỗi: ${failed.map(x => `${x.room} (${x.detail})`).join(', ')}`, false);
    } else {
        toast(`Đã tạo ${okCount} phòng`);
    }
}

async function saveRoom() {
    const id  = document.getElementById('rm-id').value;
    if (!id && document.getElementById('rm-mode').value === 'multi') {
        await saveMultipleRooms();
        return;
    }

    const num = document.getElementById('rm-number').value.trim();
    if (!num) { toast('Nhập số phòng', false); return; }

    const fd = new FormData();
    fd.append('room_number', num);
    fd.append('floor',       document.getElementById('rm-floor').value||1);
    fd.append('notes',       document.getElementById('rm-notes').value||'');
    fd.append('sort_order',  document.getElementById('rm-sort').value||0);
    const tid = document.getElementById('rm-type').value;
    if (tid) fd.append('room_type_id', tid);
    if (!id) fd.append('branch_id', S.bid);

    const url = id ? `/api/pms/admin/rooms/${id}` : '/api/pms/admin/rooms';
    const r = await fetch(url, { method: id ? 'PUT' : 'POST', body: fd, credentials:'same-origin' });
    const d = await r.json();
    if (r.ok) {
        closeModal('roomModal');
        toast(d.message||'Đã lưu');
        await loadRooms();
        updateBranchSummary();
    } else { toast(d.detail||'Lỗi', false); }
}

async function delRoom(id) {
    const rm = S.rooms.find(x => x.id === id);
    if (rm?.is_occupied || rm?.status === 'OCCUPIED') {
        toast('Phòng đang có khách ở, chỉ được ngừng dùng khi phòng trống', false);
        return;
    }
    const roomNum = rm ? rm.room_number : id;
    if (!confirm(`Ngừng dùng phòng ${roomNum}? Phòng sẽ được ẩn khỏi sơ đồ và danh sách bán phòng.`)) return;
    const r = await fetch(`/api/pms/admin/rooms/${id}`, { method: 'DELETE', credentials:'same-origin' });
    const d = await r.json();
    if (r.ok) { toast(d.message || `Đã ngừng dùng phòng ${roomNum}`); await loadRooms(); updateBranchSummary(); }
    else { toast(d.detail||'Lỗi', false); }
}

// ── Modal Section Tabs ────────────────────────────────────────────────
function showMTab(name, btn) {
    document.querySelectorAll('.m-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.m-tab').forEach(el => el.classList.remove('active'));
    const sec = document.getElementById(`ms-${name}`);
    if (sec) sec.classList.add('active');
    if (btn) btn.classList.add('active');
}

// ── Update Rule Card badges dynamically ───────────────────────────────
function updateRuleCards() {
    const thr = document.getElementById('tm-day-threshold').value || 8;
    const el1 = document.getElementById('rc-threshold');
    const el2 = document.getElementById('rc-rollover');
    if (el1) el1.textContent = `≥ ${thr}h`;
    if (el2) el2.textContent = `≥ ${thr}h`;
}

function setVal(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
}

function applyPreset(kind) {
    const night = Number(document.getElementById('tm-night').value) || 0;
    const baseNight = night > 0 ? night : 600000;
    if (kind === 'balanced') {
        setVal('tm-night', baseNight);
        setVal('tm-hour', Math.round(baseNight * 0.35 / 5000) * 5000);
        setVal('tm-next-hour', Math.round(baseNight * 0.12 / 5000) * 5000);
        setVal('tm-day-threshold', 8);
        setVal('tm-grace', 10);
    }
    if (kind === 'hourly') {
        setVal('tm-night', baseNight);
        setVal('tm-hour', Math.round(baseNight * 0.28 / 5000) * 5000);
        setVal('tm-next-hour', Math.round(baseNight * 0.10 / 5000) * 5000);
        setVal('tm-day-threshold', 6);
        setVal('tm-grace', 5);
    }
    if (kind === 'overnight') {
        setVal('tm-night', baseNight);
        setVal('tm-hour', Math.round(baseNight * 0.32 / 5000) * 5000);
        setVal('tm-next-hour', Math.round(baseNight * 0.11 / 5000) * 5000);
        setVal('tm-promo-start', '22:00');
        setVal('tm-promo-end', '06:00');
        setVal('tm-promo-amount', Math.round(baseNight * 0.10 / 10000) * 10000);
        setVal('tm-day-threshold', 8);
    }
    updateRuleCards();
    updateConfigScore();
}

function updateConfigScore() {
    const name = document.getElementById('tm-name')?.value.trim();
    const night = Number(document.getElementById('tm-night')?.value || 0);
    const hour = Number(document.getElementById('tm-hour')?.value || 0);
    const nextHour = Number(document.getElementById('tm-next-hour')?.value || 0);
    const guests = Number(document.getElementById('tm-guests')?.value || 0);
    const minHours = Number(document.getElementById('tm-minhours')?.value || 0);
    const ci = document.getElementById('tm-std-checkin')?.value || '14:00';
    const co = document.getElementById('tm-std-checkout')?.value || '12:00';
    const early = Number(document.getElementById('tm-early-fee')?.value || 0);
    const late = Number(document.getElementById('tm-late-fee')?.value || 0);
    const threshold = Number(document.getElementById('tm-day-threshold')?.value || 0);
    const grace = Number(document.getElementById('tm-grace')?.value || 0);
    const ps = document.getElementById('tm-promo-start')?.value;
    const pe = document.getElementById('tm-promo-end')?.value;
    const discountAmount = Number(document.getElementById('tm-promo-amount')?.value || 0);
    let score = 0;
    if (name) score += 12;
    if (guests > 0 && minHours > 0) score += 12;
    if (night > 0) score += 16;
    if (hour > 0 && nextHour > 0) score += 16;
    if (ci && co) score += 12;
    if (early >= 0 && late >= 0) score += 10;
    if (threshold > 0 && threshold <= 24) score += 12;
    if (grace >= 0 && grace <= 60) score += 5;
    if ((ps && pe && discountAmount > 0) || (!ps && !pe && discountAmount === 0)) score += 5;
    score = Math.max(0, Math.min(100, score));

    const fill = document.getElementById('score-meter-fill');
    const text = document.getElementById('score-text');
    if (fill) fill.style.width = `${score}%`;
    if (score > 0) {
        const panel = document.getElementById('pp-panel');
        if (panel) panel.style.display = 'block';
    }
    if (text) {
        text.textContent = score >= 90 ? 'Cấu hình đã đủ chắc để áp dụng vận hành.' :
            score >= 70 ? 'Cấu hình khá đầy đủ; nên test thêm vài kịch bản giá.' :
            score >= 45 ? 'Cần bổ sung bảng giá và luật thời gian trước khi lưu.' :
            'Mới có thông tin cơ bản, chưa đủ để vận hành ổn định.';
    }
    const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    setText('sum-night', fmt(night));
    setText('sum-hour', `${fmt(hour)} / ${fmt(nextHour)}`);
    setText('sum-window', `${ci || '—'} → ${co || '—'}`);
    setText('sum-threshold', `${threshold || 0}h`);
    setText('sum-promo', (ps && pe && discountAmount > 0) ? `${ps}–${pe}, giảm ${fmt(discountAmount)}` : 'Chưa bật');
}
// ── Live Pricing Preview ──────────────────────────────────────────────
async function runPreview() {
    const typeId = document.getElementById('tm-id').value;
    if (!typeId) { toast('Lưu hạng phòng trước khi test giá', false); return; }

    const ci = document.getElementById('pp-checkin').value;
    const co = document.getElementById('pp-checkout').value;
    const mode = document.getElementById('pp-mode-sel').value;
    if (!ci || !co) { toast('Nhập thời gian check-in/check-out', false); return; }

    const ppn = document.getElementById('tm-night').value || 0;
    const pph = document.getElementById('tm-hour').value || 0;
    const pnh = document.getElementById('tm-next-hour').value || 0;
    const eFee = document.getElementById('tm-early-fee').value || 0;
    const lFee = document.getElementById('tm-late-fee').value || 0;
    const grace = document.getElementById('tm-grace').value || 10;
    const thr = document.getElementById('tm-day-threshold').value || 8;

    const params = new URLSearchParams({
        checkin: ci, checkout: co, mode: mode,
        day_threshold: thr,
        ppn: ppn, pph: pph, pnh: pnh, early_fee: eFee, late_fee: lFee, grace: grace, promo_discount_amount: document.getElementById('tm-promo-amount').value || 0
    });
    const url = `/api/pms/admin/room-types/${typeId}/pricing-preview?${params.toString()}`;
    try {
        const r = await fetch(url, { credentials: 'same-origin' });
        const d = await r.json();
        if (!r.ok) { toast(d.detail || 'Lỗi', false); return; }
        renderPreview(d);
    } catch (e) {
        toast('Lỗi kết nối', false);
    }
}

function renderPreview(data) {
    // Mode badge
    const badge = document.getElementById('pp-mode-badge');
    const modeMap = { HOURLY: 'hourly', DAILY: 'daily', OVERNIGHT: 'overnight' };
    const modeLabel = { HOURLY: '⏱ Giờ', DAILY: '🌙 Ngày', OVERNIGHT: '🌃 Qua đêm' };
    const cls = modeMap[data.mode_selected] || 'daily';
    badge.className = `pp-mode ${cls}`;
    badge.textContent = modeLabel[data.mode_selected] || data.mode_selected;

    // Breakdown rows
    let html = '<div class="pp-breakdown">';
    for (const item of data.breakdown) {
        const st = item.slice_type || 'core';
        const dotCls = item.day_rollover ? 'rollover' : st;
        const isFree = item.free_buffer || item.amount === 0;
        html += `<div class="pp-row${isFree ? ' free' : ''}">`;
        html += `<span class="pp-desc"><span class="pp-dot ${dotCls}"></span>${item.description}</span>`;
        html += `<span class="pp-amt">${isFree ? 'Miễn phí' : fmt(item.amount)}</span>`;
        html += `</div>`;
    }
    html += '</div>';

    // Total
    html += `<div class="pp-total">`;
    html += `<span class="pp-total-label">Tổng cộng</span>`;
    html += `<span class="pp-total-val">${fmt(data.total)}</span>`;
    html += `</div>`;

    document.getElementById('pp-result').innerHTML = html;
}


let bound = false;

function currentDashboardBranchId() {
    const branchSelect = document.getElementById('branchSelect');
    return Number(branchSelect?.value || window.PMS?.branchId || window.PMS_ROOM_SETUP_BOOT?.branchId || 0) || null;
}

function currentDashboardBranchName(branchId) {
    const branchSelect = document.getElementById('branchSelect');
    const selected = branchSelect?.selectedOptions?.[0];
    if (selected?.textContent?.trim()) return selected.textContent.trim();
    const current = document.getElementById('branch-current');
    if (current?.dataset?.branchName) return current.dataset.branchName;
    const hidden = document.getElementById('branch-select');
    if (hidden?.dataset?.bname) return hidden.dataset.bname;
    return branchId ? `Chi nhánh #${branchId}` : '';
}

function selectBranch(branchId) {
    branchId = Number(branchId || currentDashboardBranchId() || 0) || null;
    if (!branchId) return false;
    const name = currentDashboardBranchName(branchId);
    S.bid = branchId;
    S.bname = name;
    const hidden = document.getElementById('branch-select');
    if (hidden) {
        hidden.value = String(branchId);
        hidden.dataset.bname = name;
    }
    const current = document.getElementById('branch-current');
    if (current) {
        current.dataset.branchId = String(branchId);
        current.dataset.branchName = name;
    }
    const label = document.getElementById('branch-current-name');
    if (label) label.textContent = name || `Chi nhánh #${branchId}`;
    const main = document.getElementById('main-content');
    const summary = document.getElementById('branch-summary');
    if (main) main.style.display = 'block';
    if (summary) summary.style.display = 'block';
    return true;
}

function hideSetupData() {
    const main = document.getElementById('main-content');
    const summary = document.getElementById('branch-summary');
    if (main) main.style.display = 'none';
    if (summary) summary.style.display = 'none';
    S.bid = null;
    S.bname = '';
}

function bindEvents() {
    if (bound) return;
    bound = true;
    document.querySelectorAll('.rs-v-modal').forEach(m => {
        m.addEventListener('click', e => { if (e.target === m) closeModal(m.id); });
    });
    window.addEventListener('themeChanged', applyBaseTheme);
    document.getElementById('tm-day-threshold')?.addEventListener('input', updateRuleCards);
    const setupModal = document.getElementById('pmsSetupModal');
    if (setupModal) {
        setupModal.addEventListener('click', e => { if (e.target === setupModal) closeSetupModal(); });
    }
}

function init(options = {}) {
    bindEvents();
    applyBaseTheme();
    const params = new URLSearchParams(window.location.search);
    const initialTab = options.initialTab || params.get('tab');
    if (initialTab === 'rooms') {
        const btn = document.querySelector('.s-tab[data-tab="rooms"]');
        if (btn) showTab('rooms', btn);
    }
    const branchId = Number(options.branchId || currentDashboardBranchId() || 0) || null;
    if (branchId && selectBranch(branchId)) loadAll();
}

function open(options = {}) {
    init({ ...options, branchId: options.branchId || currentDashboardBranchId() || window.PMS_ROOM_SETUP_BOOT?.branchId });
    const el = document.getElementById('pmsSetupModal');
    if (el) {
        el.classList.add('show');
        document.body.classList.add('pms-setup-open');
    }
    if (S.bid) loadAll();
}

function closeSetupModal() {
    const el = document.getElementById('pmsSetupModal');
    if (el) {
        el.classList.remove('show');
        document.body.classList.remove('pms-setup-open');
    }
}

async function reload() {
    if (!S.bid) {
        const branchId = currentDashboardBranchId() || window.PMS_ROOM_SETUP_BOOT?.branchId;
        if (!selectBranch(branchId)) return;
    }
    await loadAll();
}

function refreshDashboardRooms() {
    if (typeof window.pmsLoadRooms === 'function') window.pmsLoadRooms();
}


window.PmsRoomSetup = {
    init,
    open,
    close: closeSetupModal,
    reload,
    openModal,
    closeModal,
    showTab,
    renderTypes,
    setRoomView,
    setRoomInputMode,
    openAddType,
    editType,
    saveType: async () => { await saveType(); refreshDashboardRooms(); },
    openAddRoom,
    editRoom,
    saveRoom: async () => { await saveRoom(); refreshDashboardRooms(); },
    delRoom: async (id) => { await delRoom(id); refreshDashboardRooms(); },
    showMTab,
    updateRuleCards,
    updateConfigScore,
    applyPreset,
    runPreview,
};

document.addEventListener('DOMContentLoaded', () => init(window.PMS_ROOM_SETUP_BOOT || {}));
})();

