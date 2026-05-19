// PMS Reservation Hub - OTA tools and logs
'use strict';

Object.assign(BookingHub, {
    async scanOtaToday() {
        const btn = document.getElementById('bk-ota-scan-btn');
        if (btn?.disabled || this.state.otaScanRunning) return;
        const dateInput = document.getElementById('bk-ota-scan-date');
        const today = this.toDateInput(new Date());
        const scanDate = (dateInput?._fp_get_iso?.() || dateInput?.value || today);
        if (!window.confirm(`Bạn có chắc muốn quét email OTA ngày ${this.formatDate(scanDate)} không?`)) return;
        const params = new URLSearchParams();
        params.set('scan_date', scanDate);
        this.state.otaScanRunning = true;
        this.setButtonBusy(btn, true, 'Đang quét...');
        try {
            const res = await pmsApi(`/api/pms/reservations/ota/scan-today?${params.toString()}`, { method: 'POST' });
            if (res?.status === 'already_running') {
                pmsToast(res.message || `Đang quét email OTA ngày ${this.formatDate(scanDate)} trong nền`, true);
            } else {
                pmsToast(`Đã bắt đầu quét email OTA ngày ${this.formatDate(scanDate)} trong nền`, true);
            }
            this.loadOtaPanel();
        } catch (err) {
            pmsToast(err.message || 'Không quét được email OTA', false);
        } finally {
            this.state.otaScanRunning = false;
            this.setButtonBusy(btn, false, 'Quét OTA');
        }
    },

    async loadOtaPanel() {
        const dateInput = document.getElementById('bk-ota-scan-date');
        if (dateInput && !dateInput._flatpickr && !dateInput.value) dateInput.value = this.toDateInput(new Date());
        try {
            const params = new URLSearchParams();
            params.set('days', '1');
            const statusRes = await pmsApi(`/api/pms/reservations/ota/status?${params.toString()}`);
            this.renderOtaStatus(statusRes || {});
            if (statusRes?.database_offline) {
                const latest = document.getElementById('bk-ota-latest');
                if (latest) latest.textContent = statusRes.message || 'Không kết nối được cơ sở dữ liệu';
                return;
            }
            if (document.getElementById('bk-ota-log-modal')?.classList.contains('show')) {
                await this.loadOtaLogs();
            }
        } catch (err) {
            const latest = document.getElementById('bk-ota-latest');
            if (latest) latest.textContent = err.message || 'Không tải được trạng thái OTA';
        }
    },

    renderOtaStatus(data) {
        this.state.otaStatusData = data;
        this.text('bk-ota-total', data.ota_total || 0);
        this.text('bk-ota-confirmed', data.ota_confirmed || 0);
        this.text('bk-ota-cancelled', data.ota_cancelled || data.cancelled_emails || 0);
        this.text('bk-ota-failed', data.failed_emails || 0);
        this.text('bk-ota-agent-total', data.agent_total_count || 0);
        this.text('bk-ota-agent-ai', data.agent_ai_count ?? data.agent_gemini_count ?? 0);
        this.text('bk-ota-agent-rule', data.agent_rule_count ?? data.agent_parse_count ?? 0);
        const windowText = document.getElementById('bk-ota-agent-window');
        if (windowText) windowText.textContent = `${data.agent_window_days || 1} ngày gần nhất`;
        const latest = document.getElementById('bk-ota-latest');
        if (latest) {
            const when = data.latest_email_at ? this.formatDateTime(data.latest_email_at) : 'Chưa có dữ liệu';
            const status = data.latest_email_status ? ` • ${data.latest_email_status}` : '';
            latest.textContent = `${when}${status}`;
        }
    },

    renderOtaLogDashboardSkeleton() {
        ['bk-ota-dash-total', 'bk-ota-dash-confirmed', 'bk-ota-dash-updated', 'bk-ota-dash-cancelled', 'bk-ota-dash-failed'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '<span class="bk-ota-log-skeleton short" style="display:inline-block;width:32px;height:18px;"></span>';
        });
        const branchEl = document.getElementById('bk-ota-dash-branch');
        if (branchEl) branchEl.innerHTML = '<span class="bk-ota-log-skeleton medium" style="display:inline-block;width:80px;height:10px;"></span>';
    },

    updateOtaLogDashboard(res) {
        const c = res?.counts || {};
        this.text('bk-ota-dash-total', res?.total ?? 0);
        this.text('bk-ota-dash-confirmed', c.NEW ?? 0);
        this.text('bk-ota-dash-updated', c.UPDATE ?? 0);
        this.text('bk-ota-dash-cancelled', c.CANCEL ?? 0);
        this.text('bk-ota-dash-failed', c.FAILED ?? 0);
        this.text('bk-ota-dash-branch', res?.branch_name || 'Tất cả chi nhánh');
    },

    startOtaRealtimePolling() {
        if (this.state.otaRealtimeTimer) return;
        const tick = () => this.checkOtaRealtime().catch(() => {});
        tick();
        this.state.otaRealtimeTimer = setInterval(tick, 10000);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) tick();
        });
    },

    buildOtaRealtimeStatusUrl() {
        const params = new URLSearchParams();
        params.set('days', '1');
        params.set('fresh', '1');
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        return `/api/pms/reservations/ota/status?${params.toString()}`;
    },

    otaRealtimeScopeKey() {
        return String(this.state.branchId || 'all');
    },

    otaRealtimeMessage(payload, action) {
        const source = payload?.booking_source || 'OTA';
        const guest = payload?.guest_name || 'khách';
        const code = payload?.external_id ? ` #${payload.external_id}` : '';
        const branch = payload?.branch_name && payload.branch_name !== 'Chưa xác định' ? ` • ${payload.branch_name}` : '';
        const dates = payload?.check_in ? ` • ${payload.check_in}` : '';
        if (action === 'cancel') return `❌ HỦY PHÒNG ${source}${code}: ${guest}${branch}${dates}`;
        return `✅ ĐẶT PHÒNG MỚI ${source}${code}: ${guest}${branch}${dates}`;
    },

    updateOtaRealtimeBaseline(data) {
        this.state.otaRealtimeBaseline = {
            scope: this.otaRealtimeScopeKey(),
            latestSuccessLogId: Number(data?.latest_success_log_id || 0) || null,
            latestCancelLogId: Number(data?.latest_cancel_log_id || 0) || null,
        };
    },

    async checkOtaRealtime() {
        if (document.hidden || this.state.otaRealtimeChecking) return;
        this.state.otaRealtimeChecking = true;
        try {
            const data = await pmsApi(this.buildOtaRealtimeStatusUrl());
            if (data?.database_offline) return;
            this.renderOtaStatus(data || {});
            const baseline = this.state.otaRealtimeBaseline;
            const currentScope = this.otaRealtimeScopeKey();
            if (!baseline || baseline.scope !== currentScope) {
                this.updateOtaRealtimeBaseline(data);
                return;
            }

            const latestSuccessLogId = Number(data?.latest_success_log_id || 0) || null;
            const latestCancelLogId = Number(data?.latest_cancel_log_id || 0) || null;
            const hasNewBooking = latestSuccessLogId && (!baseline.latestSuccessLogId || latestSuccessLogId > baseline.latestSuccessLogId);
            const hasCancel = latestCancelLogId && (!baseline.latestCancelLogId || latestCancelLogId > baseline.latestCancelLogId);
            if (!hasNewBooking && !hasCancel) return;

            this.updateOtaRealtimeBaseline(data);
            if (hasCancel) pmsToast(this.otaRealtimeMessage(data.latest_cancel_booking, 'cancel'), true);
            if (hasNewBooking) pmsToast(this.otaRealtimeMessage(data.latest_success_booking, 'new'), true);
            await Promise.all([this.loadStats(), this.loadReservations()]);
            if (document.getElementById('bk-ota-log-modal')?.classList.contains('show')) {
                await this.loadOtaLogs();
            }
            this.loadAvailabilityBar();
            this.renderOtaStatus(data || {});
        } catch (err) {
            // Polling is best-effort; manual refresh remains available.
        } finally {
            this.state.otaRealtimeChecking = false;
        }
    },

    openOtaLogModal() {
        const modal = document.getElementById('bk-ota-log-modal');
        if (!modal) return;
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('bk-modal-open');

        // Default range: từ đầu tháng → hôm nay
        const fromInput = document.getElementById('bk-ota-log-from-date');
        const toInput = document.getElementById('bk-ota-log-to-date');
        if (fromInput && !fromInput.value) {
            const now = new Date();
            const yyyy = now.getFullYear();
            const mm = String(now.getMonth() + 1).padStart(2, '0');
            const dd = String(now.getDate()).padStart(2, '0');
            fromInput.value = `${yyyy}-${mm}-01`;
            if (toInput && !toInput.value) toInput.value = `${yyyy}-${mm}-${dd}`;
        }

        this.loadOtaLogs();
    },

    closeOtaLogModal() {
        const modal = document.getElementById('bk-ota-log-modal');
        if (!modal) return;
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('bk-modal-open');
    },

    buildOtaLogParams(page = 1) {
        const params = new URLSearchParams();
        params.set('limit', '20');
        params.set('page', String(page));
        const fields = [
            ['status', 'bk-ota-log-status-filter'],
            ['booking_source', 'bk-ota-log-source-filter'],
            ['action_type', 'bk-ota-log-action-filter'],
            ['from_date', 'bk-ota-log-from-date'],
            ['to_date', 'bk-ota-log-to-date'],
            ['search', 'bk-ota-log-search'],
        ];
        fields.forEach(([key, id]) => {
            const value = (document.getElementById(id)?.value || '').trim();
            if (value) params.set(key, value);
        });
        const branchFilter = document.getElementById('bk-ota-log-branch-filter');
        const branchId = branchFilter ? (branchFilter.value || '').trim() : (this.state.branchId || '');
        if (branchId) params.set('branch_id', branchId);
        return params;
    },

    renderOtaLogSkeleton(count = 8) {
        const rows = document.getElementById('bk-ota-log-rows');
        if (!rows) return;
        rows.innerHTML = Array.from({ length: count }).map(() => `
            <tr class="bk-ota-log-skeleton-row" aria-hidden="true">
                <td><span class="bk-ota-log-skeleton wide"></span><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton wide"></span><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton wide"></span><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton short"></span></td>
                <td><span class="bk-ota-log-skeleton wide"></span><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton short"></span></td>
            </tr>
        `).join('');
    },

    async loadOtaLogs(page = 1) {
        const rows = document.getElementById('bk-ota-log-rows');
        const meta = document.getElementById('bk-ota-log-meta');
        if (!rows) return;
        this.state.otaLogPage = page;
        const requestId = (this.state.otaLogRequestId || 0) + 1;
        this.state.otaLogRequestId = requestId;
        this.renderOtaLogSkeleton();
        this.renderOtaLogDashboardSkeleton();
        if (meta) meta.textContent = 'Đang tải log booking/hủy OTA...';
        try {
            const params = this.buildOtaLogParams(page);
            const res = await pmsApi(`/api/pms/reservations/ota/logs?${params.toString()}`);
            if (requestId !== this.state.otaLogRequestId) return;
            this.state.otaLogs = Array.isArray(res.items) ? res.items : [];
            this.state.otaLogTotal = res.total || 0;
            this.state.otaLogTotalPages = res.total_pages || 1;
            this.renderOtaLogTable(this.state.otaLogs);
            this.renderOtaLogPagination();
            if (meta) meta.textContent = `Hiển thị ${this.state.otaLogs.length} / ${this.state.otaLogTotal} log • Trang ${page}/${this.state.otaLogTotalPages}`;
            this.updateOtaLogDashboard(res);
        } catch (err) {
            if (requestId !== this.state.otaLogRequestId) return;
            rows.innerHTML = `<tr><td colspan="6" class="bk-ota-log-error">${this.escape(err.message || 'Không tải được log OTA')}</td></tr>`;
            if (meta) meta.textContent = 'Không tải được log OTA.';
        }
    },

    renderOtaLogPagination() {
        const container = document.getElementById('bk-ota-log-pagination');
        if (!container) return;
        const total = this.state.otaLogTotalPages || 1;
        const current = this.state.otaLogPage || 1;
        if (total <= 1) { container.innerHTML = ''; return; }
        let html = '<div class="bk-pagination">';
        html += `<button class="bk-page-btn" ${current <= 1 ? 'disabled' : ''} onclick="BookingHub.loadOtaLogs(${current - 1})">‹</button>`;
        const start = Math.max(1, current - 2);
        const end = Math.min(total, current + 2);
        if (start > 1) html += `<button class="bk-page-btn" onclick="BookingHub.loadOtaLogs(1)">1</button>`;
        if (start > 2) html += '<span class="bk-page-dots">…</span>';
        for (let i = start; i <= end; i++) {
            html += `<button class="bk-page-btn ${i === current ? 'active' : ''}" onclick="BookingHub.loadOtaLogs(${i})">${i}</button>`;
        }
        if (end < total - 1) html += '<span class="bk-page-dots">…</span>';
        if (end < total) html += `<button class="bk-page-btn" onclick="BookingHub.loadOtaLogs(${total})">${total}</button>`;
        html += `<button class="bk-page-btn" ${current >= total ? 'disabled' : ''} onclick="BookingHub.loadOtaLogs(${current + 1})">›</button>`;
        html += '</div>';
        container.innerHTML = html;
    },

    renderOtaLogTable(logs) {
        const rows = document.getElementById('bk-ota-log-rows');
        if (!rows) return;
        if (!logs.length) {
            rows.innerHTML = '<tr><td colspan="6" class="bk-ota-log-empty">Không có log đặt/hủy phòng phù hợp bộ lọc.</td></tr>';
            return;
        }
        rows.innerHTML = logs.map((log) => {
            const status = String(log.status || '').toUpperCase();
            const failed = status === 'FAILED';
            const actionType = String(log.action_type || 'NEW').toUpperCase();
            const actionLabel = actionType === 'CANCEL' ? 'Hủy phòng' : (actionType === 'UPDATE' ? 'Cập nhật' : 'Đặt phòng');
            const source = log.booking_source || 'OTA';
            const branch = log.branch_name || 'Chưa xác định';
            const bookingCode = log.external_id || '';
            const guestName = log.guest_name || '';
            const roomTypeName = log.room_type_name || '';
            const checkInTime = log.check_in_time || '';
            const checkOutTime = log.check_out_time || '';
            const parseStayMinutes = (v) => {
                const m = String(v || '').match(/^(\d{1,2}):(\d{2})/);
                if (!m) return null;
                const h = Number(m[1]), min = Number(m[2]);
                return (h <= 23 && min <= 59) ? h * 60 + min : null;
            };
            const ciMin = parseStayMinutes(checkInTime);
            const coMin = parseStayMinutes(checkOutTime);
            const crossesMidnight = Boolean(log.ota_cross_midnight_booking || (log.ota_same_day_booking && ciMin !== null && coMin !== null && coMin <= ciMin));
            const checkOutDate = log.ota_actual_check_out && !crossesMidnight ? log.ota_actual_check_out : log.check_out;
            const actualStayDays = this.dateDiff(log.check_in, checkOutDate);
            const isHourly = Boolean(log.ota_same_day_booking && !crossesMidnight && actualStayDays <= 0);
            const nights = Math.max(1, this.dateDiff(log.check_in, log.check_out) || 1);
            const stayLengthText = isHourly ? 'Theo giờ' : `${nights} đêm`;
            const checkInText = this.formatStayDateTime(log.check_in, checkInTime);
            const checkOutText = this.formatStayDateTime(checkOutDate, checkOutTime);
            const guests = Number(log.num_guests || 1);
            const subject = log.email_subject || 'Email OTA';
            const detail = failed && log.error_message ? log.error_message : (log.email_sender || '');
            const statusLabel = failed ? 'Thất bại' : 'Thành công';
            return `
                <tr class="${failed ? 'failed' : ''}">
                    <td><div style="display:flex;flex-direction:column;gap:3px;"><strong>${this.escape(this.formatDateTime(log.received_at) || '—')}</strong><small>${this.escape(branch)}</small><span class="bk-source-pill" style="align-self:flex-start;">${this.escape(source)}</span></div></td>
                    <td>${failed ? '' : `<div style="display:flex;flex-direction:column;gap:2px;">${bookingCode ? `<small style="opacity:.7;">${this.escape(bookingCode)}</small>` : ''}${guestName ? `<strong>${this.escape(guestName)}</strong>` : ''}${roomTypeName ? `<small style="opacity:.7;">${this.escape(roomTypeName)}</small>` : ''}</div>`}</td>
                    <td>${failed ? '' : `
                        <div class="bk-stay-cell">
                            <strong class="bk-stay-datetime">${this.escape(checkInText || '—')}</strong>
                            <span class="bk-stay-checkout">→ ${this.escape(checkOutText || '—')}</span>
                            <span class="bk-stay-nights"><i class="bi bi-moon-stars"></i> ${this.escape(stayLengthText)} • ${guests} khách</span>
                        </div>`}</td>
                    <td><div style="display:flex;flex-direction:column;gap:3px;align-items:flex-start;"><span class="bk-status ${failed ? 'CANCELLED' : 'CONFIRMED'}">${statusLabel}</span><small>${this.escape(actionLabel)}</small></div></td>
                    <td><div class="bk-ota-log-subject"><strong>${this.escape(subject)}</strong>${detail ? `<small>${this.escape(detail)}</small>` : ''}</div></td>
                    <td class="bk-ota-log-actions">${failed ? `<button class="bk-mini-btn" type="button" onclick="BookingHub.retryOtaLog(${Number(log.id) || 0})">Thử lại</button>` : ''}</td>
                </tr>
            `;
        }).join('');
    },

    onOtaLogSearchKey(event) {
        if (event.key === 'Enter') this.loadOtaLogs();
    },

    resetOtaLogFilters() {
        ['bk-ota-log-branch-filter', 'bk-ota-log-status-filter', 'bk-ota-log-source-filter', 'bk-ota-log-action-filter', 'bk-ota-log-from-date', 'bk-ota-log-to-date', 'bk-ota-log-search'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        this.loadOtaLogs(1);
    },

    async retryOtaLog(id) {
        const btn = document.querySelector(`button[onclick*="retryOtaLog(${id})"]`);
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Đang xử lý...';
        }
        try {
            const res = await pmsApi(`/api/pms/reservations/ota/retry/${id}`, { method: 'POST' });
            if (res?.status === 'processing') {
                pmsToast(res.message || 'Đang xử lý lại email OTA trong nền', true);
                this.pollOtaRetryStatus(id);
                return;
            }
            pmsToast('Đã xử lý lại email OTA', true);
            this.refreshAfterMutation({ availability: true });
            if (document.getElementById('bk-ota-log-modal')?.classList.contains('show')) {
                this.loadOtaLogs();
            }
        } catch (err) {
            pmsToast(err.message || 'Không retry được email OTA', false);
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Thử lại';
            }
        }
    },

    pollOtaRetryStatus(id) {
        const poll = async (attempt = 0) => {
            try {
                const res = await pmsApi(`/api/pms/reservations/ota/retry/${id}/status`);
                if (res?.status === 'processing' && attempt < 60) {
                    window.setTimeout(() => poll(attempt + 1), 2000);
                    return;
                }
                if (res?.status === 'SUCCESS') {
                    pmsToast('Đã xử lý lại email OTA thành công', true);
                    this.refreshAfterMutation({ availability: true });
                } else if (res?.status) {
                    pmsToast(res.error_message || 'Retry email OTA chưa thành công', false);
                }
                if (document.getElementById('bk-ota-log-modal')?.classList.contains('show')) {
                    this.loadOtaLogs();
                }
            } catch (err) {
                pmsToast(err.message || 'Không kiểm tra được trạng thái retry OTA', false);
                if (document.getElementById('bk-ota-log-modal')?.classList.contains('show')) {
                    this.loadOtaLogs();
                }
            }
        };
        window.setTimeout(() => poll(), 2000);
    }
});
