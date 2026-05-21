// PMS Reservation Hub - create/edit reservation form and CRM guest search
'use strict';

Object.assign(BookingHub, {
    openCreate() {
        this.state.editingBookingId = null;
        this.state.selectedRoomType = null;
        this.state.roomCart = [];
        this.setCreateMode(false);
        this.resetCreateForm();
        this.bindFormDateDefaults();
        this.renderRoomTypeOptions();
        this.setWizardStep(1);
        if (typeof pmsPopulateNationalities === 'function') pmsPopulateNationalities('dl-nationality');
        this.switchBookingAddressMode('new', false);
        this.loadWizardAvailability();
        this.showModal('bk-create-modal');
    },

    closeCreate() {
        this.hideModal('bk-create-modal');
    },

    setCreateMode(isEdit) {
        this.text('bk-create-title', isEdit ? 'Sửa đặt phòng' : 'Tạo đặt phòng');
        this.text(
            'bk-create-subtitle',
            isEdit
                ? 'Các thay đổi ngày ở, loại phòng hoặc trạng thái sẽ tự cập nhật tồn phòng.'
                : 'Chọn ngày → chọn phòng → nhập thông tin khách.'
        );
        this.setButtonBusy(document.getElementById('bk-create-submit'), false, isEdit ? 'Lưu thay đổi' : 'Lưu đặt phòng');
        if (isEdit) {
            this.setWizardStep(2);
        }
    },

    async openEdit(id) {
        this.state.editingBookingId = id;
        this.setCreateMode(true);
        this.renderRoomTypeOptions();
        try {
            const booking = this.apiData(await pmsApi(`/api/pms/reservations/${id}`), {});
            if (booking.booking_type === 'OTA' && booking.reservation_status !== 'CONFIRMED') {
                this.state.editingBookingId = null;
                this.setCreateMode(false);
                pmsToast('Chỉ được sửa booking OTA sau khi đã xác nhận và chọn đúng loại phòng.', 'warning');
                return;
            }
            this.state.selectedRoomType = booking.room_type_id ? {
                room_type_id: booking.room_type_id,
                room_type: booking.room_type,
                base_price: booking.total_price / Math.max(1, this.dateDiff(booking.check_in, booking.check_out)),
                available: Math.max(1, Number(booking.raw_data?.reservation_reserved_qty || 1)),
                max_guests: booking.num_guests || 1,
                over_capacity: Boolean(booking.raw_data?.over_capacity_pending),
            } : null;
            this.state.roomCart = this.state.selectedRoomType ? [{
                ...this.state.selectedRoomType,
                quantity: 1,
                unit_total: Number(booking.total_price || 0),
            }] : [];
            this.state.depositAllocationMode = 'split';
            this.state.depositTargetRoomKey = '';
            this.state.depositSplitAmounts = {};
            this.state.depositSplitTouched = false;
            this.state.bookingPricingPreview = booking.raw_data?.pricing_preview || null;
            await this.fillBookingForm(booking);
            this.setWizardStep(2);
            this.showModal('bk-create-modal');
        } catch (err) {
            pmsToast(err.message || 'Không tải được đặt phòng để sửa', false);
        }
    },

    updateBookingNote(id, value) {
        pmsApi(`/api/pms/reservations/${id}/note`, { method: 'PATCH', body: JSON.stringify({ note: value }) });
    },

    onMoneyInput(el) {
        let val = el.value.replace(/\D/g, '');
        if (val === '') {
            el.value = '0';
        } else {
            el.value = Number(val).toLocaleString('vi-VN');
        }
        if (el.id === 'bk-form-total') {
            el.dataset.bkUserEdited = '1';
            this.updateBookingTotalPreview();
        }
        // Force update UI if it's total money or deposit
        this.renderPaymentRoomSummary();
    },

    getMoneyValue(id) {
        const el = document.getElementById(id);
        if (!el) return 0;
        return Number(el.value.replace(/\D/g, '') || 0);
    },

    async fillBookingForm(booking) {
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.value = value ?? '';
        };
        set('bk-form-guest-id', booking.guest_id || '');
        set('bk-form-guest-name', booking.guest_name || '');
        set('bk-form-guest-phone', booking.guest_phone || '');
        set('bk-form-guest-email', booking.guest_email || '');
        set('bk-form-guest-cccd', booking.guest_cccd || '');
        set('bk-form-id-type', booking.guest_id_type || 'cccd');
        set('bk-form-gender', booking.gender || '');
        set('bk-form-date-of-birth', booking.date_of_birth || '');
        set('bk-form-nationality', booking.nationality || 'VNM - Việt Nam');
        if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(document.getElementById('bk-form-id-expire'), booking.id_expire);
        else set('bk-form-id-expire', booking.id_expire || '');
        set('bk-form-address', booking.address || '');
        const raw = booking.raw_data || {};
        const otaChannel = booking.booking_type === 'OTA'
            ? (booking.booking_source || raw.ota_channel || '').replace(/^G2J$/i, 'Go2Joy')
            : '';
        const addressMode = raw.address_type === 'old' ? 'old' : 'new';
        try {
            await this.switchBookingAddressMode(addressMode, false);
            if (addressMode === 'old') {
                set('bk-form-address', raw.address_detail || booking.address || '');
                set('bk-form-province', raw.old_city || '');
                await this.onBookingProvinceChange(document.getElementById('bk-form-province'), true);
                set('bk-form-district', raw.old_district || '');
                await this.onBookingDistrictChange(document.getElementById('bk-form-district'), true);
                set('bk-form-ward', raw.old_ward || '');
                set('bk-form-new-province', raw.city || '');
                set('bk-form-new-ward', raw.ward || '');
            } else {
                set('bk-form-address', raw.address_detail || booking.address || '');
                set('bk-form-province', raw.city || '');
                await this.onBookingProvinceChange(document.getElementById('bk-form-province'), true);
                set('bk-form-district', raw.district || '');
                set('bk-form-ward', raw.ward || '');
            }
        } catch (err) {
            set('bk-form-address', raw.address_detail || booking.address || '');
        }
        set('bk-form-check-in', booking.check_in || '');
        set('bk-form-check-out', booking.check_out || '');
        set('bk-form-check-in-at', booking.raw_data?.check_in_at || `${booking.check_in || ''}T${(booking.estimated_arrival || '14:00').slice(0, 5)}`);
        set('bk-form-check-out-at', booking.raw_data?.check_out_at || `${booking.check_out || ''}T12:00`);
        this.syncBookingDateHiddenFields();
        this.initBookingPlannerFlatpickr();
        set('bk-form-room-type', booking.room_type_id || '');
        set('bk-form-status', ['PENDING', 'CONFIRMED'].includes(booking.reservation_status) ? booking.reservation_status : 'PENDING');
        this.setStatus(['PENDING', 'CONFIRMED'].includes(booking.reservation_status) ? booking.reservation_status : 'PENDING');
        set('bk-form-booking-type', booking.booking_type || 'DIRECT');
        set('bk-form-ota-channel', otaChannel);
        set('bk-form-sales-name', booking.raw_data?.sales_name || '');
        set('bk-form-booking-code', booking.external_id || booking.raw_data?.booking_code || booking.raw_data?.source_booking_code || '');
        if (booking.booking_type === 'OTA') this.ensureOtaChannelOption(otaChannel);
        set('bk-form-zalo-name', booking.raw_data?.zalo_name || '');
        set('bk-form-source-phone', booking.raw_data?.source_phone || '');
        set('bk-form-guests', booking.num_guests || 1);
        set('bk-form-total', Math.round(Number(booking.total_price || 0)).toLocaleString('vi-VN'));
        set('bk-form-deposit', Math.round(Number(booking.deposit_amount || 0)).toLocaleString('vi-VN'));
        const totalInputForEdit = document.getElementById('bk-form-total');
        if (totalInputForEdit) totalInputForEdit.dataset.bkUserEdited = '1';
        set('bk-form-payment-method', booking.deposit_type || booking.payment_method || 'Chi nhánh');
        set('bk-form-payment-ref', booking.deposit_meta?.ref_code || booking.deposit_meta?.beneficiary || booking.deposit_meta?.card_ref || '');
        set('bk-form-requests', booking.special_requests || '');
        set('bk-form-notes', booking.internal_notes || '');
        this.onBookingIdTypeChange();
        this.onBookingTypeChange();
        this.onBookingPaymentMethodChange();
        this.previewBookingPrice();
        this.setBookingCrmFieldsLocked(false);
        document.getElementById('bk-step-2')?.classList.toggle('bk-ota-guest-relaxed', booking.booking_type === 'OTA');
    },

    ensureOtaChannelOption(value) {
        const channel = String(value || '').trim();
        const input = document.getElementById('bk-form-ota-channel');
        if (!channel || !input) return;
        const datalistId = input.getAttribute('list');
        const datalist = datalistId ? document.getElementById(datalistId) : null;
        if (datalist) {
            const exists = Array.from(datalist.options || []).some((option) => option.value === channel);
            if (!exists) {
                const option = document.createElement('option');
                option.value = channel;
                datalist.appendChild(option);
            }
        }
        input.value = channel;
    },

    onBookingTypeChange() {
        const type = this.value('bk-form-booking-type');
        const status = document.getElementById('bk-form-status');
        const infoGrid = document.querySelector('#bk-step-1 .bk-room-meta-row');
        const extraMap = {
            SALES: ['bk-form-sales-name-wrap', 'bk-form-sales-name'],
            OTA: ['bk-form-ota-channel-wrap', 'bk-form-ota-channel'],
            COMPANY: ['bk-form-company-name-wrap', 'bk-form-company-name'],
            ZALO: ['bk-form-zalo-name-wrap', 'bk-form-zalo-name'],
            PHONE: ['bk-form-source-phone-wrap', 'bk-form-source-phone'],
        };
        Object.entries(extraMap).forEach(([sourceType, fieldIds]) => {
            const [wrapId, inputId] = Array.isArray(fieldIds) ? fieldIds : [];
            if (!wrapId || !inputId) return;
            const wrap = document.getElementById(wrapId);
            const input = document.getElementById(inputId);
            const active = type === sourceType;
            if (wrap) wrap.style.display = active ? '' : 'none';
            if (!active && input) {
                input.value = '';
                input.classList.remove('is-invalid');
            }
        });
        // Company extra fields (MST + address)
        const companyTaxWrap = document.getElementById('bk-form-company-tax-wrap');
        const companyAddrWrap = document.getElementById('bk-form-company-address-wrap');
        const isCompany = type === 'COMPANY';
        if (companyTaxWrap) companyTaxWrap.style.display = isCompany ? '' : 'none';
        if (companyAddrWrap) companyAddrWrap.style.display = isCompany ? '' : 'none';
        if (!isCompany) {
            const taxInput = document.getElementById('bk-form-company-tax');
            const addrInput = document.getElementById('bk-form-company-address');
            if (taxInput) { taxInput.value = ''; taxInput.classList.remove('is-invalid'); }
            if (addrInput) { addrInput.value = ''; }
        }

        const codeWrap = document.getElementById('bk-form-booking-code-wrap');
        const codeInput = document.getElementById('bk-form-booking-code');
        const showReferenceCode = type === 'OTA';
        if (codeWrap) codeWrap.style.display = showReferenceCode ? '' : 'none';
        if (!showReferenceCode && codeInput) {
            codeInput.value = '';
            codeInput.classList.remove('is-invalid');
        }
        const isOta = this.value('bk-form-booking-type') === 'OTA';
        document.getElementById('bk-step-2')?.classList.toggle('bk-ota-guest-relaxed', isOta);
        if (isOta) {
            this.applyOtaDepositLock();
        } else {
            this.applyOtaDepositLock(false);
        }
        this.applyCompanyPaymentLock(isCompany);
        if (infoGrid) infoGrid.classList.toggle('has-source-extra', Object.prototype.hasOwnProperty.call(extraMap, type) || showReferenceCode);
        const configRow = document.querySelector('#bk-step-1 .bk-config-row');
        if (configRow) configRow.classList.toggle('bk-config-2col', type === 'OTA' || type === 'COMPANY');
        if (!status || this.state.editingBookingId) return;
        status.value = 'CONFIRMED';
    },

    prefillGuestFromSource() {
        const type = this.value('bk-form-booking-type');
        const guestName = document.getElementById('bk-form-guest-name');
        const guestPhone = document.getElementById('bk-form-guest-phone');
        if (type === 'ZALO') {
            const zaloName = this.value('bk-form-zalo-name');
            if (zaloName && guestName && !guestName.value.trim()) {
                guestName.value = zaloName;
            }
        } else if (type === 'PHONE') {
            const sourcePhone = this.value('bk-form-source-phone');
            if (sourcePhone && guestPhone && !guestPhone.value.trim()) {
                guestPhone.value = sourcePhone;
            }
        }
    },

    getBookingSourceExtraConfig() {
        const type = this.value('bk-form-booking-type');
        const config = {
            SALES: { id: 'bk-form-sales-name', key: 'sales_name', message: 'Vui lòng nhập tên Sales' },
            OTA: { id: 'bk-form-ota-channel', key: 'ota_channel', message: 'Vui lòng nhập kênh OTA' },
            COMPANY: { id: 'bk-form-company-name', key: 'company_name', message: 'Vui lòng nhập tên công ty' },
            ZALO: { id: 'bk-form-zalo-name', key: 'zalo_name', message: 'Vui lòng nhập tên Zalo' },
            PHONE: { id: 'bk-form-source-phone', key: 'source_phone', message: 'Vui lòng nhập số điện thoại nguồn' },
        };
        return config[type] || null;
    },

    getBookingSourceExtraPayload() {
        const type = this.value('bk-form-booking-type');
        if (type === 'COMPANY') {
            return {
                company_name: this.value('bk-form-company-name'),
                company_tax_code: this.value('bk-form-company-tax'),
                company_address: this.value('bk-form-company-address'),
            };
        }
        const cfg = this.getBookingSourceExtraConfig();
        return cfg ? { [cfg.key]: this.value(cfg.id) } : {};
    },

    applyCompanyPaymentLock(locked = false) {
        const method = document.getElementById('bk-form-payment-method');
        if (locked) {
            if (method) method.value = 'Công ty';
            this.updateBookingPaymentMethodCards();
            document.querySelectorAll('.bk-method-card-v2').forEach(card => {
                card.classList.toggle('disabled', card.dataset.method !== 'Công ty');
            });
        } else {
            document.querySelectorAll('.bk-method-card-v2').forEach(card => {
                card.classList.remove('disabled');
            });
        }
    },

    setStatus(val) {
        document.getElementById('bk-form-status').value = val;
        document.querySelectorAll('.bk-seg-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.status === val);
        });
    },

    // ── Availability Bar (toolbar) ─────────────────────────
    async loadAvailabilityBar() {
        const ci = this.value('bk-avail-ci');
        const co = this.value('bk-avail-co');
        const container = document.getElementById('bk-avail-cards');
        if (!container || !ci || !co) return;
        container.innerHTML = '<div class="bk-skeleton" style="height:80px;grid-column:1/-1;"></div>';

        const params = new URLSearchParams({ check_in: ci, check_out: co });
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        const requestId = (this.state.availabilityRequestId || 0) + 1;
        this.state.availabilityRequestId = requestId;
        try {
            const data = this.apiData(await pmsApi(`/api/pms/inventory/availability?${params}`), []);
            if (requestId !== this.state.availabilityRequestId) return;
            container.dataset.count = String(data.length);
            if (!data.length) {
                container.innerHTML = '<div class="bk-avail-empty">Chưa có loại phòng nào</div>';
                return;
            }
            const nights = Math.max(1, this.dateDiff(ci, co));
            container.innerHTML = data.map(rt => this._renderAvailCard(rt, ci, co, nights, 'toolbar')).join('');
            this.renderAvailabilityFallbackPrices(container);
        } catch (err) {
            container.innerHTML = `<div class="bk-avail-empty">${this.escape(err.message || 'Lỗi tải tồn phòng')}</div>`;
        }
    },

    // ── Wizard Availability (modal step 1) ─────────────────
    async loadWizardAvailability() {
        const ci = this.value('bk-form-check-in');
        const co = this.value('bk-form-check-out');
        const container = document.getElementById('bk-wizard-avail-cards');
        if (!container) return;
        if (!ci || !co) {
            container.innerHTML = '<div class="bk-avail-empty">Chọn ngày nhận và ngày trả để xem phòng trống</div>';
            return;
        }
        container.innerHTML = '<div class="bk-skeleton" style="height:80px;grid-column:1/-1;"></div>';

        const params = new URLSearchParams({ check_in: ci, check_out: co });
        if (this.state.branchId) params.set('branch_id', this.state.branchId);
        try {
            const data = this.apiData(await pmsApi(`/api/pms/inventory/availability?${params}`), []);
            container.dataset.count = String(data.length);
            if (!data.length) {
                container.innerHTML = '<div class="bk-avail-empty">Chưa có loại phòng nào</div>';
                return;
            }
            const nights = Math.max(1, this.dateDiff(ci, co));
            container.innerHTML = data.map(rt => this._renderAvailCard(rt, ci, co, nights, 'wizard')).join('');
            this.renderAvailabilityFallbackPrices(container);
        } catch (err) {
            container.innerHTML = `<div class="bk-avail-empty">${this.escape(err.message || 'Lỗi tải tồn phòng')}</div>`;
        }
    },

    _renderAvailCard(rt, ci, co, nights, context) {
        const soldOut = rt.stop_sell || Number(rt.available_rooms || 0) <= 0;
        const low = rt.low_inventory;
        const totalRooms = Number(rt.total_rooms || 0);
        const availableRooms = Number(rt.available_rooms || 0);
        const usedRooms = Math.max(0, totalRooms - availableRooms);
        const usedPct = soldOut ? 100 : (totalRooms > 0 ? Math.round((usedRooms / totalRooms) * 100) : 0);
        const fillClass = soldOut ? 'danger' : low ? 'warn' : 'good';
        const selected = this.getRoomCart().some((item) => Number(item.room_type_id) === Number(rt.room_type_id));
        const selectedQty = this.getRoomCart().find((item) => Number(item.room_type_id) === Number(rt.room_type_id))?.quantity || 1;
        const maxGuests = Number(rt.max_guests || rt.max_occupancy || 2);
        const roomTypeArg = encodeURIComponent(rt.room_type || '');
        const fallback = Math.round(Number(rt.base_price || 0) * nights);
        const clickFn = context === 'toolbar'
            ? `BookingHub.bookFromAvailability('${ci}','${co}',${rt.room_type_id},decodeURIComponent('${roomTypeArg}'),${rt.base_price},${rt.available_rooms},${maxGuests})`
            : `BookingHub.selectWizardRoom(${rt.room_type_id},decodeURIComponent('${roomTypeArg}'),${rt.base_price},${rt.available_rooms},${maxGuests})`;

        return `
            <div class="bk-avail-card ${soldOut ? 'sold-out overbookable' : ''} ${low ? 'low-inventory' : ''} ${selected ? 'selected' : ''}"
                 data-room-type-id="${rt.room_type_id}"
                 data-sold-out="${soldOut ? '1' : '0'}"
                 onclick="${clickFn}">
                <div class="bk-avail-main">
                    <strong>${this.escape(rt.room_type)}</strong>
                    <div class="bk-avail-progress">
                        <div class="bk-avail-fill ${fillClass}" style="width:${usedPct}%"></div>
                    </div>
                    <div class="bk-avail-meta">
                        <span>${soldOut ? 'Hết phòng' : `Còn ${availableRooms}/${totalRooms} phòng`}</span>
                        <span class="bk-money" data-fallback="${fallback}">${pmsMoney(fallback)}</span>
                    </div>
                </div>
                <div class="bk-avail-cta">
                    ${soldOut ? (selected ? `Đã chọn x${selectedQty}` : 'Thêm vào đặt phòng') : (context === 'toolbar' ? 'Đặt phòng' : (selected ? `Đã chọn x${selectedQty}` : 'Thêm'))}
                </div>
            </div>
        `;
    },

    renderAvailabilityFallbackPrices(container) {
        container?.querySelectorAll('.bk-money').forEach((el) => {
            el.textContent = pmsMoney(Number(el.dataset.fallback || 0));
            el.classList.remove('is-loading');
        });
    },

    async updateAvailabilityCardPrices(container, roomTypes, checkInAt = null, checkOutAt = null) {
        const ci = checkInAt || this.value('bk-form-check-in-at') || `${this.value('bk-form-check-in')}T14:00`;
        const co = checkOutAt || this.value('bk-form-check-out-at') || `${this.value('bk-form-check-out')}T12:00`;
        if (!container || !ci || !co || co <= ci) {
            container?.querySelectorAll('.bk-money').forEach((el) => {
                el.textContent = pmsMoney(Number(el.dataset.fallback || 0));
                el.classList.remove('is-loading');
            });
            return;
        }
        await Promise.all((roomTypes || []).map(async (rt) => {
            const priceEl = container.querySelector(`.bk-avail-card[data-room-type-id="${rt.room_type_id}"] .bk-money`);
            if (!priceEl) return;
            try {
                const data = await pmsApi('/api/pms/pricing/preview', {
                    method: 'POST',
                    body: new URLSearchParams({
                        room_type_id: rt.room_type_id,
                        check_in: ci,
                        check_out: co,
                        stay_type: 'AUTO',
                    }),
                });
                priceEl.textContent = pmsMoney(Number(data.total || 0));
            } catch (err) {
                priceEl.textContent = pmsMoney(Number(priceEl.dataset.fallback || 0));
            } finally {
                priceEl.classList.remove('is-loading');
            }
        }));
    },

    selectWizardRoom(roomTypeId, roomTypeName, basePrice, available, maxGuests = 2) {
        const overCapacity = Number(available || 0) <= 0;
        this.state.selectedRoomType = { room_type_id: roomTypeId, room_type: roomTypeName, base_price: basePrice, available, max_guests: maxGuests, over_capacity: overCapacity };
        this.addRoomCartItem(roomTypeId, roomTypeName, basePrice, available, maxGuests);
        const select = document.getElementById('bk-form-room-type');
        if (select) {
            select.innerHTML = `<option value="${roomTypeId}" selected>${this.escape(roomTypeName)}</option>`;
            select.value = roomTypeId;
        }
        const guests = document.getElementById('bk-form-guests');
        if (guests) guests.max = String(this.getRoomCartMaxGuests() || maxGuests || available || 1);
        this.applyOverCapacityStatusLock();
        this.previewBookingPrice();
        this.updateSelectedAvailabilityCard('bk-wizard-avail-cards');
    },

    getRoomCart() {
        if (!Array.isArray(this.state.roomCart)) this.state.roomCart = [];
        return this.state.roomCart;
    },

    addRoomCartItem(roomTypeId, roomTypeName, basePrice, available, maxGuests = 2) {
        const cart = this.getRoomCart();
        const id = Number(roomTypeId);
        const existing = cart.find((item) => Number(item.room_type_id) === id);
        const overCapacity = Number(available || 0) <= 0;
        const maxQty = Math.max(1, Number(available || existing?.available || 1));
        if (existing) {
            if (Number(existing.quantity || 0) >= maxQty) {
                pmsToast(overCapacity ? 'Phòng đã hết tồn, booking sẽ ở trạng thái chờ xác nhận' : `Chỉ còn ${maxQty} phòng loại này`, overCapacity ? 'warning' : false);
            }
            existing.quantity = Math.min(maxQty, Number(existing.quantity || 0) + 1);
            existing.available = maxQty;
            existing.over_capacity = Boolean(existing.over_capacity || overCapacity);
            existing.base_price = Number(basePrice || existing.base_price || 0);
            existing.max_guests = Number(maxGuests || existing.max_guests || 2);
        } else {
            cart.push({
                room_type_id: id,
                room_type: roomTypeName,
                base_price: Number(basePrice || 0),
                available: maxQty,
                max_guests: Number(maxGuests || 2),
                over_capacity: overCapacity,
                quantity: 1,
                unit_total: 0,
            });
        }
        this.renderRoomCart();
        this.applyOverCapacityStatusLock();
    },

    changeRoomCartQty(roomTypeId, delta) {
        const cart = this.getRoomCart();
        const item = cart.find((entry) => Number(entry.room_type_id) === Number(roomTypeId));
        if (!item) return;
        const nextQty = Number(item.quantity || 0) + Number(delta || 0);
        if (nextQty < 1) {
            this.removeRoomCartItem(roomTypeId);
            return;
        }
        item.quantity = Math.min(Number(item.available || nextQty), nextQty);
        this.renderRoomCart();
        this.applyOverCapacityStatusLock();
        this.previewBookingPrice();
        this.updateSelectedAvailabilityCard('bk-wizard-avail-cards');
    },

    removeRoomCartItem(roomTypeId) {
        this.state.roomCart = this.getRoomCart().filter((item) => Number(item.room_type_id) !== Number(roomTypeId));
        this.state.selectedRoomType = this.getRoomCart()[0] || null;
        const select = document.getElementById('bk-form-room-type');
        if (select) select.value = this.state.selectedRoomType?.room_type_id || '';
        this.renderRoomCart();
        this.applyOverCapacityStatusLock();
        this.previewBookingPrice();
        this.updateSelectedAvailabilityCard('bk-wizard-avail-cards');
    },

    getRoomCartQuantity() {
        return this.getRoomCart().reduce((sum, item) => sum + Number(item.quantity || 0), 0);
    },

    getRoomCartMaxGuests() {
        return this.getRoomCart().reduce((sum, item) => {
            return sum + (Number(item.max_guests || 1) * Number(item.quantity || 0));
        }, 0);
    },

    getDepositAllocationRoomLines() {
        const lines = [];
        this.getRoomCart().forEach((item) => {
            const qty = Number(item.quantity || 1);
            for (let i = 1; i <= qty; i += 1) {
                const key = `${item.room_type_id}:${i}`;
                lines.push({
                    key,
                    room_type_id: Number(item.room_type_id),
                    room_type: item.room_type || 'Loại phòng',
                    index: i,
                    quantity: qty,
                    label: qty > 1 ? `${item.room_type || 'Loại phòng'} #${i}` : (item.room_type || 'Loại phòng'),
                });
            }
        });
        return lines;
    },

    getDepositAllocationTypeLines() {
        return this.getRoomCart().map((item) => {
            const qty = Number(item.quantity || 1);
            const unit = Number(item.unit_total || item.base_price || 0);
            return {
                key: String(item.room_type_id),
                room_type_id: Number(item.room_type_id),
                room_type: item.room_type || 'Loại phòng',
                quantity: qty,
                unit_total: unit,
                total: unit * qty,
                label: item.room_type || 'Loại phòng',
            };
        });
    },

    parseDepositSplitInput(value) {
        return Number(String(value || '').replace(/[^0-9]/g, '')) || 0;
    },

    formatDepositSplitInput(value) {
        const amount = this.parseDepositSplitInput(value);
        return amount ? amount.toLocaleString('vi-VN') : '0';
    },

    getDefaultDepositSplitAmounts(lines = this.getDepositAllocationTypeLines()) {
        const deposit = this.getMoneyValue('bk-form-deposit');
        const totalQty = lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0);
        if (!totalQty || deposit <= 0) return {};
        const baseAmount = Math.round(deposit / totalQty);
        let left = deposit;
        const amounts = {};
        lines.forEach((line, lineIndex) => {
            const qty = Number(line.quantity || 1);
            let typeAmount = 0;
            for (let idx = 1; idx <= qty; idx += 1) {
                const isLastRoom = lineIndex === lines.length - 1 && idx === qty;
                const amount = isLastRoom ? left : baseAmount;
                typeAmount += amount;
                left -= amount;
            }
            amounts[line.key] = typeAmount;
        });
        return amounts;
    },

    getDepositSplitAmounts(lines = this.getDepositAllocationTypeLines()) {
        const defaults = this.getDefaultDepositSplitAmounts(lines);
        const current = this.state.depositSplitAmounts || {};
        return lines.reduce((amounts, line) => {
            amounts[line.key] = Object.prototype.hasOwnProperty.call(current, line.key) ? Math.max(0, Number(current[line.key]) || 0) : defaults[line.key] || 0;
            return amounts;
        }, {});
    },

    rebalanceDepositSplitAmounts(changedKey = '') {
        const lines = this.getDepositAllocationTypeLines();
        const deposit = this.getMoneyValue('bk-form-deposit');
        if (!lines.length || deposit <= 0) {
            this.state.depositSplitAmounts = {};
            this.state.depositSplitTouched = false;
            return {};
        }
        if (!changedKey) {
            const defaults = this.getDefaultDepositSplitAmounts(lines);
            this.state.depositSplitAmounts = defaults;
            this.state.depositSplitTouched = false;
            return defaults;
        }
        const amounts = this.getDepositSplitAmounts(lines);
        const changedAmount = Math.min(deposit, Math.max(0, Number(amounts[changedKey] || 0)));
        amounts[changedKey] = changedAmount;
        const otherLines = lines.filter((line) => line.key !== changedKey);
        let remaining = deposit - changedAmount;
        if (otherLines.length === 1) {
            amounts[otherLines[0].key] = remaining;
        } else if (otherLines.length > 1) {
            const otherTotal = otherLines.reduce((sum, line) => sum + Number(amounts[line.key] || 0), 0);
            otherLines.forEach((line, idx) => {
                const amount = idx === otherLines.length - 1
                    ? remaining
                    : (otherTotal > 0 ? Math.round(remaining * Number(amounts[line.key] || 0) / otherTotal) : Math.round(remaining / otherLines.length));
                amounts[line.key] = Math.max(0, amount);
                remaining -= amounts[line.key];
            });
        }
        this.state.depositSplitAmounts = amounts;
        return amounts;
    },

    splitDepositAmountByQuantity(amount, quantity) {
        const qty = Math.max(1, Number(quantity || 1));
        const total = Math.max(0, Number(amount || 0));
        const base = Math.round(total / qty);
        let left = total;
        return Array.from({ length: qty }, (_, idx) => {
            const value = idx === qty - 1 ? left : base;
            left -= value;
            return value;
        });
    },

    setDepositSplitAmount(key, value) {
        this.state.depositSplitAmounts = this.getDepositSplitAmounts();
        this.state.depositSplitAmounts[String(key)] = this.parseDepositSplitInput(value);
        this.state.depositSplitTouched = true;
        this.rebalanceDepositSplitAmounts(String(key));
        this.renderPaymentRoomSummary();
    },

    onSplitMoneyInput(el) {
        let val = el.value.replace(/\D/g, '');
        if (val === '') {
            el.value = '0';
        } else {
            el.value = Number(val).toLocaleString('vi-VN');
        }
    },

    setDepositAllocationMode(mode) {
        this.state.depositAllocationMode = mode === 'single' ? 'single' : 'split';
        if (this.state.depositAllocationMode === 'single' && !this.state.depositTargetRoomKey) {
            this.state.depositTargetRoomKey = this.getDepositAllocationRoomLines()[0]?.key || '';
        }
        this.updateDepositAllocationControls();
        this.renderPaymentRoomSummary();
    },

    setDepositTargetRoom(key) {
        this.state.depositTargetRoomKey = key || '';
        this.renderPaymentRoomSummary();
    },

    updateDepositAllocationControls() {
        const totalQty = this.getRoomCartQuantity();
        const panel = document.getElementById('bk-deposit-allocation-panel');
        if (panel) panel.hidden = totalQty <= 1 || this.isOtaBookingForm();

        const mode = this.state.depositAllocationMode === 'single' ? 'single' : 'split';
        document.querySelectorAll('.bk-deposit-mode-card').forEach((card) => {
            const active = card.dataset.mode === mode;
            card.classList.toggle('active', active);
            card.setAttribute('aria-checked', active ? 'true' : 'false');
        });

        const target = document.getElementById('bk-deposit-target-room');
        const splitWrap = document.getElementById('bk-deposit-split-lines');
        const typeLines = this.getDepositAllocationTypeLines();
        if (splitWrap) {
            const showSplit = mode === 'split' && totalQty > 1 && !this.isOtaBookingForm();
            const amounts = (this.state.depositSplitTouched && showSplit) ? this.getDepositSplitAmounts(typeLines) : this.rebalanceDepositSplitAmounts();
            splitWrap.hidden = !showSplit;
            splitWrap.innerHTML = showSplit ? typeLines.map((line) => {
                const perRoomAmounts = this.splitDepositAmountByQuantity(amounts[line.key] || 0, line.quantity);
                const perRoomHint = line.quantity > 1
                    ? `${line.quantity} phòng • mỗi phòng ${perRoomAmounts.map((amount) => pmsMoney(amount)).join(' / ')}`
                    : '1 phòng';
                return `
                    <label class="bk-deposit-split-line">
                        <span class="bk-split-room-meta">
                            <strong>${this.escape(line.label)}</strong>
                            <small>${this.escape(perRoomHint)}</small>
                        </span>
                        <span class="bk-split-money-editor">
                            <small>Tổng cọc loại phòng</small>
                            <input class="bk-input" type="text" inputmode="numeric" value="${this.formatDepositSplitInput(amounts[line.key] || 0)}" oninput="BookingHub.onSplitMoneyInput(this)" onblur="BookingHub.setDepositSplitAmount('${this.escape(line.key)}', this.value)">
                        </span>
                    </label>
                `;
            }).join('') : '';
        }
        if (!target) return;
        const roomLines = this.getDepositAllocationRoomLines();
        target.innerHTML = roomLines.map((line) => (
            `<option value="${this.escape(line.key)}">${this.escape(line.label)}</option>`
        )).join('');
        if (!roomLines.some((line) => line.key === this.state.depositTargetRoomKey)) {
            this.state.depositTargetRoomKey = roomLines[0]?.key || '';
        }
        target.value = this.state.depositTargetRoomKey;
        target.hidden = mode !== 'single' || totalQty <= 1 || this.isOtaBookingForm();
    },

    getDepositAllocationPayload() {
        const totalQty = this.getRoomCartQuantity();
        const deposit = this.getMoneyValue('bk-form-deposit');
        const roomLines = this.getDepositAllocationRoomLines();
        if (totalQty <= 1 || deposit <= 0 || !roomLines.length) return null;
        const mode = this.state.depositAllocationMode === 'single' ? 'single' : 'split';
        const target = document.getElementById('bk-deposit-target-room');
        if (mode === 'single') {
            const selectedKey = target?.value || this.state.depositTargetRoomKey || roomLines[0].key;
            this.state.depositTargetRoomKey = selectedKey;
            return {
                mode,
                target_key: selectedKey,
                items: roomLines.map((line) => ({
                    room_type_id: line.room_type_id,
                    room_type_index: line.index,
                    amount: line.key === selectedKey ? deposit : 0,
                })),
            };
        }
        const typeLines = this.getDepositAllocationTypeLines();
        const amounts = this.state.depositSplitTouched ? this.getDepositSplitAmounts(typeLines) : this.rebalanceDepositSplitAmounts();
        const perRoomAmounts = typeLines.reduce((map, line) => {
            map[line.room_type_id] = this.splitDepositAmountByQuantity(amounts[line.key] || 0, line.quantity);
            return map;
        }, {});
        return {
            mode,
            items: roomLines.map((line) => ({
                room_type_id: line.room_type_id,
                room_type_index: line.index,
                amount: Number(perRoomAmounts[line.room_type_id]?.[line.index - 1] || 0),
            })),
        };
    },

    renderRoomCart() {
        const cart = this.getRoomCart();
        const wrap = document.getElementById('bk-room-cart');
        const itemsEl = document.getElementById('bk-room-cart-items');
        const totalEl = document.getElementById('bk-room-cart-total');
        const summaryTotalPriceEl = document.getElementById('bk-summary-total-price');

        if (!wrap || !itemsEl || !totalEl) return;
        const totalQty = this.getRoomCartQuantity();
        const hasOverCapacity = this.hasOverCapacityCart();
        wrap.style.display = totalQty ? 'flex' : 'none';
        totalEl.textContent = String(totalQty);

        let grandTotal = 0;
        itemsEl.innerHTML = cart.map((item) => {
            const qty = Number(item.quantity || 0);
            const unitTotal = Number(item.unit_total || item.base_price || 0);
            const lineTotal = unitTotal * qty;
            grandTotal += lineTotal;

            return `
                <div class="bk-cart-item-v4 ${item.over_capacity ? 'over-capacity' : ''}" data-room-type-id="${item.room_type_id}">
                    <div class="bk-cart-item-head">
                        <strong>${this.escape(item.room_type || 'Loại phòng')}</strong>
                        <button class="bk-cart-remove" type="button" onclick="BookingHub.removeRoomCartItem(${item.room_type_id})" title="Xóa">×</button>
                    </div>
                    <div class="bk-cart-item-ctrl">
                        <div class="bk-cart-qty-v4">
                            <button type="button" onclick="BookingHub.changeRoomCartQty(${item.room_type_id}, -1)">−</button>
                            <span>${qty}</span>
                            <button type="button" onclick="BookingHub.changeRoomCartQty(${item.room_type_id}, 1)">+</button>
                        </div>
                        <div class="bk-cart-price-v4">${pmsMoney(lineTotal)}</div>
                    </div>
                </div>
            `;
        }).join('');

        if (summaryTotalPriceEl) {
            summaryTotalPriceEl.textContent = pmsMoney(grandTotal);
        }
        wrap.classList.toggle('has-over-capacity', hasOverCapacity);

        const guests = document.getElementById('bk-form-guests');
        if (guests) guests.max = String(this.getRoomCartMaxGuests() || 1);
        this.applyOverCapacityStatusLock();
        this.renderPaymentRoomSummary();
    },

    hasOverCapacityCart() {
        return this.getRoomCart().some((item) => item.over_capacity || Number(item.available || 0) <= 0);
    },

    applyOverCapacityStatusLock() {
        const locked = this.hasOverCapacityCart();
        const confirmBtn = document.querySelector('.bk-seg-btn[data-status="CONFIRMED"]');
        if (locked) {
            this.setStatus('PENDING');
            if (confirmBtn) confirmBtn.classList.add('disabled');
        } else {
            if (confirmBtn) confirmBtn.classList.remove('disabled');
        }
    },

    renderPaymentRoomSummary() {
        const el = document.getElementById('bk-payment-room-summary');
        if (!el) return;
        const cart = this.getRoomCart();
        if (!cart.length) {
            el.innerHTML = '<div class="bk-payment-empty">Chưa chọn phòng.</div>';
            this.applyOverCapacityStatusLock();
            return;
        }
        const totalQty = this.getRoomCartQuantity();
        const totalGuests = this.getRoomCartMaxGuests();
        const totalMoney = this.getMoneyValue('bk-form-total');
        const deposit = this.getEffectiveBookingDeposit();
        const isOta = this.isOtaBookingForm();

        // Update Dashboard V2 elements
        this.text('bk-main-total-label', isOta ? 'Giá OTA thực thu' : 'Tổng giá trị dự kiến');
        this.text('bk-total-v2', pmsMoney(totalMoney));
        this.text('bk-flow-total', pmsMoney(totalMoney));
        this.text('bk-flow-deposit', pmsMoney(deposit));
        this.text('bk-flow-balance', pmsMoney(Math.max(0, totalMoney - deposit)));

        this.updateDepositAllocationControls();
        const overCapacity = this.hasOverCapacityCart();
        const allocationMode = this.state.depositAllocationMode === 'single' ? 'single' : 'split';
        const allocationLines = this.getDepositAllocationRoomLines();
        const allocationTypeLines = this.getDepositAllocationTypeLines();
        const selectedDepositTarget = document.getElementById('bk-deposit-target-room')?.value || this.state.depositTargetRoomKey;
        const splitAmounts = allocationMode === 'split'
            ? (this.state.depositSplitTouched ? this.getDepositSplitAmounts(allocationTypeLines) : this.rebalanceDepositSplitAmounts())
            : {};
        const balance = Math.max(0, totalMoney - deposit);
        const depositPct = totalMoney > 0 ? Math.min(100, Math.round((deposit / totalMoney) * 100)) : 0;
        const pmsReferenceTotal = this.getPmsReferenceTotal();
        const otaDelta = totalMoney - pmsReferenceTotal;
        const otaDeltaClass = otaDelta > 0 ? 'up' : (otaDelta < 0 ? 'down' : 'same');
        const otaDeltaText = otaDelta === 0 ? 'Bằng giá PMS' : `${otaDelta > 0 ? '+' : '-'}${pmsMoney(Math.abs(otaDelta))}`;

        // Update Dashboard V2 Progress Bar
        const progressBar = document.getElementById('bk-dashboard-progress-bar');
        if (progressBar) progressBar.style.width = `${depositPct}%`;
        const dashboardBadge = document.getElementById('bk-dashboard-badge');
        if (dashboardBadge) dashboardBadge.textContent = `${depositPct}% ĐÃ THANH TOÁN`;
        document.getElementById('bk-payment-dashboard-v2')?.classList.toggle('ota-mode', isOta);

        const rows = cart.map((item) => {
            const qty = Number(item.quantity || 1);
            const unit = Number(item.unit_total || item.base_price || 0);
            const typeLine = allocationTypeLines.find((line) => line.room_type_id === Number(item.room_type_id));
            const typeAmount = allocationMode === 'split' ? Number(splitAmounts[typeLine?.key] || 0) : 0;
            const perRoomAmounts = allocationMode === 'split' ? this.splitDepositAmountByQuantity(typeAmount, qty) : [];
            const allocationPreview = !isOta && totalQty > 1 && deposit > 0
                ? allocationLines
                    .filter((line) => line.room_type_id === Number(item.room_type_id))
                    .map((line, idx, sameTypeLines) => {
                        const amount = allocationMode === 'single' ? (line.key === selectedDepositTarget ? deposit : 0) : Number(perRoomAmounts[line.index - 1] || 0);
                        return `<span class="bk-room-allocation-tag">${this.escape(sameTypeLines.length > 1 ? `#${idx + 1}` : 'Phòng')}: ${pmsMoney(amount)}</span>`;
                    }).join('')
                : '';
            return `
                <div class="bk-receipt-room-card">
                    <div class="bk-room-info">
                        <strong>${this.escape(item.room_type || 'Loại phòng')}</strong>
                        <span>${qty} phòng × ${pmsMoney(unit)}</span>
                        ${allocationPreview ? `<div class="bk-room-allocation-tags">${allocationPreview}</div>` : ''}
                    </div>
                    <div class="bk-room-price">${pmsMoney(unit * qty)}</div>
                </div>
            `;
        }).join('');

        el.innerHTML = `
            ${isOta ? `
                <div class="bk-ota-payment-view">
                    <div class="bk-ota-payment-head">
                        <span class="bk-source-pill">OTA</span>
                        <strong>${this.escape(this.value('bk-form-ota-channel') || 'Kênh OTA')}</strong>
                    </div>
                    <div class="bk-ota-price-compare">
                        <div><span>Giá OTA thực thu</span><strong>${pmsMoney(totalMoney)}</strong></div>
                        <div><span>Giá PMS tham chiếu</span><strong>${pmsMoney(pmsReferenceTotal)}</strong></div>
                        <div class="${otaDeltaClass}"><span>Chênh lệch</span><strong>${otaDeltaText}</strong></div>
                    </div>
                </div>
            ` : ''}
            <div class="bk-receipt-header">
                <div class="bk-receipt-title">
                    <span>Chi tiết phiếu thu</span>
                    <strong>${totalQty} phòng • sức chứa ${totalGuests} khách</strong>
                </div>
            </div>
            ${overCapacity ? '<div class="bk-over-capacity-note">Có hạng phòng đã hết tồn. Booking sẽ ở trạng thái chờ xác nhận cho tới khi đủ tồn.</div>' : ''}
            <div class="bk-receipt-room-list">${rows}</div>
            <div class="bk-receipt-footer">
                ${isOta ? 'Tiền OTA được xử lý theo giá thực thu của kênh.' : (totalQty > 1 ? (allocationMode === 'single' ? 'Toàn bộ tiền cọc sẽ được ghi vào phòng đã chọn.' : 'Tiền cọc sẽ được chia đều cho từng phòng trong nhóm.') : 'Khoản cọc áp dụng cho booking này.')}
            </div>
        `;
    },

    updateSelectedAvailabilityCard(containerId) {
        const cartIds = new Set(this.getRoomCart().map((item) => String(item.room_type_id)));
        document.querySelectorAll(`#${containerId} .bk-avail-card`).forEach((card) => {
            const isSelected = cartIds.has(card.dataset.roomTypeId);
            card.classList.toggle('selected', Boolean(isSelected));
            const cta = card.querySelector('.bk-avail-cta');
            const item = this.getRoomCart().find((entry) => String(entry.room_type_id) === card.dataset.roomTypeId);
            const soldOut = card.dataset.soldOut === '1';
            if (cta) cta.textContent = isSelected ? `Đã chọn x${item?.quantity || 1}` : (soldOut ? 'Thêm vào đặt phòng' : (containerId === 'bk-avail-cards' ? 'Đặt phòng' : 'Thêm'));
        });
    },

    bookFromAvailability(checkIn, checkOut, roomTypeId, roomTypeName, price, available = 1, maxGuests = 2) {
        this.openCreate();
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
        set('bk-form-check-in-at', `${checkIn}T14:00`);
        set('bk-form-check-out-at', `${checkOut}T12:00`);
        this.syncBookingDateHiddenFields();
        this.initBookingPlannerFlatpickr();
        set('bk-form-status', Number(available || 0) <= 0 ? 'PENDING' : 'CONFIRMED');
        this.setStatus(Number(available || 0) <= 0 ? 'PENDING' : 'CONFIRMED');
        this.state.roomCart = [];
        this.selectWizardRoom(roomTypeId, roomTypeName, price, available, maxGuests);
        this.previewBookingPrice();
        this.loadWizardAvailability();
    },

    // ── Wizard Navigation ──────────────────────────────────
    setWizardStep(step) {
        this.state.wizardStep = step;
        ['bk-step-1', 'bk-step-2', 'bk-step-3'].forEach((id, i) => {
            const el = document.getElementById(id);
            if (el) el.classList.toggle('active', i + 1 === step);
        });
        ['bk-wiz-step-1', 'bk-wiz-step-2', 'bk-wiz-step-3'].forEach((id, i) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.classList.remove('active', 'done');
            if (i + 1 === step) el.classList.add('active');
            else if (i + 1 < step) el.classList.add('done');
        });
        const backBtn = document.getElementById('bk-wiz-back');
        const nextBtn = document.getElementById('bk-wiz-next');
        const submitBtn = document.getElementById('bk-create-submit');
        if (backBtn) backBtn.style.display = step > 1 ? 'inline-flex' : 'none';
        if (nextBtn) nextBtn.style.display = step < 3 ? 'inline-flex' : 'none';
        if (nextBtn) nextBtn.textContent = step === 1 ? 'Nhập khách →' : 'Thanh toán →';
        if (submitBtn) submitBtn.style.display = step === 3 ? 'inline-flex' : 'none';
        if (step === 1) {
            this.loadWizardAvailability();
        } else if (step === 2) {
            this.prefillGuestFromSource();
            this.onBookingIdTypeChange();
            this.switchBookingAddressMode(this.getBookingAddressMode(), true);
            setTimeout(() => document.getElementById('bk-form-guest-name')?.focus(), 150);
        } else if (step === 3) {
            this.onBookingPaymentMethodChange();
            this.previewBookingPrice();
            this.updateDepositAllocationControls();
        }

        const wizard = document.querySelector('.bk-wizard-v4');
        if (wizard) {
            wizard.classList.toggle('bk-wiz-summary-active', step === 1);
        }
    },

    goToStep(step) {
        const target = Math.max(1, Math.min(3, Number(step || 1)));
        const current = Number(this.state.wizardStep || 1);
        if (target <= current) {
            this.setWizardStep(target);
            return;
        }
        let guard = 0;
        while (Number(this.state.wizardStep || 1) < target && guard < 3) {
            const before = Number(this.state.wizardStep || 1);
            this.wizardNext();
            if (Number(this.state.wizardStep || 1) === before) break;
            guard += 1;
        }
    },

    wizardNext() {
        if (this.state.wizardStep === 1) {
            const ci = this.value('bk-form-check-in');
            const co = this.value('bk-form-check-out');
            if (!ci || !co) { pmsToast('Vui lòng chọn ngày nhận và ngày trả', false); return; }
            if (this.value('bk-form-check-out-at') <= this.value('bk-form-check-in-at')) {
                pmsToast('Thời gian trả phòng phải sau thời gian nhận phòng', false);
                return;
            }
            if (!this.value('bk-form-booking-type')) {
                this.failReservationValidation('bk-form-booking-type', 'Vui lòng chọn nguồn đặt');
                return;
            }
            if (!this.value('bk-form-status')) {
                this.failReservationValidation('bk-form-status', 'Vui lòng chọn trạng thái');
                return;
            }
            const sourceExtra = this.getBookingSourceExtraConfig();
            if (sourceExtra && !this.value(sourceExtra.id)) {
                this.failReservationValidation(sourceExtra.id, sourceExtra.message);
                return;
            }
            if (this.value('bk-form-booking-type') === 'OTA' && !this.value('bk-form-booking-code')) {
                this.failReservationValidation('bk-form-booking-code', 'Vui lòng nhập mã tham chiếu OTA');
                return;
            }
            if (this.value('bk-form-booking-type') === 'COMPANY' && !this.value('bk-form-company-tax')) {
                this.failReservationValidation('bk-form-company-tax', 'Vui lòng nhập mã số thuế (MST)');
                return;
            }
            if (!this.getRoomCartQuantity() && !this.state.editingBookingId) {
                pmsToast('Vui lòng chọn ít nhất một phòng bằng cách click vào thẻ phòng', false);
                return;
            }
            // Auto-fill company name into guest name field
            if (this.value('bk-form-booking-type') === 'COMPANY') {
                const companyName = this.value('bk-form-company-name');
                if (companyName && !this.value('bk-form-guest-name')) {
                    document.getElementById('bk-form-guest-name').value = companyName;
                }
            }
            this.setWizardStep(2);
            return;
        }
        if (this.state.wizardStep === 2) {
            document.getElementById('bk-step-2')?.classList.toggle('bk-ota-guest-relaxed', this.value('bk-form-booking-type') === 'OTA');
            if (!this.validateReservationGuestStep()) return;
            this.setWizardStep(3);
        }
    },

    openReservationInfoModal() {
        const rt = this.state.selectedRoomType;
        const cart = this.getRoomCart();
        const ci = this.value('bk-form-check-in');
        const co = this.value('bk-form-check-out');
        if ((!rt && !cart.length) || !ci || !co) {
            pmsToast('Vui lòng chọn ngày ở và phòng trước', false);
            return;
        }
        if (cart.length > 1 || this.getRoomCartQuantity() > 1) {
            pmsToast('Modal nhận thông tin nhanh hiện chỉ hỗ trợ một phòng. Vui lòng dùng form đặt phòng đầy đủ.', false);
            return;
        }
        const selected = cart[0] || rt;
        const nights = Math.max(1, this.dateDiff(ci, co));
        const total = this.getMoneyValue('bk-form-total') || Math.round(Number(selected.base_price || 0) * nights);
        const context = {
            title: 'Tạo đặt phòng',
            submit_label: 'Lưu đặt phòng',
            branch_id: this.state.branchId,
            booking_type: this.value('bk-form-booking-type') || 'DIRECT',
            reservation_status: this.value('bk-form-status') || 'CONFIRMED',
            room_type_id: Number(selected.room_type_id),
            room_type: selected.room_type,
            room_number: 'Chưa gán phòng',
            max_guests: selected.max_guests || 2,
            available_rooms: selected.available || 1,
            base_price: Number(selected.base_price || 0),
            check_in: ci,
            check_out: co,
            estimated_arrival: this.getBookingArrivalTime(),
            total_price: total,
            deposit_amount: this.getEffectiveBookingDeposit(),
            notes: this.value('bk-form-requests') || '',
        };
        if (typeof pmsCiOpenReservationModal !== 'function') {
            pmsToast('Modal thông tin khách chưa sẵn sàng', false);
            return;
        }
        this.hideModal('bk-create-modal');
        pmsCiOpenReservationModal(context);
    },

    wizardBack() {
        if (this.state.wizardStep <= 1) return;
        const prev = this.state.wizardStep - 1;
        this.setWizardStep(prev);
        if (prev === 1) this.loadWizardAvailability();
    },

    bindReservationFormListeners() {
        this.bindBookingScanShortcut();
        ['bk-form-total', 'bk-form-deposit'].forEach((id) => {
            const el = document.getElementById(id);
            if (el && !el.dataset.bkMoneyBound) {
                const refreshMoneyPreview = () => {
                    this.updateBookingTotalPreview();
                    this.renderPaymentRoomSummary();
                };
                el.addEventListener('input', () => {
                    if (id === 'bk-form-total') el.dataset.bkUserEdited = '1';
                    if (id !== 'bk-form-deposit') refreshMoneyPreview();
                });
                el.addEventListener('blur', () => {
                    if (id === 'bk-form-deposit') refreshMoneyPreview();
                });
                el.dataset.bkMoneyBound = '1';
            }
        });
        [
            'bk-form-guest-name', 'bk-form-guest-cccd', 'bk-form-id-expire', 'bk-form-gender',
            'bk-form-date-of-birth', 'bk-form-nationality', 'bk-form-guests', 'bk-form-booking-type',
            'bk-form-status', 'bk-form-sales-name', 'bk-form-booking-code', 'bk-form-zalo-name',
            'bk-form-source-phone', 'bk-form-guest-phone', 'bk-form-province', 'bk-form-district',
            'bk-form-ward', 'bk-form-address', 'bk-form-company-name', 'bk-form-company-tax'
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el && !el.dataset.bkValidationBound) {
                el.addEventListener('input', () => el.classList.remove('is-invalid'));
                el.addEventListener('change', () => el.classList.remove('is-invalid'));
                el.dataset.bkValidationBound = '1';
            }
        });
        const birthEl = document.getElementById('bk-form-date-of-birth');
        if (birthEl && !birthEl.dataset.bkCccdExpiryBound) {
            birthEl.addEventListener('blur', () => this.checkBookingBirth(birthEl));
            birthEl.addEventListener('change', () => this.applyBookingCCCDExpiryFromBirth());
            birthEl.dataset.bkCccdExpiryBound = '1';
        }
        if (typeof pmsEnsureVietnameseDateInputs === 'function') {
            pmsEnsureVietnameseDateInputs(['bk-form-id-expire', 'bk-form-date-of-birth']);
        }
        this.updateBookingPaymentMethodCards();
    },

    bindBookingScanShortcut() {
        if (this.state.bookingScanShortcutBound) return;
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'F1') return;
            const modal = document.getElementById('bk-create-modal');
            if (!modal?.classList.contains('show')) return;
            if (this.state.wizardStep !== 2) return;
            if (document.getElementById('scanModal')?.classList.contains('show')) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            this.scanBookingGuest();
        }, true);
        this.state.bookingScanShortcutBound = true;
    },

    formatBookingCapitalize(input) {
        if (!input || !input.value) return;
        input.value = input.value
            .trim()
            .replace(/\s+/g, ' ')
            .toLowerCase()
            .replace(/(^|\s)\S/g, (s) => s.toUpperCase());
    },

    formatBookingSentence(input) {
        if (!input || !input.value) return;
        const value = input.value.trim().replace(/\s+/g, ' ');
        input.value = value ? value.charAt(0).toUpperCase() + value.slice(1) : '';
    },

    formatBookingNumeric(input) {
        if (!input) return;
        input.value = String(input.value || '').replace(/[^\d+]/g, '');
    },

    formatBookingUpper(input) {
        if (!input || !input.value) return;
        input.value = String(input.value || '').trim().toUpperCase();
    },

    validateBookingIdNumber() {
        const input = document.getElementById('bk-form-guest-cccd');
        if (!input || !input.value) return true;
        input.classList.toggle('is-invalid', input.value.trim().length < 6);
        return !input.classList.contains('is-invalid');
    },

    checkBookingIdExpire(input) {
        if (typeof pmsIsCCCDPermanentExpiry === 'function' && pmsIsCCCDPermanentExpiry(input)) {
            input.classList.remove('is-invalid');
            return true;
        }
        if (!input || !input.value) return true;
        const today = this.toDateInput(new Date());
        input.classList.toggle('is-invalid', input.value < today);
        if (input.value < today) pmsToast('Giấy tờ đã hết hạn', false);
        return input.value >= today;
    },

    checkBookingBirth(input) {
        if (!input || !input.value) return true;
        this.applyBookingCCCDExpiryFromBirth();
        const today = this.toDateInput(new Date());
        input.classList.toggle('is-invalid', input.value >= today);
        return input.value < today;
    },

    applyBookingCCCDExpiryFromBirth() {
        if (typeof pmsApplyCCCDExpiryFromBirth !== 'function') return false;
        return pmsApplyCCCDExpiryFromBirth({
            idTypeEl: document.getElementById('bk-form-id-type'),
            birthEl: document.getElementById('bk-form-date-of-birth'),
            expireEl: document.getElementById('bk-form-id-expire'),
            checkExpire: (input) => this.checkBookingIdExpire(input),
        });
    },

    isOtaBookingForm() {
        return this.value('bk-form-booking-type') === 'OTA';
    },

    getEffectiveBookingDeposit() {
        return this.isOtaBookingForm() ? 0 : this.getMoneyValue('bk-form-deposit');
    },

    getEffectiveBookingPaymentMethod() {
        return this.isOtaBookingForm() ? 'OTA' : (this.value('bk-form-payment-method') || 'Chi nhánh');
    },

    getPmsReferenceTotal() {
        return this.getRoomCart().reduce((sum, item) => {
            return sum + Number(item.unit_total || item.base_price || 0) * Number(item.quantity || 1);
        }, 0);
    },

    isBookingTotalManualOverride(totalPrice = this.getMoneyValue('bk-form-total'), referenceTotal = this.getPmsReferenceTotal()) {
        if (this.isOtaBookingForm()) return false;
        const totalInput = document.getElementById('bk-form-total');
        if (totalInput?.dataset.bkUserEdited !== '1') return false;
        const total = Number(totalPrice || 0);
        const reference = Number(referenceTotal || 0);
        if (!Number.isFinite(total) || total <= 0) return false;
        return !Number.isFinite(reference) || Math.round(total) !== Math.round(reference);
    },

    updateBookingTotalPreview() {
        const total = this.getMoneyValue('bk-form-total');
        const isOta = this.isOtaBookingForm();
        const referenceTotal = this.getPmsReferenceTotal();
        const delta = total - referenceTotal;
        const totalLabel = document.getElementById('bk-form-total-label');
        const totalHint = document.getElementById('bk-form-total-hint');
        const previewLabel = document.getElementById('bk-form-total-preview-label');
        const paymentHint = document.getElementById('bk-form-payment-hint');
        if (totalLabel) totalLabel.textContent = isOta ? 'Tổng tiền OTA thực thu' : 'Tổng tiền';
        if (totalHint) totalHint.textContent = isOta ? 'Nhập đúng số tiền trên kênh OTA; PMS chỉ dùng giá nội bộ để tham chiếu.' : 'Tổng tiền sẽ được tự tính từ PricingEngine và có thể chỉnh tay nếu cần.';
        if (previewLabel) previewLabel.textContent = isOta ? 'Giá OTA thực thu' : 'Tổng giá dự kiến';
        if (paymentHint) paymentHint.textContent = isOta ? 'Với OTA không nhập tiền cọc trước; tổng tiền lưu trên booking là giá kênh OTA, giá PMS chỉ để so sánh.' : 'Khoản khách trả trước cho booking.';
        this.text('bk-form-total-preview', total > 0 ? pmsMoney(total) : '—');
        this.text('bk-form-ota-price-delta', isOta && referenceTotal > 0 ? `PMS tham chiếu ${pmsMoney(referenceTotal)} • Chênh lệch ${delta >= 0 ? '+' : '-'}${pmsMoney(Math.abs(delta))}` : '');
        if (isOta) this.applyOtaDepositLock();
    },

    syncBookingDateHiddenFields() {
        const ciAt = this.value('bk-form-check-in-at');
        const coAt = this.value('bk-form-check-out-at');
        const ci = document.getElementById('bk-form-check-in');
        const co = document.getElementById('bk-form-check-out');
        if (ci) ci.value = ciAt ? ciAt.slice(0, 10) : '';
        if (co) co.value = coAt ? coAt.slice(0, 10) : '';
    },

    syncAvailabilityDateHiddenFields() {
        const ciAt = this.value('bk-avail-ci-at');
        const coAt = this.value('bk-avail-co-at');
        const ci = document.getElementById('bk-avail-ci');
        const co = document.getElementById('bk-avail-co');
        if (ci) ci.value = ciAt ? ciAt.slice(0, 10) : '';
        if (co) co.value = coAt ? coAt.slice(0, 10) : '';
    },

    initBookingPlannerFlatpickr() {
        const plannerFields = [
            { hiddenId: 'bk-form-check-in-at', displayId: 'bk-form-check-in-at-display', role: 'check-in' },
            { hiddenId: 'bk-form-check-out-at', displayId: 'bk-form-check-out-at-display', role: 'check-out' },
        ];
        const toDate = (value) => {
            if (!value) return null;
            const next = new Date(value);
            return Number.isNaN(next.getTime()) ? null : next;
        };
        const locale = typeof flatpickr !== 'undefined' && flatpickr.l10ns && flatpickr.l10ns.vn
            ? flatpickr.l10ns.vn
            : undefined;
        const syncInstanceFromHidden = (instance, hiddenInput) => {
            const nextDate = toDate(hiddenInput.value);
            if (!nextDate) {
                instance.clear(false);
                return;
            }
            const currentDate = instance.selectedDates[0];
            if (!currentDate || currentDate.getTime() !== nextDate.getTime()) {
                instance.setDate(nextDate, false);
            }
        };

        plannerFields.forEach(({ hiddenId, displayId, role }) => {
            const hiddenInput = document.getElementById(hiddenId);
            const displayInput = document.getElementById(displayId);
            if (!hiddenInput || !displayInput || typeof flatpickr !== 'function') return;

            if (displayInput._flatpickr) {
                syncInstanceFromHidden(displayInput._flatpickr, hiddenInput);
                return;
            }

            flatpickr(displayInput, {
                enableTime: true,
                time_24hr: true,
                minuteIncrement: 30,
                allowInput: false,
                disableMobile: true,
                locale,
                minDate: role === 'check-out' ? 'today' : null,
                dateFormat: 'd/m/Y, H:i',
                defaultDate: toDate(hiddenInput.value),
                prevArrow: '<i class="bi bi-chevron-left"></i>',
                nextArrow: '<i class="bi bi-chevron-right"></i>',
                onReady: (_selectedDates, _dateStr, instance) => {
                    instance.input.readOnly = true;
                    instance.calendarContainer.classList.add('bk-planner-flatpickr-popup');
                    instance.calendarContainer.dataset.plannerRole = role;
                    syncInstanceFromHidden(instance, hiddenInput);
                },
                onOpen: (_selectedDates, _dateStr, instance) => {
                    instance.calendarContainer.dataset.plannerRole = role;
                },
                onChange: (selectedDates) => {
                    if (!selectedDates.length) {
                        hiddenInput.value = '';
                        this.onBookingDateTimeChange();
                        return;
                    }
                    hiddenInput.value = flatpickr.formatDate(selectedDates[0], 'Y-m-d\\TH:i');
                    this.onBookingDateTimeChange();
                },
            });
        });
    },

    initBookingDateTimePickers() {
        if (typeof ShadDateTimePicker !== 'function') return;
        document.querySelectorAll('#pms-booking-page .ci-shad-dt-wrap').forEach((el) => {
            if (el.dataset.shadDtBound !== '1') new ShadDateTimePicker(el);
            if (el._shadDateTimePicker) el._shadDateTimePicker.syncFromInput();
        });
    },

    getBookingArrivalTime() {
        const ciAt = this.value('bk-form-check-in-at');
        return ciAt && ciAt.includes('T') ? ciAt.slice(11, 16) : '14:00';
    },

    onBookingDateTimeChange() {
        this.syncBookingDateHiddenFields();
        if (!this.state.editingBookingId && this.getRoomCartQuantity()) {
            this.state.roomCart = [];
            this.state.selectedRoomType = null;
            const select = document.getElementById('bk-form-room-type');
            if (select) select.value = '';
            this.renderRoomCart();
        }
        this.loadWizardAvailability();
        this.previewBookingPrice();
    },

    onAvailabilityDateTimeChange() {
        this.syncAvailabilityDateHiddenFields();
        clearTimeout(this.state.availabilityReloadTimer);
        this.state.availabilityReloadTimer = setTimeout(() => this.loadAvailabilityBar(), 250);
    },

    async previewBookingPrice() {
        const cart = this.getRoomCart();
        const rt = this.state.selectedRoomType;
        const ci = this.value('bk-form-check-in-at');
        const co = this.value('bk-form-check-out-at');
        const totalInput = document.getElementById('bk-form-total');
        const isOta = this.isOtaBookingForm();
        const breakdown = document.getElementById('bk-form-price-breakdown');
        if ((!cart.length && !rt) || !ci || !co) {
            if (breakdown) breakdown.innerHTML = '<div class="bk-field-hint">Chọn phòng và ngày ở để xem giá.</div>';
            this.updateBookingTotalPreview();
            return;
        }
        if (co <= ci) {
            if (breakdown) breakdown.innerHTML = '<div class="bk-field-hint">Thời gian trả phòng phải sau thời gian nhận phòng.</div>';
            if (totalInput && !isOta) totalInput.value = '0';
            this.updateBookingTotalPreview();
            return;
        }
        if (breakdown) breakdown.innerHTML = '<div class="bk-field-hint">Đang tính giá dự kiến...</div>';
        try {
            const targets = cart.length ? cart : [rt];
            const results = await Promise.all(targets.map(async (item) => {
                const data = await pmsApi('/api/pms/pricing/preview', {
                    method: 'POST',
                    body: new URLSearchParams({
                        room_type_id: item.room_type_id,
                        check_in: ci,
                        check_out: co,
                        stay_type: 'AUTO',
                    }),
                });
                const unitTotal = Math.round(Number(data.total || 0));
                item.unit_total = unitTotal;
                return { item, data, unitTotal };
            }));
            const total = results.reduce((sum, row) => sum + row.unitTotal * Number(row.item.quantity || 1), 0);
            this.state.bookingPricingPreview = results[0]?.data || null;
            if (totalInput && !isOta && !totalInput.dataset.bkUserEdited) totalInput.value = Number(total).toLocaleString('vi-VN');
            this.renderBookingPriceBreakdown(results[0]?.data || {}, { referenceLabel: isOta ? 'Tổng PMS tham chiếu' : 'Tổng cộng' });
            if (breakdown && results.length > 1) {
                const summary = results.map((row) => {
                    const qty = Number(row.item.quantity || 1);
                    return `<div class="bk-price-row"><span>${this.escape(row.item.room_type)} x${qty}</span><strong>${pmsMoney(row.unitTotal * qty)}</strong></div>`;
                }).join('');
                breakdown.insertAdjacentHTML('afterbegin', `<div class="bk-price-group">${summary}</div>`);
            }
            this.renderRoomCart();
        } catch (err) {
            this.state.bookingPricingPreview = null;
            const targets = cart.length ? cart : [rt];
            const fallbackTotal = targets.reduce((sum, item) => {
                const unit = Math.round(Number(item.base_price || 0) * Math.max(1, this.dateDiff(ci.slice(0, 10), co.slice(0, 10))));
                item.unit_total = unit;
                return sum + unit * Number(item.quantity || 1);
            }, 0);
            if (totalInput && !isOta && !totalInput.dataset.bkUserEdited) totalInput.value = Number(fallbackTotal).toLocaleString('vi-VN');
            if (breakdown) {
                const hint = this.escape(err.message || 'Không tính được giá từ PricingEngine.');
                breakdown.innerHTML = `<div class="bk-field-hint">${hint} ${isOta ? 'Giữ nguyên giá OTA đã nhập và chỉ dùng giá cơ bản để tham chiếu.' : 'Đang dùng giá cơ bản.'}</div>`;
            }
            this.renderRoomCart();
        }
        this.updateBookingTotalPreview();
    },

    renderBookingPriceBreakdown(data, { referenceLabel = 'Tổng cộng' } = {}) {
        const std = document.getElementById('bk-form-price-std');
        const breakdown = document.getElementById('bk-form-price-breakdown');
        const cfg = data?.config || {};
        if (std) std.textContent = `Khung chuẩn ${cfg.std_checkin_time || '14:00'} → ${cfg.std_checkout_time || '12:00'}`;
        if (!breakdown) return;
        const rows = Array.isArray(data?.breakdown) ? data.breakdown : [];
        if (!rows.length) {
            breakdown.innerHTML = '<div class="bk-field-hint" style="padding:12px;">Chưa có chi tiết giá.</div>';
            return;
        }
        const labelMap = {
            EARLY_CHECKIN_FEE: 'Phí nhận sớm',
            LATE_CHECKOUT_FEE: 'Phí trả muộn',
            ROOM_CHARGE: 'Tiền phòng',
            HOURLY_CHARGE: 'Tiền phòng theo giờ',
            REFUND: 'Hoàn tiền',
            DISCOUNT_MANUAL: 'Giảm giá',
        };
        const cssClass = {
            EARLY_CHECKIN_FEE: 'fee-early',
            LATE_CHECKOUT_FEE: 'fee-late',
            ROOM_CHARGE: 'fee-core',
            HOURLY_CHARGE: 'fee-core',
            REFUND: 'fee-refund',
            DISCOUNT_MANUAL: 'fee-refund',
        };
        const timeLabel = (iso) => {
            if (!iso) return '';
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return '';
            return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
        };
        const body = rows.map((item) => {
            const name = labelMap[item.type] || item.type || 'Khoản giá';
            const amount = Number(item.amount || 0);
            const range = item.start_iso && item.end_iso
                ? `${timeLabel(item.start_iso)} → ${timeLabel(item.end_iso)}`
                : (item.days ? `${item.days} đêm` : (item.hours ? `${item.hours} giờ` : ''));
            const isRefund = amount < 0 || ['REFUND', 'DISCOUNT_MANUAL'].includes(item.type);
            const amountText = isRefund ? `-${pmsMoney(Math.abs(amount))}` : pmsMoney(amount);
            return `
                <div class="bk-bd-row ${cssClass[item.type] || ''}">
                    <span class="bk-bd-row-label">
                        <span class="bk-bd-row-name">${this.escape(name)}</span>
                        ${range ? `<span class="bk-bd-row-time">${this.escape(range)}</span>` : ''}
                    </span>
                    <span class="bk-bd-row-amount">${amountText}</span>
                </div>
            `;
        }).join('');
        breakdown.innerHTML = `
            <div class="bk-bd-rows">${body}</div>
            <div class="bk-bd-row bk-bd-total">
                <span class="bk-bd-row-name">${this.escape(referenceLabel)}</span>
                <span class="bk-bd-row-amount">${pmsMoney(Number(data.total || 0))}</span>
            </div>
        `;
    },

    getBookingAddressMode() {
        return document.querySelector('input[name="bk-area"]:checked')?.value || 'new';
    },

    populateBookingDatalist(datalistId, items) {
        const dl = document.getElementById(datalistId);
        if (!dl) return;
        dl.innerHTML = '';
        const normalize = (item) => typeof item === 'string' ? item : item.name;
        const strip = typeof vnStripPrefix === 'function' ? vnStripPrefix : (s) => s;
        [...(items || [])]
            .sort((a, b) => strip(normalize(a)).localeCompare(strip(normalize(b)), 'vi', { numeric: true }))
            .forEach((item) => {
                const opt = document.createElement('option');
                opt.value = normalize(item) || '';
                if (item && typeof item === 'object') {
                    if (item.code) opt.dataset.code = item.code;
                    if (item.short) opt.dataset.short = item.short;
                }
                dl.appendChild(opt);
            });
    },

    getBookingDatalistOption(datalistId, value) {
        const dl = document.getElementById(datalistId);
        if (!dl || !value) return null;
        const norm = typeof vnNormVietnamese === 'function'
            ? (v) => vnNormVietnamese(typeof vnNormWardNumber === 'function' ? vnNormWardNumber(v) : v)
            : (v) => String(v || '').toLowerCase().trim();
        const target = norm(value);
        for (const opt of dl.options) {
            if (norm(opt.value) === target) return opt;
        }
        return null;
    },

    clearBookingConversion() {
        const prov = document.getElementById('bk-form-new-province');
        const ward = document.getElementById('bk-form-new-ward');
        if (prov) prov.value = '';
        if (ward) ward.value = '';
    },

    async switchBookingAddressMode(mode = 'new', keepValues = true) {
        const normalizedMode = mode === 'old' ? 'old' : 'new';
        const radio = document.querySelector(`input[name="bk-area"][value="${normalizedMode}"]`);
        if (radio) radio.checked = true;
        if (!keepValues) {
            ['bk-form-province', 'bk-form-district', 'bk-form-ward'].forEach((id) => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
        }
        this.populateBookingDatalist('bk-dl-district', []);
        this.populateBookingDatalist('bk-dl-ward', []);
        this.clearBookingConversion();

        const distGrp = document.getElementById('bk-grp-district');
        const convGrp = document.getElementById('bk-conversion-grp');
        const lblProv = document.getElementById('bk-lbl-province');
        const lblDist = document.getElementById('bk-lbl-district');
        const lblWard = document.getElementById('bk-lbl-ward');

        if (lblProv) lblProv.textContent = 'Tỉnh/Thành phố *';
        if (lblDist) lblDist.textContent = 'Quận/Huyện *';
        if (lblWard) lblWard.textContent = 'Phường/Xã *';

        if (normalizedMode === 'new') {
            if (distGrp) distGrp.style.display = 'none';
            if (convGrp) convGrp.style.display = 'none';
            const provinces = typeof vnLoadNewProvinces === 'function' ? await vnLoadNewProvinces() : [];
            this.populateBookingDatalist('bk-dl-province', (provinces || []).map((p) => ({ name: p.name, short: p.short })));
        } else {
            if (distGrp) distGrp.style.display = '';
            if (convGrp) convGrp.style.display = '';
            const provinces = typeof vnLoadOldProvinces === 'function' ? await vnLoadOldProvinces() : [];
            this.populateBookingDatalist('bk-dl-province', provinces || []);
        }

        const province = document.getElementById('bk-form-province');
        if (province && province.value) await this.onBookingProvinceChange(province, true);
    },

    async onBookingProvinceChange(inputEl, keepChildValues = false) {
        const mode = this.getBookingAddressMode();
        const provinceName = inputEl?.value?.trim() || '';
        const districtEl = document.getElementById('bk-form-district');
        const wardEl = document.getElementById('bk-form-ward');
        if (!keepChildValues) {
            if (districtEl) districtEl.value = '';
            if (wardEl) wardEl.value = '';
        }
        this.populateBookingDatalist('bk-dl-district', []);
        this.populateBookingDatalist('bk-dl-ward', []);
        this.clearBookingConversion();
        if (!provinceName) return;

        if (mode === 'new') {
            const opt = this.getBookingDatalistOption('bk-dl-province', provinceName);
            let short = opt?.dataset?.short || null;
            if (!short && typeof vnStripPrefix === 'function') {
                const opt2 = this.getBookingDatalistOption('bk-dl-province', vnStripPrefix(provinceName));
                short = opt2?.dataset?.short || null;
                if (short && inputEl) inputEl.value = opt2.value;
            }
            if (!short) return;
            const wards = typeof vnLoadNewWards === 'function' ? await vnLoadNewWards(short) : [];
            this.populateBookingDatalist('bk-dl-ward', wards || []);
            return;
        }

        const opt = this.getBookingDatalistOption('bk-dl-province', provinceName);
        this.state.bookingOldProvince = {
            code: opt?.dataset?.code ? Number(opt.dataset.code) : null,
            name: inputEl?.value?.trim() || provinceName,
        };
        this.state.bookingOldDistrict = { code: null, name: '' };
        if (!this.state.bookingOldProvince.code) return;
        const districts = typeof vnLoadOldDistricts === 'function'
            ? await vnLoadOldDistricts(this.state.bookingOldProvince.code)
            : [];
        this.populateBookingDatalist('bk-dl-district', districts || []);
        if (districtEl?.value) await this.onBookingDistrictChange(districtEl, true);
    },

    async onBookingDistrictChange(inputEl, keepWardValue = false) {
        if (this.getBookingAddressMode() !== 'old') return;
        const wardEl = document.getElementById('bk-form-ward');
        if (!keepWardValue && wardEl) wardEl.value = '';
        this.populateBookingDatalist('bk-dl-ward', []);
        this.clearBookingConversion();

        const districtName = inputEl?.value?.trim() || '';
        const opt = this.getBookingDatalistOption('bk-dl-district', districtName);
        this.state.bookingOldDistrict = {
            code: opt?.dataset?.code ? Number(opt.dataset.code) : null,
            name: districtName,
        };
        if (!this.state.bookingOldDistrict.code) return;
        const wards = typeof vnLoadOldWards === 'function'
            ? await vnLoadOldWards(this.state.bookingOldDistrict.code)
            : [];
        this.populateBookingDatalist('bk-dl-ward', wards || []);
        if (wardEl?.value) await this.onBookingWardChange(wardEl);
    },

    async onBookingWardChange(inputEl) {
        if (this.getBookingAddressMode() !== 'old') return;
        const wardName = inputEl?.value?.trim() || '';
        this.clearBookingConversion();
        if (!wardName) return;
        if (typeof vnIsInDatalist === 'function' && !vnIsInDatalist('bk-dl-ward', wardName)) return;
        try {
            const oldProvince = this.state.bookingOldProvince || {};
            const oldDistrict = this.state.bookingOldDistrict || {};
            const res = await fetch('/api/vn-address/convert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    old_ward_name: wardName,
                    old_province_name: oldProvince.name || '',
                    old_district_name: oldDistrict.name || '',
                    old_province_code: oldProvince.code || null,
                }),
            });
            const result = await res.json();
            const newProvince = document.getElementById('bk-form-new-province');
            const newWard = document.getElementById('bk-form-new-ward');
            if (newProvince) newProvince.value = result.new_province || oldProvince.name || '';
            if (newWard) newWard.value = result.new_ward || wardName;
        } catch (err) {
            this.clearBookingConversion();
        }
    },

    validateBookingDatalist(inputEl) {
        if (!inputEl) return true;
        inputEl.classList.remove('is-invalid');
        return true;
    },

    onBookingIdTypeChange() {
        const idType = this.value('bk-form-id-type') || 'cccd';
        const expire = document.getElementById('bk-form-id-expire');
        const label = document.getElementById('bk-form-id-expire-label');
        const expireGroup = expire?.closest('.bk-field');
        const addressSection = document.getElementById('bk-addr-section');
        const isForeign = ['passport', 'visa'].includes(idType);
        const noExpire = ['cmnd', 'gplx'].includes(idType);
        const crmLocked = Boolean(this.value('bk-form-guest-id'));
        if (expireGroup) expireGroup.style.display = noExpire ? 'none' : '';
        if (expire) {
            expire.disabled = noExpire;
            if (noExpire) {
                expire.value = '';
                expire.classList.remove('is-invalid');
            }
            if (!noExpire && typeof pmsSyncCCCDExpiryReadonly === 'function') {
                pmsSyncCCCDExpiryReadonly({
                    idTypeEl: document.getElementById('bk-form-id-type'),
                    birthEl: document.getElementById('bk-form-date-of-birth'),
                    expireEl: expire,
                    checkExpire: (input) => this.checkBookingIdExpire(input),
                });
            }
        }
        if (label) label.classList.toggle('bk-required', !noExpire);
        if (addressSection) addressSection.style.display = isForeign ? 'none' : '';
        ['bk-form-province', 'bk-form-district', 'bk-form-ward', 'bk-form-address'].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.disabled = isForeign;
            el.readOnly = isForeign || crmLocked;
            if (isForeign) {
                el.value = '';
                el.classList.remove('is-invalid');
            }
        });
        this.applyBookingCCCDExpiryFromBirth();
    },

    onBookingPaymentMethodChange() {
        const method = this.value('bk-form-payment-method') || 'Chi nhánh';
        const meta = document.getElementById('bk-form-payment-meta');
        const label = document.getElementById('bk-form-payment-meta-label');
        const ref = document.getElementById('bk-form-payment-ref');
        const needsMeta = ['Công ty', 'OTA', 'Chuyển khoản', 'Quẹt thẻ'].includes(method);
        if (meta) meta.classList.toggle('show', needsMeta);
        if (label) {
            if (method === 'Công ty') label.textContent = 'Tên công ty / người thanh toán';
            else if (method === 'OTA') label.textContent = 'Mã booking OTA';
            else if (method === 'Chuyển khoản') label.textContent = 'Mã giao dịch';
            else if (method === 'Quẹt thẻ') label.textContent = 'Mã giao dịch thẻ';
            else label.textContent = 'Mã tham chiếu';
        }
        if (!needsMeta && ref) ref.value = '';
        if (this.isOtaBookingForm()) this.applyOtaDepositLock();
        this.updateBookingPaymentMethodCards();
    },

    applyOtaDepositLock(forceLocked = null) {
        const locked = forceLocked === null ? this.isOtaBookingForm() : Boolean(forceLocked);
        const deposit = document.getElementById('bk-form-deposit');
        const method = document.getElementById('bk-form-payment-method');
        const ref = document.getElementById('bk-form-payment-ref');
        const paymentHint = document.getElementById('bk-form-payment-hint');
        if (locked) {
            if (deposit) {
                deposit.value = '0';
                deposit.disabled = true;
                deposit.classList.remove('is-invalid');
            }
            if (method) method.value = 'OTA';
            if (ref) ref.value = this.value('bk-form-booking-code');
            if (paymentHint) paymentHint.textContent = 'Đặt phòng OTA không nhập tiền cọc trước; mã OTA chỉ dùng để đối soát.';
        } else {
            if (deposit) deposit.disabled = false;
        }
    },

    selectBookingPaymentMethod(method) {
        if (this.isOtaBookingForm()) return;
        if (this.value('bk-form-booking-type') === 'COMPANY') return;
        const select = document.getElementById('bk-form-payment-method');
        if (select) select.value = method || 'Chi nhánh';
        this.updateBookingPaymentMethodCards();
        this.onBookingPaymentMethodChange();
    },

    updateBookingPaymentMethodCards() {
        const method = this.value('bk-form-payment-method') || 'Chi nhánh';
        const locked = this.isOtaBookingForm();
        
        // Update V2 cards (current UI)
        document.querySelectorAll('.bk-method-card-v2').forEach(card => {
            const active = card.dataset.method === method;
            card.classList.toggle('active', active);
            card.classList.toggle('disabled', locked);
        });

        // Update legacy cards for compatibility if they exist
        document.querySelectorAll('.bk-payment-method-card').forEach((card) => {
            const active = card.dataset.method === method;
            card.classList.toggle('active', active);
            card.classList.toggle('disabled', locked);
            card.setAttribute('aria-checked', active ? 'true' : 'false');
        });
    },

    onDepositInput(input) {
        this.state.depositSplitTouched = false;
        this.rebalanceDepositSplitAmounts();
        this.renderPaymentRoomSummary();
    },

    setDepositPreset(percent) {
        const total = this.getMoneyValue('bk-form-total');
        const depositEl = document.getElementById('bk-form-deposit');
        if (!depositEl) return;

        let amount = 0;
        if (percent === 100) amount = total;
        else if (percent === 50) amount = Math.round(total / 2);

        depositEl.value = amount ? amount.toLocaleString('vi-VN') : '0';
        
        // Update presets UI
        document.querySelectorAll('.bk-deposit-presets button').forEach(btn => {
            const isMatch = (percent === 100 && btn.textContent.includes('100')) ||
                            (percent === 50 && btn.textContent.includes('50')) ||
                            (percent === 0 && btn.textContent.includes('Hủy'));
            btn.classList.toggle('active', isMatch);
        });

        this.renderPaymentRoomSummary();
    },

    clearReservationValidation() {
        document.querySelectorAll('#bk-create-modal .is-invalid').forEach((el) => el.classList.remove('is-invalid'));
        this.text('bk-form-validation-hint', 'Sẵn sàng nhập thông tin khách.');
    },

    failReservationValidation(id, message) {
        const el = document.getElementById(id);
        if (el) {
            el.classList.add('is-invalid');
            el.focus();
        }
        this.text('bk-form-validation-hint', message);
        pmsToast(message, false);
        return false;
    },

    getBookingIdExpireRequired(idType = null) {
        const type = idType || this.value('bk-form-id-type') || 'cccd';
        return !['cmnd', 'gplx'].includes(type);
    },

    validateReservationGuestFields() {
        document.getElementById('bk-step-2')?.classList.toggle('bk-ota-guest-relaxed', this.value('bk-form-booking-type') === 'OTA');
        if (!this.value('bk-form-guest-name')) return this.failReservationValidation('bk-form-guest-name', 'Vui lòng nhập họ tên khách');
        return true;
    },

    validateReservationForm() {
        this.clearReservationValidation();

        if (!this.validateReservationGuestFields()) return false;
        if (!this.value('bk-form-booking-type')) return this.failReservationValidation('bk-form-booking-type', 'Vui lòng chọn nguồn đặt');
        if (!this.value('bk-form-status')) return this.failReservationValidation('bk-form-status', 'Vui lòng chọn trạng thái');
        const sourceExtra = this.getBookingSourceExtraConfig();
        if (sourceExtra && !this.value(sourceExtra.id)) return this.failReservationValidation(sourceExtra.id, sourceExtra.message);
        if (this.value('bk-form-booking-type') === 'OTA' && !this.value('bk-form-booking-code')) return this.failReservationValidation('bk-form-booking-code', 'Vui lòng nhập mã tham chiếu OTA');
        if (this.value('bk-form-booking-type') === 'COMPANY' && !this.value('bk-form-company-tax')) return this.failReservationValidation('bk-form-company-tax', 'Vui lòng nhập mã số thuế (MST)');
        if (this.isOtaBookingForm() && this.getMoneyValue('bk-form-total') <= 0) return this.failReservationValidation('bk-form-total', 'Vui lòng nhập tổng tiền OTA thực thu');
        if (!this.value('bk-form-guest-id') && !this.value('bk-form-guest-name')) return this.failReservationValidation('bk-form-guest-name', 'Vui lòng nhập họ tên khách');
        if ((!this.getRoomCartQuantity() && !this.state.editingBookingId) || !this.value('bk-form-check-in') || !this.value('bk-form-check-out')) {
            pmsToast('Thiếu ngày ở hoặc phòng đã chọn', false);
            return false;
        }
        return true;
    },

    validateReservationGuestStep() {
        this.clearReservationValidation();
        return this.validateReservationGuestFields();
    },

    getBookingAddressPayload() {
        const mode = this.getBookingAddressMode();
        const detail = this.value('bk-form-address');
        const province = this.value('bk-form-province');
        const district = this.value('bk-form-district');
        const ward = this.value('bk-form-ward');
        const newProvince = this.value('bk-form-new-province');
        const newWard = this.value('bk-form-new-ward');
        const fullAddress = mode === 'old'
            ? [detail, newWard || ward, newProvince || province].filter(Boolean).join(', ')
            : [detail, ward, district, province].filter(Boolean).join(', ');
        return {
            detail,
            fullAddress,
            raw: {
                address_detail: detail,
                address_type: mode,
                city: mode === 'old' ? newProvince : province,
                district: mode === 'old' ? '' : district,
                ward: mode === 'old' ? newWard : ward,
                old_city: mode === 'old' ? province : '',
                old_district: mode === 'old' ? district : '',
                old_ward: mode === 'old' ? ward : '',
            },
        };
    },

    getBookingDepositMeta() {
        const method = this.getEffectiveBookingPaymentMethod();
        const ref = this.isOtaBookingForm() ? this.value('bk-form-booking-code') : this.value('bk-form-payment-ref');
        if (method === 'Công ty') return { beneficiary: ref };
        if (method === 'OTA') return { ota_channel: this.value('bk-form-ota-channel'), ref_code: ref };
        if (method === 'Chuyển khoản') return { ref_code: ref };
        if (method === 'Quẹt thẻ') return { card_ref: ref };
        return {};
    },

    getBookingSourceLabel() {
        const select = document.getElementById('bk-form-booking-type');
        return select?.selectedOptions?.[0]?.textContent?.trim() || this.value('bk-form-booking-type') || 'Trực tiếp';
    },

    async submitCreate() {
        const btn = document.getElementById('bk-create-submit');
        if (!this.validateReservationForm()) return;
        await this.previewBookingPrice();
        const isEdit = Boolean(this.state.editingBookingId);
        this.applyOverCapacityStatusLock();
        const depositMethod = this.getEffectiveBookingPaymentMethod();
        const guestIdType = this.value('bk-form-id-type') || 'cccd';
        const depositMeta = this.getBookingDepositMeta();
        const addressPayload = this.getBookingAddressPayload();
        const totalPrice = Number(this.getMoneyValue('bk-form-total') || 0);
        const depositAmount = Number(this.getEffectiveBookingDeposit() || 0);
        const pmsReferenceTotal = Number(this.getPmsReferenceTotal() || 0);
        const manualTotalOverride = this.isBookingTotalManualOverride(totalPrice, pmsReferenceTotal);
        const selectedRoomTypeId = Number(this.value('bk-form-room-type'));
        const otaPricing = this.isOtaBookingForm()
            ? {
                ota_price_mode: 'manual_channel_total',
                ota_actual_total: Number.isFinite(totalPrice) ? totalPrice : 0,
                pms_reference_total: Number.isFinite(pmsReferenceTotal) ? pmsReferenceTotal : 0,
                ota_price_delta: Number.isFinite(totalPrice - pmsReferenceTotal) ? totalPrice - pmsReferenceTotal : 0,
                ota_group_total: Number.isFinite(totalPrice) ? totalPrice : 0,
                ota_room_count: this.getRoomCartQuantity() || 1,
            }
            : {};
        const payload = {
            booking_type: this.value('bk-form-booking-type') || 'DIRECT',
            booking_source: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-ota-channel') : '',
            external_id: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-booking-code') : '',
            reservation_status: this.value('bk-form-status') || 'CONFIRMED',
            branch_id: this.state.branchId,
            room_type_id: Number.isFinite(selectedRoomTypeId) && selectedRoomTypeId > 0 ? selectedRoomTypeId : null,
            guest_name: this.value('bk-form-guest-name'),
            guest_phone: this.value('bk-form-guest-phone'),
            guest_id: null,
            guest_email: this.value('bk-form-guest-email'),
            guest_cccd: this.value('bk-form-guest-cccd'),
            gender: this.value('bk-form-gender'),
            date_of_birth: this.value('bk-form-date-of-birth') || null,
            nationality: this.value('bk-form-nationality'),
            id_expire: this.value('bk-form-id-expire') || null,
            address: addressPayload.fullAddress,
            check_in: this.value('bk-form-check-in'),
            check_out: this.value('bk-form-check-out'),
            estimated_arrival: this.getBookingArrivalTime(),
            num_guests: Math.max(1, Number(this.value('bk-form-guests') || 1)),
            total_price: Number.isFinite(totalPrice) ? totalPrice : 0,
            deposit_amount: Number.isFinite(depositAmount) ? depositAmount : 0,
            payment_method: depositMethod,
            special_requests: this.value('bk-form-requests'),
            internal_notes: this.value('bk-form-notes'),
            raw_data: {
                source_ui: 'reservation_wizard',
                guest_id_type: guestIdType,
                deposit_type: depositMethod,
                deposit_meta: depositMeta,
                check_in_at: this.value('bk-form-check-in-at'),
                check_out_at: this.value('bk-form-check-out-at'),
                pricing_preview: this.state.bookingPricingPreview || null,
                manual_total_override: manualTotalOverride,
                manual_total_price: manualTotalOverride ? totalPrice : null,
                manual_total_reference: Number.isFinite(pmsReferenceTotal) ? pmsReferenceTotal : 0,
                manual_total_delta: manualTotalOverride && Number.isFinite(totalPrice - pmsReferenceTotal) ? totalPrice - pmsReferenceTotal : 0,
                source_label: this.getBookingSourceLabel(),
                booking_reference_code: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-booking-code') : '',
                ota_channel: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-ota-channel') : '',
                over_capacity_pending: this.hasOverCapacityCart(),
                ...otaPricing,
                sales_name: this.value('bk-form-booking-type') === 'SALES' ? this.value('bk-form-sales-name') : '',
                ...this.getBookingSourceExtraPayload(),
                ...addressPayload.raw,
            },
        };
        if (!isEdit) {
            const cart = this.getRoomCart().filter((item) => Number(item.room_type_id));
            const isOta = this.isOtaBookingForm();
            payload.room_items = cart.map((item) => {
                const unitTotal = Number(item.unit_total || 0);
                return {
                    room_type_id: Number(item.room_type_id),
                    quantity: Math.max(1, Number(item.quantity || 1)),
                    unit_total: isOta || manualTotalOverride || !Number.isFinite(unitTotal) ? 0 : unitTotal,
                    reference_unit_total: Number.isFinite(unitTotal) ? unitTotal : 0,
                    room_type: item.room_type,
                };
            });
            payload.raw_data.deposit_allocation = this.getDepositAllocationPayload();
            if (payload.room_items.length) {
                payload.room_type_id = Number(payload.room_items[0].room_type_id);
                payload.raw_data.room_items = payload.room_items;
                payload.raw_data.room_summary = payload.room_items.map((item) => `${item.room_type} x${item.quantity}`).join(', ');
            }
        }

        this.setButtonBusy(btn, true, isEdit ? 'Đang cập nhật...' : 'Đang lưu...');
        try {
            const url = isEdit ? `/api/pms/reservations/${this.state.editingBookingId}` : '/api/pms/reservations';
            const response = await pmsApi(url, {
                method: isEdit ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const createdQty = !isEdit ? this.getRoomCartQuantity() : 1;
            const responseData = this.apiData(response, null);
            const createdBooking = Array.isArray(responseData) ? responseData[0] : responseData;
            pmsToast(isEdit ? 'Đã cập nhật đặt phòng' : `Đã tạo ${createdQty || 1} phòng đặt`, true);
            this.closeCreate();
            this.resetCreateForm();
            await this.refreshAfterMutation({ availability: true });
            if (isEdit && createdBooking?.id) await this.openDetail(createdBooking.id);
            if (!isEdit && createdBooking?.id) await this.openDetail(createdBooking.id);
        } catch (err) {
            pmsToast(err.message || 'Không tạo được đặt phòng', false);
        } finally {
            this.setButtonBusy(btn, false, isEdit ? 'Lưu thay đổi' : 'Lưu đặt phòng');
        }
    },

    async submitReservationFromCi() {
        if (this.state.savingReservationFromCi) return;
        if (typeof pmsCiCollectReservationData !== 'function') {
            pmsToast('Không đọc được dữ liệu khách từ modal nhận phòng', false);
            return;
        }
        const ciData = pmsCiCollectReservationData();
        if (!ciData) return;

        const ctx = window._pmsCiReservationContext || {};
        const guest = ciData.guest || {};
        const checkInAt = ciData.check_in_at || `${ctx.check_in}T${ctx.estimated_arrival || '14:00'}`;
        const checkOutAt = ciData.check_out_at || `${ctx.check_out}T12:00`;
        const checkIn = String(checkInAt).slice(0, 10);
        const checkOut = String(checkOutAt).slice(0, 10);
        const arrival = String(checkInAt).includes('T') ? String(checkInAt).slice(11, 16) : (ctx.estimated_arrival || '14:00');
        const servicesTotal = (ciData.services || []).reduce((sum, item) => {
            return sum + (Number(item.price || 0) * Number(item.qty || 1));
        }, 0);
        const totalPrice = Number(ciData.pricing?.total || ctx.total_price || 0) + servicesTotal;
        const addressParts = [guest.address, guest.ward, guest.district, guest.city].filter(Boolean);
        const btn = document.querySelector('#ciModal .v-footer .v-btn.success');

        const payload = {
            booking_type: ctx.booking_type || this.value('bk-form-booking-type') || 'DIRECT',
            reservation_status: ctx.reservation_status || this.value('bk-form-status') || 'CONFIRMED',
            branch_id: ctx.branch_id || this.state.branchId,
            room_type_id: Number(ctx.room_type_id || this.value('bk-form-room-type')),
            guest_id: guest.id || null,
            guest_name: guest.full_name,
            guest_phone: guest.phone || '',
            guest_email: ciData.tax_contact || '',
            guest_cccd: guest.cccd || '',
            gender: guest.gender || '',
            date_of_birth: guest.birth_date || null,
            nationality: guest.nationality || 'VNM - Việt Nam',
            id_expire: guest.id_expire || null,
            address: addressParts.join(', '),
            check_in: checkIn,
            check_out: checkOut,
            estimated_arrival: arrival,
            num_guests: Math.max(1, (ciData.guests || []).length),
            total_price: totalPrice,
            deposit_amount: ciData.deposit.amount,
            payment_method: ciData.deposit.method,
            special_requests: ciData.notes || '',
            internal_notes: '',
            raw_data: {
                source_ui: 'checkin_modal_reservation',
                guest_id_type: guest.id_type || 'cccd',
                guest_notes: guest.notes || '',
                address_type: guest.address_type || 'new',
                city: guest.city || '',
                district: guest.district || '',
                ward: guest.ward || '',
                new_city: guest.new_city || '',
                new_ward: guest.new_ward || '',
                old_city: guest.old_city || '',
                old_district: guest.old_district || '',
                old_ward: guest.old_ward || '',
                require_invoice: ciData.require_invoice,
                tax_code: ciData.tax_code,
                tax_contact: ciData.tax_contact,
                deposit_type: ciData.deposit.method,
                deposit_meta: ciData.deposit.meta,
                extra_guests: (ciData.guests || []).slice(1),
                services: ciData.services || [],
                pricing_preview: ciData.pricing || null,
                check_in_at: checkInAt,
                check_out_at: checkOutAt,
                risk_confirmed: ciData.risk_confirmed,
            },
        };

        if (!payload.guest_name || !payload.room_type_id || !payload.check_in || !payload.check_out) {
            pmsToast('Vui lòng nhập đủ thông tin khách, ngày ở và loại phòng', false);
            return;
        }

        this.state.savingReservationFromCi = true;
        this.setButtonBusy(btn, true, 'Đang lưu đặt phòng...');
        try {
            const response = await pmsApi('/api/pms/reservations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const createdBooking = this.apiData(response, null);
            pmsToast('Đã tạo đặt phòng', true);
            window._pmsCiReservationMode = false;
            window._pmsCiReservationContext = null;
            if (typeof pmsCiCloseModal === 'function') pmsCiCloseModal();
            this.resetCreateForm();
            await this.refreshAfterMutation({ availability: true });
            if (createdBooking?.id) await this.openDetail(createdBooking.id);
        } catch (err) {
            pmsToast(err.message || 'Không tạo được đặt phòng', false);
        } finally {
            this.state.savingReservationFromCi = false;
            this.setButtonBusy(btn, false, 'Lưu đặt phòng');
        }
    },

    resetCreateForm() {
        [
            'bk-form-guest-id', 'bk-form-guest-name', 'bk-form-guest-phone',
            'bk-form-guest-email', 'bk-form-guest-cccd', 'bk-form-gender',
            'bk-form-date-of-birth', 'bk-form-id-expire', 'bk-form-address',
            'bk-form-total', 'bk-form-deposit',
            'bk-form-requests', 'bk-form-notes', 'bk-form-payment-ref', 'bk-form-sales-name',
            'bk-form-ota-channel', 'bk-form-booking-code', 'bk-form-zalo-name', 'bk-form-source-phone',
            'bk-form-company-name', 'bk-form-company-tax', 'bk-form-company-address',
            'bk-form-province', 'bk-form-district', 'bk-form-ward',
            'bk-form-new-province', 'bk-form-new-ward'
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el) {
                el.value = id === 'bk-form-total' || id === 'bk-form-deposit' ? '0' : '';
                if (id === 'bk-form-total') delete el.dataset.bkUserEdited;
            }
        });
        const nat = document.getElementById('bk-form-nationality');
        if (nat) nat.value = 'VNM - Việt Nam';
        const idType = document.getElementById('bk-form-id-type');
        if (idType) idType.value = 'cccd';
        const paymentMethod = document.getElementById('bk-form-payment-method');
        if (paymentMethod) paymentMethod.value = 'Chi nhánh';
        const deposit = document.getElementById('bk-form-deposit');
        if (deposit) deposit.disabled = false;
        const guests = document.getElementById('bk-form-guests');
        if (guests) guests.value = '2';
        const status = document.getElementById('bk-form-status');
        if (status) status.value = 'CONFIRMED';
        this.setStatus('CONFIRMED');
        const bookingType = document.getElementById('bk-form-booking-type');
        if (bookingType) bookingType.value = 'DIRECT';
        this.state.editingBookingId = null;
        this.state.selectedRoomType = null;
        this.state.roomCart = [];
        this.state.depositAllocationMode = 'split';
        this.state.depositTargetRoomKey = '';
        this.state.depositSplitAmounts = {};
        this.state.depositSplitTouched = false;
        this.renderRoomCart();
        this.setCreateMode(false);
        this.setBookingCrmFieldsLocked(false);
        this.closeCrmSearchPopup();
        this.switchBookingAddressMode('new', false);
        this.bindFormDateDefaults();
        this.setWizardStep(1);
        this.onBookingIdTypeChange();
        this.onBookingTypeChange();
        this.onBookingPaymentMethodChange();
        this.previewBookingPrice();
        this.clearReservationValidation();
    },

    onCrmSearchKey(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.searchCrmGuests();
        }
    },

    async searchCrmGuests() {
        const q = (this.value('bk-crm-search-input') || '').trim();
        if (!q || q.length < 5) {
            pmsToast('Nhập ít nhất 5 ký tự để tìm khách CRM', false);
            return;
        }
        const requestId = (this.state.crmSearchRequestId || 0) + 1;
        this.state.crmSearchRequestId = requestId;
        this.state.crmSearchCache = this.state.crmSearchCache || {};
        const cacheKey = q.toLowerCase();
        const renderGuests = (guests) => {
            if (requestId !== this.state.crmSearchRequestId) return;
            if (!guests.length) {
                this.closeCrmSearchPopup();
                pmsToast('Không tìm thấy khách CRM phù hợp', false);
                return;
            }
            this.showCrmSearchPopup(guests);
        };
        if (this.state.crmSearchCache[cacheKey]) {
            renderGuests(this.state.crmSearchCache[cacheKey]);
            return;
        }
        try {
            const data = this.apiData(await pmsApi(`/api/pms/crm/guests/search?q=${encodeURIComponent(q)}&page_size=8`), {});
            const guests = data.items || data.guests || [];
            this.state.crmSearchCache[cacheKey] = guests;
            renderGuests(guests);
        } catch (err) {
            if (requestId === this.state.crmSearchRequestId) {
                this.closeCrmSearchPopup();
                pmsToast(err.message || 'Lỗi tìm khách CRM', false);
            }
        }
    },

    closeCrmSearchPopup() {
        const modal = document.getElementById('bk-crm-results-modal');
        if (!modal) return;
        modal.style.opacity = '0';
        modal.classList.remove('bk-crm-popup-show');
        setTimeout(() => modal.remove(), 180);
    },

    async selectCrmSearchResult(index) {
        const guests = this.state.crmSearchResults || [];
        const guest = guests[index];
        if (!guest) return;
        this.closeCrmSearchPopup();
        await this.selectCrmGuest(guest);
    },

    showCrmSearchPopup(guests) {
        this.state.crmSearchResults = guests;
        const existing = document.getElementById('bk-crm-results-modal');
        if (existing) existing.remove();
        const resultsHtml = guests.map((g, idx) => {
            const name = this.escape(g.full_name || 'Khách');
            const meta = this.escape([g.phone, g.cccd, g.email].filter(Boolean).join(' • ') || 'Chưa có định danh');
            const tier = this.escape(g.tier_display || g.tier || 'BASIC');
            const initials = this.escape(String(g.full_name || '?').split(' ').map((w) => w[0]).join('').slice(-2).toUpperCase());
            const risks = [
                g.is_blacklisted ? '<span class="bk-crm-popup-risk danger">Blacklist</span>' : '',
                g.has_unpaid_debt ? `<span class="bk-crm-popup-risk warn">Nợ ${pmsMoney(g.unpaid_debt_amount || 0)}</span>` : '',
            ].join('');
            return `
                <button class="bk-crm-popup-card" type="button" onclick="BookingHub.selectCrmSearchResult(${idx})">
                    <span class="bk-crm-popup-avatar">${initials}</span>
                    <span class="bk-crm-popup-info">
                        <strong>${name} ${risks}</strong>
                        <small>${meta}</small>
                    </span>
                    <span class="bk-crm-popup-tier">${tier}</span>
                </button>
            `;
        }).join('');
        const modal = document.createElement('div');
        modal.id = 'bk-crm-results-modal';
        modal.innerHTML = `
            <style>
                #bk-crm-results-modal {
                    position: fixed; inset: 0; z-index: 100004;
                    display: flex; align-items: center; justify-content: center;
                    padding: 18px; background: rgba(15, 23, 42, .6);
                    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
                    opacity: 0; transition: opacity .18s ease;
                }
                .bk-crm-popup {
                    width: min(560px, 94vw); max-height: 72vh; overflow: hidden;
                    background: #fff; border-radius: 16px; display: flex; flex-direction: column;
                    box-shadow: 0 25px 60px rgba(15, 23, 42, .28);
                    transform: translateY(12px); transition: transform .22s ease;
                }
                #bk-crm-results-modal.bk-crm-popup-show .bk-crm-popup { transform: translateY(0); }
                .bk-crm-popup-head {
                    display: flex; align-items: center; gap: 14px;
                    padding: 18px 20px 14px; border-bottom: 1px solid #e2e8f0;
                }
                .bk-crm-popup-icon {
                    width: 42px; height: 42px; border-radius: 12px; flex: 0 0 auto;
                    display: grid; place-items: center; color: #2563eb;
                    background: linear-gradient(135deg, #dbeafe, #bfdbfe);
                }
                .bk-crm-popup-head h5 { margin: 0; font-size: 16px; color: #0f172a; font-weight: 800; }
                .bk-crm-popup-head p { margin: 3px 0 0; font-size: 12.5px; color: #64748b; }
                .bk-crm-popup-close {
                    margin-left: auto; width: 36px; height: 36px; border: 0; border-radius: 10px;
                    background: transparent; color: #94a3b8; cursor: pointer;
                }
                .bk-crm-popup-close:hover { background: #f1f5f9; color: #475569; }
                .bk-crm-popup-list { overflow-y: auto; padding: 12px 14px 14px; }
                .bk-crm-popup-card {
                    width: 100%; display: flex; align-items: center; gap: 12px;
                    padding: 13px 14px; margin-bottom: 10px; border: 1px solid #e2e8f0;
                    border-radius: 12px; background: #fff; text-align: left; cursor: pointer;
                    transition: background .15s, border-color .15s, transform .15s, box-shadow .15s;
                }
                .bk-crm-popup-card:last-child { margin-bottom: 0; }
                .bk-crm-popup-card:hover {
                    border-color: #93c5fd; background: linear-gradient(135deg, #f0f9ff, #eff6ff);
                    box-shadow: 0 4px 12px rgba(37, 99, 235, .1); transform: translateY(-1px);
                }
                .bk-crm-popup-avatar {
                    width: 42px; height: 42px; border-radius: 12px; flex: 0 0 auto;
                    display: grid; place-items: center; background: #2563eb; color: #fff;
                    font-size: 13px; font-weight: 800;
                }
                .bk-crm-popup-info { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
                .bk-crm-popup-info strong {
                    color: #0f172a; font-size: 14px; font-weight: 750;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                }
                .bk-crm-popup-info small {
                    color: #64748b; font-size: 12px;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                }
                .bk-crm-popup-tier, .bk-crm-popup-risk {
                    flex: 0 0 auto; border-radius: 999px; padding: 3px 8px;
                    font-size: 10px; font-weight: 800;
                }
                .bk-crm-popup-tier { background: #ecfeff; color: #0e7490; }
                .bk-crm-popup-risk { margin-left: 6px; }
                .bk-crm-popup-risk.danger { background:#fee2e2; color:#b91c1c; }
                .bk-crm-popup-risk.warn { background:#fef3c7; color:#92400e; }
            </style>
            <div class="bk-crm-popup" role="dialog" aria-modal="true" aria-label="Kết quả tìm khách CRM">
                <div class="bk-crm-popup-head">
                    <div class="bk-crm-popup-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                        </svg>
                    </div>
                    <div>
                        <h5>Tìm thấy ${guests.length} khách hàng</h5>
                        <p>Chọn khách hàng để điền thông tin vào phiếu đặt phòng</p>
                    </div>
                    <button class="bk-crm-popup-close" type="button" onclick="BookingHub.closeCrmSearchPopup()" title="Đóng">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="bk-crm-popup-list">${resultsHtml}</div>
            </div>
        `;
        document.body.appendChild(modal);
        requestAnimationFrame(() => {
            modal.style.opacity = '1';
            modal.classList.add('bk-crm-popup-show');
        });
        modal.addEventListener('click', (event) => {
            if (event.target === modal) this.closeCrmSearchPopup();
        });
        const escHandler = (event) => {
            if (event.key === 'Escape') {
                this.closeCrmSearchPopup();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    },

    setBookingCrmFieldsLocked(locked) {
        [
            'bk-form-guest-name',
            'bk-form-guest-cccd', 'bk-form-id-type', 'bk-form-gender',
            'bk-form-date-of-birth', 'bk-form-nationality',
            'bk-form-province', 'bk-form-district', 'bk-form-ward', 'bk-form-address'
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.readOnly = Boolean(locked);
            if (el.tagName === 'SELECT') el.disabled = Boolean(locked);
            el.classList.toggle('bk-crm-locked', Boolean(locked));
        });
        document.querySelectorAll('input[name="bk-area"]').forEach((radio) => {
            radio.disabled = Boolean(locked);
        });
    },

    splitBookingAddressFallback(address) {
        const parts = String(address || '').split(',').map((p) => p.trim()).filter(Boolean);
        if (parts.length < 2) return { detail: address || '', ward: '', district: '', city: '' };
        if (parts.length === 2) return { detail: parts[0], ward: '', district: '', city: parts[1] };
        if (parts.length === 3) return { detail: parts[0], ward: parts[1], district: '', city: parts[2] };
        return {
            detail: parts.slice(0, parts.length - 3).join(', '),
            ward: parts[parts.length - 3] || '',
            district: parts[parts.length - 2] || '',
            city: parts[parts.length - 1] || '',
        };
    },

    getBookingGuestAddressDetail(guest, fallback) {
        const rawAddress = String(guest.address || '').trim();
        if (!rawAddress) return fallback.detail || '';
        const hasStructuredAddress = Boolean(
            guest.city || guest.district || guest.ward ||
            guest.old_city || guest.old_district || guest.old_ward
        );
        if (rawAddress.includes(',') && (hasStructuredAddress || rawAddress === String(guest.default_address || '').trim())) {
            return fallback.detail || '';
        }
        return rawAddress;
    },

    async fillBookingAddressFromGuest(guest) {
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.value = value || '';
        };
        const fallback = this.splitBookingAddressFallback(guest.default_address || guest.address || '');
        const addressDetail = this.getBookingGuestAddressDetail(guest, fallback);
        const mode = guest.address_type || (guest.old_city || guest.old_district || guest.old_ward ? 'old' : 'new');
        const currentMode = this.getBookingAddressMode();
        const provinceEl = document.getElementById('bk-form-province');
        const districtEl = document.getElementById('bk-form-district');
        const wardEl = document.getElementById('bk-form-ward');
        if (currentMode !== mode) await this.switchBookingAddressMode(mode, false);
        else {
            ['bk-form-province', 'bk-form-district', 'bk-form-ward'].forEach((id) => set(id, ''));
            this.populateBookingDatalist('bk-dl-district', []);
            this.populateBookingDatalist('bk-dl-ward', []);
            this.clearBookingConversion();
        }

        if (mode === 'old') {
            set('bk-form-address', addressDetail);
            set('bk-form-province', guest.old_city || fallback.city || '');
            set('bk-form-district', guest.old_district || fallback.district || '');
            set('bk-form-ward', guest.old_ward || fallback.ward || '');
            set('bk-form-new-province', guest.city || '');
            set('bk-form-new-ward', guest.ward || '');
            if (provinceEl?.value) await this.onBookingProvinceChange(provinceEl, true);
            if (districtEl?.value) await this.onBookingDistrictChange(districtEl, true);
            if (wardEl?.value) this.onBookingWardChange(wardEl);
            return;
        }

        set('bk-form-address', addressDetail);
        set('bk-form-province', guest.city || fallback.city || '');
        set('bk-form-district', guest.district || fallback.district || '');
        set('bk-form-ward', guest.ward || fallback.ward || '');
        if (provinceEl?.value) this.onBookingProvinceChange(provinceEl, true);
    },

    async fillBookingAddressFromScan(rawAddress, cardType = 'CCCD_CU') {
        if (typeof pmsMatchAddressToForm === 'function') {
            await pmsMatchAddressToForm(rawAddress, 'bk', cardType);
            if (typeof pmsShowAddressValidationIssues === 'function') pmsShowAddressValidationIssues('bk');
            return;
        }
        const address = document.getElementById('bk-form-address');
        if (address) address.value = rawAddress || '';
    },

    async selectCrmGuest(guest) {
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.value = value || '';
        };
        const requestId = (this.state.crmSelectRequestId || 0) + 1;
        this.state.crmSelectRequestId = requestId;
        this.setBookingCrmFieldsLocked(false);
        set('bk-form-guest-id', guest.id);
        set('bk-form-guest-name', guest.full_name);
        set('bk-form-guest-phone', guest.phone);
        set('bk-form-guest-email', guest.email);
        set('bk-form-guest-cccd', guest.cccd);
        set('bk-form-id-type', guest.id_type || 'cccd');
        set('bk-form-gender', guest.gender);
        set('bk-form-date-of-birth', guest.birth_date || guest.date_of_birth);
        set('bk-form-nationality', guest.nationality || 'VNM - Việt Nam');
        if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(document.getElementById('bk-form-id-expire'), guest.id_expire);
        else set('bk-form-id-expire', guest.id_expire);
        await this.fillBookingAddressFromGuest(guest);
        if (requestId !== this.state.crmSelectRequestId) return;
        this.onBookingIdTypeChange();
        this.setBookingCrmFieldsLocked(true);
        this.clearReservationValidation();
        this.closeCrmSearchPopup();
        const guestName = guest.full_name || 'Khách';
        const guestTier = guest.tier_display || guest.tier || 'BASIC';
        pmsToast(`Đã chọn CRM: ${guestName} • ${guestTier}`, true);
    },

    scanBookingGuest() {
        if (typeof openScanModal !== 'function') {
            pmsToast('Modal quét CCCD chưa sẵn sàng', false);
            return;
        }
        openScanModal(async (parsed) => {
            await this.fillBookingGuestFromScan(parsed);
            pmsToast(`Đã quét: ${parsed.name || parsed.id_number || parsed.old_id || ''}`, true);
        });
    },

    async fillBookingGuestFromScan(parsed) {
        if (!parsed?.is_valid) return;

        const isCmnd = parsed.card_type === 'CMND';
        const idValue = isCmnd
            ? (parsed.old_id || parsed.id_number || parsed.cccd || '')
            : (parsed.id_number || parsed.cccd || '');
        const normalizedId = String(idValue || '').trim().toUpperCase();

        if (normalizedId && normalizedId.length >= 3) {
            try {
                const searchRes = await pmsApi(`/api/pms/crm/guests/search?cccd=${encodeURIComponent(normalizedId)}`);
                const guests = searchRes?.guests || searchRes?.items || [];
                if (guests.length > 0) {
                    await this.selectCrmGuest(guests[0]);
                    const idEl = document.getElementById('bk-form-guest-cccd');
                    if (idEl) idEl.value = normalizedId;
                    return;
                }
            } catch (err) {
                console.warn('[BookingHub] Scan CRM lookup failed, filling from scan data:', err);
            }
        }

        this.setBookingCrmFieldsLocked(false);
        const set = (id, value) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.value = value || '';
            el.classList.remove('is-invalid');
        };
        set('bk-form-guest-id', '');
        set('bk-form-guest-cccd', normalizedId);
        set('bk-form-id-type', isCmnd ? 'cmnd' : 'cccd');
        set('bk-form-guest-name', typeof pmsTitleCase === 'function' ? pmsTitleCase(parsed.name || '') : (parsed.name || ''));
        set('bk-form-gender', parsed.gender || '');
        if (parsed.dob && typeof pmsScanDateToISO === 'function') {
            set('bk-form-date-of-birth', pmsScanDateToISO(parsed.dob));
            this.checkBookingBirth(document.getElementById('bk-form-date-of-birth'));
        }
        if (parsed.expiry_date) {
            const expireEl = document.getElementById('bk-form-id-expire');
            if (parsed.expiry_date === 'Không thời hạn' && typeof pmsSetCCCDPermanentExpiry === 'function') {
                pmsSetCCCDPermanentExpiry(expireEl);
            } else if (typeof pmsScanDateToISO === 'function') {
                if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(expireEl, parsed.expiry_date);
                else set('bk-form-id-expire', pmsScanDateToISO(parsed.expiry_date));
                this.checkBookingIdExpire(expireEl);
            }
        }
        set('bk-form-nationality', 'VNM - Việt Nam');
        await this.fillBookingAddressFromScan(parsed.address, parsed.card_type || 'CCCD_CU');
        this.onBookingIdTypeChange();
        this.clearReservationValidation();

        this.closeCrmSearchPopup();
        document.getElementById('bk-form-guest-phone')?.focus();
    },

    resetBookingGuestFields() {
        this.state.crmSelectRequestId = (this.state.crmSelectRequestId || 0) + 1;
        this.closeCrmSearchPopup();
        this.setBookingCrmFieldsLocked(false);
        [
            'bk-form-guest-id', 'bk-crm-search-input', 'bk-form-guest-name', 'bk-form-guest-phone',
            'bk-form-guest-email', 'bk-form-guest-cccd', 'bk-form-gender',
            'bk-form-date-of-birth', 'bk-form-id-expire', 'bk-form-address',
            'bk-form-guest-notes', 'bk-form-province', 'bk-form-district',
            'bk-form-ward', 'bk-form-new-province', 'bk-form-new-ward'
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const nat = document.getElementById('bk-form-nationality');
        if (nat) nat.value = 'VNM - Việt Nam';
        const idType = document.getElementById('bk-form-id-type');
        if (idType) idType.value = 'cccd';
        this.switchBookingAddressMode('new', false);
        this.setBookingCrmFieldsLocked(false);
        this.onBookingIdTypeChange();
        this.clearReservationValidation();
    },

    clearSelectedGuest(showToast = true) {
        this.resetBookingGuestFields();
        this.setBookingCrmFieldsLocked(false);
        this.closeCrmSearchPopup();
        if (showToast) pmsToast('Chuyển sang tạo khách mới', true);
    }
});
