// static/js/pms.js – PMS Room Map v3 (SVG icons, no emoji)
'use strict';

let PMS = { floors: {}, branchId: null, roomTypes: [], timer: null };

// SVG icon strings (Lucide style)
const SVG = {
    user:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    users:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    logIn:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>`,
    logOut: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    addUser:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`,
    swap:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`,
    bed:    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>`,
    building:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/></svg>`,
    // Gender icons
    male:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="14" r="5"/><line x1="19" y1="5" x2="14.14" y2="9.86"/><polyline points="15 5 19 5 19 9"/></svg>`,
    female: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="5"/><line x1="12" y1="14" x2="12" y2="21"/><line x1="9" y1="18" x2="15" y2="18"/></svg>`,
    other:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
};

// Gender icon helper
function genderIcon(g) {
    if (!g) return SVG.other;
    const v = g.toLowerCase();
    if (v === 'nam' || v === 'male') return SVG.male;
    if (v === 'nữ' || v === 'nu' || v === 'female') return SVG.female;
    return SVG.other;
}

// Format birth date dd/mm/yyyy
function fdate(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''));
        const p = n => String(n).padStart(2,'0');
        return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
    } catch { return iso; }
}

document.addEventListener('DOMContentLoaded', () => {
    const ci = document.getElementById('ci-in');
    if (ci) ci.value = toISO(new Date());
    loadRooms();
    PMS.timer = setInterval(() => loadRooms(undefined, true), 45000);
    ['ci-in','ci-out'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', calcPrice);
    });
});

// ── Utilities ─────────────────────────────────────────────────────────
function money(n) {
    return new Intl.NumberFormat('vi-VN',{style:'currency',currency:'VND'}).format(n||0);
}
function fdt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
}
function toISO(d) {
    const p=n=>String(n).padStart(2,'0');
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function dur(fromISO) {
    const ms = Date.now()-new Date(fromISO).getTime();
    if (ms<0) return '—';
    const h=Math.floor(ms/3600000), m=Math.floor((ms%3600000)/60000);
    return h>0?`${h}g ${m}p`:`${m} phút`;
}
function toast(msg, ok=true) {
    const el=document.getElementById('pms-toast'); if(!el) return;
    el.textContent=msg;
    el.className=`show ${ok?'ok':'err'}`;
    clearTimeout(el._t);
    el._t=setTimeout(()=>el.className='',3500);
}
async function api(url,opts={}) {
    const r=await fetch(url,{credentials:'same-origin',...opts});
    const d=await r.json(); if(!r.ok) throw new Error(d.detail||'Lỗi server');
    return d;
}

// ── Load ──────────────────────────────────────────────────────────────
async function loadRooms(bid, silent = false) {
    if (bid!==undefined) PMS.branchId=bid;
    if (!silent) {
        document.getElementById('pms-loading').style.display='block';
        document.getElementById('pms-floors').style.display='none';
    }
    try {
        let url='/api/pms/rooms'; if(PMS.branchId) url+=`?branch_id=${PMS.branchId}`;
        const data=await api(url);
        PMS.floors=data.floors||{};
        let rtUrl='/api/pms/room-types'; if(PMS.branchId) rtUrl+=`?branch_id=${PMS.branchId}`;
        PMS.roomTypes=await api(rtUrl);
        render();
    } catch(e) {
        document.getElementById('pms-loading').innerHTML=`<span class="text-danger small">${e.message}</span>`;
    }
}
function changeBranch(v) { loadRooms(v||null); }

// ── Render ────────────────────────────────────────────────────────────
let VIEW_MODE = 'floor'; // 'floor' | 'type'

function setView(mode) {
    VIEW_MODE = mode;
    const floorBtn = document.getElementById('view-floor');
    const typeBtn  = document.getElementById('view-type');
    const ACTIVE = 'padding:5px 14px;font-size:13px;border-radius:6px;background:#2563eb;color:#fff;font-weight:600;';
    const IDLE   = 'padding:5px 14px;font-size:13px;border-radius:6px;background:transparent;color:#6b7280;font-weight:600;';
    if (floorBtn && typeBtn) {
        floorBtn.style.cssText = mode === 'floor' ? ACTIVE : IDLE;
        typeBtn.style.cssText  = mode === 'type'  ? ACTIVE : IDLE;
    }
    render();
}

function render() {
    const loadEl   = document.getElementById('pms-loading');
    const floorsEl = document.getElementById('pms-floors');
    const sortedF  = Object.keys(PMS.floors).map(Number).sort((a,b) => a-b);

    // Build flat room list & roomMap
    const allRooms = sortedF.flatMap(f => PMS.floors[f]);
    PMS.roomMap = {};
    allRooms.forEach(r => PMS.roomMap[r.id] = r);

    if (!sortedF.length) {
        floorsEl.innerHTML = `<div class="pms-empty">
            ${SVG.bed}
            <p>Chưa có phòng nào. <a href="/pms/setup">Thiết lập phòng ngay</a></p>
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

    if (VIEW_MODE === 'floor') {
        // ── Nhóm theo tầng ──────────────────────────────────────────
        for (const f of sortedF) {
            const rooms = PMS.floors[f];
            const o = rooms.filter(r => r.status === 'OCCUPIED').length;
            html += `<div class="f-block">
              <div class="f-head">
                <span class="f-name">${SVG.building} Tầng ${f}</span>
                <span class="f-stat">Đang ở: <b style="color:#2563eb;">${o}</b> &nbsp;&bull;&nbsp; Trống: <b style="color:#16a34a;">${rooms.length - o}</b></span>
              </div>
              <div class="f-rooms">${rooms.map(r => card(r)).join('')}</div>
            </div>`;
        }
    } else {
        // ── Nhóm theo hạng phòng ────────────────────────────────────
        const typeMap = {};
        allRooms.forEach(r => {
            const key = (r.room_type_name && r.room_type_name !== '—') ? r.room_type_name : '— Chưa phân hạng';
            if (!typeMap[key]) typeMap[key] = [];
            typeMap[key].push(r);
        });
        // Sort: named types alphabetically, unnamed last
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
            const [bg, fg] = COLORS[idx % COLORS.length];
            const o = rooms.filter(r => r.status === 'OCCUPIED').length;
            html += `<div class="f-block">
              <div class="f-head">
                <span class="f-name" style="gap:8px;">
                  <span style="padding:3px 12px;border-radius:99px;background:${bg};color:${fg};font-size:12.5px;font-weight:700;">${typeName}</span>
                  <span style="font-size:12.5px;color:#6b7280;font-weight:400;">${rooms.length} phòng</span>
                </span>
                <span class="f-stat">Đang ở: <b style="color:#2563eb;">${o}</b> &nbsp;&bull;&nbsp; Trống: <b style="color:#16a34a;">${rooms.length - o}</b></span>
              </div>
              <div class="f-rooms">${rooms.map(r => card(r)).join('')}</div>
            </div>`;
        });
    }

    floorsEl.innerHTML = html;
    loadEl.style.display = 'none';
    floorsEl.style.display = 'block';
}


// ── Card ──────────────────────────────────────────────────────────────
function card(r) {
    const isOcc = r.status === 'OCCUPIED', s = r.stay, cls = isOcc ? 'rc-occ' : 'rc-vac';
    const badgeClick = isOcc && s ? `openCO(${s.id},'${r.room_number}')` : `openCI(${r.id})`;

    // Middle info
    let info;
    if (isOcc && s) {
        info = `<div class="ri-name">${s.primary_guest}</div>
                <div class="ri-sub" style="margin-top:5px;display:flex;align-items:center;gap:4px;">
                  <b style="color:#374151;">CI:</b> ${fdt(s.check_in_at)}
                </div>
                <div class="ri-sub" style="margin-top:3px;display:flex;align-items:center;gap:4px;">
                  <b style="color:#374151;">Đã ở:</b> ${dur(s.check_in_at)}
                </div>`;
    } else {
        info = `<div class="ri-emp" style="padding:18px 0;">Phòng trống</div>`;
    }

    // Right-side vertical circular action buttons
    let acts;
    if (isOcc && s) {
        acts = `
        <button class="ra-btn ra-co" onclick="openCO(${s.id},'${r.room_number}')" title="Check-out">
            ${SVG.logOut}
        </button>
        <button class="ra-btn ra-ag" onclick="openAG(${s.id},'${r.room_number}')" title="Thêm khách">
            ${SVG.addUser}
        </button>
        <button class="ra-btn ra-tf" onclick="openTF(${s.id},'${r.room_number}')" title="Đổi phòng">
            ${SVG.swap}
        </button>`;
    } else {
        acts = `<button class="ra-btn ra-ci" onclick="openCI(${r.id})" title="Check-in">
            ${SVG.logIn}
        </button>`;
    }

    // Guest list
    let guests;
    if (isOcc && s && s.guests && s.guests.length) {
        guests = s.guests.map(g => `
            <div class="rg-row">
                <span class="rg-name">
                    <span style="width:14px;height:14px;display:inline-block;vertical-align:middle;">${genderIcon(g.gender)}</span>
                    ${g.full_name}
                </span>
                <span class="rg-cc" style="color:#6b7280;font-size:11px;">${fdate(g.birth_date)}</span>
            </div>`).join('');
    } else {
        guests = `<div class="rg-empty">Chưa có khách</div>`;
    }

    return `<div class="rc-wrap">
        <div class="rc ${cls}">
            <div class="rc-badge" onclick="${badgeClick}">
                <div class="rb-num">${r.room_number}</div>
                <div class="rb-type">${r.room_type_name || '—'}</div>
                <div class="rb-cap"><span style="width:11px;height:11px;display:inline-block;">${SVG.user}</span> ${isOcc && s ? s.guest_count : 0}/${r.max_guests}</div>
            </div>
            <div class="rc-info">${info}</div>
            <div class="rc-actions">${acts}</div>
        </div>
        <div class="rc-guests ${cls.replace('rc-','rg-')}">${guests}</div>
    </div>`;
}


// ── Check-in ──────────────────────────────────────────────────────────
let _ci={};
function openCI(id) {
    const r = PMS.roomMap[id]; if (!r) return;
    _ci=r;
    document.getElementById('ci-room-id').value=id;
    document.getElementById('ci-title').textContent=`Check-in – Phòng ${r.room_number}`;
    document.getElementById('ci-sub').textContent=`${r.room_type_name||'—'} | Đêm: ${money(r.price_per_night)} | Giờ: ${money(r.price_per_hour)}`;
    document.getElementById('ci-in').value=toISO(new Date());
    ['ci-out','ci-name','ci-cccd','ci-birth','ci-phone','ci-notes'].forEach(x=>document.getElementById(x).value='');
    document.getElementById('ci-gender').value='';
    document.getElementById('ci-deposit').value='0';
    document.getElementById('ci-price').textContent='—';
    document.getElementById('st-night').checked=true;
    openModal('ciModal');
}
function calcPrice() {
    const st=document.querySelector('input[name="st"]:checked')?.value||'night';
    const ciV=document.getElementById('ci-in')?.value;
    const coV=document.getElementById('ci-out')?.value;
    const el=document.getElementById('ci-price'); if(!el) return;
    if(!ciV||!coV){el.textContent='—';return;}
    const ms=new Date(coV)-new Date(ciV); if(ms<=0){el.textContent='—';return;}
    
    let p = 0;
    if (st === 'hour') {
        const hours = Math.max(_ci.min_hours||1, Math.ceil(ms/3600000));
        p = (_ci.price_per_hour||0)*(_ci.min_hours||1) + (_ci.price_next_hour||0)*Math.max(0, hours-(_ci.min_hours||1));
    } else {
        const nights = Math.max(1, Math.ceil(ms/86400000));
        let ppN = _ci.price_per_night||0;
        
        if (_ci.promo_start_time && _ci.promo_end_time && (_ci.promo_discount_percent||0) > 0) {
            const timeStr = ciV.split('T')[1].substring(0,5); // HH:mm
            const startStr = _ci.promo_start_time.substring(0,5);
            const endStr = _ci.promo_end_time.substring(0,5);
            
            let isPromo = false;
            if (startStr <= endStr) {
                if (startStr <= timeStr && timeStr <= endStr) isPromo = true;
            } else {
                if (timeStr >= startStr || timeStr <= endStr) isPromo = true;
            }
            if (isPromo) {
                ppN = ppN * (1 - _ci.promo_discount_percent / 100);
            }
        }
        p = ppN * nights;
    }
    el.textContent=money(p);
}
async function submitCI() {
    const name=document.getElementById('ci-name').value.trim();
    if(!name){toast('Vui lòng nhập tên khách',false);return;}
    const fd=new FormData();
    ['ci-room-id','ci-in','ci-out','ci-deposit','ci-notes','ci-cccd','ci-birth','ci-phone'].forEach(id=>{
        const v=document.getElementById(id)?.value||'';
        const key={
            'ci-room-id':'room_id','ci-in':'check_in_at','ci-out':'check_out_at',
            'ci-deposit':'deposit','ci-notes':'notes','ci-cccd':'guest_cccd',
            'ci-birth':'guest_birth','ci-phone':'guest_phone'
        }[id];
        if(key&&v) fd.append(key,v);
    });
    fd.append('stay_type',document.querySelector('input[name="st"]:checked')?.value||'night');
    fd.append('guest_name',name);
    fd.append('guest_gender',document.getElementById('ci-gender').value||'');
    try {
        const r=await api('/api/pms/checkin',{method:'POST',body:fd});
        closeModal('ciModal');
        toast(r.message); await loadRooms();
    } catch(e){toast(e.message,false);}
}

// ── Check-out ─────────────────────────────────────────────────────────
async function openCO(stayId,num) {
    document.getElementById('co-stay-id').value=stayId;
    document.getElementById('co-title').textContent=`Check-out – Phòng ${num}`;
    document.getElementById('co-override').value='';
    try {
        const d=await api(`/api/pms/stays/${stayId}`);
        const now=new Date();
        document.getElementById('co-sub').textContent=`${d.room_type} | ${d.stay_type==='hour'?'Thuê giờ':'Qua đêm'}`;
        document.getElementById('co-ci').textContent=fdt(d.check_in_at);
        document.getElementById('co-now').textContent=fdt(now.toISOString());
        document.getElementById('co-dur').textContent=dur(d.check_in_at);
        document.getElementById('co-dep').textContent=money(d.deposit);
        const ms=now-new Date(d.check_in_at);
        let p = 0;
        if (d.stay_type === 'hour') {
            const hours = Math.max(d.min_hours||1, Math.ceil(ms/3600000));
            p = (d.price_per_hour||0)*(d.min_hours||1) + (d.price_next_hour||0)*Math.max(0, hours-(d.min_hours||1));
        } else {
            p = d.total_price || (d.price_per_night * Math.max(1,Math.ceil(ms/86400000)));
        }
        document.getElementById('co-total').textContent=money(p);
        document.getElementById('co-guests').innerHTML=d.guests.map(g=>
            `<span class="badge bg-light text-dark border" style="font-size:12px;padding:4px 10px;">
                <span style="width:12px;height:12px;display:inline-block;vertical-align:middle;">${g.is_primary?SVG.user:SVG.users}</span>
                ${g.full_name}
            </span>`).join('');
        openModal('coModal');
    } catch(e){toast(e.message,false);}
}
async function submitCO() {
    const id=document.getElementById('co-stay-id').value;
    const fd=new FormData();
    const ov=document.getElementById('co-override').value; if(ov) fd.append('final_price',ov);
    try {
        const r=await api(`/api/pms/checkout/${id}`,{method:'POST',body:fd});
        closeModal('coModal');
        toast(`${r.message} | ${money(r.total_price)}`); await loadRooms();
    } catch(e){toast(e.message,false);}
}

// ── Add Guest ─────────────────────────────────────────────────────────
function openAG(stayId,num) {
    document.getElementById('ag-stay-id').value=stayId;
    document.getElementById('ag-title').textContent=`Thêm khách – Phòng ${num}`;
    ['ag-name','ag-cccd','ag-birth','ag-phone'].forEach(x=>document.getElementById(x).value='');
    document.getElementById('ag-gender').value='';
    openModal('agModal');
}
async function submitAG() {
    const name=document.getElementById('ag-name').value.trim();
    if(!name){toast('Nhập tên khách',false);return;}
    const fd=new FormData();
    fd.append('full_name',name);
    fd.append('cccd',document.getElementById('ag-cccd').value||'');
    fd.append('gender',document.getElementById('ag-gender').value||'');
    fd.append('birth_date',document.getElementById('ag-birth').value||'');
    fd.append('phone',document.getElementById('ag-phone').value||'');
    const id=document.getElementById('ag-stay-id').value;
    try {
        const r=await api(`/api/pms/stays/${id}/guests`,{method:'POST',body:fd});
        closeModal('agModal');
        toast(r.message); await loadRooms();
    } catch(e){toast(e.message,false);}
}

// ── Transfer ──────────────────────────────────────────────────────────
function openTF(stayId,num) {
    document.getElementById('tf-stay-id').value=stayId;
    document.getElementById('tf-info').textContent=`Chuyển từ phòng ${num} sang`;
    const sel=document.getElementById('tf-room');
    sel.innerHTML='<option value="">— Chọn phòng —</option>';
    for (const [floor,rooms] of Object.entries(PMS.floors)) {
        const vac=rooms.filter(r=>r.status==='VACANT');
        if(vac.length) {
            const g=document.createElement('optgroup'); g.label=`Tầng ${floor}`;
            vac.forEach(r=>{const o=document.createElement('option');o.value=r.id;o.textContent=`Phòng ${r.room_number} (${r.room_type_name})`;g.appendChild(o);});
            sel.appendChild(g);
        }
    }
    openModal('tfModal');
}
async function submitTF() {
    const id=document.getElementById('tf-stay-id').value;
    const rid=document.getElementById('tf-room').value;
    if(!rid){toast('Chọn phòng mới',false);return;}
    const fd=new FormData(); fd.append('new_room_id',rid);
    try {
        const r=await fetch(`/api/pms/stays/${id}/transfer`,{method:'PUT',body:fd,credentials:'same-origin'});
        const d=await r.json(); if(!r.ok) throw new Error(d.detail||'Lỗi');
        closeModal('tfModal');
        toast(d.message); await loadRooms();
    } catch(e){toast(e.message,false);}
}
