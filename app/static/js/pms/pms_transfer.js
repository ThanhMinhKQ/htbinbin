// static/js/pms/pms_transfer.js
// PMS Transfer Room - Open modal, load available rooms, submit transfer
'use strict';

// Global state
window.pmsTfStayId = null;
window.pmsTfRooms = [];
window.pmsTfSelectedId = null;
window._pmsTfAllRooms = [];

// ─────────────────────────────────────────────────────────────────────────────
// Open Transfer Modal
// ─────────────────────────────────────────────────────────────────────────────
async function openTF(stayId, currentRoomNum) {
    if (!stayId) {
        pmsToast('Thiếu ID lưu trú.', false);
        return;
    }

    window.pmsTfStayId = stayId;
    window.pmsTfRooms = [];
    window.pmsTfSelectedId = null;
    window._pmsTfAllRooms = [];

    // Set modal header info
    const infoEl = document.getElementById('tf-info');
    if (infoEl) infoEl.textContent = `Phòng hiện tại: ${currentRoomNum}`;

    // Reset room list
    const listEl = document.getElementById('tf-room-list');
    if (listEl) {
        listEl.innerHTML = `<div class="tf-room-loading">
            <div class="tf-spinner"></div>
            <span>Đang tải phòng trống...</span>
        </div>`;
    }

    // Reset selected info
    const selEl = document.getElementById('tf-selected-info');
    if (selEl) selEl.textContent = 'Chưa chọn phòng';
    const btnEl = document.getElementById('tf-submit-btn');
    if (btnEl) btnEl.disabled = true;

    // Load available rooms
    await pmsTfLoadRooms();

    // Open modal
    if (typeof openModal === 'function') openModal('tfModal');
    else if (typeof pmsOpenModal === 'function') pmsOpenModal('tfModal');
    else document.getElementById('tfModal').classList.add('show');
}

// ─────────────────────────────────────────────────────────────────────────────
// Load Available Rooms
// ─────────────────────────────────────────────────────────────────────────────
async function pmsTfLoadRooms() {
    if (!window.pmsTfStayId) return;

    try {
        const data = await pmsApi(`/api/pms/rooms/available?stay_id=${window.pmsTfStayId}`);
        window.pmsTfRooms = data.rooms || [];
        window._pmsTfAllRooms = window.pmsTfRooms;

        const listEl = document.getElementById('tf-room-list');
        if (!listEl) return;

        if (window.pmsTfRooms.length === 0) {
            listEl.innerHTML = `<div class="tf-empty">
                <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                    <polyline points="9 22 9 12 15 12 15 22"/>
                </svg>
                <p>Không có phòng trống nào khả dụng</p>
            </div>`;
            return;
        }

        listEl.innerHTML = window.pmsTfRooms.map(r => `
            <div class="tf-room-item" data-id="${r.id}" onclick="pmsTfSelectRoom(${r.id}, '${r.room_number}', ${r.price_per_night})">
                <div class="tf-room-icon">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                        <polyline points="9 22 9 12 15 12 15 22"/>
                    </svg>
                </div>
                <div class="tf-room-info">
                    <div class="tf-room-num">Phòng ${r.room_number}</div>
                    <div class="tf-room-type">${r.type_name || '—'}</div>
                </div>
                <div class="tf-room-price">${r.price_per_night ? r.price_per_night.toLocaleString() : '0'}<small>đ</small></div>
                <div class="tf-check-icon">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
            </div>
        `).join('');

    } catch (e) {
        pmsToast(`Không thể tải phòng: ${e.message}`, false);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Select Room
// ─────────────────────────────────────────────────────────────────────────────
function pmsTfSelectRoom(roomId, roomNum, price) {
    // Remove previous selection
    document.querySelectorAll('.tf-room-item').forEach(el => {
        el.classList.remove('selected');
    });

    // Mark selected
    const target = document.querySelector(`.tf-room-item[data-id="${roomId}"]`);
    if (target) target.classList.add('selected');

    window.pmsTfSelectedId = roomId;

    // Update info
    const selEl = document.getElementById('tf-selected-info');
    if (selEl) selEl.textContent = `Phòng: ${roomNum} — ${pmsMoney(price)}`;

    const btnEl = document.getElementById('tf-submit-btn');
    if (btnEl) btnEl.disabled = false;
}

// ─────────────────────────────────────────────────────────────────────────────
// Submit Transfer
// ─────────────────────────────────────────────────────────────────────────────
async function submitTF() {
    if (!window.pmsTfStayId || !window.pmsTfSelectedId) {
        pmsToast('Vui lòng chọn phòng mới.', false);
        return;
    }

    const btnEl = document.getElementById('tf-submit-btn');
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = 'Đang xử lý...';
    }

    try {
        const fd = new FormData();
        fd.append('new_room_id', window.pmsTfSelectedId);

        const r = await pmsApi(`/api/pms/stays/${window.pmsTfStayId}/transfer`, {
            method: 'PUT',
            body: fd,
        });

        pmsToast(r.message);

        // Close modal
        if (typeof closeModal === 'function') closeModal('tfModal');
        else if (typeof pmsCloseModal === 'function') pmsCloseModal('tfModal');
        else document.getElementById('tfModal').classList.remove('show');

        // Reload room map
        if (typeof pmsLoadRooms === 'function') pmsLoadRooms(undefined, true);

    } catch (e) {
        pmsToast(e.message, false);
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.textContent = 'Xác nhận đổi phòng';
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Filter rooms locally by search query
// ─────────────────────────────────────────────────────────────────────────────
function pmsTfFilterRooms(query) {
    const q = (query || '').toLowerCase().trim();
    const listEl = document.getElementById('tf-room-list');
    if (!listEl) return;

    const allRooms = window._pmsTfAllRooms || [];
    const filtered = q ? allRooms.filter(r =>
        (r.room_number || '').toLowerCase().includes(q) ||
        (r.type_name || '').toLowerCase().includes(q)
    ) : allRooms;

    if (filtered.length === 0) {
        listEl.innerHTML = `<div class="tf-empty">
            <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <circle cx="11" cy="11" r="8"/>
                <path d="m21 21-4.3-4.3"/>
            </svg>
            <p>${q ? 'Không tìm thấy phòng phù hợp' : 'Không có phòng trống nào khả dụng'}</p>
        </div>`;
        return;
    }

    listEl.innerHTML = filtered.map(r => `
        <div class="tf-room-item" data-id="${r.id}" onclick="pmsTfSelectRoom(${r.id}, '${r.room_number}', ${r.price_per_night})">
            <div class="tf-room-icon">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                    <polyline points="9 22 9 12 15 12 15 22"/>
                </svg>
            </div>
            <div class="tf-room-info">
                <div class="tf-room-num">Phòng ${r.room_number}</div>
                <div class="tf-room-type">${r.type_name || '—'}</div>
            </div>
            <div class="tf-room-price">${r.price_per_night ? r.price_per_night.toLocaleString() : '0'}<small>đ</small></div>
            <div class="tf-check-icon">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
        </div>
    `).join('');

    // Re-apply selection if any
    if (window.pmsTfSelectedId) {
        const prev = document.querySelector(`.tf-room-item[data-id="${window.pmsTfSelectedId}"]`);
        if (prev) prev.classList.add('selected');
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Export globals
// ─────────────────────────────────────────────────────────────────────────────
window.openTF = openTF;
window.submitTF = submitTF;
window.pmsTfSelectRoom = pmsTfSelectRoom;
window.pmsTfLoadRooms = pmsTfLoadRooms;
window.pmsTfFilterRooms = pmsTfFilterRooms;
