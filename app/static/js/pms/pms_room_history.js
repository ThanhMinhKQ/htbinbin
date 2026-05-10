'use strict';

/**
 * PMS Room History — Full-page component
 * 2 view modes: grid (flat) | type (by room type)
 * Card structure matches pms_dashboard.js / pmsRoomCard() — 100% identical
 * Date range filter via Flatpickr
 * AbortController for fast navigation
 */

(function () {
    // ── Helpers ────────────────────────────────────────────────────────────────

    function escHtml(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    }

    function rhFmtDate(iso) {
        if (!iso) return '—';
        const d = typeof pmsParseDate === 'function' ? pmsParseDate(iso) : new Date(iso);
        if (isNaN(d)) return '—';
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const yyyy = d.getFullYear();
        return `${dd}/${mm}/${yyyy}`;
    }

    function rhFmtTime(iso) {
        if (!iso) return '—';
        const d = typeof pmsParseDate === 'function' ? pmsParseDate(iso) : new Date(iso);
        if (isNaN(d)) return '—';
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    function rhFmtDateTime(iso) {
        if (!iso) return '—';
        return `${rhFmtDate(iso)} ${rhFmtTime(iso)}`;
    }

    /** API trả `debt` | `refund` | `paid` — chuẩn hoá cho UI */
    function rhNormSummary(raw) {
        const s = String(raw || '').toLowerCase();
        if (s === 'debt') return 'debt';
        if (s === 'refund') return 'refund';
        return 'paid';
    }

    function rhStatusColor(status) {
        if (status === 'debt') return '#dc2626';
        if (status === 'refund') return '#16a34a';
        return '#16a34a';
    }

    function rhStatusLabel(status) {
        if (status === 'debt') return 'Còn nợ';
        if (status === 'refund') return 'Đã hoàn tiền';
        return 'Đã thanh toán';
    }

    function rhMoney(n) {
        const v = Number(n) || 0;
        try {
            return new Intl.NumberFormat('vi-VN').format(Math.round(v)) + ' ₫';
        } catch (e) {
            return String(Math.round(v)) + ' ₫';
        }
    }

    /** Tính thời gian lưu trú (đêm hoặc giờ/phút) */
    function rhCalcDuration(ciIso, coIso, pricingMode) {
        if (!ciIso || !coIso) return '—';
        const ci = typeof pmsParseDate === 'function' ? pmsParseDate(ciIso) : new Date(ciIso);
        const co = typeof pmsParseDate === 'function' ? pmsParseDate(coIso) : new Date(coIso);
        if (isNaN(ci) || isNaN(co)) return '—';
        const ms = co - ci;
        if (ms <= 0) return '0 phút';
        
        if (pricingMode === 'HOURLY' || pricingMode === 'HOURLY_CHARGE') {
            const totalMins = Math.floor(ms / 60000);
            const hours = Math.floor(totalMins / 60);
            const mins = totalMins % 60;
            if (hours > 0) {
                return mins > 0 ? `${hours} giờ ${mins} phút` : `${hours} giờ`;
            }
            return `${mins} phút`;
        } else {
            return Math.ceil(ms / 86400000) + ' đêm';
        }
    }

    // ── SVG Icons ──────────────────────────────────────────────────────────────

    const SVG = {
        user: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        check: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        warn: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        clock: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
        bed: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>',
        empty: '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>',
    };

    // ── State ───────────────────────────────────────────────────────────────────

    const state = {
        page: 1,
        pageSize: 24,
        filter: 'all',
        viewMode: 'grid',   // 'grid' | 'list'
        branchId: null,
        dateFrom: null,     // ISO string
        dateTo: null,       // ISO string
        dateField: 'check_in', // 'check_in' | 'check_out' | 'created'
        search: null,       // guest name or CCCD
        total: 0,
        pages: 0,
        loading: false,
        items: [],
        totals: { debt: 0, refund: 0, paid: 0, total: 0 },
    };

    let _abortCtrl = null; // AbortController for cancelling stale requests

    // ── Flatpickr Init ──────────────────────────────────────────────────────────

    function rhInitDatePickers() {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const defaultFrom = new Date();
        defaultFrom.setDate(defaultFrom.getDate() - 7);

        // LUÔN set state TRƯỚC (sync) — flatpickr load async
        state.dateFrom = defaultFrom.toISOString().split('T')[0];
        state.dateTo = tomorrow.toISOString().split('T')[0];

        const fpConfig = {
            dateFormat: 'd/m/Y',
            locale: typeof flatpickr !== 'undefined' && flatpickr.l10ns && flatpickr.l10ns.vn ? 'vn' : 'default',
            disableMobile: true,
        };

        const elFrom = document.getElementById('rh-date-from');
        const elTo = document.getElementById('rh-date-to');

        if (elFrom && typeof flatpickr === 'function') {
            flatpickr(elFrom, { ...fpConfig, defaultDate: defaultFrom });
        }
        if (elTo && typeof flatpickr === 'function') {
            flatpickr(elTo, { ...fpConfig, defaultDate: tomorrow });
        }
    }

    // ── API ─────────────────────────────────────────────────────────────────────

    async function rhApi(url, signal) {
        const opts = { method: 'GET', credentials: 'same-origin' };
        if (signal) opts.signal = signal;

        if (typeof pmsApi === 'function') {
            // pmsApi doesn't support signal, but we can still use it
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

    function rhToast(msg, type) {
        if (typeof pmsToast === 'function') { pmsToast(msg, type || 'info'); return; }
        alert(msg);
    }

    // ── Stats ───────────────────────────────────────────────────────────────────

    function rhUpdateStats() {
        const de = document.getElementById('rh-stat-debt');
        const re = document.getElementById('rh-stat-refund');
        const pe = document.getElementById('rh-stat-paid');
        const te = document.getElementById('rh-stat-total');
        if (de) de.textContent = state.totals.debt || 0;
        if (re) re.textContent = state.totals.refund || 0;
        if (pe) pe.textContent = state.totals.paid || 0;
        if (te) te.textContent = state.totals.total || 0;
    }

    // ── Status helpers ──────────────────────────────────────────────────────────

    function rhFooterSub(it) {
        const bal = Number(it.balance_remaining) || 0;
        if (bal > 0) return `Còn nợ: ${rhMoney(bal)}`;
        if (bal < 0) return `Khách dư: ${rhMoney(Math.abs(bal))}`;
        return '';
    }

    // ── Card HTML ───────────────────────────────────────────────────────────────

    function rhCard(it) {
        const summaryStatus = rhNormSummary(it.summary_status);
        const isPaid = summaryStatus === 'paid';
        const isRefund = summaryStatus === 'refund';
        const isDebt = summaryStatus === 'debt';

        const statusClass = isDebt ? 'rc-debt' : isRefund ? 'rc-refund' : 'rc-paid';

        // Status label + icon
        let statusLabel, statusIcon;
        if (isDebt) {
            statusLabel = 'Còn nợ';
            statusIcon = SVG.warn;
        } else if (isRefund) {
            statusLabel = 'Đã hoàn tiền';
            statusIcon = SVG.clock;
        } else {
            statusLabel = 'Đã thanh toán';
            statusIcon = SVG.check;
        }

        const subLine = rhFooterSub(it);

        const gc = it.guest_count != null ? it.guest_count : 0;
        const maxG = it.max_guests != null ? it.max_guests : 2;
        const roomNum = escHtml(it.room_number || '?');
        const roomType = escHtml(it.room_type_name || '');
        const guestName = escHtml(it.guest_name || '—');
        const durationText = rhCalcDuration(it.check_in_at, it.check_out_at, it.pricing_mode);

        const stayId = Number(it.stay_id);
        const roomRaw = String(it.room_number || '?');

        // Guest icon — use PMS_SVG if available
        const userSvg = (typeof PMS_SVG !== 'undefined' && PMS_SVG.user) ? PMS_SVG.user : SVG.user;

        return `<div class="rc-wrap" data-stay-id="${stayId}" data-room="${escHtml(roomRaw)}" data-summary="${summaryStatus}" role="button" tabindex="0" aria-label="Chi tiết lưu trú phòng ${roomNum}">
  <div class="rc ${statusClass}">
    <div class="rc-top">
      <!-- Left badge: room number + type + guests -->
      <div class="rc-badge">
        <div class="rb-num">${roomNum}</div>
        <div class="rb-type">${roomType}</div>
        <div class="rb-cap">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          ${gc}/${maxG}
        </div>
      </div>

      <!-- Middle info: guest + stay dates -->
      <div class="rc-info">
        <div class="ri-guest">
          <div class="ri-guest-icon">${userSvg}</div>
          <div class="ri-guest-name">${guestName}</div>
        </div>
        <div class="ri-stay-vertical">
          <div class="ri-v-row active">
            <span class="ri-label">Nhận</span>
            <span class="ri-value">${rhFmtDateTime(it.check_in_at)}</span>
          </div>
          <div class="ri-v-row">
            <span class="ri-label">Trả</span>
            <span class="ri-value">${rhFmtDateTime(it.check_out_at)}</span>
          </div>
          <div class="ri-v-row">
            <span class="ri-label">Thời gian</span>
            <span class="ri-value">${durationText}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer: payment status -->
    <div class="rc-status-footer">
      <span class="rc-status-label">${statusIcon} ${statusLabel}</span>
      <span class="rc-status-amount">${subLine}</span>
    </div>
  </div>
</div>`;
    }

    function rhSkeletonGrid() {
        const cards = Array.from({ length: 8 }, () => `<div class="rh-skeleton-card" aria-hidden="true">
          <div class="rh-sk-head">
            <div class="rh-sk-badge"></div>
            <div class="rh-sk-lines">
              <div class="rh-sk-line w80"></div>
              <div class="rh-sk-line w55"></div>
              <div class="rh-sk-line w42"></div>
            </div>
          </div>
          <div class="rh-sk-grid-mini">
            <div class="rh-sk-pill"></div>
            <div class="rh-sk-pill"></div>
            <div class="rh-sk-pill"></div>
            <div class="rh-sk-pill"></div>
          </div>
        </div>`).join('');
        return `<div class="rh-skeleton-grid">${cards}</div>`;
    }

    function rhSkeletonList() {
        const rows = Array.from({ length: 7 }, () => `<div class="rh-skeleton-row" aria-hidden="true">
          <div class="rh-sk-line w55"></div>
          <div class="rh-sk-line w80"></div>
          <div class="rh-sk-line"></div>
          <div class="rh-sk-line w55"></div>
          <div class="rh-sk-line w42"></div>
        </div>`).join('');
        return `<div class="rh-skeleton-list">${rows}</div>`;
    }

    // ── Open detail ─────────────────────────────────────────────────────────────

    function rhOpenDetail(stayId, roomNum) {
        const sid = Number(stayId);
        const room = roomNum != null ? String(roomNum) : '';

        if (!Number.isFinite(sid) || sid <= 0) {
            rhToast('Không xác định được lưu trú.', 'error');
            return;
        }

        if (typeof window.openRoomDetail === 'function') {
            window.openRoomDetail(sid, room, 'payment');
        } else {
            rhToast('Chưa tải xong modal chi tiết. Tải lại trang.', 'error');
        }
    }

    /** Open room detail AND auto-open payment popup (for "Thu nợ" button) */
    function rhOpenDetailAndPay(stayId) {
        const sid = Number(stayId);
        if (!Number.isFinite(sid) || sid <= 0) {
            rhToast('Không xác định được lưu trú.', 'error');
            return;
        }
        // Set flag so rdLoadPayment auto-opens payment popup after fetching data
        if (typeof window.rdSetAutoPay === 'function') {
            window.rdSetAutoPay(true);
        }
        rhOpenDetail(sid, null);
    }

    /** Delegation listener on #rh-floors */
    function rhBindCardDelegation() {
        const root = document.getElementById('rh-floors');
        if (!root || root.dataset.rhDelegBound === '1') return;
        root.dataset.rhDelegBound = '1';

        root.addEventListener('click', (e) => {
            const wrap = e.target.closest('.rc-wrap[data-stay-id]');
            if (!wrap || !root.contains(wrap)) return;
            rhOpenDetail(wrap.getAttribute('data-stay-id'), wrap.getAttribute('data-room') || '');
        });

        root.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            const wrap = e.target.closest('.rc-wrap[data-stay-id]');
            if (!wrap || !root.contains(wrap) || e.target !== wrap) return;
            e.preventDefault();
            rhOpenDetail(wrap.getAttribute('data-stay-id'), wrap.getAttribute('data-room') || '');
        });
    }

    // ── Render: Grid (flat) ────────────────────────────────────────────────────

    function rhRenderGrid(items) {
        const grid = document.getElementById('rh-floors');
        if (!grid) return;

        if (!items || !items.length) {
            grid.innerHTML = `<div class="rh-empty">${SVG.empty}<p>Không có lưu trú nào trong bộ lọc này.</p></div>`;
            return;
        }
        grid.innerHTML = `<div class="rh-grid">${items.map(rhCard).join('')}</div>`;
    }

    // ── Render: List (table) View ───────────────────────────────────────────────

    function rhRenderList(items) {
        const grid = document.getElementById('rh-floors');
        if (!grid) return;

        if (!items || !items.length) {
            grid.innerHTML = `<div class="rh-empty">${SVG.empty}<p>Không có lưu trú nào trong bộ lọc này.</p></div>`;
            return;
        }

        const rows = items.map(it => {
            const st = rhNormSummary(it.summary_status);
            const bal = Number(it.balance_remaining) || 0;
            const deposit = Number(it.deposit) || 0;
            const totalPrice = Number(it.total_price) || 0;
            const durationText = rhCalcDuration(it.check_in_at, it.check_out_at, it.pricing_mode);
            const stayId = Number(it.stay_id);
            const roomNum = escHtml(it.room_number || '?');
            const floor = it.room_floor ? `Tầng ${it.room_floor}` : '—';
            const guestName = escHtml(it.guest_name || '—');
            const gender = escHtml(it.guest_gender || '');
            
            const badgeClass = st === 'debt' ? 'rh-badge-debt' : st === 'refund' ? 'rh-badge-refund' : 'rh-badge-paid';
            const balLabel = st === 'debt' ? 'Phải thu' : st === 'refund' ? 'Phải hoàn' : 'Đã tất toán';

            return `<tr data-stay-id="${stayId}" onclick="window.rhOpenDetail(${stayId},'${escHtml(it.room_number || '')}')">
              <td>
                <div class="rh-cell-room">
                  <div class="rh-room-badge">
                    <span class="rh-room-num">${roomNum}</span>
                    <span class="rh-room-floor">${floor}</span>
                  </div>
                  <div style="font-size:11px; font-weight:700; color:var(--rh-text-muted);">${escHtml(it.room_type_name || '—')}</div>
                </div>
              </td>
              <td>
                <div class="rh-cell-guest">
                  <div class="rh-guest-main">
                    <span style="color:var(--rh-accent);">${SVG.user}</span>
                    ${guestName}
                  </div>
                  <div class="rh-guest-sub">${gender}</div>
                </div>
              </td>
              <td>
                <div class="rh-stay-info">
                  <div class="rh-stay-dates">
                    <span style="color:var(--rh-paid);">${rhFmtDateTime(it.check_in_at)}</span>
                    <span style="color:var(--rh-text-subtle);">${rhFmtDateTime(it.check_out_at)}</span>
                  </div>
                  <div class="rh-stay-sep"></div>
                  <div class="rh-duration-tag">${durationText}</div>
                </div>
              </td>
              <td>
                <div class="rh-money-wrap">
                  <div class="rh-m-val">${rhMoney(totalPrice)}</div>
                  <div class="rh-m-label">Tổng hóa đơn</div>
                </div>
              </td>
              <td>
                <div class="rh-money-wrap">
                  <div class="rh-m-val" style="color:var(--rh-text-muted);">${rhMoney(deposit)}</div>
                  <div class="rh-m-label">Đã đặt cọc</div>
                </div>
              </td>
              <td>
                <div class="rh-money-wrap">
                  <div class="rh-m-val ${st}">${bal != 0 ? rhMoney(Math.abs(bal)) : '0 ₫'}</div>
                  <div class="rh-m-label">${balLabel}</div>
                </div>
              </td>
              <td>
                <span class="rh-badge-pill ${badgeClass}">${rhStatusLabel(st)}</span>
              </td>
              <td>
                <div class="rh-actions">
                  <button class="rh-btn-action" title="Xem chi tiết">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                  </button>
                </div>
              </td>
            </tr>`;
        }).join('');

        grid.innerHTML = `<div class="rh-list-wrap">
          <table class="rh-list-table">
            <thead>
              <tr>
                <th>Phòng</th>
                <th>Khách hàng</th>
                <th>Thời gian lưu trú</th>
                <th style="text-align:right;">Tổng cộng</th>
                <th style="text-align:right;">Đặt cọc</th>
                <th style="text-align:right;">Thanh toán</th>
                <th>Trạng thái</th>
                <th style="text-align:right;"></th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    }

    // ── Render: Main ───────────────────────────────────────────────────────────

    function rhRender() {
        const loading = document.getElementById('rh-loading');
        const floors = document.getElementById('rh-floors');
        if (!floors) return;

        if (state.loading) {
            floors.style.display = 'block';
            floors.innerHTML = state.viewMode === 'list' ? rhSkeletonList() : rhSkeletonGrid();
            if (loading) {
                loading.style.display = 'none';
                loading.innerHTML = '';
            }
            return;
        }

        if (loading) loading.style.display = 'none';
        floors.style.display = 'block';

        if (state.viewMode === 'list') {
            rhRenderList(state.items);
        } else {
            rhRenderGrid(state.items);
        }

        rhUpdatePager();
        rhUpdateStats();
    }

    // ── Pager ──────────────────────────────────────────────────────────────────

    function rhUpdatePager() {
        const meta = document.getElementById('rh-meta');
        const prev = document.getElementById('rh-prev');
        const next = document.getElementById('rh-next');

        if (meta) {
            if (!state.total) {
                meta.textContent = '0 lưu trú';
            } else {
                const from = (state.page - 1) * state.pageSize + 1;
                const to = Math.min(state.page * state.pageSize, state.total);
                meta.textContent = `${from}–${to} / ${state.total}`;
            }
        }

        if (prev) prev.disabled = state.page <= 1;
        if (next) next.disabled = state.page >= state.pages || state.pages <= 1;
    }

    // ── Date filter helpers ─────────────────────────────────────────────────────

    function rhParseFlatpickrDate(inputId) {
        const el = document.getElementById(inputId);
        if (!el || !el.value) return null;
        // Flatpickr format: dd/mm/yyyy
        const parts = el.value.split('/');
        if (parts.length !== 3) return null;
        return `${parts[2]}-${parts[1]}-${parts[0]}`;
    }

    function rhApplyDateFilter() {
        state.dateFrom = rhParseFlatpickrDate('rh-date-from');
        state.dateTo = rhParseFlatpickrDate('rh-date-to');
        const dateFieldEl = document.getElementById('rh-date-field');
        state.dateField = dateFieldEl ? dateFieldEl.value : 'check_in';
        rhLoad(1);
    }

    function rhApplySearch() {
        const searchEl = document.getElementById('rh-search');
        state.search = searchEl ? searchEl.value.trim() : '';
        rhLoad(1);
    }

    function rhResetDateFilter() {
        const elFrom = document.getElementById('rh-date-from');
        const elTo = document.getElementById('rh-date-to');
        const elDateField = document.getElementById('rh-date-field');
        const elSearch = document.getElementById('rh-search');

        // Reset to default 7 days
        const defaultFrom = new Date();
        defaultFrom.setDate(defaultFrom.getDate() - 7);

        if (elFrom && elFrom._flatpickr) {
            elFrom._flatpickr.setDate(defaultFrom);
        }
        if (elTo && elTo._flatpickr) {
            elTo._flatpickr.setDate(new Date());
        }
        if (elDateField) {
            elDateField.value = 'check_in';
        }
        if (elSearch) {
            elSearch.value = '';
        }

        state.dateFrom = defaultFrom.toISOString().split('T')[0];
        state.dateTo = new Date().toISOString().split('T')[0];
        state.dateField = 'check_in';
        state.search = '';
        rhLoad(1);
    }

    // ── Load data ───────────────────────────────────────────────────────────────

    async function rhLoad(page, silent = false) {
        const floors = document.getElementById('rh-floors');
        if (!floors) return;

        // Cancel previous request
        if (_abortCtrl) {
            try { _abortCtrl.abort(); } catch (e) {}
        }
        _abortCtrl = new AbortController();
        const signal = _abortCtrl.signal;

        state.page = page || 1;
        if (!silent) {
            state.loading = true;
            rhRender();
        }

        const q = new URLSearchParams();
        q.set('summary_filter', state.filter);
        q.set('page', String(state.page));
        q.set('page_size', String(state.pageSize));
        if (state.branchId) q.set('branch_id', String(state.branchId));
        if (state.dateFrom) q.set('date_from', state.dateFrom);
        if (state.dateTo) q.set('date_to', state.dateTo);
        if (state.dateField) q.set('date_field', state.dateField);
        if (state.search && state.search.length >= 2) q.set('search', state.search);

        const apiUrl = `/api/pms/stays/history?${q.toString()}`;

        try {
            const data = await rhApi(apiUrl, signal);

            // Check if this request was superseded
            if (signal.aborted) return;

            state.total = data.total || 0;
            state.pages = data.pages || 0;
            state.items = data.items || [];
            state.totals = {
                debt:   data.stats ? (data.stats.debt   || 0) : 0,
                refund: data.stats ? (data.stats.refund || 0) : 0,
                paid:   data.stats ? (data.stats.paid   || 0) : 0,
                total:  data.stats ? (data.stats.total  || 0) : (data.total || 0),
            };
            state.loading = false;
            rhRender();
        } catch (err) {
            if (err.name === 'AbortError') return; // Cancelled — ignore
            state.loading = false;
            state.items = [];
            floors.innerHTML = `<div class="rh-empty">${escHtml(err.message || 'Không tải được dữ liệu')}</div>`;
            floors.style.display = 'block';
            if (document.getElementById('rh-loading')) document.getElementById('rh-loading').style.display = 'none';
            rhToast(err.message || 'Không tải được lịch sử', 'error');
        }
    }

    // ── Bind: Filters + View ───────────────────────────────────────────────────

    function rhBindFilters() {
        document.querySelectorAll('[data-rh-filter]').forEach(btn => {
            btn.addEventListener('click', () => {
                const v = btn.getAttribute('data-rh-filter') || 'all';
                if (state.filter === v) return;
                state.filter = v;
                document.querySelectorAll('[data-rh-filter]').forEach(b => {
                    b.classList.toggle('is-on', b === btn);
                });
                rhLoad(1);
            });
        });

        document.querySelectorAll('[data-rh-view]').forEach(btn => {
            btn.addEventListener('click', () => {
                const v = btn.getAttribute('data-rh-view') || 'grid';
                if (state.viewMode === v) return;
                state.viewMode = v;
                document.querySelectorAll('[data-rh-view]').forEach(b => {
                    b.classList.toggle('active', b === btn);
                });
                rhRender();
            });
        });

        const prev = document.getElementById('rh-prev');
        const next = document.getElementById('rh-next');
        if (prev) prev.addEventListener('click', () => { if (state.page > 1) rhLoad(state.page - 1); });
        if (next) next.addEventListener('click', () => { if (state.page < state.pages) rhLoad(state.page + 1); });
    }

    // ── Branch change ───────────────────────────────────────────────────────────

    function rhSetBranch(bid) {
        state.branchId = (bid !== undefined && bid !== null && bid !== '') ? bid : null;
        rhLoad(1);
    }

    // ── Init ────────────────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        const boot = window.PMS_ROOM_HISTORY_BOOT || {};
        const branchSelect = document.getElementById('rh-branch-select');
        const initialBranch = (branchSelect && branchSelect.value) || boot.branchId || null;
        state.branchId = initialBranch ? String(initialBranch) : null;
        if (branchSelect && state.branchId) branchSelect.value = state.branchId;
        rhInitDatePickers();
        rhBindCardDelegation();
        rhBindFilters();
        rhLoad(1);
    });

    // Expose globally
    window.rhLoad            = rhLoad;
    window.rhState           = state;
    window.rhSetBranch       = rhSetBranch;
    window.rhOpenDetail      = rhOpenDetail;
    window.rhOpenDetailAndPay = rhOpenDetailAndPay;
    window.rhApplyDateFilter = rhApplyDateFilter;
    window.rhResetDateFilter = rhResetDateFilter;
    window.rhApplySearch     = rhApplySearch;
})();
