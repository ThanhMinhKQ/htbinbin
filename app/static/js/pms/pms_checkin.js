// static/js/pms/pms_checkin.js
// PMS Check-in - Check-in modal, guest management, price calculation
'use strict';

let pmsCi = {};
let pmsCiRoomNumber = null;
let pmsCiGuestList = [];
let pmsCiMaxGuests = 2;

function openCI(id) {
    const r = PMS.roomMap[id]; if (!r) return;
    pmsCi = r;
    pmsCiRoomNumber = r.room_number;
    pmsCiMaxGuests = r.max_guests || 2;
    pmsCiGuestList = [];
    window._ciRoomNumber = r.room_number;
    document.getElementById('ci-room-id').value = id;
    document.getElementById('ci-title').textContent = 'Nhận phòng nhanh';
    document.getElementById('ci-sub').textContent = `Phòng ${r.room_number} | ${r.room_type_name || '—'} | Tối đa ${pmsCiMaxGuests} khách`;
    const opt = document.getElementById('ci-room-type-opt');
    if (opt) { opt.textContent = r.room_type_name || '—'; opt.value = r.room_type_id || ''; }
    const rn = document.getElementById('ci-room-num');
    if (rn) rn.value = r.room_number || '';

    // Initialize Flatpickr datetime pickers
    pmsCiInitFlatpickr();

    document.getElementById('ci-deposit').value = '0';
    document.getElementById('ci-notes').value = '';
    document.getElementById('ci-price').textContent = '0';
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    document.getElementById('ci-guest-list-panel').classList.remove('show');
    document.getElementById('ci-capacity-warn').classList.remove('show');
    // Initialize dynamic datalists
    if (typeof pmsPopulateNationalities === 'function') pmsPopulateNationalities('dl-nationality');
    if (typeof vnInitAddressFields === 'function') vnInitAddressFields();
    if (typeof openModal === 'function') openModal('ciModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('ciModal');
    else document.getElementById('ciModal').classList.add('show');
}

// ─────────────────────────────────────────────────────────────────────────────
// Time input Initialization
// ─────────────────────────────────────────────────────────────────────────────

function pmsCiInitFlatpickr() {
    const ciInEl = document.getElementById('ci-in');
    const ciOutEl = document.getElementById('ci-out');

    if (ciInEl) {
        const now = new Date();
        const tzOffset = now.getTimezoneOffset() * 60000; // offset in milliseconds
        const localISOTime = (new Date(now.getTime() - tzOffset)).toISOString().slice(0, 16);
        ciInEl.value = localISOTime;
    }
    if (ciOutEl) ciOutEl.value = '';

    if (typeof pmsCalcPrice === 'function') setTimeout(pmsCalcPrice, 100);
}

function pmsCiGetFormGuest() {
    // Get invoice info
    const invoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    const taxCode = invoiceVal === '1' ? (document.getElementById('ci-tax-code')?.value?.trim() || '') : '';
    const invoiceContact = invoiceVal === '1' ? (document.getElementById('ci-tax-contact')?.value?.trim() || '') : '';

    // address_type drives which fields feed the submission
    // ── OLD mode: ci-province/ci-district/ci-ward hold OLD values;
    //              ci-new-province/ci-new-ward hold the READONLY converted new values.
    // ── NEW mode: ci-province/ci-ward hold NEW values; ci-new-* are empty.
    const addrType = document.querySelector('input[name="ci-area"]:checked')?.value || 'new';
    const _city = document.getElementById('ci-province')?.value?.trim() || '';
    const _ward = document.getElementById('ci-ward')?.value?.trim() || '';
    const _dist = addrType === 'old'
        ? (document.getElementById('ci-district')?.value?.trim() || '')
        : (document.getElementById('ci-district')?.value?.trim() || '');
    const _newCity = addrType === 'old'
        ? (document.getElementById('ci-new-province')?.value?.trim() || '')
        : _city;
    const _newWard = addrType === 'old'
        ? (document.getElementById('ci-new-ward')?.value?.trim() || '')
        : _ward;

    return {
        // Include guest id when autofilling an existing guest
        ...(window._pmsCiExistingGuestId ? { id: window._pmsCiExistingGuestId } : {}),
        full_name: document.getElementById('ci-name')?.value?.trim() || '',
        id_type: document.getElementById('ci-id-type')?.value || 'cccd',
        cccd: document.getElementById('ci-cccd')?.value?.trim() || '',
        id_expire: document.getElementById('ci-id-expire')?.value || '',
        gender: document.getElementById('ci-gender')?.value || '',
        birth_date: document.getElementById('ci-birth')?.value || '',
        phone: document.getElementById('ci-phone')?.value?.trim() || '',
        vehicle: document.getElementById('ci-vehicle')?.value?.trim() || '',
        // city/ward = what user typed (OLD values in old-mode; NEW values in new-mode)
        city: _city,
        district: _dist,
        ward: _ward,
        address: document.getElementById('ci-address')?.value?.trim() || '',
        address_type: addrType,
        // new_city/new_ward = post-reform values (from readonly conversion display)
        new_city: _newCity,
        new_ward: _newWard,
        // old_* = explicitly typed OLD values (only in old-mode)
        old_city: addrType === 'old' ? _city : null,
        old_district: addrType === 'old' ? _dist : null,
        old_ward: addrType === 'old' ? _ward : null,
        nationality: document.getElementById('ci-nationality')?.value?.trim() || 'VNM - Việt Nam',
        notes: document.getElementById('ci-guest-notes')?.value?.trim() || '',
        tax_code: taxCode,
        invoice_contact: invoiceContact,
        from_old: window._pmsCiIsOldGuest || false
    };
}

function pmsCiRefreshGuestForm() {
    ['ci-name', 'ci-cccd', 'ci-id-expire', 'ci-birth', 'ci-phone', 'ci-guest-notes', 'ci-address', 'ci-province', 'ci-district', 'ci-ward', 'ci-vehicle'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.value = '';
            el.readOnly = false;
            el.classList.remove('is-invalid', 'is-warning');
        }
    });
    // Also clear readonly conversion display fields
    ['ci-new-province', 'ci-new-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.value = ''; el.style.color = ''; }
    });
    const g = document.getElementById('ci-gender');
    if (g) { g.value = ''; g.disabled = false; }

    // Reset to new-mode radio
    const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
    if (newRadio) newRadio.checked = true;
    if (oldRadio) { oldRadio.disabled = false; oldRadio.style.display = ''; }
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');
    if (distGrp) distGrp.style.display = 'none';
    if (convGrp) convGrp.style.display = 'none';

    // Reset toolbar
    document.getElementById('ci-add-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-update-guest-btn').style.display = 'none';
    document.getElementById('ci-cancel-edit-btn').style.display = 'none';
    document.getElementById('ci-refresh-btn').style.display = 'inline-flex';

    // Clear tax/invoice fields as well
    const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
    if (invoiceRadio0) {
        invoiceRadio0.checked = true;
        pmsCiToggleInvoice(invoiceRadio0);
    }
    document.getElementById('ci-tax-code').value = '';
    document.getElementById('ci-tax-contact').value = '';

    // Remove any hint and reset existing guest ID
    const hintEl = document.getElementById('ci-cccd-hint');
    if (hintEl) hintEl.remove();
    window._pmsCiExistingGuestId = null;
    window._pmsCiIsOldGuest = false;

    // Remove autofill notice
    const autofillNotice = document.getElementById('ci-autofill-notice');
    if (autofillNotice) autofillNotice.remove();

    // Remove edit address button
    const editAddrBtn = document.getElementById('ci-edit-addr-btn');
    if (editAddrBtn) editAddrBtn.remove();

    // Reset address lock state
    window._pmsCiAddressLocked = false;

    // Hide address validation warning panel
    const warnPanel = document.getElementById('ci-addr-warning-panel');
    if (warnPanel) warnPanel.style.display = 'none';

    // Remove state badge
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.clearStateBadge) {
        PMS_ADDR.clearStateBadge();
    }

    // Reset deposit classification
    const depType = document.getElementById('ci-deposit-type');
    if (depType) {
        depType.value = 'Chi nhánh';
        pmsCiOnDepositTypeChange(depType);
    }

    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) { idTypeEl.value = 'cccd'; idTypeEl.disabled = false; pmsCiToggleIdFields(idTypeEl); }
    pmsCiUnlockAllRequiredFields();
}

async function pmsCiAddGuest() {
    const idx = window._ciEditIndex;
    if (idx !== undefined && idx !== null) {
        await pmsCiUpdateGuest();
        return;
    }
    const g = pmsCiGetFormGuest();
    const v = pmsCiValidateGuestForm(g);
    if (!v.valid) { return; }

    // Check for duplicates in JS list - if found, verify DB status
    if (g.cccd && pmsCiGuestList.some(xg => xg.cccd === g.cccd)) {
        const existingGuest = pmsCiGuestList.find(xg => xg.cccd === g.cccd);
        console.log('[CI] DUPLICATE found in local list:', existingGuest);

        // Cảnh báo khách đã có trong danh sách chờ nhận phòng
        window.alert(`CẢNH BÁO: Khách với số giấy tờ ${g.cccd} đã có trong danh sách chờ nhận phòng của phòng này.\n\nVui lòng xóa khách khỏi danh sách trước hoặc chọn khách trong danh sách để chỉnh sửa.`);
        pmsToast(`Khách ${g.cccd} đã có trong danh sách chờ nhận phòng. Không thể thêm trùng.`, false);
        return;
    }

    // Real-time block for active CCCDs (for new CCCDs not in local list)
    if (g.cccd && g.cccd.length >= 3 && !pmsCiGuestList.some(xg => xg.cccd === g.cccd)) {
        try {
            const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
            console.log('[CI] Checking CCCD in DB:', g.cccd, 'URL:', url);
            const res = await pmsApi(url);
            console.log('[CI] CCCD check result:', JSON.stringify(res));

            if (res && res.is_active) {
                const currentRoom = pmsCiRoomNumber;
                console.log('[CI] CCCD is active at room:', res.room_number, 'Current room:', currentRoom);
                if (res.room_number === currentRoom) {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}. Không thể thêm trùng.`);
                    pmsToast(`Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}. Không thể thêm trùng.`, false);
                } else {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`);
                    pmsToast(`Khách hàng có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`, false);
                }
                return;
            } else {
                console.log('[CI] CCCD check: NOT active in DB');
            }
        } catch (e) {
            console.error('[CI] Error checking active CCCD', e);
            pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
            return;
        }
    }

    const total = pmsCiGuestList.length + 1;
    if (total > pmsCiMaxGuests) {
        pmsCiUpdateCapacityWarn();
    }
    pmsCiGuestList.push(g);
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
    // Tự động bật panel danh sách khách để user thấy đã thêm
    const panel = document.getElementById('ci-guest-list-panel');
    const btn = document.getElementById('ci-toggle-list-btn');
    if (panel && !panel.classList.contains('show')) {
        panel.classList.add('show');
    }
    if (btn) {
        btn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2">
              <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
            Ẩn danh sách (<span id="ci-guest-count">${pmsCiGuestList.length}</span>)
        `;
    }
}

function pmsCiRenderGuestList() {
    const panel = document.getElementById('ci-guest-list-panel');
    if (!panel) return;
    if (pmsCiGuestList.length === 0) {
        panel.innerHTML = '<p style="margin:0;font-size:13px;color:#64748b;">Chưa thêm khách nào. Nhập thông tin và bấm "Thêm khách".</p>';
        return;
    }
    panel.innerHTML = pmsCiGuestList.map((g, i) => `
        <span class="guest-chip">
          <span class="ci-chip-icon">${pmsGenderIcon(g.gender)}</span>
          <span onclick="pmsCiEditGuest(${i})" style="cursor:pointer;">${pmsEscapeHtml(g.full_name)}</span>
          <button type="button" onclick="pmsCiRemoveGuest(${i})" style="background:none;border:none;cursor:pointer;padding:0 4px;color:#94a3b8;font-size:16px;line-height:1;" title="Xóa">×</button>
        </span>
    `).join('');
}

async function pmsCiEditGuest(i) {
    const g = pmsCiGuestList[i];
    if (!g) return;

    // Store edit index first
    window._ciEditIndex = i;

    // ========== PHASE 1: Fill ALL values first ==========
    document.getElementById('ci-name').value = g.full_name || '';
    document.getElementById('ci-gender').value = g.gender || '';
    document.getElementById('ci-birth').value = g.birth_date ? String(g.birth_date).slice(0, 10) : '';
    document.getElementById('ci-phone').value = g.phone || '';
    document.getElementById('ci-cccd').value = g.cccd || '';
    document.getElementById('ci-id-type').value = g.id_type || 'cccd';
    document.getElementById('ci-id-expire').value = g.id_expire ? String(g.id_expire).slice(0, 10) : '';
    document.getElementById('ci-vehicle').value = g.vehicle || '';
    document.getElementById('ci-guest-notes').value = g.notes || '';
    document.getElementById('ci-nationality').value = g.nationality || 'VNM - Việt Nam';
    document.getElementById('ci-address').value = g.address || '';

    // Restore invoice fields (both old and new guests can have invoice)
    if (g.tax_code || g.invoice_contact) {
        const invoiceRadio1 = document.querySelector('input[name="ci-invoice"][value="1"]');
        if (invoiceRadio1) invoiceRadio1.checked = true;
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.value = g.tax_code || '';
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.value = g.invoice_contact || '';
        // Show invoice fields wrapper
        const invoiceFields = document.getElementById('ci-invoice-fields');
        if (invoiceFields) invoiceFields.style.display = 'block';
        // Call toggle to sync visibility state
        if (invoiceRadio1) pmsCiToggleInvoice(invoiceRadio1);
    } else {
        const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
        if (invoiceRadio0) invoiceRadio0.checked = true;
        const invoiceFields = document.getElementById('ci-invoice-fields');
        if (invoiceFields) invoiceFields.style.display = 'none';
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.value = '';
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.value = '';
        // Call toggle to sync visibility state
        if (invoiceRadio0) pmsCiToggleInvoice(invoiceRadio0);
    }

    // Handle address - load province/ward data and set values
    const hasOldData = !!(g.old_city || g.old_ward || g.old_district);
    const addrType = g.address_type || 'new';

    const pEl = document.getElementById('ci-province');
    const wEl = document.getElementById('ci-ward');
    const dEl = document.getElementById('ci-district');
    const nProvEl = document.getElementById('ci-new-province');
    const nWardEl = document.getElementById('ci-new-ward');
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
    const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');

    if (hasOldData) {
        // Load OLD province datalist and fill OLD datalist inputs
        if (typeof vnLoadOldProvinces === 'function') {
            const oldProvinces = await vnLoadOldProvinces();
            vnPopulateDatalist('dl-province', oldProvinces);
        }
        // Fill NEW readonly conversion display FIRST
        if (nProvEl) { nProvEl.value = g.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = g.ward || ''; nWardEl.style.color = '#15803d'; }
        // Set OLD values
        if (pEl) pEl.value = g.old_city || '';
        if (pEl && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(pEl);
        if (dEl) dEl.value = g.old_district || '';
        if (dEl && typeof vnOnDistrictChange === 'function') await vnOnDistrictChange(dEl);
        if (wEl) wEl.value = g.old_ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ward');
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
        // Set radio
        if (oldRadio) oldRadio.checked = true;
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';
    } else {
        // Load NEW province datalist
        if (typeof vnLoadNewProvinces === 'function' && typeof vnPopulateDatalist === 'function') {
            const provinces = await vnLoadNewProvinces();
            vnPopulateDatalist('dl-province', provinces.map(p => ({ name: p.name, short: p.short })));
        }
        if (pEl) pEl.value = g.city || '';
        if (pEl && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(pEl);
        if (wEl) wEl.value = g.ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ward');
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
        if (newRadio) newRadio.checked = true;
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
    }

    // ALWAYS hide conversion chip when editing from list (only appears for new manual input in old mode)
    if (convGrp) convGrp.style.display = 'none';

    pmsCiToggleIdFields(document.getElementById('ci-id-type'));

    // ========== PHASE 2: Set lock state based on guest type ==========
    if (g.from_old) {
        // OLD GUEST: Lock most fields
        window._pmsCiIsOldGuest = true;
        window._pmsCiExistingGuestId = g.id || null;

        // Lock ALL fields
        pmsCiLockAllFields();

        // Unlock specific editable fields only
        const unlockFields = ['ci-phone', 'ci-guest-notes', 'ci-id-expire', 'ci-vehicle'];
        unlockFields.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.readOnly = false;
        });

        // Unlock invoice fields
        const invoiceRadios = document.querySelectorAll('input[name="ci-invoice"]');
        invoiceRadios.forEach(r => r.disabled = false);
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.readOnly = false;
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.readOnly = false;

        // Lock address inputs (they're already locked by pmsCiLockAllFields)
        [pEl, dEl, wEl].forEach(el => {
            if (el) el.readOnly = true;
        });

        // Show autofill notice
        pmsCiShowAutofillNotice(g.full_name, g.cccd);
    } else {
        // NEW GUEST: Unlock all fields
        window._pmsCiIsOldGuest = false;
        window._pmsCiExistingGuestId = null;
        pmsCiUnlockAllFields();

        // Remove autofill notice
        const existingNotice = document.getElementById('ci-autofill-notice');
        if (existingNotice) existingNotice.remove();
    }

    // Show/hide buttons
    document.getElementById('ci-add-guest-btn').style.display = 'none';
    document.getElementById('ci-update-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-cancel-edit-btn').style.display = 'inline-flex';
    document.getElementById('ci-refresh-btn').style.display = 'none';

    pmsToast('Đang chỉnh sửa khách. Bấm "Cập nhật" để lưu.');
}

function pmsCiCancelEdit() {
    window._ciEditIndex = null;
    pmsCiRefreshGuestForm();
    document.getElementById('ci-add-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-update-guest-btn').style.display = 'none';
    document.getElementById('ci-cancel-edit-btn').style.display = 'none';
    document.getElementById('ci-refresh-btn').style.display = 'inline-flex';
}

async function pmsCiUpdateGuest() {
    const idx = window._ciEditIndex;
    if (idx === undefined || idx === null || idx < 0 || idx >= pmsCiGuestList.length) {
        pmsToast('Không tìm thấy khách cần cập nhật', false);
        return;
    }
    const g = pmsCiGetFormGuest();
    if (!window.confirm(`Cập nhật thông tin khách "${g.full_name}"?`)) return;
    const v = pmsCiValidateGuestForm(g);
    if (!v.valid) { return; }

    // Check for duplicates in JS list
    if (g.cccd && pmsCiGuestList.some((xg, i) => i !== idx && xg.cccd === g.cccd)) {
        window.alert(`CẢNH BÁO: Số giấy tờ ${g.cccd} đã có trong danh sách khách chờ nhận phòng.\n\nVui lòng chọn khách khác hoặc xóa khách trùng lặp.`);
        pmsToast(`Số giấy tờ ${g.cccd} đã có trong danh sách. Không thể cập nhật trùng.`, false);
        return;
    }

    // Real-time block for active CCCDs
    if (g.cccd && g.cccd.length >= 3) {
        try {
            const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
            const res = await pmsApi(url);
            if (res && res.is_active) {
                const currentRoom = pmsCiRoomNumber;
                if (res.room_number === currentRoom) {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}. Không thể thêm trùng.`);
                    pmsToast(`Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}. Không thể thêm trùng.`, false);
                } else {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể Cập nhật.`);
                    pmsToast(`Khách hàng có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể Cập nhật.`, false);
                }
                return;
            }
        } catch (e) {
            console.error('Error checking active CCCD', e);
            pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
            return;
        }
    }
    pmsCiGuestList[idx] = g;
    window._ciEditIndex = null;
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
    pmsToast('Đã cập nhật thông tin khách');
}

function pmsCiRemoveGuest(i) {
    pmsCiGuestList.splice(i, 1);
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
}

function pmsCiUpdateGuestCount() {
    const el = document.getElementById('ci-guest-count');
    if (el) el.textContent = String(pmsCiGuestList.length);
}

function pmsCiUpdateCapacityWarn() {
    const primary = pmsCiGetFormGuest().full_name ? 1 : 0;
    const total = pmsCiGuestList.length + primary;
    const warnEl = document.getElementById('ci-capacity-warn');
    if (!warnEl) return;
    if (total > pmsCiMaxGuests) {
        warnEl.textContent = `Số khách (${total}) vượt quá giới hạn phòng (tối đa ${pmsCiMaxGuests} người). Vui lòng giảm số lượng khách hoặc chọn phòng khác.`;
        warnEl.classList.add('show');
    } else {
        warnEl.classList.remove('show');
    }
}

function pmsCiScanCode() {
    openScanModal(async (parsed) => {
        await pmsCiFillFromScan(parsed);
        pmsToast(`Đã quét: ${parsed.name}`, true);
    });
}

// ─── Fill checkin form from parsed CCCD scan data ──────────────────────────────
async function pmsCiFillFromScan(parsed) {
    if (!parsed.is_valid) return;

    const cccdEl  = document.getElementById('ci-cccd');
    const idTypeEl = document.getElementById('ci-id-type');
    const expireEl  = document.getElementById('ci-id-expire');
    const nameEl    = document.getElementById('ci-name');
    const genderEl  = document.getElementById('ci-gender');
    const birthEl   = document.getElementById('ci-birth');

    // id_number = CCCD 12 số | old_id = CMND 9 số | backward compat: 'cccd'
    // Chỉ dùng old_id khi card_type = 'CMND' (CMND thật sự), không dùng cho CCCD/Căn cước
    const isCmnd = parsed.card_type === 'CMND';
    const idValue = isCmnd
        ? (parsed.old_id || parsed.id_number || parsed.cccd || '')
        : (parsed.id_number || parsed.cccd || '');
    if (cccdEl) {
        cccdEl.value = idValue;
        cccdEl.classList.remove('is-invalid');
    }
    // card_type: "CCCD_CU" | "CAN_CUOC_MOI" | "CMND"
    if (idTypeEl) {
        idTypeEl.value = isCmnd ? 'cmnd' : 'cccd';
        pmsCiToggleIdFields(idTypeEl);
    }
    if (expireEl && parsed.expiry_date && parsed.expiry_date !== 'Không thời hạn') {
        expireEl.value = pmsScanDateToISO(parsed.expiry_date);
        pmsCiCheckIdExpire(expireEl);
    }
    if (nameEl) {
        nameEl.value = pmsTitleCase(parsed.name || '');
        nameEl.classList.remove('is-invalid');
    }
    if (genderEl && parsed.gender) {
        genderEl.value = parsed.gender;
    }
    if (birthEl && parsed.dob) {
        birthEl.value = pmsScanDateToISO(parsed.dob);
        pmsCiCheckBirth(birthEl);
    }

    // ── Address matching: switch mode + fill fields based on card_type ──
    const cardType = parsed.card_type || 'CCCD_CU';
    if (typeof pmsMatchAddressToForm === 'function') {
        await pmsMatchAddressToForm(parsed.address, 'ci', cardType);
    }

    // ── Validate address fields after scan ──
    // Show warning if any address field is not in datalist
    setTimeout(() => {
        if (typeof pmsShowAddressValidationIssues === 'function') {
            pmsShowAddressValidationIssues('ci');
        }
    }, 100);

    const phoneEl = document.getElementById('ci-phone');
    if (phoneEl) phoneEl.focus();
}

window.pmsCiFillFromScan = pmsCiFillFromScan;
window.pmsCiScanCode = pmsCiScanCode;

function pmsCiToggleGuestList() {
    if (pmsCiGuestList.length === 0) {
        alert('Danh sách khách đang trống!');
        return;
    }
    const panel = document.getElementById('ci-guest-list-panel');
    const btn = document.getElementById('ci-toggle-list-btn');
    if (panel) {
        panel.classList.toggle('show');
        if (btn) {
            const isShown = panel.classList.contains('show');
            btn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="2">
                  <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
                  <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
                </svg>
                ${isShown ? 'Ẩn danh sách' : 'Hiện danh sách'} (<span id="ci-guest-count">${pmsCiGuestList.length}</span>)
            `;
        }
    }
}

function pmsCalcPrice() {
    const ciV = document.getElementById('ci-in')?.value;
    const coV = document.getElementById('ci-out')?.value;
    const st = coV ? 'night' : 'hour';
    const el = document.getElementById('ci-price'); if (!el) return;
    if (!ciV || !coV) { el.textContent = '0'; return; }
    const ms = new Date(coV) - new Date(ciV); if (ms <= 0) { el.textContent = '0'; return; }

    let p = 0;
    if (st === 'hour') {
        const hours = Math.max(pmsCi.min_hours || 1, Math.ceil(ms / 3600000));
        p = (pmsCi.price_per_hour || 0) * (pmsCi.min_hours || 1) + (pmsCi.price_next_hour || 0) * Math.max(0, hours - (pmsCi.min_hours || 1));
    } else {
        const nights = Math.max(1, Math.ceil(ms / 86400000));
        let ppN = pmsCi.price_per_night || 0;

        if (pmsCi.promo_start_time && pmsCi.promo_end_time && (pmsCi.promo_discount_percent || 0) > 0) {
            const timeStr = ciV.split('T')[1].substring(0, 5);
            const startStr = pmsCi.promo_start_time.substring(0, 5);
            const endStr = pmsCi.promo_end_time.substring(0, 5);
            let isPromo = false;
            if (startStr <= endStr) { if (startStr <= timeStr && timeStr <= endStr) isPromo = true; }
            else { if (timeStr >= startStr || timeStr <= endStr) isPromo = true; }
            if (isPromo) ppN = ppN * (1 - pmsCi.promo_discount_percent / 100);
        }
        p = ppN * nights;
    }
    el.textContent = pmsMoney(p);
}

async function submitCI() {
    console.log('[CI SUBMIT] ===== START submitCI =====');
    
    try {
    // Check-in Time is required
    const ciAt = document.getElementById('ci-in').value;
    if (!ciAt) { pmsToast('Vui lòng chọn Thời gian nhận phòng', false); return; }

    // Address validation is handled inside pmsCiValidateGuestForm() below

    const formGuest = pmsCiGetFormGuest();
    const hasFormGuest = !!formGuest.full_name;
    const allGuests = [...pmsCiGuestList];

    console.log('[CI SUBMIT] formGuest:', JSON.stringify(formGuest));
    console.log('[CI SUBMIT] hasFormGuest:', hasFormGuest);
    console.log('[CI SUBMIT] pmsCiGuestList length:', pmsCiGuestList.length);
    console.log('[CI SUBMIT] pmsCiGuestList:', JSON.stringify(pmsCiGuestList.map(g => ({ name: g.full_name, cccd: g.cccd }))));

    // ─── VALIDATION: Stay Type & Time ───
    const stayType = document.getElementById('ci-type')?.value;
    const coVal = document.getElementById('ci-out')?.value;
    if (stayType === 'NIGHT' && !coVal) {
        pmsToast('Vui lòng chọn Ngày trả phòng dự kiến cho thuê Qua đêm.', false);
        const coEl = document.getElementById('ci-out');
        if (coEl) { coEl.classList.add('is-invalid'); coEl.focus(); }
        return;
    }

    // ─── TRƯỜNG HỢP 1: Có thông tin khách đang nhập trên form ───
    if (hasFormGuest) {
        console.log('[CI SUBMIT] Processing form guest (hasFormGuest = true)');

        console.log('[CI SUBMIT] Calling pmsCiValidateGuestForm...');
        const v = pmsCiValidateGuestForm(formGuest);
        if (!v.valid) { return; }

        // Check if this guest is already in pmsCiGuestList (prevent duplicates)
        const formCccd = (formGuest.cccd || '').trim().toUpperCase();
        console.log('[CI SUBMIT] formCccd:', formCccd);
        console.log('[CI SUBMIT] pmsCiGuestList:', JSON.stringify(pmsCiGuestList.map(g => ({ cccd: (g.cccd || '').trim().toUpperCase() }))));

        if (formCccd) {
            const foundIndex = pmsCiGuestList.findIndex(xg => (xg.cccd || '').trim().toUpperCase() === formCccd);
            console.log('[CI SUBMIT] foundIndex:', foundIndex);
            if (foundIndex !== -1) {
                console.log('[CI SUBMIT] DUPLICATE FOUND - Showing alert');
                window.alert(`CẢNH BÁO: Khách với số giấy tờ ${formGuest.cccd} đã có trong danh sách chờ nhận phòng.\n\nVui lòng xóa khách khỏi danh sách trước khi nhận phòng, hoặc chọn khách trong danh sách để chỉnh sửa.`);
                pmsToast(`Khách ${formGuest.cccd} đã có trong danh sách chờ. Vui lòng xóa trước khi nhận phòng.`, false);
                return;
            }
        }
        console.log('[CI SUBMIT] No duplicate found in local list');

        // Real-time block for active CCCDs for primary guest
        if (formGuest.cccd && formGuest.cccd.length >= 3) {
            console.log('[CI SUBMIT] Checking active CCCD in database...');
            try {
                const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(formGuest.cccd)}`;
                const res = await pmsApi(url);
                console.log('[CI SUBMIT] Active CCCD check result:', res);
                if (res && res.is_active) {
                    const currentRoom = pmsCiRoomNumber;
                    if (res.room_number === currentRoom) {
                        window.alert(`CẢNH BÁO: Khách ${formGuest.cccd} đã có trong danh sách phòng ${currentRoom}. Không thể nhận phòng trùng.`);
                        pmsToast(`Khách ${formGuest.cccd} đã có trong danh sách phòng ${currentRoom}. Không thể nhận phòng trùng.`, false);
                    } else {
                        window.alert(`CẢNH BÁO: Khách ${formGuest.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể nhận phòng.`);
                        pmsToast(`Khách hàng có số giấy tờ ${formGuest.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể nhận phòng.`, false);
                    }
                    return;
                }
            } catch (e) {
                console.error('Error checking active CCCD', e);
                pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
                return;
            }
        }

        // Thêm form guest làm primary vào đầu danh sách
        allGuests.unshift(formGuest);
        console.log('[CI SUBMIT] Added form guest to list, allGuests length:', allGuests.length);
    }
    
    // ─── TRƯỜNG HỢP 2: Form trống hoàn toàn ───
    // Khi form không có full_name và danh sách trống, kiểm tra các required fields để báo lỗi cụ thể
    // Thứ tự: Số giấy tờ -> Loại giấy tờ -> Ngày hết hạn -> Họ và tên -> Giới tính -> Ngày sinh -> Quốc tịch -> Địa chỉ
    if (!hasFormGuest && pmsCiGuestList.length === 0) {
        const cccdEl = document.getElementById('ci-cccd');
        const idTypeEl = document.getElementById('ci-id-type');
        const idExpireEl = document.getElementById('ci-id-expire');
        const nameEl = document.getElementById('ci-name');
        const genderEl = document.getElementById('ci-gender');
        const birthEl = document.getElementById('ci-birth');
        const natEl = document.getElementById('ci-nationality');

        // 1. Số giấy tờ
        if (!cccdEl?.value.trim()) {
            cccdEl?.classList.add('is-invalid');
            cccdEl?.focus();
            window.alert('Vui lòng nhập Số giấy tờ');
            return;
        }
        // 2. Loại giấy tờ
        if (!idTypeEl?.value) {
            idTypeEl?.classList.add('is-invalid');
            idTypeEl?.focus();
            window.alert('Vui lòng chọn Loại giấy tờ');
            return;
        }
        // 3. Ngày hết hạn (chỉ kiểm tra nếu giấy tờ có hạn)
        const idType = idTypeEl?.value || 'cccd';
        const noExpire = idType === 'cmnd' || idType === 'gplx';
        if (!noExpire && !idExpireEl?.value) {
            idExpireEl?.classList.add('is-invalid');
            idExpireEl?.focus();
            window.alert('Vui lòng nhập Ngày hết hạn giấy tờ');
            return;
        }
        // 4. Họ và tên
        if (!nameEl?.value.trim()) {
            nameEl?.classList.add('is-invalid');
            nameEl?.focus();
            window.alert('Vui lòng nhập Họ và tên');
            return;
        }
        // 5. Giới tính
        if (!genderEl?.value) {
            genderEl?.classList.add('is-invalid');
            genderEl?.focus();
            window.alert('Vui lòng chọn Giới tính');
            return;
        }
        // 6. Ngày sinh
        if (!birthEl?.value) {
            birthEl?.classList.add('is-invalid');
            birthEl?.focus();
            window.alert('Vui lòng nhập Ngày sinh');
            return;
        }
        // 7. Quốc tịch
        if (!natEl?.value.trim()) {
            natEl?.classList.add('is-invalid');
            natEl?.focus();
            window.alert('Vui lòng chọn Quốc tịch');
            return;
        }
        // 8. Địa chỉ (chỉ kiểm tra nếu KHÔNG phải Passport/Visa và KHÔNG phải khách cũ auto-fill)
        const isForeign = idType === 'passport' || idType === 'visa';
        const isOldGuest = window._pmsCiIsOldGuest === true;
        if (!isForeign && !isOldGuest) {
            const provEl = document.getElementById('ci-province');
            const wardEl = document.getElementById('ci-ward');
            const addrEl = document.getElementById('ci-address');
            
            // Kiểm tra Tỉnh/TP - phải có giá trị
            if (!provEl?.value.trim()) {
                provEl?.classList.add('is-invalid');
                provEl?.focus();
                window.alert('Vui lòng chọn Tỉnh/Thành phố');
                return;
            }
            // Kiểm tra Tỉnh/TP có trong datalist không
            if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-province', provEl.value)) {
                provEl.classList.add('is-invalid');
                provEl.focus();
                window.alert(`"${provEl.value}" không có trong danh sách!\n\nVui lòng chọn Tỉnh/Thành phố từ danh sách gợi ý.`);
                return;
            }
            
            // Kiểm tra Phường/Xã - phải có giá trị
            if (!wardEl?.value.trim()) {
                wardEl?.classList.add('is-invalid');
                wardEl?.focus();
                window.alert('Vui lòng chọn Phường/Xã');
                return;
            }
            // Kiểm tra Phường/Xã có trong datalist không
            if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-ward', wardEl.value)) {
                wardEl.classList.add('is-invalid');
                wardEl.focus();
                window.alert(`"${wardEl.value}" không có trong danh sách!\n\nVui lòng chọn Phường/Xã từ danh sách gợi ý.`);
                return;
            }
            
            if (!addrEl?.value.trim()) {
                addrEl?.classList.add('is-invalid');
                addrEl?.focus();
                window.alert('Vui lòng nhập Địa chỉ chi tiết');
                return;
            }
        }
    }

    // ─── TRƯỜNG HỢP 3: Có CCCD/phone/id_type nhưng không có tên ───
    else if (formGuest.cccd || formGuest.phone || formGuest.address || formGuest.birth_date || (formGuest.id_type && formGuest.id_type !== 'cccd')) {
        console.log('[CI SUBMIT] TRƯỜNG HỢP 3 triggered - has data but checking...');
        console.log('[CI SUBMIT] formGuest.full_name:', formGuest.full_name);
        if (!formGuest.full_name) {
            pmsToast('Vui lòng nhập đầy đủ thông tin khách (Họ tên, CCCD, ngày sinh...) hoặc xoá các trường đã nhập.', false);
            const nameEl = document.getElementById('ci-name');
            if (nameEl) { nameEl.classList.add('is-invalid'); nameEl.focus(); }
            return;
        }
        console.log('[CI SUBMIT] TRƯỜNG HỢP 3 - formGuest has full_name, continuing...');
    }

    // ─── KIỂM TRA: Cần ít nhất 1 khách ───
    if (allGuests.length === 0) {
        pmsToast('Vui lòng nhập thông tin khách hàng và bấm "Nhận phòng" để tiếp tục.', false);
        return;
    }

    // ─── KIỂM TRA SỐ KHÁCH VƯỢT QUÁ ───
    if (allGuests.length > pmsCiMaxGuests) {
        pmsCiUpdateCapacityWarn();
    }

    // ─── KIỂM TRA TRÙNG CCCD TRONG DANH SÁCH ───
    const cccdMap = {};
    for (let i = 0; i < allGuests.length; i++) {
        const guest = allGuests[i];
        if (guest.cccd && guest.cccd.length >= 3) {
            const up = (guest.cccd || '').trim().toUpperCase();
            if (!cccdMap[up]) cccdMap[up] = [];
            cccdMap[up].push(i);
        }
    }
    // Check for duplicates in the combined list
    for (const cccd in cccdMap) {
        if (cccdMap[cccd].length > 1) {
            const indices = cccdMap[cccd];
            const names = indices.map(i => `"${allGuests[i].full_name}"`).join(', ');
            window.alert(`CẢNH BÁO: Số giấy tờ ${cccd} bị trùng lặp trong danh sách khách (${indices.length} lần): ${names}.\n\nVui lòng xóa bớt các khách trùng lặp.`);
            pmsToast(`Số giấy tờ ${cccd} bị trùng lặp ${indices.length} lần trong danh sách. Vui lòng xóa bớt.`, false);
            return;
        }
    }

    // ─── VALIDATE ALL GUESTS IN LIST ───
    for (let i = 0; i < allGuests.length; i++) {
        const g = allGuests[i];
        if (!g.full_name || !g.cccd || !g.gender || !g.birth_date) {
            const guestName = g.full_name || `Khách thứ ${i + 1}`;
            window.alert(`Thông tin khách "${guestName}" chưa đầy đủ (Thiếu Họ tên, Số giấy tờ, Giới tính hoặc Ngày sinh). Vui lòng kiểm tra lại.`);
            pmsToast(`Khách "${guestName}" thiếu thông tin bắt buộc.`, false);
            
            // Try to focus the guest for user to fix
            if (i === 0 && hasFormGuest) {
                 document.getElementById('ci-name')?.focus();
            } else {
                 const listIdx = hasFormGuest ? i - 1 : i;
                 if (typeof pmsCiEditGuest === 'function') pmsCiEditGuest(listIdx);
                 else pmsToast('Vui lòng chọn khách trong danh sách để bổ sung thông tin.', false);
            }
            return;
        }
    }

    const submitBtn = document.querySelector('button[onclick="submitCI()"]');
    let oriText = 'Nhận phòng';
    if (submitBtn) {
        oriText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" style="margin-right:8px;" role="status" aria-hidden="true"></span> Đang xử lý...';
        submitBtn.style.opacity = '0.7';
    }

    const primary = allGuests[0];
    const fd = new FormData();
    const coV = document.getElementById('ci-out').value || '';
    fd.append('room_id', document.getElementById('ci-room-id').value);
    fd.append('stay_type', coV ? 'NIGHT' : 'HOUR');
    fd.append('check_in_at', document.getElementById('ci-in').value);
    const co_val = document.getElementById('ci-out').value;
    if (co_val) fd.append('check_out_at', co_val);

    // Deposit handling: remove dots/commas
    const rawDeposit = document.getElementById('ci-deposit').value || '0';
    const depositNum = rawDeposit.toString().replace(/[^0-9]/g, '');
    fd.append('deposit', depositNum);

    const depositType = document.getElementById('ci-deposit-type')?.value || 'Chi nhánh';
    fd.append('deposit_type', depositType);

    let meta = {};
    if (depositType === 'Công ty') {
        meta.beneficiary = document.getElementById('ci-deposit-beneficiary')?.value || '';
    } else if (depositType === 'OTA') {
        meta.ota_channel = document.getElementById('ci-deposit-ota')?.value || '';
    } else if (depositType === 'UNC') {
        meta.invoice_code = document.getElementById('ci-deposit-invoice')?.value || '';
    }
    fd.append('deposit_meta', JSON.stringify(meta));

    fd.append('notes', document.getElementById('ci-notes').value || '');

    // Invoice handling
    const invoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    fd.append('require_invoice', invoiceVal === '1' ? 'true' : 'false');
    if (invoiceVal === '1') {
        const tax_code = document.getElementById('ci-tax-code')?.value?.trim() || '';
        const tax_contact = document.getElementById('ci-tax-contact')?.value?.trim() || '';
        if (!tax_code || !tax_contact) {
            alert("Vui lòng nhập Mã số thuế và Liên hệ gửi hoá đơn!");
            return;
        }
        fd.append('tax_code', tax_code);
        fd.append('tax_contact', tax_contact);
    }

    // ── Get full guest data for primary guest ──
    // If form has guest from autofill preview, get data from form
    // Guest from list may be incomplete (only full_name + cccd)
    let guestData = primary;
    if (hasFormGuest && window._pmsCiIsOldGuest) {
        // Guest from autofill preview - get full data from form
        guestData = pmsCiGetFormGuest();
        // Preserve the guest_id if it was set during autofill
        if (window._pmsCiExistingGuestId) {
            guestData.id = window._pmsCiExistingGuestId;
        }
    }

    // Use guestData (from form) with fallback to primary (from list)
    const getGuest = (field, fallback = '') => guestData[field] || primary[field] || fallback;

    fd.append('guest_name', getGuest('full_name'));
    fd.append('guest_cccd', getGuest('cccd'));
    fd.append('guest_id_expire', getGuest('id_expire'));
    fd.append('guest_gender', getGuest('gender'));
    fd.append('guest_birth', getGuest('birth_date'));
    fd.append('guest_phone', getGuest('phone'));
    fd.append('guest_nationality', getGuest('nationality', 'VNM - Việt Nam'));

    // Send existing guest ID if found (for auto-update)
    if (window._pmsCiExistingGuestId) {
        fd.append('guest_id', window._pmsCiExistingGuestId);
    }

    // Address fields
    fd.append('vehicle', getGuest('vehicle'));
    fd.append('city', getGuest('city'));
    fd.append('district', getGuest('district'));
    fd.append('ward', getGuest('ward'));
    fd.append('address', getGuest('address'));
    fd.append('address_type', getGuest('address_type', 'new'));
    fd.append('new_city', getGuest('new_city', ''));
    fd.append('new_ward', getGuest('new_ward', ''));
    if (getGuest('old_city')) fd.append('old_city', getGuest('old_city'));
    if (getGuest('old_district')) fd.append('old_district', getGuest('old_district'));
    if (getGuest('old_ward')) fd.append('old_ward', getGuest('old_ward'));
    fd.append('guest_notes', getGuest('notes', ''));
    fd.append('guest_id_type', getGuest('id_type', 'cccd'));
    const extra = allGuests.slice(1);
    if (extra.length) fd.append('extra_guests', JSON.stringify(extra));
    try {
        console.log('[CI SUBMIT] Calling API /api/pms/checkin...');
        const r = await pmsApi('/api/pms/checkin', { method: 'POST', body: fd });
        console.log('[CI SUBMIT] API Success:', JSON.stringify(r));
        if (typeof closeModal === 'function') closeModal('ciModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('ciModal');
        else document.getElementById('ciModal').classList.remove('show');
        pmsToast(r.message);

        const roomId = document.getElementById('ci-room-id')?.value;
        if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(roomId);
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
    } catch (e) {
        console.error('[CI SUBMIT] API Error:', e);
        pmsToast(e.message, false);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = oriText;
            submitBtn.style.opacity = '1';
        }
    }
    } catch (outerError) {
        console.error('[CI SUBMIT] OUTER ERROR:', outerError);
        pmsToast('Lỗi: ' + outerError.message, false);
    }
}

// Export globally
window.openCI = openCI;
window.submitCI = submitCI;
window.pmsCalcPrice = pmsCalcPrice;
window.vnValidateDatalist = vnValidateDatalist;
window.vnValidateAddressFields = vnValidateAddressFields;

// Export ci- functions for HTML onclick handlers
window.ciRefreshGuestForm = pmsCiRefreshGuestForm;
window.ciAddGuest = pmsCiAddGuest;
window.ciEditGuest = pmsCiEditGuest;
window.ciCancelEdit = pmsCiCancelEdit;
window.ciUpdateGuest = pmsCiUpdateGuest;
window.ciRemoveGuest = pmsCiRemoveGuest;
window.ciToggleGuestList = pmsCiToggleGuestList;
window.ciScanCode = pmsCiScanCode;

function pmsCiToggleIdFields(select) {
    const val = select.value;
    const isForeign = val === 'passport' || val === 'visa';
    const noExpire = val === 'cmnd' || val === 'gplx';
    const expireEl = document.getElementById('ci-grp-expire');
    const areaEl = document.getElementById('ci-grp-area');
    const addrEl = document.getElementById('ci-grp-address');
    const provEl = document.getElementById('ci-grp-province');
    const wardEl = document.getElementById('ci-grp-ward');
    const addrSection = document.querySelector('.ci-address-section');
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');

    if (expireEl) expireEl.style.display = noExpire ? 'none' : 'block';

    if (isForeign) {
        // Ẩn và disable toàn bộ section địa chỉ
        if (areaEl) areaEl.style.display = 'none';
        if (addrEl) addrEl.style.display = 'none';
        if (provEl) provEl.style.display = 'none';
        if (wardEl) wardEl.style.display = 'none';
        if (addrSection) addrSection.style.display = 'none';
        // Disable các address fields cụ thể
        ['ci-province', 'ci-district', 'ci-ward', 'ci-address'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.disabled = true; el.readOnly = true; }
        });
        // Disable radio buttons
        document.querySelectorAll('#ciModal input[name="ci-area"]').forEach(r => {
            if (r) r.disabled = true;
        });
    } else {
        // Hiện lại section địa chỉ
        if (areaEl) areaEl.style.display = 'flex';
        if (addrEl) addrEl.style.display = 'flex';
        if (provEl) provEl.style.display = 'flex';
        if (wardEl) wardEl.style.display = 'flex';
        if (addrSection) addrSection.style.display = '';
        // Enable các address fields
        ['ci-province', 'ci-district', 'ci-ward', 'ci-address'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.disabled = false; el.readOnly = false; }
        });
        // Enable radio buttons
        document.querySelectorAll('#ciModal input[name="ci-area"]').forEach(r => {
            if (r && r.style.display !== 'none') r.disabled = false;
        });
    }
}
window.pmsCiToggleIdFields = pmsCiToggleIdFields;

function pmsCiToggleInvoice(radio) {
    const val = radio.value;
    // New layout: toggle wrapper div
    const fieldsEl = document.getElementById('ci-invoice-fields');
    if (fieldsEl) fieldsEl.style.display = val === '1' ? 'block' : 'none';
    // Legacy fallback for individual fields
    const taxEl = document.getElementById('ci-grp-tax');
    const contactEl = document.getElementById('ci-grp-tax-contact');
    if (taxEl) taxEl.style.display = val === '1' ? 'flex' : 'none';
    if (contactEl) contactEl.style.display = val === '1' ? 'flex' : 'none';
}
window.pmsCiToggleInvoice = pmsCiToggleInvoice;
function pmsCiToggleArea(val) {
    // Delegate to vnSwitchMode
    if (typeof vnSwitchMode === 'function') vnSwitchMode(val);
}
window.pmsCiToggleArea = pmsCiToggleArea;

function pmsCiFormatCurrency(input) {
    let val = input.value.replace(/[^0-9]/g, '');
    if (!val) {
        input.value = '0';
        return;
    }
    input.value = parseInt(val).toLocaleString('vi-VN');
}
window.pmsCiFormatCurrency = pmsCiFormatCurrency;

function pmsCiFormatID(input) {
    // Chỉ xoá khoảng trắng và chuyển in hoa, cho phép nhập cả chữ và số tự do
    input.value = input.value.replace(/\s+/g, '').toUpperCase();
}
window.pmsCiFormatID = pmsCiFormatID;

// Add Enter key listener for CCCD search
document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
        const el = e.target;
        if (el && el.id === 'ci-cccd') {
            e.preventDefault();
            if (typeof pmsCiSearchOldGuest === 'function') pmsCiSearchOldGuest();
        }
    }
});

function pmsCiFormatCapitalize(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
window.pmsCiFormatCapitalize = pmsCiFormatCapitalize;

function pmsCiFormatSentence(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.charAt(0).toUpperCase() + val.slice(1);
}
window.pmsCiFormatSentence = pmsCiFormatSentence;

function pmsCiFormatBasicNumeric(input) {
    input.value = input.value.replace(/\s+/g, '').replace(/\D/g, ''); // Xoá trắng, chỉ để lại số
}
window.pmsCiFormatBasicNumeric = pmsCiFormatBasicNumeric;

function pmsCiValidateID(input) {
    if (!input) return { valid: true };
    const type = document.getElementById('ci-id-type')?.value || 'cccd';
    const val = input.value.trim();
    if (!val) {
        input.classList.remove('is-invalid');
        return { valid: true };
    }

    let isValid = true;
    let msg = '';

    if (type === 'cccd') {
        // Kiểm tra CCCD: phải là 12 chữ số
        if (!/^\d{12}$/.test(val)) {
            isValid = false;
            msg = 'Số CCCD phải có đúng 12 chữ số!';
        }
    } else if (type === 'cmnd') {
        // Kiểm tra CMND: phải là 9 chữ số
        if (!/^\d{9}$/.test(val)) {
            isValid = false;
            msg = 'Số CMND phải có đúng 9 chữ số!';
        }
    }

    if (!isValid) {
        input.classList.add('is-invalid');
    } else {
        input.classList.remove('is-invalid');
    }

    return { valid: isValid, message: msg };
}
window.pmsCiValidateID = pmsCiValidateID;

function pmsCiFailValidation(inputId, message) {
    const el = document.getElementById(inputId);
    if (el) { el.classList.add('is-invalid'); el.focus(); }
    window.alert(message);
    return { valid: false, message: message };
}

function pmsCiClearValidation() {
    document.querySelectorAll('#ciModal .is-invalid').forEach(el => el.classList.remove('is-invalid'));
    document.querySelectorAll('#ciModal .is-warning').forEach(el => el.classList.remove('is-warning'));
}

function pmsCiValidateGuestForm(g) {
    pmsCiClearValidation();

    // 1. Số giấy tờ (kiểm tra trước loại giấy tờ)
    if (!g.cccd) return pmsCiFailValidation('ci-cccd', 'Vui lòng nhập Số giấy tờ');
    // 2. Loại giấy tờ
    if (!g.id_type) return pmsCiFailValidation('ci-id-type', 'Vui lòng chọn Loại giấy tờ');
    // 3. Ngày hết hạn (chỉ kiểm tra nếu giấy tờ có hạn)
    const noExpire = g.id_type === 'cmnd' || g.id_type === 'gplx';
    if (!noExpire) {
        if (!g.id_expire) return pmsCiFailValidation('ci-id-expire', 'Vui lòng nhập Ngày hết hạn giấy tờ!');
        const today = new Date();
        const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
        if (g.id_expire <= todayStr) return pmsCiFailValidation('ci-id-expire', 'Giấy tờ này đã quá ngày hết hạn!');
    }
    // 4. Validate ID format sau khi biết loại giấy tờ
    const idInput = document.getElementById('ci-cccd');
    const idValid = pmsCiValidateID(idInput);
    if (!idValid.valid) return pmsCiFailValidation('ci-cccd', idValid.message);
    // 5. Họ và tên
    if (!g.full_name) return pmsCiFailValidation('ci-name', 'Vui lòng nhập Họ và tên');
    // 6. Giới tính
    if (!g.gender) return pmsCiFailValidation('ci-gender', 'Vui lòng chọn Giới tính');
    // 7. Ngày sinh
    if (!g.birth_date) return pmsCiFailValidation('ci-birth', 'Vui lòng nhập Ngày sinh');
    // 8. Quốc tịch
    if (!g.nationality) return pmsCiFailValidation('ci-nationality', 'Vui lòng chọn Quốc tịch');

    // 8b. Invoice validation — chỉ kiểm tra khi chọn "Có xuất hoá đơn"
    const invoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    if (invoiceVal === '1') {
        const taxCodeEl = document.getElementById('ci-tax-code');
        const invoiceContactEl = document.getElementById('ci-tax-contact');
        if (!taxCodeEl?.value?.trim()) {
            return pmsCiFailValidation('ci-tax-code', 'Vui lòng nhập Mã số thuế');
        }
        if (!invoiceContactEl?.value?.trim()) {
            return pmsCiFailValidation('ci-tax-contact', 'Vui lòng nhập Liên hệ hoá đơn (Email hoặc SĐT)');
        }
    }

    // 9. Địa chỉ - CHỈ validation cho khách MỚI (auto-fill khách cũ thì bỏ qua)
    const isForeign = g.id_type === 'passport' || g.id_type === 'visa';
    const isOldGuest = window._pmsCiIsOldGuest === true;
    
    if (!isForeign && !isOldGuest) {
        // KHÁCH MỚI: Phải chọn Tỉnh/TP từ datalist
        if (!g.city) {
            return pmsCiFailValidation('ci-province', 'Vui lòng chọn Tỉnh/Thành phố từ danh sách');
        }
        // Kiểm tra Tỉnh/TP có trong datalist không
        if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-province', g.city)) {
            const provEl = document.getElementById('ci-province');
            if (provEl) provEl.classList.add('is-invalid');
            return pmsCiFailValidation('ci-province', `"${g.city}" không có trong danh sách. Vui lòng chọn Tỉnh/Thành phố từ danh sách!`);
        }

        // KHÁCH MỚI: Phải chọn Phường/Xã từ datalist
        if (!g.ward) {
            return pmsCiFailValidation('ci-ward', 'Vui lòng chọn Phường/Xã từ danh sách');
        }
        // Kiểm tra Phường/Xã có trong datalist không
        if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-ward', g.ward)) {
            const wardEl = document.getElementById('ci-ward');
            if (wardEl) wardEl.classList.add('is-invalid');
            return pmsCiFailValidation('ci-ward', `"${g.ward}" không có trong danh sách. Vui lòng chọn Phường/Xã từ danh sách!`);
        }

        // Chỉ yêu cầu Quận/Huyện trong chế độ địa bàn cũ
        const addrType = g.address_type || 'new';
        if (addrType === 'old' && !g.district) {
            return pmsCiFailValidation('ci-district', 'Vui lòng chọn Quận/Huyện');
        }

        // Luôn yêu cầu địa chỉ chi tiết
        if (!g.address) return pmsCiFailValidation('ci-address', 'Vui lòng nhập Địa chỉ chi tiết');
    }

    // Kiểm tra tuổi < 18 sau khi đã nhập ngày sinh
    const birthInput = document.getElementById('ci-birth');
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
window.pmsCiValidateGuestForm = pmsCiValidateGuestForm;

// ─────────────────────────────────────────────────────────────────────────────
// Guest Search & Fill Functions
// ─────────────────────────────────────────────────────────────────────────────

// Lock ALL fields (full read-only) — used when auto-fill from old guest
// For old guests: lock everything including address radios
function pmsCiLockAllFields() {
    ['ci-name', 'ci-cccd', 'ci-id-expire', 'ci-birth', 'ci-nationality',
        'ci-address', 'ci-vehicle', 'ci-guest-notes',
        'ci-province', 'ci-district', 'ci-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.readOnly = true; el.classList.remove('is-invalid', 'is-warning'); }
        });
    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) idTypeEl.disabled = true;
    const genderEl = document.getElementById('ci-gender');
    if (genderEl) genderEl.disabled = true;
    // Lock address radios to prevent switching modes
    const areaRadios = document.querySelectorAll('input[name="ci-area"]');
    areaRadios.forEach(r => r.disabled = true);
    const staySection = document.getElementById('ci-section-stay');
    if (staySection) staySection.classList.add('ci-section-disabled');
}
window.pmsCiLockAllFields = pmsCiLockAllFields;

// Unlock ALL fields — used when starting new checkin or cancelling edit
function pmsCiUnlockAllFields() {
    ['ci-name', 'ci-cccd', 'ci-id-expire', 'ci-birth', 'ci-nationality',
        'ci-address', 'ci-vehicle', 'ci-guest-notes',
        'ci-province', 'ci-district', 'ci-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.readOnly = false; el.classList.remove('is-invalid', 'is-warning'); }
        });
    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) { idTypeEl.disabled = false; pmsCiToggleIdFields(idTypeEl); }
    const genderEl = document.getElementById('ci-gender');
    if (genderEl) genderEl.disabled = false;
    const invoiceRadios = document.querySelectorAll('input[name="ci-invoice"]');
    invoiceRadios.forEach(r => r.disabled = false);
    const areaRadios = document.querySelectorAll('input[name="ci-area"]');
    areaRadios.forEach(r => {
        // Only enable if it was not hidden (old mode radio is hidden for non-old guests)
        if (r.style.display !== 'none') r.disabled = false;
    });
    const staySection = document.getElementById('ci-section-stay');
    if (staySection) staySection.classList.remove('ci-section-disabled');
}
window.pmsCiUnlockAllFields = pmsCiUnlockAllFields;

// Legacy aliases
function pmsCiLockAllRequiredFields() { pmsCiLockAllFields(); }
function pmsCiUnlockAllRequiredFields() { pmsCiUnlockAllFields(); }
window.pmsCiLockAllRequiredFields = pmsCiLockAllRequiredFields;
window.pmsCiUnlockAllRequiredFields = pmsCiUnlockAllRequiredFields;

// Fill guest form from old data (TRUSTED DATA - for preview only)
// Flow: Fill form → Lock address → User decides: "Thêm khách" or "Nhận phòng"
async function pmsCiFillGuestFromOld(guest) {
    try {
        if (typeof guest === 'string') guest = JSON.parse(guest);

        // 0. Mark as trusted BEFORE filling (PMS_ADDR progressive normalization)
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.markAutofill) {
            PMS_ADDR.markAutofill();
        }

        // 1. Fill basic fields (sync - immediate)
        const nameEl = document.getElementById('ci-name');
        if (nameEl) nameEl.value = guest.full_name || '';
        const genderEl = document.getElementById('ci-gender');
        if (genderEl) genderEl.value = guest.gender || '';
        const nationalityEl = document.getElementById('ci-nationality');
        if (nationalityEl) nationalityEl.value = guest.nationality || 'VNM - Việt Nam';
        const idTypeEl = document.getElementById('ci-id-type');
        if (idTypeEl) {
            idTypeEl.value = (guest.id_type || 'cccd').toLowerCase();
            // Trigger visibility toggle for passport/visa (hide address sections)
            pmsCiToggleIdFields(idTypeEl);
        }
        const cccdEl = document.getElementById('ci-cccd');
        if (cccdEl) cccdEl.value = guest.cccd || '';
        const idExpireEl = document.getElementById('ci-id-expire');
        if (idExpireEl) {
            idExpireEl.value = guest.id_expire ? String(guest.id_expire).slice(0, 10) : '';
            pmsCiCheckIdExpire(idExpireEl);
        }
        const birthEl = document.getElementById('ci-birth');
        if (birthEl && guest.birth_date) {
            birthEl.value = String(guest.birth_date).slice(0, 10);
            pmsCiCheckBirth(birthEl);
        }
        const phoneEl = document.getElementById('ci-phone');
        if (phoneEl) phoneEl.value = guest.phone || '';
        const vehicleEl = document.getElementById('ci-vehicle');
        if (vehicleEl) vehicleEl.value = guest.vehicle || '';
        const notesEl = document.getElementById('ci-guest-notes');
        if (notesEl) notesEl.value = guest.notes || '';

        // 1b. Fill invoice info (UNLOCKED - user can update) - invoice is per-guest
        if (guest.tax_code || guest.invoice_contact) {
            const invoiceRadio1 = document.querySelector('input[name="ci-invoice"][value="1"]');
            const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
            if (invoiceRadio1) invoiceRadio1.checked = true;
            const taxCodeEl = document.getElementById('ci-tax-code');
            if (taxCodeEl) taxCodeEl.value = guest.tax_code || '';
            const taxContactEl = document.getElementById('ci-tax-contact');
            if (taxContactEl) taxContactEl.value = guest.invoice_contact || '';
            // Show invoice fields in LEFT column and call toggle to sync state
            const invoiceFields = document.getElementById('ci-invoice-fields');
            if (invoiceFields) invoiceFields.style.display = 'block';
            if (invoiceRadio1) pmsCiToggleInvoice(invoiceRadio1);
        } else {
            // Reset invoice section
            const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
            if (invoiceRadio0) invoiceRadio0.checked = true;
            const invoiceFields = document.getElementById('ci-invoice-fields');
            if (invoiceFields) invoiceFields.style.display = 'none';
            if (invoiceRadio0) pmsCiToggleInvoice(invoiceRadio0);
        }

        // 1c. Auto-fill done — user can scroll to see invoice data if needed

        // 2. Fill address fields (READONLY - trusted from DB)
        // Không dùng guest.ward để suy ra "cũ" — ward là phường mới sau chuẩn hóa.
        const hasOldData = guest.address_type === 'old' || !!(guest.old_city || guest.old_district || guest.old_ward);
        const addrType = hasOldData ? 'old' : 'new';

        // Set address mode radio
        const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
        const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
        if (addrType === 'old') {
            if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = true; }
            if (newRadio) { newRadio.disabled = true; }
        } else {
            if (newRadio) { newRadio.checked = true; }
            if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }
        }

        // Fill province
        const pEl = document.getElementById('ci-province');
        if (pEl) pEl.value = hasOldData ? (guest.old_city || '') : (guest.city || '');

        // Fill ward
        const wEl = document.getElementById('ci-ward');
        if (wEl) wEl.value = hasOldData ? (guest.old_ward || '') : (guest.ward || '');

        // Fill district (for old mode)
        const dEl = document.getElementById('ci-district');
        if (dEl) dEl.value = hasOldData ? (guest.old_district || '') : '';

        // Fill address detail
        const addrDetailEl = document.getElementById('ci-address');
        if (addrDetailEl) addrDetailEl.value = guest.address || '';

        // Fill NEW conversion display (for old mode - read only info)
        const nProvEl = document.getElementById('ci-new-province');
        const nWardEl = document.getElementById('ci-new-ward');
        if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }

        // 3. Hiển thị đủ hàng Quận/Huyện + khối chuẩn hóa (đọc từ DB, không ẩn như helper nhập tay)
        pmsCiShowAddressHelpers();
        
        // 4. ẨN khối chuyển đổi địa bàn (chỉ dùng cho khách mới nhập tay)
        const convGrp = document.getElementById('ci-conversion-grp');
        if (convGrp) convGrp.style.display = 'none';

        // 4. Lock ALL fields (read-only for trusted data)
        pmsCiLockAllFields();

        // 4b. UNLOCK invoice fields - user can update invoice info per-guest
        const invoiceRadios = document.querySelectorAll('input[name="ci-invoice"]');
        invoiceRadios.forEach(r => r.disabled = false);
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.readOnly = false;
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.readOnly = false;

        // Force critical fields after lock
        if (cccdEl) { cccdEl.value = guest.cccd || ''; cccdEl.readOnly = true; }
        if (idTypeEl) idTypeEl.disabled = true;
        if (nameEl) nameEl.readOnly = true;
        if (genderEl) genderEl.disabled = true;
        if (birthEl) birthEl.readOnly = true;
        if (nationalityEl) nationalityEl.readOnly = true;

        // Lock address fields (trusted data)
        if (pEl) { pEl.readOnly = true; pEl.style.background = '#f0fdf4'; }
        if (dEl) { dEl.readOnly = true; dEl.style.background = '#f0fdf4'; }
        if (wEl) { wEl.readOnly = true; wEl.style.background = '#f0fdf4'; }
        if (addrDetailEl) { addrDetailEl.readOnly = true; addrDetailEl.style.background = '#f0fdf4'; }

        // Unlock editable fields only
        if (phoneEl) phoneEl.readOnly = false;
        if (notesEl) notesEl.readOnly = false;
        if (vehicleEl) vehicleEl.readOnly = false;
        if (idExpireEl) idExpireEl.readOnly = false;

        // 5. Show state badge for trusted data
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR._updateStateBadge) {
            PMS_ADDR._updateStateBadge('TRUSTED', 'Địa chỉ từ dữ liệu cũ', 'green');
        }

        // 6. Store existing guest ID for auto-update
        window._pmsCiExistingGuestId = guest.id;
        window._pmsCiIsOldGuest = true;

        // 7. Remove hint
        const hintEl = document.getElementById('ci-cccd-hint');
        if (hintEl) hintEl.remove();

        // 8. Show info message that data is from DB
        pmsCiShowAutofillNotice(guest.full_name, guest.cccd);

        pmsToast(`Đã tìm thấy khách: ${guest.full_name || guest.cccd}`);

    } catch (e) {
        console.error('Error filling guest data:', e);
        pmsToast('Lỗi khi điền thông tin', false);
    }
}
window.pmsCiFillGuestFromOld = pmsCiFillGuestFromOld;

// ─── Address Helper Visibility ──────────────────────────────────────────────────

function pmsCiShowAddressHelpers() {
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');
    const mode = document.querySelector('input[name="ci-area"]:checked')?.value || 'new';

    if (distGrp) distGrp.style.display = mode === 'old' ? '' : 'none';
    if (convGrp) convGrp.style.display = mode === 'old' ? '' : 'none';
}

// ─── Autofill Notice ─────────────────────────────────────────────────────────

function pmsCiShowAutofillNotice(name, cccd) {
    // Remove existing notice
    const existing = document.getElementById('ci-autofill-notice');
    if (existing) existing.remove();

    const infoBar = document.getElementById('ci-section-stay');
    if (!infoBar) return;

    const notice = document.createElement('div');
    notice.id = 'ci-autofill-notice';
    notice.style.cssText = `
        background: linear-gradient(135deg, #f0fdf4, #dcfce7);
        border: 1px solid #86efac;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 13px;
    `;
    notice.innerHTML = `
        <div style="width: 32px; height: 32px; background: #22c55e; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
        </div>
        <div style="flex: 1;">
            <div style="font-weight: 600; color: #15803d;">Dữ liệu từ lưu trú trước</div>
            <div style="color: #64748b; font-size: 12px;">Khách <strong>${name || cccd}</strong> - Địa chỉ đã được xác nhận từ hệ thống</div>
        </div>
    `;

    infoBar.insertBefore(notice, infoBar.firstChild);
}

// ─── Premium Search Popup ─────────────────────────────────────────────────────

function _pmsCiCloseSearchPopup() {
    const modal = document.getElementById('ci-search-results-modal');
    if (modal) {
        modal.style.opacity = '0';
        setTimeout(() => modal.remove(), 200);
    }
}
window._pmsCiCloseSearchPopup = _pmsCiCloseSearchPopup;

function _pmsCiSelectGuest(index) {
    if (!window._pmsCiSearchResults || !window._pmsCiSearchResults[index]) return;
    const guest = window._pmsCiSearchResults[index];
    _pmsCiCloseSearchPopup();
    pmsCiFillGuestFromOld(guest);
}
window._pmsCiSelectGuest = _pmsCiSelectGuest;

async function pmsCiSearchOldGuest() {
    const cccd = document.getElementById('ci-cccd')?.value?.trim();
    if (!cccd || cccd.length < 3) {
        pmsToast('Vui lòng nhập ít nhất 3 ký tự để tìm kiếm', false);
        return;
    }

    try {
        const r = await pmsApi(`/api/pms/guests/search?cccd=${encodeURIComponent(cccd)}`);

        if (!r.guests || r.guests.length === 0) {
            alert(`⚠️ Không tìm thấy khách hàng nào với số giấy tờ "${cccd}".\n\nVui lòng kiểm tra lại số giấy tờ hoặc nhập thông tin khách mới.`);
            pmsToast(`Không tìm thấy khách với CCCD "${cccd}"`, false);
            return;
        }

        // Store results globally for selection
        window._pmsCiSearchResults = r.guests;

        // If only 1 result, auto-fill directly
        if (r.guests.length === 1) {
            pmsCiFillGuestFromOld(r.guests[0]);
            return;
        }

        // Build premium popup for multiple results
        const resultsHtml = r.guests.map((g, idx) => {
            const initials = (g.full_name || '?').split(' ').map(w => w[0]).join('').slice(-2).toUpperCase();
            const genderColor = g.gender === 'Nam' ? '#3b82f6' : g.gender === 'Nữ' ? '#ec4899' : '#8b5cf6';
            const addressParts = [g.address, g.ward, g.city].filter(Boolean);
            const addressStr = addressParts.length > 0 ? addressParts.join(', ') : '—';

            return `
                <div class="ci-search-card" onclick="_pmsCiSelectGuest(${idx})" tabindex="0">
                    <div class="ci-search-avatar" style="background:linear-gradient(135deg, ${genderColor}, ${genderColor}dd);">
                        ${initials}
                    </div>
                    <div class="ci-search-info">
                        <div class="ci-search-name">${pmsEscapeHtml(g.full_name)}</div>
                        <div class="ci-search-detail">
                            <span class="ci-search-tag">
                                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                                ${pmsEscapeHtml(g.cccd)}
                            </span>
                            ${g.phone ? `<span class="ci-search-tag">
                                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                                ${pmsEscapeHtml(g.phone)}
                            </span>` : ''}
                            ${g.gender ? `<span class="ci-search-tag">${pmsEscapeHtml(g.gender)}</span>` : ''}
                        </div>
                        <div class="ci-search-address">
                            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                            ${pmsEscapeHtml(addressStr)}
                        </div>
                    </div>
                    <div class="ci-search-arrow">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </div>
                </div>
            `;
        }).join('');

        // Remove existing popup if any
        const existing = document.getElementById('ci-search-results-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'ci-search-results-modal';
        modal.innerHTML = `
            <style>
                #ci-search-results-modal {
                    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(15, 23, 42, 0.6);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    z-index: 10000;
                    display: flex; align-items: center; justify-content: center;
                    opacity: 0;
                    transition: opacity 0.2s ease;
                }
                .ci-search-popup {
                    background: #fff;
                    border-radius: 16px;
                    max-width: 520px; width: 92%;
                    max-height: 70vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 25px 60px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.1);
                    transform: translateY(12px);
                    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                }
                #ci-search-results-modal.ci-show .ci-search-popup { transform: translateY(0); }
                .ci-search-header {
                    padding: 20px 24px 16px; border-bottom: 1px solid #f1f5f9;
                    display: flex; align-items: center; gap: 14px;
                }
                .ci-search-header-icon {
                    width: 42px; height: 42px; border-radius: 12px;
                    background: linear-gradient(135deg, #dbeafe, #bfdbfe);
                    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
                }
                .ci-search-header-icon svg { stroke: #2563eb; }
                .ci-search-header h5 { margin: 0; font-size: 16px; font-weight: 700; color: #1e293b; }
                .ci-search-header p { margin: 4px 0 0; font-size: 13px; color: #64748b; }
                .ci-search-close {
                    margin-left: auto; padding: 8px; background: none;
                    border: none; border-radius: 8px; cursor: pointer; color: #94a3b8; transition: all 0.15s;
                }
                .ci-search-close:hover { background: #f1f5f9; color: #475569; }
                .ci-search-list { flex: 1; overflow-y: auto; padding: 12px 16px 16px; }
                .ci-search-card {
                    display: flex; align-items: center; gap: 14px;
                    padding: 14px 16px; border-radius: 12px;
                    border: 1px solid #e2e8f0; background: #fff;
                    cursor: pointer; transition: all 0.15s ease; margin-bottom: 10px;
                }
                .ci-search-card:last-child { margin-bottom: 0; }
                .ci-search-card:hover {
                    border-color: #93c5fd; background: linear-gradient(135deg, #f0f9ff, #eff6ff);
                    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1); transform: translateY(-1px);
                }
                .ci-search-card:active { transform: translateY(0); }
                .ci-search-avatar {
                    width: 44px; height: 44px; border-radius: 12px;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 14px; font-weight: 700; color: #fff; flex-shrink: 0; letter-spacing: 0.5px;
                }
                .ci-search-info { flex: 1; min-width: 0; }
                .ci-search-name {
                    font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 4px;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                }
                .ci-search-detail { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
                .ci-search-tag {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 2px 8px; border-radius: 6px;
                    background: #f1f5f9; color: #475569; font-size: 11.5px; font-weight: 500;
                }
                .ci-search-address {
                    display: flex; align-items: center; gap: 4px;
                    font-size: 12px; color: #94a3b8;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                }
                .ci-search-arrow { flex-shrink: 0; color: #cbd5e1; transition: all 0.15s; }
                .ci-search-card:hover .ci-search-arrow { color: #3b82f6; transform: translateX(2px); }
            </style>
            <div class="ci-search-popup">
                <div class="ci-search-header">
                    <div class="ci-search-header-icon">
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                        </svg>
                    </div>
                    <div>
                        <h5>Tìm thấy ${r.guests.length} khách hàng</h5>
                        <p>Chọn khách hàng để điền thông tin vào form</p>
                    </div>
                    <button class="ci-search-close" onclick="_pmsCiCloseSearchPopup()" title="Đóng">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="ci-search-list">${resultsHtml}</div>
            </div>
        `;
        document.body.appendChild(modal);

        // Trigger animation
        requestAnimationFrame(() => {
            modal.style.opacity = '1';
            modal.classList.add('ci-show');
        });

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) _pmsCiCloseSearchPopup();
        });

        // Close on Escape
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                _pmsCiCloseSearchPopup();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

    } catch (e) {
        console.error('Error searching:', e);
        pmsToast('Lỗi tìm kiếm', false);
    }
}
window.pmsCiSearchOldGuest = pmsCiSearchOldGuest;



// ─────────────────────────────────────────────────────────────────────────────
// Expiration Check
// ─────────────────────────────────────────────────────────────────────────────
let _pmsCiIdExpireTimer = null;
function pmsCiCheckIdExpire(inputEl) {
    if (!inputEl.value) {
        inputEl.classList.remove('is-invalid');
        return;
    }
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');

    if (inputEl.value <= todayStr) {
        inputEl.classList.add('is-invalid');
        clearTimeout(_pmsCiIdExpireTimer);
        _pmsCiIdExpireTimer = setTimeout(() => {
            alert('⚠️ Cảnh báo: Giấy tờ này đã quá ngày hết hạn! Vui lòng cập nhật.');
        }, 100);
    } else {
        inputEl.classList.remove('is-invalid');
    }
}
// ─────────────────────────────────────────────────────────────────────────────
// Birth Check
// ─────────────────────────────────────────────────────────────────────────────
let _pmsCiBirthTimer = null;
function pmsCiCheckBirth(inputEl) {
    if (!inputEl.value) {
        inputEl.classList.remove('is-warning');
        return;
    }
    const parts = inputEl.value.split('-');
    if (parts.length === 3) {
        const birth = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const today = new Date();
        let age = today.getFullYear() - birth.getFullYear();
        const m = today.getMonth() - birth.getMonth();
        if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
        if (age < 18) {
            inputEl.classList.add('is-warning');
            clearTimeout(_pmsCiBirthTimer);
            _pmsCiBirthTimer = setTimeout(() => {
                alert(`⚠️ Cảnh báo: Khách hàng hiện mới ${age} tuổi. Việc nhận phòng có thể yêu cầu người giám hộ!`);
            }, 500);
        } else {
            inputEl.classList.remove('is-warning');
        }
    }
}
window.pmsCiCheckIdExpire = pmsCiCheckIdExpire;
function pmsCiOnDepositTypeChange(select) {
    const val = select.value;
    const metaGrp = document.getElementById('ci-deposit-meta-grp');
    const metaCompany = document.getElementById('ci-meta-company');
    const metaOta = document.getElementById('ci-meta-ota');
    const metaUnc = document.getElementById('ci-meta-unc');

    if (!metaGrp) return;

    // Hide all first
    metaGrp.style.display = 'none';
    if (metaCompany) metaCompany.style.display = 'none';
    if (metaOta) metaOta.style.display = 'none';
    if (metaUnc) metaUnc.style.display = 'none';

    if (val === 'Công ty') {
        metaGrp.style.display = 'flex';
        if (metaCompany) metaCompany.style.display = 'block';
    } else if (val === 'OTA') {
        metaGrp.style.display = 'flex';
        if (metaOta) metaOta.style.display = 'block';
    } else if (val === 'UNC') {
        metaGrp.style.display = 'flex';
        if (metaUnc) metaUnc.style.display = 'block';
    }
}
window.pmsCiOnDepositTypeChange = pmsCiOnDepositTypeChange;
