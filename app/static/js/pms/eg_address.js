// static/js/pms/eg_address.js
// EG Modal — Address Field Handlers
// ─────────────────────────────────────────────────────────────────────────────
// UNIFIED MODULE INTEGRATION:
// This module now uses PMS_ADDR (pms_addr.js) for:
// - Context-aware validation (trusts autofill/DB data)
// - State machine (RAW → SELECTED → MAPPED → NORMALIZED)
// - Unified datalist helpers
// - Progressive normalization
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const _egVnCacheAddr = {
    newProvinces: null,
    newWards: {},
    oldProvinces: null,
    oldDistricts: {},
    oldWards: {},
};

window._egOldProv = { code: null, name: '' };
window._egOldDist = { code: null, name: '' };

let _egDistrictLoading = false;
let _egWardLoading = false;

function egSetDistrictLoading(isLoading) {
    _egDistrictLoading = isLoading;
    const distEl = document.getElementById('eg-district');
    if (distEl) {
        if (isLoading) {
            distEl.style.opacity = '0.6';
            distEl.style.cursor = 'wait';
            distEl.placeholder = 'Đang tải danh sách...';
        } else {
            distEl.style.opacity = '';
            distEl.style.cursor = '';
            distEl.placeholder = 'Chọn Quận/Huyện';
        }
    }
}

function egSetWardLoading(isLoading) {
    _egWardLoading = isLoading;
    const wardEl = document.getElementById('eg-ward');
    if (wardEl) {
        if (isLoading) {
            wardEl.style.opacity = '0.6';
            wardEl.style.cursor = 'wait';
            wardEl.placeholder = 'Đang tải danh sách...';
        } else {
            wardEl.style.opacity = '';
            wardEl.style.cursor = '';
            wardEl.placeholder = 'Chọn Phường/Xã';
        }
    }
}

async function egVnFetch(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error('[vn_address EG]', url, e.message);
        return null;
    }
}

async function egLoadNewProvinces() {
    if (_egVnCacheAddr.newProvinces) return _egVnCacheAddr.newProvinces;
    const data = await egVnFetch('/api/vn-address/new-provinces');
    if (data?.provinces) { _egVnCacheAddr.newProvinces = data.provinces; return data.provinces; }
    return [];
}

async function egLoadNewWards(provinceShort) {
    if (!provinceShort) return [];
    if (_egVnCacheAddr.newWards[provinceShort]) return _egVnCacheAddr.newWards[provinceShort];
    const data = await egVnFetch(`/api/vn-address/new-wards/${encodeURIComponent(provinceShort)}`);
    if (data?.wards) { _egVnCacheAddr.newWards[provinceShort] = data.wards; return data.wards; }
    return [];
}

async function egLoadOldProvinces() {
    if (_egVnCacheAddr.oldProvinces) return _egVnCacheAddr.oldProvinces;
    const data = await egVnFetch('/api/vn-address/old-provinces');
    if (Array.isArray(data)) { _egVnCacheAddr.oldProvinces = data; return data; }
    return [];
}

async function egLoadOldDistricts(provinceCode) {
    if (!provinceCode) return [];
    if (_egVnCacheAddr.oldDistricts[provinceCode]) return _egVnCacheAddr.oldDistricts[provinceCode];
    const data = await egVnFetch(`/api/vn-address/old-districts/${provinceCode}`);
    if (data?.districts) { _egVnCacheAddr.oldDistricts[provinceCode] = data.districts; return data.districts; }
    return [];
}

async function egLoadOldWards(districtCode) {
    if (!districtCode) return [];
    if (_egVnCacheAddr.oldWards[districtCode]) return _egVnCacheAddr.oldWards[districtCode];
    const data = await egVnFetch(`/api/vn-address/old-wards/${districtCode}`);
    if (data?.wards) { _egVnCacheAddr.oldWards[districtCode] = data.wards; return data.wards; }
    return [];
}

function egVnStripPrefix(s) {
    if (!s) return '';
    const lower = s.toLowerCase();
    for (const p of ['tỉnh ', 'thành phố ', 'tp ', 'quận ', 'huyện ', 'thị xã ', 'thị trấn ', 'phường ', 'xã ']) {
        if (lower.startsWith(p)) return s.substring(p.length).trim();
    }
    return s.trim();
}

function egPopulateDatalist(datalistId, items) {
    const dl = document.getElementById(datalistId);
    if (!dl) return;
    
    const sortedItems = [...items].sort((a, b) => {
        const nameA = typeof a === 'string' ? a : a.name;
        const nameB = typeof b === 'string' ? b : b.name;
        return egVnStripPrefix(nameA).localeCompare(egVnStripPrefix(nameB), 'vi', { numeric: true });
    });
    
    let html = '';
    sortedItems.forEach(item => {
        const val = typeof item === 'string' ? item : item.name;
        const safeVal = val.replace(/"/g, '&quot;');
        const codeAttr = item.code ? ` data-code="${item.code}"` : '';
        const shortAttr = item.short ? ` data-short="${item.short}"` : '';
        html += `<option value="${safeVal}"${codeAttr}${shortAttr}></option>`;
    });
    dl.innerHTML = html;
}

function egGetOpt(datalistId, name) {
    const dl = document.getElementById(datalistId);
    if (!dl || !name) return null;
    for (const opt of dl.options) {
        if (opt.value.trim() === name.trim()) return opt;
    }
    return null;
}

function egFindOptWithPrefix(datalistId, name, extraPrefixes = []) {
    if (!name) return null;
    const dl = document.getElementById(datalistId);
    if (!dl) return null;

    // 1. Exact match
    const exact = egGetOpt(datalistId, name);
    if (exact) return exact;

    // 2. Try stripping prefixes first
    const stripped = egVnStripPrefix(name);
    if (stripped !== name) {
        const strippedOpt = egGetOpt(datalistId, stripped);
        if (strippedOpt) return strippedOpt;
    }

    // 3. Try adding prefixes
    const allPrefixes = [...extraPrefixes, 'Quận ', 'Huyện ', 'Thị xã ', 'Phường ', 'Xã '];
    for (const prefix of allPrefixes) {
        const withPrefix = prefix + stripped;
        const opt = egGetOpt(datalistId, withPrefix);
        if (opt) return opt;
    }

    return null;
}

function egSetConversion(province, ward, matched) {
    const provEl = document.getElementById('eg-new-province');
    const wardEl = document.getElementById('eg-new-ward');
    if (provEl) { provEl.value = province || ''; provEl.style.color = matched ? '#15803d' : '#b45309'; }
    if (wardEl) { wardEl.value = ward || ''; wardEl.style.color = matched ? '#15803d' : '#b45309'; }
}
function egClearConversion() { egSetConversion('', '', false); }

let _egConvTimeout = null;
// _egOldProv and _egOldDist are now global window properties

function egGetMode() {
    return document.querySelector('input[name="eg-area"]:checked')?.value || 'new';
}

async function egOnNewProvinceChange(inputEl) {
    const name = inputEl.value.trim();
    const opt = egGetOpt('dl-eg-province', name);
    const short = opt?.dataset?.short || null;
    
    // Try strip prefix if exact match fails
    if (!short && name !== '') {
        const strippedName = egVnStripPrefix(name);
        const opt2 = egGetOpt('dl-eg-province', strippedName);
        if (opt2?.dataset?.short) {
            // Match found after stripping prefix - update input to standard value
            inputEl.value = opt2.value;
            const short2 = opt2.dataset.short;
            const wardInput = document.getElementById('eg-ward');
            if (wardInput) wardInput.value = '';
            egPopulateDatalist('dl-eg-ward', []);
            const wards = await egLoadNewWards(short2);
            egPopulateDatalist('dl-eg-ward', wards);
            return;
        }
        return; // still typing valid partial
    }
    
    const wardInput = document.getElementById('eg-ward');
    if (wardInput) wardInput.value = '';
    egPopulateDatalist('dl-eg-ward', []);
    if (!short) return;
    const wards = await egLoadNewWards(short);
    egPopulateDatalist('dl-eg-ward', wards);
}

async function egOnOldProvinceChange(inputEl) {
    const name = inputEl.value.trim();
    let opt = egFindOptWithPrefix('dl-eg-province', name, ['Tỉnh ', 'Thành phố ', 'TP. ']);
    let newCode = opt ? parseInt(opt.dataset.code) : null;

    if (opt) {
        inputEl.value = opt.value;
    }

    const newName = inputEl.value.trim();

    if (_egOldProv.code === newCode && _egOldProv.name === newName) return; // no change
    _egOldProv = { code: newCode, name: newName };

    if (!newCode && newName !== '') return; // still typing a partial string

    _egOldDist = { code: null, name: '' };
    ['eg-district', 'eg-ward'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    egPopulateDatalist('dl-eg-district', []);
    egPopulateDatalist('dl-eg-ward', []);
    egClearConversion();

    if (!newCode) {
        if (newName === '') { _egOldProv = { code: null, name: '' }; }
        return;
    }

    egSetDistrictLoading(true);
    const districts = await egLoadOldDistricts(newCode);
    egSetDistrictLoading(false);
    egPopulateDatalist('dl-eg-district', districts);

    const distEl = document.getElementById('eg-district');
    if (distEl && districts.length > 0) { distEl.focus(); }
}

async function egOnOldDistrictChange(inputEl) {
    const name = inputEl.value.trim();
    let opt = egFindOptWithPrefix('dl-eg-district', name, ['Quận ', 'Huyện ', 'Thị xã ']);
    let newCode = opt ? parseInt(opt.dataset.code) : null;

    if (opt) {
        inputEl.value = opt.value;
    }

    const newName = inputEl.value.trim();

    if (_egOldDist.code === newCode && _egOldDist.name === newName) return; // no change
    _egOldDist = { code: newCode, name: newName };

    if (!newCode && newName !== '') return; // still typing

    const wardInput = document.getElementById('eg-ward');
    if (wardInput) wardInput.value = '';
    egPopulateDatalist('dl-eg-ward', []);
    egClearConversion();

    if (!newCode) {
        if (newName === '') { _egOldDist = { code: null, name: '' }; }
        return;
    }

    egSetWardLoading(true);
    const wards = await egLoadOldWards(newCode);
    egSetWardLoading(false);
    egPopulateDatalist('dl-eg-ward', wards);

    const wEl = document.getElementById('eg-ward');
    if (wEl && wards.length > 0) { wEl.focus(); }
}

async function egOnOldWardChange(inputEl) {
    const wardName = inputEl.value.trim();

    // Flexible match: try exact, strip prefix, add prefix
    let opt = egFindOptWithPrefix('dl-eg-ward', wardName, ['Phường ', 'Xã ', 'Thị trấn ']);
    if (opt) {
        inputEl.value = opt.value;
    }

    egClearConversion();
    if (!inputEl.value) return;
    if (!egIsInDatalist('dl-eg-ward', inputEl.value)) return;

    clearTimeout(_egConvTimeout);
    _egConvTimeout = setTimeout(async () => {
        try {
            const r = await fetch('/api/vn-address/convert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    old_ward_name: inputEl.value,
                    old_province_name: _egOldProv.name,
                    old_district_name: _egOldDist.name,
                    old_province_code: _egOldProv.code,
                })
            });
            const result = await r.json();
            egSetConversion(result.new_province, result.new_ward, result.matched);
        } catch (e) { console.error('[vn_address EG] convert error:', e); egClearConversion(); }
    }, 300);
}

async function egOnProvinceChange(inputEl) {
    if (egGetMode() === 'new') await egOnNewProvinceChange(inputEl);
    else await egOnOldProvinceChange(inputEl);
}

async function egOnDistrictChange(inputEl) {
    if (egGetMode() === 'old') await egOnOldDistrictChange(inputEl);
}

async function egOnWardChange(inputEl) {
    if (egGetMode() === 'old') await egOnOldWardChange(inputEl);
}

async function egSwitchMode(mode, keepValues = true) {
    if (!keepValues) {
        ['eg-province', 'eg-district', 'eg-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    }
    egPopulateDatalist('dl-eg-district', []);
    egPopulateDatalist('dl-eg-ward', []);
    egClearConversion();

    // ── FIX: Luôn set checked state cho radio trước khi gọi handlers ──
    const radioNew = document.querySelector('input[name="eg-area"][value="new"]');
    const radioOld = document.querySelector('input[name="eg-area"][value="old"]');
    if (mode === 'new') {
        if (radioNew) radioNew.checked = true;
    } else {
        if (radioOld) radioOld.checked = true;
    }

    const distGrp = document.getElementById('eg-grp-district');
    const convGrp = document.getElementById('eg-conversion-grp');
    if (mode === 'new') {
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
        const provinces = await egLoadNewProvinces();
        egPopulateDatalist('dl-eg-province', provinces.map(p => ({ name: p.name, short: p.short })));
    } else {
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';
        const provinces = await egLoadOldProvinces();
        egPopulateDatalist('dl-eg-province', provinces);
    }
}

async function egInitAddressFields() {
    const mode = egGetMode();
    if (mode === 'new') {
        const provinces = await egLoadNewProvinces();
        egPopulateDatalist('dl-eg-province', provinces.map(p => ({ name: p.name, short: p.short })));
    } else {
        const provinces = await egLoadOldProvinces();
        egPopulateDatalist('dl-eg-province', provinces);
    }
}

function egIsInDatalist(datalistId, value) {
    if (!value) return false;
    const dl = document.getElementById(datalistId);
    if (!dl) return false;
    const v = value.trim().toLowerCase();
    for (const opt of dl.options) {
        if (opt.value.trim().toLowerCase() === v) return true;
    }
    return false;
}

function egValidateDatalist(inputEl) {
    // Delegate to unified PMS_ADDR module for context-aware validation
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.validateDatalist) {
        return PMS_ADDR.validateDatalist(inputEl);
    }

    // Fallback: progressive validation (never block)
    const dlId = inputEl.dataset.dl;
    if (!dlId) return true;
    const dl = document.getElementById(dlId);
    if (!dl) return true;

    const val = inputEl.value.trim();

    // Wait for async load
    if (inputEl.id === 'eg-district' && _egDistrictLoading) return true;
    if (inputEl.id === 'eg-ward' && _egWardLoading) return true;

    // Empty = ok
    if (!val) {
        inputEl.style.borderColor = '';
        return true;
    }

    // Match found = ok
    if (egIsInDatalist(dlId, val)) {
        inputEl.style.borderColor = '';
        return true;
    }

    // Progressive normalization: suggest but accept
    inputEl.style.borderColor = '#eab308'; // Amber instead of red
    inputEl.title = `"${val}" không khớp — vẫn lưu được, gợi ý chọn từ danh sách`;
    return true; // ✅ Always accept, never block
}

function egValidateAddressFields() {
    // Delegate to unified PMS_ADDR module
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.validateAddressFields) {
        return PMS_ADDR.validateAddressFields('eg');
    }

    // Fallback: progressive validation
    if (_egDistrictLoading || _egWardLoading) {
        return { valid: true, errors: [], warnings: ['Vui lòng chờ dữ liệu được tải...'] };
    }

    const errors = [];
    const warnings = [];
    const provEl = document.getElementById('eg-province');
    const provVal = provEl?.value?.trim();

    if (!provVal) {
        errors.push('Tỉnh/Thành phố là bắt buộc');
    }

    return { valid: errors.length === 0, errors, warnings };
}

// ── Global exports ──
window.egGetMode = egGetMode;
window.egGetOpt = egGetOpt;
window.egLoadOldDistricts = egLoadOldDistricts;
window.egLoadOldWards = egLoadOldWards;
window.egLoadNewWards = egLoadNewWards;
window.egClearConversion = egClearConversion;
window.egIsInDatalist = egIsInDatalist;
window.egOnProvinceChange = egOnProvinceChange;
window.egOnDistrictChange = egOnDistrictChange;
window.egOnWardChange = egOnWardChange;
window.egOnOldProvinceChange = egOnOldProvinceChange;
window.egOnOldDistrictChange = egOnOldDistrictChange;
window.egSwitchMode = egSwitchMode;
window.egLoadNewProvinces = egLoadNewProvinces;
window.egLoadOldProvinces = egLoadOldProvinces;
window.egPopulateDatalist = egPopulateDatalist;
window.egInitAddressFields = egInitAddressFields;
window.egValidateDatalist = egValidateDatalist;
window.egValidateAddressFields = egValidateAddressFields;
