// static/js/pms/pms_checkin.js
// PMS Check-in - Check-in modal, guest management, price calculation
'use strict';

let pmsCi = {};
let pmsCiGuestList = [];
let pmsCiMaxGuests = 2;

function openCI(id) {
    const r = PMS.roomMap[id]; if (!r) return;
    pmsCi = r;
    pmsCiMaxGuests = r.max_guests || 2;
    pmsCiGuestList = [];
    document.getElementById('ci-room-id').value=id;
    document.getElementById('ci-title').textContent='Nhận phòng nhanh';
    document.getElementById('ci-sub').textContent=`Phòng ${r.room_number} | ${r.room_type_name||'—'} | Tối đa ${pmsCiMaxGuests} khách`;
    const opt = document.getElementById('ci-room-type-opt');
    if (opt) { opt.textContent = r.room_type_name || '—'; opt.value = r.room_type_id || ''; }
    const rn = document.getElementById('ci-room-num');
    if (rn) rn.value = r.room_number || '';
    document.getElementById('ci-in').value=pmsToISO(new Date());
    const ciOut = document.getElementById('ci-out');
    if (ciOut) ciOut.value = '';
    document.getElementById('ci-deposit').value='0';
    document.getElementById('ci-notes').value='';
    document.getElementById('ci-price').textContent='0';
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    document.getElementById('ci-guest-list-panel').classList.remove('show');
    document.getElementById('ci-capacity-warn').classList.remove('show');
    if (typeof openModal === 'function') openModal('ciModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('ciModal');
    else document.getElementById('ciModal').classList.add('show');
}

function pmsCiGetFormGuest() {
    // Get invoice info
    const invoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    const taxCode = invoiceVal === '1' ? (document.getElementById('ci-tax-code')?.value?.trim() || '') : '';
    const invoiceContact = invoiceVal === '1' ? (document.getElementById('ci-tax-contact')?.value?.trim() || '') : '';
    
    return {
        full_name: document.getElementById('ci-name')?.value?.trim() || '',
        id_type: document.getElementById('ci-id-type')?.value || 'cccd',
        cccd: document.getElementById('ci-cccd')?.value?.trim() || '',
        id_expire: document.getElementById('ci-id-expire')?.value || '',
        gender: document.getElementById('ci-gender')?.value || '',
        birth_date: document.getElementById('ci-birth')?.value || '',
        phone: document.getElementById('ci-phone')?.value?.trim() || '',
        vehicle: document.getElementById('ci-vehicle')?.value?.trim() || '',
        city: document.getElementById('ci-province')?.value?.trim() || '',
        district: document.getElementById('ci-district')?.value?.trim() || '',
        ward: document.getElementById('ci-ward')?.value?.trim() || '',
        address: document.getElementById('ci-address')?.value?.trim() || '',
        address_type: document.querySelector('input[name="ci-area"]:checked')?.value || 'new',
        nationality: document.getElementById('ci-nationality')?.value?.trim() || 'VNM - Việt Nam',
        notes: document.getElementById('ci-guest-notes')?.value?.trim() || '',
        tax_code: taxCode,
        invoice_contact: invoiceContact
    };
}

function pmsCiRefreshGuestForm() {
    ['ci-name','ci-cccd','ci-id-expire','ci-birth','ci-phone','ci-guest-notes','ci-address','ci-province','ci-district','ci-ward','ci-vehicle'].forEach(id=>{
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const g = document.getElementById('ci-gender');
    if (g) g.value = '';
    
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
}

function pmsCiAddGuest() {
    const idx = window._ciEditIndex;
    if (idx !== undefined && idx !== null) {
        pmsCiUpdateGuest();
        return;
    }
    const g = pmsCiGetFormGuest();
    const v = pmsCiValidateGuestForm(g);
    if (!v.valid) {
        pmsToast(v.message, false);
        return;
    }

    const total = pmsCiGuestList.length + 1;
    if (total > pmsCiMaxGuests) {
        pmsToast(`Phòng này tối đa ${pmsCiMaxGuests} khách. Số người hiện tại (${total}) vượt giới hạn.`, false);
        pmsCiUpdateCapacityWarn();
        return;
    }
    pmsCiGuestList.push(g);
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
}

function pmsCiRenderGuestList() {
    const panel = document.getElementById('ci-guest-list-panel');
    if (!panel) return;
    if (pmsCiGuestList.length === 0) {
        panel.innerHTML = '<p style="margin:0;font-size:13px;color:#64748b;">Chưa thêm khách nào. Nhập thông tin và bấm "Thêm khách".</p>';
        return;
    }
    panel.innerHTML = pmsCiGuestList.map((g,i)=>`
        <span class="guest-chip">
          <span class="ci-chip-icon">${pmsGenderIcon(g.gender)}</span>
          <span onclick="pmsCiEditGuest(${i})" style="cursor:pointer;">${pmsEscapeHtml(g.full_name)}</span>${g.phone ? ` <span style="color:#64748b;">${pmsEscapeHtml(g.phone)}</span>` : ''}
          <button type="button" onclick="pmsCiRemoveGuest(${i})" style="background:none;border:none;cursor:pointer;padding:0 4px;color:#94a3b8;font-size:16px;line-height:1;" title="Xóa">×</button>
        </span>
    `).join('');
}

function pmsCiEditGuest(i) {
    const g = pmsCiGuestList[i];
    if (!g) return;
    document.getElementById('ci-name').value = g.full_name || '';
    document.getElementById('ci-gender').value = g.gender || '';
    document.getElementById('ci-birth').value = g.birth_date || '';
    document.getElementById('ci-phone').value = g.phone || '';
    document.getElementById('ci-cccd').value = g.cccd || '';
    document.getElementById('ci-add-guest-btn').style.display = 'none';
    document.getElementById('ci-update-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-cancel-edit-btn').style.display = 'inline-flex';
    window._ciEditIndex = i;
    pmsToast('Đang chỉnh sửa khách. Bấm "Cập nhật" để lưu.');
}

function pmsCiCancelEdit() {
    window._ciEditIndex = null;
    pmsCiRefreshGuestForm();
    document.getElementById('ci-add-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-update-guest-btn').style.display = 'none';
    document.getElementById('ci-cancel-edit-btn').style.display = 'none';
}

function pmsCiUpdateGuest() {
    const idx = window._ciEditIndex;
    if (idx === undefined || idx === null || idx < 0 || idx >= pmsCiGuestList.length) {
        pmsToast('Không tìm thấy khách cần cập nhật', false);
        return;
    }
    const g = pmsCiGetFormGuest();
    const v = pmsCiValidateGuestForm(g);
    if (!v.valid) {
        pmsToast(v.message, false);
        return;
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
    pmsToast('Chức năng quét mã (F1) có thể tích hợp sau với thiết bị đọc CCCD.', true);
}

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
    const ciV=document.getElementById('ci-in')?.value;
    const coV=document.getElementById('ci-out')?.value;
    const st = coV ? 'night' : 'hour';
    const el=document.getElementById('ci-price'); if(!el) return;
    if(!ciV||!coV){el.textContent='0';return;}
    const ms=new Date(coV)-new Date(ciV); if(ms<=0){el.textContent='0';return;}

    let p = 0;
    if (st === 'hour') {
        const hours = Math.max(pmsCi.min_hours||1, Math.ceil(ms/3600000));
        p = (pmsCi.price_per_hour||0)*(pmsCi.min_hours||1) + (pmsCi.price_next_hour||0)*Math.max(0, hours-(pmsCi.min_hours||1));
    } else {
        const nights = Math.max(1, Math.ceil(ms/86400000));
        let ppN = pmsCi.price_per_night||0;

        if (pmsCi.promo_start_time && pmsCi.promo_end_time && (pmsCi.promo_discount_percent||0) > 0) {
            const timeStr = ciV.split('T')[1].substring(0,5);
            const startStr = pmsCi.promo_start_time.substring(0,5);
            const endStr = pmsCi.promo_end_time.substring(0,5);
            let isPromo = false;
            if (startStr <= endStr) { if (startStr <= timeStr && timeStr <= endStr) isPromo = true; }
            else { if (timeStr >= startStr || timeStr <= endStr) isPromo = true; }
            if (isPromo) ppN = ppN * (1 - pmsCi.promo_discount_percent / 100);
        }
        p = ppN * nights;
    }
    el.textContent=pmsMoney(p);
}

async function submitCI() {
    // Check-in Time is required
    const ciAt = document.getElementById('ci-in').value;
    if (!ciAt) { pmsToast('Vui lòng chọn Thời gian nhận phòng', false); return; }

    const formGuest = pmsCiGetFormGuest();
    const hasFormGuest = !!formGuest.full_name;
    const allGuests = [...pmsCiGuestList];
    if (hasFormGuest) {
        const v = pmsCiValidateGuestForm(formGuest);
        if (!v.valid) {
            pmsToast('Khách đang nhập: ' + v.message, false);
            return;
        }
        allGuests.unshift(formGuest);
    } else if (formGuest.cccd || formGuest.phone || formGuest.address) {
        pmsToast('Vui lòng nhập đầy đủ họ tên cho khách trên form, hoặc xoá các trường.', false); return;
    }
    if (allGuests.length === 0) {
        pmsToast('Vui lòng nhập ít nhất một khách (hoặc thêm khách vào danh sách).', false);
        return;
    }
    if (allGuests.length > pmsCiMaxGuests) {
        pmsToast(`Số khách (${allGuests.length}) vượt giới hạn phòng (tối đa ${pmsCiMaxGuests} người).`, false);
        pmsCiUpdateCapacityWarn();
        return;
    }
    const primary = allGuests[0];
    const fd=new FormData();
    const coV = document.getElementById('ci-out').value || '';
    fd.append('room_id', document.getElementById('ci-room-id').value);
    fd.append('stay_type', coV ? 'night' : 'hour');
    fd.append('check_in_at', document.getElementById('ci-in').value);
    const co_val = document.getElementById('ci-out').value;
    if (co_val) fd.append('check_out_at', co_val);
    
    // Deposit handling: remove dots/commas
    const rawDeposit = document.getElementById('ci-deposit').value || '0';
    const depositNum = rawDeposit.toString().replace(/[^0-9]/g, '');
    fd.append('deposit', depositNum);
    
    fd.append('notes', document.getElementById('ci-notes').value||'');
    
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

    fd.append('guest_name', primary.full_name);
    fd.append('guest_cccd', primary.cccd||'');
    if(primary.id_expire) fd.append('guest_id_expire', primary.id_expire);
    fd.append('guest_gender', primary.gender||'');
    fd.append('guest_birth', primary.birth_date||'');
    fd.append('guest_phone', primary.phone||'');
    
    // Send existing guest ID if found (for auto-update)
    if (window._pmsCiExistingGuestId) {
        fd.append('guest_id', window._pmsCiExistingGuestId);
    }
    
    // Round 4 Guest fields
    fd.append('vehicle', primary.vehicle);
    fd.append('city', primary.city);
    fd.append('district', primary.district);
    fd.append('ward', primary.ward);
    fd.append('address', primary.address);
    fd.append('address_type', primary.address_type);
    fd.append('guest_notes', primary.notes || '');
    const extra = allGuests.slice(1);
    if (extra.length) fd.append('extra_guests', JSON.stringify(extra));
    try {
        const r=await pmsApi('/api/pms/checkin',{method:'POST',body:fd});
        if (typeof closeModal === 'function') closeModal('ciModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('ciModal');
        else document.getElementById('ciModal').classList.remove('show');
        pmsToast(r.message); await pmsLoadRooms();
    } catch(e){pmsToast(e.message,false);}
}

// Export globally
window.openCI = openCI;
window.submitCI = submitCI;
window.pmsCalcPrice = pmsCalcPrice;

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
    const expireEl = document.getElementById('ci-grp-expire');
    const areaEl = document.getElementById('ci-grp-area');
    const addrEl = document.getElementById('ci-grp-address');
    const provEl = document.getElementById('ci-grp-province');
    const wardEl = document.getElementById('ci-grp-ward');

    if (expireEl) expireEl.style.display = isForeign ? 'flex' : 'none';
    if (areaEl) areaEl.style.display = isForeign ? 'none' : 'flex';
    if (addrEl) addrEl.style.display = isForeign ? 'none' : 'flex';
    if (provEl) provEl.style.display = isForeign ? 'none' : 'flex';
    if (wardEl) wardEl.style.display = isForeign ? 'none' : 'flex';
}
window.pmsCiToggleIdFields = pmsCiToggleIdFields;

function pmsCiToggleInvoice(radio) {
    const val = radio.value;
    const taxEl = document.getElementById('ci-grp-tax');
    const contactEl = document.getElementById('ci-grp-tax-contact');
    
    if (taxEl) taxEl.style.display = val === '1' ? 'flex' : 'none';
    if (contactEl) contactEl.style.display = val === '1' ? 'flex' : 'none';
}
window.pmsCiToggleInvoice = pmsCiToggleInvoice;
function pmsCiToggleArea(val) {
    const isOld = val === 'old';
    const distEl = document.getElementById('ci-grp-district');
    const lblProv = document.getElementById('ci-lbl-province');
    const lblWard = document.getElementById('ci-lbl-ward');

    if (distEl) distEl.style.display = isOld ? 'block' : 'none';
    if (lblProv) lblProv.innerHTML = isOld ? 'Tỉnh/Thành phố cũ' : 'Tỉnh/Thành phố';
    if (lblWard) lblWard.innerHTML = isOld ? 'Phường/Xã cũ' : 'Phường/Xã';
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
    const type = document.getElementById('ci-id-type')?.value || 'cccd';
    let val = input.value.replace(/\s+/g, ''); // Luôn xoá khoảng trắng
    
    if (type === 'cccd') {
        val = val.replace(/\D/g, '').slice(0, 12); // Chỉ số, tối đa 12
    } else if (type === 'cmnd') {
        val = val.replace(/\D/g, '').slice(0, 9); // Chỉ số, tối đa 9
    }
    
    input.value = val.toUpperCase(); // Luôn in hoa
}
window.pmsCiFormatID = pmsCiFormatID;

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
    if (!input) return true;
    const type = document.getElementById('ci-id-type')?.value || 'cccd';
    const val = input.value.trim();
    if (!val) {
        input.classList.remove('is-invalid');
        return true;
    }
    
    let isValid = true;
    let msg = '';
    
    if (type === 'cccd' && val.length !== 12) {
        isValid = false;
        msg = 'Số CCCD phải có đúng 12 chữ số!';
    } else if (type === 'cmnd' && val.length !== 9) {
        isValid = false;
        msg = 'Số CMND phải có đúng 9 chữ số!';
    }
    
    if (!isValid) {
        input.classList.add('is-invalid');
    } else {
        input.classList.remove('is-invalid');
    }
    return { valid: isValid, message: msg };
}
window.pmsCiValidateID = pmsCiValidateID;

function pmsCiValidateGuestForm(g) {
    if (!g.full_name) return { valid: false, message: 'Vui lòng nhập Họ và tên' };
    if (!g.gender) return { valid: false, message: 'Vui lòng chọn Giới tính' };
    if (!g.birth_date) return { valid: false, message: 'Vui lòng nhập Ngày sinh' };
    if (!g.nationality) return { valid: false, message: 'Vui lòng chọn Quốc tịch' };
    if (!g.id_type) return { valid: false, message: 'Vui lòng chọn Loại giấy tờ' };
    if (!g.cccd) return { valid: false, message: 'Vui lòng nhập Số giấy tờ' };
    
    // Check ID Length/Specific logic
    const idInput = document.getElementById('ci-cccd');
    const idValid = pmsCiValidateID(idInput);
    if (!idValid.valid) return idValid;

    const isForeign = g.id_type === 'passport' || g.id_type === 'visa';
    if (isForeign) {
        if (!g.id_expire) return { valid: false, message: 'Vui lòng nhập Ngày hết hạn giấy tờ' };
    } else {
        if (!g.address) return { valid: false, message: 'Vui lòng nhập Địa chỉ chi tiết' };
    }

    return { valid: true, message: '' };
}
window.pmsCiValidateGuestForm = pmsCiValidateGuestForm;

// ─────────────────────────────────────────────────────────────────────────────
// Guest Search & Duplicate Check Functions
// ─────────────────────────────────────────────────────────────────────────────

// Debounce timer for search
let pmsCiSearchTimeout = null;

// Check for duplicate CCCD and auto-fill guest info
async function pmsCiCheckGuestByCCCD(input) {
    const cccd = input.value?.trim();
    if (!cccd || cccd.length < 3) {
        const hintEl = document.getElementById('ci-cccd-hint');
        if (hintEl) hintEl.remove();
        return;
    }
    
    if (pmsCiSearchTimeout) {
        clearTimeout(pmsCiSearchTimeout);
    }
    
    pmsCiSearchTimeout = setTimeout(async () => {
        try {
            const r = await pmsApi(`/api/pms/guests/check-cccd?cccd=${encodeURIComponent(cccd)}`);
            
            const existingHint = document.getElementById('ci-cccd-hint');
            if (existingHint) existingHint.remove();
            
            if (r.exists && r.guest) {
                // Auto-fill guest data without prompting
                pmsCiFillGuestFromOld(JSON.stringify(r.guest));
                // Store guest ID for update on save
                window._pmsCiExistingGuestId = r.guest.id;
            }
        } catch (e) {
            console.error('Error checking CCCD:', e);
        }
    }, 500);
}
window.pmsCiCheckGuestByCCCD = pmsCiCheckGuestByCCCD;

// Fill guest form from old data
function pmsCiFillGuestFromOld(guestJson) {
    try {
        const guest = JSON.parse(guestJson);
        
        // Fill basic info
        document.getElementById('ci-name').value = guest.full_name || '';
        document.getElementById('ci-gender').value = guest.gender || '';
        document.getElementById('ci-birth').value = guest.birth_date || '';
        document.getElementById('ci-phone').value = guest.phone || '';
        document.getElementById('ci-address').value = guest.address || '';
        document.getElementById('ci-province').value = guest.city || '';
        document.getElementById('ci-district').value = guest.district || '';
        document.getElementById('ci-ward').value = guest.ward || '';
        document.getElementById('ci-vehicle').value = guest.vehicle || '';
        document.getElementById('ci-guest-notes').value = guest.notes || '';
        
        // Fill tax info if exists
        if (guest.tax_code) {
            document.getElementById('ci-tax-code').value = guest.tax_code;
            // Check the invoice radio if tax code exists
            const invoiceRadio = document.querySelector('input[name="ci-invoice"][value="1"]');
            if (invoiceRadio) {
                invoiceRadio.checked = true;
                pmsCiToggleInvoice(invoiceRadio);
            }
        }
        if (guest.invoice_contact) {
            document.getElementById('ci-tax-contact').value = guest.invoice_contact;
        }
        
        // Remove hint
        const hintEl = document.getElementById('ci-cccd-hint');
        if (hintEl) hintEl.remove();
        
        // Store guest ID for update on save
        window._pmsCiExistingGuestId = guest.id;
        
        pmsToast('Đã điền thông tin khách hàng cũ');
    } catch (e) {
        console.error('Error filling guest data:', e);
        pmsToast('Lỗi khi điền thông tin', false);
    }
}
window.pmsCiFillGuestFromOld = pmsCiFillGuestFromOld;

// Function to manually search for old guests (search icon click)
async function pmsCiSearchOldGuest() {
    const cccd = document.getElementById('ci-cccd')?.value?.trim();
    if (!cccd || cccd.length < 3) {
        pmsToast('Vui lòng nhập ít nhất 3 ký tự để tìm kiếm', false);
        return;
    }
    
    try {
        const r = await pmsApi(`/api/pms/guests/search?cccd=${encodeURIComponent(cccd)}`);
        
        if (r.guests && r.guests.length > 0) {
            // Show modal or dropdown with search results
            let resultsHtml = r.guests.map(g => `
                <div onclick="pmsCiFillGuestFromOld('${pmsEscapeHtml(JSON.stringify(g).replace(/'/g, "\\'"))}')" 
                     style="padding:12px;border-bottom:1px solid #e5e7eb;cursor:pointer;hover:background:#f9fafb;">
                    <div style="font-weight:600;">${pmsEscapeHtml(g.full_name)}</div>
                    <div style="font-size:12px;color:#6b7280;">
                        ${g.cccd} | ${g.phone || '—'} | ${g.address || '—'}
                    </div>
                </div>
            `).join('');
            
            // Create temporary modal for results
            const modalId = 'ci-search-results-modal';
            let modal = document.getElementById(modalId);
            if (modal) modal.remove();
            
            modal = document.createElement('div');
            modal.id = modalId;
            modal.className = 'v-modal show';
            modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';
            modal.innerHTML = `
                <div style="background:#fff;border-radius:12px;max-width:400px;width:90%;max-height:400px;overflow:hidden;display:flex;flex-direction:column;">
                    <div style="padding:16px;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center;">
                        <h5 style="margin:0;font-weight:600;">Kết quả tìm kiếm</h5>
                        <button onclick="document.getElementById('${modalId}').remove()" style="background:none;border:none;font-size:20px;cursor:pointer;">&times;</button>
                    </div>
                    <div style="flex:1;overflow-y:auto;">
                        ${resultsHtml}
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        } else {
            pmsToast('Không tìm thấy khách hàng nào');
        }
    } catch (e) {
        console.error('Error searching:', e);
        pmsToast('Lỗi tìm kiếm', false);
    }
}
window.pmsCiSearchOldGuest = pmsCiSearchOldGuest;