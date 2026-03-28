// static/js/pms/rd_modal.js
'use strict';

let rdStayData = null;
let rdGuestList = [];
let rdMaxGuests = 2;
let rdTlAllActivities = [];

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

    // Load timeline when switching to timeline tab
    if (tabName === 'timeline') {
        rdLoadTimeline();
    }
}
async function openRoomDetail(stayId, num) {
    const elRdStayId = document.getElementById('rd-stay-id');
    if (elRdStayId) elRdStayId.value = stayId;
    // Reset tab về Room (tab mặc định mới)
    if (typeof rdSwitchTab === 'function') {
        rdSwitchTab('room');
    }
    const elSearch = document.getElementById('rd-search-guest');
    if (elSearch) elSearch.value = '';
    const elFilterStatus = document.getElementById('rd-filter-status');
    if (elFilterStatus) elFilterStatus.value = 'all';

    rdGuestList = [];
    rdTempServices = [];
    rdTempSurcharges = [];

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
        const elNotesRoom = document.getElementById('rd-notes-room');
        if (elNotesRoom) elNotesRoom.value = d.notes || '';
        const elRoomNumNotes = document.getElementById('rd-room-num-notes');
        if (elRoomNumNotes) elRoomNumNotes.textContent = num;

        // Room info (read-only)
        const elRoomNumRo = document.getElementById('rd-room-num-ro');
        if (elRoomNumRo) elRoomNumRo.value = num;
        const elRoomTypeRo = document.getElementById('rd-room-type-ro');
        if (elRoomTypeRo) elRoomTypeRo.value = d.room_type || '';

        // Deposit
        const elDeposit = document.getElementById('rd-deposit');
        if (elDeposit) elDeposit.value = pmsMoney(d.deposit || 0);

        // Invoice tab logic
        const elInvTaxCode = document.getElementById('rd-invoice-tax-code');
        if (elInvTaxCode) elInvTaxCode.value = d.tax_code || '';
        const elInvTaxContact = document.getElementById('rd-invoice-tax-contact');
        if (elInvTaxContact) elInvTaxContact.value = d.tax_contact || '';

        // Hiển thị/Ẩn tab xuất hoá đơn dựa trên has_invoice
        const tabInvTrigger = document.getElementById('rd-tab-trigger-invoice');
        if (tabInvTrigger) {
            tabInvTrigger.style.display = d.has_invoice ? 'flex' : 'none';
        }

        // --- Cập nhật Tab 2: Phòng ---
        const elRoomNum = document.getElementById('rd-room-num');
        if (elRoomNum) elRoomNum.textContent = num;
        const elRoomNumDisp = document.getElementById('rd-room-num-display');
        if (elRoomNumDisp) elRoomNumDisp.textContent = num;
        const ciDisp = d.check_in_at ? new Date(d.check_in_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' }) : '';
        const coDisp = coEst.toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' });
        const elCiDisp = document.getElementById('rd-room-ci-display');
        if (elCiDisp) elCiDisp.textContent = ciDisp;
        const elCoDisp = document.getElementById('rd-room-co-display');
        if (elCoDisp) elCoDisp.textContent = coDisp;
        const elPriceDisp = document.getElementById('rd-room-price-display');
        if (elPriceDisp) elPriceDisp.textContent = pmsMoney(d.price_per_night || 0) + ' VNĐ';
        const elPrepDisp = document.getElementById('rd-room-prepayment-display');
        if (elPrepDisp) elPrepDisp.textContent = pmsMoney(d.deposit || 0) + ' VNĐ';

        // Vehicle display from primary guest
        const primaryGuest = (d.guests || []).find(g => g.is_primary) || (d.guests || [])[0];
        const elVehicle = document.getElementById('rd-vehicle');
        if (elVehicle) elVehicle.value = (primaryGuest && primaryGuest.vehicle) ? primaryGuest.vehicle : '';

        // Ẩn các trường debug
        const oldRmType = document.getElementById('rd-room-type'); if (oldRmType) oldRmType.textContent = d.room_type || '';
        const oldStyType = document.getElementById('rd-stay-type'); if (oldStyType) oldStyType.textContent = d.stay_type === 'hour' ? 'Thuê giờ' : 'Qua đêm';


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


        // Load ALL guests (including soft-checked-out) for room history display
        // Guest who soft-checked-out then moved to another room will still show here with "ĐÃ RA" badge
        rdGuestList = (d.guests || [])
            .map(g => ({
            id: g.id,
            crm_guest_id: g.crm_guest_id != null ? g.crm_guest_id : null,
            full_name: g.full_name || '',
            gender: g.gender || '',
            birth_date: g.birth_date || '',
            phone: g.phone || '',
            cccd: g.cccd || '',
            is_primary: g.is_primary || false,
            vehicle: g.vehicle || '',
            notes: g.notes || '',
            address: g.address || '',
            address_type: g.address_type || 'new',
            city: g.city || '',
            district: g.district || '',
            ward: g.ward || '',
            id_expire: g.id_expire || '',
            id_type: g.id_type || 'cccd',
            tax_code: g.tax_code || '',
            invoice_contact: g.invoice_contact || '',
            nationality: g.nationality || 'VNM - Việt Nam',
            check_in_at: g.check_in_at || d.check_in_at,
            check_out_at: g.check_out_at || null
        }));

        const primaryG = rdGuestList.find(g => g.is_primary) || rdGuestList[0];
        if (primaryG) {
            document.getElementById('rd-rep-name').value = primaryG.full_name || '';

            const elRepPhone = document.getElementById('rd-rep-phone');
            if (elRepPhone) elRepPhone.value = primaryG.phone || '';

            const elRepIdTypeRo = document.getElementById('rd-rep-id-type-ro');
            const idTypeMap = { 'cccd': 'Căn cước công dân', 'cmnd': 'Chứng minh nhân dân', 'passport': 'Hộ chiếu', 'gplx': 'Giấy phép lái xe', 'other': 'Khác' };
            if (elRepIdTypeRo) elRepIdTypeRo.value = idTypeMap[primaryG.id_type || 'cccd'] || 'Căn cước công dân';

            const elRepIdType = document.getElementById('rd-rep-id-type');
            if (elRepIdType) elRepIdType.value = primaryG.id_type || 'cccd';

            const elRepCccd = document.getElementById('rd-rep-cccd');
            if (elRepCccd) elRepCccd.value = primaryG.cccd || '';

            const elRepBirth = document.getElementById('rd-rep-birth');
            if (elRepBirth) elRepBirth.value = primaryG.birth_date || '';

            const elRepAddr = document.getElementById('rd-rep-address');
            if (elRepAddr) {
                let fullAddr = [];
                if (primaryG.ward) fullAddr.push(primaryG.ward);
                if (primaryG.district) fullAddr.push(primaryG.district);
                if (primaryG.city) fullAddr.push(primaryG.city);
                elRepAddr.value = fullAddr.join(', ');
            }


        } else {
            document.getElementById('rd-rep-name').value = '';
            const elRepPhone = document.getElementById('rd-rep-phone'); if (elRepPhone) elRepPhone.value = '';
            const elRepIdType = document.getElementById('rd-rep-id-type'); if (elRepIdType) elRepIdType.value = 'cccd';
            const elRepCccd = document.getElementById('rd-rep-cccd'); if (elRepCccd) elRepCccd.value = '';
            const elRepBirth = document.getElementById('rd-rep-birth'); if (elRepBirth) elRepBirth.value = '';
            const elRepAddr = document.getElementById('rd-rep-address'); if (elRepAddr) elRepAddr.value = '';
            const elRepCi = document.getElementById('rd-rep-ci'); if (elRepCi) elRepCi.value = '';
        }

        const activeCount = rdGuestList.filter(g => !g.check_out_at).length;
        const elRdGuestCount = document.getElementById('rd-guest-count-display');
        if (elRdGuestCount) elRdGuestCount.textContent = activeCount;
        const elMaxGuests = document.getElementById('rd-max-guests-display');
        if (elMaxGuests) elMaxGuests.textContent = rdMaxGuests;

        const filterStatus = document.getElementById('rd-filter-status')?.value || 'all';
        pmsRdRenderGuestList('', filterStatus);
        pmsRdRenderActiveLists();
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

    try {
        const r = await pmsApi(`/api/pms/stays/${stayId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                check_in_at: ciVal || null,
                check_out_at: coEstVal || null,
                deposit: depositVal ? parseFloat(depositVal.replace(/[.,\s]/g, '')) || 0 : 0,
                notes: notesVal || null,
            })
        });
        
        // Update price in UI immediately
        const priceEl = document.getElementById('rd-room-price-display');
        if (priceEl && r.total_price !== undefined) {
            priceEl.textContent = pmsMoney(r.total_price);
        }
        
        // Update deposit in UI if it was changed
        const depEl = document.getElementById('rd-room-prepayment-display');
        if (depEl && r.deposit !== undefined) {
             // r.deposit might not be returned yet, but we have depositVal
             depEl.textContent = pmsMoney(parseFloat(depositVal.replace(/[.,\s]/g, '') || 0));
        }

        pmsToast('Cập nhật thành công');

        const elRdRoomNum = document.getElementById('rd-room-num');
        const roomNum = elRdRoomNum ? elRdRoomNum.textContent : '';
        if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(null, roomNum);
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);

    } catch (e) {
        pmsToast(e.message, false);
    }
}
function pmsRdUpdateCapacityWarn() {
    const warnEl = document.getElementById('rd-capacity-warn');
    if (!warnEl) return;
    const activeCount = rdGuestList.filter(g => !g.check_out_at).length;
    if (activeCount > rdMaxGuests) {
        warnEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> Vượt giới hạn: ${activeCount} khách (tối đa ${rdMaxGuests})`;
        warnEl.style.display = 'flex';
    } else {
        warnEl.style.display = 'none';
    }
};
function pmsRdSearchGuest() {
    const text = document.getElementById('rd-search-guest')?.value || '';
    const status = document.getElementById('rd-filter-status')?.value || 'all';
    pmsRdRenderGuestList(text, status);
}
function pmsRdResetFilter() {
    const elSearch = document.getElementById('rd-search-guest');
    if (elSearch) elSearch.value = '';
    const elFilterStatus = document.getElementById('rd-filter-status');
    if (elFilterStatus) elFilterStatus.value = 'all';
    pmsRdSearchGuest();
}
function pmsRdRenderGuestList(filterText = '', filterStatus = 'staying') {
    const panel = document.getElementById('rd-guest-list-panel');
    if (!panel) return;

    let filteredList = rdGuestList;

    // 1. Filter by Status
    if (filterStatus === 'staying') {
        filteredList = filteredList.filter(g => !g.check_out_at);
    } else if (filterStatus === 'out') {
        filteredList = filteredList.filter(g => !!g.check_out_at);
    }

    // 2. Filter by Search Text
    if (filterText) {
        const f = filterText.toLowerCase();
        filteredList = filteredList.filter(g =>
            (g.full_name || '').toLowerCase().includes(f) ||
            (g.cccd || '').toLowerCase().includes(f)
        );
    }

    if (filteredList.length === 0) {
        let msg = 'Chưa có khách trong danh sách.';
        if (filterText || filterStatus !== 'all') msg = 'Không tìm thấy khách phù hợp.';
        panel.innerHTML = `<p style="margin:0;font-size:13px;color:#64748b;text-align:center;padding:24px;">${msg}</p>`;
        return;
    }
    panel.innerHTML = filteredList.map((g, i) => {
        const isOut = !!g.check_out_at;
        const bg = isOut ? '#f8fafc' : '#fff';
        const borderColor = isOut ? '#e2e8f0' : '#22c55e';
        const ciStr = g.check_in_at ? new Date(g.check_in_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' }) : '—';
        const coStr = g.check_out_at ? new Date(g.check_out_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' }) : (isOut ? '—' : 'Đang ở');

        // Gender Icon
        let genderIcon = `
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        `;
        if (g.gender === 'Nam') {
            genderIcon = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5" title="Nam">
              <circle cx="10" cy="14" r="5"/><path d="M14 10l7-7m-4 0h4v4"/>
            </svg>
          `;
        } else if (g.gender === 'Nữ') {
            genderIcon = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2.5" title="Nữ">
              <circle cx="12" cy="8" r="5"/><path d="M12 13v8m-3-3h6"/>
            </svg>
          `;
        }

        return `
        <div style="flex-shrink:0; border:1px solid ${borderColor}; border-radius:10px; padding:10px; background:${bg}; display:flex; justify-content:space-between; align-items:flex-start; box-shadow:0 1px 2px rgba(0,0,0,0.03); margin-bottom:6px; transition: all 0.2s;">
          <div style="display:flex; gap:14px; align-items:flex-start; flex:1;">
            <!-- Column 1: Identity -->
            <div style="flex:1; border-right:1px solid #f1f5f9; padding-right:14px;">
              <div style="font-weight:700; color:#334155; font-size:14px; display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                ${genderIcon}
                ${g.is_primary ? '<span style="background:#dcfce7;color:#16a34a;padding:1px 8px;border-radius:10px;font-size:9px;letter-spacing:0.3px;">CHÍNH</span>' : ''} 
                <span style="letter-spacing:0.2px;">${pmsEscapeHtml(g.full_name || 'CHƯA NHẬP TÊN').toUpperCase()}</span>
                ${isOut ? '<span style="background:#f1f5f9;color:#64748b;padding:1px 8px;border-radius:10px;font-size:9px;">ĐÃ RA</span>' : ''}
              </div>
              <div style="display:flex; flex-direction:column; gap:3px;">
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#64748b;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  Giấy tờ: <strong style="color:#475569;">${pmsEscapeHtml(g.id_type?.toUpperCase() || 'CCCD')}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#64748b;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  Số: <strong style="color:#1e293b;">${pmsEscapeHtml(g.cccd || '—')}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#64748b;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                  SĐT: <strong style="color:#1e293b;">${pmsEscapeHtml(g.phone || '—')}</strong>
                </div>
              </div>
            </div>

            <!-- Column 2: Stay Info & Address -->
            <div style="flex:1;">
              <div style="display:flex; flex-direction:column; gap:3px;">
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#64748b;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                  Ngày sinh: <strong style="color:#475569;">${g.birth_date ? new Date(g.birth_date).toLocaleDateString('vi-VN') : '—'}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#64748b;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                  Vào: <strong style="color:#059669;">${ciStr}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#64748b;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  Ra: <strong style="color:#dc2626;">${coStr}</strong>
                </div>
                <div style="display:flex; align-items:flex-start; gap:8px; font-size:12px; color:#64748b; border-top:1px dashed #e2e8f0; padding-top:4px; margin-top:2px;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                  <div style="color:#475569; font-weight:500;">
                    ${pmsEscapeHtml(g.ward || '—')}${g.city ? ', ' + pmsEscapeHtml(g.city) : ''}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div style="display:flex; flex-direction:column; gap:10px; padding-left:20px; border-left:1px solid #f1f5f9; margin-left:10px; height:100%; justify-content:center;">
            <button onclick="pmsRdEditGuest(${i})" style="background:#fff; border:1px solid #e2e8f0; color:#64748b; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer;" title="Sửa thông tin">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            ${!g.is_primary && !g.check_out_at ? `
            <button onclick="pmsRdCheckoutGuest(${i})" style="background:#fff; border:1px solid #e2e8f0; color:#ef4444; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer;" title="Trả phòng">
               <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                 <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                 <polyline points="16 17 21 12 16 7" />
                 <line x1="21" y1="12" x2="9" y2="12" />
               </svg>
            </button>
            ` : ''}
          </div>
        </div>
        `;
    }).join('');
    const elRdGuestCount2 = document.getElementById('rd-guest-count-display');
    if (elRdGuestCount2) elRdGuestCount2.textContent = rdGuestList.filter(g => !g.check_out_at).length;
}
async function pmsRdCheckoutGuest(i) {
    const g = rdGuestList[i];
    if (!g) return;
    if (g.is_primary) {
        pmsToast('Khách chính không thể trả phòng riêng. Vui lòng trả phòng toàn bộ.', false);
        return;
    }
    if (g.check_out_at) {
        pmsToast('Khách này đã trả phòng rồi.', false);
        return;
    }
    if (!confirm(`Bạn có chắc muốn trả phòng cho khách "${g.full_name}"?`)) return;

    try {
        const stayId = document.getElementById('rd-stay-id').value;
        const now = new Date().toISOString();

        // Mark guest as checked out (SOFT - keep in list so user can see history)
        const nowIso = now.substring(0, 19);
        await pmsApi(`/api/pms/guests/${g.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ check_out_at: nowIso })
        });

        // Update guest in rdGuestList with check_out_at timestamp (DO NOT remove)
        rdGuestList[i] = { ...rdGuestList[i], check_out_at: now.substring(0, 10) };

        // Update rdStayData to reflect the change
        if (rdStayData && rdStayData.guests) {
            const guestInData = rdStayData.guests.find(g2 => g2.id === g.id);
            if (guestInData) guestInData.check_out_at = now.substring(0, 10);
        }

        pmsToast(`Đã trả phòng cho "${g.full_name}"`);

        // Switch filter to 'all' so user can see the checked-out guest with status badge
        const filterEl = document.getElementById('rd-filter-status');
        if (filterEl) {
            filterEl.value = 'all';
        }

        // Re-render guest list (show all including checked-out)
        pmsRdRenderGuestList('', 'all');
        pmsRdUpdateCapacityWarn();

        // Refresh dashboard room cards after guest checkout
        if (typeof pmsLoadRooms === 'function') pmsLoadRooms(undefined, true);

    } catch (e) {
        pmsToast(e.message, false);
    }
}
function pmsRdEditGuest(i) {
    const g = rdGuestList[i];
    if (!g) return;

    const elRdStayId = document.getElementById('rd-stay-id');
    const stayId = elRdStayId ? elRdStayId.value : '';
    const guestId = g.id;

    if (!stayId || !guestId) {
        pmsToast('Thiếu thông tin lưu trú hoặc khách', false);
        return;
    }

    // Open the dedicated Edit Guest modal (ID fields LOCKED)
    if (typeof openEG === 'function') {
        openEG(parseInt(stayId), guestId);
    } else {
        pmsToast('Chức năng sửa khách chưa sẵn sàng', false);
    }
}

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
    } catch (e) {
        pmsToast(e.message || 'Lỗi lưu thông tin hoá đơn', false);
    }
}
window.rdSaveInvoice = rdSaveInvoice;
let rdTempSurcharges = [];
let rdTempServices = [];
let rdAllServices = [];

function rdFormatDateTime(dt) {
    if (!dt) return '---';
    const HH = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    const DD = String(dt.getDate()).padStart(2, '0');
    const MM = String(dt.getMonth() + 1).padStart(2, '0');
    const YYYY = dt.getFullYear();
    const weekdays = ['Chủ Nhật', 'Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7'];
    const weekday = weekdays[dt.getDay()];
    return `${DD} - ${MM} - ${YYYY} | ${HH}:${mm} | ${weekday}`;
}
function pmsRdOpenExtension() {
    const elDate = document.getElementById('rd-sm-ext-date');
    const elTime = document.getElementById('rd-sm-ext-time');
    if (elDate) {
        const coString = document.getElementById('rd-co-est')?.value || new Date().toISOString().substring(0, 16);
        elDate.value = coString.split('T')[0];
        elTime.value = "12:00"; // Default to 12:00 for user convenience

        // Show current checkout time as reference
        const currentCO = new Date(coString);
        const elCurrent = document.getElementById('rd-sm-ext-current');
        if (elCurrent) {
            elCurrent.textContent = rdFormatDateTime(currentCO);
        }
    }
    rdUpdateExtPreview();
    document.getElementById('rd-sub-modal-extension').style.display = 'flex';
}
function rdUpdateExtPreview() {
    const dateVal = document.getElementById('rd-sm-ext-date').value;
    const timeVal = document.getElementById('rd-sm-ext-time').value;
    const preview = document.getElementById('rd-sm-ext-preview');
    if (!dateVal || !timeVal) {
        preview.textContent = '---';
        return;
    }
    const dt = new Date(`${dateVal}T${timeVal}`);
    preview.textContent = rdFormatDateTime(dt);
}
function rdQuickExt(hours) {
    const elDate = document.getElementById('rd-sm-ext-date');
    const elTime = document.getElementById('rd-sm-ext-time');
    if (!elDate.value || !elTime.value) return;

    // Create a proper Date object from current inputs
    const dt = new Date(`${elDate.value}T${elTime.value}`);
    // Add hours - JS Date object handles rollover (day/month/year) automatically
    dt.setHours(dt.getHours() + hours);

    // Update inputs
    // Use local time for ISO format extraction safely
    const pad = (n) => n.toString().padStart(2, '0');
    const y = dt.getFullYear();
    const m = pad(dt.getMonth() + 1);
    const d = pad(dt.getDate());
    const hh = pad(dt.getHours());
    const mm = pad(dt.getMinutes());

    elDate.value = `${y}-${m}-${d}`;
    elTime.value = `${hh}:${mm}`;
    rdUpdateExtPreview();
}
async function pmsRdSaveExtension() {
    const date = document.getElementById('rd-sm-ext-date').value;
    const time = document.getElementById('rd-sm-ext-time').value;
    if (!date) return pmsToast('Vui lòng chọn thời gian', false);

    const newCo = `${date}T${time}:00`;
    const coDisplay = document.getElementById('rd-room-co-display');
    if (coDisplay) coDisplay.textContent = new Date(newCo).toLocaleString('vi-VN');

    const coInp = document.getElementById('rd-co-est');
    if (coInp) coInp.value = newCo.substring(0, 16);

    document.getElementById('rd-sub-modal-extension').style.display = 'none';

    // Auto-save to backend
    await pmsRdUpdateStay();
}
function pmsRdOpenSurcharge() {
    document.getElementById('rd-sm-sur-content').value = '';
    const elAmt = document.getElementById('rd-sm-sur-amount');
    if (elAmt) {
        elAmt.value = '0';
        if (!elAmt.getAttribute('data-fmt-bound')) {
            elAmt.addEventListener('input', () => agFormatCurrencyInput(elAmt));
            elAmt.setAttribute('data-fmt-bound', 'true');
        }
    }
    pmsRdRenderTempSurcharge();
    document.getElementById('rd-sub-modal-surcharge').style.display = 'flex';
}
function rdQuickAddSur(note, amount) {
    document.getElementById('rd-sm-sur-content').value = note;
    const elAmt = document.getElementById('rd-sm-sur-amount');
    elAmt.value = amount;
    agFormatCurrencyInput(elAmt);
}
function pmsRdAddTempSurcharge() {
    const note = document.getElementById('rd-sm-sur-content').value;
    const amtStr = document.getElementById('rd-sm-sur-amount').value.replace(/\D/g, '');
    const amount = parseInt(amtStr || '0');

    if (!note || amount <= 0) return pmsToast('Thông tin phát sinh không hợp lệ', false);

    rdTempSurcharges.push({ note, amount });
    pmsRdRenderTempSurcharge();
    document.getElementById('rd-sm-sur-content').value = '';
    document.getElementById('rd-sm-sur-amount').value = '0';
}
function pmsRdRenderTempSurcharge() {
    const list = document.getElementById('rd-sm-sur-bill-list');
    if (!list) return;
    let total = 0;
    if (rdTempSurcharges.length === 0) {
        list.innerHTML = `<div class="rd-sv-empty" style="text-align:center; padding:40px 20px; font-size:13px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px;">
      <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" style="opacity:0.4;">
        <rect width="18" height="18" x="3" y="3" rx="2"/>
        <path d="M3 9h18"/>
        <path d="M9 21V9"/>
      </svg>
      <p style="margin:0;">Chưa có khoản phát sinh nào được chọn</p>
    </div>`;
    } else {
        list.innerHTML = rdTempSurcharges.map((s, i) => {
            total += s.amount;
            return `
        <div class="rd-sm-bill-item" style="border-left: 3px solid #3b82f6;">
          <div style="flex:1;">
            <div style="font-weight:600;">${pmsEscapeHtml(s.note)}</div>
            <div style="font-size:11px; color:#64748b;">${new Date().toLocaleTimeString()}</div>
          </div>
          <div style="text-align:right;">
             <div style="font-weight:700; color:#0f172a;">${s.amount.toLocaleString()}</div>
             <span style="color:#ef4444; cursor:pointer; font-size:11px;" onclick="pmsRdRemoveTempSurcharge(${i})">Xoá</span>
          </div>
        </div>
      `;
        }).join('');
    }
    document.getElementById('rd-sm-sur-total').textContent = total.toLocaleString();
}
function pmsRdRemoveTempSurcharge(i) {
    rdTempSurcharges.splice(i, 1);
    pmsRdRenderTempSurcharge();
}
function pmsRdApplySurcharge() {
    if (rdTempSurcharges.length === 0) return pmsToast('Vui lòng thêm ít nhất 1 khoản phát sinh', false);
    const elCount = document.getElementById('rd-surcharge-count');
    if (elCount) elCount.textContent = rdTempSurcharges.length;
    document.getElementById('rd-sub-modal-surcharge').style.display = 'none';
    pmsToast(`Đã thêm ${rdTempSurcharges.length} khoản phát sinh thành công`, true);
}
function pmsRdOpenService() {
    pmsRdRenderServiceList();
    pmsRdRenderTempService();
    document.getElementById('rd-sub-modal-service').style.display = 'flex';
}
function pmsRdRenderServiceList(filter = '', cat = 'Đồ uống') {
    const list = document.getElementById('rd-sm-sv-list');
    if (!list) return;

    let filtered = rdAllServices;
    if (cat !== 'All') {
        filtered = filtered.filter(s => s.cat === cat);
    }
    if (filter) {
        filtered = filtered.filter(s => s.name.toLowerCase().includes(filter.toLowerCase()));
    }

    if (filtered.length === 0) {
        list.innerHTML = `<div class="rd-sv-empty" style="text-align:center; padding:80px 20px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px;">
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" style="opacity:0.4;">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.3-4.3"/>
      </svg>
      <p style="margin:0; font-size:14px;">Không tìm thấy dịch vụ nào</p>
    </div>`;
    } else {
        list.innerHTML = filtered.map((s, idx) => `
      <div style="background:#fff; border:1px solid #f1f5f9; border-radius:12px; padding:10px 16px; transition:all 0.2s ease; display:flex; align-items:center; gap:16px; box-shadow:0 1px 2px rgba(0,0,0,0.01);" class="rd-sv-row-card">
        
        <!-- Left: Compact Icon & Info -->
        <div style="width:36px; height:36px; background:#f8fafc; border-radius:10px; display:flex; align-items:center; justify-content:center; color:#3b82f6; flex-shrink:0;">
           <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2z"/><path d="M3 19a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2z"/></svg>
        </div>
        
        <div style="flex:1; min-width:0;">
           <div style="font-weight:700; font-size:14px; color:#0f172a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${s.name}">${s.name}</div>
           <span style="background:rgba(71,85,105,0.06); color:#64748b; font-size:9px; font-weight:800; padding:1px 6px; border-radius:100px; text-transform:uppercase;">${s.cat}</span>
        </div>

        <!-- Middle: Price -->
        <div style="text-align:right; min-width:100px; flex-shrink:0;">
           <div style="color:#10b981; font-weight:800; font-size:16px; letter-spacing:-0.4px;">${s.price.toLocaleString()}<small style="font-size:10px; margin-left:1px; font-weight:700;">đ</small></div>
        </div>

        <!-- Right: Compact Stepper & Icon Button -->
        <div style="display:flex; align-items:center; gap:10px; border-left:1px solid #f1f5f9; padding-left:16px; flex-shrink:0;">
           <div style="display:flex; align-items:center; background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:3px;">
              <button onclick="rdStepSvQty(this, -1)" style="width:28px; height:28px; border:none; background:#fff; border-radius:6px; color:#64748b; cursor:pointer; font-size:16px; font-weight:700; box-shadow:0 1px 2px rgba(0,0,0,0.05); display:flex; align-items:center; justify-content:center;">-</button>
              <input type="text" value="1" id="sv-qty-${idx}" style="width:40px; border:none; background:none; text-align:center; font-size:14px; font-weight:800; color:#1e293b; padding:0;" oninput="this.value=this.value.replace(/\\D/g,'')">
              <button onclick="rdStepSvQty(this, 1)" style="width:28px; height:28px; border:none; background:#fff; border-radius:6px; color:#64748b; cursor:pointer; font-size:16px; font-weight:700; box-shadow:0 1px 2px rgba(0,0,0,0.05); display:flex; align-items:center; justify-content:center;">+</button>
           </div>
           
           <button class="v-btn primary" onclick="pmsRdAddTempService('${s.name}', ${s.price}, 'sv-qty-${idx}')" style="width:36px; height:36px; padding:0; border-radius:10px; min-width:auto; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5"><path d="M5 12h14m-7-7v14"/></svg>
           </button>
        </div>
      </div>
    `).join('');
    }
}
function rdStepSvQty(btn, step) {
    const inp = btn.parentElement.querySelector('input');
    let val = parseInt(inp.value) || 0;
    val = Math.max(1, val + step);
    inp.value = val;
}
function pmsRdSearchService(input) {
    const activeCat = document.querySelector('.rd-sm-cat-item.active')?.textContent || 'Đồ uống';
    pmsRdRenderServiceList(input.value, activeCat);
}
function pmsRdSwitchSvCat(el) {
    document.querySelectorAll('.rd-sm-cat-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    const cat = el.textContent;
    const searchVal = document.querySelector('#rd-sub-modal-service input')?.value || '';
    pmsRdRenderServiceList(searchVal, cat);
}
function pmsRdAddTempService(name, price, qtyInpId) {
    const qtyInp = document.getElementById(qtyInpId);
    const qty = parseInt(qtyInp?.value || '1');
    if (qty <= 0) return;

    const existing = rdTempServices.find(s => s.name === name);
    if (existing) {
        existing.qty += qty;
    } else {
        rdTempServices.push({ name, amount: price, qty: qty });
    }
    pmsRdRenderTempService();
    if (qtyInp) qtyInp.value = '1'; // Reset
}
function pmsRdRenderTempService() {
    const list = document.getElementById('rd-sm-sv-bill-list');
    if (!list) return;
    let total = 0;
    if (rdTempServices.length === 0) {
        list.innerHTML = `<div class="rd-sv-empty" style="text-align:center; padding:40px 20px; font-size:13px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px;">
      <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" style="opacity:0.4;">
        <rect width="18" height="18" x="3" y="3" rx="2"/>
        <path d="M3 9h18"/>
        <path d="M9 21V9"/>
      </svg>
      <p style="margin:0;">Chưa có dịch vụ nào được chọn</p>
    </div>`;
        list.style.background = 'transparent';
    } else {
        list.innerHTML = rdTempServices.map((s, i) => {
            total += s.amount * s.qty;
            return `
        <div class="rd-sm-bill-item" style="padding:12px;">
          <div style="flex:1;">
            <div style="font-weight:600;">${pmsEscapeHtml(s.name)}</div>
            <div style="font-size:11px; color:#64748b;">Số lượng: <strong>${s.qty}</strong></div>
          </div>
          <div style="text-align:right;">
            <div style="font-weight:700; color:#1e293b;">${(s.amount * s.qty).toLocaleString()}</div>
            <span style="color:#ef4444; cursor:pointer; font-size:11px;" onclick="pmsRdRemoveTempService(${i})">Gỡ</span>
          </div>
        </div>
      `;
        }).join('');
    }
    document.getElementById('rd-sm-sv-total').textContent = total.toLocaleString();
}
function pmsRdRemoveTempService(i) {
    rdTempServices.splice(i, 1);
    pmsRdRenderTempService();
}
function pmsRdApplyService() {
    const elCount = document.getElementById('rd-service-count');
    if (elCount) elCount.textContent = rdTempServices.reduce((sum, s) => sum + s.qty, 0);
    pmsRdRenderActiveLists();
    document.getElementById('rd-sub-modal-service').style.display = 'none';
    pmsToast('Dịch vụ đã được áp dụng vào hoá đơn phòng', true);
}
function pmsRdApplySurcharge() {
    const elCount = document.getElementById('rd-surcharge-count');
    if (elCount) elCount.textContent = rdTempSurcharges.length;
    pmsRdRenderActiveLists();
    document.getElementById('rd-sub-modal-surcharge').style.display = 'none';
    pmsToast('Phát sinh đã được áp dụng vào hoá đơn phòng', true);
}
function pmsRdRenderActiveLists() {
    const svList = document.getElementById('rd-services-active-list');
    const surList = document.getElementById('rd-surcharges-active-list');

    if (svList) {
        if (rdTempServices.length === 0) {
            svList.innerHTML = '';
        } else {
            svList.innerHTML = rdTempServices.map(s => `
        <div class="rd-active-list-item" onclick="pmsRdOpenService()" style="display:flex; justify-content:space-between; align-items:center;">
          <span style="flex:1; font-weight:600; text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${pmsEscapeHtml(s.name)}</span>
          <span style="flex:1; text-align:center; color:#64748b; font-weight:700;">x${s.qty}</span>
          <span style="flex:1; text-align:right; color:#10b981;">+${(s.amount * s.qty).toLocaleString()}</span>
        </div>
      `).join('');
        }
    }

    if (surList) {
        if (rdTempSurcharges.length === 0) {
            surList.innerHTML = '';
        } else {
            surList.innerHTML = rdTempSurcharges.map(s => `
        <div class="rd-active-list-item" onclick="pmsRdOpenSurcharge()" style="display:flex; justify-content:space-between; align-items:center;">
          <span style="flex:1.5; font-weight:600; text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${pmsEscapeHtml(s.note)}</span>
          <span style="flex:1; text-align:right; color:#ef4444;">+${s.amount.toLocaleString()}</span>
        </div>
      `).join('');
        }
    }
}
window.openRoomDetail = openRoomDetail;
window.rdSwitchTab = rdSwitchTab;
window.pmsRdUpdateStay = pmsRdUpdateStay;
window.pmsRdRenderGuestList = pmsRdRenderGuestList;
window.pmsRdEditGuest = pmsRdEditGuest;
window.pmsRdCheckoutGuest = pmsRdCheckoutGuest;
window.pmsRdUpdateCapacityWarn = pmsRdUpdateCapacityWarn;
window.pmsRdOpenExtension = pmsRdOpenExtension;
window.pmsRdSaveExtension = pmsRdSaveExtension;
window.rdUpdateExtPreview = rdUpdateExtPreview;
window.rdQuickExt = rdQuickExt;
window.rdStepSvQty = rdStepSvQty;
window.pmsRdOpenSurcharge = pmsRdOpenSurcharge;
window.rdQuickAddSur = rdQuickAddSur;
window.pmsRdAddTempSurcharge = pmsRdAddTempSurcharge;
window.pmsRdRemoveTempSurcharge = pmsRdRemoveTempSurcharge;
window.pmsRdApplySurcharge = pmsRdApplySurcharge;
window.pmsRdOpenService = pmsRdOpenService;
window.pmsRdSearchService = pmsRdSearchService;
window.pmsRdSwitchSvCat = pmsRdSwitchSvCat;
window.pmsRdAddTempService = pmsRdAddTempService;
window.pmsRdRemoveTempService = pmsRdRemoveTempService;
window.pmsRdApplyService = pmsRdApplyService;
window.pmsRdSearchGuest = pmsRdSearchGuest;
window.pmsRdRenderActiveLists = pmsRdRenderActiveLists;

// ══════════════════════════════════════════════════════
// TIMELINE - Guest Activity Timeline
// ══════════════════════════════════════════════════════

// ─── Icon map per activity type ───
const RD_TL_ICONS = {
    CHECK_IN: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 15 3 9"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`,
    CHECK_OUT: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    ROOM_CHANGE: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`,
    EXTEND_STAY: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="12" y1="14" x2="12" y2="18"/><line x1="10" y1="16" x2="14" y2="16"/></svg>`,
    EARLY_CHECKIN: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    LATE_CHECKOUT: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    GUEST_ADDED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`,
    BOOKING_CREATED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
    BOOKING_CANCELLED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    NO_SHOW: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="18" y1="8" x2="23" y2="13"/><line x1="23" y1="8" x2="18" y2="13"/></svg>`,
    PAYMENT_RECEIVED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`,
    PAYMENT_REFUND: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
    DEPOSIT_ADDED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>`,
    DEPOSIT_USED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><line x1="12" y1="14" x2="12" y2="18"/><line x1="10" y1="16" x2="14" y2="16"/></svg>`,
    SERVICE_USED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93l-1.41 1.41"/><path d="M6.34 17.66l-1.41 1.41"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="M4.93 4.93l1.41 1.41"/><path d="M17.66 17.66l1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/></svg>`,
    MINIBAR_USED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2z"/></svg>`,
    COMPLAINT: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
    FEEDBACK: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
    REVIEW: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
    LOST_ITEM: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    PROFILE_UPDATED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    BLACKLISTED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>`,
    MERGED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>`,
    BOOKING_MODIFIED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
};

// ─── CSS class map per activity type ───
const RD_TL_CLASS = {
    CHECK_IN: 'rd-tl-checkin',
    CHECK_OUT: 'rd-tl-checkout',
    ROOM_CHANGE: 'rd-tl-roomchange',
    EARLY_CHECKIN: 'rd-tl-checkin',
    LATE_CHECKOUT: 'rd-tl-checkout',
    EXTEND_STAY: 'rd-tl-checkin',
    GUEST_ADDED: 'rd-tl-guestadd',
    BOOKING_CREATED: 'rd-tl-booking',
    BOOKING_MODIFIED: 'rd-tl-booking',
    BOOKING_CANCELLED: 'rd-tl-default',
    NO_SHOW: 'rd-tl-default',
    PAYMENT_RECEIVED: 'rd-tl-payment',
    PAYMENT_REFUND: 'rd-tl-payment',
    DEPOSIT_ADDED: 'rd-tl-deposit',
    DEPOSIT_USED: 'rd-tl-deposit',
    SERVICE_USED: 'rd-tl-service',
    MINIBAR_USED: 'rd-tl-service',
    COMPLAINT: 'rd-tl-complaint',
    FEEDBACK: 'rd-tl-default',
    REVIEW: 'rd-tl-default',
    LOST_ITEM: 'rd-tl-default',
    PROFILE_UPDATED: 'rd-tl-system',
    BLACKLISTED: 'rd-tl-system',
    MERGED: 'rd-tl-system',
};

// ─── Format time HH:MM ───
function rdTlTime(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        const p = n => String(n).padStart(2, '0');
        return `${p(d.getHours())}:${p(d.getMinutes())}`;
    } catch { return '—'; }
}

// ─── Format date for group header ───
function rdTlDate(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        const now = new Date();
        const diff = Math.floor((now - d) / 86400000);
        if (diff === 0) return 'Hôm nay';
        if (diff === 1) return 'Hôm qua';
        if (diff < 7) return `${diff} ngày trước`;
        const p = n => String(n).padStart(2, '0');
        return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
    } catch { return '—'; }
}

// ─── Get actor display name ───
function rdTlActor(actor_type, actor_id, extra_data) {
    if (actor_type === 'system') return 'Hệ thống';
    if (actor_type === 'user' && actor_id) return `NV #${actor_id}`;
    return '';
}

// ─── Render single activity item ───
function rdTlRenderItem(act) {
    const cls = RD_TL_CLASS[act.activity_type] || 'rd-tl-default';
    const icon = RD_TL_ICONS[act.activity_type] || RD_TL_ICONS.SERVICE_USED;
    const time = rdTlTime(act.created_at);
    const title = act.title || act.activity_type;
    const desc = act.description || '';
    const amount = act.amount ? `${parseFloat(act.amount).toLocaleString('vi-VN')}đ` : '';
    const actor = rdTlActor(act.actor_type, act.actor_id, act.extra_data);

    return `
    <div class="rd-tl-item">
        <div class="rd-tl-node">
            <div class="rd-tl-dot ${cls}">${icon}</div>
        </div>
        <div class="rd-tl-card ${cls}">
            <div class="rd-tl-main">
                <div class="rd-tl-title-row">
                    <div class="rd-tl-title">${title}</div>
                    ${amount ? `<div class="rd-tl-amount">${amount}</div>` : ''}
                </div>
                ${desc ? `<div class="rd-tl-desc">${desc}</div>` : ''}
                <div class="rd-tl-meta">
                    <span class="rd-tl-time">${time}</span>
                    ${actor ? `<span class="rd-tl-actor">· ${actor}</span>` : ''}
                </div>
            </div>
        </div>
    </div>`;
}

// ─── Group activities by date ───
function rdTlGroupByDate(activities) {
    const groups = {};
    activities.forEach(a => {
        const d = new Date(a.created_at);
        const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
        if (!groups[key]) groups[key] = [];
        groups[key].push(a);
    });
    // Sort within each group by time desc
    Object.values(groups).forEach(g => g.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)));
    return groups;
}

// ─── Main: Load & render timeline ───
async function rdLoadTimeline() {
    const stayId = rdStayData && rdStayData.id;
    if (!stayId) {
        const loadingEl = document.getElementById('rd-tl-loading');
        const emptyEl = document.getElementById('rd-tl-empty');
        if (loadingEl) loadingEl.style.display = 'none';
        if (emptyEl) {
            emptyEl.style.display = 'flex';
            const p = emptyEl.querySelector('p');
            if (p) p.textContent = 'Chưa mở chi tiết lưu trú — không tải được lịch sử.';
        }
        return;
    }

    const listEl = document.getElementById('rd-tl-list');
    const loadingEl = document.getElementById('rd-tl-loading');
    const emptyEl = document.getElementById('rd-tl-empty');

    if (loadingEl) loadingEl.style.display = 'flex';
    if (listEl) listEl.style.display = 'none';
    if (emptyEl) emptyEl.style.display = 'none';

    try {
        const data = await pmsApi(`/api/pms/stays/${stayId}/activities?limit=100`);
        rdTlAllActivities = data.activities || [];

        // Update stats
        const stats = data.stats || {};
        const elCheckin = document.getElementById('rd-tl-stat-checkin');
        const elCheckout = document.getElementById('rd-tl-stat-checkout');
        const elPayments = document.getElementById('rd-tl-stat-payments');
        const elSpent = document.getElementById('rd-tl-stat-spent');
        if (elCheckin) elCheckin.textContent = stats.total_checkins || 0;
        if (elCheckout) elCheckout.textContent = stats.total_checkouts || 0;
        if (elPayments) elPayments.textContent = stats.total_payments || 0;
        if (elSpent) elSpent.textContent = `${parseFloat(stats.total_spent || 0).toLocaleString('vi-VN')}đ`;

        if (loadingEl) loadingEl.style.display = 'none';

        if (rdTlAllActivities.length === 0) {
            if (emptyEl) emptyEl.style.display = 'flex';
            return;
        }

        if (listEl) {
            listEl.style.display = 'flex';

            // Apply current filter
            const activeBtn = document.querySelector('.rd-tl-filter-btn.active');
            const filter = activeBtn ? activeBtn.dataset.filter : 'all';

            rdTlRenderTimelineList(rdTlAllActivities, filter);
        }
    } catch (e) {
        if (loadingEl) loadingEl.style.display = 'none';
        pmsToast(`Không thể tải lịch sử: ${e.message}`, false);
    }
}

// ─── Render timeline list with filter ───
function rdTlRenderTimelineList(activities, filter = 'all') {
    const listEl = document.getElementById('rd-tl-list');
    if (!listEl) return;

    let filtered = activities;
    if (filter !== 'all') {
        filtered = activities.filter(a => a.activity_group === filter);
    }

    if (filtered.length === 0) {
        listEl.innerHTML = '';
        const emptyEl = document.getElementById('rd-tl-empty');
        if (emptyEl) {
            emptyEl.style.display = 'flex';
            emptyEl.querySelector('p').textContent = filter === 'all'
                ? 'Chưa có hoạt động nào được ghi nhận'
                : 'Không có hoạt động nào trong nhóm này';
        }
        return;
    }

    const emptyEl = document.getElementById('rd-tl-empty');
    if (emptyEl) emptyEl.style.display = 'none';

    const groups = rdTlGroupByDate(filtered);
    const sortedKeys = Object.keys(groups).sort((a, b) => new Date(b) - new Date(a));

    let html = '';
    sortedKeys.forEach(key => {
        const acts = groups[key];
        const firstAct = acts[0];
        const dateLabel = rdTlDate(firstAct.created_at);
        html += `<div class="rd-tl-group-header">
            <span class="rd-tl-group-date">${dateLabel}</span>
            <div class="rd-tl-group-line"></div>
        </div>`;
        acts.forEach(a => { html += rdTlRenderItem(a); });
    });

    listEl.innerHTML = html;
}

// ─── Filter handler ───
let rdTlCurrentFilter = 'all';

function rdTlFilter(filter) {
    rdTlCurrentFilter = filter;

    // Update button states
    document.querySelectorAll('.rd-tl-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });

    rdTlRenderTimelineList(rdTlAllActivities, filter);
}

// ─── Export globals ───
window.rdSwitchTab = rdSwitchTab;
window.rdLoadTimeline = rdLoadTimeline;
window.rdTlFilter = rdTlFilter;
window.rdTlRenderTimelineList = rdTlRenderTimelineList;