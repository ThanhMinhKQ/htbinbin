// static/js/pms/ag_form.js
// AG Modal — Validation, Formatting, ID Field & Form Helpers
// Kiến trúc mirror hoàn chỉnh từ pms_checkin.js với logic AG chuyên biệt
// NOTE: State variables (agStayId, agGuestList, _agEditIndex, _agIsOldGuest...) được khai báo trong ag_modal.js
'use strict';

// ── Get current form guest data ─────────────────────────────────────────────

function agGetFormGuest() {
    // Address type drives which fields feed submission:
    // ── NEW mode:
    //     ag-province/ward = NEW values (datalist inputs, pre-2025 standard names)
    //     ag-new-province/ward = empty (no conversion needed)
    //     Submit: city/ward = NEW values; old_* = null
    // ── OLD mode:
    //     ag-province/district/ward = OLD values (datalist inputs, pre-2025 standard)
    //     ag-new-province/ward = READONLY display of converted NEW values
    //     Submit: city/ward = OLD values; old_city/old_district/old_ward = OLD values
    //             Backend will convert OLD → NEW and store both sides.
    const mode = document.querySelector('input[name="ag-area"]:checked')?.value || 'new';

    const _oldCity = document.getElementById('ag-province')?.value?.trim() || '';
    const _oldWard = document.getElementById('ag-ward')?.value?.trim() || '';
    const _oldDist = mode === 'old'
        ? (document.getElementById('ag-district')?.value?.trim() || '')
        : (document.getElementById('ag-district')?.value?.trim() || '');

    // new_* carry the converted values (from readonly conversion display)
    const _newCityEl = document.getElementById('ag-new-province');
    const _newWardEl = document.getElementById('ag-new-ward');
    const _newCity = _newCityEl?.value?.trim() || _oldCity;
    const _newWard = _newWardEl?.value?.trim() || _oldWard;

    // Invoice info
    const invoiceVal = document.querySelector('input[name="ag-invoice"]:checked')?.value || '0';
    const taxCode = invoiceVal === '1' ? (document.getElementById('ag-tax-code')?.value?.trim() || '') : '';
    const invoiceContact = invoiceVal === '1' ? (document.getElementById('ag-tax-contact')?.value?.trim() || '') : '';

    return {
        full_name: document.getElementById('ag-name')?.value?.trim() || '',
        id_type: document.getElementById('ag-id-type')?.value || 'cccd',
        cccd: document.getElementById('ag-cccd')?.value?.trim() || '',
        id_expire: document.getElementById('ag-id-expire')?.value || '',
        gender: document.getElementById('ag-gender')?.value || '',
        birth_date: document.getElementById('ag-birth')?.value || '',
        phone: document.getElementById('ag-phone')?.value?.trim() || '',
        // city/ward = what user typed (OLD values in old-mode; NEW values in new-mode)
        city: _oldCity,
        district: _oldDist,
        ward: _oldWard,
        address: document.getElementById('ag-address')?.value?.trim() || '',
        address_type: mode,
        // new_city/new_ward = post-reform values (from readonly conversion display)
        new_city: _newCity,
        new_ward: _newWard,
        // old_* = explicitly typed OLD values (only in old-mode)
        old_city: mode === 'old' ? _oldCity : null,
        old_district: mode === 'old' ? _oldDist : null,
        old_ward: mode === 'old' ? _oldWard : null,
        nationality: document.getElementById('ag-nationality')?.value?.trim() || 'VNM - Việt Nam',
        notes: document.getElementById('ag-notes')?.value?.trim() || '',
        tax_code: taxCode,
        invoice_contact: invoiceContact,
        from_old: _agIsOldGuest
    };
}
window.agGetFormGuest = agGetFormGuest;

// ── Get stay info for submission ─────────────────────────────────────────────

function agGetStayInfo() {
    return {
        stay_id: parseInt(document.getElementById('ag-stay-id')?.value || '0'),
        room_number: agRoomNum || '',
        max_guests: agMaxGuests
    };
}
window.agGetStayInfo = agGetStayInfo;

// ── Capacity Warning ─────────────────────────────────────────────────────────

function agUpdateCapacityWarn() {
    const primary = agGetFormGuest().full_name ? 1 : 0;
    const total = agGuestList.length + primary;
    const warnEl = document.getElementById('ag-capacity-warn');
    if (!warnEl) return;
    if (total > agMaxGuests) {
        warnEl.textContent = `Số khách (${total}) vượt quá giới hạn phòng (tối đa ${agMaxGuests} người). Vui lòng giảm số lượng khách hoặc chọn phòng khác.`;
        warnEl.classList.add('show');
    } else {
        warnEl.classList.remove('show');
    }
}
window.agUpdateCapacityWarn = agUpdateCapacityWarn;

function agGetGuestCount() {
    const primary = agGetFormGuest().full_name ? 1 : 0;
    return agGuestList.length + primary;
}
window.agGetGuestCount = agGetGuestCount;

// ── ID format / validation ───────────────────────────────────────────────────

function agFormatID(input) {
    input.value = input.value.replace(/\s+/g, '').toUpperCase();
}
window.agFormatID = agFormatID;

function agValidateID(input) {
    if (!input) return { valid: true };
    const type = document.getElementById('ag-id-type')?.value || 'cccd';
    const val = input.value.trim();
    if (!val) {
        input.classList.remove('is-invalid');
        return { valid: true };
    }

    let isValid = true;
    let message = '';

    if (type === 'cccd') {
        if (!/^\d{12}$/.test(val)) {
            isValid = false;
            message = 'Số CCCD phải có đúng 12 chữ số!';
        }
    } else if (type === 'cmnd') {
        if (!/^\d{9}$/.test(val)) {
            isValid = false;
            message = 'Số CMND phải có đúng 9 chữ số!';
        }
    }

    if (!isValid) {
        input.classList.add('is-invalid');
    } else {
        input.classList.remove('is-invalid');
    }

    return { valid: isValid, message };
}
window.agValidateID = agValidateID;

// ── ID type toggle (show/hide address & expire based on doc type) ───────────

function agToggleIdFields(select) {
    const val = select.value;
    const isForeign = val === 'passport' || val === 'visa';
    const noExpire = val === 'cmnd' || val === 'gplx';
    const expireGrp = document.getElementById('ag-grp-expire');
    const staySection = document.getElementById('ag-section-stay');
    const areaGrp = document.getElementById('ag-grp-area');
    const provGrp = document.getElementById('ag-grp-province');
    const wardGrp = document.getElementById('ag-grp-ward');
    const addrGrp = document.getElementById('ag-grp-address');

    if (expireGrp) expireGrp.style.display = noExpire ? 'none' : '';

    if (isForeign) {
        if (staySection) staySection.classList.add('ag-section-disabled');
        ['ag-province', 'ag-district', 'ag-ward', 'ag-address'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.disabled = true; el.readOnly = true; }
        });
        document.querySelectorAll('#agModal input[name="ag-area"]').forEach(r => {
            if (r) r.disabled = true;
        });
        if (areaGrp) areaGrp.style.display = 'none';
        if (provGrp) provGrp.style.display = 'none';
        if (wardGrp) wardGrp.style.display = 'none';
        if (addrGrp) addrGrp.style.display = 'none';
        // Also hide conversion and district
        const distGrp = document.getElementById('ag-grp-district');
        const convGrp = document.getElementById('ag-conversion-grp');
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
    } else {
        if (staySection) staySection.classList.remove('ag-section-disabled');
        ['ag-province', 'ag-district', 'ag-ward', 'ag-address'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.disabled = false; el.readOnly = false; }
        });
        document.querySelectorAll('#agModal input[name="ag-area"]').forEach(r => {
            if (r && r.style.display !== 'none') r.disabled = false;
        });
        if (areaGrp) areaGrp.style.display = '';
        if (provGrp) provGrp.style.display = '';
        if (wardGrp) wardGrp.style.display = '';
        if (addrGrp) addrGrp.style.display = '';
    }
}
window.agToggleIdFields = agToggleIdFields;

// ── Stay area radios toggle ──────────────────────────────────────────────────

function agToggleStayAreaRadios(enabled) {
    document.querySelectorAll('#agModal input[name="ag-area"]').forEach(r => {
        if (r) r.disabled = !enabled;
    });
}
window.agToggleStayAreaRadios = agToggleStayAreaRadios;

// ── Expire / birth check (with alert on blur) ───────────────────────────────

let _agIdExpireTimer = null;
let _agBirthTimer = null;

function agCheckIdExpire(inputEl) {
    if (!inputEl.value) { inputEl.classList.remove('is-invalid'); return; }
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    if (inputEl.value <= todayStr) {
        inputEl.classList.add('is-invalid');
        clearTimeout(_agIdExpireTimer);
        _agIdExpireTimer = setTimeout(() => {
            alert('⚠️ Cảnh báo: Giấy tờ này đã quá ngày hết hạn!');
        }, 100);
    } else {
        inputEl.classList.remove('is-invalid');
    }
}
window.agCheckIdExpire = agCheckIdExpire;

function agCheckBirth(inputEl) {
    if (!inputEl.value) { inputEl.classList.remove('is-warning'); return; }
    const parts = inputEl.value.split('-');
    if (parts.length === 3) {
        const birth = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const today = new Date();
        let age = today.getFullYear() - birth.getFullYear();
        const m = today.getMonth() - birth.getMonth();
        if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
        if (age < 18) {
            inputEl.classList.add('is-warning');
            clearTimeout(_agBirthTimer);
            _agBirthTimer = setTimeout(() => {
                alert(`⚠️ Cảnh báo: Khách hàng hiện mới ${age} tuổi. Việc nhận phòng có thể yêu cầu người giám hộ!`);
            }, 250);
        } else {
            inputEl.classList.remove('is-warning');
        }
    }
}
window.agCheckBirth = agCheckBirth;

// ── Text formatting helpers ───────────────────────────────────────────────────

function agFormatCapitalize(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
window.agFormatCapitalize = agFormatCapitalize;

function agFormatSentence(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.charAt(0).toUpperCase() + val.slice(1);
}
window.agFormatSentence = agFormatSentence;

function agFormatBasicNumeric(input) {
    input.value = input.value.replace(/\s+/g, '').replace(/\D/g, '');
}
window.agFormatBasicNumeric = agFormatBasicNumeric;

// ── Invoice toggle ───────────────────────────────────────────────────────────

function agToggleInvoice(radio) {
    const val = radio.value;
    const fieldsEl = document.getElementById('ag-invoice-fields');
    if (fieldsEl) fieldsEl.style.display = val === '1' ? 'block' : 'none';
}
window.agToggleInvoice = agToggleInvoice;

// ── Validation Core ──────────────────────────────────────────────────────────

function agFailValidation(inputId, message) {
    const el = document.getElementById(inputId);
    if (el) { el.classList.add('is-invalid'); el.focus(); }
    alert(message);
    return { valid: false, message };
}
window.agFailValidation = agFailValidation;

function agClearValidation() {
    document.querySelectorAll('#agModal .is-invalid').forEach(el => el.classList.remove('is-invalid'));
    document.querySelectorAll('#agModal .is-warning').forEach(el => el.classList.remove('is-warning'));
}

function agValidateGuestForm(g) {
    agClearValidation();

    // ── 1. Số giấy tờ (required) ──────────────────────────────────────
    if (!g.cccd) return agFailValidation('ag-cccd', 'Vui lòng nhập Số giấy tờ');
    // ── 2. Loại giấy tờ (required) ───────────────────────────────────
    if (!g.id_type) return agFailValidation('ag-id-type', 'Vui lòng chọn Loại giấy tờ');
    // ── 3. Ngày hết hạn (only for documents that have expiry) ──────────
    const noExpire = g.id_type === 'cmnd' || g.id_type === 'gplx';
    if (!noExpire) {
        if (!g.id_expire) return agFailValidation('ag-id-expire', 'Vui lòng nhập Ngày hết hạn giấy tờ!');
        const today = new Date();
        const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
        if (g.id_expire <= todayStr) return agFailValidation('ag-id-expire', 'Giấy tờ này đã quá ngày hết hạn!');
    }
    // ── 4. Validate ID format after knowing doc type ───────────────────
    const idInput = document.getElementById('ag-cccd');
    const idValid = agValidateID(idInput);
    if (!idValid.valid) return agFailValidation('ag-cccd', idValid.message);
    // ── 5. Họ và tên (required) ────────────────────────────────────────
    if (!g.full_name) return agFailValidation('ag-name', 'Vui lòng nhập Họ và tên');
    // ── 6. Giới tính (required) ────────────────────────────────────────
    if (!g.gender) return agFailValidation('ag-gender', 'Vui lòng chọn Giới tính');
    // ── 7. Ngày sinh (required) ───────────────────────────────────────
    if (!g.birth_date) return agFailValidation('ag-birth', 'Vui lòng nhập Ngày sinh');
    // ── 8. Quốc tịch (required) ───────────────────────────────────────
    if (!g.nationality) return agFailValidation('ag-nationality', 'Vui lòng chọn Quốc tịch');

    // ── 9. Invoice validation — only when "Có xuất hoá đơn" ───────────
    const invoiceVal = document.querySelector('input[name="ag-invoice"]:checked')?.value || '0';
    if (invoiceVal === '1') {
        const taxCodeEl = document.getElementById('ag-tax-code');
        if (!taxCodeEl?.value?.trim()) return agFailValidation('ag-tax-code', 'Vui lòng nhập Mã số thuế');
        const taxContactEl = document.getElementById('ag-tax-contact');
        if (!taxContactEl?.value?.trim()) return agFailValidation('ag-tax-contact', 'Vui lòng nhập Liên hệ hoá đơn (Email hoặc SĐT)');
    }

    // ── 10. Address validation — only for domestic NEW guests ──────────
    // Skipped for: Passport/Visa (foreign) + old guests (already validated by DB)
    const isForeign = g.id_type === 'passport' || g.id_type === 'visa';
    const isOldGuest = _agIsOldGuest === true;

    if (!isForeign && !isOldGuest) {
        // Must select Province from datalist
        if (!g.city) return agFailValidation('ag-province', 'Vui lòng chọn Tỉnh/Thành phố từ danh sách');
        if (typeof agIsInDatalist === 'function' && !agIsInDatalist('dl-ag-province', g.city)) {
            const provEl = document.getElementById('ag-province');
            if (provEl) provEl.classList.add('is-invalid');
            return agFailValidation('ag-province', `"${g.city}" không có trong danh sách. Vui lòng chọn Tỉnh/Thành phố từ danh sách!`);
        }

        // Must select Ward from datalist
        if (!g.ward) return agFailValidation('ag-ward', 'Vui lòng chọn Phường/Xã từ danh sách');
        if (typeof agIsInDatalist === 'function' && !agIsInDatalist('dl-ag-ward', g.ward)) {
            const wardEl = document.getElementById('ag-ward');
            if (wardEl) wardEl.classList.add('is-invalid');
            return agFailValidation('ag-ward', `"${g.ward}" không có trong danh sách. Vui lòng chọn Phường/Xã từ danh sách!`);
        }

        // District only required in old-mode
        const addrType = g.address_type || 'new';
        if (addrType === 'old' && !g.district) {
            return agFailValidation('ag-district', 'Vui lòng chọn Quận/Huyện');
        }

        // Always require detail address
        if (!g.address) return agFailValidation('ag-address', 'Vui lòng nhập Địa chỉ chi tiết');
    }

    // ── 11. Age warning — < 18 triggers is-warning but does not block ─
    const birthInput = document.getElementById('ag-birth');
    if (g.birth_date && birthInput) {
        const parts = g.birth_date.split('-');
        if (parts.length === 3) {
            const birth = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
            const today = new Date();
            let age = today.getFullYear() - birth.getFullYear();
            const m = today.getMonth() - birth.getMonth();
            if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
            if (age < 18) birthInput.classList.add('is-warning');
            else birthInput.classList.remove('is-warning');
        }
    }

    return { valid: true, message: '' };
}
window.agValidateGuestForm = agValidateGuestForm;

// ── Lock / Unlock Fields ─────────────────────────────────────────────────────

function agSetStayAreaRadiosDisabled(disabled) {
    document.querySelectorAll('#agModal input[name="ag-area"]').forEach(r => {
        if (r) r.disabled = !!disabled;
    });
}

function agLockAllFields() {
    ['ag-name','ag-cccd','ag-id-expire','ag-birth','ag-nationality',
     'ag-address','ag-notes',
     'ag-province','ag-district','ag-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.readOnly = true;
            el.classList.remove('is-invalid', 'is-warning');
        }
    });
    const idTypeEl = document.getElementById('ag-id-type');
    if (idTypeEl) idTypeEl.disabled = true;
    const genderEl = document.getElementById('ag-gender');
    if (genderEl) genderEl.disabled = true;
    agSetStayAreaRadiosDisabled(true);
    // Lock invoice fields
    document.querySelectorAll('input[name="ag-invoice"]').forEach(r => r.disabled = true);
    const taxCodeEl = document.getElementById('ag-tax-code');
    if (taxCodeEl) taxCodeEl.readOnly = true;
    const taxContactEl = document.getElementById('ag-tax-contact');
    if (taxContactEl) taxContactEl.readOnly = true;
}
window.agLockAllFields = agLockAllFields;

function agUnlockAllFields() {
    ['ag-name','ag-cccd','ag-id-expire','ag-birth','ag-nationality',
     'ag-address','ag-notes',
     'ag-province','ag-district','ag-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.readOnly = false;
            el.classList.remove('is-invalid', 'is-warning');
        }
    });
    const idTypeEl = document.getElementById('ag-id-type');
    if (idTypeEl) { idTypeEl.disabled = false; agToggleIdFields(idTypeEl); }
    const genderEl = document.getElementById('ag-gender');
    if (genderEl) genderEl.disabled = false;
    agSetStayAreaRadiosDisabled(false);
    document.querySelectorAll('input[name="ag-invoice"]').forEach(r => r.disabled = false);
    const taxCodeEl = document.getElementById('ag-tax-code');
    if (taxCodeEl) taxCodeEl.readOnly = false;
    const taxContactEl = document.getElementById('ag-tax-contact');
    if (taxContactEl) taxContactEl.readOnly = false;
}
window.agUnlockAllFields = agUnlockAllFields;

// Legacy aliases
function agLockAllRequiredFields() { agLockAllFields(); }
function agUnlockAllRequiredFields() { agUnlockAllFields(); }
window.agLockAllRequiredFields = agLockAllRequiredFields;
window.agUnlockAllRequiredFields = agUnlockAllRequiredFields;
