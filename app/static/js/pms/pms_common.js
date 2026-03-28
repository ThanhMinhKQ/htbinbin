// static/js/pms/pms_common.js
// PMS Common Utilities - Shared functions across all PMS modules
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// SVG Icons (Lucide style)
// ─────────────────────────────────────────────────────────────────────────────
const PMS_SVG = {
    user: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    users: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    logIn: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>`,
    logOut: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    addUser: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`,
    swap: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`,
    bed: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>`,
    building: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/></svg>`,
    male: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="14" r="5"/><line x1="19" y1="5" x2="14.14" y2="9.86"/><polyline points="15 5 19 5 19 9"/></svg>`,
    female: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="5"/><line x1="12" y1="14" x2="12" y2="21"/><line x1="9" y1="18" x2="15" y2="18"/></svg>`,
    other: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    cake: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8"/><path d="M4 16s1-1 4-1 5 2 8 2 4-1 4-1V4"/><path d="M4 4h16v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4Z"/></svg>`,
    userX: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="18" y1="8" x2="23" y2="13"/><line x1="23" y1="8" x2="18" y2="13"/></svg>`,
    calendar: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
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
        const p = n => String(n).padStart(2, '0');
        return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
    } catch { return iso; }
}

// Format datetime for display
function pmsFdt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// Format datetime long: DD/MM/YY | HH:mm
function pmsFdtLong(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    const p = n => String(n).padStart(2, '0');
    const yy = String(d.getFullYear()).slice(-2);
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${yy} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Format currency VND
function pmsMoney(n) {
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(n || 0);
}

// Convert Date to ISO string
function pmsToISO(d) {
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Duration from check-in (hours/minutes)
function pmsDur(fromISO) {
    const ms = Date.now() - new Date(fromISO).getTime();
    if (ms < 0) return '—';
    const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000);
    return h > 0 ? `${h}g ${m}p` : `${m} phút`;
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

// Format duration for live counter: [X ngày] HH:mm:ss
function pmsFormatDurLive(fromISO) {
    const ms = Date.now() - new Date(fromISO).getTime();
    if (ms < 0) return '00:00:00';
    const days = Math.floor(ms / (24 * 3600000));
    const remMs = ms % (24 * 3600000);
    const h = Math.floor(remMs / 3600000);
    const m = Math.floor((remMs % 3600000) / 60000);
    const s = Math.floor((remMs % 60000) / 1000);
    const p = n => String(n).padStart(2, '0');
    let res = `${p(h)}:${p(m)}:${p(s)}`;
    if (days > 0) res = `${days} ngày ${res}`;
    return res;
}

// Toast notification
function pmsToast(msg, ok = true) {
    const el = document.getElementById('pms-toast'); if (!el) return;
    el.textContent = msg;
    el.className = `show ${ok ? 'ok' : 'err'}`;
    clearTimeout(el._t);
    el._t = setTimeout(() => el.className = '', 3500);
}

// API fetch helper
async function pmsApi(url, opts = {}) {
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


// ─────────────────────────────────────────────────────────────────────────────
// CCCD / Căn Cước QR Scan Utility
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parse CCCD QR string (pattern-based, NOT index-based).
 * Input: raw string from barcode scanner (keyboard mode).
 * Returns: { card_type, id_number, old_id, name, dob, gender,
 *            address: { raw, detail, ward, district, province },
 *            issue_date, expiry_date, age, is_valid, expiry_status, error }
 */
function pmsParseScanCCCD(raw) {
    // Strip known prefixes
    let cleaned = raw.trim();
    const prefixes = ["CĂN CƯỚC CÔNG DÂN:", "CCCD:", "CMND:", "CAN CUOC:", "CANCUOC:"];
    for (const p of prefixes) {
        if (cleaned.toUpperCase().startsWith(p)) {
            cleaned = cleaned.slice(p.length).trim();
            break;
        }
    }

    const CCCD_CU = "CCCD_CU", CAN_CUOC_MOI = "CAN_CUOC_MOI", CMND_TYPE = "CMND";

    const result = {
        card_type: "", id_number: "", old_id: "", name: "",
        dob: "", gender: "",
        address: { raw: "", detail: "", ward: "", district: "", province: "" },
        issue_date: "", expiry_date: "", age: null,
        is_valid: false, expiry_status: "unknown",
        raw_cleaned: cleaned, error: ""
    };

    const parts = cleaned.split("|").map(p => p.trim());
    const dateCandidates = [];
    let addressCandidate = "";

    const re12 = /^\d{12}$/;
    const re9  = /^\d{9}$/;
    const re8  = /^\d{8}$/;

    for (const p of parts) {
        if (!p) continue;

        if (re12.test(p) && !result.id_number) {
            result.id_number = p;
            result.card_type = "CCCD_CU";
        } else if (re9.test(p) && !result.old_id) {
            result.old_id = p;
            if (!result.card_type) result.card_type = "CMND";
        } else if (re8.test(p)) {
            const d = parseInt(p.slice(0, 2)), m = parseInt(p.slice(2, 4)), y = parseInt(p.slice(4));
            if (d >= 1 && d <= 31 && m >= 1 && m <= 12 && y >= 1900 && y <= 2100) {
                const fmt = `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}/${y}`;
                dateCandidates.push({ raw: p, fmt });
            }
        } else if (p === "Nam" || p === "Nữ") {
            result.gender = p;
        } else if (!result.name && /[\u00C0-\u1EF9]/.test(p)) {
            result.name = p.trim().toUpperCase();
        } else if (p.length > addressCandidate.length) {
            if (/[\d,]|TP\.|Tỉnh|Thành phố|Quận|Huyện|Phường|Xã|Đường|Phố|Tổ|KP/.test(p)) {
                addressCandidate = p;
            }
        }
    }

    // ── Card type detection ───────────────────────────────────────────────
    let detectedCardType = result.card_type || CCCD_CU;

    // Rule 1: field[1] empty
    if (parts.length > 1 && parts[1].trim() === "") {
        detectedCardType = CAN_CUOC_MOI;
    }
    // Rule 2: > 7 fields or >= 2 empty fields
    const emptyCount = parts.filter(p => !p.trim()).length;
    const nonEmptyCount = parts.filter(p => p.trim()).length;
    if (emptyCount >= 2 || nonEmptyCount > 7) {
        detectedCardType = CAN_CUOC_MOI;
    }
    // Rule 3: issue year >= 2024
    if (dateCandidates.length >= 2) {
        try {
            const issueYear = parseInt(dateCandidates[dateCandidates.length - 1].raw.slice(4));
            if (issueYear >= 2024) detectedCardType = CAN_CUOC_MOI;
        } catch (_) {}
    }
    result.card_type = detectedCardType;

    // ── Dates ─────────────────────────────────────────────────────────────
    if (dateCandidates.length >= 1) {
        result.dob = dateCandidates[0].fmt;
    }
    if (dateCandidates.length >= 2) {
        result.issue_date = dateCandidates[dateCandidates.length - 1].fmt;
    }

    // ── Address: normalize → reverse-split → map ───────────────────────
    if (addressCandidate) {
        result.address.raw = addressCandidate;
        const addr = _pmsParseAddressVN(addressCandidate, result.card_type);
        result.address.detail   = addr.detail;
        result.address.ward     = addr.ward;
        result.address.district = addr.district;
        result.address.province = addr.province;
    }

    // ── Expiry + age ──────────────────────────────────────────────────────
    if (result.dob) {
        result.expiry_date = _pmsCalcCCCDExpiry(result.dob);
        result.age = _pmsCalcAge(result.dob);
        result.expiry_status = pmsExpiryStatus(result.expiry_date);
    }

    // ── Validation ───────────────────────────────────────────────────────
    if (!result.id_number && !result.old_id) {
        result.error = "Không tìm thấy số CCCD/CMND";
    } else if (!result.name) {
        result.error = "Không tìm thấy tên";
    } else if (!result.dob) {
        result.error = "Không tìm thấy ngày sinh";
    } else {
        result.is_valid = true;
    }

    return result;
}

const _PMS_PROV_NAMES_FOR_SPLIT = [
    "TP. Hồ Chí Minh",
    "Thừa Thiên Huế",
    "TP. Hải Phòng",
    "TP. Cần Thơ",
    "TP. Đà Nẵng",
    "Thái Nguyên",
    "Tuyên Quang",
    "Bình Dương",
    "Bình Phước",
    "Bình Thuận",
    "Kiên Giang",
    "Ninh Thuận",
    "Quảng Bình",
    "Quảng Ngãi",
    "Quảng Ninh",
    "TP. Hà Nội",
    "Tiền Giang",
    "Bắc Giang",
    "Hải Dương",
    "Hải Phòng",
    "Hậu Giang",
    "Khánh Hòa",
    "Ninh Bình",
    "Quảng Nam",
    "Quảng Trị",
    "Sóc Trăng",
    "Thanh Hóa",
    "Thái Bình",
    "Vĩnh Long",
    "Vĩnh Phúc",
    "Điện Biên",
    "Đồng Tháp",
    "An Giang",
    "Bạc Liêu",
    "Bắc Ninh",
    "Cao Bằng",
    "Hà Giang",
    "Hòa Bình",
    "Hưng Yên",
    "Lai Châu",
    "Lâm Đồng",
    "Lạng Sơn",
    "Nam Định",
    "Trà Vinh",
    "Tây Ninh",
    "Đắk Nông",
    "Đồng Nai",
    "Bắc Kạn",
    "Bến Tre",
    "Cần Thơ",
    "Gia Lai",
    "Hà Tĩnh",
    "Kon Tum",
    "Long An",
    "Lào Cai",
    "Nghệ An",
    "Phú Thọ",
    "Phú Yên",
    "TT. Huế",
    "Yên Bái",
    "Đà Nẵng",
    "Đắk Lắk",
    "Cà Mau",
    "Hà Nam",
    "Hà Nội",
    "Sơn La",
    "TP HCM",
    "Huế",
];

function _pmsNormAddrToken(s) {
    return String(s || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function _pmsSplitSegmentIfProvinceFused(seg) {
    const s = String(seg || "").trim();
    if (!s) return [];
    const sl = s.toLowerCase();
    for (const prov of _PMS_PROV_NAMES_FOR_SPLIT) {
        if (s.length <= prov.length) continue;
        const pl = prov.toLowerCase();
        if (sl.startsWith(pl + " ")) {
            const rest = s.slice(prov.length).trim();
            if (rest) return [prov, rest];
        }
    }
    return [s];
}

function _pmsDedupeTrailingWardProvince(parts) {
    let out = parts.slice();
    while (out.length >= 4) {
        const n = out.length;
        if (_pmsNormAddrToken(out[n - 1]) === _pmsNormAddrToken(out[n - 3]) &&
            _pmsNormAddrToken(out[n - 2]) === _pmsNormAddrToken(out[n - 4])) {
            out = out.slice(0, -2);
        } else break;
    }
    return out;
}

function _pmsRepairQrAddress(raw) {
    if (!raw || !String(raw).trim()) return String(raw || "").trim();
    let s = String(raw).trim()
        .replace(/\s+/g, " ")
        .replace(/\bTP\.\s*/g, "TP. ")
        .replace(/\bTỉnh\s*/gi, "")
        .replace(/\bThành phố\s*/gi, "");
    const segs = s.split(",").map(p => p.trim()).filter(Boolean);
    const expanded = [];
    for (const seg of segs) {
        expanded.push(..._pmsSplitSegmentIfProvinceFused(seg));
    }
    return _pmsDedupeTrailingWardProvince(expanded).join(", ");
}

/** Parse Vietnam address: normalize → reverse-split → map by card_type. */
function _pmsParseAddressVN(rawAddress, cardType) {
    const CCCD_CU = "CCCD_CU", CAN_CUOC_MOI = "CAN_CUOC_MOI";

    const provinceAliases = {
        "tp hcm": "TP. Hồ Chí Minh", "tp.hcm": "TP. Hồ Chí Minh",
        "tphcm": "TP. Hồ Chí Minh", "ho chi minh": "TP. Hồ Chí Minh",
        "hcm": "TP. Hồ Chí Minh",
        "tp hn": "TP. Hà Nội", "tp.hn": "TP. Hà Nội",
        "hanoi": "TP. Hà Nội", "hn": "TP. Hà Nội",
    };

    if (!rawAddress) return { detail: "", ward: "", district: "", province: "" };

    let s = _pmsRepairQrAddress(rawAddress);

    // Step 2: reverse-split by comma
    const parts = s.split(",").map(p => p.trim()).filter(Boolean).reverse();

    // Step 3: map by card_type
    // [tỉnh, quận, phường, chi tiết, ...]  ← reversed
    const provinceRaw = parts[0] || "";
    const provKey = provinceRaw.toLowerCase().replace(/\./g, "").replace(/ /g, "");
    const province  = provinceAliases[provKey] || provinceRaw;

    let ward     = "";
    let district = "";
    let detail   = "";

    if (cardType === CAN_CUOC_MOI) {
        // 3 cấp: [tỉnh, phường, chi tiết]
        ward   = parts[1] || "";
        detail = parts.slice(2).reverse().join(", ");
    } else {
        // 4 cấp: [tỉnh, quận, phường, chi tiết]
        district = parts[1] || "";
        ward     = parts[2] || "";
        detail   = parts.slice(3).reverse().join(", ");
    }

    return { detail, ward, district, province };
}

/**
 * ── pmsMatchAddressToForm ──────────────────────────────────────────────────────
 * Core address matching: parsed address object (from CCCD parser) → fill form fields.
 *
 * @param {object|string} addr   - Parsed address from CCCD parser, or raw string
 * @param {string}        prefix  - 'ci' | 'eg' | 'ag'
 * @param {string}        cardType - 'CCCD_CU' | 'CAN_CUOC_MOI' | 'CMND'
 *
 * Flow:
 *   1. Determine mode: CCCD_CU/CMND → 'old',  CAN_CUOC_MOI → 'new'
 *   2. Switch radio + load province datalist for that mode
 *   3. Match province in datalist (exact → strip prefix → add prefix)
 *   4. Cascade: province change → load wards (new) or districts (old)
 *   5. Match ward/district in datalist
 *   6. Fill detail address
 */
async function pmsMatchAddressToForm(addr, prefix = 'ci', cardType = 'CCCD_CU') {
    const CCCD_CU = "CCCD_CU", CAN_CUOC_MOI = "CAN_CUOC_MOI", CMND_TYPE = "CMND";
    const mode = (cardType === CAN_CUOC_MOI || cardType === CMND_TYPE) ? 'new' : 'old';

    // ── 1. Normalize input: support object {province,ward,district} or raw string
    let province = '', ward = '', district = '', detail = '', rawStr = '';

    if (typeof addr === 'object' && addr !== null) {
        province = addr.province || '';
        ward     = addr.ward     || '';
        district = addr.district || '';
        detail   = addr.detail   || '';
        rawStr   = addr.raw      || '';
    } else if (typeof addr === 'string') {
        rawStr = addr;
        // Fallback: use the reverse-split parser
        const parsed = _pmsParseAddressVN(addr, cardType);
        province = parsed.province;
        ward     = parsed.ward;
        district = parsed.district;
        detail   = parsed.detail;
    } else {
        return; // nothing to do
    }

    if (!province && !rawStr) return;

    // ── 2. Switch radio to correct mode and load provinces
    // Trigger switch function (ci → vnSwitchMode, eg → egSwitchMode, ag → agSwitchMode)
    const switchFnName = prefix === 'ci' ? 'vnSwitchMode'
                       : prefix === 'eg' ? 'egSwitchMode'
                       : 'agSwitchMode';
    const switchFn = window[switchFnName];
    if (typeof switchFn === 'function') {
        await switchFn(mode, true);  // keepValues=true, just switch mode
    } else {
        // Fallback: set radio manually
        const radioNew = document.querySelector(`input[name="${prefix}-area"][value="new"]`);
        const radioOld = document.querySelector(`input[name="${prefix}-area"][value="old"]`);
        if (radioNew) radioNew.checked = (mode === 'new');
        if (radioOld)  radioOld.checked = (mode === 'old');
    }

    // Wait for province datalist to be populated (switch is async)
    const ciProvDL = _pmsProvinceDatalistId(prefix);
    await _pmsWaitForDatalist(`${prefix}-province`, 2000);
    await _pmsWaitForDatalist(ciProvDL, 2000);

    // ── 3. Find province in datalist — enhanced strategies ─────────────────
    const provEl = document.getElementById(`${prefix}-province`);
    const provDL = document.getElementById(ciProvDL);
    if (!provEl) return;

    // Luôn set giá trị province trước (cho dù match hay không — user sửa lại sau)
    provEl.value = province;
    provEl.focus(); // Ensure input is focused for datalist to show
    provEl.dispatchEvent(new Event('input', { bubbles: true }));

    if (!provDL || !provDL.options.length) {
        // Datalist chưa load xong — vẫn dispatch change handler để cascade
        const provChangeFns = { ci: window.vnOnProvinceChange, eg: window.egOnProvinceChange, ag: window.agOnProvinceChange };
        const fn = provChangeFns[prefix] || window.vnOnProvinceChange;
        if (typeof fn === 'function') await fn(provEl);
        return;
    }

    // Strategies mở rộng: exact → strip TP → add TP → contains
    const stripped = _pmsStripPrefix(province);
    // Get ALL prefix candidates
    const prefixedProvinceCandidates = _pmsAddPrefix(stripped, ['TP. ', 'Thành phố ']);
    const strategies = [
        province,                          // 1. exact: "TP. Hà Nội"
        stripped,                         // 2. strip: "Hà Nội"
        ...prefixedProvinceCandidates,     // 3-4. add prefixes
        province.replace(/\s*\(\w+\)\s*$/, ''),  // 5. remove "(Cần Thơ)"
    ];

    let provMatched = '';
    const tried = new Set();
    for (const candidate of strategies) {
        if (!candidate || tried.has(candidate.toLowerCase())) continue;
        tried.add(candidate.toLowerCase());
        for (const opt of provDL.options) {
            if (opt.value.trim().toLowerCase() === candidate.toLowerCase()) {
                provMatched = opt.value;
                provEl.value = provMatched;
                provEl.focus();
                provEl.dispatchEvent(new Event('input', { bubbles: true }));
                break;
            }
        }
        if (provMatched) break;
    }

    // Last resort: contains (strip prefix first so "Hà Nội" matches "TP. Hà Nội")
    if (!provMatched) {
        const strippedLower = stripped.toLowerCase();
        for (const opt of provDL.options) {
            const optStripped = _pmsStripPrefix(opt.value).toLowerCase();
            if ((opt.value.toLowerCase().includes(strippedLower) || optStripped.includes(strippedLower)) && stripped.length >= 4) {
                provMatched = opt.value;
                provEl.value = provMatched;
                provEl.focus();
                provEl.dispatchEvent(new Event('input', { bubbles: true }));
                break;
            }
        }
    }

    // ── 4. Cascade: province change → load wards/districts ──────────────────
    const provChangeFns = { ci: window.vnOnProvinceChange, eg: window.egOnProvinceChange, ag: window.agOnProvinceChange };
    const provChangeFn = provChangeFns[prefix] || window.vnOnProvinceChange;
    if (typeof provChangeFn === 'function') {
        await provChangeFn(provEl);
    }

    if (mode === 'old') {
        // OLD mode: wait for districts, then match district
        const ciDistDL = _pmsDistrictDatalistId(prefix);
        await _pmsWaitForDatalist(ciDistDL, 2000);
        const distEl = document.getElementById(`${prefix}-district`);
        const distDL = document.getElementById(ciDistDL);
        if (distEl) {
    // Luôn set giá trị trước (user sửa lại sau)
    distEl.value = district;
    distEl.focus(); // Ensure input is focused for datalist to show
    distEl.dispatchEvent(new Event('input', { bubbles: true }));

            if (distDL && distDL.options.length && district) {
                const stripped = _pmsStripPrefix(district);
                // Get ALL prefix candidates
                const prefixedCandidates = _pmsAddPrefix(stripped, ['Quận ', 'Huyện ', 'Thị xã ']);
                const distStrategies = [
                    district,
                    stripped,
                    ...prefixedCandidates,
                ];
                let distMatched = '';
                const tried = new Set();
                for (const cand of distStrategies) {
                    if (!cand || tried.has(cand.toLowerCase())) continue;
                    tried.add(cand.toLowerCase());
                    for (const opt of distDL.options) {
                        if (opt.value.trim().toLowerCase() === cand.toLowerCase()) {
                            distMatched = opt.value; break;
                        }
                    }
                    if (distMatched) break;
                }
                // Contains match
                if (!distMatched && stripped.length >= 4) {
                    for (const opt of distDL.options) {
                        if (_pmsStripPrefix(opt.value).toLowerCase().includes(stripped.toLowerCase())) {
                            distMatched = opt.value; break;
                        }
                    }
                }
                if (distMatched) {
                    distEl.value = distMatched;
                    distEl.focus();
                    distEl.dispatchEvent(new Event('input', { bubbles: true }));
                    const distChangeFns = {
                        ci: window.vnOnDistrictChange,
                        eg: window.egOnDistrictChange,
                        ag: window.agOnDistrictChange,
                    };
                    const distChangeFn = distChangeFns[prefix] || window.vnOnDistrictChange;
                    if (typeof distChangeFn === 'function') {
                        await distChangeFn(distEl);
                    }
                } else {
                    // No match found - still trigger cascade to load wards
                    const distChangeFns = {
                        ci: window.vnOnDistrictChange,
                        eg: window.egOnDistrictChange,
                        ag: window.agOnDistrictChange,
                    };
                    const distChangeFn = distChangeFns[prefix] || window.vnOnDistrictChange;
                    if (typeof distChangeFn === 'function') {
                        await distChangeFn(distEl);
                    }
                }
            }
        }
        // OLD mode: wait for wards, then match ward
        await _pmsWaitForDatalist(_pmsWardDatalistId(prefix), 2000);
        await _pmsMatchWardInDatalist(ward, prefix);

    } else {
        // NEW mode: wait for wards (no district), then match ward
        await _pmsWaitForDatalist(_pmsWardDatalistId(prefix), 2000);
        await _pmsMatchWardInDatalist(ward, prefix);
    }

    // ── 5. Fill detail address
    const detailEl = document.getElementById(`${prefix}-address`);
    if (detailEl && detail) {
        detailEl.value = detail;
    }
}

function _pmsWardDatalistId(prefix) {
    return document.getElementById(`dl-${prefix}-ward`) ? `dl-${prefix}-ward` : 'dl-ward';
}
function _pmsDistrictDatalistId(prefix) {
    return document.getElementById(`dl-${prefix}-district`) ? `dl-${prefix}-district` : 'dl-district';
}
function _pmsProvinceDatalistId(prefix) {
    return document.getElementById(`dl-${prefix}-province`) ? `dl-${prefix}-province` : 'dl-province';
}

/** Match ward in the current datalist, with multiple strategies. */
async function _pmsMatchWardInDatalist(wardName, prefix) {
    if (!wardName) return;
    const wardEl = document.getElementById(`${prefix}-ward`);
    if (!wardEl) return;
    const wardDL = document.getElementById(_pmsWardDatalistId(prefix));

    // Luôn set giá trị trước (user sửa lại sau)
    wardEl.value = wardName;
    wardEl.focus(); // Ensure input is focused for datalist to show
    wardEl.dispatchEvent(new Event('input', { bubbles: true }));

    if (!wardDL || !wardDL.options.length) return;

    const stripped = _pmsStripPrefix(wardName);
    // Get ALL prefix candidates
    const prefixedWardCandidates = _pmsAddPrefix(stripped, ['Phường ', 'Xã ']);
    const strategies = [
        wardName,
        stripped,
        ...prefixedWardCandidates,
        wardName.replace(/^Tổ\s*\d*[,\s]*/i, ''),
        wardName.replace(/,?\s*KP\d+\s*,?\s*/gi, ','),
    ];
    const unique = [...new Set(strategies)].filter(Boolean);

    let wardMatched = '';
    for (const candidate of unique) {
        for (const opt of wardDL.options) {
            if (opt.value.trim().toLowerCase() === candidate.toLowerCase()) {
                wardMatched = opt.value; break;
            }
        }
        if (wardMatched) break;
    }

    if (!wardMatched) {
        // Contains match (strip prefix first)
        const strippedLower = stripped.toLowerCase();
        for (const opt of wardDL.options) {
            const optStripped = _pmsStripPrefix(opt.value).toLowerCase();
            if ((opt.value.toLowerCase().includes(strippedLower) || optStripped.includes(strippedLower)) && stripped.length >= 4) {
                wardMatched = opt.value; break;
            }
        }
    }

    if (wardMatched) {
        wardEl.value = wardMatched;
        wardEl.focus();
        wardEl.dispatchEvent(new Event('input', { bubbles: true }));
    }
}

/**
 * Validate address fields after scan - shows warning/error if not in datalist.
 * @param {string} prefix - 'ci' or 'ag'
 * @returns {object} - { valid: bool, issues: [{field, value, message}] }
 */
function pmsValidateAddressAfterScan(prefix = 'ci') {
    const results = { valid: true, issues: [] };

    // Province validation
    const provEl = document.getElementById(`${prefix}-province`);
    const provDL = document.getElementById(`${prefix}-province`)?.dataset?.dl
        ? document.getElementById(document.getElementById(`${prefix}-province`).dataset.dl)
        : document.getElementById(`dl-${prefix}-province`);

    if (provEl && provEl.value.trim()) {
        const provFound = _pmsIsInDatalist(provDL, provEl.value);
        if (!provFound) {
            provEl.classList.add('is-warning');
            provEl.title = `"${provEl.value}" không có trong danh sách!\nVui lòng chọn từ danh sách gợi ý.`;
            results.valid = false;
            results.issues.push({
                field: 'province',
                value: provEl.value,
                message: `Tỉnh/TP "${provEl.value}" không có trong danh sách`
            });
        } else {
            provEl.classList.remove('is-warning', 'is-invalid');
            provEl.title = '';
        }
    }

    // District validation (only for old mode)
    const mode = document.querySelector(`input[name="${prefix}-area"]:checked`)?.value;
    const distEl = document.getElementById(`${prefix}-district`);
    const distDL = distEl?.dataset?.dl
        ? document.getElementById(distEl.dataset.dl)
        : document.getElementById(`dl-${prefix}-district`);

    if (mode === 'old' && distEl && distEl.value.trim()) {
        const distFound = _pmsIsInDatalist(distDL, distEl.value);
        if (!distFound) {
            distEl.classList.add('is-warning');
            distEl.title = `"${distEl.value}" không có trong danh sách!\nVui lòng chọn từ danh sách gợi ý.`;
            results.valid = false;
            results.issues.push({
                field: 'district',
                value: distEl.value,
                message: `Quận/Huyện "${distEl.value}" không có trong danh sách`
            });
        } else {
            distEl.classList.remove('is-warning', 'is-invalid');
            distEl.title = '';
        }
    }

    // Ward validation
    const wardEl = document.getElementById(`${prefix}-ward`);
    const wardDL = wardEl?.dataset?.dl
        ? document.getElementById(wardEl.dataset.dl)
        : document.getElementById(`dl-${prefix}-ward`);

    if (wardEl && wardEl.value.trim()) {
        const wardFound = _pmsIsInDatalist(wardDL, wardEl.value);
        if (!wardFound) {
            wardEl.classList.add('is-warning');
            wardEl.title = `"${wardEl.value}" không có trong danh sách!\nVui lòng chọn từ danh sách gợi ý.`;
            results.valid = false;
            results.issues.push({
                field: 'ward',
                value: wardEl.value,
                message: `Phường/Xã "${wardEl.value}" không có trong danh sách`
            });
        } else {
            wardEl.classList.remove('is-warning', 'is-invalid');
            wardEl.title = '';
        }
    }

    return results;
}

/**
 * Check if a value exists in datalist (case-insensitive, with prefix handling).
 */
function _pmsIsInDatalist(dl, value) {
    if (!dl || !value) return false;
    const v = value.trim().toLowerCase();

    for (const opt of dl.options) {
        const optVal = opt.value.trim().toLowerCase();
        // Exact match
        if (optVal === v) return true;
        // Match after stripping prefix
        const strippedOpt = _pmsStripPrefix(opt.value).toLowerCase();
        const strippedVal = _pmsStripPrefix(value).toLowerCase();
        if (strippedOpt === strippedVal) return true;
    }
    return false;
}

/**
 * Show validation summary toast with details about address issues.
 * Also updates the warning panel in the modal.
 */
function pmsShowAddressValidationIssues(prefix = 'ci') {
    const result = pmsValidateAddressAfterScan(prefix);
    if (result.issues.length === 0) {
        // Hide warning panel
        const panel = document.getElementById(`${prefix}-addr-warning-panel`);
        if (panel) panel.style.display = 'none';
        return true;
    }

    const messages = result.issues.map(i => `• ${i.message}`).join('<br>');
    const toastMsg = `Cảnh báo địa chỉ: ${result.issues.map(i => i.message).join(', ')}`;
    pmsToast(toastMsg, false);

    // Show warning panel
    const panel = document.getElementById(`${prefix}-addr-warning-panel`);
    const listEl = document.getElementById(`${prefix}-addr-warning-list`);
    if (panel) panel.style.display = 'block';
    if (listEl) listEl.innerHTML = messages;

    // Also highlight first issue field
    const firstIssue = result.issues[0];
    const focusEl = document.getElementById(`${prefix}-${firstIssue.field}`);
    if (focusEl) {
        focusEl.focus();
    }

    return false;
}

/** Strip common address prefixes from a string. */
function _pmsStripPrefix(s) {
    if (!s) return '';
    const lower = s.toLowerCase();
    const prefixes = [
        'tỉnh ', 'thành phố ', 'tp ', 'tp. ',
        'quận ', 'huyện ', 'thị xã ', 'thị trấn ',
        'phường ', 'xã ',
    ];
    for (const p of prefixes) {
        if (lower.startsWith(p)) return s.substring(p.length).trim();
    }
    return s.trim();
}

/** Try adding common prefixes to a string - returns ALL candidates as array. */
function _pmsAddPrefix(s, prefixes) {
    if (!s) return [s];
    const results = [];
    for (const p of prefixes) {
        if (!s.toLowerCase().startsWith(p.toLowerCase())) {
            results.push(p + s);
        }
    }
    return results.length > 0 ? results : [s];
}

/** Wait for a datalist to have options (after async province/district load). */
async function _pmsWaitForDatalist(datalistId, maxMs = 2000) {
    const start = Date.now();
    while (Date.now() - start < maxMs) {
        const dl = document.getElementById(datalistId);
        if (dl && dl.options && dl.options.length > 0) return;
        await new Promise(r => setTimeout(r, 50));
    }
}

/** Tính ngày hết hạn CCCD: dob = 'dd/MM/yyyy' */
function _pmsCalcCCCDExpiry(dob) {
    const m = dob.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) return "Không xác định";
    const day = parseInt(m[1]), month = parseInt(m[2]), year = parseInt(m[3]);
    const today = new Date();
    const by25 = year + 25, by40 = year + 40, by60 = year + 60;
    if (today.getFullYear() < by25) return `01/${String(month).padStart(2, "0")}/${by25}`;
    if (today.getFullYear() < by40) return `01/${String(month).padStart(2, "0")}/${by40}`;
    if (today.getFullYear() < by60) return `01/${String(month).padStart(2, "0")}/${by60}`;
    return "Không thời hạn";
}

/** Tính tuổi từ dob string */
function _pmsCalcAge(dob) {
    const m = dob.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) return null;
    const birth = new Date(parseInt(m[3]), parseInt(m[2]) - 1, parseInt(m[1]));
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    if (today < new Date(age === 0 ? birth : birth.setFullYear(today.getFullYear()))) age--;
    return age;
}

/** Trả badge expiry: 'valid' | 'expiring' | 'expired' | 'permanent' | 'unknown' */
function pmsExpiryStatus(expiry) {
    if (!expiry || expiry === "Không xác định") return "unknown";
    if (expiry === "Không thời hạn") return "permanent";
    const m = expiry.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) return "unknown";
    const diff = new Date(parseInt(m[3]), parseInt(m[2]) - 1, parseInt(m[1])) - new Date();
    const days = Math.ceil(diff / 86400000);
    if (days < 0) return "expired";
    if (days <= 180) return "expiring";
    return "valid";
}

/** Gắn sự kiện F1 quét CCCD vào input.
 *  scannerBuffer: accumulates chars until Enter, then fires callback.
 *  keyHandler: catches F1 or rapid-entry sequence.
 *  onScan(data): called with parsed CCCD data.
 */
function pmsBindScanCCCD(inputEl, onScan) {
    if (!inputEl) return;

    const MIN_SCAN_LEN = 10;
    let _buf = "";
    let _timer = null;

    const _flush = () => {
        if (_buf.length >= MIN_SCAN_LEN) {
            try {
                const parsed = pmsParseScanCCCD(_buf);
                onScan(parsed, _buf);
            } catch (e) {
                console.error("[pmsBindScanCCCD] parse error:", e);
            }
        }
        _buf = "";
    };

    // Keyboard scanner: rapid chars + Enter
    inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            _flush();
            return;
        }
        clearTimeout(_timer);
        _timer = setTimeout(() => { _buf = ""; }, 500);
        if (e.key.length === 1) _buf += e.key;
    });

    // F1 explicit trigger
    inputEl.addEventListener("keydown", (e) => {
        if (e.key === "F1" || (e.ctrlKey && e.key === "F")) {
            e.preventDefault();
            const val = inputEl.value.trim();
            if (val.length >= MIN_SCAN_LEN) {
                try {
                    const parsed = pmsParseScanCCCD(val);
                    onScan(parsed, val);
                    inputEl.value = "";
                } catch (e) {
                    console.error("[pmsBindScanCCCD] F1 parse error:", e);
                }
            } else {
                // Show hint to user
                pmsToast("Quét CCCD: nhập hoặc dán chuỗi QR rồi nhấn F1", false);
            }
        }
    });
}

/** Tô màu expiry badge theo status */
function pmsExpiryBadgeHtml(status, expiry) {
    const colors = {
        valid: { bg: "#dcfce7", color: "#16a34a", label: "Còn hạn" },
        expiring: { bg: "#fef9c3", color: "#d97706", label: "Sắp hết hạn" },
        expired: { bg: "#fee2e2", color: "#dc2626", label: "Đã hết hạn" },
        permanent: { bg: "#e0f2fe", color: "#0369a1", label: "Không thời hạn" },
        unknown: { bg: "#f1f5f9", color: "#64748b", label: "—" },
    };
    const c = colors[status] || colors.unknown;
    return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:700;background:${c.bg};color:${c.color};white-space:nowrap;">
        ${status === "valid" ? "&#10003;" : status === "expiring" ? "&#9888;" : status === "expired" ? "&#10005;" : ""}
        ${expiry || c.label}
    </span>`;
}

/** Parse dd/MM/yyyy → yyyy-MM-dd cho <input type="date"> */
function pmsScanDateToISO(dateStr) {
    if (!dateStr) return "";
    const m = dateStr.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) return "";
    return `${m[3]}-${m[2]}-${m[1]}`;
}

window.pmsParseScanCCCD = pmsParseScanCCCD;
window.pmsExpiryStatus = pmsExpiryStatus;
window.pmsBindScanCCCD = pmsBindScanCCCD;
window.pmsExpiryBadgeHtml = pmsExpiryBadgeHtml;
window.pmsScanDateToISO = pmsScanDateToISO;
window.pmsMatchAddressToForm = pmsMatchAddressToForm;
window.pmsValidateAddressAfterScan = pmsValidateAddressAfterScan;
window.pmsShowAddressValidationIssues = pmsShowAddressValidationIssues;


// ─────────────────────────────────────────────────────────────────────────────
// Global F1 Shortcut — Scan CCCD from anywhere in PMS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Determines which modal/form is currently active and routes the scan data
 * to the correct fill function (CI or AG).
 */
async function pmsOnGlobalScan(parsed) {
    const ciModal  = document.getElementById('ciModal');
    const agModal  = document.getElementById('agModal');
    const ciActive = ciModal?.classList.contains('show');
    const agActive = agModal?.classList.contains('show');

    if (agActive && typeof agFillFromScan === 'function') {
        await agFillFromScan(parsed);
        pmsToast(`Đã quét: ${parsed.name || parsed.id_number || parsed.old_id}`, true);
    } else if (ciActive && typeof pmsCiFillFromScan === 'function') {
        await pmsCiFillFromScan(parsed);
        pmsToast(`Đã quét: ${parsed.name || parsed.id_number || parsed.old_id}`, true);
    } else {
        // No modal active — open scan modal for the next opening
        pmsToast('Mở modal quét CCCD. Dữ liệu sẽ được điền khi form check-in hoặc thêm khách mở.', true);
        openScanModal(async (scanned) => {
            const ci = document.getElementById('ciModal');
            const ag = document.getElementById('agModal');
            if (ag?.classList.contains('show') && typeof agFillFromScan === 'function') {
                await agFillFromScan(scanned);
            } else if (ci?.classList.contains('show') && typeof pmsCiFillFromScan === 'function') {
                await pmsCiFillFromScan(scanned);
            }
        });
    }
}

/**
 * Global F1 shortcut — works from any PMS page, any modal.
 * Activates when user presses F1 and no input/textarea is focused
 * (except inside the scan modal itself).
 */
document.addEventListener('keydown', function (e) {
    if (e.key !== 'F1') return;

    const tag = document.activeElement?.tagName?.toUpperCase();
    const inScanModal = document.getElementById('scanModal')?.classList.contains('show');

    // Block F1 when inside an input field OR when scan modal is already open
    if (inScanModal) return;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        // Special case: if ci-cccd or ag-cccd is focused, trigger scan directly
        const activeId = document.activeElement?.id;
        if (activeId === 'ci-cccd' || activeId === 'ag-cccd') {
            e.preventDefault();
            const val = document.activeElement.value.trim();
            if (val && val.length >= 10) {
                try {
                    const parsed = pmsParseScanCCCD(val);
                    pmsOnGlobalScan(parsed);
                } catch (err) {
                    console.error('[F1] Parse error:', err);
                }
            } else {
                openScanModal(pmsOnGlobalScan);
            }
            return;
        }
        // Block F1 in other inputs — user should not trigger scan accidentally
        return;
    }

    e.preventDefault();
    openScanModal(pmsOnGlobalScan);
});

window.pmsOnGlobalScan = pmsOnGlobalScan;
