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

function vnNormVietnamese(s) {
  if (!s) return '';
  return String(s)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase()
    .trim();
}

function vnNormWardNumber(s) {
  if (!s) return s;
  return s.replace(/^(phường|xã|thị trấn)\s*0+(\d+)/i, (match, prefix, num) => prefix + ' ' + parseInt(num, 10));
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
  const nameNorm = vnNormVietnamese(vnNormWardNumber(name));
  for (const opt of dl.options) {
    if (vnNormVietnamese(vnNormWardNumber(opt.value.trim())) === nameNorm) return opt;
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
  // ── Re-entry guard: prevent infinite loop from dispatchEvent or cascade calls ──
  if (inputEl._vnProcessing) return;
  inputEl._vnProcessing = true;

  try {
    const inputVal = inputEl.value.trim();
    const opt = vnGetOpt('dl-district', inputVal);
    _oldDist = { name: inputVal, code: opt ? parseInt(opt.dataset.code) : null };

    const wardInput = document.getElementById('ci-ward');
    if (wardInput) wardInput.value = '';
    vnPopulateDatalist('dl-ward', []);
    vnClearConversion();

    // Always load districts when province is selected, even if district input is empty
    if (!_oldProv.code) return;

    // If input is being cleared, reload district datalist for re-selection
    if (!inputVal) {
      _vnDistrictLoading = true;
      const districts = await vnLoadOldDistricts(_oldProv.code);
      _vnDistrictLoading = false;
      vnPopulateDatalist('dl-district', districts);
      // Force browser to refresh datalist dropdown after reload
      inputEl.focus();
      inputEl.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }

    // Only load wards if we have a valid district code
    if (!_oldDist.code) return;
    _vnWardLoading = true;
    const wards = await vnLoadOldWards(_oldDist.code);
    _vnWardLoading = false;
    vnPopulateDatalist('dl-ward', wards);
  } finally {
    inputEl._vnProcessing = false;
  }
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
      vnSetConversion(
          result.new_province || _oldProv.name, 
          result.new_ward || wardName, 
          result.matched
      );
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
  const vNorm = vnNormVietnamese(vnNormWardNumber(value.trim()));
  for (const opt of dl.options) {
    const optNorm = vnNormVietnamese(vnNormWardNumber(opt.value.trim()));
    if (optNorm === vNorm) return true;
    // Also check stripped versions
    const strippedOpt = vnStripPrefix(opt.value).toLowerCase();
    const strippedVal = vnStripPrefix(value).toLowerCase();
    if (vnNormVietnamese(vnNormWardNumber(strippedOpt)) === vnNormVietnamese(vnNormWardNumber(strippedVal))) return true;
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

// ═══════════════════════════════════════════════════════════════════════════════
// INTELLIGENT CONVERSION — Smart Confirm with Confidence Scoring
// ═══════════════════════════════════════════════════════════════════════════════

const VN_INTEL_API = '/api/vn-address';

// ─── Intelligent Convert ─────────────────────────────────────────────────────

/**
 * Call intelligent conversion API with confidence scoring.
 * @param {object} params - { oldWard, oldDistrict, oldProvince }
 * @returns {Promise<object>} - Result with confidence, suggestions, auto_action
 */
async function vnIntelligentConvert(params) {
  try {
    const res = await fetch(`${VN_INTEL_API}/intelligent-convert`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        old_ward_name: params.oldWard,
        old_district_name: params.oldDistrict || '',
        old_province_name: params.oldProvince || '',
      })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error('[vn_address] intelligent convert error:', e);
    return null;
  }
}

/**
 * Learn alias from user selection.
 */
async function vnLearnAlias(alias, targetWard, targetProvince) {
  try {
    await fetch(`${VN_INTEL_API}/learn-alias`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        alias,
        target_ward: targetWard,
        target_province: targetProvince,
      })
    });
  } catch (e) {
    console.error('[vn_address] learn alias error:', e);
  }
}

/**
 * Record correction when user fixes wrong suggestion.
 */
async function vnRecordCorrection(inputWard, wrongResult, correctWard, correctProvince) {
  try {
    await fetch(`${VN_INTEL_API}/record-correction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_ward: inputWard,
        wrong_result: wrongResult,
        correct_ward: correctWard,
        correct_province: correctProvince,
      })
    });
  } catch (e) {
    console.error('[vn_address] record correction error:', e);
  }
}

// ─── Confidence Display ───────────────────────────────────────────────────────

/**
 * Get CSS class and color for confidence level.
 */
function vnGetConfidenceStyle(confidence) {
  if (confidence >= 0.9) {
    return {
      cls: 'vn-conf-high',
      color: '#15803d',
      bg: '#dcfce7',
      label: 'Chắc chắn',
      icon: '✓'
    };
  } else if (confidence >= 0.7) {
    return {
      cls: 'vn-conf-medium',
      color: '#b45309',
      bg: '#fef3c7',
      label: 'Có thể',
      icon: '?'
    };
  } else {
    return {
      cls: 'vn-conf-low',
      color: '#dc2626',
      bg: '#fee2e2',
      label: 'Không chắc',
      icon: '✗'
    };
  }
}

/**
 * Render confidence badge in conversion result.
 */
function vnRenderConfidenceBadge(confidence, container) {
  if (!container) return;
  
  const style = vnGetConfidenceStyle(confidence);
  const pct = Math.round(confidence * 100);
  
  container.innerHTML = `
    <div class="vn-confidence-badge ${style.cls}" style="background:${style.bg};color:${style.color}">
      <span class="vn-conf-icon">${style.icon}</span>
      <span class="vn-conf-label">${style.label}</span>
      <span class="vn-conf-pct">${pct}%</span>
    </div>
  `;
}

// ─── Smart Confirm UI ─────────────────────────────────────────────────────────

/**
 * Show smart confirm UI based on auto_action.
 * @param {object} result - Intelligence API result
 * @param {string} inputWard - Original ward input
 */
function vnShowSmartConfirm(result, inputWard) {
  if (!result) return;
  
  const autoAction = result.auto_action || 'confirm';
  const confidence = result.confidence || 0;
  const suggestions = result.suggestions || [];
  const ambiguous = result.ambiguous;
  
  // Update confidence badge
  const badgeEl = document.getElementById('ci-conv-confidence');
  if (badgeEl) {
    vnRenderConfidenceBadge(confidence, badgeEl);
  }
  
  // Update note
  const noteEl = document.getElementById('ci-conv-note');
  if (noteEl) {
    noteEl.textContent = result.note || '';
    noteEl.style.color = confidence >= 0.9 ? '#15803d' : confidence >= 0.7 ? '#b45309' : '#dc2626';
  }
  
  // Show suggestions if ambiguous
  vnShowSuggestions(suggestions, inputWard, result);
  
  // Show warning if low confidence
  if (confidence < 0.7) {
    vnShowWarning('Độ chính xác thấp. Vui lòng xác nhận lại địa chỉ.');
  } else if (ambiguous) {
    vnShowWarning('Có nhiều kết quả phù hợp. Vui lòng chọn đúng phường/xã.');
  }
}

/**
 * Show suggestions list for ambiguous cases.
 */
function vnShowSuggestions(suggestions, inputWard, result) {
  const container = document.getElementById('ci-conv-suggestions');
  if (!container) return;
  
  if (!suggestions || suggestions.length <= 1) {
    container.innerHTML = '';
    return;
  }
  
  const items = suggestions.map((s, i) => `
    <div class="vn-suggestion-item" data-index="${i}" onclick="vnSelectSuggestion(${i}, '${s.ward}', '${s.province}')">
      <span class="vn-suggestion-num">${i + 1}</span>
      <span class="vn-suggestion-ward">${s.ward}</span>
      <span class="vn-suggestion-prov">${s.province}</span>
    </div>
  `).join('');
  
  container.innerHTML = `
    <div class="vn-suggestions-header">Gợi ý:</div>
    ${items}
  `;
}

// Global selected suggestion index
let _vnSelectedSuggestion = -1;

/**
 * Handle suggestion selection.
 */
window.vnSelectSuggestion = async function(index, ward, province) {
  _vnSelectedSuggestion = index;
  
  // Highlight selected
  document.querySelectorAll('.vn-suggestion-item').forEach((el, i) => {
    el.classList.toggle('selected', i === index);
  });
  
  // Update ward field
  const wardEl = document.getElementById('ci-new-ward');
  if (wardEl) {
    wardEl.value = ward;
  }
  
  // Update province if needed
  const provEl = document.getElementById('ci-new-province');
  if (provEl && province) {
    provEl.value = province;
  }
  
  // Learn from selection
  const oldWard = document.getElementById('ci-ward')?.value || '';
  const oldProv = document.getElementById('ci-province')?.value || '';
  await vnLearnAlias(oldWard, ward, province);
};

/**
 * Show warning message.
 */
function vnShowWarning(msg) {
  const warnEl = document.getElementById('ci-conv-warning');
  if (warnEl) {
    warnEl.textContent = msg;
    warnEl.style.display = 'block';
  }
}

/**
 * Hide warning message.
 */
function vnHideWarning() {
  const warnEl = document.getElementById('ci-conv-warning');
  if (warnEl) {
    warnEl.style.display = 'none';
  }
}

// ─── Enhanced Ward Change with Intelligence ───────────────────────────────────

let _vnIntelConvTimeout = null;

async function vnOnOldWardChangeIntel(inputEl) {
  const wardName = inputEl.value.trim();
  vnClearConversion();
  vnHideWarning();
  
  if (!wardName) return;
  
  // ✋ Guard: only trigger if value is in datalist
  if (!vnIsInDatalist('dl-ward', wardName)) return;
  
  // Debounce
  clearTimeout(_vnIntelConvTimeout);
  _vnIntelConvTimeout = setTimeout(async () => {
    // Get province and district
    const provName = document.getElementById('ci-province')?.value || '';
    const distName = document.getElementById('ci-district')?.value || '';
    
    // Call intelligent convert
    const result = await vnIntelligentConvert({
      oldWard: wardName,
      oldDistrict: distName,
      oldProvince: provName,
    });
    
    if (result) {
      // Set conversion display
      vnSetConversion(
        result.new_province || provName,
        result.new_ward || wardName,
        result.matched
      );
      
      // Show smart confirm UI
      vnShowSmartConfirm(result, wardName);
      
      // Store result for later use
      inputEl._intelResult = result;
    }
  }, 300);
}

// ─── Enhanced Conversion Display ────────────────────────────────────────────────

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
    wardEl.title = matched 
      ? 'Ánh xạ tự động từ dữ liệu thông minh'
      : 'Không tìm thấy ánh xạ — tên giữ nguyên';
  }
  
  // Clear confidence if no match
  if (!matched) {
    const badgeEl = document.getElementById('ci-conv-confidence');
    if (badgeEl) badgeEl.innerHTML = '';
    const noteEl = document.getElementById('ci-conv-note');
    if (noteEl) {
      noteEl.textContent = 'Không tìm thấy ánh xạ — vui lòng chọn thủ công';
      noteEl.style.color = '#dc2626';
    }
  }
}

function vnClearConversion() {
  vnSetConversion('', '', false);
  
  // Clear confidence UI
  const badgeEl = document.getElementById('ci-conv-confidence');
  if (badgeEl) badgeEl.innerHTML = '';
  const noteEl = document.getElementById('ci-conv-note');
  if (noteEl) noteEl.textContent = '';
  const suggestionsEl = document.getElementById('ci-conv-suggestions');
  if (suggestionsEl) suggestionsEl.innerHTML = '';
  vnHideWarning();
}

// ─── Override Original Ward Handler ────────────────────────────────────────────
// For now, keep original handler. Intelligence can be enabled per-module.

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
window.vnGetOpt = vnGetOpt;
window.vnStripPrefix = vnStripPrefix;
window.vnNormVietnamese = vnNormVietnamese;

// Intelligence exports
window.vnIntelligentConvert = vnIntelligentConvert;
window.vnLearnAlias = vnLearnAlias;
window.vnRecordCorrection = vnRecordCorrection;
window.vnOnOldWardChangeIntel = vnOnOldWardChangeIntel;
window.vnShowSmartConfirm = vnShowSmartConfirm;
window.vnGetConfidenceStyle = vnGetConfidenceStyle;
