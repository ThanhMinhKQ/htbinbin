// static/js/pms/pms_modals.js
// PMS Modals - Room Detail, Check-in, Check-out, Add Guest, etc.
'use strict';

let rdStayData = null;
let rdGuestList = [];
let rdMaxGuests = 2;

// ─────────────────────────────────────────────────────────────────────────────
// Modal Helpers
// ─────────────────────────────────────────────────────────────────────────────

function rdSwitchTab(tabName) {
    // Hide all tab contents
    document.querySelectorAll('.rd-tab-content').forEach(el => {
        el.style.display = 'none';
    });
    
    // Show selected tab content
    const target = document.getElementById(`rd-tab-${tabName}`);
    if (target) {
        const displayType = target.dataset.display || 'flex';
        target.style.display = displayType;
    }
    
    // Update tab states
    document.querySelectorAll('.rd-tab').forEach(el => {
        if (el.dataset.tab === tabName) {
            el.classList.add('active');
            el.style.borderBottom = '2px solid #3b82f6';
            el.style.color = '#3b82f6';
        } else {
            el.classList.remove('active');
            el.style.borderBottom = 'none';
            el.style.color = '#475569';
        }
    });
}


async function openRoomDetail(stayId, num) {
    const elRdStayId = document.getElementById('rd-stay-id');
    if (elRdStayId) elRdStayId.value = stayId;
    // Reset tab về general
    if (typeof rdSwitchTab === 'function') rdSwitchTab('general');
    
    rdGuestList = [];

    try {
        const d = await pmsApi(`/api/pms/stays/${stayId}`);
        rdStayData = d;
        rdMaxGuests = d.max_guests || 2;

        // --- Cập nhật Tab 1: Thông tin chung ---
        document.getElementById('rd-ci').value = d.check_in_at ? pmsToISO(new Date(d.check_in_at)) : '';
        // Lưu ý: Hệ thống cũ không có check_out dự kiến, ta tạm dùng thời gian hiện tại + 1 ngày nếu không có
        let coEst = new Date();
        coEst.setDate(coEst.getDate() + 1);
        if (d.check_out_at) {
            coEst = new Date(d.check_out_at);
        }
        document.getElementById('rd-co-est').value = pmsToISO(coEst);
        document.getElementById('rd-notes').value = d.notes || '';
        
        // Room info (read-only)
        const elRoomNumRo = document.getElementById('rd-room-num-ro');
        if (elRoomNumRo) elRoomNumRo.value = num;
        const elRoomTypeRo = document.getElementById('rd-room-type-ro');
        if (elRoomTypeRo) elRoomTypeRo.value = d.room_type || '';
        
        // Deposit
        const elDeposit = document.getElementById('rd-deposit');
        if (elDeposit) elDeposit.value = pmsMoney(d.deposit || 0);
        
        // Tax info
        const elTaxCode = document.getElementById('rd-tax-code');
        if (elTaxCode) elTaxCode.value = d.tax_code || '';
        const elTaxContact = document.getElementById('rd-tax-contact');
        if (elTaxContact) elTaxContact.value = d.tax_contact || '';
        
        // Show/hide Invoice tab based on tax data
        const hasInvoice = d.tax_code || d.tax_contact;
        const invoiceTab = document.querySelector('.rd-tab[data-tab="invoice"]');
        if (invoiceTab) {
            invoiceTab.style.display = hasInvoice ? 'flex' : 'none';
        }
        
        // Load invoice tab data if exists
        const elInvTaxCode = document.getElementById('rd-invoice-tax-code');
        if (elInvTaxCode) elInvTaxCode.value = d.tax_code || '';
        const elInvTaxContact = document.getElementById('rd-invoice-tax-contact');
        if (elInvTaxContact) elInvTaxContact.value = d.tax_contact || '';
        
        // --- Cập nhật Tab 2: Phòng ---
        const elRoomNum = document.getElementById('rd-room-num');
        if (elRoomNum) elRoomNum.textContent = num;
        const elRoomNumDisp = document.getElementById('rd-room-num-display');
        if (elRoomNumDisp) elRoomNumDisp.textContent = num;
        const ciDisp = d.check_in_at ? new Date(d.check_in_at).toLocaleString('vi-VN', {hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit', year:'numeric'}) : '';
        const coDisp = coEst.toLocaleString('vi-VN', {hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit', year:'numeric'});
        const elCiDisp = document.getElementById('rd-room-ci-display');
        if (elCiDisp) elCiDisp.textContent = ciDisp;
        const elCoDisp = document.getElementById('rd-room-co-display');
        if (elCoDisp) elCoDisp.textContent = coDisp;
        const elPriceDisp = document.getElementById('rd-room-price-display');
        if (elPriceDisp) elPriceDisp.textContent = pmsMoney(d.price_per_night || 0) + ' VNĐ';
        
        // Ẩn các trường debug
        const oldRmType = document.getElementById('rd-room-type'); if(oldRmType) oldRmType.textContent = d.room_type || '';
        const oldStyType = document.getElementById('rd-stay-type'); if(oldStyType) oldStyType.textContent = d.stay_type === 'hour' ? 'Thuê giờ' : 'Qua đêm';


        // --- Cập nhật Tab 3: Thanh toán ---
        const rNumPay = document.querySelectorAll('.rd-room-num-pay');
        rNumPay.forEach(el => el.textContent = num);
        
        let p = 0;
        const now = new Date();
        const ciTime = new Date(d.check_in_at);
        const ms = now - ciTime;
        if (ms > 0) {
            if (d.stay_type === 'hour') {
                const hours = Math.max(d.min_hours || 1, Math.ceil(ms / 3600000));
                p = (d.price_per_hour || 0) * (d.min_hours || 1) + (d.price_next_hour || 0) * Math.max(0, hours - (d.min_hours || 1));
            } else {
                p = d.price_per_night * Math.max(1, Math.ceil(ms / 86400000));
            }
        }
        
        const elRdPayRoomPrice = document.getElementById('rd-pay-room-price');
        if (elRdPayRoomPrice) elRdPayRoomPrice.textContent = pmsMoney(d.price_per_night || 0);
        const elRdPayRoomPriceSub = document.getElementById('rd-pay-room-price-sub');
        if (elRdPayRoomPriceSub) elRdPayRoomPriceSub.textContent = pmsMoney(p);
        const elRdPaySummaryRoom = document.getElementById('rd-pay-summary-room');
        if (elRdPaySummaryRoom) elRdPaySummaryRoom.textContent = pmsMoney(p);
        
        const elRdPayDepositAmt = document.getElementById('rd-pay-deposit-amt');
        if (elRdPayDepositAmt) elRdPayDepositAmt.textContent = pmsMoney(d.deposit || 0);
        const elRdPayDepositTime = document.getElementById('rd-pay-deposit-time');
        if (elRdPayDepositTime) elRdPayDepositTime.textContent = ciDisp;
        const elRdPaySummaryDeposit = document.getElementById('rd-pay-summary-deposit');
        if (elRdPaySummaryDeposit) elRdPaySummaryDeposit.textContent = pmsMoney(d.deposit || 0);
        
        const elRdPaySummaryTotal = document.getElementById('rd-pay-summary-total');
        if (elRdPaySummaryTotal) elRdPaySummaryTotal.textContent = pmsMoney(p - (d.deposit || 0));


        // Load guests into list
        rdGuestList = (d.guests || []).map(g => ({
            id: g.id,
            full_name: g.full_name || '',
            gender: g.gender || '',
            birth_date: g.birth_date || '',
            phone: g.phone || '',
            cccd: g.cccd || '',
            is_primary: g.is_primary || false,
            vehicle: g.vehicle || '',
            notes: g.notes || '',
            address: g.address || '',
            city: g.city || '',
            district: g.district || '',
            ward: g.ward || '',
            id_expire: g.id_expire || '',
            tax_code: g.tax_code || '',
            invoice_contact: g.invoice_contact || ''
        }));
        
        // Populate rep info from primary guest if available
        const primaryG = rdGuestList.find(g => g.is_primary) || rdGuestList[0];
        if (primaryG) {
             document.getElementById('rd-rep-name').value = primaryG.full_name || '';
             document.getElementById('rd-rep-phone').value = primaryG.phone || '';
             const elRepCccd = document.getElementById('rd-rep-cccd');
             if (elRepCccd) elRepCccd.value = primaryG.cccd || '';
             const elRepBirth = document.getElementById('rd-rep-birth');
             if (elRepBirth) elRepBirth.value = primaryG.birth_date || '';
        } else {
             document.getElementById('rd-rep-name').value = '';
             document.getElementById('rd-rep-phone').value = '';
             const elRepCccd = document.getElementById('rd-rep-cccd');
             if (elRepCccd) elRepCccd.value = '';
             const elRepBirth = document.getElementById('rd-rep-birth');
             if (elRepBirth) elRepBirth.value = '';
        }

        const elRdGuestCount = document.getElementById('rd-guest-count-display');
        if (elRdGuestCount) elRdGuestCount.textContent = rdGuestList.length;

        pmsRdRenderGuestList();
        pmsRdUpdateCapacityWarn();
        if (typeof openModal === 'function') openModal('rdModal');
        else if (typeof pmsOpenModal === 'function') pmsOpenModal('rdModal');
        else document.getElementById('rdModal').classList.add('show');
    } catch (e) { pmsToast(e.message, false); }
}

async function pmsRdUpdateStay() {
    const stayId = document.getElementById('rd-stay-id').value;
    const ciVal = document.getElementById('rd-ci')?.value;
    const coEstVal = document.getElementById('rd-co-est')?.value;
    const depositVal = document.getElementById('rd-deposit')?.value;
    const notesVal = document.getElementById('rd-notes')?.value;
    const taxCodeVal = document.getElementById('rd-tax-code')?.value;
    const taxContactVal = document.getElementById('rd-tax-contact')?.value;

    try {
        await pmsApi(`/api/pms/stays/${stayId}`, {
            method: 'PUT',
            body: new URLSearchParams({
                check_in_at: ciVal || '',
                check_out_at: coEstVal || '',
                deposit: depositVal ? depositVal.replace(/[.,\s]/g, '') : '0',
                notes: notesVal || '',
                tax_code: taxCodeVal || '',
                tax_contact: taxContactVal || '',
            })
        });
        pmsToast('Cập nhật thành công');
    } catch(e) {
        pmsToast(e.message, false);
    }
}

function pmsRdUpdateCapacityWarn() {
    const warnEl = document.getElementById('rd-capacity-warn');
    if (!warnEl) return;
    const total = rdGuestList.length;
    if (total > rdMaxGuests) {
        warnEl.textContent = `Số khách (${total}) vượt quá giới hạn phòng (tối đa ${rdMaxGuests} người).`;
        warnEl.classList.add('show');
    } else {
        warnEl.classList.remove('show');
    }
};

function pmsRdRenderGuestList() {
    const panel = document.getElementById('rd-guest-list-panel');
    if (!panel) return;
    if (rdGuestList.length === 0) {
        panel.innerHTML = '<p style="margin:0;font-size:13px;color:#64748b;text-align:center;padding:24px;">Chưa có khách trong danh sách.</p>';
        return;
    }
    panel.innerHTML = rdGuestList.map((g, i) => `
        <div style="border:1px solid #22c55e; border-radius:8px; padding:16px; background:#fff; display:flex; justify-content:space-between; align-items:flex-start; box-shadow:0 1px 3px rgba(0,0,0,0.05); margin-bottom:12px;">
          <div style="display:flex; gap:20px; align-items:flex-start; flex:1;">
            <div style="flex:1; border-right:1px solid #f1f5f9; padding-right:20px;">
              <div style="font-weight:600; color:#334155; font-size:14px; display:flex; align-items:center; gap:8px; margin-bottom:12px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                ${g.is_primary ? '<span style="background:#dcfce7;color:#16a34a;padding:2px 8px;border-radius:10px;font-size:11px;">CHÍNH</span>' : ''} 
                ${pmsEscapeHtml(g.full_name || 'CHƯA NHẬP TÊN').toUpperCase()}
              </div>
              <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:#64748b; margin-bottom:8px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                Số giấy tờ: <strong>${pmsEscapeHtml(g.cccd || '—')}</strong>
              </div>
              <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:#64748b; margin-bottom:8px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                Điện thoại: <strong>${pmsEscapeHtml(g.phone || '—')}</strong>
              </div>
              ${g.tax_code ? `
              <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:#7c3aed; margin-bottom:8px; background:#f5f3ff; padding:6px 8px; border-radius:4px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <strong>MST: ${pmsEscapeHtml(g.tax_code)}</strong> | ${pmsEscapeHtml(g.invoice_contact || '—')}
              </div>
              ` : ''}
              ${g.notes ? `
              <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:#64748b; margin-top:8px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                ${pmsEscapeHtml(g.notes)}
              </div>
              ` : ''}
            </div>
            <div style="flex:1;">
              <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:#64748b; margin-bottom:8px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                Ngày sinh: <strong>${g.birth_date ? new Date(g.birth_date).toLocaleDateString('vi-VN') : '—'}</strong>
              </div>
              ${g.address ? `
              <div style="display:flex; align-items:flex-start; gap:8px; font-size:13px; color:#64748b; margin-bottom:8px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                <div>
                  <div>${pmsEscapeHtml(g.address)}</div>
                  ${g.ward ? `<div style="font-size:12px;">${pmsEscapeHtml(g.ward)}, ${pmsEscapeHtml(g.district || '')}, ${pmsEscapeHtml(g.city || '')}</div>` : ''}
                </div>
              </div>
              ` : ''}
              ${g.vehicle ? `
              <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:#64748b; margin-bottom:8px; padding:4px 8px; background:#fef3c7; border-radius:4px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>
                <strong>${pmsEscapeHtml(g.vehicle)}</strong>
              </div>
              ` : ''}
            </div>
          </div>
          <div style="display:flex; flex-direction:column; gap:8px; padding-left:16px; margin-left:16px;">
            <button onclick="pmsRdEditGuest(${i})" style="background:#fff; border:1px solid #cbd5e1; color:#475569; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer;" title="Sửa">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            ${!g.is_primary ? `
            <button onclick="pmsRdRemoveGuest(${i})" style="background:#fff; border:1px solid #cbd5e1; color:#475569; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer;" title="Xoá">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
            </button>
            ` : ''}
          </div>
        </div>
    `).join('');
    const elRdGuestCount2 = document.getElementById('rd-guest-count-display');
    if (elRdGuestCount2) elRdGuestCount2.textContent = rdGuestList.length;
}

function pmsRdEditGuest(i) {
    const g = rdGuestList[i];
    if (!g) return;
    // Tái sử dụng modal Thêm khách (agModal) để sửa
    const elRdStayId = document.getElementById('rd-stay-id');
    const elRdRoomNum = document.getElementById('rd-room-num');
    if (elRdStayId && elRdRoomNum) {
        document.getElementById('ag-stay-id').value = elRdStayId.value;
        document.getElementById('ag-title').textContent = `Sửa khách – Phòng ${elRdRoomNum.textContent}`;
    }
    
    document.getElementById('ag-name').value = g.full_name || '';
    document.getElementById('ag-gender').value = g.gender || '';
    document.getElementById('ag-birth').value = g.birth_date || '';
    document.getElementById('ag-phone').value = g.phone || '';
    document.getElementById('ag-cccd').value = g.cccd || '';
    if (document.getElementById('ag-vehicle')) document.getElementById('ag-vehicle').value = g.vehicle || '';
    if (document.getElementById('ag-notes')) document.getElementById('ag-notes').value = g.notes || '';

    window._rdEditIndex = i;
    
    if (typeof openModal === 'function') openModal('agModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('agModal');
    else document.getElementById('agModal').classList.add('show');
}


async function pmsRdRemoveGuest(i) {
    const g = rdGuestList[i];
    if (!g) return;
    if (g.is_primary) {
        pmsToast('Không thể xóa khách chính', false);
        return;
    }
    if (!confirm('Bạn có chắc muốn xóa khách này?')) return;

    rdGuestList.splice(i, 1);
    pmsRdRenderGuestList();
    pmsRdUpdateCapacityWarn();

    if (g.id) {
        try {
            const stayId = document.getElementById('rd-stay-id').value;
            await pmsApi(`/api/pms/stays/${stayId}/guests/${g.id}`, { method: 'DELETE' });
            pmsToast('Đã xóa khách');
        } catch(e) {
            pmsToast(e.message, false);
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Add Guest Modal
// ─────────────────────────────────────────────────────────────────────────────

async function openAG(stayId, roomNum) {
    document.getElementById('ag-stay-id').value = stayId;
    document.getElementById('ag-title').textContent = `Thêm khách – Phòng ${roomNum}`;
    
    ['ag-name','ag-gender','ag-birth','ag-phone','ag-cccd','ag-vehicle','ag-notes'].forEach(id=>{
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    window._rdEditIndex = null;
    
    if (typeof openModal === 'function') openModal('agModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('agModal');
    else document.getElementById('agModal').classList.add('show');
}
window.openAG = openAG;

async function submitAG() {
    const stayId = document.getElementById('ag-stay-id').value;
    if (!stayId) {
        pmsToast('Thiếu stay ID', false);
        return;
    }
    
    const idx = window._rdEditIndex;
    const isEdit = idx !== undefined && idx !== null;
    
    const fd = new FormData();
    fd.append('full_name', document.getElementById('ag-name').value);
    fd.append('gender', document.getElementById('ag-gender').value);
    fd.append('birth_date', document.getElementById('ag-birth').value);
    fd.append('phone', document.getElementById('ag-phone').value);
    fd.append('cccd', document.getElementById('ag-cccd').value);
    const vehicle = document.getElementById('ag-vehicle')?.value;
    if (vehicle) fd.append('vehicle', vehicle);
    const notes = document.getElementById('ag-notes')?.value;
    if (notes) fd.append('notes', notes);
    
    try {
        if (isEdit) {
            // Update existing guest
            const guestId = rdGuestList[idx].id;
            await pmsApi(`/api/pms/guests/${guestId}`, {
                method: 'PUT',
                body: fd
            });
            // Update local data
            rdGuestList[idx] = {
                ...rdGuestList[idx],
                full_name: document.getElementById('ag-name').value,
                gender: document.getElementById('ag-gender').value,
                birth_date: document.getElementById('ag-birth').value,
                phone: document.getElementById('ag-phone').value,
                cccd: document.getElementById('ag-cccd').value,
                vehicle: vehicle || '',
                notes: notes || ''
            };
            window._rdEditIndex = null;
            pmsToast('Cập nhật khách thành công');
        } else {
            // Add new guest
            const r = await pmsApi(`/api/pms/stays/${stayId}/guests`, {
                method: 'POST',
                body: fd
            });
            // Reload room detail
            const elRdRoomNum2 = document.getElementById('rd-room-num');
            openRoomDetail(stayId, elRdRoomNum2 ? elRdRoomNum2.textContent : '');
            pmsToast(r.message || 'Thêm khách thành công');
            return;
        }
        
        pmsRdRenderGuestList();
        pmsRdUpdateCapacityWarn();
        
        if (typeof closeModal === 'function') closeModal('agModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('agModal');
        else document.getElementById('agModal').classList.remove('show');
    } catch(e) {
        pmsToast(e.message, false);
    }
}
window.submitAG = submitAG;

// Export globally
window.openRoomDetail = openRoomDetail;
window.rdSwitchTab = rdSwitchTab;
window.pmsRdUpdateStay = pmsRdUpdateStay;
window.pmsRdRenderGuestList = pmsRdRenderGuestList;
window.pmsRdEditGuest = pmsRdEditGuest;
window.pmsRdRemoveGuest = pmsRdRemoveGuest;
window.pmsRdUpdateCapacityWarn = pmsRdUpdateCapacityWarn;

// Save invoice info
async function rdSaveInvoice() {
    const stayId = document.getElementById('rd-stay-id')?.value;
    if (!stayId) {
        pmsToast('Không tìm thấy ID lưu trú', false);
        return;
    }
    
    const taxCode = document.getElementById('rd-invoice-tax-code')?.value?.trim() || '';
    const taxContact = document.getElementById('rd-invoice-tax-contact')?.value?.trim() || '';
    
    if (!taxCode || !taxContact) {
        pmsToast('Vui lòng nhập đầy đủ Mã số thuế và Liên hệ hoá đơn', false);
        return;
    }
    
    try {
        const fd = new FormData();
        fd.append('tax_code', taxCode);
        fd.append('tax_contact', taxContact);
        
        const r = await pmsApi(`/api/pms/stays/${stayId}`, {
            method: 'PUT',
            body: fd
        });
        
        pmsToast(r.message || 'Lưu thông tin hoá đơn thành công');
        
        // Reload to show invoice tab
        const roomNum = document.getElementById('rd-room-num')?.textContent || '';
        openRoomDetail(stayId, roomNum);
    } catch(e) {
        pmsToast(e.message || 'Lỗi lưu thông tin hoá đơn', false);
    }
}
window.rdSaveInvoice = rdSaveInvoice;
