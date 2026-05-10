'use strict';

/**
 * PMS Guest History — Guest accommodation history page
 * Shows all stays for a specific guest
 */

(function () {
    // ── Helpers ────────────────────────────────────────────────────────────────

    function escHtml(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    }

    function ghFmtDate(iso) {
        if (!iso) return '—';
        const d = typeof pmsParseDate === 'function' ? pmsParseDate(iso) : new Date(iso);
        if (isNaN(d)) return '—';
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const yyyy = d.getFullYear();
        return `${dd}/${mm}/${yyyy}`;
    }

    function ghFmtDateTime(iso) {
        if (!iso) return '—';
        return `${ghFmtDate(iso)} ${String(new Date(iso).getHours()).padStart(2, '0')}:${String(new Date(iso).getMinutes()).padStart(2, '0')}`;
    }

    function ghMoney(n) {
        const v = Number(n) || 0;
        try {
            return new Intl.NumberFormat('vi-VN').format(Math.round(v)) + ' đ';
        } catch (e) {
            return String(Math.round(v)) + ' đ';
        }
    }

    function ghCalcNights(ciIso, coIso) {
        if (!ciIso || !coIso) return 0;
        const ci = typeof pmsParseDate === 'function' ? pmsParseDate(ciIso) : new Date(ciIso);
        const co = typeof pmsParseDate === 'function' ? pmsParseDate(coIso) : new Date(coIso);
        if (isNaN(ci) || isNaN(co)) return 0;
        const ms = co - ci;
        if (ms <= 0) return 0;
        return Math.ceil(ms / 86400000);
    }

    function ghNormSummary(raw) {
        const s = String(raw || '').toLowerCase();
        if (s === 'debt') return 'debt';
        if (s === 'refund') return 'refund';
        return 'paid';
    }

    // ── SVG Icons ──────────────────────────────────────────────────────────────

    const SVG = {
        user: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        check: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        warn: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        clock: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
        empty: '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    };

    // ── State ───────────────────────────────────────────────────────────────────

    const state = {
        page: 1,
        pageSize: 24,
        branchId: null,
        dateFrom: null,
        dateTo: null,
        guestId: null,
        total: 0,
        pages: 0,
        loading: false,
        allItems: [],
        items: [],
        quickSearch: '',
        quickStatus: 'all',
        sort: 'newest',
    };

    let _abortCtrl = null;

    // ── Flatpickr Init ──────────────────────────────────────────────────────────

    function ghInitDatePickers() {
        const defaultFrom = new Date();
        defaultFrom.setDate(defaultFrom.getDate() - 365);

        const fpConfig = {
            dateFormat: 'd/m/Y',
            locale: typeof flatpickr !== 'undefined' && flatpickr.l10ns && flatpickr.l10ns.vn ? 'vn' : 'default',
            disableMobile: true,
        };

        const elFrom = document.getElementById('gh-date-from');
        const elTo = document.getElementById('gh-date-to');

        if (elFrom && typeof flatpickr === 'function') {
            flatpickr(elFrom, { ...fpConfig, defaultDate: defaultFrom });
            state.dateFrom = defaultFrom.toISOString().split('T')[0];
        }
        if (elTo && typeof flatpickr === 'function') {
            flatpickr(elTo, { ...fpConfig, defaultDate: new Date() });
            state.dateTo = new Date().toISOString().split('T')[0];
        }
    }

    // ── API ─────────────────────────────────────────────────────────────────────

    async function ghApi(url, signal) {
        const opts = { method: 'GET', credentials: 'same-origin' };
        if (signal) opts.signal = signal;

        if (typeof pmsApi === 'function') {
            return pmsApi(url, opts);
        }
        const res = await fetch(url, opts);
        const text = await res.text();
        let data;
        try { data = JSON.parse(text); } catch (e) { throw new Error('Phản hồi không hợp lệ'); }
        if (!res.ok) {
            const d = data && data.detail;
            throw new Error(typeof d === 'string' ? d : (d && d.message) || res.statusText || 'Lỗi API');
        }
        return data;
    }

    function ghToast(msg, type) {
        if (typeof pmsToast === 'function') { pmsToast(msg, type || 'info'); return; }
        alert(msg);
    }

    // ── Render: Guest Badge ─────────────────────────────────────────────────────

    function ghUpdateGuestBadge(guest, stats) {
        const badge = document.getElementById('gh-guest-badge');
        const avatar = document.getElementById('gh-avatar');
        const nameEl = document.getElementById('gh-guest-name');
        const metaEl = document.getElementById('gh-guest-meta');
        const staysEl = document.getElementById('gh-stat-stays');
        const spentEl = document.getElementById('gh-stat-spent');
        const depositEl = document.getElementById('gh-stat-deposit');

        if (!badge) return;

        if (guest) {
            badge.style.display = 'flex';
            if (nameEl) nameEl.textContent = guest.full_name || '—';

            let meta = '';
            if (guest.cccd) meta += 'CCCD: ' + guest.cccd;
            if (guest.phone) meta += (meta ? ' · ' : '') + guest.phone;
            if (metaEl) metaEl.textContent = meta || '—';

            if (avatar) {
                const initials = String(guest.full_name || '?').trim().split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?';
                avatar.textContent = initials;
            }

            if (staysEl) staysEl.textContent = stats ? (stats.total_stays || 0) : 0;
            if (spentEl) spentEl.textContent = stats ? ghMoney(stats.total_spent || 0) : '0 đ';
            if (depositEl) depositEl.textContent = stats ? ghMoney(stats.total_deposit || 0) : '0 đ';
        } else {
            badge.style.display = 'none';
        }
    }

    function ghNormText(s) {
        return String(s || '').trim().toLowerCase();
    }

    function ghBuildStatusCounts(items) {
        const counts = { all: 0, paid: 0, debt: 0, refund: 0 };
        (items || []).forEach((it) => {
            const st = ghNormSummary(it.summary_status);
            counts.all += 1;
            if (st === 'debt') counts.debt += 1;
            else if (st === 'refund') counts.refund += 1;
            else counts.paid += 1;
        });
        return counts;
    }

    function ghUpdateStatusChips() {
        const counts = ghBuildStatusCounts(state.allItems);

        const allEl = document.getElementById('gh-status-all');
        const paidEl = document.getElementById('gh-status-paid');
        const debtEl = document.getElementById('gh-status-debt');
        const refundEl = document.getElementById('gh-status-refund');
        if (allEl) allEl.textContent = counts.all;
        if (paidEl) paidEl.textContent = counts.paid;
        if (debtEl) debtEl.textContent = counts.debt;
        if (refundEl) refundEl.textContent = counts.refund;

        const chips = document.querySelectorAll('#gh-status-filters .gh-status-chip');
        chips.forEach((chip) => {
            const active = (chip.dataset.status || 'all') === state.quickStatus;
            chip.classList.toggle('active', active);
        });
    }

    function ghMatchesQuickSearch(it, keyword) {
        const k = ghNormText(keyword);
        if (!k) return true;

        const guestsText = (it.guests || []).map(g => `${g.full_name || ''} ${g.cccd || ''} ${g.phone || ''}`).join(' ');
        const haystack = [
            it.room_number,
            it.room_type_name,
            it.branch_name,
            it.check_in_at,
            it.check_out_at,
            it.summary_status,
            guestsText,
        ].map(ghNormText).join(' ');

        return haystack.includes(k);
    }

    function ghSortItems(items) {
        const byDate = (it) => {
            if (!it || !it.check_in_at) return 0;
            const d = typeof pmsParseDate === 'function' ? pmsParseDate(it.check_in_at) : new Date(it.check_in_at);
            return Number.isNaN(d.getTime()) ? 0 : d.getTime();
        };
        const byValue = (it) => Number(it.total_price || 0);

        if (state.sort === 'oldest') {
            items.sort((a, b) => byDate(a) - byDate(b));
        } else if (state.sort === 'value_desc') {
            items.sort((a, b) => byValue(b) - byValue(a));
        } else if (state.sort === 'value_asc') {
            items.sort((a, b) => byValue(a) - byValue(b));
        } else {
            items.sort((a, b) => byDate(b) - byDate(a));
        }
    }

    function ghApplyQuickFilters() {
        let items = (state.allItems || []).slice();

        if (state.quickSearch) {
            items = items.filter((it) => ghMatchesQuickSearch(it, state.quickSearch));
        }

        if (state.quickStatus !== 'all') {
            items = items.filter((it) => ghNormSummary(it.summary_status) === state.quickStatus);
        }

        ghSortItems(items);
        state.items = items;
        ghUpdateStatusChips();

        if (!state.loading) {
            ghRender();
        }
    }
    // ── Card HTML ──────────────────────────────────────────────────────────────

    function ghCard(it) {
        const summaryStatus = ghNormSummary(it.summary_status);
        const statusClass = summaryStatus === 'debt' ? 'gh-debt' : summaryStatus === 'refund' ? 'gh-refund' : 'gh-paid';

        let statusLabel, statusIcon;
        if (summaryStatus === 'debt') {
            statusLabel = 'Chưa thanh toán';
            statusIcon = SVG.warn;
        } else if (summaryStatus === 'refund') {
            statusLabel = 'Đã hoàn tiền';
            statusIcon = SVG.check;
        } else {
            statusLabel = 'Đã thanh toán';
            statusIcon = SVG.check;
        }

        const roomNumRaw = String(it.room_number || '?');
        const roomNum = escHtml(roomNumRaw);
        const roomNumArg = encodeURIComponent(roomNumRaw);
        const roomType = escHtml(it.room_type_name || '');
        const branchName = escHtml(it.branch_name || '');
        const nights = ghCalcNights(it.check_in_at, it.check_out_at);

        const stayId = Number(it.stay_id);

        // Build guests list
        const guestsHtml = (it.guests || []).map(g => {
            const name = escHtml(g.full_name || '—');
            const isPrimary = g.is_primary;
            return `<span class="gh-guest-tag ${isPrimary ? 'primary' : ''}">
                ${SVG.user} ${name}${isPrimary ? ' (chính)' : ''}
            </span>`;
        }).join('');

        return `<div class="gh-item ${statusClass}" data-stay-id="${stayId}" onclick="ghOpenStay(${stayId}, '${roomNumArg}')">
            <div class="gh-item-header">
                <div class="gh-room-badge">
                    <div class="gh-room-num">${roomNum}</div>
                    <div class="gh-room-type">${roomType}</div>
                </div>
                <div class="gh-stay-info">
                    ${branchName ? `<span class="gh-branch">${branchName}</span>` : ''}
                    <div class="gh-dates">
                        <div class="gh-date-row">
                            <span class="gh-date-label">Nhận:</span>
                            <span class="gh-date-value">${ghFmtDateTime(it.check_in_at)}</span>
                        </div>
                        <div class="gh-date-row">
                            <span class="gh-date-label">Trả:</span>
                            <span class="gh-date-value">${ghFmtDateTime(it.check_out_at)}</span>
                        </div>
                        <span class="gh-nights">${nights > 0 ? nights + ' đêm' : '—'}</span>
                    </div>
                </div>
                <div class="gh-price-info">
                    <span class="gh-total-price">${ghMoney(it.total_price)}</span>
                    <span class="gh-deposit">Cọc: ${ghMoney(it.deposit)}</span>
                    <span class="gh-status-badge ${statusClass}">
                        ${statusIcon} ${statusLabel}
                    </span>
                </div>
            </div>
            <div class="gh-guests">
                ${guestsHtml}
            </div>
        </div>`;
    }

    function ghOpenStay(stayId, roomNum) {
        const sid = Number(stayId);
        if (!Number.isFinite(sid) || sid <= 0) {
            ghToast('Không xác định được lưu trú.', 'error');
            return;
        }
        let decodedRoomNum = '';
        try {
            decodedRoomNum = roomNum ? decodeURIComponent(roomNum) : '';
        } catch (e) {
            decodedRoomNum = String(roomNum || '');
        }
        if (typeof window.openRoomDetail === 'function') {
            window.openRoomDetail(sid, decodedRoomNum, 'room');
        } else {
            ghToast('Chưa tải xong modal chi tiết. Tải lại trang.', 'error');
        }
    }

    // ── Render: Main ───────────────────────────────────────────────────────────

    function ghRender() {
        const loading = document.getElementById('gh-loading');
        const list = document.getElementById('gh-list');
        if (!list) return;

        if (state.loading) {
            list.style.display = 'none';
            list.innerHTML = '';
            if (loading) {
                loading.style.display = 'flex';
                loading.innerHTML = `<div class="gh-spinner"></div>Đang tải…`;
            }
            return;
        }

        if (loading) loading.style.display = 'none';
        list.style.display = 'block';

        if (!state.items || !state.items.length) {
            const hasPageData = (state.allItems || []).length > 0;
            const msg = hasPageData
                ? 'Không có kết quả phù hợp với tìm kiếm/bộ lọc trong trang hiện tại.'
                : 'Không có lưu trú nào trong bộ lọc này.';
            list.innerHTML = `<div class="gh-empty">${SVG.empty}<p>${msg}</p></div>`;
            ghUpdatePager();
            return;
        }

        list.innerHTML = `<div class="gh-list">${state.items.map(ghCard).join('')}</div>`;

        ghUpdatePager();
    }

    // ── Pager ──────────────────────────────────────────────────────────────────

    function ghUpdatePager() {
        const meta = document.getElementById('gh-meta');
        const prev = document.getElementById('gh-prev');
        const next = document.getElementById('gh-next');

        if (meta) {
            if (!state.total) {
                meta.textContent = '0 lưu trú';
            } else {
                const from = (state.page - 1) * state.pageSize + 1;
                const to = Math.min(state.page * state.pageSize, state.total);
                const quickActive = !!state.quickSearch || state.quickStatus !== 'all';
                if (quickActive) {
                    meta.textContent = `${from}–${to} / ${state.total} · lọc nhanh: ${state.items.length} kết quả`;
                } else {
                    meta.textContent = `${from}–${to} / ${state.total}`;
                }
            }
        }

        if (prev) prev.disabled = state.page <= 1;
        if (next) next.disabled = state.page >= state.pages || state.pages <= 1;
    }

    // ── Date filter helpers ─────────────────────────────────────────────────────

    function ghParseFlatpickrDate(inputId) {
        const el = document.getElementById(inputId);
        if (!el || !el.value) return null;
        const parts = el.value.split('/');
        if (parts.length !== 3) return null;
        return `${parts[2]}-${parts[1]}-${parts[0]}`;
    }

    function ghApplyDateFilter() {
        state.dateFrom = ghParseFlatpickrDate('gh-date-from');
        state.dateTo = ghParseFlatpickrDate('gh-date-to');
        ghLoad(1);
    }

    function ghResetDateFilter() {
        const elFrom = document.getElementById('gh-date-from');
        const elTo = document.getElementById('gh-date-to');

        const defaultFrom = new Date();
        defaultFrom.setDate(defaultFrom.getDate() - 365);

        if (elFrom && elFrom._flatpickr) {
            elFrom._flatpickr.setDate(defaultFrom);
        }
        if (elTo && elTo._flatpickr) {
            elTo._flatpickr.setDate(new Date());
        }

        state.dateFrom = defaultFrom.toISOString().split('T')[0];
        state.dateTo = new Date().toISOString().split('T')[0];
        ghLoad(1);
    }

    // ── Load data ───────────────────────────────────────────────────────────────

    async function ghLoad(page) {
        const list = document.getElementById('gh-list');
        if (!list) return;

        if (_abortCtrl) {
            try { _abortCtrl.abort(); } catch (e) {}
        }
        _abortCtrl = new AbortController();
        const signal = _abortCtrl.signal;
        const parsedPage = Number(page);
        if (Number.isFinite(parsedPage) && parsedPage > 0) {
            state.page = parsedPage;
        } else if (!state.page || state.page < 1) {
            state.page = 1;
        }
        state.page = page || 1;
        state.loading = true;
        ghRender();

        const q = new URLSearchParams();
        q.set('page', String(state.page));
        q.set('page_size', String(state.pageSize));
        if (state.guestId) q.set('guest_id', String(state.guestId));
        if (state.branchId) q.set('branch_id', String(state.branchId));
        if (state.dateFrom) q.set('date_from', state.dateFrom);
        if (state.dateTo) q.set('date_to', state.dateTo);

        try {
            const data = await ghApi(`/api/pms/guests/${state.guestId}/history?${q.toString()}`, signal);

            if (signal.aborted) return;

            state.total = data.total || 0;
            state.pages = data.pages || 0;
            state.allItems = data.items || [];
            state.items = [];

            // Update guest badge
            if (data.guest) {
                ghUpdateGuestBadge(data.guest, data.stats);
            }

            state.loading = false;
            ghApplyQuickFilters();
        } catch (err) {
            if (err.name === 'AbortError') return;
            state.loading = false;
            state.allItems = [];
            state.items = [];
            ghUpdateStatusChips();
            list.innerHTML = `<div class="gh-empty">${escHtml(err.message || 'Không tải được dữ liệu')}</div>`;
            list.style.display = 'block';
            if (document.getElementById('gh-loading')) document.getElementById('gh-loading').style.display = 'none';
            ghToast(err.message || 'Không tải được lịch sử', 'error');
        }
    }

    // ── Bind: Pager ─────────────────────────────────────────────────────────────

    function ghBindPager() {
        const prev = document.getElementById('gh-prev');
        const next = document.getElementById('gh-next');
        if (prev) prev.addEventListener('click', () => { if (state.page > 1) ghLoad(state.page - 1); });
        if (next) next.addEventListener('click', () => { if (state.page < state.pages) ghLoad(state.page + 1); });
    }

    // ── Init ────────────────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        // Get guest_id from URL or page data
        const guestIdEl = document.getElementById('gh-guest-id');
        if (guestIdEl) {
            state.guestId = parseInt(guestIdEl.value, 10);
        }
        // For now, require guest_id to be set
        if (!state.guestId) {
            console.warn('[GuestHistory] No guest_id provided');
            const badge = document.getElementById('gh-guest-badge');
            if (badge) badge.style.display = 'none';
        }

        ghInitDatePickers();
        ghBindPager();
        if (state.guestId) {
            ghLoad(1);
        }
    });

    // Expose globally
    window.ghLoad = ghLoad;
    window.ghApplyDateFilter = ghApplyDateFilter;
    window.ghResetDateFilter = ghResetDateFilter;
    window.ghSetGuestId = function(guestId) {
        state.guestId = parseInt(guestId, 10);
        ghLoad(1);
    };
    window.ghSetBranch = function(bid) {
        state.branchId = (bid !== undefined && bid !== null && bid !== '') ? bid : null;
        ghLoad(1);
    };
    window.ghOpenStay = ghOpenStay;
})();
