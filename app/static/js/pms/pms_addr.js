// static/js/pms/pms_addr.js
// PMS Unified Address Manager - Progressive Normalization
// Handles address lifecycle: RAW → SELECTED → MAPPED → NORMALIZED
'use strict';

// ─── Address State Machine ───────────────────────────────────────────────────

const PMS_ADDR = {
    // Context types
    CTX_AUTOFILL: 'autofill',
    CTX_USER_INPUT: 'user_input',
    CTX_SCAN: 'scan',
    CTX_EDIT: 'edit',

    // Lifecycle states
    STATE_RAW: 'RAW',
    STATE_SELECTED: 'SELECTED',
    STATE_MAPPED: 'MAPPED',
    STATE_NORMALIZED: 'NORMALIZED',

    // Internal state (per-modal, use getState/setState)
    _state: null,
    _context: null,
    _modalId: null,

    // ── State Management ───────────────────────────────────────────────────────

    init(modalId) {
        this._modalId = modalId;
        this._state = this.STATE_RAW;
        this._context = this.CTX_USER_INPUT;
        this._clearBadges();
    },

    reset() {
        this._state = this.STATE_RAW;
        this._context = this.CTX_USER_INPUT;
    },

    getState() {
        return {
            state: this._state,
            context: this._context,
            isTrusted: this._context === this.CTX_AUTOFILL,
            isRaw: this._state === this.STATE_RAW,
            isSelected: this._state === this.STATE_SELECTED,
            isMapped: this._state === this.STATE_MAPPED,
            isNormalized: this._state === this.STATE_NORMALIZED,
            shouldValidate: this._context !== this.CTX_AUTOFILL
        };
    },

    // Mark as autofill/trusted data (from DB/CCCD)
    markAutofill() {
        this._context = this.CTX_AUTOFILL;
        this._state = this.STATE_RAW;
    },

    // Mark as user input
    markUserInput() {
        this._context = this.CTX_USER_INPUT;
    },

    // Mark as selected from dropdown
    markSelected() {
        this._state = this.STATE_SELECTED;
    },

    // Mark as mapped by conversion
    markMapped() {
        this._state = this.STATE_MAPPED;
    },

    // Mark as normalized
    markNormalized() {
        this._state = this.STATE_NORMALIZED;
    },

    // ── Validation Helpers ───────────────────────────────────────────────────

    shouldValidate() {
        return this._context !== this.CTX_AUTOFILL;
    },

    // Main validation function - context-aware
    validateDatalist(inputEl) {
        const state = this.getState();
        const dlId = inputEl.dataset.dl;
        const dl = dlId ? document.getElementById(dlId) : null;
        const val = inputEl.value.trim();

        // Wait for async load
        if (inputEl.id?.includes('district') && this._isLoading('district')) {
            return true;
        }
        if (inputEl.id?.includes('ward') && this._isLoading('ward')) {
            return true;
        }

        // ── TRUSTED DATA (autofill/DB) ──────────────────────────────────────
        if (state.isTrusted) {
            // Auto-accept, show green badge
            this._setInputState(inputEl, 'trusted', 'Địa chỉ từ dữ liệu cũ - sẽ được chuẩn hóa');
            this._updateStateBadge('RAW', 'Địa chỉ từ dữ liệu cũ', 'blue');
            return true;
        }

        // ── RAW STATE (not matched yet) ───────────────────────────────────
        if (state.isRaw) {
            if (!val) {
                this._clearInputState(inputEl);
                return true;
            }

            // Check if matches datalist
            if (dl && this._isInDatalist(dl, val)) {
                this._setInputState(inputEl, 'matched', 'Khớp với danh sách');
                this.markMapped();
                return true;
            }

            // Has value but not in datalist - suggest but accept
            const suggestions = dl ? this._findSuggestions(dl, val) : [];
            if (suggestions.length > 0) {
                this._setInputState(inputEl, 'warning', `Gợi ý: "${suggestions[0]}"`);
                this._showSuggestions(inputEl, suggestions);
                return true;
            }

            // No match, no suggestions - accept with warning
            this._setInputState(inputEl, 'warning', 'Địa chỉ không khớp - vẫn lưu được');
            return true;
        }

        // ── SELECTED/MAPPED STATE ──────────────────────────────────────────
        if (!val) {
            this._clearInputState(inputEl);
            return true;
        }

        if (dl && this._isInDatalist(dl, val)) {
            this._setInputState(inputEl, 'matched', 'Hợp lệ');
            return true;
        }

        // Near match - suggest
        const suggestions = dl ? this._findSuggestions(dl, val) : [];
        if (suggestions.length > 0) {
            this._setInputState(inputEl, 'suggest', `Có thể: "${suggestions[0]}"`);
            return true;
        }

        // User typed something not in list - accept but flag
        this._setInputState(inputEl, 'warning', 'Giá trị tự nhập - vẫn lưu được');
        return true;
    },

    // Address-level validation
    validateAddressFields(prefix = 'ci') {
        if (this._isLoading('district') || this._isLoading('ward')) {
            return { valid: true, errors: [], warnings: ['Đang tải dữ liệu địa chỉ...'] };
        }

        const state = this.getState();
        const errors = [];
        const warnings = [];

        const provEl = document.getElementById(`${prefix}-province`);
        const provVal = provEl?.value?.trim();

        // Province is always required for VN guests
        if (!provVal) {
            errors.push('Tỉnh/Thành phố là bắt buộc');
            if (provEl) {
                provEl.classList.add('is-invalid');
                provEl.focus();
            }
        }

        // Trust data passes
        if (state.isTrusted || state.isRaw) {
            if (state.isRaw) {
                warnings.push('Địa chỉ chưa chuẩn hóa - sẽ được xử lý sau');
            }
            return { valid: errors.length === 0, errors, warnings };
        }

        // Ward validation for non-passport/visa
        const wardEl = document.getElementById(`${prefix}-ward`);
        const wardVal = wardEl?.value?.trim();

        if (!wardVal) {
            // Only require ward if province is selected
            if (provVal) {
                warnings.push('Phường/Xã khuyến nghị chọn từ danh sách');
            }
        }

        return { valid: errors.length === 0, errors, warnings };
    },

    // ── Internal Helpers ────────────────────────────────────────────────────

    _isLoading(type) {
        const el = document.getElementById(`_addr_${type}_loading`);
        return el ? el.value === 'true' : false;
    },

    _setLoading(type, isLoading) {
        let el = document.getElementById(`_addr_${type}_loading`);
        if (!el) {
            el = document.createElement('input');
            el.type = 'hidden';
            el.id = `_addr_${type}_loading`;
            document.body.appendChild(el);
        }
        el.value = isLoading ? 'true' : 'false';
    },

    _isInDatalist(dl, value) {
        if (!dl || !value) return false;
        const v = value.trim().toLowerCase();
        for (const opt of dl.options) {
            if (opt.value.trim().toLowerCase() === v) return true;
        }
        return false;
    },

    _findSuggestions(dl, value) {
        if (!dl || !value) return [];
        const v = value.trim().toLowerCase();
        const suggestions = [];

        for (const opt of dl.options) {
            const optVal = opt.value.trim().toLowerCase();
            // Starts with
            if (optVal.startsWith(v)) {
                suggestions.push(opt.value);
            }
            // Contains
            else if (optVal.includes(v)) {
                suggestions.push(opt.value);
            }
        }

        return suggestions.slice(0, 3);
    },

    _setInputState(inputEl, state, message) {
        if (!inputEl) return;

        inputEl.classList.remove('is-invalid', 'is-warning', 'is-suggest', 'is-trusted', 'is-matched');
        inputEl.style.borderColor = '';

        switch (state) {
            case 'trusted':
                inputEl.classList.add('is-trusted');
                inputEl.style.borderColor = '#22c55e';
                inputEl.title = message;
                break;
            case 'matched':
                inputEl.classList.add('is-matched');
                inputEl.style.borderColor = '#22c55e';
                inputEl.title = message;
                break;
            case 'warning':
                inputEl.classList.add('is-warning');
                inputEl.style.borderColor = '#eab308';
                inputEl.title = message;
                break;
            case 'suggest':
                inputEl.classList.add('is-suggest');
                inputEl.style.borderColor = '#8b5cf6';
                inputEl.title = message;
                break;
            case 'error':
                inputEl.classList.add('is-invalid');
                inputEl.style.borderColor = '#ef4444';
                inputEl.title = message;
                break;
        }
    },

    _clearInputState(inputEl) {
        if (!inputEl) return;
        inputEl.classList.remove('is-invalid', 'is-warning', 'is-suggest', 'is-trusted', 'is-matched');
        inputEl.style.borderColor = '';
        inputEl.title = '';
    },

    _showSuggestions(inputEl, suggestions) {
        // Remove existing dropdown
        const existing = document.getElementById('_addr_suggestions');
        if (existing) existing.remove();

        if (suggestions.length === 0) return;

        const wrapper = document.createElement('div');
        wrapper.id = '_addr_suggestions';
        wrapper.className = 'addr-suggestions-dropdown';
        wrapper.style.cssText = `
            position: absolute;
            z-index: 1000;
            background: #fff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            max-height: 150px;
            overflow-y: auto;
            width: 100%;
        `;

        suggestions.forEach(s => {
            const item = document.createElement('div');
            item.style.cssText = 'padding: 8px 12px; cursor: pointer; font-size: 13px;';
            item.textContent = s;
            item.onclick = () => {
                inputEl.value = s;
                inputEl.dispatchEvent(new Event('change'));
                wrapper.remove();
                this.markSelected();
            };
            item.onmouseenter = () => item.style.background = '#f1f5f9';
            item.onmouseleave = () => item.style.background = '#fff';
            wrapper.appendChild(item);
        });

        // Position below input
        const rect = inputEl.getBoundingClientRect();
        wrapper.style.left = rect.left + 'px';
        wrapper.style.top = (rect.bottom + 4) + 'px';
        wrapper.style.width = rect.width + 'px';

        document.body.appendChild(wrapper);

        // Auto-dismiss on click outside
        setTimeout(() => {
            const handler = (e) => {
                if (!wrapper.contains(e.target) && e.target !== inputEl) {
                    wrapper.remove();
                    document.removeEventListener('click', handler);
                }
            };
            document.addEventListener('click', handler);
        }, 100);
    },

    _updateStateBadge(state, message, color) {
        const badge = document.getElementById('_addr_state_badge');
        if (!badge) return;

        const colorMap = {
            blue: '#3b82f6',
            green: '#22c55e',
            amber: '#eab308',
            purple: '#8b5cf6',
            gray: '#94a3b8'
        };

        badge.innerHTML = `
            <span class="addr-badge-dot" style="background: ${colorMap[color] || colorMap.gray}"></span>
            <span class="addr-badge-text"><strong>${state}</strong>: ${message}</span>
            <span class="addr-badge-hint">→ có thể chuẩn hóa sau</span>
        `;
        badge.style.display = 'flex';
    },

    _clearBadges() {
        const badge = document.getElementById('_addr_state_badge');
        if (badge) badge.style.display = 'none';
    },

    // ── Public Badge API ────────────────────────────────────────────────────

    showStateBadge(state, message, color) {
        this._updateStateBadge(state, message, color);
    },

    clearStateBadge() {
        this._clearBadges();
    },

    // ── Prefix Stripping ───────────────────────────────────────────────────

    stripPrefix(s) {
        if (!s) return '';
        const lower = s.toLowerCase();
        const prefixes = ['tỉnh ', 'thành phố ', 'tp ', 'quận ', 'huyện ', 'thị xã ', 'thị trấn ', 'phường ', 'xã '];
        for (const p of prefixes) {
            if (lower.startsWith(p)) return s.substring(p.length).trim();
        }
        return s.trim();
    },

    // ── Get Form Data ─────────────────────────────────────────────────────

    getFormData(prefix = 'ci') {
        const mode = document.querySelector(`input[name="${prefix}-area"]:checked`)?.value || 'new';
        const _city = document.getElementById(`${prefix}-province`)?.value?.trim() || '';
        const _ward = document.getElementById(`${prefix}-ward`)?.value?.trim() || '';
        const _dist = mode === 'old'
            ? (document.getElementById(`${prefix}-district`)?.value?.trim() || '')
            : (document.getElementById(`${prefix}-district`)?.value?.trim() || '');
        const _newCityEl = document.getElementById(`${prefix}-new-province`);
        const _newWardEl = document.getElementById(`${prefix}-new-ward`);
        const _newCity = _newCityEl?.value?.trim() || _city;
        const _newWard = _newWardEl?.value?.trim() || _ward;

        return {
            city: _city,
            district: _dist,
            ward: _ward,
            address_type: mode,
            new_city: _newCity,
            new_ward: _newWard,
            old_city: mode === 'old' ? _city : null,
            old_district: mode === 'old' ? _dist : null,
            old_ward: mode === 'old' ? _ward : null,
            _isRaw: this.getState().isRaw
        };
    }
};

// ─── Unified Datalist Helper ──────────────────────────────────────────────────

function addrPopulateDatalist(datalistId, items) {
    const dl = document.getElementById(datalistId);
    if (!dl) return;

    const sortedItems = [...items].sort((a, b) => {
        const nameA = typeof a === 'string' ? a : a.name;
        const nameB = typeof b === 'string' ? b : b.name;
        return PMS_ADDR.stripPrefix(nameA).localeCompare(PMS_ADDR.stripPrefix(nameB), 'vi', { numeric: true });
    });

    dl.innerHTML = '';
    sortedItems.forEach(item => {
        const opt = document.createElement('option');
        opt.value = typeof item === 'string' ? item : item.name;
        if (item.code) opt.dataset.code = item.code;
        if (item.short) opt.dataset.short = item.short;
        dl.appendChild(opt);
    });
}

function addrGetOpt(datalistId, name) {
    const dl = document.getElementById(datalistId);
    if (!dl || !name) return null;
    for (const opt of dl.options) {
        if (opt.value.trim() === name.trim()) return opt;
    }
    return null;
}

function addrIsInDatalist(datalistId, value) {
    if (!value) return false;
    const dl = document.getElementById(datalistId);
    if (!dl) return false;
    const v = value.trim().toLowerCase();
    for (const opt of dl.options) {
        if (opt.value.trim().toLowerCase() === v) return true;
    }
    return false;
}

// ─── Address Validation Wrapper ──────────────────────────────────────────────

function addrValidateDatalist(inputEl) {
    return PMS_ADDR.validateDatalist(inputEl);
}

function addrValidateAddressFields(prefix = 'ci') {
    return PMS_ADDR.validateAddressFields(prefix);
}

function addrGetFormData(prefix = 'ci') {
    return PMS_ADDR.getFormData(prefix);
}

// ─── Mode Switch ────────────────────────────────────────────────────────────

async function addrSwitchMode(prefix, mode, keepValues = true) {
    const distGrp = document.getElementById(`${prefix}-grp-district`);
    const convGrp = document.getElementById(`${prefix}-conversion-grp`);
    const districtEl = document.getElementById(`${prefix}-district`);
    const wardEl = document.getElementById(`${prefix}-ward`);
    const newProvEl = document.getElementById(`${prefix}-new-province`);
    const newWardEl = document.getElementById(`${prefix}-new-ward`);

    if (!keepValues) {
        document.getElementById(`${prefix}-province`).value = '';
        if (districtEl) districtEl.value = '';
        if (wardEl) wardEl.value = '';
    }

    // Clear dependent lists
    addrPopulateDatalist(`${prefix}-district`, []);
    addrPopulateDatalist(`${prefix}-ward`, []);

    // Clear conversion display
    if (newProvEl) { newProvEl.value = ''; newProvEl.style.color = ''; }
    if (newWardEl) { newWardEl.value = ''; newWardEl.style.color = ''; }

    // Show/hide district for old mode
    if (mode === 'new') {
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
    } else {
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';
    }
}

// ─── Fill From DB (Trusted Data) ─────────────────────────────────────────────

async function addrFillFromDB(prefix, guest) {
    const hasOldData = !!(guest.old_city || guest.old_ward || guest.old_district);
    const addrType = hasOldData ? 'old' : 'new';

    // 1. Mark as trusted BEFORE filling
    PMS_ADDR.markAutofill();

    // 2. Set radio without triggering switch
    const oldRadio = document.querySelector(`input[name="${prefix}-area"][value="old"]`);
    const newRadio = document.querySelector(`input[name="${prefix}-area"][value="new"]`);
    const distGrp = document.getElementById(`${prefix}-grp-district`);
    const convGrp = document.getElementById(`${prefix}-conversion-grp`);

    if (addrType === 'old') {
        if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = false; }
        if (newRadio) newRadio.disabled = false;
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';
    } else {
        if (newRadio) { newRadio.checked = true; }
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
        if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }
    }

    // 3. Fill province
    const pEl = document.getElementById(`${prefix}-province`);
    const dEl = document.getElementById(`${prefix}-district`);
    const wEl = document.getElementById(`${prefix}-ward`);
    const nProvEl = document.getElementById(`${prefix}-new-province`);
    const nWardEl = document.getElementById(`${prefix}-new-ward`);

    if (addrType === 'old') {
        // Fill OLD values into inputs
        if (pEl) pEl.value = guest.old_city || '';
        if (dEl) dEl.value = guest.old_district || '';
        if (wEl) wEl.value = guest.old_ward || '';

        // Fill NEW conversion display
        if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }
    } else {
        // Fill NEW values
        if (pEl) pEl.value = guest.city || '';
        if (wEl) wEl.value = guest.ward || '';

        if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }
    }

    // 4. Show state badge
    PMS_ADDR._updateStateBadge('RAW', 'Địa chỉ từ dữ liệu cũ - sẽ được chuẩn hóa', 'blue');

    // 5. Reset trusted flag after fill
    setTimeout(() => {
        PMS_ADDR.reset();
    }, 500);
}

// ─── CSS for Address States ──────────────────────────────────────────────────

const addrStateCSS = `
/* Address input states */
.is-trusted {
    border-color: #22c55e !important;
    background-color: #f0fdf4 !important;
}
.is-matched {
    border-color: #22c55e !important;
    background-color: #fff !important;
}
.is-warning {
    border-color: #eab308 !important;
    background-color: #fefce8 !important;
}
.is-suggest {
    border-color: #8b5cf6 !important;
    background-color: #faf5ff !important;
}

/* Address state badge */
.addr-state-badge {
    display: none;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
    border: 1px solid #bae6fd;
    border-radius: 8px;
    font-size: 12px;
    margin-top: 8px;
}
.addr-badge-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.addr-badge-text {
    color: #1e293b;
}
.addr-badge-hint {
    color: #64748b;
    font-size: 11px;
}

/* Address suggestions dropdown */
.addr-suggestions-dropdown {
    font-family: inherit;
}
.addr-suggestions-dropdown div:hover {
    background: #f1f5f9;
}
`;

// Inject CSS once (prevent duplicates)
if (typeof document !== 'undefined' && !document.getElementById('pms-addr-styles')) {
    const style = document.createElement('style');
    style.id = 'pms-addr-styles';
    style.textContent = addrStateCSS;
    document.head.appendChild(style);
}

// ─── Progressive Normalization State Badge ─────────────────────────────────────

function addrShowStateBadge(state, message, color) {
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR._updateStateBadge) {
        PMS_ADDR._updateStateBadge(state, message, color);
    }
}

function addrClearStateBadge() {
    const badge = document.getElementById('_addr_state_badge');
    if (badge) badge.style.display = 'none';
}

// ─── Global Exports ───────────────────────────────────────────────────────────

window.PMS_ADDR = PMS_ADDR;
window.addrPopulateDatalist = addrPopulateDatalist;
window.addrGetOpt = addrGetOpt;
window.addrIsInDatalist = addrIsInDatalist;
window.addrValidateDatalist = addrValidateDatalist;
window.addrValidateAddressFields = addrValidateAddressFields;
window.addrGetFormData = addrGetFormData;
window.addrSwitchMode = addrSwitchMode;
window.addrFillFromDB = addrFillFromDB;
window.addrShowStateBadge = addrShowStateBadge;
window.addrClearStateBadge = addrClearStateBadge;


// ─────────────────────────────────────────────────────────────────────────────
// CCCD QR Auto-Match: best-effort parse address string → datalist selection
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Attempt to match province/ward from a full Vietnamese address string.
 * prefix: 'ci' | 'ag' — maps to ci-province / ag-province, etc.
 *
 * addr: string | { raw?, province?, ward?, district?, detail? }
 *   - Khi là object (từ CCCD parser): dùng pmsMatchAddressToForm với card_type='CCCD_CU'
 *   - Khi là string (legacy): dùng pmsMatchAddressToForm với card_type='CCCD_CU'
 *
 * NOTE: Để switch đúng mode (cũ/mới), caller nên truyền card_type.
 *       Gọi trực tiếp pmsMatchAddressToForm(addr, prefix, cardType) để chỉ định mode.
 */
async function vnAutoMatchAddress(addr, prefix = 'ci') {
    if (!addr) return;
    if (typeof pmsMatchAddressToForm === 'function') {
        await pmsMatchAddressToForm(addr, prefix, 'CCCD_CU');
    }
}

window.vnAutoMatchAddress = vnAutoMatchAddress;
