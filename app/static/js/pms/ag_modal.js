// static/js/pms/ag_modal.js
// AG Modal — Core: open, guest list, CRUD, submit
// Kiến trúc hoàn toàn mirror từ pms_checkin.js
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

let agStayId = null;
let agRoomNum = null;
let agGuestId = null;
let agEditMode = false;
let agMaxGuests = 2;
let agGuestList = [];           // guest objects managed within this modal session
let _agEditIndex = null;       // index into agGuestList being edited
let _agIsOldGuest = false;
let _agIsExternalEdit = false;

// ─────────────────────────────────────────────────────────────────────────────
// Open Modal
// ─────────────────────────────────────────────────────────────────────────────

async function openAG(stayId, roomNum) {
    agStayId = stayId;
    agRoomNum = roomNum;
    agGuestId = null;
    agEditMode = false;
    _agEditIndex = null;

    // Always clear to prevent stale data
    agGuestList = [];
    agMaxGuests = 2;

    // Fetch latest stay data
    try {
        const d = await pmsApi(`/api/pms/stays/${stayId}`);
        console.log('[openAG] Fetched stay data:', JSON.stringify({
            id: d.id,
            status: d.status,
            guests_count: d.guests?.length
        }));

        agMaxGuests = d.max_guests || 2;

        // Load ALL guests (active + checked-out for context)
        const rawGuests = (d.guests || []).map(g => ({
            id: g.id,
            full_name: g.full_name || '',
            gender: g.gender || '',
            birth_date: g.birth_date || '',
            phone: g.phone || '',
            cccd: g.cccd || '',
            is_primary: g.is_primary || false,
            notes: g.notes || '',
            address: g.address || '',
            address_type: g.address_type || 'new',
            city: g.city || '',
            district: g.district || '',
            ward: g.ward || '',
            old_city: g.old_city || '',
            old_district: g.old_district || '',
            old_ward: g.old_ward || '',
            id_expire: g.id_expire || '',
            id_type: g.id_type || 'cccd',
            tax_code: g.tax_code || '',
            invoice_contact: g.invoice_contact || '',
            nationality: g.nationality || 'VNM - Việt Nam',
            check_in_at: g.check_in_at || d.check_in_at || null,
            check_out_at: g.check_out_at || null,
            from_old: !!g.id
        }));

        // AG modal: only active guests (not checked out yet)
        agGuestList = rawGuests.filter(g => !g.check_out_at);
        console.log('[openAG] Loaded', agGuestList.length, 'active guests:', agGuestList.map(x => x.cccd));

    } catch (e) {
        console.error('[openAG] Failed to fetch stay data:', e);
        agGuestList = [];
    }

    document.getElementById('ag-stay-id').value = stayId;
    document.getElementById('ag-guest-id').value = '';
    document.getElementById('ag-title').textContent = 'Thêm khách';

    // Update sub-header with fresh data
    const currentCount = agGuestList.length;
    document.getElementById('ag-sub').textContent =
        `Phòng ${roomNum} | ${currentCount}/${agMaxGuests} khách`;

    // Init address + nationality
    if (typeof pmsPopulateNationalities === 'function') pmsPopulateNationalities('dl-nationality');
    if (typeof agInitAddressFields === 'function') agInitAddressFields();

    agRefreshGuestForm();
    agRenderGuestList();
    agSetEditMode(false);

    if (typeof openModal === 'function') openModal('agModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('agModal');
    else document.getElementById('agModal')?.classList.add('show');
}
window.openAG = openAG;

// ─────────────────────────────────────────────────────────────────────────────
// Edit mode toolbar
// ─────────────────────────────────────────────────────────────────────────────

function agSetEditMode(isEdit, guestName = '') {
    const addBtn = document.getElementById('ag-add-btn');
    const updBtn = document.getElementById('ag-update-btn');
    const cancelBtn = document.getElementById('ag-cancel-btn');
    const refreshBtn = document.getElementById('ag-refresh-btn');
    const scanBtn = document.getElementById('ag-scan-btn');
    const toggleBtn = document.getElementById('ag-toggle-list-btn');

    if (isEdit) {
        agEditMode = true;
        if (addBtn) addBtn.style.display = 'none';
        if (updBtn) { updBtn.style.display = 'inline-flex'; updBtn.style.background = '#16a34a'; }
        if (cancelBtn) cancelBtn.style.display = 'inline-flex';
        if (refreshBtn) refreshBtn.style.display = 'none';
        if (scanBtn) scanBtn.style.display = 'none';
        if (toggleBtn) toggleBtn.style.display = agGuestList.length >= 2 ? 'inline-flex' : 'none';
    } else {
        agEditMode = false;
        agGuestId = null;
        _agEditIndex = null;
        if (addBtn) addBtn.style.display = 'inline-flex';
        if (updBtn) { updBtn.style.display = 'none'; updBtn.style.background = ''; }
        if (cancelBtn) cancelBtn.style.display = 'none';
        if (refreshBtn) refreshBtn.style.display = 'inline-flex';
        if (scanBtn) scanBtn.style.display = 'inline-flex';
        if (toggleBtn) toggleBtn.style.display = 'inline-flex';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Render guest list (chip strip)
// ─────────────────────────────────────────────────────────────────────────────

function agToggleGuestList() {
    const chipRow = document.getElementById('ag-chip-row');
    const btn = document.getElementById('ag-toggle-list-btn');
    if (!chipRow) return;

    const isHidden = chipRow.style.display === 'none';
    chipRow.style.display = isHidden ? 'flex' : 'none';

    if (btn) {
        const isShown = chipRow.style.display !== 'none';
        btn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>
              <line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
            </svg>
            ${isShown ? 'Ẩn danh sách' : 'Hiện danh sách'} (<span id="ag-guest-count-btn">${agGuestList.length}</span>)
        `;
    }
}
window.agToggleGuestList = agToggleGuestList;

function agRenderGuestList() {
    const chipRow = document.getElementById('ag-chip-row');
    const countBtn = document.getElementById('ag-guest-count-btn');
    const countBadge = document.getElementById('ag-guest-count');

    if (countBtn) countBtn.textContent = agGuestList.length;
    if (countBadge) countBadge.textContent = agGuestList.length;

    if (!chipRow) return;

    if (agGuestList.length === 0) {
        chipRow.innerHTML = `<span class="ag-chip-empty">Chưa có khách — nhập form và bấm <strong>Thêm khách</strong></span>`;
        return;
    }

    chipRow.innerHTML = agGuestList.map((g, i) => {
        const isEditingThis = (_agEditIndex === i);
        const isPrimary = g.is_primary ? 'is-primary' : '';
        const editCls = isEditingThis ? 'ag-editing' : '';
        const isLocked = !!g.id;  // has DB id = locked (already saved)
        const lockedCls = isLocked ? 'ag-chip-locked' : '';

        const genderIcon = typeof pmsGenderIcon === 'function'
            ? pmsGenderIcon(g.gender)
            : `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="3"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`;

        const delBtn = !isLocked ? `
            <button class="ag-chip-del" onclick="event.stopPropagation(); agRemoveGuest(${i})" title="Xóa khách">×</button>
        ` : '';

        // Locked guests: disable pointer-events entirely, no hover, no click
        if (isLocked) {
            return `
                <div class="ag-guest-chip ${isPrimary} ${lockedCls}" style="pointer-events:none; cursor:not-allowed;">
                  <div class="ag-chip-icon">${genderIcon}</div>
                  <span style="cursor:not-allowed; opacity:0.85;">${pmsEscapeHtml(g.full_name || 'CHƯA NHẬP')}</span>
                  <svg style="flex-shrink:0; opacity:0.5;" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2.5"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                </div>
            `;
        }

        return `
            <div class="ag-guest-chip ${isPrimary} ${editCls} ${lockedCls}">
              <div class="ag-chip-icon">${genderIcon}</div>
              <span onclick="agEditGuest(${i})" style="cursor:pointer;">${pmsEscapeHtml(g.full_name || 'CHƯA NHẬP')}</span>
              ${delBtn}
            </div>
        `;
    }).join('');
}
window.agRenderGuestList = agRenderGuestList;

// ─────────────────────────────────────────────────────────────────────────────
// Refresh / Clear form
// ─────────────────────────────────────────────────────────────────────────────

function agRefreshGuestForm() {
    ['ag-name','ag-cccd','ag-id-expire','ag-birth','ag-phone',
        'ag-notes','ag-address','ag-nationality',
        'ag-province','ag-district','ag-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.value = '';
            el.readOnly = false;
            el.classList.remove('is-invalid', 'is-warning');
        }
    });
    ['ag-new-province','ag-new-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.value = ''; el.style.color = ''; }
    });

    const gEl = document.getElementById('ag-gender');
    if (gEl) { gEl.value = ''; gEl.disabled = false; }
    const natEl = document.getElementById('ag-nationality');
    if (natEl) natEl.value = 'VNM - Việt Nam';
    const idTypeEl = document.getElementById('ag-id-type');
    if (idTypeEl) { idTypeEl.value = 'cccd'; idTypeEl.disabled = false; agToggleIdFields(idTypeEl); }

    // Invoice
    const invoiceRadio0 = document.querySelector('input[name="ag-invoice"][value="0"]');
    if (invoiceRadio0) { invoiceRadio0.checked = true; agToggleInvoice(invoiceRadio0); }
    ['ag-tax-code','ag-tax-contact'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const invoiceFields = document.getElementById('ag-invoice-fields');
    if (invoiceFields) invoiceFields.style.display = 'none';

    // Address mode reset
    const newRadio = document.querySelector('input[name="ag-area"][value="new"]');
    const oldRadio = document.querySelector('input[name="ag-area"][value="old"]');
    if (newRadio) { newRadio.checked = true; newRadio.disabled = false; newRadio.style.display = ''; }
    if (oldRadio) { oldRadio.checked = false; oldRadio.disabled = false; oldRadio.style.display = ''; }

    const distGrp = document.getElementById('ag-grp-district');
    const convGrp = document.getElementById('ag-conversion-grp');
    if (distGrp) distGrp.style.display = 'none';
    if (convGrp) convGrp.style.display = 'none';

    // Reset address state
    if (typeof agClearConversion === 'function') agClearConversion();

    // Hide address validation warning panel
    const warnPanel = document.getElementById('ag-addr-warning-panel');
    if (warnPanel) warnPanel.style.display = 'none';

    agGuestId = null;
    _agIsOldGuest = false;
    document.getElementById('ag-guest-id').value = '';

    // Remove notices
    ['ag-autofill-notice','ag-capacity-warn'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
    });

    agUpdateCapacityWarn();
}
window.agRefreshGuestForm = agRefreshGuestForm;

// ─────────────────────────────────────────────────────────────────────────────
// Add Guest
// ─────────────────────────────────────────────────────────────────────────────

async function agAddGuest() {
    // If currently editing, switch to update
    if (_agEditIndex !== null) {
        await agUpdateGuest();
        return;
    }

    const g = agGetFormGuest();
    const v = agValidateGuestForm(g);
    if (!v.valid) return;

    // ── Duplicate check: in local list ─────────────────────────────────
    if (g.cccd && agGuestList.some(xg => xg.cccd === g.cccd)) {
        const existingGuest = agGuestList.find(xg => xg.cccd === g.cccd);
        console.log('[AG] CCCD duplicate in local list:', existingGuest);

        if (g.cccd.length >= 3) {
            try {
                const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
                const res = await pmsApi(url);

                if (res && res.is_active) {
                    if (res.room_number === agRoomNum) {
                        window.alert(`CẢNH BÁO: Khách ${g.cccd} đã có trong danh sách phòng ${agRoomNum}. Không thể thêm trùng.`);
                        pmsToast(`Khách ${g.cccd} đã có trong danh sách phòng ${agRoomNum}. Không thể thêm trùng.`, false);
                    } else {
                        window.alert(`CẢNH BÁO: Khách ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`);
                        pmsToast(`Khách hàng có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`, false);
                    }
                    return;
                }

                // DB says NOT active — guest previously checked out; update info
                Object.assign(existingGuest, {
                    full_name: g.full_name, gender: g.gender,
                    birth_date: g.birth_date, phone: g.phone,
                    id_expire: g.id_expire, id_type: g.id_type,
                    address: g.address, nationality: g.nationality,
                    tax_code: g.tax_code, invoice_contact: g.invoice_contact,
                    notes: g.notes
                });
                agRefreshGuestForm();
                agRenderGuestList();
                pmsToast(`Đã cập nhật thông tin khách ${g.cccd} (đã checkout trước đó).`, true);
                return;

            } catch(e) {
                console.error('[AG] Error checking active CCCD', e);
                pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
                return;
            }
        }
    }

    // ── Real-time block: active CCCD (new CCCDs not in local list) ────
    if (g.cccd && g.cccd.length >= 3) {
        try {
            const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
            const res = await pmsApi(url);

            if (res && res.is_active) {
                if (res.room_number === agRoomNum) {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đã có trong danh sách phòng ${agRoomNum}. Không thể thêm trùng.`);
                    pmsToast(`Khách ${g.cccd} đã có trong danh sách phòng ${agRoomNum}. Không thể thêm trùng.`, false);
                } else {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`);
                    pmsToast(`Khách hàng có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`, false);
                }
                return;
            }
        } catch(e) {
            console.error('[AG] Error checking active CCCD', e);
            pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
            return;
        }
    }

    // ── Capacity warning ────────────────────────────────────────────────
    const total = agGuestList.length + 1;
    if (total > agMaxGuests) {
        agUpdateCapacityWarn();
        pmsToast(`Chú ý: Số khách (${total}) vượt quá giới hạn phòng (tối đa ${agMaxGuests} người).`);
    }

    agGuestList.push(g);
    agRefreshGuestForm();
    agRenderGuestList();

    const chipRow = document.getElementById('ag-chip-row');
    if (chipRow) chipRow.style.display = 'flex';

    pmsToast(`Đã thêm khách "${g.full_name}" vào danh sách.`);
}
window.agAddGuest = agAddGuest;

// ─────────────────────────────────────────────────────────────────────────────
// Edit / Update / Cancel Guest
// ─────────────────────────────────────────────────────────────────────────────

async function agEditGuest(i) {
    const g = agGuestList[i];
    if (!g) return;

    _agEditIndex = i;
    agGuestId = g.id || null;
    _agIsOldGuest = !!(g.from_old || g.id);
    const isExistingGuest = _agIsOldGuest;

    // ── Phase 1: Fill all values first ────────────────────────────────
    const nameEl = document.getElementById('ag-name');
    const genderEl = document.getElementById('ag-gender');
    const nationalityEl = document.getElementById('ag-nationality');
    const cccdEl = document.getElementById('ag-cccd');
    const phoneEl = document.getElementById('ag-phone');
    const addressEl = document.getElementById('ag-address');
    const notesEl = document.getElementById('ag-notes');
    const idTypeEl = document.getElementById('ag-id-type');
    const idExpireEl = document.getElementById('ag-id-expire');
    const birthEl = document.getElementById('ag-birth');

    if (nameEl) nameEl.value = g.full_name || '';
    if (genderEl) genderEl.value = g.gender || '';
    if (nationalityEl) nationalityEl.value = g.nationality || 'VNM - Việt Nam';
    if (cccdEl) cccdEl.value = g.cccd || '';
    if (phoneEl) phoneEl.value = g.phone || '';
    if (addressEl) addressEl.value = g.address || '';
    if (notesEl) notesEl.value = g.notes || '';
    if (idTypeEl) idTypeEl.value = (g.id_type || 'cccd').toLowerCase();
    if (idExpireEl) {
        idExpireEl.value = g.id_expire ? String(g.id_expire).slice(0, 10) : '';
        agCheckIdExpire(idExpireEl);
    }
    if (birthEl && g.birth_date) {
        birthEl.value = String(g.birth_date).slice(0, 10);
        agCheckBirth(birthEl);
    }

    // Invoice
    if (g.tax_code || g.invoice_contact) {
        const radio1 = document.querySelector('input[name="ag-invoice"][value="1"]');
        if (radio1) { radio1.checked = true; agToggleInvoice(radio1); }
        const taxCodeEl = document.getElementById('ag-tax-code');
        const taxContactEl = document.getElementById('ag-tax-contact');
        if (taxCodeEl) taxCodeEl.value = g.tax_code || '';
        if (taxContactEl) taxContactEl.value = g.invoice_contact || '';
    } else {
        const radio0 = document.querySelector('input[name="ag-invoice"][value="0"]');
        if (radio0) { radio0.checked = true; agToggleInvoice(radio0); }
        ['ag-tax-code','ag-tax-contact'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    }

    // ── Address: detect mode (sync — values from object, no cascade needed) ──
    const hasOldData = !!(g.old_city || g.old_ward || g.old_district);
    const addrType = hasOldData ? 'old' : 'new';

    const oldRadio = document.querySelector('input[name="ag-area"][value="old"]');
    const newRadio = document.querySelector('input[name="ag-area"][value="new"]');
    const distGrp = document.getElementById('ag-grp-district');
    const convGrp = document.getElementById('ag-conversion-grp');

    if (addrType === 'old') {
        if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = false; }
        if (newRadio) newRadio.disabled = false;
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = 'none';
    } else {
        if (newRadio) { newRadio.checked = true; }
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
        if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }
    }

    // ── Fill address fields ────────────────────────────────────────────
    const pEl = document.getElementById('ag-province');
    const dEl = document.getElementById('ag-district');
    const wEl = document.getElementById('ag-ward');
    const nProvEl = document.getElementById('ag-new-province');
    const nWardEl = document.getElementById('ag-new-ward');

    if (addrType === 'old') {
        if (typeof agLoadOldProvinces === 'function') {
            const oldProvinces = await agLoadOldProvinces();
            agPopulateDatalist('dl-ag-province', oldProvinces);
        }
        if (nProvEl) { nProvEl.value = g.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = g.ward || ''; nWardEl.style.color = '#15803d'; }
        if (pEl) pEl.value = g.old_city || '';
        if (pEl && typeof agOnOldProvinceChange === 'function') await agOnOldProvinceChange(pEl);
        if (dEl) dEl.value = g.old_district || '';
        if (dEl && typeof agOnOldDistrictChange === 'function') await agOnOldDistrictChange(dEl);
        if (wEl) wEl.value = g.old_ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ag-ward');
            if (dl) {
                for (const opt of dl.options) {
                    if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                        wEl.value = opt.value; break;
                    }
                }
            }
            wEl.dispatchEvent(new Event('blur'));
        }
        if (dEl) dEl.dispatchEvent(new Event('blur'));
        if (pEl) pEl.dispatchEvent(new Event('blur'));
    } else {
        if (typeof agLoadNewProvinces === 'function') {
            const provinces = await agLoadNewProvinces();
            agPopulateDatalist('dl-ag-province', provinces.map(p => ({ name: p.name, short: p.short })));
        }
        if (pEl) pEl.value = g.city || '';
        if (pEl && typeof agOnNewProvinceChange === 'function') await agOnNewProvinceChange(pEl);
        if (wEl) wEl.value = g.ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ag-ward');
            if (dl) {
                for (const opt of dl.options) {
                    if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                        wEl.value = opt.value; break;
                    }
                }
            }
            wEl.dispatchEvent(new Event('blur'));
        }
        if (pEl) pEl.dispatchEvent(new Event('blur'));
    }

    // ── Toggle ID fields (only for new guests being edited) ────────────
    if (!isExistingGuest && idTypeEl) agToggleIdFields(idTypeEl);
    else if (isExistingGuest && idTypeEl) agToggleIdFields(idTypeEl);

    // ── Phase 2: Lock / Unlock based on guest type ─────────────────────
    if (isExistingGuest) {
        _agIsOldGuest = true;
        agLockAllFields();
        // Force lock critical fields AFTER lockAllFields
        if (idTypeEl) idTypeEl.disabled = true;
        if (cccdEl) { cccdEl.value = g.cccd || ''; cccdEl.readOnly = true; }
        // Unlock ONLY editable fields
        ['ag-phone','ag-notes'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.readOnly = false;
        });
        if (idExpireEl) {
            const expireGrp = document.getElementById('ag-grp-expire');
            if (expireGrp && expireGrp.style.display !== 'none') idExpireEl.readOnly = false;
        }
        // Unlock invoice
        document.querySelectorAll('input[name="ag-invoice"]').forEach(r => r.disabled = false);
        ['ag-tax-code','ag-tax-contact'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.readOnly = false;
        });
        if (typeof agShowAutofillNotice === 'function') agShowAutofillNotice(g.full_name, g.cccd);
    } else {
        _agIsOldGuest = false;
        agUnlockAllFields();
        const existingNotice = document.getElementById('ag-autofill-notice');
        if (existingNotice) existingNotice.remove();
    }

    agSetEditMode(true, g.full_name);
    agRenderGuestList();
    pmsToast('Đang sửa khách. Bấm "Cập nhật" để lưu.');
}
window.agEditGuest = agEditGuest;

async function agUpdateGuest() {
    if (_agEditIndex === null) return;

    const g = agGetFormGuest();
    const v = agValidateGuestForm(g);
    if (!v.valid) return;

    // ── Duplicate in list (excluding self) ─────────────────────────────
    if (g.cccd && agGuestList.some((xg, i) => i !== _agEditIndex && xg.cccd === g.cccd)) {
        pmsToast(`Số giấy tờ ${g.cccd} bị trùng với người khác trong danh sách.`, false);
        return;
    }

    // ── Real-time active CCCD check ────────────────────────────────────
    if (g.cccd && g.cccd.length >= 3) {
        try {
            const stayId = document.getElementById('ag-stay-id')?.value;
            let url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
            if (stayId && !isNaN(parseInt(stayId))) url += `&exclude_stay_id=${stayId}`;
            const res = await pmsApi(url);
            if (res.is_active) {
                pmsToast(`Khách hàng có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể Cập nhật.`, false);
                return;
            }
        } catch(e) {
            console.error('[AG] Error checking active CCCD', e);
            pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
            return;
        }
    }

    // ── Apply update ────────────────────────────────────────────────────
    agGuestList[_agEditIndex] = {
        ...agGuestList[_agEditIndex],
        ...g,
        id: agGuestId
    };

    _agEditIndex = null;
    agGuestId = null;
    _agIsOldGuest = false;
    agSetEditMode(false);
    agRefreshGuestForm();
    agRenderGuestList();
    pmsToast('Đã cập nhật thông tin khách');
}
window.agUpdateGuest = agUpdateGuest;

function agCancelEdit() {
    _agEditIndex = null;
    agGuestId = null;
    _agIsOldGuest = false;
    agUnlockAllFields();
    agRefreshGuestForm();
    agSetEditMode(false);
}
window.agCancelEdit = agCancelEdit;

// ─────────────────────────────────────────────────────────────────────────────
// Remove Guest
// ─────────────────────────────────────────────────────────────────────────────

function agRemoveGuest(i) {
    const g = agGuestList[i];
    if (!g) return;
    if (g.id) { pmsToast('Không thể xoá khách đã lưu từ Modal này. Vui lòng checkout khách trước.', false); return; }
    if (g.is_primary) { pmsToast('Không thể xoá khách chính.', false); return; }
    if (!confirm(`Bạn có chắc muốn xoá khách "${g.full_name}"?`)) return;
    agGuestList.splice(i, 1);
    if (_agEditIndex === i) agCancelEdit();
    agRenderGuestList();
    agUpdateCapacityWarn();
}
window.agRemoveGuest = agRemoveGuest;

// ─────────────────────────────────────────────────────────────────────────────
// ─── CCCD QR Scan ───────────────────────────────────────────────────────────

function agScanCode() {
    openScanModal(async (parsed) => {
        await agFillFromScan(parsed);
        pmsToast(`Đã quét: ${parsed.name}`, true);
    });
}

// ─── Fill AG form from parsed CCCD scan ─────────────────────────────────────────

async function agFillFromScan(parsed) {
    if (!parsed.is_valid) return;

    const cccdEl  = document.getElementById('ag-cccd');
    const idTypeEl = document.getElementById('ag-id-type');
    const expireEl  = document.getElementById('ag-id-expire');
    const nameEl    = document.getElementById('ag-name');
    const genderEl  = document.getElementById('ag-gender');
    const birthEl   = document.getElementById('ag-birth');

    const isCmnd = parsed.card_type === 'CMND';
    const idValue = isCmnd ? (parsed.old_id || parsed.id_number || parsed.cccd || '') : (parsed.id_number || parsed.cccd || '');
    if (cccdEl) {
        cccdEl.value = idValue;
        cccdEl.classList.remove('is-invalid');
    }
    if (idTypeEl) {
        idTypeEl.value = isCmnd ? 'cmnd' : 'cccd';
        if (typeof agToggleIdFields === 'function') agToggleIdFields(idTypeEl);
    }
    if (expireEl && parsed.expiry_date && parsed.expiry_date !== 'Không thời hạn') {
        expireEl.value = pmsScanDateToISO(parsed.expiry_date);
        if (typeof agCheckIdExpire === 'function') agCheckIdExpire(expireEl);
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
        if (typeof agCheckBirth === 'function') agCheckBirth(birthEl);
    }

    // ── Address matching: switch mode + fill fields based on card_type ──
    const cardType = parsed.card_type || 'CCCD_CU';
    if (typeof pmsMatchAddressToForm === 'function') {
        await pmsMatchAddressToForm(parsed.address, 'ag', cardType);
    }

    // ── Validate address fields after scan ──
    // Show warning if any address field is not in datalist
    setTimeout(() => {
        if (typeof pmsShowAddressValidationIssues === 'function') {
            pmsShowAddressValidationIssues('ag');
        }
    }, 100);

    const phoneEl = document.getElementById('ag-phone');
    if (phoneEl) phoneEl.focus();
}

window.agScanCode = agScanCode;
window.agFillFromScan = agFillFromScan;

// ─────────────────────────────────────────────────────────────────────────────
// Submit All Guests
// ─────────────────────────────────────────────────────────────────────────────

async function submitAG() {
    console.log('[submitAG] ===== START submitAG =====');

    try {
        const stayId = document.getElementById('ag-stay-id')?.value;
        if (!stayId) { pmsToast('Thiếu stay ID', false); return; }

        const formGuest = agGetFormGuest();
        const hasFormGuest = !!formGuest.full_name;
        const allGuests = [...agGuestList];

        console.log('[submitAG] formGuest:', JSON.stringify(formGuest));
        console.log('[submitAG] hasFormGuest:', hasFormGuest);
        console.log('[submitAG] agGuestList length:', agGuestList.length);
        console.log('[submitAG] agGuestList:', JSON.stringify(agGuestList.map(g => ({ name: g.full_name, cccd: g.cccd }))));

        // ── TRƯỜNG HỢP 1: Form có thông tin khách đang nhập ───────────
        if (hasFormGuest) {
            console.log('[submitAG] Processing form guest (hasFormGuest = true)');

            const v = agValidateGuestForm(formGuest);
            if (!v.valid) return;

            // Check duplicate in local list
            const formCccd = (formGuest.cccd || '').trim().toUpperCase();
            if (formCccd) {
                const foundIndex = agGuestList.findIndex(
                    xg => (xg.cccd || '').trim().toUpperCase() === formCccd
                );
                if (foundIndex !== -1) {
                    window.alert(`CẢNH BÁO: Khách với số giấy tờ ${formGuest.cccd} đã có trong danh sách.\n\nVui lòng xóa khách khỏi danh sách trước hoặc chọn khách trong danh sách để chỉnh sửa.`);
                    pmsToast(`Khách ${formGuest.cccd} đã có trong danh sách. Không thể thêm trùng.`, false);
                    return;
                }
            }

            // Real-time active CCCD check
            if (formGuest.cccd && formGuest.cccd.length >= 3) {
                try {
                    let url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(formGuest.cccd)}&exclude_stay_id=${stayId}`;
                    const res = await pmsApi(url);
                    console.log('[submitAG] Active CCCD check result:', res);
                    if (res && res.is_active) {
                        if (res.room_number === agRoomNum) {
                            window.alert(`CẢNH BÁO: Khách ${formGuest.cccd} đã có trong danh sách phòng ${agRoomNum}. Không thể thêm trùng.`);
                            pmsToast(`Khách ${formGuest.cccd} đã có trong danh sách phòng ${agRoomNum}. Không thể thêm trùng.`, false);
                        } else {
                            window.alert(`CẢNH BÁO: Khách ${formGuest.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`);
                            pmsToast(`Khách hàng có số giấy tờ ${formGuest.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm khách.`, false);
                        }
                        return;
                    }
                } catch(e) {
                    console.error('[submitAG] CCCD check error', e);
                    pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
                    return;
                }
            }

            // Add form guest as new entry
            allGuests.unshift(formGuest);
            console.log('[submitAG] Added form guest to list, allGuests length:', allGuests.length);
        }

        // ── TRƯỜNG HỢP 2: Form trống hoàn toàn + danh sách trống ───────
        if (!hasFormGuest && agGuestList.length === 0) {
            const cccdEl = document.getElementById('ag-cccd');
            const idTypeEl = document.getElementById('ag-id-type');
            const idExpireEl = document.getElementById('ag-id-expire');
            const nameEl = document.getElementById('ag-name');
            const genderEl = document.getElementById('ag-gender');
            const birthEl = document.getElementById('ag-birth');
            const natEl = document.getElementById('ag-nationality');
            const provEl = document.getElementById('ag-province');
            const wardEl = document.getElementById('ag-ward');
            const addrEl = document.getElementById('ag-address');

            const isForeign = (idTypeEl?.value) === 'passport' || (idTypeEl?.value) === 'visa';
            const isOldGuest = _agIsOldGuest === true;

            if (!cccdEl?.value.trim()) { cccdEl?.classList.add('is-invalid'); cccdEl?.focus(); alert('Vui lòng nhập Số giấy tờ'); return; }
            if (!idTypeEl?.value) { idTypeEl?.classList.add('is-invalid'); idTypeEl?.focus(); alert('Vui lòng chọn Loại giấy tờ'); return; }
            const noExpire = idTypeEl?.value === 'cmnd' || idTypeEl?.value === 'gplx';
            if (!noExpire && !idExpireEl?.value) { idExpireEl?.classList.add('is-invalid'); idExpireEl?.focus(); alert('Vui lòng nhập Ngày hết hạn giấy tờ'); return; }
            if (!nameEl?.value.trim()) { nameEl?.classList.add('is-invalid'); nameEl?.focus(); alert('Vui lòng nhập Họ và tên'); return; }
            if (!genderEl?.value) { genderEl?.classList.add('is-invalid'); genderEl?.focus(); alert('Vui lòng chọn Giới tính'); return; }
            if (!birthEl?.value) { birthEl?.classList.add('is-invalid'); birthEl?.focus(); alert('Vui lòng nhập Ngày sinh'); return; }
            if (!natEl?.value.trim()) { natEl?.classList.add('is-invalid'); natEl?.focus(); alert('Vui lòng chọn Quốc tịch'); return; }

            if (!isForeign && !isOldGuest) {
                if (!provEl?.value.trim()) { provEl?.classList.add('is-invalid'); provEl?.focus(); alert('Vui lòng chọn Tỉnh/Thành phố'); return; }
                if (typeof agIsInDatalist === 'function' && !agIsInDatalist('dl-ag-province', provEl.value)) {
                    provEl.classList.add('is-invalid'); provEl.focus();
                    alert(`"${provEl.value}" không có trong danh sách!\n\nVui lòng chọn Tỉnh/Thành phố từ danh sách gợi ý.`); return;
                }
                if (!wardEl?.value.trim()) { wardEl?.classList.add('is-invalid'); wardEl?.focus(); alert('Vui lòng chọn Phường/Xã'); return; }
                if (typeof agIsInDatalist === 'function' && !agIsInDatalist('dl-ag-ward', wardEl.value)) {
                    wardEl.classList.add('is-invalid'); wardEl.focus();
                    alert(`"${wardEl.value}" không có trong danh sách!\n\nVui lòng chọn Phường/Xã từ danh sách gợi ý.`); return;
                }
                if (!addrEl?.value.trim()) { addrEl?.classList.add('is-invalid'); addrEl?.focus(); alert('Vui lòng nhập Địa chỉ chi tiết'); return; }
            }
        }

        // ── TRƯỜNG HỢP 3: Form có partial data nhưng không có tên ─────
        else if (formGuest.cccd || formGuest.phone || formGuest.address ||
                 formGuest.birth_date || (formGuest.id_type && formGuest.id_type !== 'cccd')) {
            if (!formGuest.full_name) {
                pmsToast('Vui lòng nhập đầy đủ thông tin khách (Họ tên, CCCD, ngày sinh...) hoặc xoá các trường đã nhập.', false);
                const nameEl = document.getElementById('ag-name');
                if (nameEl) { nameEl.classList.add('is-invalid'); nameEl.focus(); }
                return;
            }
        }

        // ── Capacity check ───────────────────────────────────────────────
        if (allGuests.length === 0) {
            pmsToast('Vui lòng nhập thông tin khách và bấm "Thêm khách" để tiếp tục.', false);
            return;
        }
        if (allGuests.length > agMaxGuests) {
            agUpdateCapacityWarn();
        }

        // ── Duplicate CCCD within all guests list ────────────────────────
        const cccdMap = {};
        for (let i = 0; i < allGuests.length; i++) {
            const guest = allGuests[i];
            if (guest.cccd && guest.cccd.length >= 3) {
                const up = (guest.cccd || '').trim().toUpperCase();
                if (!cccdMap[up]) cccdMap[up] = [];
                cccdMap[up].push(i);
            }
        }
        for (const cccd in cccdMap) {
            if (cccdMap[cccd].length > 1) {
                const indices = cccdMap[cccd];
                const names = indices.map(i => `"${allGuests[i].full_name}"`).join(', ');
                window.alert(`CẢNH BÁO: Số giấy tờ ${cccd} bị trùng lặp trong danh sách khách (${indices.length} lần): ${names}.\n\nVui lòng xóa bớt các khách trùng lặp.`);
                pmsToast(`Số giấy tờ ${cccd} bị trùng lặp ${indices.length} lần trong danh sách. Vui lòng xóa bớt.`, false);
                return;
            }
        }

        // ── Validate all guests in list ────────────────────────────────
        for (let i = 0; i < allGuests.length; i++) {
            const g = allGuests[i];
            if (!g.full_name || !g.cccd || !g.gender || !g.birth_date) {
                const guestName = g.full_name || `Khách thứ ${i + 1}`;
                window.alert(`Thông tin khách "${guestName}" chưa đầy đủ (thiếu Họ tên, Số giấy tờ, Giới tính hoặc Ngày sinh). Vui lòng kiểm tra lại.`);
                pmsToast(`Khách "${guestName}" thiếu thông tin bắt buộc.`, false);
                if (i === 0 && hasFormGuest) {
                    document.getElementById('ag-name')?.focus();
                } else {
                    const listIdx = hasFormGuest ? i - 1 : i;
                    agEditGuest(listIdx);
                }
                return;
            }
        }

        // ── Submit button loading state ─────────────────────────────────
        const submitBtn = document.getElementById('ag-submit-btn');
        let oriText = 'Lưu tất cả khách';
        if (submitBtn) {
            oriText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm" style="margin-right:8px;" role="status" aria-hidden="true"></span> Đang xử lý...`;
            submitBtn.style.opacity = '0.7';
        }

        // ── Separate new vs existing guests ────────────────────────────
        // Existing guests (have DB id) were already saved — skip them
        // Only POST new guests (no id)
        const newGuests = allGuests.filter(g => !g.id);
        const existingGuests = allGuests.filter(g => !!g.id);

        if (newGuests.length === 0) {
            pmsToast('Không có khách mới để lưu.', true);
            if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = oriText; submitBtn.style.opacity = '1'; }
            if (typeof closeModal === 'function') closeModal('agModal');
            else if (typeof pmsCloseModal === 'function') pmsCloseModal('agModal');
            else document.getElementById('agModal')?.classList.remove('show');
            return;
        }

        // ── Check active CCCDs for new guests in DB ────────────────────
        for (const g of newGuests) {
            if (g.cccd && g.cccd.length >= 3) {
                try {
                    const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}&exclude_stay_id=${stayId}`;
                    console.log('[submitAG] Checking CCCD:', g.cccd, 'URL:', url);
                    const res = await pmsApi(url);
                    console.log('[submitAG] CCCD check result:', res);
                    if (res && res.is_active) {
                        pmsToast(`Khách "${g.full_name}" có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}. Không thể thêm.`, false);
                        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = oriText; submitBtn.style.opacity = '1'; }
                        return;
                    }
                } catch(e) {
                    console.error('[submitAG] CCCD check error', e);
                }
            }
        }

        // ── POST each new guest ─────────────────────────────────────────
        let savedCount = 0;
        for (const g of newGuests) {
            const fd = new FormData();
            fd.append('full_name', g.full_name);
            fd.append('id_type', g.id_type || 'cccd');
            fd.append('cccd', g.cccd || '');
            fd.append('id_expire', g.id_expire || '');
            fd.append('gender', g.gender || '');
            fd.append('birth_date', g.birth_date || '');
            fd.append('phone', g.phone || '');
            fd.append('address', g.address || '');
            fd.append('address_type', g.address_type || 'new');
            fd.append('nationality', g.nationality || 'VNM - Việt Nam');
            fd.append('city', g.city || '');
            fd.append('ward', g.ward || '');
            fd.append('district', g.district || '');
            if (g.old_city) fd.append('old_city', g.old_city);
            if (g.old_district) fd.append('old_district', g.old_district);
            if (g.old_ward) fd.append('old_ward', g.old_ward);
            if (g.new_city) fd.append('new_city', g.new_city);
            if (g.new_ward) fd.append('new_ward', g.new_ward);
            if (g.tax_code) fd.append('tax_code', g.tax_code);
            if (g.invoice_contact) fd.append('invoice_contact', g.invoice_contact);
            if (g.notes) fd.append('notes', g.notes);

            await pmsApi(`/api/pms/stays/${stayId}/guests`, { method: 'POST', body: fd });
            savedCount++;
        }

        console.log(`[submitAG] Saved ${savedCount} new guests, ${existingGuests.length} existing guests skipped`);

        // ── Reload room detail ──────────────────────────────────────────
        if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(null, agRoomNum);
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
        if (typeof openRoomDetail === 'function') openRoomDetail(parseInt(stayId), agRoomNum);

        const msg = newGuests.length > 1
            ? `Lưu thành công ${newGuests.length} khách mới`
            : `Lưu khách "${newGuests[0]?.full_name}" thành công`;
        pmsToast(msg, true);

        if (typeof closeModal === 'function') closeModal('agModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('agModal');
        else document.getElementById('agModal')?.classList.remove('show');

    } catch (e) {
        console.error('[submitAG] OUTER ERROR:', e);
        pmsToast('Lỗi: ' + e.message, false);
    } finally {
        const submitBtn = document.getElementById('ag-submit-btn');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = 'Lưu tất cả khách';
            submitBtn.style.opacity = '1';
        }
    }
}
window.submitAG = submitAG;

// ─────────────────────────────────────────────────────────────────────────────
// Autofill Notice (TRUSTED DATA banner)
// ─────────────────────────────────────────────────────────────────────────────

function agShowAutofillNotice(name, cccd) {
    const existing = document.getElementById('ag-autofill-notice');
    if (existing) existing.remove();

    const infoBar = document.getElementById('ag-section-stay');
    if (!infoBar) return;

    const notice = document.createElement('div');
    notice.id = 'ag-autofill-notice';
    notice.style.cssText = `
        background: linear-gradient(135deg, #f0fdf4, #dcfce7);
        border: 1px solid #86efac;
        border-radius: 8px;
        padding: 10px 14px; margin-bottom: 12px;
        display: flex; align-items: center; gap: 10px; font-size: 13px;
    `;
    notice.innerHTML = `
        <div style="width:32px;height:32px;background:#22c55e;border-radius:50%;display:flex;align-items:center;justify-content:center;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
        </div>
        <div style="flex:1;">
            <div style="font-weight:600;color:#15803d;">Dữ liệu từ lưu trú trước</div>
            <div style="color:#64748b;font-size:12px;">Khách <strong>${name || cccd}</strong> - Địa chỉ đã được xác nhận từ hệ thống</div>
        </div>
    `;
    infoBar.insertBefore(notice, infoBar.firstChild);
}
window.agShowAutofillNotice = agShowAutofillNotice;

// ─────────────────────────────────────────────────────────────────────────────
// Enter key listener: CCCD → search
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        const el = e.target;
        if (el && el.id === 'ag-cccd') {
            e.preventDefault();
            if (typeof agSearchOldGuest === 'function') agSearchOldGuest();
        }
    }
});
