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
let lastCancelledCount = null; // số booking huỷ lần poll trước
let _soundUnlocked = false; // Web Audio đã được unlock bởi user gesture

// ── Sound ──────────────────────────────────────────────────────────────
const _soundCache = {};
function playSound(filename) {
    try {
        if (!_soundCache[filename]) {
            _soundCache[filename] = new Audio(`/static/sounds/${filename}`);
        }
        const audio = _soundCache[filename];
        audio.currentTime = 0;
        audio.play().catch(() => { });
    } catch (e) { }
}
// Unlock âm thanh sau lần đầu user click vào trang
document.addEventListener('click', () => { _soundUnlocked = true; }, { once: true });

// Cập nhật title tab trình duyệt với số booking mới
function updateTabTitle(count) {
    const base = 'OTA Dashboard';
    document.title = count > 0 ? `(${count}) ${base} - Bin Bin Hotel` : `${base} - Bin Bin Hotel`;
}

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

    // User đang xem OTA Dashboard → clear badge và reset title
    localStorage.setItem('otaNewCount', '0');
    updateTabTitle(0);
    // Nếu badge vẫn còn trong cùng tab (ít xảy ra)
    const navBadge = document.getElementById('ota-nav-badge');
    if (navBadge) navBadge.style.display = 'none';
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
        const newCancelled = d.cancelled_count ?? 0;

        if (lastKnownCount === null || lastCancelledCount === null) {
            // Lần đầu — chỉ lưu baseline, không notify
            lastKnownCount = newTotal;
            lastCancelledCount = newCancelled;
            return;
        }

        let shouldReloadTable = false;

        if (newTotal > lastKnownCount) {
            // Có booking mới!
            const delta = newTotal - lastKnownCount;
            newBookingCount += delta;
            lastKnownCount = newTotal;

            // Phát âm thanh thông báo đặt phòng mới
            playSound('Add.mp3');

            // Cập nhật localStorage để badge hiển thị trên các trang khác
            const prev = parseInt(localStorage.getItem('otaNewCount') || '0', 10);
            localStorage.setItem('otaNewCount', prev + delta);

            // Cập nhật title tab trình duyệt
            updateTabTitle(prev + delta);

            // Hiện notification banner
            showNewBookingBanner(delta);
            shouldReloadTable = true;
        }

        if (newCancelled > lastCancelledCount) {
            // Có booking huỷ!
            const cancelDelta = newCancelled - lastCancelledCount;
            lastCancelledCount = newCancelled;
            
            // Phát âm thanh huỷ (dùng tạm Add.mp3 hoặc chuông khác nếu có, tuỳ chọn)
            playSound('Add.mp3'); 

            showCancellationBanner(cancelDelta, d.latest_cancelled_id);
            shouldReloadTable = true;
        }

        if (shouldReloadTable) {
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
        <button onclick="document.getElementById('newBookingBanner').remove(); newBookingCount=0; localStorage.setItem('otaNewCount', '0'); const nb = document.getElementById('ota-nav-badge'); if(nb) nb.style.display='none'; updatePageBadge();"
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

function showCancellationBanner(count, latest_cancelled_id) {
    const existing = document.getElementById('cancellationBanner');
    if (existing) existing.remove();

    const banner = document.createElement('div');
    banner.id = 'cancellationBanner';
    banner.style.cssText = `
        position: fixed; top: 140px; right: 20px; z-index: 9998;
        background: #ef4444; color: #fff; border-radius: 12px;
        padding: 14px 20px; box-shadow: 0 4px 20px rgba(239,68,68,0.4);
        display: flex; align-items: center; gap: 12px;
        font-size: 14px; font-weight: 500;
        animation: slideInRight 0.3s cubic-bezier(0.16,1,0.3,1);
        cursor: pointer;
    `;
    
    // Nếu có mã đơn phòng, hiển thị mã đơn
    const idText = latest_cancelled_id ? `[Mã đơn: ${latest_cancelled_id}]` : `${count} đơn phòng`;
    
    banner.innerHTML = `
        <span style="font-size:20px;">⚠️</span>
        <div>
            <div style="font-weight:700; font-size:13px; color:#fff;">Phòng vừa bị huỷ!</div>
            <div style="font-size:12px; color:rgba(255,255,255,0.85);">${idText} vừa bị huỷ trên OTA.</div>
        </div>
        <button onclick="document.getElementById('cancellationBanner').remove();"
            style="background:rgba(255,255,255,0.2); border:none; color:#fff; border-radius:6px; padding:4px 8px; cursor:pointer; font-size:11px;">✕</button>
    `;

    // Tự đóng sau 10s
    setTimeout(() => {
        if(document.getElementById('cancellationBanner')) {
            document.getElementById('cancellationBanner').remove();
        }
    }, 10000);
    document.body.appendChild(banner);
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
function setInitialCount(total, cancelled) {
    if (lastKnownCount === null) lastKnownCount = total;
    if (lastCancelledCount === null) lastCancelledCount = cancelled;
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
        setInitialCount(d.total_bookings ?? 0, d.cancelled_count ?? 0);
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

        // Đảm bảo các đơn đã huỷ không hiển thị là đã thanh toán
        allBookings.forEach(b => {
            const s = (b.status || '').toUpperCase();
            if (s === 'CANCELLED' || s === 'CANCELED' || s === 'FAILED') {
                b.is_prepaid = false;
            }
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

    // Parse date range (về đầu/cuối ngày) - theo NGÀY LƯU TRÚ, không phải ngày tạo đơn
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

        // Date filter (theo NGÀY LƯU TRÚ: khoảng check-in/check-out)
        if (fromTs || toTs) {
            // Nếu thiếu check_in/check_out thì không thể lọc theo ngày lưu trú → loại khỏi kết quả
            if (!b.check_in && !b.check_out) return false;

            // Mốc bắt đầu lưu trú: ngày check_in (00:00)
            const stayStartTs = b.check_in
                ? new Date(b.check_in + 'T00:00:00').getTime()
                : null;

            // Mốc kết thúc lưu trú: ngày check_out (23:59), nếu không có thì dùng check_in
            const stayEndTs = b.check_out
                ? new Date(b.check_out + 'T23:59:59').getTime()
                : stayStartTs;

            if (!stayStartTs || !stayEndTs) return false;

            // Điều kiện giao nhau giữa [stayStartTs, stayEndTs] và [fromTs, toTs]
            if (fromTs && stayEndTs < fromTs) return false;
            if (toTs && stayStartTs > toTs) return false;
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
        let totalPrice = b.total_price ? b.total_price.toLocaleString('vi-VN') + ' ' + (b.currency || 'VND') : '—';
        const s = (b.status || '').toUpperCase();
        if (s === 'CANCELLED' || s === 'CANCELED' || s === 'FAILED') {
            totalPrice = `<del style="color:#94a3b8;">${totalPrice}</del>`;
        }
        const statusBadge = renderStatus(b.status);
        const roomType = b.room_type || '—';
        const branchName = b.branch_name || 'Chưa map';
        const paymentLabel = renderPaymentLabel(b);
        const specialReq = b.special_requests || null;
        const stayCell = renderStayCell(b, checkIn, checkOut, nights);

        return `
        <tr onclick="showBookingDetail(${b.id})" style="cursor:pointer;">
            <td>
                <a class="order-id" href="javascript:void(0)" onclick="event.stopPropagation();showBookingDetail(${b.id})">
                    ${escapeHtml(b.external_id)}
                </a>
                <div class="order-date" style="margin-top:4px;">${createdDate}</div>
            </td>
            <td>
                <div class="ota-source">${escapeHtml(b.booking_source || '—')}</div>
                <div class="ota-id" style="margin-top:2px; font-size:11px; color:#94a3b8;">ID: ${b.id}</div>
            </td>
            <td>
                <div class="guest-name">${escapeHtml(b.guest_name)}</div>
                <div class="guest-count">${numGuests > 1 ? formatGuestText(b) : (numGuests + ' người lớn')}</div>
                ${b.guest_phone ? `<div style="font-size:11.5px; color:#64748b; margin-top:4px;"><i class="bi bi-telephone"></i> ${escapeHtml(b.guest_phone)}</div>` : ''}
            </td>
            <td>
                <div class="order-date" style="color:#64748b; font-weight:600; margin-bottom:4px;">${escapeHtml(branchName)}</div>
                <div class="room-name">${escapeHtml(roomType)}</div>
                ${(b.num_rooms || 1) > 1
                ? `<div style="margin-top:5px;"><span style="background:#fff3e0; color:#e8390e; font-size:11px; font-weight:600; padding:2px 7px; border-radius:4px; border:1px solid #ffd8b0;">${b.num_rooms} phòng</span></div>`
                : ''}
            </td>
            <td>${stayCell}</td>
            <td>${statusBadge}</td>
            <td>
                <span class="total-price">${totalPrice}</span>
                <div style="margin-top:4px;">${paymentLabel}</div>
            </td>
            <td style="max-width:200px; padding-right:12px;">
                ${specialReq
                ? `<div style="font-size:12.5px; color:#374151; line-height:1.4; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;" title="${escapeHtml(specialReq)}">${escapeHtml(specialReq)}</div>`
                : `<span style="color:#bbb; font-size:12px;">—</span>`
            }
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
    const isSameDay = b.check_in && b.check_out && b.check_in === b.check_out;
    const isHourly = isSameDay || nightsNum === 0;
    const totalPrice = b.total_price ? b.total_price.toLocaleString('vi-VN') + ' ' + (b.currency || 'VND') : '—';

    const checkinTimeStr = (isHourly && b.check_in_time) ? ` <span style="color:#6366f1">${escapeHtml(b.check_in_time)}</span>` : '';
    const checkoutTimeStr = (isHourly && b.check_out_time) ? ` <span style="color:#6366f1">${escapeHtml(b.check_out_time)}</span>` : '';
    const timeRangeStr = (b.check_in_time || b.check_out_time) ? `${b.check_in_time || '?'} – ${b.check_out_time || '?'}` : null;
    const nightsDisplay = isHourly
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

    // Hiện nút Chỉnh sửa nếu là admin
    const adminActions = document.getElementById('bm-admin-actions');
    if (adminActions) {
        adminActions.style.display = window.OTA_CONFIG?.isAdmin ? 'block' : 'none';
    }

    const modal = new bootstrap.Modal(document.getElementById('bookingDetailModal'));
    modal.show();
}

// ── Edit Booking Modal (Admin only) ────────────────────────────────────────
function openEditModal() {
    const b = allBookings.find(x => x.id === _currentBookingId || x.external_id === _currentBookingId);
    // _currentBookingId có thể là external_id hoặc id sau khi sửa, lấy chắc chắn hơn từ header
    const eid = document.getElementById('bm-booking-id')?.textContent?.trim();
    const booking = allBookings.find(x => x.external_id === eid);
    if (!booking) return;

    // Điền sẵn dữ liệu hiện tại vào form
    document.getElementById('em-booking-id').value = booking.id;
    document.getElementById('em-title').textContent = `#${booking.external_id} — ${booking.guest_name}`;
    document.getElementById('em-guest-name').value = booking.guest_name || '';
    document.getElementById('em-guest-phone').value = booking.guest_phone || '';

    // Populate branch options
    const branchSelect = document.getElementById('em-branch');
    if (branchSelect) {
        // Clear existing options except the first "Chưa gắn chi nhánh"
        branchSelect.innerHTML = '<option value="">-- Chưa gắn chi nhánh --</option>';
        const config = window.OTA_CONFIG || {};

        if (config.isAdmin) {
            // Lấy từ branchFilter
            const filterEl = document.getElementById('branchFilter');
            if (filterEl) {
                Array.from(filterEl.options).forEach(opt => {
                    if (opt.value) { // skip the empty "Tất cả" option
                        const newOption = document.createElement('option');
                        newOption.value = opt.value;
                        newOption.textContent = opt.textContent;
                        branchSelect.appendChild(newOption);
                    }
                });
            }
        } else if (config.currentBranch) {
            // Nếu là lễ tân, chỉ cho chọn chi nhánh của họ
            const newOption = document.createElement('option');
            newOption.value = config.currentBranch;
            newOption.textContent = config.currentBranch;
            branchSelect.appendChild(newOption);
        }

        branchSelect.value = booking.branch_name || '';
    }

    document.getElementById('em-room-type').value = booking.room_type || '';
    document.getElementById('em-num-rooms').value = booking.num_rooms || 1;
    document.getElementById('em-check-in').value = booking.check_in || '';
    document.getElementById('em-check-out').value = booking.check_out || '';
    document.getElementById('em-check-in-time').value = booking.check_in_time || '';
    document.getElementById('em-check-out-time').value = booking.check_out_time || '';
    document.getElementById('em-total-price').value = booking.total_price ? booking.total_price.toLocaleString('vi-VN') : '';
    document.getElementById('em-currency').value = booking.currency || 'VND';
    document.getElementById('em-status').value = (booking.status || 'CONFIRMED').toUpperCase();

    const isPrepaidSelect = document.getElementById('em-is-prepaid');
    if (isPrepaidSelect) {
        if (booking.is_prepaid === true) isPrepaidSelect.value = 'true';
        else if (booking.is_prepaid === false) isPrepaidSelect.value = 'false';
        else isPrepaidSelect.value = 'null';
    }

    document.getElementById('em-checkin-code').value = booking.checkin_code || '';
    document.getElementById('em-special-requests').value = booking.special_requests || '';

    // Đóng modal chi tiết, mở modal edit
    bootstrap.Modal.getInstance(document.getElementById('bookingDetailModal'))?.hide();
    setTimeout(() => {
        new bootstrap.Modal(document.getElementById('bookingEditModal')).show();
    }, 300);
}

async function saveBookingEdit() {
    const bookingId = document.getElementById('em-booking-id').value;
    if (!bookingId) return;

    const btn = document.getElementById('em-save-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Đang lưu...';

    const statusValue = document.getElementById('em-status').value || null;

    // Parse is_prepaid from the edit dropdown
    const isPrepaidSelect = document.getElementById('em-is-prepaid');
    let is_prepaid_val = null;
    if (isPrepaidSelect) {
        if (isPrepaidSelect.value === 'true') is_prepaid_val = true;
        else if (isPrepaidSelect.value === 'false') is_prepaid_val = false;
    } else {
        // Fallback for missing dropdown
        const eid = document.getElementById('bm-booking-id')?.textContent?.trim();
        const currBooking = allBookings.find(x => x.external_id === eid);
        is_prepaid_val = currBooking ? currBooking.is_prepaid : null;
    }

    const payload = {
        guest_name: document.getElementById('em-guest-name').value.trim() || null,
        guest_phone: document.getElementById('em-guest-phone').value.trim() || null,
        room_type: document.getElementById('em-room-type').value.trim() || null,
        num_rooms: parseInt(document.getElementById('em-num-rooms').value) || null,
        check_in: document.getElementById('em-check-in').value || null,
        check_out: document.getElementById('em-check-out').value || null,
        check_in_time: document.getElementById('em-check-in-time').value || null,
        check_out_time: document.getElementById('em-check-out-time').value || null,
        total_price: parseFloat(document.getElementById('em-total-price').value.replace(/\./g, '').replace(/,/g, '')) || null,
        currency: document.getElementById('em-currency').value || null,
        status: statusValue,
        checkin_code: document.getElementById('em-checkin-code').value.trim() || null,
        special_requests: document.getElementById('em-special-requests').value.trim() || null,
        is_prepaid: is_prepaid_val,
        branch_name: document.getElementById('em-branch')?.value || null,
    };

    try {
        const res = await fetch(`/api/ota/bookings/${bookingId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Lỗi khi lưu thay đổi');
        }

        const updated = await res.json();

        // Cập nhật lại object trong allBookings
        const idx = allBookings.findIndex(x => x.id === updated.id);
        if (idx !== -1) allBookings[idx] = updated;

        // Áp dụng lại filter (cập nhật bảng)
        applyFilters();

        // Tải lại các stats card (để cập nhật lại doanh thu tức thời)
        loadStats();

        bootstrap.Modal.getInstance(document.getElementById('bookingEditModal'))?.hide();
        showToast('✅ Đã cập nhật phiếu đặt phòng thành công!', 'success');
    } catch (err) {
        showToast('❌ ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Lưu thay đổi';
    }
}

// Format input giá tiền
document.addEventListener('DOMContentLoaded', () => {
    const priceInput = document.getElementById('em-total-price');
    if (priceInput) {
        priceInput.addEventListener('input', function () {
            let val = this.value.replace(/\D/g, ''); // chỉ lấy số
            this.value = val ? parseInt(val, 10).toLocaleString('vi-VN') : '';
        });
    }
});

function exportExcel(event) {
    event.preventDefault();

    // Export filteredBookings as CSV (Excel-compatible)
    const headers = ['Nguồn OTA', 'Mã đơn', 'Ngày tạo', 'Khách hàng', 'Số khách', 'SĐT', 'Chi nhánh', 'Loại phòng', 'Số lượng phòng', 'Check-in', 'Check-out', 'Số đêm', 'Trạng thái', 'Tổng tiền', 'Tình trạng thanh toán', 'Yêu cầu đặc biệt'];

    const rows = filteredBookings.map(b => [
        b.booking_source || '',
        b.external_id || '',
        b.created_at ? new Date(b.created_at).toLocaleString('vi-VN') : '',
        b.guest_name || '',
        b.num_guests || '',
        b.guest_phone || '',
        b.branch_name || '',
        b.room_type || '',
        b.num_rooms || 1,
        b.check_in || '',
        b.check_out || '',
        calcNightsNum(b.check_in, b.check_out),
        b.status || '',
        b.total_price ? (b.total_price + ' ' + (b.currency || 'VND')) : '',
        b.is_prepaid ? 'Đã thanh toán (OTA)' : (b.is_prepaid === false ? 'Khách trả tại khách sạn' : 'Chưa rõ'),
        b.special_requests || ''
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

    const confirmMsg = `Bạn có chắc chắn muốn chạy quét toàn bộ email đặt phòng OTA của ${dateLabel} không?\n\nLưu ý: Quá trình AI đọc và trích xuất dữ liệu có thể tốn khá nhiều thời gian (khoảng 30 giây tới vài phút) tùy thuộc vào độ trễ của hộp thư. Vui lòng không nhấn quét liên tục.`;
    if (!confirm(confirmMsg)) {
        return;
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

function renderPaymentLabel(booking) {
    const s = (booking.status || '').toUpperCase();
    if (s === 'CANCELLED' || s === 'CANCELED' || s === 'FAILED') {
        return `<div style="font-size:11px; color:#94a3b8; margin-top:3px;">— Đã hủy</div>`;
    }

    if (booking.is_prepaid === true) {
        return `<div style="font-size:11px; color:#22c55e; margin-top:3px; font-weight:500;">✓ Đã thanh toán (OTA)</div>`;
    } else if (booking.is_prepaid === false) {
        return `<div style="font-size:11px; color:#ef4444; margin-top:3px; font-weight:500;">✘ Chưa thanh toán</div>`;
    }
    return `<div style="font-size:11px; color:#94a3b8; margin-top:3px;">Chưa rõ TT</div>`;
}

function renderStatus(status) {
    const s = (status || '').toUpperCase();
    if (s === 'SUCCESS' || s === 'CONFIRMED' || s === 'ACTIVE') {
        return `<span class="status-badge success"><i class="bi bi-check-circle-fill"></i> Thành công</span>`;
    } else if (s === 'CANCELLED' || s === 'CANCELED' || s === 'FAILED') {
        return `<span class="status-badge cancelled"><i class="bi bi-x-circle-fill"></i> Đã huỷ</span>`;
    } else if (s === 'NO_SHOW') {
        return `<span class="status-badge no-show"><i class="bi bi-person-slash"></i> No-show</span>`;
    } else if (s === 'PENDING' || s === 'PROCESSING') {
        return `<span class="status-badge pending"><i class="bi bi-clock-fill"></i> Đang xử lý</span>`;
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

// ── Capture Modal as Image ──────────────────────────────────────────────────
async function captureBookingDetail() {
    const eid = document.getElementById('bm-booking-id')?.textContent?.trim() || 'unknown';
    const modalContent = document.querySelector('#bookingDetailModal .modal-content');
    if (!modalContent) return;

    try {
        // Tạm ẩn các element không mong muốn khi chụp bằng html2canvas
        const footer = modalContent.querySelector('.modal-footer');
        const closeBtn = modalContent.querySelector('.btn-close');
        // Tìm nút chụp ảnh bằng selector chuẩn xác hơn
        const captureBtn = modalContent.querySelector('button[onclick="captureBookingDetail()"]');
        
        if (footer) footer.style.display = 'none';
        if (closeBtn) closeBtn.style.display = 'none';
        if (captureBtn) captureBtn.style.display = 'none';

        // Gọi html2canvas
        const canvas = await html2canvas(modalContent, {
            scale: 2, // Tăng nét
            backgroundColor: document.body.classList.contains('dark') ? '#0f172a' : '#ffffff',
            useCORS: true
        });

        // Khôi phục lại hiển thị ban đầu
        if (footer) footer.style.display = '';
        if (closeBtn) closeBtn.style.display = '';
        if (captureBtn) captureBtn.style.display = '';

        // Tạo file ảnh và ném vào Clipboard
        canvas.toBlob(async (blob) => {
            if (!blob) throw new Error("Cannot create blob");
            try {
                const item = new ClipboardItem({ "image/png": blob });
                await navigator.clipboard.write([item]);

                // Hiệu ứng "Đã chép" cho nút
                if (captureBtn) {
                    const originalHTML = captureBtn.innerHTML;
                    const originalBg = captureBtn.style.backgroundColor || captureBtn.style.background;
                    captureBtn.innerHTML = '<i class="bi bi-check2"></i> <span style="font-size:12px; font-weight:500;">Đã chép</span>';
                    captureBtn.style.background = 'rgba(34,197,94,0.35)'; // Màu xanh lá nhẹ
                    setTimeout(() => {
                        captureBtn.innerHTML = originalHTML;
                        captureBtn.style.background = originalBg;
                    }, 2000);
                }

                showToast('Đã lưu ảnh phiếu phòng vào bộ nhớ tạm! Bạn có thể dán (Ctrl+V) vào Zalo ngay.', 'success');
            } catch (err) {
                console.error("Clipboard error:", err);
                showToast('Lỗi khi lưu. Trình duyệt chưa hỗ trợ sao chép ảnh!', 'error');
            }
        }, 'image/png');

    } catch (err) {
        console.error('Error capturing booking:', err);
        showToast('Không thể chụp ảnh, vui lòng thử lại', 'error');
        // Phục hồi lỡ xảy ra lỗi
        const modalContent = document.querySelector('#bookingDetailModal .modal-content');
        if (modalContent) {
            const footer = modalContent.querySelector('.modal-footer');
            const closeBtn = modalContent.querySelector('.btn-close');
            const captureBtn = modalContent.querySelector('button[onclick="captureBookingDetail()"]');
            if (footer) footer.style.display = '';
            if (closeBtn) closeBtn.style.display = '';
            if (captureBtn) captureBtn.style.display = '';
        }
    }
}

