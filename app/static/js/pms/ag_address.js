// static/js/pms/ag_address.js
// AG Modal — Address Field Handlers
// ─────────────────────────────────────────────────────────────────────────────
// UNIFIED MODULE INTEGRATION:
// This module now uses PMS_ADDR (pms_addr.js) for:
// - Context-aware validation (trusts autofill/DB data)
// - State machine (RAW → SELECTED → MAPPED → NORMALIZED)
// - Unified datalist helpers
// - Progressive normalization
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const _agVnCache = {
    newProvinces: null,
    newWards: {},
    oldProvinces: null,
    oldDistricts: {},
    oldWards: {},
};

async function agVnFetch(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error('[vn_address AG]', url, e.message);
        return null;
    }
}

async function agLoadNewProvinces() {
    if (_agVnCache.newProvinces) return _agVnCache.newProvinces;
    const data = await agVnFetch('/api/vn-address/new-provinces');
    if (data?.provinces) { _agVnCache.newProvinces = data.provinces; return data.provinces; }
    return [];
}

async function agLoadNewWards(provinceShort) {
    if (!provinceShort) return [];
    if (_agVnCache.newWards[provinceShort]) return _agVnCache.newWards[provinceShort];
    const data = await agVnFetch(`/api/vn-address/new-wards/${encodeURIComponent(provinceShort)}`);
    if (data?.wards) { _agVnCache.newWards[provinceShort] = data.wards; return data.wards; }
    return [];
}

async function agLoadOldProvinces() {
    if (_agVnCache.oldProvinces) return _agVnCache.oldProvinces;
    const data = await agVnFetch('/api/vn-address/old-provinces');
    if (Array.isArray(data)) { _agVnCache.oldProvinces = data; return data; }
    return [];
}

async function agLoadOldDistricts(provinceCode) {
    if (!provinceCode) return [];
    if (_agVnCache.oldDistricts[provinceCode]) return _agVnCache.oldDistricts[provinceCode];
    const data = await agVnFetch(`/api/vn-address/old-districts/${provinceCode}`);
    if (data?.districts) { _agVnCache.oldDistricts[provinceCode] = data.districts; return data.districts; }
    return [];
}

async function agLoadOldWards(districtCode) {
    if (!districtCode) return [];
    if (_agVnCache.oldWards[districtCode]) return _agVnCache.oldWards[districtCode];
    const data = await agVnFetch(`/api/vn-address/old-wards/${districtCode}`);
    if (data?.wards) { _agVnCache.oldWards[districtCode] = data.wards; return data.wards; }
    return [];
}

function agVnStripPrefix(s) {
    if (!s) return '';
    const lower = s.toLowerCase();
    for (const p of ['tỉnh ', 'thành phố ', 'tp ', 'quận ', 'huyện ', 'thị xã ', 'thị trấn ', 'phường ', 'xã ']) {
        if (lower.startsWith(p)) return s.substring(p.length).trim();
    }
    return s.trim();
}

function agPopulateDatalist(datalistId, items) {
    const dl = document.getElementById(datalistId);
    if (!dl) return;
    
    const sortedItems = [...items].sort((a, b) => {
        const nameA = typeof a === 'string' ? a : a.name;
        const nameB = typeof b === 'string' ? b : b.name;
        return agVnStripPrefix(nameA).localeCompare(agVnStripPrefix(nameB), 'vi', { numeric: true });
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

function agGetOpt(datalistId, name) {
    const dl = document.getElementById(datalistId);
    if (!dl || !name) return null;
    for (const opt of dl.options) {
        if (opt.value.trim() === name.trim()) return opt;
    }
    return null;
}

function agFindOptWithPrefix(datalistId, name, extraPrefixes = []) {
    if (!name) return null;
    const dl = document.getElementById(datalistId);
    if (!dl) return null;

    // 1. Exact match
    const exact = agGetOpt(datalistId, name);
    if (exact) return exact;

    // 2. Try stripping prefixes first
    const stripped = agVnStripPrefix(name);
    if (stripped !== name) {
        const strippedOpt = agGetOpt(datalistId, stripped);
        if (strippedOpt) return strippedOpt;
    }

    // 3. Try adding prefixes
    const allPrefixes = [...extraPrefixes, 'Quận ', 'Huyện ', 'Thị xã ', 'Phường ', 'Xã '];
    for (const prefix of allPrefixes) {
        const withPrefix = prefix + stripped;
        const opt = agGetOpt(datalistId, withPrefix);
        if (opt) return opt;
    }

    return null;
}

function agSetConversion(province, ward, matched) {
    const provEl = document.getElementById('ag-new-province');
    const wardEl = document.getElementById('ag-new-ward');
    if (provEl) { provEl.value = province || ''; provEl.style.color = matched ? '#15803d' : '#b45309'; }
    if (wardEl) { wardEl.value = ward || ''; wardEl.style.color = matched ? '#15803d' : '#b45309'; }
}
function agClearConversion() { agSetConversion('', '', false); }

let _agConvTimeout = null;
let _agOldProv = { code: null, name: '' };
let _agOldDist = { code: null, name: '' };
let _agDistrictLoading = false;
let _agWardLoading = false;

function agGetMode() {
    return document.querySelector('input[name="ag-area"]:checked')?.value || 'new';
}

async function agOnNewProvinceChange(inputEl) {
    const name = inputEl.value.trim();
    const opt = agGetOpt('dl-ag-province', name);
    const short = opt?.dataset?.short || null;
    
    // Try strip prefix if exact match fails
    if (!short && name !== '') {
        const strippedName = agVnStripPrefix(name);
        const opt2 = agGetOpt('dl-ag-province', strippedName);
        if (opt2?.dataset?.short) {
            // Match found after stripping prefix - update input to standard value
            inputEl.value = opt2.value;
            const short2 = opt2.dataset.short;
            const wardInput = document.getElementById('ag-ward');
            if (wardInput) wardInput.value = '';
            agPopulateDatalist('dl-ag-ward', []);
            const wards = await agLoadNewWards(short2);
            agPopulateDatalist('dl-ag-ward', wards);
            return;
        }
        return; // still typing valid partial
    }
    
    const wardInput = document.getElementById('ag-ward');
    if (wardInput) wardInput.value = '';
    agPopulateDatalist('dl-ag-ward', []);
    if (!short) return;
    const wards = await agLoadNewWards(short);
    agPopulateDatalist('dl-ag-ward', wards);
}

async function agOnOldProvinceChange(inputEl) {
    const name = inputEl.value.trim();
    let opt = agFindOptWithPrefix('dl-ag-province', name, ['Tỉnh ', 'Thành phố ', 'TP. ']);
    let newCode = opt ? parseInt(opt.dataset.code) : null;

    if (opt) {
        // Update input to show full name from datalist
        inputEl.value = opt.value;
    }

    const newName = inputEl.value.trim();

    if (_agOldProv.code === newCode && _agOldProv.name === newName) return; // no change
    _agOldProv = { code: newCode, name: newName };

    if (!newCode && newName !== '') return; // still typing a partial string

    _agOldDist = { code: null, name: '' };
    ['ag-district', 'ag-ward'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    agPopulateDatalist('dl-ag-district', []);
    agPopulateDatalist('dl-ag-ward', []);
    agClearConversion();

    if (!newCode) {
        if (newName === '') {
            _agOldProv = { code: null, name: '' };
        }
        return;
    }
    _agDistrictLoading = true;
    const districts = await agLoadOldDistricts(newCode);
    _agDistrictLoading = false;
    agPopulateDatalist('dl-ag-district', districts);
}

async function agOnOldDistrictChange(inputEl) {
    const name = inputEl.value.trim();
    let opt = agFindOptWithPrefix('dl-ag-district', name, ['Quận ', 'Huyện ', 'Thị xã ']);
    let newCode = opt ? parseInt(opt.dataset.code) : null;

    if (opt) {
        // Update input to show full name from datalist
        inputEl.value = opt.value;
    }

    const newName = inputEl.value.trim();

    if (_agOldDist.code === newCode && _agOldDist.name === newName) return; // no change
    _agOldDist = { code: newCode, name: newName };

    if (!newCode && newName !== '') return; // still typing

    const wardInput = document.getElementById('ag-ward');
    if (wardInput) wardInput.value = '';
    agPopulateDatalist('dl-ag-ward', []);
    agClearConversion();

    if (!newCode) {
        if (newName === '') {
            _agOldDist = { code: null, name: '' };
        }
        return;
    }
    _agWardLoading = true;
    const wards = await agLoadOldWards(newCode);
    _agWardLoading = false;
    agPopulateDatalist('dl-ag-ward', wards);
}

async function agOnOldWardChange(inputEl) {
    const wardName = inputEl.value.trim();
    agClearConversion();
    if (!wardName) return;
    if (!agIsInDatalist('dl-ag-ward', wardName)) return;
    clearTimeout(_agConvTimeout);
    _agConvTimeout = setTimeout(async () => {
        try {
            const r = await fetch('/api/vn-address/convert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    old_ward_name: wardName,
                    old_province_name: _agOldProv.name,
                    old_district_name: _agOldDist.name,
                    old_province_code: _agOldProv.code,
                })
            });
            const result = await r.json();
            agSetConversion(result.new_province, result.new_ward, result.matched);
        } catch (e) { console.error('[vn_address AG] convert error:', e); agClearConversion(); }
    }, 300);
}

async function agOnProvinceChange(inputEl) {
    if (agGetMode() === 'new') await agOnNewProvinceChange(inputEl);
    else await agOnOldProvinceChange(inputEl);
}

async function agOnDistrictChange(inputEl) {
    if (agGetMode() === 'old') await agOnOldDistrictChange(inputEl);
}

async function agOnWardChange(inputEl) {
    if (agGetMode() === 'old') await agOnOldWardChange(inputEl);
}

async function agSwitchMode(mode, keepValues = true, guest = null) {
    if (!keepValues) {
        ['ag-province', 'ag-district', 'ag-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    }
    agPopulateDatalist('dl-ag-district', []);
    agPopulateDatalist('dl-ag-ward', []);
    agClearConversion();

    // ── FIX: Luôn set checked state cho radio trước khi gọi handlers ──
    const radioNew = document.querySelector('input[name="ag-area"][value="new"]');
    const radioOld = document.querySelector('input[name="ag-area"][value="old"]');
    if (mode === 'new') {
        if (radioNew) radioNew.checked = true;
    } else {
        if (radioOld) radioOld.checked = true;
    }

    const distGrp = document.getElementById('ag-grp-district');
    const convGrp = document.getElementById('ag-conversion-grp');
    if (mode === 'new') {
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
        const provinces = await agLoadNewProvinces();
        agPopulateDatalist('dl-ag-province', provinces.map(p => ({ name: p.name, short: p.short })));
        if (guest) {
            const pEl = document.getElementById('ag-province');
            const wEl = document.getElementById('ag-ward');
            const nProvEl = document.getElementById('ag-new-province');
            const nWardEl = document.getElementById('ag-new-ward');
            // Set province FIRST, then load wards via province change
            if (pEl) pEl.value = guest.city || '';
            if (typeof agOnNewProvinceChange === 'function' && pEl) await agOnNewProvinceChange(pEl);
            // NOW set ward value (after wards are loaded)
            if (wEl) wEl.value = guest.ward || '';
            if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
            if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }
            // Match ward value to datalist option
            if (wEl && wEl.value) {
                const dl = document.getElementById('dl-ag-ward');
                if (dl) {
                    for (const opt of dl.options) {
                        if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                            wEl.value = opt.value;
                            break;
                        }
                    }
                }
                wEl.dispatchEvent(new Event('blur'));
            }
            if (pEl) pEl.dispatchEvent(new Event('blur'));
        }
    } else {
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = 'none';
        const provinces = await agLoadOldProvinces();
        agPopulateDatalist('dl-ag-province', provinces);
        if (guest) {
            const pEl = document.getElementById('ag-province');
            const dEl = document.getElementById('ag-district');
            const wEl = document.getElementById('ag-ward');
            const nProvEl = document.getElementById('ag-new-province');
            const nWardEl = document.getElementById('ag-new-ward');
            if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
            if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }
            // Set province FIRST, then load districts/wards via province/district change
            if (pEl) pEl.value = guest.old_city || '';
            if (typeof agOnOldProvinceChange === 'function' && pEl) await agOnOldProvinceChange(pEl);
            // NOW set district value (after districts are loaded)
            if (dEl) dEl.value = guest.old_district || '';
            if (typeof agOnOldDistrictChange === 'function' && dEl) await agOnOldDistrictChange(dEl);
            // NOW set ward value (after wards are loaded)
            if (wEl) wEl.value = guest.old_ward || '';
            // Match ward value to datalist option
            if (wEl && wEl.value) {
                const dl = document.getElementById('dl-ag-ward');
                if (dl) {
                    for (const opt of dl.options) {
                        if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                            wEl.value = opt.value;
                            break;
                        }
                    }
                }
                wEl.dispatchEvent(new Event('blur'));
            }
            if (dEl) dEl.dispatchEvent(new Event('blur'));
            if (pEl) pEl.dispatchEvent(new Event('blur'));
        }
    }
}

async function agInitAddressFields() {
    const mode = agGetMode();
    if (mode === 'new') {
        const provinces = await agLoadNewProvinces();
        agPopulateDatalist('dl-ag-province', provinces.map(p => ({ name: p.name, short: p.short })));
    } else {
        const provinces = await agLoadOldProvinces();
        agPopulateDatalist('dl-ag-province', provinces);
    }
}
window.agInitAddressFields = agInitAddressFields;

function agIsInDatalist(datalistId, value) {
    if (!value) return false;
    const dl = document.getElementById(datalistId);
    if (!dl) return false;
    const v = value.trim().toLowerCase();
    for (const opt of dl.options) {
        if (opt.value.trim().toLowerCase() === v) return true;
    }
    return false;
}

function agValidateDatalist(inputEl) {
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

    // Wait for async load to finish
    if (inputEl.id === 'ag-district' && _agDistrictLoading) return true;
    if (inputEl.id === 'ag-ward' && _agWardLoading) return true;

    // Empty = ok
    if (!val) {
        inputEl.style.borderColor = '';
        return true;
    }

    // Match found = ok
    if (agIsInDatalist(dlId, val)) {
        inputEl.style.borderColor = '';
        return true;
    }

    // Progressive normalization: suggest but accept
    inputEl.style.borderColor = '#eab308'; // Amber instead of red
    inputEl.title = `"${val}" không khớp — vẫn lưu được, gợi ý chọn từ danh sách`;
    return true; // ✅ Always accept, never block
}
window.agValidateDatalist = agValidateDatalist;

function agValidateAddressFields() {
    // Delegate to unified PMS_ADDR module
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.validateAddressFields) {
        return PMS_ADDR.validateAddressFields('ag');
    }

    // Fallback: progressive validation
    if (_agDistrictLoading || _agWardLoading) {
        return { valid: true, errors: [], warnings: ['Vui lòng chờ dữ liệu được tải...'] };
    }

    const errors = [];
    const warnings = [];
    const provEl = document.getElementById('ag-province');
    const provVal = provEl?.value?.trim();

    if (!provVal) {
        errors.push('Tỉnh/Thành phố là bắt buộc');
    }

    return { valid: errors.length === 0, errors, warnings };
}
window.agValidateAddressFields = agValidateAddressFields;

// ── Global exports ──
window.agOnProvinceChange = agOnProvinceChange;
window.agOnDistrictChange = agOnDistrictChange;
window.agOnWardChange = agOnWardChange;
window.agSwitchMode = agSwitchMode;
window.agLoadNewProvinces = agLoadNewProvinces;
window.agLoadOldProvinces = agLoadOldProvinces;
window.agPopulateDatalist = agPopulateDatalist;
