// static/js/pms/pms_common.js
// PMS Common Utilities - Shared functions across all PMS modules
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// GLOBAL ADDRESS DATA CACHE — Preload for fast form fill
// ─────────────────────────────────────────────────────────────────────────────
const PMS_ADDR_CACHE = {
    // Cache state
    _loaded: false,
    _loading: false,
    _loadPromise: null,
    
    // Data storage
    newProvinces: [],      // [{short, name}]
    newWards: {},          // province_short → [ward_name]
    oldProvinces: [],      // [{name, code}]
    oldDistricts: {},     // province_code → [{name, code}]
    oldWards: {},          // district_code → [{name, code}]
    
    // Old province code lookup
    oldProvinceByCode: {}, // code → name
    oldProvinceByName: {}, // normalized name → {name, code}
    
    // Load everything once
    async load() {
        if (this._loaded) return true;
        if (this._loading) return this._loadPromise;
        
        this._loading = true;
        this._loadPromise = this._doLoad();
        
        try {
            await this._loadPromise;
            this._loaded = true;
            console.log('[PMS] Address cache loaded:', {
                provinces: this.newProvinces.length,
                wards: Object.values(this.newWards).reduce((a, b) => a + b.length, 0),
            });
            return true;
        } catch (e) {
            console.error('[PMS] Address cache load failed:', e);
            return false;
        } finally {
            this._loading = false;
        }
    },
    
    async _doLoad() {
        const promises = [
            this._loadNewProvinces(),
            this._loadOldProvinces(),
        ];
        await Promise.all(promises);
    },
    
    async _loadNewProvinces() {
        try {
            const res = await fetch('/api/vn-address/new-provinces');
            const data = await res.json();

            if (data?.provinces) {
                this.newProvinces = data.provinces;
                // Không auto-preload wards của các tỉnh lớn: tốn 5 request song song
                // làm cạnh tranh pool DB. Wards được load lazy ở _loadNewWards(prov)
                // khi user thực sự chọn province trong form.
            }
        } catch (e) {
            console.warn('[PMS] Could not load new provinces:', e);
        }
    },
    
    async _loadNewWards(provinceShort) {
        if (this.newWards[provinceShort]) return this.newWards[provinceShort];
        
        try {
            const res = await fetch(`/api/vn-address/new-wards/${encodeURIComponent(provinceShort)}`);
            const data = await res.json();
            
            if (data?.wards) {
                this.newWards[provinceShort] = data.wards;
            }
        } catch (e) {
            console.warn(`[PMS] Could not load wards for ${provinceShort}:`, e);
        }
        
        return this.newWards[provinceShort] || [];
    },
    
    async _loadOldProvinces() {
        try {
            const res = await fetch('/api/vn-address/old-provinces');
            const data = await res.json();
            
            if (Array.isArray(data)) {
                this.oldProvinces = data;
                
                // Build lookup maps
                this.oldProvinceByCode = {};
                this.oldProvinceByName = {};
                
                for (const p of data) {
                    this.oldProvinceByCode[p.code] = p.name;
                    
                    const norm = this._normText(p.name);
                    this.oldProvinceByName[norm] = { name: p.name, code: p.code };
                    
                    // Also add aliases
                    const lower = p.name.toLowerCase();
                    this.oldProvinceByName[lower] = { name: p.name, code: p.code };
                }
            }
        } catch (e) {
            console.warn('[PMS] Could not load old provinces:', e);
        }
    },
    
    async _loadOldDistricts(provinceCode) {
        if (this.oldDistricts[provinceCode]) return this.oldDistricts[provinceCode];
        
        try {
            const res = await fetch(`/api/vn-address/old-districts/${provinceCode}`);
            const data = await res.json();
            
            if (data?.districts) {
                this.oldDistricts[provinceCode] = data.districts;
            }
        } catch (e) {
            console.warn(`[PMS] Could not load districts for province ${provinceCode}:`, e);
        }
        
        return this.oldDistricts[provinceCode] || [];
    },
    
    async _loadOldWards(districtCode) {
        if (this.oldWards[districtCode]) return this.oldWards[districtCode];
        
        try {
            const res = await fetch(`/api/vn-address/old-wards/${districtCode}`);
            const data = await res.json();
            
            if (data?.wards) {
                this.oldWards[districtCode] = data.wards;
            }
        } catch (e) {
            console.warn(`[PMS] Could not load wards for district ${districtCode}:`, e);
        }
        
        return this.oldWards[districtCode] || [];
    },
    
    _normText(s) {
        if (!s) return '';
        return String(s).trim().toLowerCase()
            .replace(/[.,\-/_]+/g, ' ')
            .replace(/\s+/g, ' ');
    },
    
    // Quick lookup without await (returns cached or empty)
    getNewWardsSync(provinceShort) {
        return this.newWards[provinceShort] || null;
    },
    
    getOldProvinceByName(name) {
        const norm = this._normText(name);
        return this.oldProvinceByName[norm] || null;
    },
};

// ─────────────────────────────────────────────────────────────────────────────
// LOADING OVERLAY — Show when filling address fields
// ─────────────────────────────────────────────────────────────────────────────
const PMS_LOADING_OVERLAY = {
    _active: false,
    _container: null,
    
    show(targetEl, message = 'Đang tải địa chỉ...') {
        if (this._active) return;
        this._active = true;
        
        // Remove existing if any
        this.hide();
        
        // Create overlay
        const overlay = document.createElement('div');
        overlay.id = 'pms-addr-loading-overlay';
        overlay.className = 'pms-addr-loading-overlay';
        overlay.innerHTML = `
            <div class="pms-addr-loading-spinner"></div>
            <div class="pms-addr-loading-text">${message}</div>
        `;
        
        // Position relative to target
        if (targetEl) {
            targetEl.style.position = 'relative';
            targetEl.appendChild(overlay);
        } else {
            document.body.appendChild(overlay);
        }
        
        this._container = overlay;
    },
    
    update(message) {
        if (!this._container) return;
        const textEl = this._container.querySelector('.pms-addr-loading-text');
        if (textEl) textEl.textContent = message;
    },
    
    hide() {
        if (this._container) {
            this._container.remove();
            this._container = null;
        }
        this._active = false;
    },
};

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

const PMS_VN_TZ = 'Asia/Ho_Chi_Minh';

// Safely parse ISO date strings cross-browser (fixes Safari fractional seconds bug)
function pmsParseDate(iso) {
    if (!iso) return new Date(NaN);
    if (typeof iso === 'string') {
        let clean = iso.replace(/(\.\d{3})\d+/, '$1');
        clean = clean.replace(' ', 'T');
        return new Date(clean);
    }
    return new Date(iso);
}

function pmsFormatDateTimeVN(isoOrDate) {
    if (isoOrDate == null || isoOrDate === '') return '—';
    const d = isoOrDate instanceof Date ? isoOrDate : pmsParseDate(isoOrDate);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString('vi-VN', {
        timeZone: PMS_VN_TZ,
        hour: '2-digit',
        minute: '2-digit',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
    });
}

function pmsFormatDateVN(isoOrDate) {
    if (isoOrDate == null || isoOrDate === '') return '—';
    const d = isoOrDate instanceof Date ? isoOrDate : pmsParseDate(isoOrDate);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('vi-VN', {
        timeZone: PMS_VN_TZ,
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
    });
}

function pmsDateToDatetimeLocalVN(d) {
    if (!d || Number.isNaN(d.getTime())) return '';
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: PMS_VN_TZ,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).formatToParts(d);
    const v = (t) => parts.find((p) => p.type === t)?.value ?? '00';
    return `${v('year')}-${v('month')}-${v('day')}T${v('hour')}:${v('minute')}`;
}

// Format birth date dd/mm/yyyy
function pmsFdate(iso) {
    if (!iso) return '';
    try {
        const d = pmsParseDate(iso + (iso.length === 10 ? 'T12:00:00' : ''));
        if (Number.isNaN(d.getTime())) return iso;
        return pmsFormatDateVN(d);
    } catch { return iso; }
}

// Format datetime for display
function pmsFdt(iso) {
    if (!iso) return '—';
    return pmsFormatDateTimeVN(iso);
}

// Format datetime long: DD/MM/YY | HH:mm
function pmsFdtLong(iso) {
    if (!iso) return '—';
    const d = pmsParseDate(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const p = (n) => String(n).padStart(2, '0');
    const f = new Intl.DateTimeFormat('en-CA', {
        timeZone: PMS_VN_TZ,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
    const parts = f.formatToParts(d);
    const v = (t) => parts.find((x) => x.type === t)?.value ?? '00';
    const yy = v('year').slice(-2);
    return `${v('day')}/${v('month')}/${yy} ${v('hour')}:${v('minute')}`;
}

// Format currency VND
function pmsMoney(n) {
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(n || 0);
}

// Render pricing breakdown (Time-Slicing Engine output) vào container
// Dùng trong pricing preview modal và checkout info
function pmsRenderPricingBreakdown(breakdown, config, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!breakdown || breakdown.length === 0) {
        container.innerHTML = `<div style="padding:24px; color:#94a3b8; font-size:13px; text-align:center;">Không có dữ liệu giá</div>`;
        return;
    }

    const sliceMeta = {
        early:    { icon: '🌅', label: 'Phí nhận sớm',   color: '#d97706', bg: '#fffbeb' },
        core:     { icon: '🛏', label: 'Tiền phòng',     color: '#2563eb', bg: '#eff6ff' },
        late:     { icon: '🌇', label: 'Phí trả muộn',   color: '#d97706', bg: '#fffbeb' },
        night:    { icon: '🌙', label: 'Giá ban đêm',   color: '#7c3aed', bg: '#f5f3ff' },
        overflow: { icon: '⏸', label: 'Vùng chuyển tiếp', color: '#94a3b8', bg: '#f8fafc' },
        unknown:  { icon: '📋', label: 'Phí dịch vụ',     color: '#64748b', bg: '#f1f5f9' },
    };

    const typeMeta = {
        EARLY_CHECKIN_FEE:  { label: 'Phí nhận sớm',   color: '#d97706' },
        LATE_CHECKOUT_FEE:  { label: 'Phí trả muộn',   color: '#d97706' },
        ROOM_CHARGE:         { label: 'Tiền phòng (đêm)', color: '#2563eb' },
        HOURLY_CHARGE:        { label: 'Tiền phòng (giờ)', color: '#7c3aed' },
    };

    let html = '';
    breakdown.forEach(item => {
        const sliceType = item.slice_type || 'unknown';
        const meta = sliceMeta[sliceType] || sliceMeta.unknown;
        const typeInfo = typeMeta[item.type] || { label: item.description || item.type, color: meta.color };

        const qtyLabel = item.hours ? `${item.hours}h` : (item.days ? `${item.days}N` : 'x1');
        const modeBadge = item.mode ? `<span style="font-size:9px; font-weight:700; padding:1px 5px; background:${item.mode === 'DAILY' ? '#dcfce7' : '#f5f3ff'}; color:${item.mode === 'DAILY' ? '#15803d' : '#7c3aed'}; border-radius:4px; margin-left:4px;">${item.mode}</span>` : '';

        html += `
        <div style="display:grid; grid-template-columns:auto 1fr auto; gap:0 12px; align-items:center;
                    padding:10px 0; border-bottom:1px solid #f1f5f9;">
            <div style="width:32px; height:32px; background:${meta.bg}; border-radius:8px;
                        display:flex; align-items:center; justify-content:center; font-size:16px;
                        flex-shrink:0;">
                ${meta.icon}
            </div>
            <div style="display:flex; flex-direction:column; gap:2px;">
                <span style="font-size:13px; font-weight:600; color:#1e293b;">
                    ${pmsEscapeHtml(typeInfo.label)}
                    ${modeBadge}
                </span>
                <span style="font-size:11px; color:#94a3b8;">${pmsEscapeHtml(item.description || '')}</span>
            </div>
            <div style="text-align:right; flex-shrink:0;">
                <div style="font-size:15px; font-weight:700; color:#0f172a; font-family:'Courier New',monospace;">
                    ${pmsMoney(item.amount)}
                </div>
                <div style="font-size:10px; color:#94a3b8;">x${qtyLabel}</div>
            </div>
        </div>`;
    });

    const total = breakdown.reduce((acc, item) => acc + (item.amount || 0), 0);
    html = `
        <div style="padding:8px 0 4px; margin-bottom:4px;">
            ${html}
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 0 0;
                    border-top:2px solid #e2e8f0; margin-top:4px;">
            <span style="font-size:14px; font-weight:700; color:#0f172a;">Tổng cộng</span>
            <span style="font-size:20px; font-weight:800; color:#0369a1; font-family:'Courier New',monospace;">
                ${pmsMoney(total)}
            </span>
        </div>`;

    container.innerHTML = html;
}

// Convert Date to ISO string
function pmsToISO(d) {
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Duration from check-in (hours/minutes)
function pmsDur(fromISO) {
    const ms = Date.now() - pmsParseDate(fromISO).getTime();
    if (ms < 0) return '—';
    const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000);
    return h > 0 ? `${h}g ${m}p` : `${m} phút`;
}

// Duration nights
function pmsDurNights(fromISO) {
    const ms = Date.now() - pmsParseDate(fromISO).getTime();
    if (ms < 0) return '0 đêm';
    const days = Math.floor(ms / (24 * 3600000));
    return days > 0 ? `${days} đêm` : '< 1 đêm';
}

// Full duration (days, hours, minutes)
function pmsDurFull(fromISO) {
    const ms = Date.now() - pmsParseDate(fromISO).getTime();
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

// Format duration for live counter: [X ngày] HH:mm:ss (fromISO string hoặc epoch ms)
function pmsFormatDurLive(fromISOOrMs) {
    let fromMs;
    if (typeof fromISOOrMs === 'number' && Number.isFinite(fromISOOrMs)) {
        fromMs = fromISOOrMs;
    } else if (fromISOOrMs != null && fromISOOrMs !== '') {
        fromMs = pmsParseDate(fromISOOrMs).getTime();
    } else {
        return '00:00:00';
    }
    if (!Number.isFinite(fromMs)) return '00:00:00';
    const ms = Date.now() - fromMs;
    if (ms < 0) return '00:00:00';
    const days = Math.floor(ms / 86400000);
    const remMs = ms % 86400000;
    const h = Math.floor(remMs / 3600000);
    const m = Math.floor((remMs % 3600000) / 60000);
    const s = Math.floor((remMs % 60000) / 1000);
    const p = n => String(n).padStart(2, '0');
    let res = `${p(h)}:${p(m)}:${p(s)}`;
    if (days > 0) res = `${days} ngày ${res}`;
    return res;
}

function pmsEnsureToastStyles() {
    if (document.getElementById('pms-toast-runtime-style')) return;
    const style = document.createElement('style');
    style.id = 'pms-toast-runtime-style';
    style.textContent = `
        #pms-toast-stack {
            position: fixed !important;
            top: max(18px, env(safe-area-inset-top, 0px) + 12px) !important;
            right: max(18px, env(safe-area-inset-right, 0px) + 12px) !important;
            bottom: auto !important;
            left: auto !important;
            z-index: 2147483647 !important;
            width: min(400px, calc(100vw - 28px)) !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
            pointer-events: none !important;
        }
        .pms-toast-card {
            --toast-accent: #2563eb;
            --toast-bg: rgba(239, 246, 255, 0.97);
            --toast-border: rgba(37, 99, 235, 0.20);
            --toast-icon-bg: rgba(37, 99, 235, 0.10);
            --toast-icon-color: #1d4ed8;
            --toast-title-color: #0f172a;
            --toast-msg-color: #475569;
            position: relative;
            display: grid;
            grid-template-columns: 36px minmax(0, 1fr) 24px;
            align-items: start;
            gap: 10px;
            padding: 14px 12px 14px 14px;
            overflow: hidden;
            pointer-events: auto;
            border: 1px solid var(--toast-border);
            border-left: 4px solid var(--toast-accent);
            border-radius: 14px;
            background: var(--toast-bg);
            box-shadow: 0 4px 6px -1px rgba(0,0,0,.07), 0 10px 28px -4px rgba(0,0,0,.10);
            backdrop-filter: blur(16px) saturate(1.4);
            -webkit-backdrop-filter: blur(16px) saturate(1.4);
            isolation: isolate;
            animation: pmsToastEnter .22s cubic-bezier(.16, 1, .3, 1) both;
        }
        .pms-toast-card.ok {
            --toast-accent: #16a34a;
            --toast-bg: rgba(240, 253, 244, 0.97);
            --toast-border: rgba(22, 163, 74, 0.20);
            --toast-icon-bg: rgba(22, 163, 74, 0.10);
            --toast-icon-color: #15803d;
        }
        .pms-toast-card.err {
            --toast-accent: #dc2626;
            --toast-bg: rgba(254, 242, 242, 0.97);
            --toast-border: rgba(220, 38, 38, 0.20);
            --toast-icon-bg: rgba(220, 38, 38, 0.10);
            --toast-icon-color: #b91c1c;
        }
        .pms-toast-card.warn {
            --toast-accent: #d97706;
            --toast-bg: rgba(255, 251, 235, 0.97);
            --toast-border: rgba(217, 119, 6, 0.22);
            --toast-icon-bg: rgba(217, 119, 6, 0.10);
            --toast-icon-color: #92400e;
        }
        .pms-toast-card.info {
            --toast-accent: #0284c7;
            --toast-bg: rgba(240, 249, 255, 0.97);
            --toast-border: rgba(2, 132, 199, 0.20);
            --toast-icon-bg: rgba(2, 132, 199, 0.10);
            --toast-icon-color: #0369a1;
        }
        .pms-toast-card.is-leaving { animation: pmsToastExit .16s ease-in forwards; }
        .pms-toast-icon-badge {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            color: var(--toast-icon-color);
            background: var(--toast-icon-bg);
            margin-top: 1px;
        }
        .pms-toast-content { min-width: 0; padding-top: 2px; }
        .pms-toast-title {
            margin: 0 0 3px;
            color: var(--toast-title-color);
            font-size: 13px;
            font-weight: 700;
            letter-spacing: -.01em;
            line-height: 1.3;
        }
        .pms-toast-msg {
            color: var(--toast-msg-color);
            font-size: 12.5px;
            line-height: 1.5;
            overflow-wrap: anywhere;
        }
        .pms-toast-close {
            width: 24px;
            height: 24px;
            border: 0;
            border-radius: 6px;
            color: var(--toast-msg-color);
            background: transparent;
            font-size: 18px;
            line-height: 1;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-top: 2px;
            transition: background .12s, color .12s;
        }
        .pms-toast-close:hover {
            color: var(--toast-title-color);
            background: rgba(0, 0, 0, .06);
        }
        .pms-toast-progress {
            position: absolute;
            right: 0;
            bottom: 0;
            left: 4px;
            height: 2px;
            overflow: hidden;
            border-radius: 0 0 14px 0;
            background: transparent;
        }
        .pms-toast-progress span {
            display: block;
            width: 100%;
            height: 100%;
            background: var(--toast-accent);
            opacity: .35;
            transform-origin: left center;
            animation: pmsToastProgress var(--toast-duration, 4200ms) linear forwards;
        }
        html.dark .pms-toast-card,
        body.dark .pms-toast-card,
        .dark-mode .pms-toast-card,
        .dark .pms-toast-card {
            --toast-bg: rgba(15, 23, 42, 0.96);
            --toast-border: rgba(148, 163, 184, 0.16);
            --toast-title-color: #f1f5f9;
            --toast-msg-color: #94a3b8;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,.3), 0 10px 28px -4px rgba(0,0,0,.4);
        }
        html.dark .pms-toast-card.ok,
        body.dark .pms-toast-card.ok,
        .dark-mode .pms-toast-card.ok,
        .dark .pms-toast-card.ok {
            --toast-bg: rgba(5, 46, 22, 0.95);
            --toast-border: rgba(22, 163, 74, 0.28);
            --toast-icon-bg: rgba(22, 163, 74, 0.18);
            --toast-icon-color: #4ade80;
        }
        html.dark .pms-toast-card.err,
        body.dark .pms-toast-card.err,
        .dark-mode .pms-toast-card.err,
        .dark .pms-toast-card.err {
            --toast-bg: rgba(69, 10, 10, 0.95);
            --toast-border: rgba(220, 38, 38, 0.28);
            --toast-icon-bg: rgba(220, 38, 38, 0.18);
            --toast-icon-color: #f87171;
        }
        html.dark .pms-toast-card.warn,
        body.dark .pms-toast-card.warn,
        .dark-mode .pms-toast-card.warn,
        .dark .pms-toast-card.warn {
            --toast-bg: rgba(69, 26, 3, 0.95);
            --toast-border: rgba(217, 119, 6, 0.28);
            --toast-icon-bg: rgba(217, 119, 6, 0.18);
            --toast-icon-color: #fbbf24;
        }
        html.dark .pms-toast-card.info,
        body.dark .pms-toast-card.info,
        .dark-mode .pms-toast-card.info,
        .dark .pms-toast-card.info {
            --toast-bg: rgba(3, 30, 56, 0.95);
            --toast-border: rgba(2, 132, 199, 0.28);
            --toast-icon-bg: rgba(2, 132, 199, 0.18);
            --toast-icon-color: #38bdf8;
        }
        html.dark .pms-toast-close:hover,
        body.dark .pms-toast-close:hover,
        .dark-mode .pms-toast-close:hover,
        .dark .pms-toast-close:hover { background: rgba(255,255,255,.08); }
        @keyframes pmsToastEnter {
            from { opacity: 0; transform: translate3d(16px, -6px, 0) scale(.96); }
            to   { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
        }
        @keyframes pmsToastExit {
            to { opacity: 0; transform: translate3d(16px, -4px, 0) scale(.97); }
        }
        @keyframes pmsToastProgress { to { transform: scaleX(0); } }
        @media (max-width: 720px) {
            #pms-toast-stack {
                top: max(12px, env(safe-area-inset-top, 0px) + 8px) !important;
                right: 12px !important;
                left: 12px !important;
                width: auto !important;
            }
        }
        @media (prefers-reduced-motion: reduce) {
            .pms-toast-card,
            .pms-toast-progress span { animation: none !important; transition: none !important; }
        }
    `;
    document.head.appendChild(style);
}

function pmsToastIcon(type) {
    if (type === 'ok') return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>`;
    if (type === 'err') return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/></svg>`;
    if (type === 'warn') return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>`;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`;
}

function pmsNormalizeToastType(type) {
    if (type === true || type === 'ok' || type === 'success' || type === 'complete' || type === 'add' || type === 'update') return 'ok';
    if (type === false || type === 'err' || type === 'error' || type === 'danger' || type === 'delete') return 'err';
    if (type === 'warn' || type === 'warning') return 'warn';
    return 'info';
}

function pmsToastDefaults(type) {
    if (type === 'ok') return 'Thành công';
    if (type === 'err') return 'Lỗi hệ thống';
    if (type === 'warn') return 'Cảnh báo';
    return 'Thông báo';
}

function pmsNormalizeToastOptions(input, status) {
    const raw = input && typeof input === 'object' && !Array.isArray(input) ? input : { message: input, type: status };
    const type = pmsNormalizeToastType(raw.type ?? raw.status ?? raw.ok ?? status ?? 'info');
    return {
        type,
        title: raw.title || pmsToastDefaults(type),
        message: raw.message ?? raw.msg ?? raw.text ?? '',
        icon: raw.icon || pmsToastIcon(type),
        sound: raw.sound || '',
        duration: Number(raw.duration || raw.delay || 4200)
    };
}

// ── Web Audio sound system ──────────────────────────────────────────
let _pmsAudioCtx = null;
function _pmsGetAudioCtx() {
    if (!_pmsAudioCtx || _pmsAudioCtx.state === 'closed') {
        try { _pmsAudioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}
    }
    return _pmsAudioCtx;
}

function pmsPlaySound(type) {
    try {
        const ctx = _pmsGetAudioCtx();
        if (!ctx) return;
        if (ctx.state === 'suspended') ctx.resume();
        const gain = ctx.createGain();
        gain.connect(ctx.destination);
        const osc = ctx.createOscillator();
        osc.connect(gain);
        const now = ctx.currentTime;
        if (type === 'ok' || type === 'success') {
            // Two-tone ascending chime
            osc.type = 'sine';
            osc.frequency.setValueAtTime(523, now);
            osc.frequency.setValueAtTime(784, now + 0.1);
            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.18, now + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38);
            osc.start(now);
            osc.stop(now + 0.38);
        } else if (type === 'err' || type === 'error') {
            // Low descending tone
            osc.type = 'sine';
            osc.frequency.setValueAtTime(330, now);
            osc.frequency.setValueAtTime(220, now + 0.12);
            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.20, now + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.36);
            osc.start(now);
            osc.stop(now + 0.36);
        } else if (type === 'warn') {
            // Double pulse
            osc.type = 'sine';
            osc.frequency.setValueAtTime(440, now);
            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.16, now + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.14);
            gain.gain.setValueAtTime(0, now + 0.18);
            gain.gain.linearRampToValueAtTime(0.14, now + 0.20);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.34);
            osc.start(now);
            osc.stop(now + 0.34);
        } else if (type === 'click') {
            // Soft click
            osc.type = 'sine';
            osc.frequency.setValueAtTime(600, now);
            osc.frequency.exponentialRampToValueAtTime(300, now + 0.06);
            gain.gain.setValueAtTime(0.10, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.06);
            osc.start(now);
            osc.stop(now + 0.06);
        } else {
            // Info — soft single tone
            osc.type = 'sine';
            osc.frequency.setValueAtTime(660, now);
            gain.gain.setValueAtTime(0, now);
            gain.gain.linearRampToValueAtTime(0.14, now + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
            osc.start(now);
            osc.stop(now + 0.28);
        }
    } catch (e) {}
}

function pmsPlayToastSound(src) {
    if (!src) return;
    try {
        const audio = new Audio(src);
        audio.volume = 0.6;
        audio.play().catch(() => {});
    } catch (e) {}
}

// Attach click sound to buttons — call once after DOM ready
function pmsInitButtonSounds() {
    if (document.getElementById('pms-btn-sound-init')) return;
    const marker = document.createElement('meta');
    marker.id = 'pms-btn-sound-init';
    document.head.appendChild(marker);

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('button, .bk-btn, .bk-mini-btn, .bk-icon-btn, .bk-method-card-v2, .bk-deposit-mode-card, .bk-nav-item, .bk-avail-card:not(.sold-out), .bk-assign-room, .bk-waitlist-item, .rs-date-header, .rs-avail-tile, .rs-booking-bar, .ci-btn, .ci-action-btn');
        if (!btn) return;
        if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') return;

        // Determine sound type from button context
        const isPrimary = btn.classList.contains('primary') || btn.classList.contains('success') || btn.classList.contains('bk-avail-card') || btn.classList.contains('bk-assign-room');
        const isDanger = btn.classList.contains('danger') || btn.classList.contains('bk-assign-danger') || btn.classList.contains('rs-assign-danger');
        const isClose = btn.classList.contains('bk-close') || btn.classList.contains('pms-toast-close') || btn.classList.contains('bk-wiz-back');

        if (isDanger) pmsPlaySound('warn');
        else if (isPrimary) pmsPlaySound('click');
        else if (isClose) pmsPlaySound('click');
        else pmsPlaySound('click');
    }, { passive: true });
}

window.pmsPlaySound = pmsPlaySound;

function pmsToast(input, status = true) {
    pmsEnsureToastStyles();
    const config = pmsNormalizeToastOptions(input, status);
    const duration = Number.isFinite(config.duration) && config.duration > 0 ? config.duration : 4200;

    document.getElementById('pms-toast')?.remove();

    let stack = document.getElementById('pms-toast-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.id = 'pms-toast-stack';
        stack.setAttribute('aria-live', 'polite');
        stack.setAttribute('aria-atomic', 'false');
        document.body.appendChild(stack);
    }

    const el = document.createElement('div');
    el.className = `pms-toast-card ${config.type}`;
    el.setAttribute('role', config.type === 'err' ? 'alert' : 'status');
    el.style.setProperty('--toast-duration', `${duration}ms`);
    el.innerHTML = `
        <div class="pms-toast-icon-badge" aria-hidden="true">${config.icon}</div>
        <div class="pms-toast-content">
            <div class="pms-toast-title">${pmsEscapeHtml(String(config.title || ''))}</div>
            <div class="pms-toast-msg">${pmsEscapeHtml(String(config.message || ''))}</div>
        </div>
        <button class="pms-toast-close" type="button" aria-label="Đóng thông báo">×</button>
        <div class="pms-toast-progress" aria-hidden="true"><span></span></div>
    `;

    const dismiss = () => {
        if (el._t) clearTimeout(el._t);
        el.classList.add('is-leaving');
        setTimeout(() => el.remove(), 180);
    };

    el.querySelector('.pms-toast-close')?.addEventListener('click', dismiss, { once: true });
    stack.appendChild(el);
    while (stack.children.length > 4) stack.firstElementChild?.remove();
    el._t = setTimeout(dismiss, duration);
    if (config.sound) pmsPlayToastSound(config.sound);
    else pmsPlaySound(config.type);
    return el;
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
    if (!r.ok) {
        const message = typeof d.detail === 'string'
            ? d.detail
            : (typeof d.message === 'string'
                ? d.message
                : (d.detail?.message || 'Lỗi server'));
        const err = new Error(message);
        err.status = r.status;
        err.detail = d.detail;
        err.payload = d;
        throw err;
    }
    return d;
}

// Escape HTML
function pmsEscapeHtml(s) {
    if (!s) return '';
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

/** Convert name to Title Case: "BÙI HẠNH" → "Bùi Hạnh" */
function pmsTitleCase(s) {
    if (!s) return '';
    return String(s).trim().split(/\s+/).map(w =>
        w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
    ).join(' ');
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
window.PMS = window.PMS || { floors: {}, branchId: null, roomTypes: [], timer: null, _loading: false };

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
window.pmsParseDate = pmsParseDate;
window.PMS_VN_TZ = PMS_VN_TZ;
window.pmsFormatDateTimeVN = pmsFormatDateTimeVN;
window.pmsFormatDateVN = pmsFormatDateVN;
window.pmsDateToDatetimeLocalVN = pmsDateToDatetimeLocalVN;
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
window.pmsFormatDurLive = pmsFormatDurLive;
window.pmsFdtLong = pmsFdtLong;
window.pmsRenderPricingBreakdown = pmsRenderPricingBreakdown;
window.pmsInitButtonSounds = pmsInitButtonSounds;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', pmsInitButtonSounds);
} else {
    pmsInitButtonSounds();
}

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
/** Địa chỉ QR còn cấp Quận/Huyện sau dấu phẩy → dùng tách 4 cấp (CCCD_CU). */
function _pmsIsProvinceRepeat(first, second) {
    if (!first || !second) return false;
    const a = _pmsNormVietnamese(_pmsStripPrefix(first)).replace(/[.\s]/g, '');
    const b = _pmsNormVietnamese(_pmsStripPrefix(second)).replace(/[.\s]/g, '');
    const aliases = {
        hanoi: 'hanoi', thanhphohanoi: 'hanoi', tphanoi: 'hanoi', hn: 'hanoi',
        tphcm: 'hcm', hcm: 'hcm', hochiminh: 'hcm', thanhphohochiminh: 'hcm',
        danang: 'danang', thanhphodanang: 'danang', tpdanang: 'danang',
    };
    return (aliases[a] || a) === (aliases[b] || b);
}

function _pmsAddressHintsOldAdminLevels(raw) {
    if (!raw || !String(raw).trim()) return false;

    const addr = String(raw).trim();
    const parts = addr.split(',').map(p => p.trim()).filter(Boolean);

    if (parts.length >= 3 && _pmsIsNewWardInProvince(parts[parts.length - 2], parts[parts.length - 1])) {
        return false;
    }

    if (parts.length >= 4 && _pmsIsProvinceRepeat(parts[parts.length - 2], parts[parts.length - 1])) {
        return false;
    }

    // Pattern 1: Prefix rõ ràng
    if (/,\s*(quận|huyện|thị xã|thị trấn|tx\.)\s/i.test(addr)) {
        return true;
    }

    // Pattern 2: Count dấu phẩy → nếu >= 3 dấu phẩy → 4 cấp
    const commaCount = (addr.match(/,/g) || []).length;
    if (commaCount >= 3) {
        return true;
    }

    // Pattern 3: Các quận/huyện phổ biến không có prefix
    const knownDistricts = [
        "nam từ liêm", "bình thạnh", "thủ đức", "phú nhuận", "tân bình",
        "tân phú", "gò vấp", "bình tân", "hóc môn", "củ chi", "cần giờ",
        "long biên", "cầu giấy", "đống đa", "hai bà trưng", "hoàn kiếm",
        "ba đình", "tây hồ", "thanh xuân", "hà đông", "hoàng mai",
        "bắc từ liêm", "nam từ liêm", "đông anh", "gia lâm",
        "ba vì", "chương mỹ", "đan phượng", "hoài đức", "mê linh",
        "phú xuyên", "quốc oai", "sóc sơn", "thạch thất", "thường tín",
        "ứng hòa",
    ];

    // Tách parts để kiểm tra
    const lowerParts = addr.split(',').map(p => p.trim().toLowerCase());

    // Kiểm tra nếu có phần tử là tên quận/huyện
    for (let i = 0; i < lowerParts.length; i++) {
        const part = lowerParts[i];

        // Skip nếu là số nhà, tổ, KP
        if (/^(số|tổ|kp|đường|phố)\s*\d/i.test(part)) continue;
        // Skip nếu là phường/xã
        if (/^(phường|xã)\s*\d/i.test(part)) continue;

        for (const district of knownDistricts) {
            if (part.includes(district)) {
                // Cần ít nhất 2 phần tử trước đó (detail + ward)
                if (i >= 2) {
                    return true;
                }
            }
        }
    }

    return false;
}

function _pmsIsNewWardInProvince(ward, province) {
    if (!ward || !province) return false;
    const provinceKey = _pmsNormVietnamese(_pmsStripPrefix(province)).replace(/[.\s]/g, '');
    const wardNorm = _pmsNormVietnamese(_pmsStripPrefix(ward)).replace(/[.\s]/g, '');
    const hcmKeys = new Set(['tphcm', 'hcm', 'hochiminh', 'thanhphohochiminh']);
    if (hcmKeys.has(provinceKey) && wardNorm === 'minhthanh') return true;
    return false;
}

function _pmsNormalizeQrRaw(raw) {
    let s = String(raw || '');
    if (typeof s.normalize === 'function') s = s.normalize('NFKC');
    s = s.replace(/﻿/g, '')
         .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
         .replace(/\r\n|\r|\n/g, '')
         .replace(/[｜¦]/g, '|')
         .replace(/\|{3,}/g, '||');
    if (typeof s.normalize === 'function') s = s.normalize('NFC');
    return s.trim();
}

function _pmsNormCompare(s) {
    return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[.\s]/g, '').trim();
}

function _pmsNormalizeGender(value) {
    const v = _pmsNormCompare(value);
    if (['nam', 'male', 'm'].includes(v)) return 'Nam';
    if (['nu', 'n', 'female', 'f'].includes(v)) return 'Nữ';
    return '';
}

function _pmsBirthGenderFromCCCD(id) {
    if (!/^\d{12}$/.test(id || '')) return null;
    const code = Number(id[3]);
    const year = Number(id.slice(4, 6));
    return { gender: code % 2 === 0 ? 'Nam' : 'Nữ', birthYear: 1900 + Math.floor(code / 2) * 100 + year };
}

function _pmsIsAddressLikeField(p) {
    return /[,\d]|TP\.|Tỉnh|Thành phố|Quận|Huyện|Phường|Xã|Đường|Phố|Tổ|KP/i.test(String(p || ''));
}

function _pmsIsNameLikeField(p) {
    const s = String(p || '').trim();
    if (!s || _pmsIsAddressLikeField(s)) return false;
    const words = s.split(/\s+/).filter(Boolean);
    if (words.length < 2 || words.length > 6) return false;
    return words.every(w => /^[A-Za-zÀ-ỹĐđ'’-]+$/.test(w));
}

function pmsParseScanCCCD(raw) {
    let cleaned = _pmsNormalizeQrRaw(raw);
    const prefixes = ["CĂN CƯỚC CÔNG DÂN:", "CCCD:", "CMND:", "CAN CUOC:", "CANCUOC:"];
    for (const p of prefixes) {
        if (cleaned.toUpperCase().startsWith(p)) {
            cleaned = cleaned.slice(p.length).trim();
            break;
        }
    }

    const CCCD_CU = "CCCD_CU", CAN_CUOC_MOI = "CAN_CUOC_MOI", CMND_TYPE = "CMND";

    const result = {
        card_type: "", address_mode: "", id_number: "", old_id: "", name: "",
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
        } else if (re9.test(p) && !result.old_id) {
            result.old_id = p;
        } else if (re8.test(p)) {
            const d = parseInt(p.slice(0, 2)), m = parseInt(p.slice(2, 4)), y = parseInt(p.slice(4));
            const dt = new Date(y, m - 1, d);
            if (dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d) {
                const fmt = `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}/${y}`;
                dateCandidates.push({ raw: p, fmt });
            }
        } else {
            const normalizedGender = _pmsNormalizeGender(p);
            if (normalizedGender) {
                result.gender = normalizedGender;
            } else if (!result.name && _pmsIsNameLikeField(p)) {
                result.name = pmsTitleCase(p.trim());
            } else if (p.length > addressCandidate.length && _pmsIsAddressLikeField(p)) {
                addressCandidate = p;
            }
        }
    }

    // ── Card type detection ───────────────────────────────────────────────
    const idEvidence = _pmsBirthGenderFromCCCD(result.id_number);
    const conflicts = [];
    const warnings = [];
    if (idEvidence) {
        if (result.gender && result.gender !== idEvidence.gender) conflicts.push('gender_mismatch');
        if (dateCandidates.length && parseInt(dateCandidates[0].raw.slice(4), 10) !== idEvidence.birthYear) {
            conflicts.push('birth_year_mismatch');
        }
        if (!result.gender) result.gender = idEvidence.gender;
    }

    let detectedCardType;
    if (!result.id_number && result.old_id) {
        detectedCardType = CMND_TYPE;
    } else {
        detectedCardType = CCCD_CU;
        if (!_pmsAddressHintsOldAdminLevels(addressCandidate)) {
            if (parts.length > 1 && parts[1].trim() === '') detectedCardType = CAN_CUOC_MOI;
            const emptyCount = parts.filter(p => !p.trim()).length;
            const nonEmptyCount = parts.filter(p => p.trim()).length;
            if (emptyCount >= 2 || nonEmptyCount > 7) detectedCardType = CAN_CUOC_MOI;
            if (dateCandidates.length >= 2) {
                const issueYear = parseInt(dateCandidates[dateCandidates.length - 1].raw.slice(4), 10);
                if (issueYear >= 2024) detectedCardType = CAN_CUOC_MOI;
            }
        }
    }
    result.card_type = detectedCardType;
    result.address_mode = detectedCardType === CMND_TYPE ? 'old'
                        : detectedCardType === CAN_CUOC_MOI && !_pmsAddressHintsOldAdminLevels(addressCandidate) ? 'new'
                        : 'old';
    result.conflicts = conflicts;
    result.warnings = warnings;

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
        const addr = _pmsParseAddressVN(addressCandidate, result.address_mode === 'new' ? CAN_CUOC_MOI : CCCD_CU);
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
    } else if (result.conflicts && result.conflicts.length) {
        result.error = "Dữ liệu QR mâu thuẫn";
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
 * OPTIMIZED: Uses preloaded cache, shows loading overlay, parallel data loading.
 *
 * @param {object|string} addr   - Parsed address from CCCD parser, or raw string
 * @param {string}        prefix  - 'ci' | 'eg' | 'ag'
 * @param {string}        cardType - 'CCCD_CU' | 'CAN_CUOC_MOI' | 'CMND'
 *
 * Flow:
 *   1. Preload all address data in background (once)
 *   2. Determine mode: CCCD_CU/CMND → 'old',  CAN_CUOC_MOI → 'new'
 *   3. Switch radio to correct mode
 *   4. Use cached data to populate datalists instantly
 *   5. Match province/district/ward using cached lookups
 *   6. Fill detail address
 */
async function pmsMatchAddressToForm(addr, prefix = 'ci', cardType = 'CCCD_CU') {
    const CCCD_CU = "CCCD_CU", CAN_CUOC_MOI = "CAN_CUOC_MOI", CMND_TYPE = "CMND";
    const preferredMode = addr && typeof addr === 'object' && addr.address_mode ? addr.address_mode : '';
    const mode = preferredMode || (cardType === CAN_CUOC_MOI ? 'new' : 'old');
    
    // ── 0. Ensure cache is loaded ─────────────────────────────────────────────
    // Show loading overlay on address section
    const addrSection = document.getElementById(_pmsAddressFieldId(prefix, 'addr-section')) ||
                        document.getElementById(`${prefix}-addr-section`) || 
                        document.querySelector(`.${prefix}-addr-section`) ||
                        document.querySelector('.ci-section');
    
    PMS_LOADING_OVERLAY.show(addrSection, 'Đang tải dữ liệu địa chỉ...');
    
    // Start preloading if not already done
    const cacheReady = await PMS_ADDR_CACHE.load();
    
    // ── 1. Normalize input ─────────────────────────────────────────────────────
    let province = '', ward = '', district = '', detail = '', rawStr = '';

    if (typeof addr === 'object' && addr !== null) {
        province = addr.province || '';
        ward     = addr.ward     || '';
        district = addr.district || '';
        detail   = addr.detail   || '';
        rawStr   = addr.raw      || '';
    } else if (typeof addr === 'string') {
        rawStr = addr;
        const parsed = _pmsParseAddressVN(addr, cardType);
        province = parsed.province;
        ward     = parsed.ward;
        district = parsed.district;
        detail   = parsed.detail;
    } else {
        PMS_LOADING_OVERLAY.hide();
        return;
    }

    if (!province && !rawStr) {
        PMS_LOADING_OVERLAY.hide();
        return;
    }
    
    PMS_LOADING_OVERLAY.update('Đang điền địa chỉ...');

    // ── 2. Switch radio to correct mode ───────────────────────────────────────
    const switchFnName = prefix === 'ci' ? 'vnSwitchMode'
                       : prefix === 'eg' ? 'egSwitchMode'
                       : prefix === 'bk' ? ''
                       : 'agSwitchMode';
    const switchFn = window[switchFnName];
    if (prefix === 'bk' && window.BookingHub && typeof window.BookingHub.switchBookingAddressMode === 'function') {
        await window.BookingHub.switchBookingAddressMode(mode, false);
    } else if (typeof switchFn === 'function') {
        await switchFn(mode, true);
    } else {
        const radioName = _pmsAddressRadioName(prefix);
        const radioNew = document.querySelector(`input[name="${radioName}"][value="new"]`);
        const radioOld = document.querySelector(`input[name="${radioName}"][value="old"]`);
        if (radioNew) radioNew.checked = (mode === 'new');
        if (radioOld)  radioOld.checked = (mode === 'old');
    }

    // ── 3. Use cache for province matching ────────────────────────────────────
    PMS_LOADING_OVERLAY.update(mode === 'new' ? 'Đang tìm phường/xã...' : 'Đang tìm quận/huyện...');
    
    const provEl = document.getElementById(_pmsAddressFieldId(prefix, 'province'));
    if (!provEl) {
        PMS_LOADING_OVERLAY.hide();
        return;
    }
    
    provEl.value = province;
    
    // Try to match province using enhanced strategies
    const ciProvDL = _pmsProvinceDatalistId(prefix);
    const provDL = document.getElementById(ciProvDL);
    
    let provMatched = null;
    if (provDL && provDL.options.length) {
        provMatched = _pmsMatchInOptions(province, provDL.options);
        if (provMatched) {
            provEl.value = provMatched;
        }
    }
    
    // ── 4. For NEW mode: match wards using cache ────────────────────────────────
    if (mode === 'new') {
        await _pmsMatchNewModeFast(provEl, ward, prefix);
    } else {
        // ── 5. For OLD mode: cascade with cache ─────────────────────────────────
        await _pmsMatchOldModeFast(provEl, district, ward, prefix);
    }
    
    // ── 6. Fill detail address ────────────────────────────────────────────────
    const detailEl = document.getElementById(_pmsAddressFieldId(prefix, 'address'));
    if (detailEl && detail) {
        detailEl.value = detail;
    }
    
    PMS_LOADING_OVERLAY.hide();
    
    // Highlight section briefly
    if (addrSection) {
        addrSection.classList.add('pms-addr-section-filling');
        setTimeout(() => addrSection.classList.remove('pms-addr-section-filling'), 600);
    }
}

/**
 * Fast match for NEW mode using cached wards
 */
async function _pmsMatchNewModeFast(provEl, ward, prefix) {
    // Get province short from datalist
    const ciProvDL = _pmsProvinceDatalistId(prefix);
    const provDL = document.getElementById(ciProvDL);
    
    if (!provDL) return;
    
    let provShort = null;
    for (const opt of provDL.options) {
        if (opt.value.trim().toLowerCase() === provEl.value.trim().toLowerCase()) {
            provShort = opt.dataset?.short || opt.dataset?.code || null;
            break;
        }
    }
    
    // Cascade to load wards
    const provChangeFns = {
        ci: window.vnOnProvinceChange,
        eg: window.egOnProvinceChange,
        ag: window.agOnProvinceChange,
        bk: (el) => window.BookingHub?.onBookingProvinceChange?.(el, true),
    };
    const provChangeFn = provChangeFns[prefix] || window.vnOnProvinceChange;
    if (typeof provChangeFn === 'function') {
        await provChangeFn(provEl);
    }
    
    // Match ward
    await _pmsWaitForDatalist(_pmsWardDatalistId(prefix), 1000);
    await _pmsMatchWardInDatalist(ward, prefix);
}

/**
 * Fast match for OLD mode using cached districts/wards
 * Handles empty district (CCCD cũ bị thiếu Quận)
 */
async function _pmsMatchOldModeFast(provEl, district, ward, prefix) {
    // Get province code for lookup
    const ciProvDL = _pmsProvinceDatalistId(prefix);
    const provDL = document.getElementById(ciProvDL);
    
    let provCode = null;
    if (provDL) {
        for (const opt of provDL.options) {
            if (_pmsNormVietnamese(opt.value.trim()) === _pmsNormVietnamese(provEl.value.trim())) {
                provCode = parseInt(opt.dataset?.code || '0') || null;
                break;
            }
        }
    }
    
    // Cascade to load districts
    const provChangeFns = {
        ci: window.vnOnProvinceChange,
        eg: window.egOnProvinceChange,
        ag: window.agOnProvinceChange,
        bk: (el) => window.BookingHub?.onBookingProvinceChange?.(el, true),
    };
    const provChangeFn = provChangeFns[prefix] || window.vnOnProvinceChange;
    if (typeof provChangeFn === 'function') {
        await provChangeFn(provEl);
    }
    
    // Wait for districts
    const ciDistDL = _pmsDistrictDatalistId(prefix);
    await _pmsWaitForDatalist(ciDistDL, 1000);
    
    const distEl = document.getElementById(_pmsAddressFieldId(prefix, 'district'));
    const distDL = document.getElementById(ciDistDL);
    
    // Check if district is empty (CCCD cũ bị thiếu Quận)
    const hasDistrict = district && district.trim() !== '';
    
    if (distEl && hasDistrict) {
        distEl.value = district;
        
        if (distDL && distDL.options.length) {
            const distMatched = _pmsMatchInOptions(district, distDL.options);
            if (distMatched) {
                distEl.value = distMatched;
            }
        }
        
        // Cascade to load wards
        const distChangeFns = {
            ci: window.vnOnDistrictChange,
            eg: window.egOnDistrictChange,
            ag: window.agOnDistrictChange,
            bk: (el) => window.BookingHub?.onBookingDistrictChange?.(el, true),
        };
        const distChangeFn = distChangeFns[prefix] || window.vnOnDistrictChange;
        if (typeof distChangeFn === 'function') {
            await distChangeFn(distEl);
        }
    } else if (distEl) {
        // No district - clear it and load wards directly (for TP.HCM, Hà Nội, etc.)
        distEl.value = '';
        
        // For old mode without district, we still need wards
        // Load wards using the province code directly
        if (provCode) {
            // Trigger ward datalist population - wards depend on district
            // In old mode, wards need district code, so we can't load them without district
            // Just leave ward empty for user to select
        }
    }
    
    // Wait for wards and match (if ward was provided)
    if (ward && ward.trim()) {
        await _pmsWaitForDatalist(_pmsWardDatalistId(prefix), 1000);
        await _pmsMatchWardInDatalist(ward, prefix);
    }
}

/**
 * Helper: Match a value in datalist options using multiple strategies
 * ENHANCED: Vietnamese diacritic-insensitive comparison, ward number normalization
 */
function _pmsMatchInOptions(value, options) {
    if (!value || !options || !options.length) return null;
    
    const stripped = _pmsStripPrefix(value);
    const valNorm = _pmsNormVietnamese(_pmsNormWardNumber(value));
    const strippedNorm = _pmsNormVietnamese(_pmsNormWardNumber(stripped));
    
    const strategies = [
        value,
        _pmsNormWardNumber(value),
        stripped,
        _pmsNormWardNumber(stripped),
        ..._pmsAddPrefix(stripped, ['Phường ', 'Xã ', 'Quận ', 'Huyện ', 'TP. ', 'Thành phố ']),
    ];
    
    const tried = new Set();
    for (const candidate of strategies) {
        if (!candidate) continue;
        const candNorm = _pmsNormVietnamese(_pmsNormWardNumber(candidate));
        if (tried.has(candNorm)) continue;
        tried.add(candNorm);
        
        for (const opt of options) {
            if (_pmsNormVietnamese(_pmsNormWardNumber(opt.value.trim())) === candNorm) {
                return opt.value;
            }
        }
    }
    
    // Contains match (diacritic-insensitive, ward-number-normalized)
    if (strippedNorm.length >= 3) {
        for (const opt of options) {
            const optStrippedNorm = _pmsNormVietnamese(_pmsNormWardNumber(_pmsStripPrefix(opt.value)));
            if (optStrippedNorm.includes(strippedNorm) || strippedNorm.includes(optStrippedNorm)) {
                return opt.value;
            }
        }
    }
    
    return null;
}

function _pmsWardDatalistId(prefix) {
    if (prefix === 'bk') return 'bk-dl-ward';
    return document.getElementById(`dl-${prefix}-ward`) ? `dl-${prefix}-ward` : 'dl-ward';
}
function _pmsDistrictDatalistId(prefix) {
    if (prefix === 'bk') return 'bk-dl-district';
    return document.getElementById(`dl-${prefix}-district`) ? `dl-${prefix}-district` : 'dl-district';
}
function _pmsProvinceDatalistId(prefix) {
    if (prefix === 'bk') return 'bk-dl-province';
    return document.getElementById(`dl-${prefix}-province`) ? `dl-${prefix}-province` : 'dl-province';
}

function _pmsAddressFieldId(prefix, field) {
    if (prefix === 'bk') {
        if (field === 'addr-section') return 'bk-addr-section';
        return `bk-form-${field}`;
    }
    return `${prefix}-${field}`;
}

function _pmsAddressRadioName(prefix) {
    return prefix === 'bk' ? 'bk-area' : `${prefix}-area`;
}

/** Match ward in the current datalist, with multiple strategies.
 * ENHANCED: Vietnamese diacritic-insensitive comparison
 */
async function _pmsMatchWardInDatalist(wardName, prefix) {
    if (!wardName) return;
    const wardEl = document.getElementById(_pmsAddressFieldId(prefix, 'ward'));
    if (!wardEl) return;
    const wardDL = document.getElementById(_pmsWardDatalistId(prefix));

    // Set value directly — do NOT dispatchEvent to avoid triggering handlers
    wardEl.value = wardName;

    if (!wardDL || !wardDL.options.length) return;

    const stripped = _pmsStripPrefix(wardName);
    const strippedNorm = _pmsNormVietnamese(stripped);
    // Get ALL prefix candidates
    const prefixedWardCandidates = _pmsAddPrefix(stripped, ['Phường ', 'Xã ']);
    const strategies = [
        wardName,
        _pmsNormWardNumber(wardName),  // Normalize ward number: "Phường 01" → "Phường 1"
        stripped,
        _pmsNormWardNumber(stripped),
        ...prefixedWardCandidates.map(p => _pmsNormWardNumber(p)),
        wardName.replace(/^Tổ\s*\d*[,\s]*/i, ''),
        wardName.replace(/,?\s*KP\d+\s*,?\s*/gi, ','),
    ];
    const unique = [...new Set(strategies)].filter(Boolean);

    let wardMatched = '';
    for (const candidate of unique) {
        const candNorm = _pmsNormVietnamese(_pmsNormWardNumber(candidate));
        for (const opt of wardDL.options) {
            const optNorm = _pmsNormVietnamese(_pmsNormWardNumber(opt.value.trim()));
            if (optNorm === candNorm) {
                wardMatched = opt.value; break;
            }
        }
        if (wardMatched) break;
    }

    if (!wardMatched) {
        // Contains match (strip prefix first, diacritic-insensitive, ward-number-normalized)
        for (const opt of wardDL.options) {
            const optStrippedNorm = _pmsNormVietnamese(_pmsNormWardNumber(_pmsStripPrefix(opt.value)));
            if ((optStrippedNorm.includes(strippedNorm) || strippedNorm.includes(optStrippedNorm)) && strippedNorm.length >= 4) {
                wardMatched = opt.value; break;
            }
        }
    }

    if (wardMatched) {
        wardEl.value = wardMatched;
    }

    // Trigger ward change handler directly (for old→new conversion display)
    // Do NOT use dispatchEvent('input') — that causes loops.
    const wardChangeFns = {
        ci: window.vnOnWardChange,
        eg: window.egOnWardChange,
        ag: window.agOnWardChange,
        bk: (el) => window.BookingHub?.onBookingWardChange?.(el),
    };
    const wardChangeFn = wardChangeFns[prefix] || window.vnOnWardChange;
    if (typeof wardChangeFn === 'function' && wardEl.value.trim()) {
        await wardChangeFn(wardEl);
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
    const provEl = document.getElementById(_pmsAddressFieldId(prefix, 'province'));
    const provDL = provEl?.dataset?.dl
        ? document.getElementById(provEl.dataset.dl)
        : document.getElementById(_pmsProvinceDatalistId(prefix));

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
    const mode = document.querySelector(`input[name="${_pmsAddressRadioName(prefix)}"]:checked`)?.value;
    const distEl = document.getElementById(_pmsAddressFieldId(prefix, 'district'));
    const distDL = distEl?.dataset?.dl
        ? document.getElementById(distEl.dataset.dl)
        : document.getElementById(_pmsDistrictDatalistId(prefix));

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
    const wardEl = document.getElementById(_pmsAddressFieldId(prefix, 'ward'));
    const wardDL = wardEl?.dataset?.dl
        ? document.getElementById(wardEl.dataset.dl)
        : document.getElementById(_pmsWardDatalistId(prefix));

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
 * Check if a value exists in datalist (case-insensitive, diacritic-insensitive, ward-number-normalized).
 */
function _pmsIsInDatalist(dl, value) {
    if (!dl || !value) return false;
    const v = value.trim();
    const vNorm = _pmsNormVietnamese(_pmsNormWardNumber(v));

    for (const opt of dl.options) {
        const optVal = opt.value.trim();
        // Exact match (with ward number + diacritic normalization)
        const optNorm = _pmsNormVietnamese(_pmsNormWardNumber(optVal));
        if (optNorm === vNorm) return true;
        // Match after stripping prefix
        const strippedOpt = _pmsStripPrefix(optVal);
        const strippedVal = _pmsStripPrefix(v);
        if (_pmsNormVietnamese(_pmsNormWardNumber(strippedOpt)) === _pmsNormVietnamese(_pmsNormWardNumber(strippedVal))) return true;
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
    const focusEl = document.getElementById(_pmsAddressFieldId(prefix, firstIssue.field));
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

/** Remove Vietnamese diacritics for comparison: "Hòa Bình" → "Hoa Binh" */
function _pmsNormVietnamese(s) {
    if (!s) return '';
    return String(s)
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '') // Remove diacritics
        .replace(/đ/g, 'd')
        .replace(/Đ/g, 'D')
        .toLowerCase()
        .trim();
}

/** Normalize ward number by removing leading zeros: "Phường 01" → "Phường 1" */
function _pmsNormWardNumber(s) {
    if (!s) return s;
    return s.replace(/^(phường|xã|thị trấn)\s*0+(\d+)/i, (match, prefix, num) => prefix + ' ' + parseInt(num, 10));
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

/** Tính ngày hết hạn CCCD theo tuổi (cùng ngày/tháng sinh): dob = 'dd/MM/yyyy' */
function _pmsCalcCCCDExpiry(dob) {
    const m = dob.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) return "Không xác định";
    const d = parseInt(m[1], 10), mo = parseInt(m[2], 10), y = parseInt(m[3], 10);
    const today = new Date();
    let age = today.getFullYear() - y;
    const tm = today.getMonth(), td = today.getDate();
    if (tm < mo - 1 || (tm === mo - 1 && td < d)) age--;

    function addYears(ny) {
        const t = new Date(y, mo - 1, d);
        t.setFullYear(t.getFullYear() + ny);
        const dd = String(t.getDate()).padStart(2, "0");
        const mm = String(t.getMonth() + 1).padStart(2, "0");
        const yy = t.getFullYear();
        return `${dd}/${mm}/${yy}`;
    }

    if (age < 25) return addYears(25);
    if (age < 40) return addYears(40);
    if (age < 60) return addYears(60);
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
window.pmsScanDateToISO = pmsScanDateToISO;
window.pmsMatchAddressToForm = pmsMatchAddressToForm;
window.pmsValidateAddressAfterScan = pmsValidateAddressAfterScan;
window.pmsShowAddressValidationIssues = pmsShowAddressValidationIssues;

// ─── Address Cache & Loading Exports ─────────────────────────────────────────
window.PMS_ADDR_CACHE = PMS_ADDR_CACHE;
window.PMS_LOADING_OVERLAY = PMS_LOADING_OVERLAY;


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

// ═══════════════════════════════════════════════════════════════════════════════
// ADDRESS LEARNING SYSTEM
// Tracks user selections and corrections to improve matching accuracy
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Global address learning state
 */
const PMS_ADDR_LEARNING = {
    // Track selections for learning
    selectionHistory: [],  // [{input, selected, timestamp}]
    correctionHistory: [], // [{input, wrong, correct, timestamp}]
    
    // Local storage key
    STORAGE_KEY: 'pms_addr_learning_v1',
    
    // Max entries to keep locally
    MAX_LOCAL_ENTRIES: 100,
};

/**
 * Load learning data from localStorage
 */
function pmsAddrLoadLearning() {
    try {
        const stored = localStorage.getItem(PMS_ADDR_LEARNING.STORAGE_KEY);
        if (stored) {
            const data = JSON.parse(stored);
            PMS_ADDR_LEARNING.selectionHistory = data.selectionHistory || [];
            PMS_ADDR_LEARNING.correctionHistory = data.correctionHistory || [];
        }
    } catch (e) {
        console.warn('[PMS] Could not load address learning data:', e);
    }
}

/**
 * Save learning data to localStorage
 */
function pmsAddrSaveLearning() {
    try {
        // Trim to max entries
        const selections = PMS_ADDR_LEARNING.selectionHistory.slice(-PMS_ADDR_LEARNING.MAX_LOCAL_ENTRIES);
        const corrections = PMS_ADDR_LEARNING.correctionHistory.slice(-PMS_ADDR_LEARNING.MAX_LOCAL_ENTRIES);
        
        localStorage.setItem(PMS_ADDR_LEARNING.STORAGE_KEY, JSON.stringify({
            selectionHistory: selections,
            correctionHistory: corrections,
            lastUpdated: new Date().toISOString(),
        }));
    } catch (e) {
        console.warn('[PMS] Could not save address learning data:', e);
    }
}

/**
 * Record when user selects a ward from suggestions
 * @param {string} inputWard - What user originally typed
 * @param {string} selectedWard - What user selected
 * @param {string} province - Province context
 */
function pmsAddrRecordSelection(inputWard, selectedWard, province) {
    if (!inputWard || !selectedWard) return;
    if (inputWard.toLowerCase() === selectedWard.toLowerCase()) return; // No change, no learning needed
    
    const entry = {
        input: inputWard.trim(),
        selected: selectedWard.trim(),
        province: province || '',
        timestamp: new Date().toISOString(),
    };
    
    PMS_ADDR_LEARNING.selectionHistory.push(entry);
    
    // Learn alias via API
    if (typeof vnLearnAlias === 'function') {
        vnLearnAlias(inputWard, selectedWard, province);
    }
    
    // Also send to server
    pmsAddrSyncLearning(entry, 'selection');
    
    // Save locally
    pmsAddrSaveLearning();
    
    console.log('[PMS] Learned address selection:', entry);
}

/**
 * Record when user corrects a wrong suggestion
 * @param {string} inputWard - What user originally typed
 * @param {string} wrongResult - What system suggested
 * @param {string} correctWard - What user actually selected
 * @param {string} province - Province context
 */
function pmsAddrRecordCorrection(inputWard, wrongResult, correctWard, province) {
    if (!inputWard || !correctWard) return;
    
    const entry = {
        input: inputWard.trim(),
        wrong: wrongResult?.trim() || '',
        correct: correctWard.trim(),
        province: province || '',
        timestamp: new Date().toISOString(),
    };
    
    PMS_ADDR_LEARNING.correctionHistory.push(entry);
    
    // Record correction via API
    if (typeof vnRecordCorrection === 'function') {
        vnRecordCorrection(inputWard, wrongResult || '', correctWard, province);
    }
    
    // Also send to server
    pmsAddrSyncLearning(entry, 'correction');
    
    // Save locally
    pmsAddrSaveLearning();
    
    console.log('[PMS] Recorded address correction:', entry);
}

/**
 * Sync learning data to server
 */
async function pmsAddrSyncLearning(entry, type) {
    try {
        const endpoint = type === 'selection' 
            ? '/api/vn-address/learn-alias'
            : '/api/vn-address/record-correction';
        
        await pmsApi(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                alias: entry.input,
                target_ward: entry.selected || entry.correct,
                target_province: entry.province,
                input_ward: entry.input,
                wrong_result: entry.wrong || '',
                correct_ward: entry.correct,
                correct_province: entry.province,
            })
        });
    } catch (e) {
        console.warn('[PMS] Could not sync learning data:', e);
    }
}

/**
 * Get learning statistics
 */
function pmsAddrGetStats() {
    return {
        selections: PMS_ADDR_LEARNING.selectionHistory.length,
        corrections: PMS_ADDR_LEARNING.correctionHistory.length,
        recentSelections: PMS_ADDR_LEARNING.selectionHistory.slice(-5).reverse(),
        recentCorrections: PMS_ADDR_LEARNING.correctionHistory.slice(-5).reverse(),
    };
}

/**
 * Clear learning data
 */
function pmsAddrClearLearning() {
    PMS_ADDR_LEARNING.selectionHistory = [];
    PMS_ADDR_LEARNING.correctionHistory = [];
    localStorage.removeItem(PMS_ADDR_LEARNING.STORAGE_KEY);
    console.log('[PMS] Address learning data cleared');
}

/**
 * Hook into form submission to record address selections
 * Call this when user confirms check-in or guest registration
 */
function pmsAddrHookFormSubmission(prefix = 'ci') {
    const wardInput = document.getElementById(`${prefix}-ward`);
    const newWardInput = document.getElementById(`${prefix}-new-ward`) || document.getElementById(`${prefix}-new-province`);
    const provInput = document.getElementById(`${prefix}-province`);
    
    if (!wardInput || !newWardInput) return;
    
    const originalWard = wardInput.value?.trim() || '';
    const selectedWard = newWardInput.value?.trim() || '';
    const province = provInput?.value?.trim() || '';
    
    if (originalWard && selectedWard && originalWard !== selectedWard) {
        // User selected different ward - learn from it
        setTimeout(() => {
            pmsAddrRecordSelection(originalWard, selectedWard, province);
        }, 500); // Delay to ensure form data is committed
    }
}

/**
 * Hook into ward selection for corrections
 * Call this when user manually changes ward after seeing suggestions
 */
function pmsAddrHookWardCorrection(inputWard, wrongSuggestion, correctWard, province) {
    if (!inputWard || !correctWard) return;
    if (wrongSuggestion && inputWard === correctWard) return; // No correction made
    
    pmsAddrRecordCorrection(inputWard, wrongSuggestion, correctWard, province);
}

// ─── Initialize ────────────────────────────────────────────────────────────────
pmsAddrLoadLearning();

// ─── Exports ─────────────────────────────────────────────────────────────────
window.pmsAddrRecordSelection = pmsAddrRecordSelection;
window.pmsAddrRecordCorrection = pmsAddrRecordCorrection;
window.pmsAddrGetStats = pmsAddrGetStats;
window.pmsAddrClearLearning = pmsAddrClearLearning;
window.pmsAddrHookFormSubmission = pmsAddrHookFormSubmission;
window.pmsAddrHookWardCorrection = pmsAddrHookWardCorrection;
