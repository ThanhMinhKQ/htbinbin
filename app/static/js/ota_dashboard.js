/**
 * OTA Booking Manager Dashboard
 * Giao diện quản lý đặt phòng - phong cách OTA manager
 */

// ── State ──────────────────────────────────────────────────────────────────
let allBookings = [];       // toàn bộ booking đã tải
let filteredBookings = [];  // sau khi lọc/tìm kiếm
let currentPage = 1;
const PAGE_SIZE = 20;
let searchTimer = null;
let autoRefreshInterval = null;
let lastKnownCount = null;  // số booking lần poll trước
let newBookingCount = 0;    // số booking mới chưa xem

// ── Init ───────────────────────────────────────────────────────────────────
window.onload = () => {
    // Set mặc định date picker là hôm nay
    const dateInput = document.getElementById('scanDateInput');
    if (dateInput) {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        dateInput.value = `${yyyy}-${mm}-${dd}`;
        dateInput.max = `${yyyy}-${mm}-${dd}`;
    }
    loadStats();
    loadBranches();
    loadBookings();
    startSmartPolling();
};

// ── Smart Polling (15s) ────────────────────────────────────────────────────
function startSmartPolling() {
    autoRefreshInterval = setInterval(checkForNewBookings, 15000);
}

async function checkForNewBookings() {
    try {
        const config = window.OTA_CONFIG || {};
        let url = '/api/ota/stats';
        let branch = '';
        if (!config.isAdmin && config.currentBranch) {
            branch = config.currentBranch;
        } else {
            const el = document.getElementById('branchFilter');
            branch = el ? el.value : '';
        }
        if (branch) url += `?branch_name=${encodeURIComponent(branch)}`;

        const res = await fetch(url);
        const d = await res.json();
        const newTotal = d.total_bookings ?? 0;

        if (lastKnownCount === null) {
            // Lần đầu — chỉ lưu baseline, không notify
            lastKnownCount = newTotal;
            return;
        }

        if (newTotal > lastKnownCount) {
            // Có booking mới!
            const delta = newTotal - lastKnownCount;
            newBookingCount += delta;
            lastKnownCount = newTotal;

            // Hiện notification banner
            showNewBookingBanner(delta);

            // Cập nhật stats cards và bảng ngay lập tức (silent)
            updateStatsFromData(d);
            loadBookings(false);
        }
    } catch (e) {
        // Silently ignore polling errors
    }
}

function showNewBookingBanner(count) {
    const existing = document.getElementById('newBookingBanner');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.id = 'newBookingBanner';
    banner.style.cssText = `
        position: fixed; top: 72px; right: 20px; z-index: 9999;
        background: #1a73e8; color: #fff; border-radius: 12px;
        padding: 14px 20px; box-shadow: 0 4px 20px rgba(26,115,232,0.4);
        display: flex; align-items: center; gap: 12px;
        font-size: 14px; font-weight: 500;
        animation: slideInRight 0.3s cubic-bezier(0.16,1,0.3,1);
        cursor: pointer;
    `;
    banner.innerHTML = `
        <span style="font-size:20px;">🔔</span>
        <div>
            <div style="font-weight:700; font-size:13px; color:#fff;">Đặt phòng mới!</div>
            <div style="font-size:12px; color:rgba(255,255,255,0.85);">${count} đặt phòng vừa được thêm — Đang tải...</div>
        </div>
        <button onclick="document.getElementById('newBookingBanner').remove(); newBookingCount=0;"
            style="background:rgba(255,255,255,0.2); border:none; color:#fff; border-radius:6px; padding:4px 8px; cursor:pointer; font-size:11px;">✕</button>
    `;

    // Tự đóng sau 8s
    setTimeout(() => banner.remove(), 8000);
    document.body.appendChild(banner);

    // Cập nhật badge trên title trang
    updatePageBadge();
}

function updatePageBadge() {
    if (newBookingCount > 0) {
        document.title = `(${newBookingCount}) Đặt phòng mới — OTA Dashboard`;
    } else {
        document.title = 'Quản lý đặt phòng OTA — Bin Bin Hotel';
    }
}

// Cập nhật stats mà không cần gọi API lần nữa (dùng data từ poll)
function updateStatsFromData(d) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? '—'; };
    set('statTotal', d.total_bookings);
    set('statConfirmed', d.confirmed_count);
    set('statCancelled', d.cancelled_count);
    set('statToday', d.bookings_today);
    set('statMonth', d.bookings_this_month);
    const rev = d.total_revenue || 0;
    const el = document.getElementById('statRevenue');
    if (el) el.textContent = rev > 0 ? rev.toLocaleString('vi-VN') + ' ₫' : '—';
}

// Đặt count ban đầu ngay sau load đầu tiên
function setInitialCount(total) {
    if (lastKnownCount === null) lastKnownCount = total;
}

// ── Stats ──────────────────────────────────────────────────────────────────
async function loadStats() {
    try {
        const config = window.OTA_CONFIG || {};
        let url = '/api/ota/stats';

        let branch = '';
        if (!config.isAdmin && config.currentBranch) {
            // Letan: luôn dùng chi nhánh từ session
            branch = config.currentBranch;
        } else {
            // Admin/manager: đọc từ dropdown (nếu đã chọn chi nhánh cụ thể)
            const branchEl = document.getElementById('branchFilter');
            branch = branchEl ? branchEl.value : '';
        }

        if (branch) url += `?branch_name=${encodeURIComponent(branch)}`;

        const res = await fetch(url);
        const d = await res.json();

        document.getElementById('statTotal').textContent = d.total_bookings ?? '—';
        document.getElementById('statConfirmed').textContent = d.confirmed_count ?? '—';
        document.getElementById('statCancelled').textContent = d.cancelled_count ?? '—';
        document.getElementById('statToday').textContent = d.bookings_today ?? '—';
        document.getElementById('statMonth').textContent = d.bookings_this_month ?? '—';

        // Format doanh thu
        const rev = d.total_revenue || 0;
        document.getElementById('statRevenue').textContent =
            rev > 0 ? rev.toLocaleString('vi-VN') + ' ₫' : '—';

        // Lưu baseline cho smart polling
        setInitialCount(d.total_bookings ?? 0);
    } catch (e) {
        console.error('Error loading stats:', e);
    }
}

// Gọi cả stats + bookings cùng lúc (dùng khi đổi chi nhánh)
function reloadAll() {
    loadStats();
    loadBookings();
}

// ── Branches ───────────────────────────────────────────────────────────────
async function loadBranches() {
    // Letan không cần dropdown vì đã auto-filter
    const config = window.OTA_CONFIG || {};
    if (!config.isAdmin) return;

    try {
        const res = await fetch('/api/ota/bookings?limit=100');
        const bookings = await res.json();
        const branchSet = new Map();
        bookings.forEach(b => {
            if (b.branch_name) branchSet.set(b.branch_name, b.branch_name);
        });

        const sel = document.getElementById('branchFilter');
        if (!sel) return;
        branchSet.forEach((name) => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error('Error loading branches:', e);
    }
}

// ── Load Bookings ──────────────────────────────────────────────────────────
async function loadBookings(showLoader = true) {
    if (showLoader) {
        document.getElementById('bookingsTable').innerHTML = `
            <tr class="loading-row">
                <td colspan="8">
                    <div class="spinner-border spinner-border-sm text-secondary me-2" role="status"></div>
                    Đang tải dữ liệu...
                </td>
            </tr>`;
    }

    const config = window.OTA_CONFIG || {};
    const ota = document.getElementById('otaFilter').value;

    let url = `/api/ota/bookings?limit=200`;
    if (ota) url += `&ota=${encodeURIComponent(ota)}`;

    // Nếu là letan → tự động lọc theo chi nhánh hiện tại từ server
    if (!config.isAdmin && config.currentBranch) {
        url += `&branch_name=${encodeURIComponent(config.currentBranch)}`;
    } else {
        // Admin/manager: dùng dropdown chọn chi nhánh
        const branchFilter = document.getElementById('branchFilter');
        const branch = branchFilter ? branchFilter.value : '';
        if (branch) url += `&branch_name=${encodeURIComponent(branch)}`;
    }

    try {
        const res = await fetch(url);
        const data = await res.json();
        // Sort mới nhất lên đầu (dự phòng server đã sort sẵn)
        allBookings = (Array.isArray(data) ? data : []).sort((a, b) => {
            const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
            const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
            return tb - ta;
        });
        applyFilters();
    } catch (e) {
        console.error('Error loading bookings:', e);
        showToast('Không thể tải danh sách đặt phòng', 'error');
        document.getElementById('bookingsTable').innerHTML = `
            <tr class="empty-row"><td colspan="8">Lỗi tải dữ liệu. Vui lòng thử lại.</td></tr>`;
    }
}

// ── Filter & Search ────────────────────────────────────────────────────────
function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => applyFilters(), 300);
}

function applyFilters() {
    const keyword = (document.getElementById('searchInput').value || '').toLowerCase().trim();
    const statusFilter = document.getElementById('statusFilter').value.toLowerCase();
    const branchFilter = document.getElementById('branchFilter').value.toLowerCase();
    const dateFrom = document.getElementById('dateFromFilter')?.value || '';
    const dateTo = document.getElementById('dateToFilter')?.value || '';

    // Parse date range (về đầu/cuối ngày)
    const fromTs = dateFrom ? new Date(dateFrom + 'T00:00:00').getTime() : null;
    const toTs = dateTo ? new Date(dateTo + 'T23:59:59').getTime() : null;

    filteredBookings = allBookings.filter(b => {
        // Search keyword
        if (keyword) {
            const haystack = [
                b.external_id,
                b.guest_name,
                b.booking_source,
                b.branch_name,
                b.room_type
            ].filter(Boolean).join(' ').toLowerCase();
            if (!haystack.includes(keyword)) return false;
        }

        // Status filter
        if (statusFilter && b.status.toLowerCase() !== statusFilter) return false;

        // Branch filter
        if (branchFilter && (b.branch_name || '').toLowerCase() !== branchFilter) return false;

        // Date filter (theo ngày tạo đơn)
        if (fromTs || toTs) {
            const createdTs = b.created_at ? new Date(b.created_at).getTime() : null;
            if (!createdTs) return false;
            if (fromTs && createdTs < fromTs) return false;
            if (toTs && createdTs > toTs) return false;
        }

        return true;
    });

    currentPage = 1;
    renderTable();
    renderPagination();
}

function clearDateFilter() {
    const fromEl = document.getElementById('dateFromFilter');
    const toEl = document.getElementById('dateToFilter');
    if (fromEl) fromEl.value = '';
    if (toEl) toEl.value = '';
    applyFilters();
}

// ── Render Table ───────────────────────────────────────────────────────────
function renderTable() {
    const tbody = document.getElementById('bookingsTable');
    const start = (currentPage - 1) * PAGE_SIZE;
    const pageData = filteredBookings.slice(start, start + PAGE_SIZE);

    if (pageData.length === 0) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="8">Không tìm thấy đơn đặt phòng nào.</td></tr>`;
        return;
    }

    tbody.innerHTML = pageData.map(b => {
        const createdDate = formatDateTime(b.created_at);
        const checkIn = b.check_in ? formatDate(b.check_in) : '—';
        const checkOut = b.check_out ? formatDate(b.check_out) : '—';
        const nights = calcNights(b.check_in, b.check_out);
        const numGuests = b.num_guests || 0;
        const totalPrice = b.total_price ? b.total_price.toLocaleString('vi-VN') + ' ' + (b.currency || 'VND') : '—';
        const statusBadge = renderStatus(b.status);
        const roomType = b.room_type || '—';
        const branchName = b.branch_name || 'Chưa map';
        const paymentLabel = renderPaymentLabel(b.status);
        const specialReq = b.special_requests || null;
        const stayCell = renderStayCell(b, checkIn, checkOut, nights);

        return `
        <tr onclick="showBookingDetail(${b.id})" style="cursor:pointer;">
            <td>
                <a class="order-id" href="javascript:void(0)" onclick="event.stopPropagation();showBookingDetail(${b.id})">
                    ${escapeHtml(b.external_id)}
                </a>
                <div class="order-date">${createdDate}</div>
            </td>
            <td>
                <div class="room-name">${escapeHtml(roomType)}</div>
                <div class="order-date" style="color:#aaa; margin-top:2px;">${escapeHtml(branchName)}</div>
                ${(b.num_rooms || 1) > 1
                ? `<div style="margin-top:3px;"><span style="background:#fff3e0; color:#e8390e; font-size:11px; font-weight:600; padding:2px 7px; border-radius:4px; border:1px solid #ffd8b0;">${b.num_rooms} phòng</span></div>`
                : ''}
            </td>
            <td>
                <div class="guest-name">${escapeHtml(b.guest_name)}</div>
                <div class="guest-count">${numGuests > 1 ? formatGuestText(b) : (numGuests + ' người lớn')}</div>
            </td>
            <td>${statusBadge}</td>
            <td style="max-width:180px;">
                ${specialReq
                ? `<span style="font-size:12.5px; color:#374151; line-height:1.4;">${escapeHtml(specialReq)}</span>`
                : `<span style="color:#bbb; font-size:12px;">—</span>`
            }
            </td>
            <td>
                <div class="ota-source">${escapeHtml(b.booking_source || '—')}</div>
                <div class="ota-id">ID: ${b.id}</div>
            </td>
            <td>${stayCell}</td>
            <td>
                <span class="total-price">${totalPrice}</span>
                ${paymentLabel}
            </td>
        </tr>`;
    }).join('');
}

// ── Render Pagination ──────────────────────────────────────────────────────
function renderPagination() {
    const total = filteredBookings.length;
    const totalPages = Math.ceil(total / PAGE_SIZE);
    const start = (currentPage - 1) * PAGE_SIZE + 1;
    const end = Math.min(currentPage * PAGE_SIZE, total);

    document.getElementById('paginationInfo').textContent =
        total > 0 ? `Hiển thị ${start}–${end} / ${total} đơn` : 'Không có dữ liệu';

    const btnsEl = document.getElementById('paginationBtns');
    if (totalPages <= 1) {
        btnsEl.innerHTML = '';
        return;
    }

    let html = '';

    // Prev
    html += `<button class="page-btn" onclick="goPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>
        <i class="bi bi-chevron-left"></i>
    </button>`;

    // Pages
    const range = getPageRange(currentPage, totalPages);
    range.forEach(p => {
        if (p === '...') {
            html += `<button class="page-btn" disabled>…</button>`;
        } else {
            html += `<button class="page-btn ${p === currentPage ? 'active' : ''}" onclick="goPage(${p})">${p}</button>`;
        }
    });

    // Next
    html += `<button class="page-btn" onclick="goPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>
        <i class="bi bi-chevron-right"></i>
    </button>`;

    btnsEl.innerHTML = html;
}

function getPageRange(current, total) {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    if (current <= 4) return [1, 2, 3, 4, 5, '...', total];
    if (current >= total - 3) return [1, '...', total - 4, total - 3, total - 2, total - 1, total];
    return [1, '...', current - 1, current, current + 1, '...', total];
}

function goPage(page) {
    const totalPages = Math.ceil(filteredBookings.length / PAGE_SIZE);
    if (page < 1 || page > totalPages) return;
    currentPage = page;
    renderTable();
    renderPagination();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Booking Detail Modal ───────────────────────────────────────────────────
let _currentBookingId = null;

function copyBookingId() {
    const id = document.getElementById('bm-booking-id')?.textContent?.trim();
    if (!id || id === '—') return;
    navigator.clipboard.writeText(id).then(() => {
        const btn = document.getElementById('bm-copy-btn');
        if (btn) {
            btn.innerHTML = '<i class="bi bi-check2" style="font-size:13px;"></i> Đã sao chép';
            btn.style.background = 'rgba(34,197,94,0.35)';
            setTimeout(() => {
                btn.innerHTML = '<i class="bi bi-clipboard" style="font-size:13px;"></i> Sao chép';
                btn.style.background = 'rgba(255,255,255,0.2)';
            }, 1800);
        }
        showToast('Đã sao chép mã đặt phòng!', 'success');
    });
}

function infoCard(icon, label, value, accent) {
    if (!value && value !== 0) return '';
    const color = accent || '#374151';
    return `
    <div style="background:#f8faff; border:1px solid #e8edf5; border-radius:12px; padding:12px 14px; display:flex; flex-direction:column; gap:3px;">
        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:.6px; font-weight:600;">
            <i class="bi bi-${icon}" style="margin-right:4px;"></i>${label}
        </div>
        <div style="font-size:14px; font-weight:600; color:${color}; line-height:1.4;">${value}</div>
    </div>`;
}

function showBookingDetail(bookingId) {
    const b = allBookings.find(x => x.id === bookingId);
    if (!b) return;
    _currentBookingId = b.external_id;

    // ── Cập nhật header modal ──
    document.getElementById('bm-guest-name').textContent = b.guest_name || '—';
    document.getElementById('bm-booking-id').textContent = b.external_id || '—';
    document.getElementById('bm-ota-badge').textContent = b.booking_source || '—';

    // ── Tính toán dữ liệu ──
    const checkIn = b.check_in ? formatDate(b.check_in) : '—';
    const checkOut = b.check_out ? formatDate(b.check_out) : '—';
    const nights = calcNights(b.check_in, b.check_out);
    const nightsNum = calcNightsNum(b.check_in, b.check_out);
    const totalPrice = b.total_price ? b.total_price.toLocaleString('vi-VN') + ' ' + (b.currency || 'VND') : '—';

    const checkinTimeStr = b.check_in_time ? ` <span style="color:#6366f1">${escapeHtml(b.check_in_time)}</span>` : '';
    const checkoutTimeStr = b.check_out_time ? ` <span style="color:#6366f1">${escapeHtml(b.check_out_time)}</span>` : '';
    const timeRangeStr = (b.check_in_time || b.check_out_time) ? `${b.check_in_time || '?'} – ${b.check_out_time || '?'}` : null;
    const nightsDisplay = nightsNum === 0
        ? `<span style="color:#6366f1; font-weight:600;">${timeRangeStr || 'Thuê giờ'}</span>`
        : nights;

    const guestStr = (() => {
        const parts = [];
        if (b.num_adults) parts.push(b.num_adults + ' người lớn');
        if (b.num_children) parts.push(b.num_children + ' trẻ em');
        return parts.length ? parts.join(', ') : (b.num_guests || 0) + ' người';
    })();

    const roomStr = b.room_type
        ? (b.room_type + ((b.num_rooms || 1) > 1 ? ` × ${b.num_rooms} phòng` : ''))
        : '—';

    // ── Render body dạng grid card ──
    document.getElementById('bookingDetailContent').innerHTML = `
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            ${infoCard('building', 'Chi nhánh', escapeHtml(b.branch_name || 'Chưa map'))}
            ${infoCard('door-open', 'Loại phòng', escapeHtml(roomStr))}
            ${infoCard('box-arrow-in-right', 'Check-in', checkIn + checkinTimeStr)}
            ${infoCard('box-arrow-right', 'Check-out', checkOut + checkoutTimeStr)}
            ${infoCard('moon', 'Lưu trú', nightsDisplay)}
            ${infoCard('people', 'Số khách', guestStr)}
            ${infoCard('cash-stack', 'Tổng tiền', totalPrice, '#e8390e')}
            ${infoCard('patch-check', 'Trạng thái', renderStatus(b.status))}
            ${b.checkin_code ? infoCard('key', 'Mã check-in', `<span style="font-family:monospace; color:#1a73e8;">${escapeHtml(b.checkin_code)}</span>`) : ''}
            ${b.guest_phone ? infoCard('telephone', 'Điện thoại', escapeHtml(b.guest_phone)) : ''}
        </div>
        ${b.special_requests ? `
        <div style="margin-top:12px; background:#fffbeb; border:1px solid #fde68a; border-radius:12px; padding:12px 14px;">
            <div style="font-size:11px; color:#92400e; text-transform:uppercase; letter-spacing:.6px; font-weight:600; margin-bottom:6px;">
                <i class="bi bi-chat-left-text me-1"></i>Yêu cầu của khách
            </div>
            <div style="font-size:13.5px; color:#78350f; line-height:1.5;">${escapeHtml(b.special_requests)}</div>
        </div>` : ''}
        <div style="margin-top:10px; font-size:11.5px; color:#94a3b8; text-align:right;">
            <i class="bi bi-clock me-1"></i>Ngày tạo: ${formatDateTime(b.created_at)}
        </div>`;

    const modal = new bootstrap.Modal(document.getElementById('bookingDetailModal'));
    modal.show();
}



// ── Export Excel ───────────────────────────────────────────────────────────
function exportExcel(event) {
    event.preventDefault();

    // Export filteredBookings as CSV (Excel-compatible)
    const headers = ['Mã đơn', 'Phòng', 'Khách hàng', 'Số khách', 'Trạng thái',
        'OTA', 'Chi nhánh', 'Check-in', 'Check-out', 'Số đêm', 'Tổng tiền', 'Ngày tạo'];

    const rows = filteredBookings.map(b => [
        b.external_id,
        b.room_type || '',
        b.guest_name,
        b.num_guests,
        b.status,
        b.booking_source,
        b.branch_name || '',
        b.check_in || '',
        b.check_out || '',
        calcNightsNum(b.check_in, b.check_out),
        b.total_price ? (b.total_price + ' ' + (b.currency || 'VND')) : '',
        b.created_at ? new Date(b.created_at).toLocaleString('vi-VN') : ''
    ]);

    const csvContent = '\uFEFF' + [headers, ...rows]
        .map(row => row.map(cell => `"${String(cell || '').replace(/"/g, '""')}"`).join(','))
        .join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `dat-phong-ota-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);

    showToast('Đã xuất file Excel thành công!', 'success');
}

// ── Manual Scan (ngày tùy chọn) ───────────────────────────────────────────
async function scanTodayEmails() {
    const btn = document.getElementById('btnScanToday');
    const dateInput = document.getElementById('scanDateInput');
    const selectedDate = dateInput ? dateInput.value : '';

    // Hiển thị ngày dưới dạng dd/mm/yyyy
    let dateLabel = 'hôm nay';
    if (selectedDate) {
        const [y, m, d] = selectedDate.split('-');
        dateLabel = `${d}/${m}/${y}`;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Đang quét...';
    }

    try {
        let url = '/api/ota/scan-today';
        if (selectedDate) url += `?scan_date=${encodeURIComponent(selectedDate)}`;

        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'started') {
            showToast(`✅ Đang quét email ngày ${dateLabel}! Dữ liệu sẽ cập nhật sau vài giây...`, 'success');
            setTimeout(() => {
                loadStats();
                loadBookings();
            }, 5000);
        } else {
            showToast('Không thể bắt đầu quét: ' + (data.message || ''), 'error');
        }
    } catch (e) {
        showToast('Lỗi kết nối khi quét email', 'error');
        console.error('Scan error:', e);
    } finally {
        setTimeout(() => {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Quét mail';
            }
        }, 6000);
    }
}

// ── Helpers ────────────────────────────────────────────────────────────────
function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
    } catch { return dateStr; }
}

function formatDateTime(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
            + '\n' + d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return dateStr; }
}

function calcNights(checkIn, checkOut) {
    const n = calcNightsNum(checkIn, checkOut);
    if (n === null) return '—';
    return `${n} đêm`;
}

function calcNightsNum(checkIn, checkOut) {
    if (!checkIn || !checkOut) return null;
    try {
        const diff = new Date(checkOut) - new Date(checkIn);
        return Math.max(0, Math.round(diff / 86400000));
    } catch { return null; }
}

function formatGuestText(b) {
    // Attempt to display guest count meaningfully
    const n = b.num_guests || 0;
    if (n <= 0) return '';
    return `${n} người lớn`;
}

// Render cột "Số ngày lưu trú" với hỗ trợ thuê giờ (Go2Joy)
function renderStayCell(b, checkIn, checkOut, nights) {
    const n = calcNightsNum(b.check_in, b.check_out);
    const isSameDay = b.check_in && b.check_out && b.check_in === b.check_out;

    if (isSameDay || n === 0) {
        // Phòng giờ: check-in và check-out cùng ngày
        const timeFrom = b.check_in_time || '?';
        const timeTo = b.check_out_time || '?';
        const timeRange = (b.check_in_time || b.check_out_time)
            ? `${timeFrom} – ${timeTo}`
            : null;
        return `
            <div class="stay-dates">${checkIn}</div>
            <div class="stay-nights" style="color:#6366f1; font-weight:600;">${timeRange || 'Thuê giờ'}</div>`;
    }

    // Phòng ngày bình thường: chỉ hiện ngày và số đêm
    return `
        <div class="stay-dates">${checkIn} – ${checkOut}</div>
        <div class="stay-nights">${nights}</div>`;
}

function renderPaymentLabel(status) {
    const s = (status || '').toUpperCase();
    if (s === 'SUCCESS' || s === 'CONFIRMED' || s === 'ACTIVE') {
        return `<div style="font-size:11px; color:#22c55e; margin-top:3px; font-weight:500;">✓ Đã thanh toán</div>`;
    } else if (s === 'CANCELLED' || s === 'CANCELED' || s === 'FAILED') {
        return `<div style="font-size:11px; color:#94a3b8; margin-top:3px;">— Đã hủy</div>`;
    } else if (s === 'PENDING' || s === 'PROCESSING') {
        return `<div style="font-size:11px; color:#f59e0b; margin-top:3px; font-weight:500;">⏳ Chưa xác nhận</div>`;
    }
    return `<div style="font-size:11px; color:#94a3b8; margin-top:3px;">Chưa rõ</div>`;
}

function renderStatus(status) {
    const s = (status || '').toUpperCase();
    if (s === 'SUCCESS' || s === 'CONFIRMED' || s === 'ACTIVE') {
        return `<span class="status-badge success"><i class="bi bi-check-circle-fill"></i> Thành công</span>`;
    } else if (s === 'PENDING' || s === 'PROCESSING') {
        return `<span class="status-badge pending"><i class="bi bi-clock-fill"></i> Đang xử lý</span>`;
    } else if (s === 'CANCELLED' || s === 'CANCELED' || s === 'FAILED') {
        return `<span class="status-badge cancelled"><i class="bi bi-x-circle-fill"></i> Đã huỷ</span>`;
    }
    return `<span class="status-badge" style="color:#888;">${escapeHtml(status)}</span>`;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function showToast(message, type = 'success') {
    const toastEl = document.getElementById('mainToast');
    toastEl.classList.remove('bg-success', 'bg-danger', 'bg-warning');
    toastEl.classList.add(type === 'success' ? 'bg-success' : type === 'error' ? 'bg-danger' : 'bg-warning');
    document.getElementById('toastBody').textContent = message;
    const toast = new bootstrap.Toast(toastEl, { delay: 3000 });
    toast.show();
}
