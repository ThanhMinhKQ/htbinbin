// PMS Reservation Hub
'use strict';

const BookingHub = {
    state: {
        branchId: null,
        activeTab: 'today',
        reservations: [],
        roomTypes: [],
        blockRooms: [],
        blocks: [],
        timeline: [],
        otaLogs: [],
        calendarStart: null,
        assigningBookingId: null,
        selectedAssignRoomId: null,
        editingBookingId: null,
        detailBookingId: null,
        otaConfirmBookingId: null,
        otaConfirmBooking: null,
        otaConfirmRoomTypeId: null,
        loading: false,
        modalListenersBound: false,
        guestEntryMode: 'new',
    },

    init() {
        const boot = window.PMS_BOOKING_BOOT || {};
        const params = new URLSearchParams(window.location.search);
        const requestedBranchId = Number(params.get('branch_id')) || null;
        const requestedTab = params.get('tab');
        const requestedSource = (params.get('source') || '').toUpperCase();
        this.state.branchId = requestedBranchId || boot.branchId || null;
        this.state.activeTab = requestedTab === 'ota' || requestedSource === 'OTA' ? 'ota' : (requestedTab || 'all');
        this.state.branches = Array.isArray(boot.branches) ? boot.branches : [];
        this.state.transferBranches = Array.isArray(boot.transferBranches) ? boot.transferBranches : this.state.branches;
        this.state.roomTypes = Array.isArray(boot.roomTypes) ? boot.roomTypes : [];
        this.state.calendarStart = this.toDateInput(new Date());
        this.state.wizardStep = 1;
        this.state.selectedRoomType = null;
        this.state.roomCart = [];
        const branchSelect = document.getElementById('bk-branch');
        if (branchSelect && this.state.branchId) branchSelect.value = String(this.state.branchId);
        if (window.PMS) window.PMS.branchId = this.state.branchId;
        this.bindFormDateDefaults();
        this.bindModalListeners();
        this.bindReservationFormListeners();
        this.renderRoomTypeOptions();
        this.initAvailabilityBar();
        this.bindOtaCancellationRefresh();
        this.applyActiveTabUI();
        this.loadAll({ availability: true });
        this.startOtaRealtimePolling();
    },

    bindOtaCancellationRefresh() {
        if (this.state.otaCancellationRefreshBound) return;
        this.state.otaCancellationRefreshBound = true;
        window.addEventListener('ota:cancellation', () => {
            this.refreshAfterMutation({ availability: true });
        });
    },

    initAvailabilityBar() {
        const today = new Date();
        const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
        const toDateTimeInput = (date, time) => `${this.toDateInput(date)}T${time}`;
        const ciAt = document.getElementById('bk-avail-ci-at');
        const coAt = document.getElementById('bk-avail-co-at');
        const ci = document.getElementById('bk-avail-ci');
        const co = document.getElementById('bk-avail-co');
        if (ciAt && !ciAt.value) ciAt.value = toDateTimeInput(today, '14:00');
        if (coAt && !coAt.value) coAt.value = toDateTimeInput(tomorrow, '12:00');
        if (ci && !ci.value) ci.value = this.toDateInput(today);
        if (co && !co.value) co.value = this.toDateInput(tomorrow);
        this.syncAvailabilityDateHiddenFields();
        ['bk-avail-ci-at', 'bk-avail-co-at'].forEach((id) => {
            const el = document.getElementById(id);
            if (el && !el.dataset.bkAvailDateBound) {
                el.addEventListener('change', () => this.onAvailabilityDateTimeChange());
                el.dataset.bkAvailDateBound = '1';
            }
        });
        this.initBookingDateTimePickers();
    },

    bindFormDateDefaults() {
        const today = new Date();
        const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
        const toDateTimeInput = (date, time) => `${this.toDateInput(date)}T${time}`;
        const ciAt = document.getElementById('bk-form-check-in-at');
        const coAt = document.getElementById('bk-form-check-out-at');
        const ci = document.getElementById('bk-form-check-in');
        const co = document.getElementById('bk-form-check-out');
        if (ciAt && !ciAt.value) ciAt.value = toDateTimeInput(today, '14:00');
        if (coAt && !coAt.value) coAt.value = toDateTimeInput(tomorrow, '12:00');
        if (ci && !ci.value) ci.value = this.toDateInput(today);
        if (co && !co.value) co.value = this.toDateInput(tomorrow);
        this.syncBookingDateHiddenFields();
        ['bk-form-check-in-at', 'bk-form-check-out-at'].forEach((id) => {
            const el = document.getElementById(id);
            if (el && !el.dataset.bkDateBound) {
                el.addEventListener('change', () => this.onBookingDateTimeChange());
                el.dataset.bkDateBound = '1';
            }
        });
        if (typeof this.initBookingPlannerFlatpickr === 'function') {
            this.initBookingPlannerFlatpickr();
        }
        this.initBookingDateTimePickers();
    },

    async changeBranch(value) {
        this.state.branchId = Number(value) || null;
        if (window.PMS) window.PMS.branchId = this.state.branchId;
        await this.loadRoomTypes();
        await this.loadAll({ availability: true });
    },

    async loadRoomTypes() {
        const params = new URLSearchParams();
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        try {
            this.state.roomTypes = this.apiData(await pmsApi(`/api/pms/room-types?${params.toString()}`), []);
            this.renderRoomTypeOptions();
        } catch (err) {
            pmsToast(err.message || 'Không tải được loại phòng', false);
        }
    },

    renderRoomTypeOptions() {
        const select = document.getElementById('bk-form-room-type');
        if (!select) return;
        if (!this.state.roomTypes.length) {
            select.innerHTML = '<option value="">Chưa có loại phòng khả dụng</option>';
            return;
        }
        select.innerHTML = this.state.roomTypes.map((rt) => (
            `<option value="${rt.id}" data-price="${Number(rt.price_per_night || 0)}">${this.escape(rt.name)}</option>`
        )).join('');
    },

    async loadAll(options = {}) {
        const tasks = [this.loadStats(), this.loadReservations()];
        if (this.state.activeTab === 'ota') tasks.push(this.loadOtaPanel());
        await Promise.all(tasks);
        if (options.availability) this.loadAvailabilityBar();
    },

    async refreshAfterMutation(options = {}) {
        const tasks = [this.loadStats(), this.loadReservations()];
        if (this.state.activeTab === 'ota' || options.ota) tasks.push(this.loadOtaPanel());
        await Promise.all(tasks);
        if (options.availability) this.loadAvailabilityBar();
    },

    async loadStats() {
        const params = new URLSearchParams();
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        try {
            const data = this.apiData(await pmsApi(`/api/pms/reservations/stats?${params.toString()}`), {});
            this.text('bk-stat-total', data.total || 0);
            this.text('bk-stat-arrivals', data.today_arrivals || 0);
            this.text('bk-stat-departures', data.today_departures || 0);
            this.text('bk-stat-confirmed', data.confirmed || 0);
            this.text('bk-stat-pending', data.pending || 0);
            this.text('bk-stat-upcoming', data.upcoming_7d || 0);
        } catch (err) {
            pmsToast(err.message || 'Không tải được thống kê đặt phòng', false);
        }
    },
};

window.BookingHub = BookingHub;
