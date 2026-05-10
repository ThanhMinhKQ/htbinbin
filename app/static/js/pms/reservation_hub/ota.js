// PMS Reservation Hub - OTA tools and logs
'use strict';

Object.assign(BookingHub, {
    async scanOtaToday() {
        const btn = document.getElementById('bk-ota-scan-btn');
        if (btn?.disabled || this.state.otaScanRunning) return;
        const dateInput = document.getElementById('bk-ota-scan-date');
        const today = this.toDateInput(new Date());
        const scanDate = dateInput?.value || today;
        if (!window.confirm(`Bạn có chắc muốn quét email OTA ngày ${this.formatDate(scanDate)} không?`)) return;
        if (dateInput && !dateInput.value) dateInput.value = scanDate;
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
        if (dateInput && !dateInput.value) dateInput.value = this.toDateInput(new Date());
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
        this.text('bk-ota-total', data.ota_total || 0);
        this.text('bk-ota-confirmed', data.ota_confirmed || 0);
        this.text('bk-ota-cancelled', data.ota_cancelled || data.cancelled_emails || 0);
        this.text('bk-ota-failed', data.failed_emails || 0);
        this.text('bk-ota-agent-total', data.agent_total_count || 0);
        this.text('bk-ota-agent-ai', data.agent_ai_count ?? data.agent_gemini_count ?? 0);
        this.text('bk-ota-agent-rule', data.agent_parse_count || 0);
        const windowText = document.getElementById('bk-ota-agent-window');
        if (windowText) windowText.textContent = `${data.agent_window_days || 1} ngày gần nhất`;
        const latest = document.getElementById('bk-ota-latest');
        if (latest) {
            const when = data.latest_email_at ? this.formatDateTime(data.latest_email_at) : 'Chưa có dữ liệu';
            const status = data.latest_email_status ? ` • ${data.latest_email_status}` : '';
            latest.textContent = `${when}${status}`;
        }
    },

    openOtaLogModal() {
        const modal = document.getElementById('bk-ota-log-modal');
        if (!modal) return;
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('bk-modal-open');
        this.loadOtaLogs();
    },

    closeOtaLogModal() {
        const modal = document.getElementById('bk-ota-log-modal');
        if (!modal) return;
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('bk-modal-open');
    },

    buildOtaLogParams() {
        const params = new URLSearchParams();
        params.set('limit', '50');
        const fields = [
            ['status', 'bk-ota-log-status-filter'],
            ['parser_method', 'bk-ota-log-method-filter'],
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
                <td><span class="bk-ota-log-skeleton wide"></span></td>
                <td><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton short"></span></td>
                <td><span class="bk-ota-log-skeleton short"></span></td>
                <td><span class="bk-ota-log-skeleton wide"></span><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton short"></span></td>
                <td><span class="bk-ota-log-skeleton wide"></span><span class="bk-ota-log-skeleton medium"></span></td>
                <td><span class="bk-ota-log-skeleton short"></span></td>
            </tr>
        `).join('');
    },

    async loadOtaLogs() {
        const rows = document.getElementById('bk-ota-log-rows');
        const meta = document.getElementById('bk-ota-log-meta');
        if (!rows) return;
        const requestId = (this.state.otaLogRequestId || 0) + 1;
        this.state.otaLogRequestId = requestId;
        this.renderOtaLogSkeleton();
        if (meta) meta.textContent = 'Đang tải log booking/hủy OTA...';
        try {
            const params = this.buildOtaLogParams();
            const res = await pmsApi(`/api/pms/reservations/ota/logs?${params.toString()}`);
            if (requestId !== this.state.otaLogRequestId) return;
            this.state.otaLogs = Array.isArray(res.items) ? res.items : [];
            this.renderOtaLogTable(this.state.otaLogs);
            if (meta) meta.textContent = `Hiển thị ${this.state.otaLogs.length} log liên quan đặt/hủy phòng theo thời gian mới nhất.`;
        } catch (err) {
            if (requestId !== this.state.otaLogRequestId) return;
            rows.innerHTML = `<tr><td colspan="8" class="bk-ota-log-error">${this.escape(err.message || 'Không tải được log OTA')}</td></tr>`;
            if (meta) meta.textContent = 'Không tải được log OTA.';
        }
    },

    renderOtaLogTable(logs) {
        const rows = document.getElementById('bk-ota-log-rows');
        if (!rows) return;
        if (!logs.length) {
            rows.innerHTML = '<tr><td colspan="8" class="bk-ota-log-empty">Không có log đặt/hủy phòng phù hợp bộ lọc.</td></tr>';
            return;
        }
        rows.innerHTML = logs.map((log) => {
            const status = String(log.status || '').toUpperCase();
            const failed = status === 'FAILED';
            const method = String(log.parser_method || '').toLowerCase();
            const methodLabel = method === 'gemini' ? 'Gemini' : (method === 'rule' ? 'Rule' : '—');
            const actionType = String(log.action_type || 'NEW').toUpperCase();
            const actionLabel = actionType === 'CANCEL' ? 'Hủy phòng' : (actionType === 'UPDATE' ? 'Cập nhật' : 'Đặt phòng');
            const source = log.booking_source || 'OTA';
            const branch = log.branch_name || 'Chưa xác định';
            const bookingBits = [
                log.booking_id ? `#${log.booking_id}` : '',
                log.external_id ? `OTA ${log.external_id}` : '',
                log.guest_name || '',
            ].filter(Boolean).join(' • ') || '—';
            const stay = [log.check_in ? this.formatDate(log.check_in) : '', log.check_out ? this.formatDate(log.check_out) : ''].filter(Boolean).join(' → ');
            const subject = log.email_subject || 'Email OTA';
            const detail = failed && log.error_message ? log.error_message : (stay || log.email_sender || '');
            return `
                <tr class="${failed ? 'failed' : ''}">
                    <td><strong>${this.escape(this.formatDateTime(log.received_at) || '—')}</strong></td>
                    <td>${this.escape(branch)}</td>
                    <td><span class="bk-source-pill">${this.escape(source)}</span><small>${this.escape(actionLabel)}</small></td>
                    <td><span class="bk-method-pill ${this.escape(method || 'unknown')}">${this.escape(methodLabel)}</span></td>
                    <td><div class="bk-ota-log-booking">${this.escape(bookingBits)}${stay ? `<small>${this.escape(stay)}</small>` : ''}</div></td>
                    <td><span class="bk-status ${failed ? 'CANCELLED' : 'CONFIRMED'}">${this.escape(status || '—')}</span></td>
                    <td><div class="bk-ota-log-subject"><strong>${this.escape(subject)}</strong>${detail ? `<small>${this.escape(detail)}</small>` : ''}</div></td>
                    <td class="bk-ota-log-actions">${failed ? `<button class="bk-mini-btn" type="button" onclick="BookingHub.retryOtaLog(${Number(log.id) || 0})">Retry</button>` : ''}</td>
                </tr>
            `;
        }).join('');
    },

    onOtaLogSearchKey(event) {
        if (event.key === 'Enter') this.loadOtaLogs();
    },

    resetOtaLogFilters() {
        ['bk-ota-log-status-filter', 'bk-ota-log-method-filter', 'bk-ota-log-action-filter', 'bk-ota-log-from-date', 'bk-ota-log-to-date', 'bk-ota-log-branch-filter', 'bk-ota-log-search'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        this.loadOtaLogs();
    },

    async retryOtaLog(id) {
        try {
            await pmsApi(`/api/pms/reservations/ota/retry/${id}`, { method: 'POST' });
            pmsToast('Đã xử lý lại email OTA', true);
            await this.refreshAfterMutation({ availability: true });
            if (document.getElementById('bk-ota-log-modal')?.classList.contains('show')) {
                await this.loadOtaLogs();
            }
        } catch (err) {
            pmsToast(err.message || 'Không retry được email OTA', false);
        }
    }
});
