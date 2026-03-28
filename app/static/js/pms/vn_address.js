// static/js/pms/vn_address.js
// Vietnamese address v4 — Powered by authoritative 2025 reform Excel data
// NEW mode  → /api/vn-address/new-provinces + /new-wards/{prov}  (curated, correct)
// OLD mode  → /api/vn-address/old-* (proxied from public API, 63 provinces)
// CONVERT   → /api/vn-address/convert (7,397-entry ward mapping from Excel)
// ─────────────────────────────────────────────────────────────────────────────
// UNIFIED MODULE INTEGRATION:
// This module now uses PMS_ADDR (pms_addr.js) for:
// - Context-aware validation (trusts autofill/DB data)
// - State machine (RAW → SELECTED → MAPPED → NORMALIZED)
// - Unified datalist helpers
// - Progressive normalization
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const VN_API = '/api/vn-address';

// ─── Client-side caches ───────────────────────────────────────────────────────
const _vnCache = {
  newProvinces: null,        // [{short, name}, ...]
  newWards: {},              // province_short → [ward_name, ...]
  oldProvinces: null,        // [{name, code}, ...]
  oldDistricts: {},          // provinceCode → [{name, code}]
  oldWards: {},              // districtCode → [{name, code}]
};

// ─── Internal API fetch ───────────────────────────────────────────────────────

async function vnFetch(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error('[vn_address]', url, e.message);
    return null;
  }
}

// ─── NEW MODE data loaders ─────────────────────────────────────────────────
// Results come from curated Excel data — always reflects post-1/7/2025 reality

async function vnLoadNewProvinces() {
  if (_vnCache.newProvinces) return _vnCache.newProvinces;
  const data = await vnFetch(`${VN_API}/new-provinces`);
  if (data?.provinces) {
    _vnCache.newProvinces = data.provinces;   // [{short, name}, ...]
    return _vnCache.newProvinces;
  }
  return [];
}

async function vnLoadNewWards(provinceShort) {
  if (!provinceShort) return [];
  if (_vnCache.newWards[provinceShort]) return _vnCache.newWards[provinceShort];
  const encoded = encodeURIComponent(provinceShort);
  const data = await vnFetch(`${VN_API}/new-wards/${encoded}`);
  if (data?.wards) {
    _vnCache.newWards[provinceShort] = data.wards;
    return data.wards;
  }
  return [];
}

// ─── OLD MODE data loaders ────────────────────────────────────────────────────
// Results come from public API (proxied server-side — no SSL issues)

async function vnLoadOldProvinces() {
  if (_vnCache.oldProvinces) return _vnCache.oldProvinces;
  const data = await vnFetch(`${VN_API}/old-provinces`);
  if (Array.isArray(data)) {
    _vnCache.oldProvinces = data;
    return data;
  }
  return [];
}

async function vnLoadOldDistricts(provinceCode) {
  if (!provinceCode) return [];
  if (_vnCache.oldDistricts[provinceCode]) return _vnCache.oldDistricts[provinceCode];
  const data = await vnFetch(`${VN_API}/old-districts/${provinceCode}`);
  if (data?.districts) {
    _vnCache.oldDistricts[provinceCode] = data.districts;
    return data.districts;
  }
  return [];
}

async function vnLoadOldWards(districtCode) {
  if (!districtCode) return [];
  if (_vnCache.oldWards[districtCode]) return _vnCache.oldWards[districtCode];
  const data = await vnFetch(`${VN_API}/old-wards/${districtCode}`);
  if (data?.wards) {
    _vnCache.oldWards[districtCode] = data.wards;
    return data.wards;
  }
  return [];
}

// ─── Datalist helpers ──────────────────────────────────────────────────────────

function vnStripPrefix(s) {
  if (!s) return '';
  const lower = s.toLowerCase();
  for (const p of ['tỉnh ', 'thành phố ', 'tp ', 'quận ', 'huyện ', 'thị xã ', 'thị trấn ', 'phường ', 'xã ']) {
    if (lower.startsWith(p)) return s.substring(p.length).trim();
  }
  return s.trim();
}

function vnPopulateDatalist(datalistId, items) {
  const dl = document.getElementById(datalistId);
  if (!dl) return;
  dl.innerHTML = '';

  const sortedItems = [...items].sort((a, b) => {
    const nameA = typeof a === 'string' ? a : a.name;
    const nameB = typeof b === 'string' ? b : b.name;
    return vnStripPrefix(nameA).localeCompare(vnStripPrefix(nameB), 'vi', { numeric: true });
  });

  sortedItems.forEach(item => {
    const opt = document.createElement('option');
    opt.value = typeof item === 'string' ? item : item.name;
    if (item.code) opt.dataset.code = item.code;
    if (item.short) opt.dataset.short = item.short;
    dl.appendChild(opt);
  });
}

function vnGetOpt(datalistId, name) {
  const dl = document.getElementById(datalistId);
  if (!dl || !name) return null;
  for (const opt of dl.options) {
    if (opt.value.trim() === name.trim()) return opt;
  }
  return null;
}

// ─── Conversion display ────────────────────────────────────────────────────────

let _convTimeout = null;

function vnSetConversion(province, ward, matched) {
  const provEl = document.getElementById('ci-new-province');
  const wardEl = document.getElementById('ci-new-ward');
  if (provEl) {
    provEl.value = province || '';
    provEl.style.color = matched ? '#15803d' : '#b45309';
  }
  if (wardEl) {
    wardEl.value = ward || '';
    wardEl.style.color = matched ? '#15803d' : '#b45309';
    wardEl.title = matched ? 'Ánh xạ chính xác từ dữ liệu Excel chính thức' : 'Không tìm thấy ánh xạ — tên giữ nguyên';
  }
}

function vnClearConversion() { vnSetConversion('', '', false); }

// ─── Mode detection ────────────────────────────────────────────────────────────

function vnGetMode() {
  return document.querySelector('input[name="ci-area"]:checked')?.value || 'new';
}

// ─── NEW MODE handlers ─────────────────────────────────────────────────────────

async function vnOnNewProvinceChange(inputEl) {
  const name = inputEl.value.trim();
  const wardInput = document.getElementById('ci-ward');
  if (wardInput) wardInput.value = '';
  vnPopulateDatalist('dl-ward', []);

  if (!name) return;

  // Find province short code from datalist
  const opt = vnGetOpt('dl-province', name);
  let short = opt?.dataset?.short || null;

  // Try strip prefix if exact match fails
  if (!short) {
    const strippedName = vnStripPrefix(name);
    const opt2 = vnGetOpt('dl-province', strippedName);
    if (opt2?.dataset?.short) {
      inputEl.value = opt2.value;
      short = opt2.dataset.short;
    }
  }

  // Try adding common prefixes if still no match (input has no prefix, datalist has prefix)
  if (!short) {
    const prefixes = ['Thành phố ', 'Tỉnh ', 'TP '];
    for (const prefix of prefixes) {
      const opt3 = vnGetOpt('dl-province', prefix + name);
      if (opt3?.dataset?.short) {
        inputEl.value = opt3.value;
        short = opt3.dataset.short;
        break;
      }
    }
  }

  if (!short) return; // still typing valid partial
  const wards = await vnLoadNewWards(short);
  vnPopulateDatalist('dl-ward', wards);  // wards is string[]
}

// ─── OLD MODE handlers ─────────────────────────────────────────────────────────

let _oldProv = { code: null, name: '' };
let _oldDist = { name: '' };
let _vnDistrictLoading = false;
let _vnWardLoading = false;

async function vnOnOldProvinceChange(inputEl) {
  const opt = vnGetOpt('dl-province', inputEl.value);
  _oldProv = { code: opt ? parseInt(opt.dataset.code) : null, name: inputEl.value.trim() };
  _oldDist = { name: '' };

  ['ci-district', 'ci-ward'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  vnPopulateDatalist('dl-district', []);
  vnPopulateDatalist('dl-ward', []);
  vnClearConversion();

  if (!_oldProv.code) return;
  _vnDistrictLoading = true;
  const districts = await vnLoadOldDistricts(_oldProv.code);
  _vnDistrictLoading = false;
  vnPopulateDatalist('dl-district', districts);
}

async function vnOnOldDistrictChange(inputEl) {
  const opt = vnGetOpt('dl-district', inputEl.value);
  _oldDist = { name: inputEl.value.trim(), code: opt ? parseInt(opt.dataset.code) : null };

  const wardInput = document.getElementById('ci-ward');
  if (wardInput) wardInput.value = '';
  vnPopulateDatalist('dl-ward', []);
  vnClearConversion();

  if (!_oldDist.code) return;
  _vnWardLoading = true;
  const wards = await vnLoadOldWards(_oldDist.code);
  _vnWardLoading = false;
  vnPopulateDatalist('dl-ward', wards);
}

async function vnOnOldWardChange(inputEl) {
  const wardName = inputEl.value.trim();
  // Always clear first
  vnClearConversion();
  if (!wardName) return;

  // ✋ Guard: only trigger conversion if value is actually in the datalist
  // (prevents free-text from calling /convert and showing wrong result)
  if (!vnIsInDatalist('dl-ward', wardName)) return;

  // Debounce — wait for user to finish typing / selecting
  clearTimeout(_convTimeout);
  _convTimeout = setTimeout(async () => {
    try {
      const r = await fetch(`${VN_API}/convert`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_ward_name: wardName,
          old_province_name: _oldProv.name,
          old_district_name: _oldDist.name,
          old_province_code: _oldProv.code,
        })
      });
      const result = await r.json();
      vnSetConversion(result.new_province, result.new_ward, result.matched);
    } catch (e) {
      console.error('[vn_address] convert error:', e);
      vnClearConversion();
    }
  }, 300);
}

// ─── Unified event handlers ────────────────────────────────────────────────────

async function vnOnProvinceChange(inputEl) {
  if (vnGetMode() === 'new') await vnOnNewProvinceChange(inputEl);
  else await vnOnOldProvinceChange(inputEl);
}

async function vnOnDistrictChange(inputEl) {
  if (vnGetMode() === 'old') await vnOnOldDistrictChange(inputEl);
}

async function vnOnWardChange(inputEl) {
  if (vnGetMode() === 'old') await vnOnOldWardChange(inputEl);
}

// ─── Mode switch ───────────────────────────────────────────────────────────────

async function vnSwitchMode(mode, keepValues = true) {
  if (!keepValues) {
    ['ci-province', 'ci-district', 'ci-ward'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
  }
  vnPopulateDatalist('dl-district', []);
  vnPopulateDatalist('dl-ward', []);
  vnClearConversion();

  // ── FIX: Luôn set checked state cho radio trước khi gọi handlers ──
  const radioNew = document.querySelector('input[name="ci-area"][value="new"]');
  const radioOld = document.querySelector('input[name="ci-area"][value="old"]');
  if (mode === 'new') {
    if (radioNew) radioNew.checked = true;
  } else {
    if (radioOld) radioOld.checked = true;
  }

  const distGrp = document.getElementById('ci-grp-district');
  const convGrp = document.getElementById('ci-conversion-grp');
  const lblProv  = document.getElementById('ci-lbl-province');
  const lblWard  = document.getElementById('ci-lbl-ward');

  if (mode === 'new') {
    if (distGrp) distGrp.style.display = 'none';
    if (convGrp) convGrp.style.display = 'none';
    if (lblProv) lblProv.innerHTML = 'Tỉnh/Thành phố <span class="f-req">*</span>';
    if (lblWard) lblWard.innerHTML = 'Phường/Xã <span class="f-req">*</span>';
    const provinces = await vnLoadNewProvinces();
    vnPopulateDatalist('dl-province', provinces.map(p => ({ name: p.name, short: p.short })));
  } else {
    if (distGrp) distGrp.style.display = '';
    if (convGrp) convGrp.style.display = '';
    if (lblProv) lblProv.innerHTML = 'Tỉnh/Thành phố <span class="f-req">*</span>';
    if (lblWard) lblWard.innerHTML = 'Phường/Xã <span class="f-req">*</span>';
    const provinces = await vnLoadOldProvinces();
    vnPopulateDatalist('dl-province', provinces);
  }

  // ── FIX: Luôn cascade province → wards/districts khi province có giá trị sẵn ──
  // (keepValues=true dùng cho autofill/scan, province đã được fill trước khi gọi switch)
  const pEl = document.getElementById('ci-province');
  if (pEl && pEl.value) {
    vnOnProvinceChange(pEl);
  }
}

// ─── Init ──────────────────────────────────────────────────────────────────────

async function vnInitAddressFields() {
  const mode = vnGetMode();
  if (mode === 'new') {
    const provinces = await vnLoadNewProvinces();
    vnPopulateDatalist('dl-province', provinces.map(p => ({ name: p.name, short: p.short })));
  } else {
    const provinces = await vnLoadOldProvinces();
    vnPopulateDatalist('dl-province', provinces);
  }
}

// ─── Context-Aware Datalist Validation ──────────────────────────────────────────
// Uses PMS_ADDR state machine for progressive normalization
// TRUSTED data (autofill/DB) → auto-accept
// RAW data → suggest but accept
// USER INPUT → validate but still accept (never block)

function vnIsInDatalist(datalistId, value) {
  if (!value) return false;
  const dl = document.getElementById(datalistId);
  if (!dl) return false;
  const v = value.trim().toLowerCase();
  for (const opt of dl.options) {
    if (opt.value.trim().toLowerCase() === v) return true;
  }
  return false;
}

function vnValidateDatalist(inputEl) {
  // Delegate to unified PMS_ADDR module for context-aware validation
  if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.validateDatalist) {
    return PMS_ADDR.validateDatalist(inputEl);
  }

  // Fallback: simple validation (for modules without PMS_ADDR)
  const dlId = inputEl.dataset.dl;
  if (!dlId) return true;
  const val = inputEl.value.trim();

  // Wait for async load
  if (inputEl.id === 'ci-district' && _vnDistrictLoading) return true;
  if (inputEl.id === 'ci-ward' && _vnWardLoading) return true;

  if (!val) {
    inputEl.style.borderColor = '';
    inputEl.style.boxShadow = '';
    inputEl.title = '';
    return true;
  }
  if (vnIsInDatalist(dlId, val)) {
    inputEl.style.borderColor = '';
    inputEl.style.boxShadow = '';
    inputEl.title = '';
    return true;
  } else {
    // Progressive normalization: accept but suggest
    inputEl.style.borderColor = '#eab308'; // Amber instead of red
    inputEl.style.boxShadow = '0 0 0 3px rgba(234,179,8,0.12)';
    inputEl.title = `"${val}" không khớp — vẫn lưu được, gợi ý chọn từ danh sách`;
    return true; // ✅ Always accept, never block
  }
}

function vnValidateAddressFields() {
  // Delegate to unified PMS_ADDR module
  if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.validateAddressFields) {
    return PMS_ADDR.validateAddressFields('ci');
  }

  // Fallback: simple validation
  if (_vnDistrictLoading || _vnWardLoading) {
    return { valid: true, errors: [], warnings: ['Vui lòng chờ dữ liệu được tải...'] };
  }

  const mode = vnGetMode();
  const errors = [];

  const provEl = document.getElementById('ci-province');
  if (provEl && !vnIsInDatalist('dl-province', provEl.value)) {
    // Progressive: warn but don't block
    provEl.style.borderColor = '#eab308';
  }

  if (mode === 'old') {
    const distEl = document.getElementById('ci-district');
    if (distEl && !vnIsInDatalist('dl-district', distEl.value)) {
      distEl.style.borderColor = '#eab308';
    }
  }

  const wardEl = document.getElementById('ci-ward');
  if (wardEl && !vnIsInDatalist('dl-ward', wardEl.value)) {
    // Progressive: warn but don't block
    wardEl.style.borderColor = '#eab308';
  }

  return { valid: true, errors: [], warnings: ['Địa chỉ chưa chuẩn hóa - sẽ được xử lý sau'] };
}

// ─── Exports ────────────────────────────────────────────────────────────────────

window.vnInitAddressFields = vnInitAddressFields;
window.vnSwitchMode = vnSwitchMode;
window.vnOnProvinceChange = vnOnProvinceChange;
window.vnOnDistrictChange = vnOnDistrictChange;
window.vnOnWardChange = vnOnWardChange;
window.vnPopulateDatalist = vnPopulateDatalist;
window.vnValidateDatalist = vnValidateDatalist;
window.vnValidateAddressFields = vnValidateAddressFields;
window.vnLoadNewProvinces = vnLoadNewProvinces;
window.vnLoadOldProvinces = vnLoadOldProvinces;
