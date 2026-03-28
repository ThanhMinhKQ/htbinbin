// static/js/pms/pms_checkout.js
// PMS Check-out - Check-out modal and calculations
'use strict';

let pmsCoStayData = null;

// ─────────────────────────────────────────────────────────────────────────────
// Open Check-out from Dashboard
// ─────────────────────────────────────────────────────────────────────────────
async function openCO(stayId, roomNum) {
    if (!stayId) {
        pmsToast('Thiếu ID lưu trú.', false);
        return;
    }

    document.getElementById('co-stay-id').value = stayId;
    document.getElementById('co-title').textContent = `Trả phòng - Phòng ${roomNum}`;
    document.getElementById('co-discount').value = '';
    document.getElementById('co-extra').value = '';
    document.getElementById('co-override').value = '';

    const now = new Date();
    document.getElementById('co-now').textContent = pmsFdt(now.toISOString());
    document.getElementById('co-sub').textContent = 'Đang tải thông tin...';
    document.getElementById('co-ci').textContent = '—';
    document.getElementById('co-dur').textContent = '—';
    document.getElementById('co-dep').textContent = pmsMoney(0);
    document.getElementById('co-total').textContent = pmsMoney(0);
    pmsCoStayData = null;

    try {
        let stayData = window.rdStayData && rdStayData.id === parseInt(stayId, 10) ? rdStayData : null;
        if (!stayData) {
            stayData = await pmsApi(`/api/pms/stays/${stayId}`);
        }

        pmsCoStayData = stayData;

        const ciDisplay = stayData.check_in_at ? pmsFdt(stayData.check_in_at) : '—';
        document.getElementById('co-ci').textContent = ciDisplay;
        document.getElementById('co-sub').textContent = `${stayData.room_type || '—'} | ${stayData.stay_type === 'hour' ? 'Thuê giờ' : 'Qua đêm'}`;
        document.getElementById('co-dep').textContent = pmsMoney(stayData.deposit || 0);
        document.getElementById('co-dur').textContent = stayData.check_in_at ? pmsDurFull(stayData.check_in_at) : '—';

        pmsCoCalcTotal();

        if (typeof openModal === 'function') openModal('coModal');
        else if (typeof pmsOpenModal === 'function') pmsOpenModal('coModal');
        else document.getElementById('coModal').classList.add('show');
    } catch (e) {
        pmsToast(`Không thể tải thông tin trả phòng: ${e.message}`, false);
        console.error('Open checkout error:', e);
    }
}

function pmsCoCalcTotal() {
    if (!pmsCoStayData) return;

    const ciTime = new Date(pmsCoStayData.check_in_at);
    const now = new Date();
    const ms = now - ciTime;
    if (ms <= 0) return;

    let p = 0;
    if (pmsCoStayData.stay_type === 'hour') {
        const hours = Math.max(pmsCoStayData.min_hours || 1, Math.ceil(ms / 3600000));
        p = (pmsCoStayData.price_per_hour || 0) * (pmsCoStayData.min_hours || 1) + (pmsCoStayData.price_next_hour || 0) * Math.max(0, hours - (pmsCoStayData.min_hours || 1));
    } else {
        p = pmsCoStayData.total_price || (pmsCoStayData.price_per_night * Math.max(1, Math.ceil(ms / 86400000)));
    }

    const override = pmsParseCurrency(document.getElementById('co-override')?.value || '0');
    const discount = pmsParseCurrency(document.getElementById('co-discount')?.value || '0');
    const extra = pmsParseCurrency(document.getElementById('co-extra')?.value || '0');

    let final = p;
    if (override > 0) final = override;
    else final = p - discount + extra;

    document.getElementById('co-total').textContent = pmsMoney(final);
}

function pmsCoFormatCurrency(el) {
    if (!el) return;
    let val = pmsParseCurrency(el.value);
    if (val > 0) {
        el.value = new Intl.NumberFormat('vi-VN').format(val);
    } else {
        el.value = '';
    }
    pmsCoCalcTotal();
}

async function submitCO() {
    const id = document.getElementById('co-stay-id').value;
    const override = pmsParseCurrency(document.getElementById('co-override')?.value || '0');
    const discount = pmsParseCurrency(document.getElementById('co-discount')?.value || '0');
    const extra = pmsParseCurrency(document.getElementById('co-extra')?.value || '0');

    // Build query string instead of FormData to avoid empty body issues
    const params = new URLSearchParams();
    if (override > 0) params.append('final_price', override);
    if (discount > 0) params.append('discount', discount);
    if (extra > 0) params.append('extra_charge', extra);

    try {
        const r = await pmsApi(`/api/pms/checkout/${id}?${params.toString()}`, { method: 'POST' });
        if (typeof closeModal === 'function') closeModal('coModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('coModal');
        else document.getElementById('coModal').classList.remove('show');
        pmsToast(`${r.message} | ${pmsMoney(r.total_price)}`);
        
        const title = document.getElementById('co-title').textContent;
        const roomNumMatch = title.match(/Phòng (.+)/);
        if (roomNumMatch && typeof pmsSetRoomLoading === 'function') {
            pmsSetRoomLoading(null, roomNumMatch[1]);
        }
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
    } catch (e) {
        console.error('Checkout Error:', e);
        pmsToast(e.message, false);
    }
}

// Export globally
window.openCO = openCO;
window.submitCO = submitCO;
window.pmsCoCalcTotal = pmsCoCalcTotal;
window.pmsCoFormatCurrency = pmsCoFormatCurrency;