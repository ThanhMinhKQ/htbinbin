// PMS room status board - Premium Edition
'use strict';

const RoomStatus = {
    state: {
        mode: 'day',
        branchId: null,
        startDate: null,
        endDate: null,
        rawData: null,
        selectedDate: null,
        loading: false,
        timer: null,
        assignBooking: null,
        assignBusy: false,
        blockRooms: [],
        blockBusy: false,
        waitlistGroups: {},
        waitlistContext: null,
    },

    init() {
        const boot = window.PMS_ROOM_STATUS_BOOT || {};
        this.state.branchId = boot.branchId || null;
        
        // Default to today
        const today = new Date();
        const nextWeek = new Date(today);
        nextWeek.setDate(nextWeek.getDate() + 7);
        this.state.startDate = this.toDateInput(today);
        this.state.endDate = this.toDateInput(nextWeek);
        this.state.selectedDate = this.state.startDate;

        this.bindEvents();
        this.syncDateControls();
        document.getElementById('rs-stat-cleaning').closest('.rs-stat-card')?.toggleAttribute('hidden', this.state.mode === 'month');
        document.getElementById('rs-block-open-btn')?.toggleAttribute('hidden', this.state.mode !== 'month');
        this.refresh();
        this.startPolling();
    },

    bindEvents() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.stopPolling();
            } else {
                this.refresh();
                this.startPolling();
            }
        });
        window.addEventListener('ota:cancellation', () => this.refresh(true));
    },

    startPolling() {
        this.stopPolling();
        this.state.timer = window.setInterval(() => this.refresh(true), 60000);
    },

    stopPolling() {
        if (this.state.timer) window.clearInterval(this.state.timer);
        this.state.timer = null;
    },

    setMode(mode) {
        if (this.state.mode === mode) return;
        this.state.mode = mode;
        
        document.getElementById('rs-mode-day').classList.toggle('active', mode === 'day');
        document.getElementById('rs-mode-month').classList.toggle('active', mode === 'month');
        
        document.getElementById('rs-stat-cleaning').closest('.rs-stat-card')?.toggleAttribute('hidden', mode === 'month');
        document.getElementById('rs-block-open-btn')?.toggleAttribute('hidden', mode !== 'month');
        document.getElementById('rs-day-panel').style.display = mode === 'day' ? 'flex' : 'none';
        document.getElementById('rs-month-panel').style.display = mode === 'month' ? 'flex' : 'none';
        this.syncDateControls();

        this.refresh();
    },

    changeBranch(value) {
        this.state.branchId = Number(value) || null;
        this.refresh();
    },

    movePeriod(direction) {
        const start = this.parseDate(this.state.startDate);
        if (this.state.mode === 'day') {
            start.setDate(start.getDate() + direction * 7);
            this.state.startDate = this.toDateInput(start);
            this.state.selectedDate = this.state.startDate;
        } else {
            const days = this.timelineDays();
            const end = this.parseDate(this.state.endDate);
            start.setDate(start.getDate() + direction * days);
            end.setDate(end.getDate() + direction * days);
            this.state.startDate = this.toDateInput(start);
            this.state.endDate = this.toDateInput(end);
        }
        this.syncDateControls();
        this.refresh();
    },

    goToToday() {
        const today = new Date();
        const nextWeek = new Date(today);
        nextWeek.setDate(nextWeek.getDate() + 7);
        this.state.startDate = this.toDateInput(today);
        this.state.endDate = this.toDateInput(nextWeek);
        this.state.selectedDate = this.state.startDate;
        this.syncDateControls();
        this.refresh();
    },

    goToDate(dateStr) {
        if (!dateStr) return;
        this.state.startDate = dateStr;
        this.state.selectedDate = dateStr;
        this.syncDateControls();
        this.refresh();
    },

    setTimelineStart(dateStr) {
        if (!dateStr) return;
        this.state.startDate = dateStr;
        if (this.parseDate(this.state.endDate) < this.parseDate(dateStr)) {
            const end = this.parseDate(dateStr);
            end.setDate(end.getDate() + 7);
            this.state.endDate = this.toDateInput(end);
        }
        this.syncDateControls();
        this.refresh();
    },

    setTimelineEnd(dateStr) {
        if (!dateStr) return;
        this.state.endDate = dateStr;
        if (this.parseDate(dateStr) < this.parseDate(this.state.startDate)) {
            this.state.startDate = dateStr;
        }
        this.syncDateControls();
        this.refresh();
    },

    async refresh(silent = false) {
        this.setLoading(!silent);
        try {
            if (this.state.mode === 'day') {
                await this.loadInventory(silent);
            } else {
                await this.loadTimeline(silent);
            }
        } finally {
            this.setLoading(false);
        }
    },

    async loadInventory(silent) {
        const params = new URLSearchParams({ 
            start_date: this.state.startDate, 
            days: 7 
        });
        if (this.state.branchId) params.set('branch_id', this.state.branchId);

        try {
            const data = await this.api(`/api/pms/inventory/calendar?${params.toString()}`);
            this.state.rawData = data.calendar || [];
            this.renderOverview(this.state.rawData);
            this.renderDayTable(this.state.rawData);
            this.renderDayDetail(this.state.rawData);
            this.setPeriodLabel(this.formatDate(this.state.startDate));
        } catch (err) {
            this.toast(err.message || 'Lỗi tải dữ liệu tồn phòng', false);
        }
    },

    async loadTimeline(silent) {
        const days = this.timelineDays();
        const params = new URLSearchParams({
            start_date: this.state.startDate,
            days: days
        });
        if (this.state.branchId) params.set('branch_id', this.state.branchId);

        try {
            const data = await this.api(`/api/pms/inventory/timeline?${params.toString()}`);
            const rooms = data.timeline || [];
            this.renderTimeline(rooms, days);
            this.renderTimelineStats(rooms);
            this.setPeriodLabel(this.formatDate(this.state.startDate));
        } catch (err) {
            this.toast(err.message || 'Lỗi tải timeline', false);
        }
    },

    renderOverview(calendar) {
        const dayData = calendar.find(d => d.date === this.state.selectedDate) || calendar[0];
        if (!dayData) return;

        document.getElementById('rs-stat-total').textContent = dayData.total_rooms || 0;
        document.getElementById('rs-stat-occupied').textContent = dayData.sold_rooms || 0;
        document.getElementById('rs-stat-booked').textContent = dayData.reserved_rooms || 0;
        document.getElementById('rs-stat-cleaning').textContent = dayData.cleaning_rooms || 0;
        document.getElementById('rs-stat-maintenance').textContent = dayData.out_of_order_rooms || 0;

        const occ = Math.round(dayData.occupancy_rate || 0);
        document.getElementById('rs-stat-occ-text').textContent = `${occ}%`;
        document.getElementById('rs-stat-occ-path').setAttribute('stroke-dasharray', `${occ}, 100`);
        document.getElementById('rs-stat-occ-ratio').textContent = `${dayData.sold_rooms || 0} / ${dayData.total_rooms || 0}`;
    },

    renderDayTable(calendar) {
        const headerRow = document.getElementById('rs-day-header');
        const body = document.getElementById('rs-day-body');
        if (!headerRow || !body) return;

        // Clear dynamic dates
        while (headerRow.children.length > 2) headerRow.lastChild.remove();
        body.innerHTML = '';

        if (!calendar.length) return;

        // Add dates to header
        calendar.forEach(day => {
            const th = document.createElement('th');
            th.className = 'rs-col-date';
            if (day.date === this.state.selectedDate) th.classList.add('active');
            th.innerHTML = `
                <button class="rs-date-header ${day.date === this.state.selectedDate ? 'active' : ''}" type="button" aria-pressed="${day.date === this.state.selectedDate ? 'true' : 'false'}">
                    <strong>${this.formatDay(day.date)}</strong>
                    <small>${this.shortWeekday(this.parseDate(day.date))}</small>
                </button>
            `;
            th.onclick = () => this.selectDate(day.date);
            headerRow.appendChild(th);
        });

        // Get unique room types
        const typesMap = {};
        calendar.forEach(day => {
            (day.room_types || []).forEach(rt => {
                if (!typesMap[rt.room_type]) {
                    typesMap[rt.room_type] = {
                        name: rt.room_type,
                        total: rt.total_rooms,
                        avail: {}
                    };
                }
                typesMap[rt.room_type].avail[day.date] = rt.available_rooms;
            });
        });

        // Render rows
        Object.values(typesMap).forEach(type => {
            const tr = document.createElement('tr');
            let html = `
                <td>
                    <div class="rs-type-name">
                        <div class="rs-type-icon"><i class="ph ph-door-open"></i></div>
                        <span>${this.escape(type.name)}</span>
                    </div>
                </td>
                <td style="font-weight: 700; color: var(--rs-text-secondary);">${type.total} <small style="font-weight: 400; opacity: 0.7;">phòng</small></td>
            `;

            calendar.forEach(day => {
                const avail = type.avail[day.date] ?? 0;
                const ratio = type.total ? (avail / type.total) : 0;
                const colorClass = ratio > 0.5 ? 'green' : ratio > 0.1 ? 'orange' : 'red';
                const active = day.date === this.state.selectedDate ? 'active' : '';

                html += `
                    <td class="rs-avail-cell ${colorClass} ${active}">
                        <button class="rs-avail-tile" type="button" aria-label="${this.escapeAttr(type.name)} còn ${avail} phòng ngày ${this.formatDate(day.date)}" aria-pressed="${day.date === this.state.selectedDate ? 'true' : 'false'}" onclick="RoomStatus.selectDate('${day.date}')">
                            <span class="rs-avail-num">${avail}</span>
                            <span class="rs-avail-label">phòng trống</span>
                            <div class="rs-progress-mini">
                                <div class="rs-progress-bar ${colorClass}" style="width: ${Math.min(100, ratio * 100)}%"></div>
                            </div>
                        </button>
                    </td>
                `;
            });
            tr.innerHTML = html;
            body.appendChild(tr);
        });
    },

    selectDate(date) {
        this.state.selectedDate = date;
        this.renderOverview(this.state.rawData);
        this.renderDayTable(this.state.rawData);
        this.renderDayDetail(this.state.rawData);
    },

    renderDayDetail(calendar) {
        const sidebarTitle = document.getElementById('rs-sidebar-title');
        const sidebarSubtitle = document.getElementById('rs-sidebar-subtitle');
        const body = document.getElementById('rs-day-detail-body');
        if (!sidebarTitle || !body) return;

        const dayData = calendar.find(d => d.date === this.state.selectedDate) || calendar[0];
        if (!dayData) {
            body.innerHTML = '<tr><td colspan="8" class="text-center">Không có dữ liệu</td></tr>';
            return;
        }

        const detailMeta = document.getElementById('rs-day-detail-meta');
        if (detailMeta) {
            detailMeta.textContent = `${this.longWeekday(this.parseDate(dayData.date))}, ${this.formatDate(dayData.date)}`;
        }

        // Sidebar Header
        const d = this.parseDate(dayData.date);
        sidebarTitle.textContent = `Chi tiết ngày ${this.formatDate(dayData.date)}`;
        sidebarSubtitle.textContent = this.longWeekday(d);

        // Sidebar Stat Card
        const availCount = dayData.available_rooms || 0;
        const totalCount = dayData.total_rooms || 1;
        const availPct = Math.round((availCount / totalCount) * 100);
        document.getElementById('rs-sidebar-avail-count').textContent = `${availCount}`;
        document.getElementById('rs-sidebar-avail-pct').textContent = `${availPct}% tổng số phòng`;

        // Render Tables
        let html = '';
        let sums = { total: 0, reserved: 0, sold: 0, cleaning: 0, maintenance: 0, available: 0 };

        (dayData.room_types || []).forEach(rt => {
            const ratio = rt.total_rooms ? (rt.available_rooms / rt.total_rooms) : 0;
            const pct = Math.round(ratio * 100);
            const barColor = pct > 50 ? '#22c55e' : pct > 10 ? '#f59e0b' : '#ef4444';

            sums.total += rt.total_rooms || 0;
            sums.reserved += rt.reserved_rooms || 0;
            sums.sold += rt.sold_rooms || 0;
            sums.cleaning += rt.cleaning_rooms || 0;
            sums.maintenance += rt.out_of_order_rooms || 0;
            sums.available += rt.available_rooms || 0;

            html += `
                <tr>
                    <td>
                        <div class="rs-type-name">
                            <div class="rs-type-icon"><i class="ph ph-door-open"></i></div>
                            <div style="display: flex; flex-direction: column;">
                                <strong>${this.escape(rt.room_type)}</strong>
                                <small style="font-size: 10px; opacity: 0.6; text-transform: uppercase;">${this.escape(rt.room_type_code || 'ROOM')}</small>
                            </div>
                        </div>
                    </td>
                    <td class="text-center" style="font-weight: 600;">${rt.total_rooms}</td>
                    <td class="text-center rs-text-reserved">${rt.reserved_rooms || 0}</td>
                    <td class="text-center rs-text-sold">${rt.sold_rooms || 0}</td>
                    <td class="text-center rs-text-cleaning">${rt.cleaning_rooms || 0}</td>
                    <td class="text-center rs-text-maint">${rt.out_of_order_rooms || 0}</td>
                    <td class="text-center rs-text-avail" style="font-size: 14px; font-weight: 800;">${rt.available_rooms}</td>
                    <td>
                        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; font-weight: 600; color: var(--rs-text-secondary);">
                            <span style="margin-right: 12px">${pct}%</span>
                            <div class="rs-inline-progress">
                                <div class="rs-progress-bar" style="width: ${pct}%; background: ${barColor};"></div>
                            </div>
                        </div>
                    </td>
                </tr>
            `;
        });

        if (dayData.room_types && dayData.room_types.length > 0) {
            const sumRatio = sums.total ? (sums.available / sums.total) : 0;
            const sumPct = Math.round(sumRatio * 100);
            const sumBarColor = sumPct > 50 ? '#22c55e' : sumPct > 10 ? '#f59e0b' : '#ef4444';
            
            html += `
                <tr class="rs-summary-row">
                    <td>TỔNG CỘNG</td>
                    <td class="text-center">${sums.total}</td>
                    <td class="text-center rs-text-reserved">${sums.reserved}</td>
                    <td class="text-center rs-text-sold">${sums.sold}</td>
                    <td class="text-center rs-text-cleaning">${sums.cleaning}</td>
                    <td class="text-center rs-text-maint">${sums.maintenance}</td>
                    <td class="text-center rs-text-avail" style="font-size: 16px;">${sums.available}</td>
                    <td>
                        <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px;">
                            <span style="margin-right: 12px">${sumPct}%</span>
                            <div class="rs-inline-progress">
                                <div class="rs-progress-bar" style="width: ${sumPct}%; background: ${sumBarColor};"></div>
                            </div>
                        </div>
                    </td>
                </tr>
            `;
        }
        body.innerHTML = html;

        this.renderSidebarDonut(dayData);
        this.renderSidebarRoomList(dayData);
    },

    renderSidebarDonut(dayData) {
        const canvas = document.getElementById('rs-avail-donut');
        const legend = document.getElementById('rs-donut-legend');
        if (!canvas || !legend) return;

        const ctx = canvas.getContext('2d');
        const data = dayData.room_types || [];
        const totalAvail = data.reduce((sum, rt) => sum + (rt.available_rooms || 0), 0);
        
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        legend.innerHTML = '';

        if (totalAvail === 0) {
            ctx.beginPath();
            ctx.arc(70, 70, 50, 0, 2 * Math.PI);
            ctx.strokeStyle = '#e2e8f0';
            ctx.lineWidth = 15;
            ctx.stroke();
            return;
        }

        const colors = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];
        let startAngle = -Math.PI / 2;

        data.forEach((rt, i) => {
            if (rt.available_rooms > 0) {
                const sliceAngle = (rt.available_rooms / totalAvail) * 2 * Math.PI;
                const color = colors[i % colors.length];

                ctx.beginPath();
                ctx.arc(70, 70, 50, startAngle, startAngle + sliceAngle);
                ctx.strokeStyle = color;
                ctx.lineWidth = 15;
                ctx.stroke();

                startAngle += sliceAngle;

                const pct = Math.round((rt.available_rooms / totalAvail) * 100);
                const item = document.createElement('div');
                item.className = 'rs-legend-item';
                item.innerHTML = `
                    <div class="rs-legend-info">
                        <div class="rs-legend-dot" style="background: ${color}"></div>
                        <span>${this.escape(rt.room_type)}</span>
                    </div>
                    <strong>${rt.available_rooms} (${pct}%)</strong>
                `;
                legend.appendChild(item);
            }
        });
    },

    renderSidebarRoomList(dayData) {
        const container = document.getElementById('rs-sidebar-room-list');
        if (!container) return;
        
        let html = '';
        (dayData.room_types || []).forEach(rt => {
            const availCount = rt.available_rooms || 0;
            const isOpen = availCount > 0;
            const rooms = this.getAvailableRoomsForType(rt);
            html += `
                <div class="rs-room-group ${isOpen ? 'open' : ''}">
                    <button class="rs-room-group-head" type="button" aria-expanded="${isOpen ? 'true' : 'false'}" onclick="RoomStatus.toggleRoomGroup(this.parentElement)">
                        <span>${this.escape(rt.room_type)} (${availCount} phòng)</span>
                        <i class="ph ph-caret-down"></i>
                    </button>
                    <div class="rs-room-group-body">
                        ${rooms.map(room => `
                            <span class="rs-room-pill">${this.escape(room.room_number)}</span>
                        `).join('') || '<div style="font-size: 11px; opacity: 0.5; padding: 4px 0;">Không có phòng trống</div>'}
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    },

    toggleRoomGroup(el) {
        if (!el) return;
        const isOpen = el.classList.toggle('open');
        el.querySelector('.rs-room-group-head')?.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    },

    getAvailableRoomsForType(roomType) {
        return (roomType.available_room_list || []).slice(0, 10);
    },

    formatMonth(dateStr) {
        const d = this.parseDate(dateStr);
        return String(d.getMonth() + 1).padStart(2, '0');
    },

    formatYear(dateStr) {
        const d = this.parseDate(dateStr);
        return d.getFullYear();
    },

    longWeekday(date) {
        return ['Chủ nhật', 'Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy'][date.getDay()];
    },


    renderTimelineStats(rooms) {
        const physicalRooms = rooms.filter(room => !room.is_unassigned);
        const occupiedRooms = physicalRooms.filter(room => (room.events || []).some(ev => ev.status === 'CHECKED_IN'));
        const bookedEvents = rooms.flatMap(room => room.events || []).filter(ev => ['PENDING', 'CONFIRMED'].includes(ev.status));
        const maintenanceEvents = rooms.flatMap(room => room.events || []).filter(ev => ev.type === 'block');

        document.getElementById('rs-stat-total').textContent = physicalRooms.length || 0;
        document.getElementById('rs-stat-occupied').textContent = occupiedRooms.length || 0;
        document.getElementById('rs-stat-booked').textContent = bookedEvents.length || 0;
        document.getElementById('rs-stat-cleaning').textContent = 0;
        document.getElementById('rs-stat-maintenance').textContent = maintenanceEvents.length || 0;

        const occ = physicalRooms.length ? Math.round((occupiedRooms.length / physicalRooms.length) * 100) : 0;
        document.getElementById('rs-stat-occ-text').textContent = `${occ}%`;
        document.getElementById('rs-stat-occ-path').setAttribute('stroke-dasharray', `${occ}, 100`);
        document.getElementById('rs-stat-occ-ratio').textContent = `${occupiedRooms.length} / ${physicalRooms.length || 0}`;
    },

    renderTimeline(rooms, days) {
        const wrap = document.getElementById('rs-timeline-wrap');
        const header = document.getElementById('rs-timeline-header');
        const grid = document.getElementById('rs-timeline-grid');
        if (!wrap || !header || !grid) return;

        const start = this.parseDate(this.state.startDate);
        const now = new Date();
        const todayStr = this.toDateInput(now);
        wrap.style.setProperty('--rs-days', days);

        // Dynamic column sizing: wider columns for short ranges, compact for long ranges
        const colMin = days <= 7 ? 100 : days <= 14 ? 64 : days <= 21 ? 50 : 46;
        wrap.style.setProperty('--rs-col-min', colMin + 'px');

        // Header
        let headerHtml = '<div class="rs-tm-corner">Phòng</div>';
        for (let i = 0; i < days; i++) {
            const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
            const isToday = this.toDateInput(d) === todayStr;
            const isWeekend = d.getDay() === 0 || d.getDay() === 6;
            headerHtml += `
                <div class="rs-tm-date ${isToday ? 'today' : ''} ${isWeekend ? 'weekend' : ''}">
                    <strong>${d.getDate()}/${d.getMonth() + 1}</strong>
                    <span>${this.shortWeekday(d)}</span>
                </div>
            `;
        }
        header.innerHTML = headerHtml;

        // Grid: Sort to put unassigned rooms at the top
        this.state.waitlistGroups = {};
        const sortedRooms = [...rooms].sort((a, b) => (b.is_unassigned ? 1 : 0) - (a.is_unassigned ? 1 : 0));

        grid.innerHTML = sortedRooms.length ? sortedRooms.map(room => {
            const events = this.prepareTimelineEvents(room.events || [], start, days, room.is_unassigned);
            const lanes = this.assignTimelineLanes(events);
            const laneCount = Math.max(1, lanes.length);
            const roomClass = room.is_unassigned ? 'rs-timeline-row unassigned' : 'rs-timeline-row';
            const roomLabel = room.is_unassigned ? 'ĐẶT PHÒNG CHỜ GÁN' : room.room_number;
            const roomSubLabel = room.is_unassigned ? 'Chờ xếp phòng' : (room.room_type || '');

            let rowHtml = `
                <div class="${roomClass}" style="--rs-lanes: ${laneCount}">
                    <div class="rs-room-label">
                        <strong>${this.escape(roomLabel)}</strong>
                        <small>${this.escape(roomSubLabel)}</small>
                    </div>
            `;

            for (let i = 0; i < days; i++) {
                rowHtml += `<button class="rs-cell" type="button" style="grid-column: ${i + 2}" ${room.is_unassigned ? `onclick="RoomStatus.openWaitlistForDay(${i})"` : ''}></button>`;
            }

            events.forEach(ev => {
                const rawStatus = String(ev.status || '').toUpperCase();
                const status = ev.type === 'block' ? 'maintenance' : rawStatus === 'CHECKED_IN' ? 'occupied' : rawStatus === 'PENDING' ? 'pending' : 'booked';
                const label = ev.label || (rawStatus === 'CHECKED_IN' ? 'Đang ở' : 'Khách hàng');
                const range = ev.is_hourly ? `${this.formatDay(ev.start_date)} · phòng giờ` : `${this.formatDay(ev.start_date)} - ${this.formatDay(ev.end_date)}`;
                const metaIcon = ev.is_hourly ? 'ph ph-clock' : 'ph ph-calendar-blank';
                const blockAttrs = ev.type === 'block' && ev.block_id ? [
                    `onclick="RoomStatus.releaseBlock(${Number(ev.block_id)})"`,
                    `data-block-id="${Number(ev.block_id)}"`,
                ].join(' ') : '';
                const bookingAttrs = ev.type !== 'block' && ev.booking_id ? [
                    `onclick="RoomStatus.openAssignModal(${Number(ev.booking_id)})"`,
                    `data-booking-id="${Number(ev.booking_id)}"`,
                ].join(' ') : '';
                const groupAttrs = ev.type === 'waitlist-group' ? [
                    `onclick="RoomStatus.openWaitlistModal('${this.escapeAttr(ev.groupKey)}')"` ,
                    `data-waitlist-key="${this.escapeAttr(ev.groupKey)}"`,
                ].join(' ') : '';
                const actionAttrs = groupAttrs || bookingAttrs || blockAttrs;

                const row = ev.type === 'waitlist-group' ? 1 : (ev.lane || 0) + 1;
                const barWidth = ev.gridEnd - ev.gridStart;
                const sizeClass = barWidth >= 3 ? 'is-wide' : barWidth >= 2 ? 'is-medium' : 'is-short';

                rowHtml += `
                    <button class="rs-booking-bar ${status} ${sizeClass} ${ev.is_hourly ? 'is-hourly' : ''} ${ev.type === 'waitlist-group' ? 'waitlist-group' : ''}"
                            type="button" 
                            style="grid-column: ${ev.gridStart} / ${ev.gridEnd}; grid-row: ${row};" 
                            title="${this.escape(label)}: ${this.escape(range)}" ${actionAttrs}>
                        <div class="rs-bar-main">
                            <i class="ph ph-user-circle"></i>
                            <strong>${this.escape(label)}</strong>
                        </div>
                        <div class="rs-bar-meta">
                            <i class="${metaIcon}"></i>
                            <span>${this.escape(range)}</span>
                        </div>
                    </button>
                `;
            });

            rowHtml += '</div>';
            return rowHtml;
        }).join('') : '<div class="rs-timeline-empty">Chưa có phòng để hiển thị trong khoảng thời gian này.</div>';
    },

    prepareTimelineEvents(events, start, days, canGroupWaitlist = false) {
        this.state.waitlistGroups = this.state.waitlistGroups || {};
        const visible = [];
        const waitlistBookings = [];

        events.forEach((ev) => {
            const evStart = this.parseDate(ev.start_date);
            const evEnd = this.parseDate(ev.end_date);
            const dayOffset = this.diffDays(start, evStart);
            const rawDuration = this.diffDays(evStart, evEnd) + 1;
            if (dayOffset + rawDuration <= 0 || dayOffset >= days) return;

            const left = Math.max(0, dayOffset);
            const width = Math.min(days - left, rawDuration - (dayOffset < 0 ? Math.abs(dayOffset) : 0));
            const gridStart = left + 2;
            const gridEnd = gridStart + width;
            if (gridEnd <= gridStart) return;

            const item = { ...ev, left, width, gridStart, gridEnd };
            if (canGroupWaitlist && ev.booking_id && ev.type !== 'block') {
                waitlistBookings.push(item);
                return;
            }
            visible.push(item);
        });

        if (canGroupWaitlist && waitlistBookings.length) {
            // Only group bookings that have the EXACT SAME interval
            const intervals = {};
            waitlistBookings.forEach(booking => {
                const key = `${booking.start_date}_${booking.end_date}`;
                if (!intervals[key]) intervals[key] = [];
                intervals[key].push(booking);
            });

            Object.values(intervals).forEach(group => {
                if (group.length === 1) {
                    visible.push(group[0]);
                } else {
                    const first = group[0];
                    const groupKey = `waitlist-${group.map(b => Number(b.booking_id)).join('-')}`;
                    this.state.waitlistGroups[groupKey] = group;
                    visible.push({
                        ...first,
                        type: 'waitlist-group',
                        label: `${group.length} booking chờ gán`,
                        groupKey
                    });
                }
            });
        }

        return visible;
    },

    assignTimelineLanes(events) {
        const lanes = [];
        events
            .sort((a, b) => a.left - b.left || b.width - a.width)
            .forEach((event) => {
                let laneIndex = lanes.findIndex((laneEnd) => event.left >= laneEnd);
                if (laneIndex === -1) {
                    laneIndex = lanes.length;
                    lanes.push(0);
                }
                event.lane = laneIndex;
                lanes[laneIndex] = event.left + event.width;
            });
        return lanes;
    },

    openWaitlistForDay() {
        const firstGroup = Object.keys(this.state.waitlistGroups || {})[0];
        if (!firstGroup) return;
        this.openWaitlistModal(firstGroup);
    },

    openWaitlistModal(groupKey) {
        const bookings = (this.state.waitlistGroups || {})[groupKey] || [];
        const modal = document.getElementById('rs-waitlist-modal');
        const list = document.getElementById('rs-waitlist-list');
        const meta = document.getElementById('rs-waitlist-meta');
        if (!modal || !list) return;
        this.state.waitlistContext = { groupKey, bookings };
        if (meta) meta.textContent = `${bookings.length} booking đang chờ gán phòng trong ngày/khoảng này.`;
        list.innerHTML = bookings.length ? bookings.map((booking) => {
            const rawStatus = String(booking.status || '').toUpperCase();
            const label = booking.label || 'Khách hàng';
            const code = booking.booking_code || booking.code || `#${booking.booking_id}`;
            return `
                <button class="rs-waitlist-item" type="button" onclick="RoomStatus.selectWaitlistBooking(${Number(booking.booking_id)})">
                    <strong>${this.escape(label)}</strong>
                    <span>${this.escape(code)} · ${this.formatDay(booking.start_date)} - ${this.formatDay(booking.end_date)}${booking.room_type ? ` · ${this.escape(booking.room_type)}` : ''}</span>
                    <em>${this.escape(rawStatus || 'PENDING')}</em>
                </button>
            `;
        }).join('') : '<div class="rs-assign-empty">Không có booking chờ gán trong nhóm này.</div>';
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
    },

    selectWaitlistBooking(bookingId) {
        this.closeWaitlistModal();
        this.openAssignModal(bookingId);
    },

    closeWaitlistModal() {
        const modal = document.getElementById('rs-waitlist-modal');
        if (!modal) return;
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        this.state.waitlistContext = null;
    },

    // Helpers
    async openAssignModal(bookingId) {
        if (!bookingId) return;
        this.state.assignBooking = { id: bookingId };
        const modal = document.getElementById('rs-assign-modal');
        const list = document.getElementById('rs-assign-list');
        const current = document.getElementById('rs-assign-current');
        const loading = document.getElementById('rs-assign-loading');
        const error = document.getElementById('rs-assign-error');
        if (list) list.innerHTML = '';
        if (current) {
            current.hidden = true;
            current.innerHTML = '';
        }
        if (error) {
            error.hidden = true;
            error.textContent = '';
        }
        if (loading) loading.hidden = false;
        if (modal) {
            modal.hidden = false;
            modal.setAttribute('aria-hidden', 'false');
        }

        try {
            const rooms = await this.api(`/api/pms/reservations/${bookingId}/assignable-rooms`);
            this.renderAssignRooms(Array.isArray(rooms) ? rooms : []);
        } catch (err) {
            if (error) {
                error.hidden = false;
                error.textContent = err.message || 'Không tải được danh sách phòng phù hợp';
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    },

    renderAssignRooms(rooms) {
        const list = document.getElementById('rs-assign-list');
        const current = document.getElementById('rs-assign-current');
        const title = document.getElementById('rs-assign-title');
        const meta = document.getElementById('rs-assign-meta');
        if (!list) return;

        const assigned = rooms.find(room => room.is_assigned);
        if (title) title.textContent = assigned ? 'Đổi hoặc gỡ phòng' : 'Gán phòng đặt trước';
        if (meta) meta.textContent = assigned ? `Booking đang gán phòng ${assigned.room_number || '—'}` : 'Chọn phòng khả dụng trong đúng loại phòng và khoảng ngày.';
        if (current) {
            current.hidden = !assigned;
            current.innerHTML = assigned ? `
                <span>Đang gán: <strong>Phòng ${this.escape(assigned.room_number || '—')}</strong></span>
                <button class="rs-assign-danger" type="button" onclick="RoomStatus.unassignBooking()">Gỡ gán phòng</button>
            ` : '';
        }

        if (!rooms.length) {
            list.innerHTML = '<div class="rs-assign-empty">Không có phòng phù hợp trong khoảng ngày này.</div>';
            return;
        }

        list.innerHTML = rooms.map(room => `
            <button class="rs-assign-room ${room.is_assigned ? 'active' : ''}" type="button" onclick="RoomStatus.assignBookingRoom(${Number(room.id)})">
                <strong>Phòng ${this.escape(room.room_number || '—')}</strong>
                <span>${this.escape(room.room_type_name || 'Chưa rõ loại phòng')}${room.floor ? ` · Tầng ${this.escape(room.floor)}` : ''}${room.is_assigned ? ' · đang gán' : ''}</span>
            </button>
        `).join('');
    },

    closeAssignModal() {
        const modal = document.getElementById('rs-assign-modal');
        if (!modal) return;
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        this.state.assignBooking = null;
        this.state.assignBusy = false;
    },

    async assignBookingRoom(roomId) {
        const bookingId = this.state.assignBooking?.id;
        if (!bookingId || !roomId || this.state.assignBusy) return;
        this.state.assignBusy = true;
        try {
            await this.api(`/api/pms/reservations/${bookingId}/assign-room`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_id: roomId }),
            });
            this.toast('Đã gán phòng', true);
            this.closeAssignModal();
            await this.refresh(true);
        } catch (err) {
            this.showAssignError(err.message || 'Không gán được phòng');
        } finally {
            this.state.assignBusy = false;
        }
    },

    async unassignBooking() {
        const bookingId = this.state.assignBooking?.id;
        if (!bookingId || this.state.assignBusy) return;
        if (!window.confirm('Gỡ phòng đang gán khỏi booking này?')) return;
        this.state.assignBusy = true;
        try {
            await this.api(`/api/pms/reservations/${bookingId}/unassign-room`, { method: 'POST' });
            this.toast('Đã gỡ gán phòng', true);
            this.closeAssignModal();
            await this.refresh(true);
        } catch (err) {
            this.showAssignError(err.message || 'Không gỡ được phòng');
        } finally {
            this.state.assignBusy = false;
        }
    },

    showAssignError(message) {
        const error = document.getElementById('rs-assign-error');
        if (!error) return;
        error.hidden = false;
        error.textContent = message;
    },

    async loadBlockRooms() {
        const params = new URLSearchParams();
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        const data = await this.api(`/api/pms/inventory/blockable-rooms?${params.toString()}`);
        this.state.blockRooms = Array.isArray(data.rooms) ? data.rooms : [];
        const select = document.getElementById('rs-block-room');
        if (!select) return;
        select.innerHTML = this.state.blockRooms.length ? this.state.blockRooms.map((room) => (
            `<option value="${Number(room.id)}">Phòng ${this.escape(room.room_number || '—')} — ${this.escape(room.room_type_name || 'Chưa phân loại')}</option>`
        )).join('') : '<option value="">Không có phòng khả dụng</option>';
    },

    async openBlockModal(roomId = null) {
        if (this.state.mode !== 'month') return;
        const modal = document.getElementById('rs-block-modal');
        const loading = document.getElementById('rs-block-loading');
        const error = document.getElementById('rs-block-error');
        const start = document.getElementById('rs-block-start');
        const end = document.getElementById('rs-block-end');
        if (error) {
            error.hidden = true;
            error.textContent = '';
        }
        if (start) start.value = this.state.startDate;
        if (end) {
            const next = this.parseDate(this.state.startDate);
            next.setDate(next.getDate() + 1);
            end.value = this.state.endDate || this.toDateInput(next);
        }
        if (loading) loading.hidden = false;
        if (modal) {
            modal.hidden = false;
            modal.setAttribute('aria-hidden', 'false');
        }
        try {
            await this.loadBlockRooms();
            if (roomId) {
                const select = document.getElementById('rs-block-room');
                if (select) select.value = String(roomId);
            }
        } catch (err) {
            this.showBlockError(err.message || 'Không tải được danh sách phòng');
        } finally {
            if (loading) loading.hidden = true;
        }
    },

    closeBlockModal() {
        const modal = document.getElementById('rs-block-modal');
        if (!modal) return;
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        this.state.blockBusy = false;
    },

    async submitBlock() {
        if (this.state.blockBusy) return;
        const payload = {
            room_id: Number(document.getElementById('rs-block-room')?.value || 0),
            start_date: document.getElementById('rs-block-start')?.value || '',
            end_date: document.getElementById('rs-block-end')?.value || '',
            reason: document.getElementById('rs-block-reason')?.value || '',
        };
        if (!payload.room_id || !payload.start_date || !payload.end_date) {
            this.showBlockError('Vui lòng chọn phòng và khoảng ngày khóa');
            return;
        }
        this.state.blockBusy = true;
        try {
            await this.api('/api/pms/inventory/blocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const reason = document.getElementById('rs-block-reason');
            if (reason) reason.value = '';
            this.toast('Đã khóa phòng', true);
            this.closeBlockModal();
            await this.refresh(true);
        } catch (err) {
            this.showBlockError(err.message || 'Không khóa được phòng');
        } finally {
            this.state.blockBusy = false;
        }
    },

    async releaseBlock(blockId) {
        if (!blockId || this.state.blockBusy) return;
        if (!window.confirm('Mở khóa phòng này?')) return;
        this.state.blockBusy = true;
        try {
            await this.api(`/api/pms/inventory/blocks/${blockId}/release`, { method: 'POST' });
            this.toast('Đã mở khóa phòng', true);
            await this.refresh(true);
        } catch (err) {
            this.toast(err.message || 'Không mở khóa được phòng', false);
        } finally {
            this.state.blockBusy = false;
        }
    },

    showBlockError(message) {
        const error = document.getElementById('rs-block-error');
        if (!error) return;
        error.hidden = false;
        error.textContent = message;
    },

    async api(url, options = {}) {
        const res = await fetch(url, {
            headers: { Accept: 'application/json', ...(options.headers || {}) },
            ...options,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || 'API Error');
        return data;
    },

    toDateInput(date) {
        return date.toISOString().split('T')[0];
    },

    parseDate(str) {
        return new Date(str + 'T00:00:00');
    },

    formatDate(str) {
        const [y, m, d] = str.split('-');
        return `${d}/${m}/${y}`;
    },

    formatDay(str) {
        const [y, m, d] = str.split('-');
        return `${d}/${m}`;
    },

    formatWeekday(str) {
        return this.parseDate(str).toLocaleDateString('vi-VN', { weekday: 'long' });
    },

    shortWeekday(date) {
        return date.toLocaleDateString('vi-VN', { weekday: 'short' });
    },

    diffDays(start, end) {
        return Math.round((end - start) / 86400000);
    },

    timelineDays() {
        const days = this.diffDays(this.parseDate(this.state.startDate), this.parseDate(this.state.endDate)) + 1;
        return Math.min(60, Math.max(1, days));
    },

    // Preset range buttons for common time windows
    setPresetRange(rangeType) {
        const today = new Date();
        this.state.startDate = this.toDateInput(today);
        switch (rangeType) {
            case '7d':
                today.setDate(today.getDate() + 6);
                break;
            case '14d':
                today.setDate(today.getDate() + 13);
                break;
            case '21d':
                today.setDate(today.getDate() + 20);
                break;
            case '30d':
                today.setDate(today.getDate() + 29);
                break;
        }
        this.state.endDate = this.toDateInput(today);
        this.syncDateControls();
        this.refresh();
    },

    syncDateControls() {
        const dayControls = document.getElementById('rs-day-date-controls');
        const timelineControls = document.getElementById('rs-timeline-date-controls');
        if (dayControls) dayControls.hidden = this.state.mode !== 'day';
        if (timelineControls) timelineControls.hidden = this.state.mode !== 'month';

        const dayPicker = document.getElementById('rs-date-picker');
        const startPicker = document.getElementById('rs-start-date-picker');
        const endPicker = document.getElementById('rs-end-date-picker');
        if (dayPicker) dayPicker.value = this.state.startDate;
        if (startPicker) startPicker.value = this.state.startDate;
        if (endPicker) endPicker.value = this.state.endDate;
    },

    setLoading(loading) {
        this.state.loading = loading;
        document.querySelector('.rs-page-wrap')?.classList.toggle('is-loading', loading);
        if (!loading) return;
        if (this.state.mode === 'month') {
            this.renderTimelineSkeleton();
        } else {
            this.renderDaySkeleton();
        }
    },

    renderDaySkeleton() {
        const body = document.getElementById('rs-day-detail-body');
        if (!body) return;
        body.innerHTML = Array.from({ length: 4 }).map(() => `
            <tr class="rs-skeleton-row">
                <td><div class="rs-skeleton-text wide"></div></td>
                <td colspan="7"><div class="rs-skeleton-text"></div></td>
            </tr>
        `).join('');
    },

    renderTimelineSkeleton() {
        const header = document.getElementById('rs-timeline-header');
        const grid = document.getElementById('rs-timeline-grid');
        const wrap = document.getElementById('rs-timeline-wrap');
        if (!header || !grid || !wrap) return;
        const days = this.timelineDays();
        wrap.style.setProperty('--rs-days', days);
        const colMin = days <= 7 ? 100 : days <= 14 ? 64 : days <= 21 ? 50 : 46;
        wrap.style.setProperty('--rs-col-min', colMin + 'px');
        header.innerHTML = '<div class="rs-tm-corner">Phòng</div>' + Array.from({ length: days }).map(() => '<div class="rs-tm-date"><div class="rs-skeleton-text"></div></div>').join('');
        
        let gridHtml = '';
        for (let r = 0; r < 8; r++) {
            gridHtml += `
                <div class="rs-timeline-row rs-skeleton-row">
                    <div class="rs-room-label">
                        <div class="rs-skeleton-text wide"></div>
                        <div class="rs-skeleton-text short"></div>
                    </div>
            `;
            for (let c = 0; c < days; c++) {
                gridHtml += `<div class="rs-cell" style="grid-column: ${c + 2}"></div>`;
            }
            if (r % 2 === 0) {
                gridHtml += `<div class="rs-booking-bar rs-skeleton-bar" style="grid-column: 3 / span 4"></div>`;
            }
            gridHtml += '</div>';
        }
        grid.innerHTML = gridHtml;
    },

    setPeriodLabel(text) {
        // No-op
    },

    toast(msg, ok) {
        console.log(msg);
    },

    escape(value) {
        return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;',
        }[char]));
    },

    escapeAttr(value) {
        return this.escape(value).replace(/`/g, '&#96;');
    },

    openBookingHub() {
        window.location.href = '/pms/booking';
    }
};

window.RoomStatus = RoomStatus;
document.addEventListener('DOMContentLoaded', () => RoomStatus.init());
