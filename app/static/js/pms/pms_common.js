// static/js/pms/pms_common.js
// PMS Common Utilities - Shared functions across all PMS modules
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// SVG Icons (Lucide style)
// ─────────────────────────────────────────────────────────────────────────────
const PMS_SVG = {
    user:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    users:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    logIn:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>`,
    logOut: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    addUser:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`,
    swap:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`,
    bed:    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>`,
    building:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/></svg>`,
    male:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="14" r="5"/><line x1="19" y1="5" x2="14.14" y2="9.86"/><polyline points="15 5 19 5 19 9"/></svg>`,
    female: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="5"/><line x1="12" y1="14" x2="12" y2="21"/><line x1="9" y1="18" x2="15" y2="18"/></svg>`,
    other:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    cake:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8"/><path d="M4 16s1-1 4-1 5 2 8 2 4-1 4-1V4"/><path d="M4 4h16v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4Z"/></svg>`,
};

// Gender icon helper
function pmsGenderIcon(g) {
    if (!g) return PMS_SVG.other;
    const v = g.toLowerCase();
    if (v === 'nam' || v === 'male') return PMS_SVG.male;
    if (v === 'nữ' || v === 'nu' || v === 'female') return PMS_SVG.female;
    return PMS_SVG.other;
}

// Format birth date dd/mm/yyyy
function pmsFdate(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''));
        const p = n => String(n).padStart(2,'0');
        return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
    } catch { return iso; }
}

// Format datetime for display
function pmsFdt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
}

// Format currency VND
function pmsMoney(n) {
    return new Intl.NumberFormat('vi-VN',{style:'currency',currency:'VND'}).format(n||0);
}

// Convert Date to ISO string
function pmsToISO(d) {
    const p=n=>String(n).padStart(2,'0');
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Duration from check-in (hours/minutes)
function pmsDur(fromISO) {
    const ms = Date.now()-new Date(fromISO).getTime();
    if (ms<0) return '—';
    const h=Math.floor(ms/3600000), m=Math.floor((ms%3600000)/60000);
    return h>0?`${h}g ${m}p`:`${m} phút`;
}

// Duration nights
function pmsDurNights(fromISO) {
    const ms = Date.now() - new Date(fromISO).getTime();
    if (ms < 0) return '0 đêm';
    const days = Math.floor(ms / (24 * 3600000));
    return days > 0 ? `${days} đêm` : '< 1 đêm';
}

// Full duration (days, hours, minutes)
function pmsDurFull(fromISO) {
    const ms = Date.now() - new Date(fromISO).getTime();
    if (ms < 0) return '—';
    const days = Math.floor(ms / (24 * 3600000));
    const remMs = ms % (24 * 3600000);
    const h = Math.floor(remMs / 3600000);
    const m = Math.floor((remMs % 3600000) / 60000);
    let parts = [];
    if (days > 0) parts.push(`${days} đêm`);
    if (h > 0) parts.push(`${h}g`);
    if (m > 0 || parts.length === 0) parts.push(`${m}p`);
    return parts.join(' ');
}

// Toast notification
function pmsToast(msg, ok=true) {
    const el=document.getElementById('pms-toast'); if(!el) return;
    el.textContent=msg;
    el.className=`show ${ok?'ok':'err'}`;
    clearTimeout(el._t);
    el._t=setTimeout(()=>el.className='',3500);
}

// API fetch helper
async function pmsApi(url, opts={}) {
    const r = await fetch(url, { credentials: 'same-origin', ...opts });
    let d;
    const contentType = r.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
        d = await r.json();
    } else {
        const text = await r.text();
        console.error("Non-JSON response from server:", text);
        if (!r.ok) throw new Error(`Server error (${r.status}): ${text.substring(0, 100)}...`);
        return text;
    }
    if (!r.ok) throw new Error(d.detail || 'Lỗi server');
    return d;
}

// Escape HTML
function pmsEscapeHtml(s) {
    if (!s) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

// Parse currency input (remove separators)
function pmsParseCurrency(val) {
    if (!val) return 0;
    return parseFloat(String(val).replace(/[.\s,]/g, '').replace(/,/g, '.')) || 0;
}

// Format currency display
function pmsFormatCurrency(el) {
    if (!el) return;
    let val = pmsParseCurrency(el.value);
    if (val > 0) {
        el.value = new Intl.NumberFormat('vi-VN').format(val);
    } else {
        el.value = '';
    }
}

// Open modal helper
function pmsOpenModal(id) {
    document.getElementById(id)?.classList.add('show');
}

// Close modal helper
function pmsCloseModal(id) {
    document.getElementById(id)?.classList.remove('show');
}

// Global PMS state
window.PMS = window.PMS || { floors: {}, branchId: null, roomTypes: [], timer: null };

// Change branch handler
function pmsChangeBranch(branchId) {
    PMS.branchId = branchId || null;
    // Trigger reload based on current page
    if (typeof pmsLoadRooms === 'function') {
        pmsLoadRooms();
    }
    if (typeof pmsSearchRooms === 'function') {
        pmsSearchRooms();
    }
}

// Export for use in other modules
window.PMS_SVG = PMS_SVG;
window.pmsGenderIcon = pmsGenderIcon;
window.pmsFdate = pmsFdate;
window.pmsFdt = pmsFdt;
window.pmsMoney = pmsMoney;
window.pmsToISO = pmsToISO;
window.pmsDur = pmsDur;
window.pmsDurNights = pmsDurNights;
window.pmsDurFull = pmsDurFull;
window.pmsToast = pmsToast;
window.pmsApi = pmsApi;
window.pmsEscapeHtml = pmsEscapeHtml;
window.pmsParseCurrency = pmsParseCurrency;
window.pmsFormatCurrency = pmsFormatCurrency;
window.pmsOpenModal = pmsOpenModal;
window.pmsCloseModal = pmsCloseModal;
window.pmsChangeBranch = pmsChangeBranch;