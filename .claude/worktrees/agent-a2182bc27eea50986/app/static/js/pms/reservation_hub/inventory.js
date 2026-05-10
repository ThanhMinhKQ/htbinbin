// PMS Reservation Hub - inventory, calendar and room blocks
'use strict';

Object.assign(BookingHub, {
    async loadCalendar() {
        const grid = document.getElementById('bk-calendar-grid');
        const loading = document.getElementById('bk-calendar-loading');
        if (grid) grid.innerHTML = '';
        if (loading) loading.style.display = 'flex';

        const params = new URLSearchParams({
            start_date: this.state.calendarStart,
            days: 30,
        });
        if (this.state.branchId) params.set('branch_id', this.state.branchId);

        try {
            const data = this.apiData(await pmsApi(`/api/pms/inventory/calendar?${params.toString()}`), {});
            const rows = Array.isArray(data.calendar) ? data.calendar : [];
            if (grid) {
                grid.innerHTML = rows.map((day) => `
                    <div class="bk-day">
                        <div class="bk-day-head">
                            <span>${this.formatDate(day.date)}</span>
                            <span>${Number(day.occupancy_rate || 0)}%</span>
                        </div>
                        <div class="bk-day-metric">
                            <span><b>${day.available_rooms || 0}</b> Trống</span>
                            <span><b>${day.reserved_rooms || 0}</b> Đặt</span>
                            <span><b>${day.sold_rooms || 0}</b> Đang ở</span>
                            <span><b>${day.out_of_order_rooms || 0}</b> Khóa</span>
                        </div>
                    </div>
                `).join('');
            }
        } catch (err) {
            pmsToast(err.message || 'Không tải được lịch tồn', false);
        } finally {
            if (loading) loading.style.display = 'none';
        }
    },

    moveCalendar(days) {
        const base = new Date(`${this.state.calendarStart}T00:00:00`);
        base.setDate(base.getDate() + days);
        this.state.calendarStart = this.toDateInput(base);
        this.loadCalendar();
    },

    async loadBlockRooms() {
        const params = new URLSearchParams();
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        const data = this.apiData(await pmsApi(`/api/pms/inventory/blockable-rooms?${params.toString()}`), {});
        this.state.blockRooms = Array.isArray(data.rooms) ? data.rooms : [];
        const select = document.getElementById('bk-block-room');
        if (select) {
            select.innerHTML = this.state.blockRooms.length ? this.state.blockRooms.map((room) => (
                `<option value="${room.id}">Phòng ${this.escape(room.room_number)} — ${this.escape(room.room_type_name || 'Chưa phân loại')}</option>`
            )).join('') : '<option value="">Không có phòng khả dụng</option>';
        }
    },

    async loadBlocks() {
        const loading = document.getElementById('bk-block-loading');
        const blockGrid = document.getElementById('bk-block-grid');
        const timelineGrid = document.getElementById('bk-timeline-grid');
        if (loading) loading.style.display = 'flex';
        if (blockGrid) blockGrid.innerHTML = '';
        if (timelineGrid) timelineGrid.innerHTML = '';
        const params = new URLSearchParams({
            start_date: this.state.calendarStart || this.toDateInput(new Date()),
            days: 21,
        });
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        try {
            const [blocksRes, timelineRes] = await Promise.all([
                pmsApi(`/api/pms/inventory/blocks?${params.toString()}&status=ACTIVE`),
                pmsApi(`/api/pms/inventory/timeline?${params.toString()}`),
            ]);
            const blocks = this.apiData(blocksRes, {});
            const timeline = this.apiData(timelineRes, {});
            this.state.blocks = Array.isArray(blocks.blocks) ? blocks.blocks : [];
            this.state.timeline = Array.isArray(timeline.timeline) ? timeline.timeline : [];
            this.renderBlocks();
            this.renderTimeline();
        } catch (err) {
            pmsToast(err.message || 'Không tải được lịch khóa phòng', false);
        } finally {
            if (loading) loading.style.display = 'none';
        }
    },

    renderBlocks() {
        const grid = document.getElementById('bk-block-grid');
        if (!grid) return;
        if (!this.state.blocks.length) {
            grid.innerHTML = '<div style="grid-column:1/-1;color:#64748b;padding:8px 0;">Không có phòng đang khóa trong khoảng ngày này.</div>';
            return;
        }
        grid.innerHTML = this.state.blocks.map((block) => `
            <div class="bk-block-card">
                <h3>Phòng ${this.escape(block.room_number || '—')}</h3>
                <p>${this.formatDate(block.start_date)} → ${this.formatDate(block.end_date)}</p>
                <p>${this.escape(block.reason || 'Không ghi lý do')}</p>
                <div class="bk-row-actions" style="margin-top:10px;justify-content:flex-start;">
                    <button class="bk-mini-btn danger" type="button" onclick="BookingHub.releaseBlock(${block.id})">Mở khóa</button>
                </div>
            </div>
        `).join('');
    },

    renderTimeline() {
        const grid = document.getElementById('bk-timeline-grid');
        if (!grid) return;
        if (!this.state.timeline.length) {
            grid.innerHTML = '';
            return;
        }
        grid.innerHTML = this.state.timeline.map((room) => {
            const events = Array.isArray(room.events) ? room.events : [];
            return `
                <div class="bk-timeline-room">
                    <h3>Phòng ${this.escape(room.room_number || '—')}</h3>
                    <p>${this.escape(room.room_type || '')}</p>
                    <div class="bk-timeline-events">
                        ${events.length ? events.map((event) => `
                            <div class="bk-timeline-event ${event.type === 'block' ? 'block' : ''}">
                                <strong>${this.escape(event.label || (event.type === 'block' ? 'Khóa phòng' : 'Booking'))}</strong>
                                <div>${this.formatDate(event.start_date)} → ${this.formatDate(event.end_date)} • ${this.escape(event.status || '')}</div>
                            </div>
                        `).join('') : '<div class="bk-timeline-event">Không có lịch trong 21 ngày tới</div>'}
                    </div>
                </div>
            `;
        }).join('');
    },

    async openBlock() {
        const today = new Date();
        const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
        const start = document.getElementById('bk-block-start');
        const end = document.getElementById('bk-block-end');
        if (start && !start.value) start.value = this.toDateInput(today);
        if (end && !end.value) end.value = this.toDateInput(tomorrow);
        try {
            await this.loadBlockRooms();
            this.showModal('bk-block-modal');
        } catch (err) {
            pmsToast(err.message || 'Không tải được danh sách phòng', false);
        }
    },

    closeBlock() {
        this.hideModal('bk-block-modal');
    },

    async submitBlock() {
        const btn = document.getElementById('bk-block-submit');
        const payload = {
            room_id: Number(this.value('bk-block-room')),
            start_date: this.value('bk-block-start'),
            end_date: this.value('bk-block-end'),
            reason: this.value('bk-block-reason'),
        };
        if (!payload.room_id || !payload.start_date || !payload.end_date) {
            pmsToast('Vui lòng chọn phòng và khoảng ngày khóa', false);
            return;
        }
        this.setButtonBusy(btn, true, 'Đang khóa...');
        try {
            await pmsApi('/api/pms/inventory/blocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            pmsToast('Đã khóa phòng', true);
            this.closeBlock();
            const reason = document.getElementById('bk-block-reason');
            if (reason) reason.value = '';
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không khóa được phòng', false);
        } finally {
            this.setButtonBusy(btn, false, 'Lưu khóa phòng');
        }
    },

    async releaseBlock(id) {
        const ok = window.confirm('Mở khóa phòng này?');
        if (!ok) return;
        try {
            await pmsApi(`/api/pms/inventory/blocks/${id}/release`, { method: 'POST' });
            pmsToast('Đã mở khóa phòng', true);
            await this.refreshAfterMutation({ availability: true });
        } catch (err) {
            pmsToast(err.message || 'Không mở khóa được phòng', false);
        }
    }
});
