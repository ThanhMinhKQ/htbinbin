// PMS Reservation Hub - reservation list and actions
'use strict';

Object.assign(BookingHub, {
    async loadReservations() {
        this.setLoading(true);
        const today = this.toDateInput(new Date());
        const week = new Date();
        week.setDate(week.getDate() + 7);

        const params = new URLSearchParams({ page_size: 80 });
        const statusFilter = this.value('bk-status-filter');
        const search = this.value('bk-search');
        const stayFrom = this.value('bk-stay-from');
        const stayTo = this.value('bk-stay-to');
        if (search) params.set('search', search);

        if (stayFrom || stayTo) {
            if (stayFrom) params.set('check_in_from', stayFrom);
            if (stayTo) params.set('check_in_to', stayTo);
            if (statusFilter) params.set('status', statusFilter);
            if (this.state.activeTab === 'pending') params.set('status', 'PENDING');
            if (this.state.activeTab === 'ota') params.set('source', 'OTA');
        } else if (this.state.activeTab === 'today') {
            params.set('check_in_from', today);
            params.set('check_in_to', today);
            if (statusFilter) params.set('status', statusFilter);
        } else if (this.state.activeTab === 'upcoming') {
            params.set('check_in_from', today);
            params.set('check_in_to', this.toDateInput(week));
            if (statusFilter) params.set('status', statusFilter);
        } else if (this.state.activeTab === 'pending') {
            params.set('status', 'PENDING');
        } else if (this.state.activeTab === 'ota') {
            params.set('source', 'OTA');
            if (statusFilter) params.set('status', statusFilter);
        } else if (statusFilter) {
            params.set('status', statusFilter);
        }
        if (this.state.branchId) {
            params.set('branch_id', this.state.branchId);
        }

        try {
            const data = this.apiData(await pmsApi(`/api/pms/reservations?${params.toString()}`), {});
            let items = Array.isArray(data.items) ? data.items : [];
            this.state.reservations = items;
            this.renderReservations();
        } catch (err) {
            pmsToast(err.message || 'Không tải được danh sách đặt phòng', false);
        } finally {
            this.setLoading(false);
        }
    },

    renderReservations() {
        const body = document.getElementById('bk-reservation-rows');
        const empty = document.getElementById('bk-empty');
        const wrap = document.getElementById('bk-table-wrap');
        if (!body || !empty || !wrap) return;

        this.renderReservationInsights();

        if (!this.state.reservations.length) {
            body.innerHTML = '';
            empty.style.display = 'block';
            wrap.style.display = 'none';
            return;
        }

        empty.style.display = 'none';
        wrap.style.display = 'block';
        body.innerHTML = this.state.reservations.map((booking) => this.renderReservationRow(booking)).join('');
    },

    renderReservationInsights() {
        const items = Array.isArray(this.state.reservations) ? this.state.reservations : [];
        const actionable = items.filter((booking) => ['PENDING', 'CONFIRMED'].includes(booking.reservation_status || 'PENDING')).length;
        const unassigned = items.filter((booking) => ['PENDING', 'CONFIRMED'].includes(booking.reservation_status || 'PENDING') && !booking.assigned_room_id).length;
        const revenue = items.reduce((sum, booking) => sum + Number(booking.total_price || 0), 0);
        const tabLabel = {
            today: 'booking đến hôm nay',
            upcoming: 'booking 7 ngày tới',
            pending: 'booking chờ xác nhận',
            ota: 'booking OTA',
            all: 'booking trong hệ thống',
        }[this.state.activeTab] || 'booking';
        this.text('bk-visible-count', items.length);
        this.text('bk-action-count', actionable);
        this.text('bk-unassigned-count', unassigned);
        this.text('bk-visible-revenue', pmsMoney(revenue));
    },

    renderReservationRow(booking) {
        const status = booking.reservation_status || 'PENDING';
        const rawData = booking.raw_data || {};
        const isTransferShadow = Boolean(rawData.transfer_shadow);
        const isSoftShadow = ['CHECKED_IN', 'CHECKED_OUT'].includes(status) && Boolean(booking.stay_id);
        const overCapacityPending = Boolean(rawData.over_capacity_pending);
        const canConfirm = status === 'PENDING' && !booking.assigned_room_id && !isTransferShadow;
        const canMarkPending = status === 'CONFIRMED' && !booking.assigned_room_id && !isTransferShadow;
        const canAssign = status === 'CONFIRMED' && !isTransferShadow;
        const canCancel = ['PENDING', 'CONFIRMED'].includes(status) && !isTransferShadow;
        const canCheckin = status === 'CONFIRMED' && booking.assigned_room_id && this.isCheckinDateReached(booking.check_in) && !isTransferShadow;
        let canNoShow = false;
        const canEdit = status === 'CONFIRMED' && !isTransferShadow;
        const canTransfer = status === 'PENDING' && !booking.assigned_room_id && !booking.stay_id && !isTransferShadow;
        const canRestore = ['CANCELLED', 'NO_SHOW'].includes(status) && !isTransferShadow;
        const sourceLabels = {
            DIRECT: 'Trực tiếp', OTA: 'OTA', SALES: 'Sales',
            COMPANY: 'Công ty', ZALO: 'Zalo', PHONE: 'Phone'
        };
        const otaChannel = String(booking.booking_source || '').trim();
        const source = booking.booking_type === 'OTA' && otaChannel
            ? this.escape(otaChannel)
            : this.escape(sourceLabels[booking.booking_type] || booking.booking_type || 'Trực tiếp');
        const bookingCode = this.escape(booking.external_id || `#${booking.id}`);
        const guestName = this.escape(booking.guest_name || 'Khách lẻ');
        const phone = booking.guest_phone ? this.escape(booking.guest_phone) : 'Chưa có SĐT';
        const room = booking.assigned_room_number ? `Phòng ${this.escape(booking.assigned_room_number)}` : 'Chưa gán phòng';
        const roomTypeRaw = booking.room_type || 'Chưa rõ loại phòng';
        const roomTypeParts = roomTypeRaw.split(/\s*[-–—]\s*/);
        const roomTypeClean = (roomTypeParts.length >= 2 ? roomTypeParts[1] : roomTypeParts[0]).split(/\s*(?:Hệ thống|Hướng dẫn|Payment)/i)[0].trim();
        let roomType = this.escape(roomTypeClean.substring(0, 80) || roomTypeParts[0].substring(0, 80));
        const originalRoomType = booking.original_room_type_name ? this.escape(booking.original_room_type_name) : '';
        const roomTypeChanged = originalRoomType && originalRoomType.toLowerCase() !== roomType.toLowerCase();
        let originalRoomTypeHtml = '';
        if (roomTypeChanged && status === 'PENDING') {
            originalRoomTypeHtml = `<span class="bk-room-type-original" title="Hạng phòng hệ thống: ${roomType}">${roomType}</span>`;
            roomType = originalRoomType;
        } else if (roomTypeChanged) {
            originalRoomTypeHtml = `<span class="bk-room-type-original" title="Hạng phòng gốc từ OTA">${originalRoomType}</span>`;
        }
        const roomSummary = booking.group_summary ? `<div class="bk-room-extra">${this.escape(booking.group_summary)}</div>` : '';
        const groupLabel = booking.group_code
            ? `<span class="bk-source-pill group">Nhóm ${this.escape(booking.group_index || 1)}/${this.escape(booking.group_total || 1)}</span>`
            : '';
        const transferLabel = isTransferShadow
            ? `<span class="bk-source-pill transfer-shadow">Đã chuyển sang ${this.escape(rawData.transferred_to_branch_name || 'chi nhánh khác')}</span>`
            : '';
        const softShadowLabel = isSoftShadow
            ? `<span class="bk-source-pill soft-shadow" title="Bản mềm để thống kê — đã nhận phòng"><i class="bi bi-archive"></i> Bản mềm</span>`
            : '';
        const overCapacityLabel = overCapacityPending
            ? '<span class="bk-source-pill over-capacity">Chờ đủ tồn</span>'
            : '';
        const checkInTime = rawData.check_in_time || rawData.estimated_arrival || booking.estimated_arrival;
        const checkOutTime = rawData.check_out_time || rawData.estimated_departure || booking.estimated_departure;
        canNoShow = this.isPastCheckoutTime(booking.check_out, checkOutTime)
            && !['CHECKED_IN', 'CHECKED_OUT', 'CANCELLED', 'NO_SHOW'].includes(status)
            && !isTransferShadow;
        const parseStayMinutes = (value) => {
            const match = String(value || '').match(/^(\d{1,2}):(\d{2})/);
            if (!match) return null;
            const hours = Number(match[1]);
            const minutes = Number(match[2]);
            if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours > 23 || minutes > 59) return null;
            return hours * 60 + minutes;
        };
        const checkInMinutes = parseStayMinutes(checkInTime);
        const checkOutMinutes = parseStayMinutes(checkOutTime);
        const crossesMidnight = Boolean(
            rawData.ota_cross_midnight_booking
            || (rawData.ota_same_day_booking && checkInMinutes !== null && checkOutMinutes !== null && checkOutMinutes <= checkInMinutes)
        );
        const checkOutDate = rawData.ota_actual_check_out && !crossesMidnight ? rawData.ota_actual_check_out : booking.check_out;
        const actualStayDays = this.dateDiff(booking.check_in, checkOutDate);
        const isHourlyStay = Boolean(rawData.ota_same_day_booking && !crossesMidnight && actualStayDays <= 0);
        const nights = Math.max(1, this.dateDiff(booking.check_in, booking.check_out) || 1);
        const stayLengthText = isHourlyStay ? 'Theo giờ' : `${nights} đêm`;
        const checkInText = this.formatStayDateTime(booking.check_in, checkInTime);
        const checkOutText = this.formatStayDateTime(checkOutDate, checkOutTime);
        const guests = Number(booking.num_guests || 1);
        const requestText = (booking.special_requests || booking.internal_notes || booking.cancel_reason || '').trim();
        const trace = booking.checked_in_trace || null;
        const traceHtml = trace ? (() => {
            const traceName = this.escape(trace.guest_name || 'Khách lẻ');
            const tracePhone = trace.guest_phone ? ` · ${this.escape(trace.guest_phone)}` : '';
            const traceLink = trace.crm_guest_id
                ? `<a class="bk-crm-link" href="/pms/crm/guest/${trace.crm_guest_id}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="Mở hồ sơ CRM"><i class="bi bi-person-vcard"></i> ${traceName}</a>`
                : `<span class="bk-crm-link disabled"><i class="bi bi-person"></i> ${traceName}</span>`;
            return `<div class="bk-checkin-trace"><span class="bk-trace-label">Đã nhận bởi:</span> ${traceLink}${tracePhone}</div>`;
        })() : '';
        const isUnassigned = canAssign && !booking.assigned_room_id;
        const rowClass = [
            status === 'PENDING' ? 'needs-confirm' : '',
            canCheckin ? 'ready-checkin' : '',
            isUnassigned ? 'needs-room' : '',
            isTransferShadow ? 'transfer-shadow' : '',
            isSoftShadow ? 'soft-shadow' : '',
        ].filter(Boolean).join(' ');
        const nextAction = isTransferShadow ? `Đã chuyển sang ${rawData.transferred_to_branch_name || 'chi nhánh khác'}`
            : overCapacityPending ? 'Chờ đủ tồn để xác nhận'
                : canCheckin ? 'Sẵn sàng nhận phòng'
                    : canConfirm ? 'Cần xác nhận'
                        : isUnassigned ? 'Cần gán phòng'
                            : status === 'CONFIRMED' ? 'Đã sẵn sàng'
                                : this.statusLabel(status);
        const paymentStatus = booking.is_prepaid ? 'Đã thanh toán' : 'Chưa thanh toán';
        const paymentMethod = booking.payment_method ? ` • ${this.escape(booking.payment_method)}` : '';
        const depositAmount = Number(booking.deposit_amount || 0);
        const paymentLine = depositAmount > 0
            ? `<span class="bk-deposit-label"><i class="bi bi-wallet2"></i> Đã cọc ${pmsMoney(depositAmount)}</span>`
            : `<span class="bk-payment-state ${booking.is_prepaid ? 'paid' : 'unpaid'}"><i class="bi bi-credit-card"></i> ${paymentStatus}${paymentMethod}</span>`;
        const actions = [
            canCheckin ? this.actionButton('checkin', 'Nhận phòng', `BookingHub.checkin(${booking.id})`, 'primary', `data-checkin-id="${booking.id}"`) : '',
            canConfirm ? this.actionButton('confirm', 'Xác nhận', `BookingHub.confirm(${booking.id})`, 'primary') : '',
            canMarkPending ? this.actionButton('restore', 'Chưa xác nhận', `BookingHub.setReservationStatus(${booking.id}, 'PENDING')`) : '',
            canTransfer ? this.actionButton('transfer', 'Chuyển chi nhánh', `BookingHub.openTransfer(${booking.id})`) : '',
            canAssign ? this.actionButton('assign', 'Gán phòng', `BookingHub.openAssign(${booking.id})`) : '',
            canEdit ? this.actionButton('edit', 'Sửa đặt phòng', `BookingHub.openEdit(${booking.id})`) : '',
            canCancel ? this.actionButton('cancel', 'Hủy đặt phòng', `BookingHub.cancel(${booking.id})`, 'danger') : '',
            canNoShow ? this.actionButton('noshow', 'Đánh dấu No-show', `BookingHub.noShow(${booking.id})`) : '',
            canRestore ? this.actionButton('restore', 'Khôi phục', `BookingHub.restoreReservation(${booking.id})`, 'primary') : '',
        ].filter(Boolean).join('');

        return `
            <tr class="${rowClass}" data-booking-id="${booking.id}" onclick="BookingHub.openDetail(${booking.id})" tabindex="0" role="button" aria-label="Mở chi tiết đặt phòng ${bookingCode}">
                <td>
                    <div class="bk-order-cell">
                        <strong class="bk-order-code">${bookingCode}</strong>
                        <span class="bk-source-pill">${source}</span>
                        ${groupLabel}
                        ${transferLabel}
                        ${softShadowLabel}
                        ${overCapacityLabel}
                        <span class="bk-order-date"><i class="bi bi-clock-history"></i> ${this.formatDateTime(booking.created_at || booking.check_in) || this.formatDate(booking.created_at || booking.check_in)}</span>
                    </div>
                </td>
                <td>
                    <div class="bk-guest-cell compact">
                        <div class="bk-guest-info">
                            <strong>${guestName}</strong>
                            <span><i class="bi bi-telephone"></i> ${phone}</span>
                            <span class="bk-badge-tier"><i class="bi bi-shield-check"></i> ${this.escape(booking.guest_tier || 'BASIC')}</span>
                        </div>
                    </div>
                </td>
                <td>
                    <div class="bk-branch-room-cell">
                        <span class="bk-room-badge ${isUnassigned ? 'unassigned' : 'assigned'}">
                            <i class="bi bi-door-open"></i> ${this.escape(room)}
                        </span>
                        <span class="bk-room-type-label">${roomType}</span>
                        ${originalRoomTypeHtml}
                        ${roomSummary}
                    </div>
                </td>
                <td>
                    <div class="bk-stay-cell">
                        <strong class="bk-stay-datetime">${this.escape(checkInText)}</strong>
                        <span class="bk-stay-checkout">→ ${this.escape(checkOutText)}</span>
                        <span class="bk-stay-nights"><i class="bi bi-moon-stars"></i> ${stayLengthText} • ${guests} khách</span>
                    </div>
                </td>
                <td>
                    <div class="bk-status-stack">
                        <span class="bk-status ${status}">${this.statusLabel(status)}</span>
                        <span class="bk-next-step">${this.escape(nextAction)}</span>
                    </div>
                </td>
                <td>
                    <div class="bk-price-line stack">
                        <strong class="bk-money">${pmsMoney(booking.total_price || 0)}</strong>
                        ${paymentLine}
                    </div>
                </td>
                <td>
                    <div class="bk-request-cell ${requestText || traceHtml ? '' : 'empty'}">
                        ${requestText ? `<div class="bk-request-text"><i class="bi bi-chat-dots"></i> ${this.escape(requestText)}</div>` : ''}
                        ${traceHtml}
                        ${!requestText && !traceHtml ? '<span class="bk-no-request">Không có yêu cầu</span>' : ''}
                    </div>
                </td>
                <td><div class="bk-row-actions" onclick="event.stopPropagation()">${actions || '<span class="bk-no-actions">Không còn thao tác</span>'}</div></td>
            </tr>
        `;
    },

    applyActiveTabUI() {
        const tab = this.state.activeTab;
        document.querySelectorAll('.bk-tab').forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === tab));
        const tablePanel = document.getElementById('bk-table-panel');
        const otaPanel = document.getElementById('bk-ota-panel');
        if (tablePanel) tablePanel.style.display = 'block';
        if (otaPanel) otaPanel.classList.toggle('show', tab === 'ota');
    },

    selectTab(tab) {
        this.state.activeTab = tab;
        this.applyActiveTabUI();
        this.loadReservations();
        if (tab === 'ota') this.loadOtaPanel();
    },

    onSearchKey(event) {
        if (event.key === 'Enter') this.loadReservations();
    },

    resetReservationFilters() {
        const search = document.getElementById('bk-search');
        const status = document.getElementById('bk-status-filter');
        const stayFrom = document.getElementById('bk-stay-from');
        const stayTo = document.getElementById('bk-stay-to');
        if (search) search.value = '';
        if (status) status.value = '';
        if (stayFrom) stayFrom.value = '';
        if (stayTo) stayTo.value = '';
        this.loadReservations();
    },

    actionIcon(name) {
        const icons = {
            checkin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 12.5 11.2 15 16 9"/><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5z"/></svg>',
            confirm: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
            assign: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10V7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v3"/><path d="M5 20v-6h14v6"/><path d="M3 14h18"/></svg>',
            edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="m14 7 3 3"/></svg>',
            unassign: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20v-6h14v6"/><path d="M3 14h18"/><path d="m6 6 12 12"/></svg>',
            transfer: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h11l-3-3"/><path d="m18 7-3 3"/><path d="M17 17H6l3 3"/><path d="m6 17 3-3"/></svg>',
            cancel: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
            noshow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 4.3 2.7 18a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/><path d="M12 8v5"/><path d="M12 17h.01"/></svg>',
            restore: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v6h6"/></svg>',
        };
        return icons[name] || icons.edit;
    },

    actionButton(icon, label, onclick, tone = '', attrs = '') {
        const safeLabel = this.escape(label);
        const safeOnclick = this.escape(onclick);
        return `<button class="bk-icon-btn ${tone}" type="button" ${attrs} onclick="event.stopPropagation(); ${safeOnclick}" title="${safeLabel}" aria-label="${safeLabel}">${this.actionIcon(icon)}<span>${safeLabel}</span></button>`;
    },

    isOtaBooking(booking) {
        const bookingType = String(booking?.booking_type || '').toUpperCase();
        const bookingSource = String(booking?.booking_source || '').toUpperCase();
        return bookingType === 'OTA' || (bookingSource && !['DIRECT', 'PHONE', 'WALK-IN', 'WALK_IN'].includes(bookingSource));
    },

    async fetchReservationDetail(id) {
        return this.apiData(await pmsApi(`/api/pms/reservations/${id}`), {});
    },

    async confirm(id) {
        const booking = this.state.reservations.find((item) => Number(item.id) === Number(id));
        const detail = booking || await this.fetchReservationDetail(id);
        if (this.isOtaBooking(detail)) {
            await this.openOtaConfirm(detail);
            return;
        }
        await this.confirmWithRoomType(id);
    },

    async confirmWithRoomType(id, roomTypeId = null) {
        const options = { method: 'POST' };
        if (roomTypeId) {
            options.headers = { 'Content-Type': 'application/json' };
            options.body = JSON.stringify({ room_type_id: roomTypeId });
        }
        try {
            await pmsApi(`/api/pms/reservations/${id}/confirm`, options);
            pmsToast('Đã xác nhận đặt phòng', true);
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không xác nhận được đặt phòng', false);
            throw err;
        }
    },

    async openOtaConfirm(booking) {
        const detail = booking?.check_in && booking?.check_out ? booking : await this.fetchReservationDetail(booking.id);
        this.state.otaConfirmBookingId = detail.id;
        this.state.otaConfirmBooking = detail;
        this.state.otaConfirmRoomTypeId = null;
        const title = document.getElementById('bk-ota-confirm-title');
        const meta = document.getElementById('bk-ota-confirm-meta');
        const list = document.getElementById('bk-ota-confirm-list');
        const loading = document.getElementById('bk-ota-confirm-loading');
        const submitBtn = document.getElementById('bk-ota-confirm-submit');
        if (submitBtn) submitBtn.disabled = true;
        const nights = Math.max(1, this.dateDiff(detail.check_in, detail.check_out) || 1);
        if (title) title.textContent = detail.guest_name || 'Booking OTA';
        if (meta) {
            meta.innerHTML = `
                <span>Mã OTA: <strong>${this.escape(detail.external_id || `#${detail.id}`)}</strong></span>
                <span>Loại OTA: <strong>${this.escape(detail.room_type || 'Chưa rõ')}</strong></span>
                <span>${this.escape(this.formatStayDateTime(detail.check_in, detail.estimated_arrival))} → ${this.escape(this.formatStayDateTime(detail.check_out))} · ${nights} đêm</span>
            `;
        }
        if (list) list.innerHTML = '';
        if (loading) loading.style.display = 'flex';
        this.showModal('bk-ota-confirm-modal');
        try {
            const params = new URLSearchParams({ check_in: detail.check_in, check_out: detail.check_out });
            if (detail.branch_id || this.state.branchId) params.set('branch_id', detail.branch_id || this.state.branchId);
            const data = this.apiData(await pmsApi(`/api/pms/inventory/availability?${params.toString()}`), []);
            if (!list) return;
            if (!Array.isArray(data) || !data.length) {
                list.innerHTML = '<div class="bk-avail-empty">Không có dữ liệu tồn phòng cho khoảng ngày này</div>';
                return;
            }
            list.innerHTML = data.map((rt) => this.renderOtaConfirmRoomTypeCard(rt, nights)).join('');
        } catch (err) {
            if (list) list.innerHTML = `<div class="bk-avail-empty">${this.escape(err.message || 'Không tải được tồn phòng')}</div>`;
        } finally {
            if (loading) loading.style.display = 'none';
        }
    },

    renderOtaConfirmRoomTypeCard(rt, nights) {
        const available = Number(rt.available_rooms ?? rt.available ?? 0);
        const roomTypeId = Number(rt.room_type_id || rt.id || 0);
        const selected = this.state.otaConfirmRoomTypeId === roomTypeId;
        const soldOut = rt.stop_sell || available <= 0 || !roomTypeId;
        const price = Number(rt.price_per_night || rt.base_price || 0);
        const total = price * Math.max(1, Number(nights || 1));
        return `
            <button class="bk-ota-confirm-card ${soldOut ? 'disabled' : ''} ${selected ? 'selected' : ''}" type="button" data-room-type-id="${roomTypeId}" ${soldOut ? 'disabled' : `onclick="BookingHub.selectOtaConfirmRoomType(${roomTypeId})"`}>
                <div>
                    <strong>${this.escape(rt.room_type || rt.name || 'Loại phòng')}</strong>
                    <span>${this.escape(rt.available_label || `Còn ${available} phòng`)}</span>
                </div>
                <div class="bk-ota-confirm-price">
                    <strong>${pmsMoney(total)}</strong>
                    <span>${pmsMoney(price)} / đêm</span>
                </div>
            </button>
        `;
    },

    closeOtaConfirm() {
        this.hideModal('bk-ota-confirm-modal');
        this.state.otaConfirmBookingId = null;
        this.state.otaConfirmBooking = null;
        this.state.otaConfirmRoomTypeId = null;
    },

    selectOtaConfirmRoomType(roomTypeId) {
        this.state.otaConfirmRoomTypeId = Number(roomTypeId) || null;
        document.querySelectorAll('#bk-ota-confirm-list .bk-ota-confirm-card').forEach((card) => {
            card.classList.toggle('selected', Number(card.dataset.roomTypeId) === this.state.otaConfirmRoomTypeId);
        });
        const submitBtn = document.getElementById('bk-ota-confirm-submit');
        if (submitBtn) submitBtn.disabled = !this.state.otaConfirmRoomTypeId;
    },

    async confirmOtaWithRoomType() {
        const id = this.state.otaConfirmBookingId;
        const roomTypeId = this.state.otaConfirmRoomTypeId;
        if (!id) return;
        if (!roomTypeId) {
            pmsToast('Chọn loại phòng trước khi xác nhận', false);
            return;
        }
        try {
            await this.confirmWithRoomType(id, roomTypeId);
            this.closeOtaConfirm();
            if (this.state.detailBookingId === id) await this.openDetail(id);
        } catch (err) {
            // Toast already shown by confirmWithRoomType.
        }
    },

    async setReservationStatus(id, status) {
        const targetStatus = (status || '').toUpperCase();
        if (targetStatus === 'PENDING') {
            const ok = window.confirm('Chuyển booking này về chưa xác nhận?');
            if (!ok) return;
        }
        try {
            await pmsApi(`/api/pms/reservations/${id}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reservation_status: targetStatus }),
            });
            pmsToast(targetStatus === 'CONFIRMED' ? 'Đã xác nhận đặt phòng' : 'Đã chuyển về chưa xác nhận', true);
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không cập nhật được trạng thái đặt phòng', false);
        }
    },

    async cancel(id) {
        const reason = window.prompt('Lý do hủy đặt phòng:', '');
        if (reason === null) return;
        try {
            await pmsApi(`/api/pms/reservations/${id}/cancel`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason }),
            });
            pmsToast('Đã hủy đặt phòng', true);
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không hủy được đặt phòng', false);
        }
    },

    async noShow(id) {
        const ok = window.confirm('Ghi nhận booking này là No-show?');
        if (!ok) return;
        try {
            await pmsApi(`/api/pms/reservations/${id}/no-show`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: 'No-show' }),
            });
            pmsToast('Đã ghi nhận no-show', true);
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không ghi nhận no-show được', false);
        }
    },

    async restoreReservation(id) {
        const ok = window.confirm('Khôi phục booking này về trạng thái chờ xác nhận?');
        if (!ok) return;
        try {
            await pmsApi(`/api/pms/reservations/${id}/restore`, { method: 'POST' });
            pmsToast('Đã khôi phục đặt phòng', true);
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không khôi phục được đặt phòng', false);
        }
    },

    branchDisplayName(branch) {
        const code = String(branch?.branch_code || '');
        if (code[0] === 'B' && /^\d+$/.test(code.slice(1))) return `Bin Bin Hotel ${code.slice(1)}`;
        return branch?.name || `Chi nhánh ${branch?.id || ''}`;
    },

    async openTransfer(id) {
        const booking = await this.fetchReservationDetail(id);
        this.state.transferBookingId = booking.id;
        this.state.transferBooking = booking;
        const subtitle = document.getElementById('bk-transfer-subtitle');
        const branchSelect = document.getElementById('bk-transfer-branch');
        const reason = document.getElementById('bk-transfer-reason');
        if (subtitle) subtitle.textContent = `${booking.external_id || `#${booking.id}`} • ${booking.guest_name || 'Khách lẻ'}`;
        if (reason) reason.value = '';
        const branches = (this.state.transferBranches || []).filter((branch) => Number(branch.id) !== Number(booking.branch_id));
        if (!branches.length) {
            pmsToast('Không có chi nhánh khác để chuyển booking', false);
            return;
        }
        if (branchSelect) {
            branchSelect.innerHTML = branches.map((branch) => `<option value="${branch.id}">${this.escape(this.branchDisplayName(branch))}</option>`).join('');
            branchSelect.value = branches[0]?.id || '';
        }
        this.showModal('bk-transfer-modal');
        await this.onTransferBranchChange(branchSelect?.value || '');
    },

    closeTransferModal() {
        this.hideModal('bk-transfer-modal');
        this.state.transferBookingId = null;
        this.state.transferBooking = null;
        this.state.pendingTransferTargetBranchId = null;
    },

    async onTransferBranchChange(branchId) {
        this.state.pendingTransferTargetBranchId = Number(branchId) || null;
        await this.populateTransferRoomTypes(branchId);
    },

    async populateTransferRoomTypes(branchId) {
        const select = document.getElementById('bk-transfer-room-type');
        if (!select || !branchId) {
            if (select) select.innerHTML = '<option value="">Chọn chi nhánh trước</option>';
            return;
        }
        select.innerHTML = '<option value="">Đang tải loại phòng...</option>';
        try {
            const params = new URLSearchParams({ branch_id: branchId });
            const roomTypes = this.apiData(await pmsApi(`/api/pms/room-types?${params.toString()}`), []);
            select.innerHTML = roomTypes.length
                ? roomTypes.map((rt) => `<option value="${rt.id}">${this.escape(rt.name)} • ${pmsMoney(rt.price_per_night || 0)}</option>`).join('')
                : '<option value="">Chi nhánh chưa có loại phòng</option>';
        } catch (err) {
            select.innerHTML = '<option value="">Không tải được loại phòng</option>';
            pmsToast(err.message || 'Không tải được loại phòng chi nhánh đích', false);
        }
    },

    async submitBranchTransfer() {
        const id = this.state.transferBookingId;
        const targetBranchId = Number(this.value('bk-transfer-branch'));
        const targetRoomTypeId = Number(this.value('bk-transfer-room-type'));
        if (!id || !targetBranchId || !targetRoomTypeId) {
            pmsToast('Chọn chi nhánh và loại phòng đích trước khi chuyển', false);
            return;
        }
        const btn = document.getElementById('bk-transfer-submit');
        this.setButtonBusy(btn, true, 'Đang chuyển...');
        try {
            const response = await pmsApi(`/api/pms/reservations/${id}/transfer-branch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_branch_id: targetBranchId,
                    target_room_type_id: targetRoomTypeId,
                    reason: this.value('bk-transfer-reason'),
                }),
            });
            const booking = this.apiData(response, {});
            pmsToast('Đã chuyển chi nhánh đặt phòng', true);
            this.closeTransferModal();
            await this.refreshAfterMutation({ availability: true });
            if (booking?.id) await this.openDetail(booking.id);
        } catch (err) {
            pmsToast(err.message || 'Không chuyển được chi nhánh', false);
        } finally {
            this.setButtonBusy(btn, false, 'Chuyển chi nhánh');
        }
    },

    async openDetail(id) {
        this.state.detailBookingId = id;
        const dialog = document.getElementById('bk-detail-dialog');
        this.showModal('bk-detail-modal');

        // Render immediately from cached list data
        const cached = (this.state.reservations || []).find(b => b.id === id);
        if (cached) {
            this._renderDetailContent(dialog, cached);
        } else if (dialog) {
            dialog.innerHTML = '<div class="bk-detail-loading"><div class="bk-skeleton"></div></div>';
        }

        // Fetch fresh data in background and re-render
        try {
            const booking = this.apiData(await pmsApi(`/api/pms/reservations/${id}`), {});
            if (this.state.detailBookingId === id && dialog) {
                this._renderDetailContent(dialog, booking);
            }
        } catch (err) {
            if (!cached && dialog) {
                dialog.innerHTML = `<div class="bk-detail-loading"><p>Không tải được chi tiết: ${this.escape(err.message)}</p></div>`;
            }
        }
    },

    _renderDetailContent(dialog, booking) {
        if (!dialog || !booking) return;
        const status = booking.reservation_status || 'PENDING';
        const code = booking.external_id || `#${booking.id}`;
        const guestName = booking.guest_name || 'Khách lẻ';

        const rawData = booking.raw_data || {};

        const parseStayMinutes = (value) => {
            const match = String(value || '').match(/^(\d{1,2}):(\d{2})/);
            if (!match) return null;
            const h = Number(match[1]);
            const m = Number(match[2]);
            if (!Number.isFinite(h) || !Number.isFinite(m) || h > 23 || m > 59) return null;
            return h * 60 + m;
        };

        const checkInTime = String(rawData.check_in_at || rawData.check_in_time || rawData.estimated_arrival || booking.estimated_arrival || '14:00').includes('T')
            ? String(rawData.check_in_at || rawData.check_in_time || rawData.estimated_arrival || booking.estimated_arrival || '14:00').slice(11, 16)
            : String(rawData.check_in_at || rawData.check_in_time || rawData.estimated_arrival || booking.estimated_arrival || '14:00').slice(0, 5);
        const checkOutTime = String(rawData.check_out_at || rawData.check_out_time || rawData.estimated_departure || '12:00').includes('T')
            ? String(rawData.check_out_at || rawData.check_out_time || rawData.estimated_departure || '12:00').slice(11, 16)
            : String(rawData.check_out_at || rawData.check_out_time || rawData.estimated_departure || '12:00').slice(0, 5);

        const checkInMinutes = parseStayMinutes(checkInTime);
        const checkOutMinutes = parseStayMinutes(checkOutTime);
        const crossesMidnight = Boolean(
            rawData.ota_cross_midnight_booking
            || (rawData.ota_same_day_booking && checkInMinutes !== null && checkOutMinutes !== null && checkOutMinutes <= checkInMinutes)
        );
        const checkOutDate = rawData.ota_actual_check_out && !crossesMidnight ? rawData.ota_actual_check_out : booking.check_out;
        const actualStayDays = this.dateDiff(booking.check_in, checkOutDate);
        const isHourlyStay = Boolean(rawData.ota_same_day_booking && !crossesMidnight && actualStayDays <= 0);

        const guests = Number(booking.num_guests || booking.num_adults || 1);
        const totalPrice = Number(booking.total_price || 0);
        const depositAmount = Number(booking.deposit_amount || 0);
        const balance = Math.max(0, totalPrice - depositAmount);
        const roomLabel = booking.assigned_room_number ? `Phòng ${booking.assigned_room_number}` : 'Chưa gán';
        const isTransferShadow = Boolean(rawData.transfer_shadow);
        const canConfirm = status === 'PENDING' && !booking.assigned_room_id && !isTransferShadow;
        const canAssign = status === 'CONFIRMED' && !isTransferShadow;
        const canCheckin = status === 'CONFIRMED' && booking.assigned_room_id && this.isCheckinDateReached(booking.check_in) && !isTransferShadow;
        const canCancel = ['PENDING', 'CONFIRMED'].includes(status) && !isTransferShadow;

        const actions = [
            canCheckin ? `<button class="bk-btn primary" onclick="BookingHub.detailCheckin(${booking.id})">Nhận phòng</button>` : '',
            canConfirm ? `<button class="bk-btn primary" onclick="BookingHub.detailConfirm(${booking.id})">Xác nhận</button>` : '',
            canAssign ? `<button class="bk-btn" onclick="BookingHub.detailAssign(${booking.id})">Gán phòng</button>` : '',
            `<button class="bk-btn" onclick="BookingHub.editFromDetail()">Chỉnh sửa</button>`,
            canCancel ? `<button class="bk-btn danger" onclick="BookingHub.detailCancel(${booking.id})">Hủy đặt</button>` : '',
        ].filter(Boolean).join('');

        dialog.innerHTML = `
            <div class="bk-receipt-wrapper">
                <header class="bk-receipt-header">
                    <div class="bk-receipt-brand">
                        <div class="bk-receipt-logo">
                            <img src="/static/logo.png" alt="Bin Bin Hotel" style="width:44px;height:44px;object-fit:contain;">
                        </div>
                        <div class="bk-receipt-brand-text">
                            <h2>BIN BIN HOTEL</h2>
                            <p>Reservation Confirmation</p>
                        </div>
                    </div>
                    <div class="bk-receipt-status">
                        <span class="bk-receipt-badge ${status.toLowerCase()}">${this.statusLabel(status)}</span>
                        <button class="bk-receipt-close" onclick="BookingHub.closeDetail()">×</button>
                    </div>
                </header>

                <div class="bk-receipt-body">
                    <div class="bk-receipt-row">
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Mã Đặt Phòng / Booking ID</span>
                            <strong class="bk-receipt-value large">${this.escape(code)}</strong>
                        </div>
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Khách Hàng / Guest Name</span>
                            <strong class="bk-receipt-value">${this.escape(guestName)}</strong>
                            <span class="bk-receipt-subvalue">${this.escape(booking.guest_phone || '—')}</span>
                        </div>
                    </div>

                    <div class="bk-receipt-divider"></div>

                    <div class="bk-receipt-row">
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Nhận Phòng / Check-in</span>
                            <strong class="bk-receipt-value">${this.escape(this.formatStayDateTime(booking.check_in, checkInTime))}</strong>
                        </div>
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Trả Phòng / Check-out</span>
                            <strong class="bk-receipt-value">${this.escape(this.formatStayDateTime(checkOutDate, checkOutTime))}</strong>
                        </div>
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Lưu Trú / Duration</span>
                            <strong class="bk-receipt-value">${isHourlyStay ? 'Theo giờ' : `${Math.max(1, this.dateDiff(booking.check_in, booking.check_out) || 1)} đêm`}</strong>
                            <span class="bk-receipt-subvalue">${guests} người lớn</span>
                        </div>
                    </div>

                    <div class="bk-receipt-divider"></div>

                    <div class="bk-receipt-row">
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Loại Phòng / Room Type</span>
                            <strong class="bk-receipt-value">${(() => { const parts = (booking.room_type || '—').split(/\s*[-–—]\s*/); const clean = (parts.length >= 2 ? parts[1] : parts[0]).split(/\s*(?:Hệ thống|Hướng dẫn|Payment)/i)[0].trim(); return this.escape((clean || parts[0]).substring(0, 80)); })()}</strong>
                        </div>
                        <div class="bk-receipt-col">
                            <span class="bk-receipt-label">Số Phòng / Room Number</span>
                            <strong class="bk-receipt-value highlight">${this.escape(roomLabel)}</strong>
                        </div>
                    </div>

                    <div class="bk-receipt-divider dashed"></div>

                    <div class="bk-receipt-finance">
                        <div class="bk-receipt-finance-row">
                            <span>Tổng cộng / Total</span>
                            <strong>${pmsMoney(totalPrice)}</strong>
                        </div>
                        <div class="bk-receipt-finance-row success">
                            <span>Đã đặt cọc / Deposit</span>
                            <strong>${pmsMoney(depositAmount)}</strong>
                        </div>
                        <div class="bk-receipt-finance-row balance">
                            <span>Còn lại cần thu / Balance Due</span>
                            <strong>${pmsMoney(balance)}</strong>
                        </div>
                    </div>

                    <div class="bk-receipt-note">
                        <strong>Ghi chú:</strong> ${this.escape(booking.special_requests || (booking.raw_data || {}).notes || 'Không có yêu cầu thêm.')}
                    </div>
                </div>

                <footer class="bk-receipt-footer">
                    <div class="bk-receipt-footer-left">
                        <button class="bk-btn" onclick="BookingHub.openConfirmationPrint()">
                            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                            Lấy đơn xác nhận đặt phòng
                        </button>
                    </div>
                    <div class="bk-receipt-footer-right">
                        ${actions}
                    </div>
                </footer>
            </div>
        `;
    },

    closeDetail() {
        this.hideModal('bk-detail-modal');
    },

    async copyDetailBookingCode() {
        const code = document.querySelector('#bk-detail-hero-meta .bk-detail-code')?.textContent?.trim();
        if (!code) return;
        try {
            await navigator.clipboard.writeText(code);
            const btn = document.getElementById('bk-detail-copy-btn');
            if (btn) {
                const original = btn.innerHTML;
                btn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"></path></svg>';
                setTimeout(() => { btn.innerHTML = original; }, 1600);
            }
            pmsToast('Đã sao chép mã đặt phòng', true);
        } catch (err) {
            pmsToast('Không sao chép được mã đặt phòng', false);
        }
    },

    downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    },

    openConfirmationPrint(id = null) {
        const bookingId = id || this.state.detailBookingId;
        if (!bookingId) return;
        window.open(`/pms/reservations/${bookingId}/confirmation/print`, '_blank', 'noopener');
    },

    async loadHtml2Canvas() {
        if (typeof html2canvas === 'function') return true;
        if (!this.state.html2CanvasPromise) {
            this.state.html2CanvasPromise = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
                script.onload = () => resolve(true);
                script.onerror = () => reject(new Error('Không tải được thư viện chụp ảnh'));
                document.head.appendChild(script);
            });
        }
        await this.state.html2CanvasPromise;
        return typeof html2canvas === 'function';
    },

    async captureDetailImage() {
        try {
            if (!await this.loadHtml2Canvas()) {
                pmsToast('Thiếu thư viện chụp ảnh html2canvas', false);
                return;
            }
        } catch (err) {
            pmsToast(err.message || 'Không tải được thư viện chụp ảnh', false);
            return;
        }
        const dialog = document.querySelector('#bk-detail-modal .bk-detail-dialog');
        const tools = document.querySelector('#bk-detail-modal .bk-detail-tools');
        const closeBtn = document.querySelector('#bk-detail-modal .bk-detail-close');
        const footer = document.getElementById('bk-detail-actions');
        if (!dialog) return;
        try {
            [tools, closeBtn, footer].forEach((el) => { if (el) el.style.display = 'none'; });
            const canvas = await html2canvas(dialog, { scale: 2, backgroundColor: '#ffffff', useCORS: true });
            canvas.toBlob(async (blob) => {
                [tools, closeBtn, footer].forEach((el) => { if (el) el.style.display = ''; });
                if (!blob) return;
                const filename = `xac-nhan-dat-phong-${this.state.detailBookingId || 'booking'}.png`;
                if (navigator.clipboard && window.ClipboardItem) {
                    try {
                        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
                        pmsToast('Đã sao chép ảnh phiếu vào clipboard — dán vào Zalo/Viber để gửi khách', true);
                        return;
                    } catch (clipErr) {
                        // clipboard bị block (HTTP hoặc permission denied) → fallback download
                    }
                }
                this.downloadBlob(blob, filename);
                pmsToast('Trình duyệt không hỗ trợ clipboard — đã tải ảnh về máy', true);
            }, 'image/png');
        } catch (err) {
            [tools, closeBtn, footer].forEach((el) => { if (el) el.style.display = ''; });
            pmsToast('Không thể chụp ảnh phiếu xác nhận', false);
        }
    },

    async detailConfirm(id) {
        await this.confirm(id);
        await this.openDetail(id);
    },

    async detailSetReservationStatus(id, status) {
        await this.setReservationStatus(id, status);
        await this.openDetail(id);
    },

    detailAssign(id) {
        this.closeDetail();
        this.openAssign(id);
    },

    detailCheckin(id) {
        this.closeDetail();
        this.checkin(id);
    },

    async detailNoShow(id) {
        await this.noShow(id);
        await this.openDetail(id);
    },

    async detailCancel(id) {
        await this.cancel(id);
        await this.openDetail(id);
    },

    async detailRestore(id) {
        await this.restoreReservation(id);
        await this.openDetail(id);
    },

    async detailTransfer(id) {
        this.closeDetail();
        await this.openTransfer(id);
    },

    editFromDetail() {
        const id = this.state.detailBookingId;
        this.closeDetail();
        if (id) this.openEdit(id);
    },

    async openAssign(id) {
        this.state.assigningBookingId = id;
        this.state.selectedAssignRoomId = null;
        const list = document.getElementById('bk-assign-list');
        const loading = document.getElementById('bk-assign-loading');
        const submitBtn = document.getElementById('bk-assign-submit');
        if (list) list.innerHTML = '';
        if (submitBtn) submitBtn.disabled = true;
        if (loading) loading.style.display = 'flex';
        this.showModal('bk-assign-modal');
        try {
            const rooms = this.apiData(await pmsApi(`/api/pms/reservations/${id}/assignable-rooms`), []);
            if (!list) return;
            if (!rooms.length) {
                list.innerHTML = '<div class="bk-avail-empty">Không có phòng phù hợp</div>';
                return;
            }
            const assigned = rooms.find((room) => room.is_assigned);
            const unassignHtml = assigned ? `
                <div class="bk-assign-current">
                    <span>Đang gán: <strong>Phòng ${this.escape(assigned.room_number || '—')}</strong></span>
                    <button class="bk-mini-btn danger" type="button" onclick="BookingHub.unassignRoom(${id}, true)">Gỡ gán phòng</button>
                </div>
            ` : '';
            list.innerHTML = unassignHtml + rooms.map((room) => `
                <button class="bk-mini-btn ${room.is_assigned ? 'primary' : ''}" type="button" data-room-id="${Number(room.id)}" onclick="BookingHub.selectAssignRoom(${room.id})">
                    Phòng ${this.escape(room.room_number || '—')}${room.is_assigned ? ' · đang gán' : ''}
                </button>
            `).join('');
        } catch (err) {
            if (list) list.innerHTML = `<div class="bk-avail-empty">${this.escape(err.message || 'Không tải được phòng trống')}</div>`;
        } finally {
            if (loading) loading.style.display = 'none';
        }
    },

    closeAssign() {
        this.hideModal('bk-assign-modal');
        this.state.selectedAssignRoomId = null;
    },

    selectAssignRoom(roomId) {
        this.state.selectedAssignRoomId = Number(roomId) || null;
        document.querySelectorAll('#bk-assign-list [data-room-id]').forEach((btn) => {
            btn.classList.toggle('primary', Number(btn.dataset.roomId) === this.state.selectedAssignRoomId);
        });
        const submitBtn = document.getElementById('bk-assign-submit');
        if (submitBtn) submitBtn.disabled = !this.state.selectedAssignRoomId;
    },

    async assignRoom(roomId = null) {
        const id = this.state.assigningBookingId;
        const selectedRoomId = Number(roomId || this.state.selectedAssignRoomId || 0);
        if (!id) return;
        if (!selectedRoomId) {
            pmsToast('Chọn phòng trước khi xác nhận gán', false);
            return;
        }
        try {
            await pmsApi(`/api/pms/reservations/${id}/assign-room`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_id: selectedRoomId }),
            });
            pmsToast('Đã gán phòng', true);
            this.closeAssign();
            await this.refreshAfterMutation();
        } catch (err) {
            pmsToast(err.message || 'Không gán được phòng', false);
        }
    },

    async unassignRoom(bookingId, fromAssignModal = false) {
        const id = bookingId || this.state.assigningBookingId;
        if (!id) return;
        const ok = window.confirm('Gỡ phòng đang gán khỏi đặt phòng này?');
        if (!ok) return;
        try {
            await pmsApi(`/api/pms/reservations/${id}/unassign-room`, { method: 'POST' });
            pmsToast('Đã gỡ gán phòng', true);
            if (fromAssignModal) this.closeAssign();
            await this.refreshAfterMutation();
            if (this.state.detailBookingId === id) await this.openDetail(id);
        } catch (err) {
            pmsToast(err.message || 'Không gỡ được phòng', false);
        }
    },

    async checkin(id) {
        try {
            const data = this.apiData(await pmsApi(`/api/pms/reservations/${id}/checkin`, { method: 'POST' }), {});
            const reservation = data.reservation || {};
            if (typeof pmsCiOpenReservationModal !== 'function') {
                pmsToast('Modal nhận phòng chưa sẵn sàng', false);
                return;
            }
            window._pmsBookingCheckinId = id;
            pmsCiOpenReservationModal({
                mode: 'checkin',
                booking_id: id,
                title: 'Nhận phòng từ đặt trước',
                submit_label: 'Nhận phòng',
                branch_id: data.branch_id || reservation.branch_id,
                room_id: data.room_id,
                room_number: data.room_number,
                room_type_id: data.room_type_id,
                room_type_name: data.room_type_name,
                max_guests: data.max_guests,
                price_per_night: data.price_per_night,
                price_per_hour: data.price_per_hour,
                price_next_hour: data.price_next_hour,
                min_hours: data.min_hours,
                check_in: reservation.check_in,
                check_out: reservation.check_out,
                estimated_arrival: reservation.estimated_arrival || '14:00',
                total_price: reservation.total_price,
                booking_type: reservation.booking_type || '',
                booking_source: reservation.booking_source || '',
                raw_data: reservation.raw_data || {},
                deposit_amount: reservation.deposit_amount,
                deposit_type: reservation.deposit_type || reservation.payment_method,
                deposit_meta: reservation.deposit_meta || {},
                notes: reservation.special_requests || '',
                guest_id: reservation.guest_id || null,
                guest_name: reservation.guest_name || '',
                guest_phone: reservation.guest_phone || '',
                guest_cccd: reservation.guest_cccd || '',
                guest_id_type: reservation.guest_id_type || 'cccd',
                gender: reservation.gender || '',
                date_of_birth: reservation.date_of_birth || '',
                nationality: reservation.nationality || 'VNM - Việt Nam',
                id_expire: reservation.id_expire || '',
                address: reservation.address || '',
                address_detail: reservation.address_detail || '',
                address_type: reservation.address_type || 'new',
                city: reservation.city || '',
                district: reservation.district || '',
                ward: reservation.ward || '',
                new_city: reservation.new_city || '',
                new_ward: reservation.new_ward || '',
                old_city: reservation.old_city || '',
                old_district: reservation.old_district || '',
                old_ward: reservation.old_ward || '',
                group_code: reservation.group_code,
                group_index: reservation.group_index,
                group_total: reservation.group_total,
                group_summary: reservation.group_summary,
            });
        } catch (err) {
            pmsToast(err.message || 'Không mở được luồng nhận phòng', false);
        }
    }
});
