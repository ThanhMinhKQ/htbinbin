// static/js/pms/eg_modal.js
// EG Modal — Edit Guest (ID fields LOCKED, dedicated modal)
// 'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let _egStayId = null;
let _egGuestId = null;
let _egGuestData = null; // original guest object

// ─── Address cache ──────────────────────────────────────────────────────────────
const _egVnCache = {
    provinces: null,
    districts: {},
    wards: {},
};

// ─── Toggle ID fields (show/hide address section based on doc type) ──────────
function egToggleIdFields(idTypeEl) {
    const val = (idTypeEl.value || '').toLowerCase();
    const isForeign = val === 'passport' || val === 'visa';
    const staySection = document.getElementById('eg-section-address');

    if (staySection) {
        if (isForeign) {
            staySection.classList.add('eg-section-locked');
        } else {
            staySection.classList.remove('eg-section-locked');
        }
    }
}
window.egToggleIdFields = egToggleIdFields;

// ─── Open modal ───────────────────────────────────────────────────────────────
async function openEG(stayId, guestId) {
    _egStayId = stayId;
    _egGuestId = guestId;
    _egGuestData = null;

    if (!stayId || !guestId) {
        pmsToast('Thiếu thông tin lưu trú hoặc khách', false);
        return;
    }

    document.getElementById('eg-stay-id').value = stayId;
    document.getElementById('eg-guest-id').value = guestId;

    // Clear form
    egClearForm();

    // Reset address mode to new
    egResetAddressMode();

    // Populate nationalities
    if (typeof pmsPopulateNationalities === 'function') {
        pmsPopulateNationalities('dl-eg-nationality');
    }

    // Load address provinces (supports both old and new)
    await egLoadProvinces();

    // Set sub-header (will be updated after fetching guest data)
    document.getElementById('eg-sub').textContent = 'Đang tải...';

    // Fetch guest data
    try {
        const d = await pmsApi(`/api/pms/stays/${stayId}`);
        const guest = (d.guests || []).find(g => g.id === guestId);
        if (!guest) {
            pmsToast('Không tìm thấy thông tin khách', false);
            closeModal('egModal');
            return;
        }
        _egGuestData = guest;
        egFillGuestData(guest);

        // Update sub-header: Phòng | Loại giấy tờ | Số giấy tờ
        const roomNum = document.getElementById('rd-room-num')?.textContent || d.room_number || '';
        const idTypeDisplay = egIdTypeDisplay(guest.id_type || 'cccd');
        const subText = `Phòng ${roomNum} | ${idTypeDisplay} | ${guest.cccd || ''}`;
        document.getElementById('eg-sub').textContent = subText;
    } catch (e) {
        console.error('[openEG] Error fetching guest:', e);
        pmsToast('Lỗi khi tải thông tin khách: ' + e.message, false);
        closeModal('egModal');
        return;
    }

    if (typeof openModal === 'function') openModal('egModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('egModal');
    else {
        const modal = document.getElementById('egModal');
        if (modal) modal.classList.add('show');
    }
}
window.openEG = openEG;

// ─── Reset Address Mode ───────────────────────────────────────────────────────
function egResetAddressMode() {
    const newRadio = document.querySelector('input[name="eg-area"][value="new"]');
    const oldRadio = document.querySelector('input[name="eg-area"][value="old"]');
    const distGrp = document.getElementById('eg-grp-district');
    const convGrp = document.getElementById('eg-conversion-grp');
    const staySection = document.getElementById('eg-section-address');

    if (newRadio) { newRadio.checked = true; newRadio.disabled = false; }
    if (oldRadio) { oldRadio.disabled = false; oldRadio.style.display = ''; }
    if (distGrp) distGrp.style.display = 'none';
    if (convGrp) convGrp.style.display = 'none';
    if (staySection) staySection.classList.remove('eg-section-locked');

    // Clear conversion fields
    ['eg-new-province', 'eg-new-ward', 'eg-district'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.value = ''; el.style.color = ''; }
    });
}

// ─── Switch Address Mode ──────────────────────────────────────────────────────
async function egSwitchMode(mode, keepValues = true) {
    const distGrp = document.getElementById('eg-grp-district');
    const convGrp = document.getElementById('eg-conversion-grp');
    const oldRadio = document.querySelector('input[name="eg-area"][value="old"]');
    const newRadio = document.querySelector('input[name="eg-area"][value="new"]');

    if (!keepValues) {
        ['eg-province', 'eg-district', 'eg-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    }

    if (mode === 'old') {
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';
        if (oldRadio) oldRadio.checked = true;

        // Load province datalist for old mode
        if (typeof egLoadOldProvinces === 'function') {
            const provinces = await egLoadOldProvinces();
            if (typeof egPopulateDatalist === 'function') {
                egPopulateDatalist('dl-eg-province', provinces);
            }
        }

        // Load districts for current province
        const provEl = document.getElementById('eg-province');
        if (provEl && provEl.value) {
            await egLoadDistricts(provEl.value);
        }

        // Trigger conversion if province/ward values exist
        egTriggerConversion();
    } else {
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
        if (newRadio) newRadio.checked = true;

        // Load province datalist for new mode
        if (typeof egLoadNewProvinces === 'function') {
            const provinces = await egLoadNewProvinces();
            if (typeof egPopulateDatalist === 'function') {
                egPopulateDatalist('dl-eg-province', provinces.map(p => ({ name: p.name, short: p.short })));
            }
        }

        // Clear conversion fields
        ['eg-new-province', 'eg-new-ward', 'eg-district'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    }
}
window.egSwitchMode = egSwitchMode;

// ─── Trigger Conversion ───────────────────────────────────────────────────────
async function egTriggerConversion() {
    const provEl = document.getElementById('eg-province');
    const wardEl = document.getElementById('eg-ward');
    const newProvEl = document.getElementById('eg-new-province');
    const newWardEl = document.getElementById('eg-new-ward');

    if (!provEl || !provEl.value) return;

    const mode = document.querySelector('input[name="eg-area"]:checked')?.value;
    if (mode !== 'old') return;

    try {
        const url = `/api/vn-address/convert?province=${encodeURIComponent(provEl.value)}&ward=${encodeURIComponent(wardEl?.value || '')}`;
        const res = await fetch(url);
        if (res.ok) {
            const data = await res.json();
            if (newProvEl) {
                newProvEl.value = data.new_province || '';
                newProvEl.style.color = data.new_province ? '#15803d' : '';
            }
            if (newWardEl) {
                newWardEl.value = data.new_ward || '';
                newWardEl.style.color = data.new_ward ? '#15803d' : '';
            }
        }
    } catch (e) {
        console.error('[eg] Conversion error:', e);
    }
}

// ─── Fill guest data ──────────────────────────────────────────────────────────
function egFillGuestData(g) {
    // 0. Mark as trusted BEFORE filling (PMS_ADDR progressive normalization)
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.markAutofill) {
        PMS_ADDR.markAutofill();
    }

    // Locked ID fields (readonly + locked style)
    const idTypeEl = document.getElementById('eg-id-type');
    if (idTypeEl) {
        idTypeEl.value = egIdTypeDisplay(g.id_type || 'cccd');
        idTypeEl.readOnly = true;
        idTypeEl.classList.add('eg-id-locked');
    }

    const cccdEl = document.getElementById('eg-cccd');
    if (cccdEl) {
        cccdEl.value = g.cccd || '';
        cccdEl.readOnly = true;
        cccdEl.classList.add('eg-id-locked');
    }

    // Personal info
    const nameEl = document.getElementById('eg-name');
    if (nameEl) nameEl.value = g.full_name || '';

    const genderEl = document.getElementById('eg-gender');
    if (genderEl) genderEl.value = g.gender || '';

    const birthEl = document.getElementById('eg-birth');
    if (birthEl) birthEl.value = g.birth_date ? String(g.birth_date).slice(0, 10) : '';

    const natEl = document.getElementById('eg-nationality');
    if (natEl) natEl.value = g.nationality || 'VNM - Việt Nam';

    const phoneEl = document.getElementById('eg-phone');
    if (phoneEl) phoneEl.value = g.phone || '';

    // Extra fields
    const expireEl = document.getElementById('eg-id-expire');
    if (expireEl) expireEl.value = g.id_expire ? String(g.id_expire).slice(0, 10) : '';

    const notesEl = document.getElementById('eg-notes');
    if (notesEl) notesEl.value = g.notes || '';

    // Toggle address section based on ID type
    if (idTypeEl) egToggleIdFields(idTypeEl);

    // Address handling
    const provEl = document.getElementById('eg-province');
    const wardEl = document.getElementById('eg-ward');
    const distEl = document.getElementById('eg-district');
    const addrEl = document.getElementById('eg-address');
    const newProvEl = document.getElementById('eg-new-province');
    const newWardEl = document.getElementById('eg-new-ward');

    // Detect mode: old_* fields exist → old mode, else new mode
    const hasOldData = !!(g.old_city || g.old_ward || g.old_district);
    const addrType = hasOldData ? 'old' : 'new';

    // Set radio WITHOUT triggering switch
    const oldRadio = document.querySelector('input[name="eg-area"][value="old"]');
    const newRadio = document.querySelector('input[name="eg-area"][value="new"]');
    const distGrp = document.getElementById('eg-grp-district');
    const convGrp = document.getElementById('eg-conversion-grp');
    const staySection = document.getElementById('eg-section-address');

    if (addrType === 'old') {
        if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = false; }
        if (newRadio) newRadio.disabled = false;
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';

        // Fill OLD values
        if (provEl) provEl.value = g.old_city || '';
        if (distEl) distEl.value = g.old_district || '';
        if (wardEl) wardEl.value = g.old_ward || '';

        // Fill NEW conversion display
        if (newProvEl) {
            newProvEl.value = g.city || '';
            newProvEl.style.color = g.city ? '#15803d' : '';
        }
        if (newWardEl) {
            newWardEl.value = g.ward || '';
            newWardEl.style.color = g.ward ? '#15803d' : '';
        }

        // Load wards for old district
        if (g.old_city && typeof _egVnCache.provinces !== 'undefined') {
            const prov = _egVnCache.provinces.find(p =>
                p.name === g.old_city || p.short === g.old_city
            );
            if (prov) {
                egLoadWards(prov.short || prov.name).then(() => {
                    if (wardEl) wardEl.value = g.old_ward || '';
                });
            }
        }
    } else {
        if (newRadio) { newRadio.checked = true; }
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
        if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }

        // Fill NEW values
        if (provEl) provEl.value = g.city || '';
        if (wardEl) wardEl.value = g.ward || '';

        // Load wards
        if (g.city && typeof _egVnCache.provinces !== 'undefined') {
            const prov = _egVnCache.provinces.find(p =>
                p.name === g.city || p.short === g.city
            );
            if (prov) {
                egLoadWards(prov.short || prov.name).then(() => {
                    if (wardEl) wardEl.value = g.ward || '';
                });
            }
        }
    }

    if (addrEl) addrEl.value = g.address || '';

    // 4b. Show state badge for trusted data (PMS_ADDR progressive normalization)
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR._updateStateBadge) {
        PMS_ADDR._updateStateBadge('RAW', 'Địa chỉ từ dữ liệu cũ - sẽ được chuẩn hóa', 'blue');
    }

    // 4c. Reset trusted flag after fill (allow validation for subsequent edits)
    setTimeout(() => {
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.reset) {
            PMS_ADDR.reset();
        }
    }, 500);
}

// ─── Clear form ───────────────────────────────────────────────────────────────
function egClearForm() {
    ['eg-name','eg-cccd','eg-id-expire','eg-birth',
     'eg-phone','eg-notes','eg-address','eg-nationality',
     'eg-province','eg-ward','eg-district',
     'eg-new-province','eg-new-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.value = '';
            el.classList.remove('is-invalid', 'is-warning');
            el.readOnly = false;
            el.style.color = '';
        }
    });
    const idTypeEl = document.getElementById('eg-id-type');
    if (idTypeEl) { idTypeEl.value = ''; idTypeEl.readOnly = false; idTypeEl.classList.remove('eg-id-locked'); }
    const cccdEl = document.getElementById('eg-cccd');
    if (cccdEl) { cccdEl.readOnly = false; cccdEl.classList.remove('eg-id-locked'); }
    const genderEl = document.getElementById('eg-gender');
    if (genderEl) genderEl.value = '';

    // Reset address section lock
    const staySection = document.getElementById('eg-section-address');
    if (staySection) staySection.classList.remove('eg-section-locked');
}

// ─── Address helpers ───────────────────────────────────────────────────────────
async function egLoadProvinces() {
    if (_egVnCache.provinces) return _egVnCache.provinces;
    try {
        const res = await fetch('/api/vn-address/new-provinces');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (data?.provinces) {
            _egVnCache.provinces = data.provinces;
            egPopulateDatalist('dl-eg-province', data.provinces.map(p => ({ name: p.name, short: p.short })));
            return data.provinces;
        }
    } catch (e) {
        console.error('[eg] Load provinces error:', e);
    }
    return [];
}

async function egLoadDistricts(provinceName) {
    if (!provinceName) return [];
    try {
        const res = await fetch('/api/vn-address/districts/' + encodeURIComponent(provinceName));
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (data?.districts) {
            _egVnCache.districts[provinceName] = data.districts;
            egPopulateDatalist('dl-eg-district', data.districts);
            return data.districts;
        }
    } catch (e) {
        console.error('[eg] Load districts error:', e);
    }
    return [];
}

async function egLoadWards(provinceShort) {
    if (!provinceShort) return [];
    if (_egVnCache.wards[provinceShort]) {
        egPopulateDatalist('dl-eg-ward', _egVnCache.wards[provinceShort]);
        return _egVnCache.wards[provinceShort];
    }
    try {
        const res = await fetch(`/api/vn-address/new-wards/${encodeURIComponent(provinceShort)}`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (data?.wards) {
            _egVnCache.wards[provinceShort] = data.wards;
            egPopulateDatalist('dl-eg-ward', data.wards);
            return data.wards;
        }
    } catch (e) {
        console.error('[eg] Load wards error:', e);
    }
    return [];
}

function egPopulateDatalist(datalistId, items) {
    const dl = document.getElementById(datalistId);
    if (!dl) return;
    const sorted = [...items].sort((a, b) => {
        const nameA = typeof a === 'string' ? a : a.name;
        const nameB = typeof b === 'string' ? b : b.name;
        return nameA.localeCompare(nameB, 'vi', { numeric: true });
    });
    let html = '';
    sorted.forEach(item => {
        const val = typeof item === 'string' ? item : item.name;
        const safeVal = val.replace(/"/g, '&quot;');
        const shortAttr = item.short ? ` data-short="${item.short}"` : '';
        html += `<option value="${safeVal}"${shortAttr}></option>`;
    });
    dl.innerHTML = html;
}

async function egOnProvinceChange(inputEl) {
    const name = inputEl.value.trim();
    const dl = document.getElementById('dl-eg-province');
    let short = null;
    if (dl) {
        for (const opt of dl.options) {
            if (opt.value.trim() === name) {
                short = opt.dataset.short;
                break;
            }
        }
    }
    const wardEl = document.getElementById('eg-ward');
    if (wardEl) wardEl.value = '';
    egPopulateDatalist('dl-eg-ward', []);
    if (!short) return;
    await egLoadWards(short);

    // If in old mode, trigger conversion
    const mode = document.querySelector('input[name="eg-area"]:checked')?.value;
    if (mode === 'old') {
        egTriggerConversion();
    }
}

function egValidateDatalist(inputEl) {
    const dlId = inputEl.dataset.dl;
    if (!dlId) return true;
    const dl = document.getElementById(dlId);
    if (!dl) return true;
    const val = inputEl.value.trim();
    if (val && Array.from(dl.options).some(opt => opt.value.trim().toLowerCase() === val.toLowerCase())) {
        inputEl.style.borderColor = '';
        return true;
    }
    if (dl.options.length > 0) {
        inputEl.value = dl.options[0].value;
        inputEl.style.borderColor = '';
        inputEl.dispatchEvent(new Event('change'));
        inputEl.dispatchEvent(new Event('input'));
        return true;
    }
    if (!val) { inputEl.style.borderColor = ''; return true; }
    inputEl.style.borderColor = '#ef4444';
    return false;
}

// ─── Formatting ───────────────────────────────────────────────────────────────
function egFormatCapitalize(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function egFormatSentence(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.charAt(0).toUpperCase() + val.slice(1);
}

function egFormatBasicNumeric(input) {
    input.value = input.value.replace(/\s+/g, '').replace(/\D/g, '');
}

// ─── Validation ───────────────────────────────────────────────────────────────
let _egIdExpireTimer = null;
let _egBirthTimer = null;

function egCheckIdExpire(inputEl) {
    if (!inputEl.value) { inputEl.classList.remove('is-invalid'); return; }
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    if (inputEl.value <= todayStr) {
        inputEl.classList.add('is-invalid');
        clearTimeout(_egIdExpireTimer);
        _egIdExpireTimer = setTimeout(() => {
            alert('Cảnh báo: Giấy tờ này đã quá ngày hết hạn!');
        }, 100);
    } else {
        inputEl.classList.remove('is-invalid');
    }
}

function egCheckBirth(inputEl) {
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
            clearTimeout(_egBirthTimer);
            _egBirthTimer = setTimeout(() => {
                alert(`Cảnh báo: Khách hàng hiện mới ${age} tuổi.`);
            }, 250);
        } else {
            inputEl.classList.remove('is-warning');
        }
    }
}

function egIdTypeDisplay(type) {
    const map = { cccd: 'CCCD', cmnd: 'CMND', passport: 'Passport', visa: 'Visa', gplx: 'GPLX' };
    return map[type] || type?.toUpperCase() || 'CCCD';
}

function egFailValidation(inputId, message) {
    const el = document.getElementById(inputId);
    if (el) { el.classList.add('is-invalid'); el.focus(); }
    alert(message);
    return false;
}

function egValidateForm() {
    document.querySelectorAll('#egModal .f-ctrl.is-invalid').forEach(el => el.classList.remove('is-invalid'));
    document.querySelectorAll('#egModal .f-ctrl.is-warning').forEach(el => el.classList.remove('is-warning'));

    // ID fields are locked, skip validation

    // Name
    const name = document.getElementById('eg-name')?.value?.trim();
    if (!name) return egFailValidation('eg-name', 'Vui lòng nhập Họ và tên');

    // Gender
    const gender = document.getElementById('eg-gender')?.value?.trim();
    if (!gender) return egFailValidation('eg-gender', 'Vui lòng chọn Giới tính');

    // Birth date
    const birth = document.getElementById('eg-birth')?.value?.trim();
    if (!birth) return egFailValidation('eg-birth', 'Vui lòng nhập Ngày sinh');

    // Nationality
    const nationality = document.getElementById('eg-nationality')?.value?.trim();
    if (!nationality) return egFailValidation('eg-nationality', 'Vui lòng chọn Quốc tịch');

    // Check if address section is locked (Visa/Passport)
    const staySection = document.getElementById('eg-section-address');
    const isAddressLocked = staySection && staySection.classList.contains('eg-section-locked');

    if (!isAddressLocked) {
        // Progressive normalization: bypass strict validation for trusted/raw data
        const addrState = (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.getState)
            ? PMS_ADDR.getState()
            : { isTrusted: false, isRaw: false };

        // Address validation based on mode
        const mode = document.querySelector('input[name="eg-area"]:checked')?.value || 'new';

        const province = document.getElementById('eg-province')?.value?.trim();
        if (!province) return egFailValidation('eg-province', 'Vui lòng chọn Tỉnh/Thành phố');

        // Progressive: for trusted/raw data, skip strict datalist validation
        if (!addrState.isTrusted && !addrState.isRaw) {
            if (!egValidateDatalist(document.getElementById('eg-province'))) return false;
        }

        // District validation for old mode
        if (mode === 'old') {
            const district = document.getElementById('eg-district')?.value?.trim();
            if (!district) {
                if (!addrState.isTrusted && !addrState.isRaw) {
                    return egFailValidation('eg-district', 'Vui lòng chọn Quận/Huyện');
                }
                // Trusted/Raw: warn but accept
                const distEl = document.getElementById('eg-district');
                if (distEl) distEl.classList.add('is-warning');
            } else if (!addrState.isTrusted && !addrState.isRaw) {
                egValidateDatalist(document.getElementById('eg-district'));
            }
        }

        const ward = document.getElementById('eg-ward')?.value?.trim();
        if (!ward) {
            if (!addrState.isTrusted && !addrState.isRaw) {
                return egFailValidation('eg-ward', 'Vui lòng chọn Phường/Xã');
            }
            // Trusted/Raw: warn but accept
            const wardEl = document.getElementById('eg-ward');
            if (wardEl) wardEl.classList.add('is-warning');
        } else if (!addrState.isTrusted && !addrState.isRaw) {
            egValidateDatalist(document.getElementById('eg-ward'));
        }

        const address = document.getElementById('eg-address')?.value?.trim();
        if (!address) return egFailValidation('eg-address', 'Vui lòng nhập Địa chỉ chi tiết');
    }

    return true;
}

// ─── Save guest ───────────────────────────────────────────────────────────────
async function egSaveGuest() {
    if (!egValidateForm()) return;

    const guestId = _egGuestId;
    if (!guestId) { pmsToast('Thiếu ID khách', false); return; }

    const btn = document.getElementById('eg-save-btn');
    let oriText = 'Lưu thay đổi';
    if (btn) {
        oriText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" style="margin-right:8px;" role="status" aria-hidden="true"></span> Đang xử lý...`;
        btn.style.opacity = '0.7';
    }

    try {
        // Get address mode
        const mode = document.querySelector('input[name="eg-area"]:checked')?.value || 'new';
        const province = document.getElementById('eg-province')?.value?.trim() || '';
        const district = document.getElementById('eg-district')?.value?.trim() || '';
        const ward = document.getElementById('eg-ward')?.value?.trim() || '';
        const newProvince = document.getElementById('eg-new-province')?.value?.trim() || '';
        const newWard = document.getElementById('eg-new-ward')?.value?.trim() || '';

        // Check if address section is locked
        const staySection = document.getElementById('eg-section-address');
        const isAddressLocked = staySection && staySection.classList.contains('eg-section-locked');

        const fd = new FormData();
        fd.append('full_name', document.getElementById('eg-name')?.value?.trim() || '');
        fd.append('gender', document.getElementById('eg-gender')?.value?.trim() || '');
        fd.append('birth_date', document.getElementById('eg-birth')?.value?.trim() || '');
        fd.append('nationality', document.getElementById('eg-nationality')?.value?.trim() || 'VNM - Việt Nam');
        fd.append('phone', document.getElementById('eg-phone')?.value?.trim() || '');
        fd.append('id_expire', document.getElementById('eg-id-expire')?.value?.trim() || '');
        fd.append('notes', document.getElementById('eg-notes')?.value?.trim() || '');

        // Address fields (only if not locked)
        if (isAddressLocked) {
            // Visa/Passport - clear address fields
            fd.append('address_type', 'new');
            fd.append('city', '');
            fd.append('ward', '');
            fd.append('district', '');
            fd.append('address', '');
            fd.append('old_city', '');
            fd.append('old_district', '');
            fd.append('old_ward', '');
        } else {
            fd.append('address_type', mode);
            fd.append('address', document.getElementById('eg-address')?.value?.trim() || '');
            if (mode === 'old') {
                // Old mode: province/district/ward = old values, new_* = converted values
                fd.append('old_city', province);
                fd.append('old_district', district);
                fd.append('old_ward', ward);
                fd.append('city', newProvince || province);
                fd.append('ward', newWard || ward);
                fd.append('district', '');
                if (newProvince) fd.append('new_city', newProvince);
                if (newWard) fd.append('new_ward', newWard);
            } else {
                // New mode
                fd.append('city', province);
                fd.append('ward', ward);
                fd.append('district', '');
                fd.append('old_city', '');
                fd.append('old_district', '');
                fd.append('old_ward', '');
            }
        }

        // ID fields NOT included — they are locked

        const stayId = _egStayId;
        await pmsApi(`/api/pms/guests/${guestId}`, { method: 'PUT', body: fd });

        // Reload room detail
        const roomNum = document.getElementById('rd-room-num')?.textContent || '';
        if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(null, roomNum);
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
        if (typeof openRoomDetail === 'function') openRoomDetail(parseInt(stayId), roomNum);

        pmsToast('Cập nhật thông tin khách thành công', true);

        if (typeof closeModal === 'function') closeModal('egModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('egModal');
        else document.getElementById('egModal')?.classList.remove('show');

    } catch (e) {
        console.error('[egSaveGuest] Error:', e);
        pmsToast(e.message || 'Lỗi khi cập nhật khách', false);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = oriText;
            btn.style.opacity = '1';
        }
    }
}
window.egSaveGuest = egSaveGuest;

// ─── Global exports ────────────────────────────────────────────────────────────
window.egOnProvinceChange = egOnProvinceChange;
window.egValidateDatalist = egValidateDatalist;
window.egFormatCapitalize = egFormatCapitalize;
window.egFormatSentence = egFormatSentence;
window.egFormatBasicNumeric = egFormatBasicNumeric;
window.egCheckIdExpire = egCheckIdExpire;
window.egCheckBirth = egCheckBirth;
window.egSwitchMode = egSwitchMode;
window.egToggleIdFields = egToggleIdFields;
