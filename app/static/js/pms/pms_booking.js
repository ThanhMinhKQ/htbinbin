// static/js/pms/pms_booking.js
// PMS Booking - Smart search, room availability calendar
'use strict';

let pmsCalendarStartDate = new Date();

// Initialize booking page
document.addEventListener('DOMContentLoaded', () => {
    pmsInitSmartSearch();
});

function pmsInitSmartSearch() {
    const ci = document.getElementById('ss-checkin');
    if (!ci) return;
    const now = new Date();
    const tomorrow = new Date(now.getTime() + 24*60*60*1000);
    ci.value = pmsToISO(now);
    const co = document.getElementById('ss-checkout');
    if (co) co.value = pmsToISO(tomorrow);
}

async function pmsSearchRooms() {
    const checkIn = document.getElementById('ss-checkin').value;
    const checkOut = document.getElementById('ss-checkout').value;
    const roomTypeId = document.getElementById('ss-roomtype').value;
    const guests = document.getElementById('ss-guests').value || 1;
    const budget = document.getElementById('ss-budget').value;

    if(!checkIn || !checkOut) {
        pmsToast('Vui lòng chọn ngày Check-in và Check-out', false);
        return;
    }

    const params = new URLSearchParams({
        check_in: checkIn,
        check_out: checkOut,
        stay_type: 'night',
        guest_count: guests
    });

    if(roomTypeId) params.append('room_type_id', roomTypeId);
    if(budget) params.append('budget_max', budget);
    if(PMS.branchId) params.append('branch_id', PMS.branchId);

    try {
        const data = await pmsApi(`/api/pms/search-rooms?${params}`);
        pmsRenderSearchResults(data);
    } catch(e) {
        pmsToast(e.message, false);
    }
}

function pmsRenderSearchResults(data) {
    const resultsEl = document.getElementById('search-results');
    const gridEl = document.getElementById('sr-grid');
    const countEl = document.getElementById('sr-count');

    resultsEl.style.display = 'block';
    countEl.textContent = `${data.total_available} phòng`;

    if(data.total_available === 0) {
        gridEl.innerHTML = `<div class="pms-empty" style="grid-column: 1/-1;">
            <p>Không có phòng available trong thời gian này</p>
        </div>`;
        return;
    }

    let html = '';
    data.available_rooms.forEach(room => {
        let promoBadge = '';
        if(room.promo) {
            promoBadge = `<div class="sr-promo">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                Giảm ${room.promo.discount_percent}% (${room.promo.valid_time})
            </div>`;
        }

        html += `
        <div class="sr-card">
            <div class="rc-badge" style="width:auto; padding:8px 12px; margin-bottom:10px;">
                <div class="rb-num" style="font-size:20px;">${room.room_number}</div>
                <div class="rb-type">${room.room_type}</div>
            </div>
            <div class="rc-info">
                <div class="ri-name">Tầng ${room.floor} • ${room.max_guests} khách</div>
                ${promoBadge}
                <div class="sr-price">${pmsMoney(room.calculated_price)}</div>
            </div>
            <button class="sr-btn" onclick="pmsQuickBook(${room.room_id}, '${room.room_number}', '${room.room_type}', ${room.price_per_night}, ${room.price_per_hour})">
                Đặt ngay
            </button>
        </div>`;
    });

    gridEl.innerHTML = html;
    resultsEl.scrollIntoView({ behavior: 'smooth' });
}

function pmsQuickBook(roomId, roomNumber, roomType, priceNight, priceHour) {
    openCI(roomId);
    document.getElementById('ci-sub').textContent = `${roomType} | Đêm: ${pmsMoney(priceNight)} | Giờ: ${pmsMoney(priceHour)}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Calendar View
// ─────────────────────────────────────────────────────────────────────────────
function pmsShowCalendar() {
    const calEl = document.getElementById('calendar-view');
    calEl.classList.add('show');
    pmsRenderCalendar();
}

function pmsHideCalendar() {
    document.getElementById('calendar-view').classList.remove('show');
}

function pmsPrevWeek() {
    pmsCalendarStartDate.setDate(pmsCalendarStartDate.getDate() - 7);
    pmsRenderCalendar();
}

function pmsNextWeek() {
    pmsCalendarStartDate.setDate(pmsCalendarStartDate.getDate() + 7);
    pmsRenderCalendar();
}

async function pmsRenderCalendar() {
    const gridEl = document.getElementById('cal-grid');
    const days = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];

    let html = days.map(d => `<div class="cal-day header">${d}</div>`).join('');

    const params = new URLSearchParams({
        start_date: pmsCalendarStartDate.toISOString().split('T')[0],
        days: 7
    });
    if(PMS.branchId) params.append('branch_id', PMS.branchId);

    try {
        const data = await pmsApi(`/api/pms/availability-calendar?${params}`);

        data.calendar.forEach(day => {
            let cls = 'vacant';
            if(day.occupancy_rate >= 90) cls = 'full';
            else if(day.occupancy_rate >= 50) cls = 'occupied';

            html += `
            <div class="cal-day ${cls}">
                <div class="cd-date">${day.date.slice(8)}</div>
                <div class="cd-stats">${day.vacant}/${day.total_rooms} trống</div>
                <div class="cd-rate ${cls}">${day.occupancy_rate}%</div>
            </div>`;
        });

        gridEl.innerHTML = html;
    } catch(e) {
        pmsToast('Lỗi tải lịch: ' + e.message, false);
    }
}

// Export
window.pmsSearchRooms = pmsSearchRooms;
window.pmsQuickBook = pmsQuickBook;
window.pmsShowCalendar = pmsShowCalendar;
window.pmsHideCalendar = pmsHideCalendar;
window.pmsPrevWeek = pmsPrevWeek;
window.pmsNextWeek = pmsNextWeek;
window.pmsRenderCalendar = pmsRenderCalendar;