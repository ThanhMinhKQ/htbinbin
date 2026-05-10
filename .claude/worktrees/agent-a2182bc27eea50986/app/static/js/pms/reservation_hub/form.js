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
            this.state.selectedRoomType = booking.room_type_id ? {
                room_type_id: booking.room_type_id,
                room_type: booking.room_type,
                base_price: booking.total_price / Math.max(1, this.dateDiff(booking.check_in, booking.check_out)),
                available: 1,
                max_guests: booking.num_guests || 1,
            } : null;
            this.state.roomCart = this.state.selectedRoomType ? [{
                ...this.state.selectedRoomType,
                quantity: 1,
                unit_total: Number(booking.total_price || 0),
            }] : [];
            this.fillBookingForm(booking);
            this.setWizardStep(2);
            this.showModal('bk-create-modal');
        } catch (err) {
            pmsToast(err.message || 'Không tải được đặt phòng để sửa', false);
        }
    },

    fillBookingForm(booking) {
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
        set('bk-form-id-expire', booking.id_expire || '');
        set('bk-form-address', booking.address || '');
        const raw = booking.raw_data || {};
        const otaChannel = booking.booking_type === 'OTA'
            ? (booking.booking_source || raw.ota_channel || '').replace(/^G2J$/i, 'Go2Joy')
            : '';
        const addressMode = raw.address_type || 'new';
        this.switchBookingAddressMode(addressMode, false).then(async () => {
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
        });
        set('bk-form-check-in', booking.check_in || '');
        set('bk-form-check-out', booking.check_out || '');
        set('bk-form-check-in-at', booking.raw_data?.check_in_at || `${booking.check_in || ''}T${(booking.estimated_arrival || '14:00').slice(0, 5)}`);
        set('bk-form-check-out-at', booking.raw_data?.check_out_at || `${booking.check_out || ''}T12:00`);
        this.syncBookingDateHiddenFields();
        set('bk-form-room-type', booking.room_type_id || '');
        set('bk-form-status', ['PENDING', 'CONFIRMED'].includes(booking.reservation_status) ? booking.reservation_status : 'PENDING');
        set('bk-form-booking-type', booking.booking_type || 'DIRECT');
        set('bk-form-ota-channel', otaChannel);
        set('bk-form-sales-name', booking.raw_data?.sales_name || '');
        set('bk-form-booking-code', booking.external_id || booking.raw_data?.booking_code || booking.raw_data?.source_booking_code || '');
        if (booking.booking_type === 'OTA') this.ensureOtaChannelOption(otaChannel);
        set('bk-form-zalo-name', booking.raw_data?.zalo_name || '');
        set('bk-form-source-phone', booking.raw_data?.source_phone || '');
        set('bk-form-guests', booking.num_guests || 1);
        set('bk-form-total', Math.round(Number(booking.total_price || 0)));
        set('bk-form-deposit', Math.round(Number(booking.deposit_amount || 0)));
        set('bk-form-payment-method', booking.deposit_type || booking.payment_method || 'Chi nhánh');
        set('bk-form-payment-ref', booking.deposit_meta?.ref_code || booking.deposit_meta?.beneficiary || booking.deposit_meta?.card_ref || '');
        set('bk-form-requests', booking.special_requests || '');
        set('bk-form-notes', booking.internal_notes || '');
        this.onBookingIdTypeChange();
        this.onBookingTypeChange();
        this.onBookingPaymentMethodChange();
        this.previewBookingPrice();
        const selected = document.getElementById('bk-selected-guest');
        if (selected && booking.guest_id) {
            selected.style.display = 'block';
            selected.textContent = `Đã chọn CRM: ${booking.guest_name || 'Khách'} • ${booking.guest_tier || 'BASIC'}`;
        }
        this.setBookingCrmFieldsLocked(Boolean(booking.guest_id));
        document.getElementById('bk-step-2')?.classList.toggle('bk-ota-guest-relaxed', booking.booking_type === 'OTA');
    },

    ensureOtaChannelOption(value) {
        const channel = String(value || '').trim();
        const select = document.getElementById('bk-form-ota-channel');
        if (!channel || !select) return;
        const exists = Array.from(select.options).some((option) => option.value === channel);
        if (!exists) {
            const option = document.createElement('option');
            option.value = channel;
            option.textContent = channel;
            select.appendChild(option);
        }
        select.value = channel;
    },

    onBookingTypeChange() {
        const type = this.value('bk-form-booking-type');
        const status = document.getElementById('bk-form-status');
        const infoGrid = document.querySelector('#bk-step-1 .bk-room-meta-row');
        const extraMap = {
            SALES: ['bk-form-sales-name-wrap', 'bk-form-sales-name'],
            OTA: ['bk-form-ota-channel-wrap', 'bk-form-ota-channel'],
            ZALO: ['bk-form-zalo-name-wrap', 'bk-form-zalo-name'],
            PHONE: ['bk-form-source-phone-wrap', 'bk-form-source-phone'],
        };
        Object.entries(extraMap).forEach(([sourceType, [wrapId, inputId]]) => {
            const wrap = document.getElementById(wrapId);
            const input = document.getElementById(inputId);
            const active = type === sourceType;
            if (wrap) wrap.style.display = active ? '' : 'none';
            if (!active && input) {
                input.value = '';
                input.classList.remove('is-invalid');
            }
        });
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
        if (infoGrid) infoGrid.classList.toggle('has-source-extra', Object.prototype.hasOwnProperty.call(extraMap, type) || showReferenceCode);
        if (!status || this.state.editingBookingId) return;
        status.value = 'PENDING';
    },

    getBookingSourceExtraConfig() {
        const type = this.value('bk-form-booking-type');
        const config = {
            SALES: { id: 'bk-form-sales-name', key: 'sales_name', message: 'Vui lòng nhập tên Sales' },
            OTA: { id: 'bk-form-ota-channel', key: 'ota_channel', message: 'Vui lòng nhập kênh OTA' },
            ZALO: { id: 'bk-form-zalo-name', key: 'zalo_name', message: 'Vui lòng nhập tên Zalo' },
            PHONE: { id: 'bk-form-source-phone', key: 'source_phone', message: 'Vui lòng nhập số điện thoại nguồn' },
        };
        return config[type] || null;
    },

    getBookingSourceExtraPayload() {
        const cfg = this.getBookingSourceExtraConfig();
        return cfg ? { [cfg.key]: this.value(cfg.id) } : {};
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
        try {
            const data = this.apiData(await pmsApi(`/api/pms/inventory/availability?${params}`), []);
            container.dataset.count = String(data.length);
            if (!data.length) {
                container.innerHTML = '<div class="bk-avail-empty">Chưa có loại phòng nào</div>';
                return;
            }
            const nights = Math.max(1, this.dateDiff(ci, co));
            container.innerHTML = data.map(rt => this._renderAvailCard(rt, ci, co, nights, 'toolbar')).join('');
            this.updateAvailabilityCardPrices(
                container,
                data,
                this.value('bk-avail-ci-at') || `${ci}T14:00`,
                this.value('bk-avail-co-at') || `${co}T12:00`
            );
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
            this.updateAvailabilityCardPrices(container, data, this.value('bk-form-check-in-at'), this.value('bk-form-check-out-at'));
        } catch (err) {
            container.innerHTML = `<div class="bk-avail-empty">${this.escape(err.message || 'Lỗi tải tồn phòng')}</div>`;
        }
    },

    _renderAvailCard(rt, ci, co, nights, context) {
        const soldOut = rt.stop_sell;
        const low = rt.low_inventory;
        const fillClass = soldOut ? 'danger' : low ? 'warn' : '';
        const totalRooms = rt.available_rooms + 3;
        const usedPct = soldOut ? 100 : Math.min(95, Math.round(((totalRooms - rt.available_rooms) / totalRooms) * 100));
        const selected = this.getRoomCart().some((item) => Number(item.room_type_id) === Number(rt.room_type_id));
        const selectedQty = this.getRoomCart().find((item) => Number(item.room_type_id) === Number(rt.room_type_id))?.quantity || 1;
        const maxGuests = Number(rt.max_guests || rt.max_occupancy || 2);
        const roomTypeArg = encodeURIComponent(rt.room_type || '');
        const fallback = Math.round(Number(rt.base_price || 0) * nights);
        const clickFn = context === 'toolbar'
            ? `BookingHub.bookFromAvailability('${ci}','${co}',${rt.room_type_id},decodeURIComponent('${roomTypeArg}'),${rt.base_price},${rt.available_rooms},${maxGuests})`
            : `BookingHub.selectWizardRoom(${rt.room_type_id},decodeURIComponent('${roomTypeArg}'),${rt.base_price},${rt.available_rooms},${maxGuests})`;

        return `
            <div class="bk-avail-card ${soldOut ? 'sold-out' : ''} ${low ? 'low-inventory' : ''} ${selected ? 'selected' : ''}"
                 data-room-type-id="${rt.room_type_id}"
                 onclick="${soldOut ? '' : clickFn}">
                <strong>${this.escape(rt.room_type)}</strong>
                <div class="bk-avail-progress">
                    <div class="bk-avail-fill ${fillClass}" style="width:${usedPct}%"></div>
                </div>
                <div class="bk-avail-meta">
                    <span>${soldOut ? 'Hết phòng' : `Còn ${rt.available_rooms} phòng`}</span>
                    <span class="bk-money is-loading" data-fallback="${fallback}">Đang tính...</span>
                </div>
                ${!soldOut ? '<div class="bk-avail-cta">' + (context === 'toolbar' ? 'Đặt phòng' : (selected ? `Đã chọn x${selectedQty}` : 'Thêm')) + '</div>' : ''}
            </div>
        `;
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
        this.state.selectedRoomType = { room_type_id: roomTypeId, room_type: roomTypeName, base_price: basePrice, available, max_guests: maxGuests };
        this.addRoomCartItem(roomTypeId, roomTypeName, basePrice, available, maxGuests);
        const select = document.getElementById('bk-form-room-type');
        if (select) {
            select.innerHTML = `<option value="${roomTypeId}" selected>${this.escape(roomTypeName)}</option>`;
            select.value = roomTypeId;
        }
        const guests = document.getElementById('bk-form-guests');
        if (guests) guests.max = String(this.getRoomCartMaxGuests() || maxGuests || available || 1);
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
        const maxQty = Math.max(1, Number(available || existing?.available || 1));
        if (existing) {
            if (Number(existing.quantity || 0) >= maxQty) {
                pmsToast(`Chỉ còn ${maxQty} phòng loại này`, false);
            }
            existing.quantity = Math.min(maxQty, Number(existing.quantity || 0) + 1);
            existing.available = maxQty;
            existing.base_price = Number(basePrice || existing.base_price || 0);
            existing.max_guests = Number(maxGuests || existing.max_guests || 2);
        } else {
            cart.push({
                room_type_id: id,
                room_type: roomTypeName,
                base_price: Number(basePrice || 0),
                available: maxQty,
                max_guests: Number(maxGuests || 2),
                quantity: 1,
                unit_total: 0,
            });
        }
        this.renderRoomCart();
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
        this.previewBookingPrice();
        this.updateSelectedAvailabilityCard('bk-wizard-avail-cards');
    },

    removeRoomCartItem(roomTypeId) {
        this.state.roomCart = this.getRoomCart().filter((item) => Number(item.room_type_id) !== Number(roomTypeId));
        this.state.selectedRoomType = this.getRoomCart()[0] || null;
        const select = document.getElementById('bk-form-room-type');
        if (select) select.value = this.state.selectedRoomType?.room_type_id || '';
        this.renderRoomCart();
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

    renderRoomCart() {
        const cart = this.getRoomCart();
        const wrap = document.getElementById('bk-room-cart');
        const itemsEl = document.getElementById('bk-room-cart-items');
        const totalEl = document.getElementById('bk-room-cart-total');
        if (!wrap || !itemsEl || !totalEl) return;
        const totalQty = this.getRoomCartQuantity();
        wrap.style.display = totalQty ? 'block' : 'none';
        totalEl.textContent = `${totalQty} phòng`;
        itemsEl.innerHTML = cart.map((item) => {
            const qty = Number(item.quantity || 0);
            const unitTotal = Number(item.unit_total || item.base_price || 0);
            return `
                <div class="bk-room-cart-row" data-room-type-id="${item.room_type_id}">
                    <div class="bk-room-cart-main">
                        <strong>${this.escape(item.room_type || 'Loại phòng')}</strong>
                        <span>Còn ${Number(item.available || 0)} phòng • Tối đa ${Number(item.max_guests || 1) * qty} khách</span>
                    </div>
                    <div class="bk-room-cart-qty">
                        <button type="button" onclick="BookingHub.changeRoomCartQty(${item.room_type_id}, -1)">−</button>
                        <span>${qty}</span>
                        <button type="button" onclick="BookingHub.changeRoomCartQty(${item.room_type_id}, 1)">+</button>
                    </div>
                    <div class="bk-room-cart-money">${pmsMoney(unitTotal * qty)}</div>
                    <button class="bk-mini-btn danger" type="button" onclick="BookingHub.removeRoomCartItem(${item.room_type_id})">Xóa</button>
                </div>
            `;
        }).join('');
        const guests = document.getElementById('bk-form-guests');
        if (guests) guests.max = String(this.getRoomCartMaxGuests() || 1);
        this.renderPaymentRoomSummary();
    },

    renderPaymentRoomSummary() {
        const el = document.getElementById('bk-payment-room-summary');
        if (!el) return;
        const cart = this.getRoomCart();
        if (!cart.length) {
            el.innerHTML = '<div class="bk-payment-empty">Chưa chọn phòng.</div>';
            return;
        }
        const totalQty = this.getRoomCartQuantity();
        const totalGuests = this.getRoomCartMaxGuests();
        const totalMoney = cart.reduce((sum, item) => {
            return sum + Number(item.unit_total || item.base_price || 0) * Number(item.quantity || 1);
        }, 0);
        const deposit = Number(this.value('bk-form-deposit') || 0);
        const isOta = this.isOtaBookingForm();
        const balance = Math.max(0, totalMoney - deposit);
        const depositPct = totalMoney > 0 ? Math.min(100, Math.round((deposit / totalMoney) * 100)) : 0;
        const rows = cart.map((item) => {
            const qty = Number(item.quantity || 1);
            const unit = Number(item.unit_total || item.base_price || 0);
            return `
                <div class="bk-payment-room-row">
                    <div class="bk-payment-room-name">
                        <strong>${this.escape(item.room_type || 'Loại phòng')}</strong>
                        <span>${qty} phòng x ${pmsMoney(unit)}</span>
                    </div>
                    <strong>${pmsMoney(unit * qty)}</strong>
                </div>
            `;
        }).join('');
        el.innerHTML = `
            <div class="bk-payment-kpis">
                <div>
                    <span>Tổng lưu trú</span>
                    <strong>${pmsMoney(totalMoney)}</strong>
                    <small>${totalQty} phòng • sức chứa ${totalGuests} khách</small>
                </div>
                <div>
                    <span>Đã đặt cọc</span>
                    <strong>${pmsMoney(deposit)}</strong>
                    <small>${depositPct}% tổng tiền</small>
                </div>
                <div>
                    <span>Còn phải thu</span>
                    <strong>${pmsMoney(balance)}</strong>
                    <small>Sau khi trừ cọc</small>
                </div>
            </div>
            <div class="bk-payment-progress">
                <div style="width:${depositPct}%"></div>
            </div>
            <div class="bk-payment-room-list">${rows}</div>
            <div class="bk-payment-note">${isOta ? 'Booking OTA không nhập cọc trước; tiền OTA được xử lý theo giá thực thu của kênh.' : 'Khoản cọc áp dụng cho toàn bộ booking nhóm, không chia đều trên màn hình thanh toán.'}</div>
        `;
    },

    updateSelectedAvailabilityCard(containerId) {
        const cartIds = new Set(this.getRoomCart().map((item) => String(item.room_type_id)));
        document.querySelectorAll(`#${containerId} .bk-avail-card`).forEach((card) => {
            const isSelected = cartIds.has(card.dataset.roomTypeId);
            card.classList.toggle('selected', Boolean(isSelected));
            const cta = card.querySelector('.bk-avail-cta');
            const item = this.getRoomCart().find((entry) => String(entry.room_type_id) === card.dataset.roomTypeId);
            if (cta) cta.textContent = isSelected ? `Đã chọn x${item?.quantity || 1}` : (containerId === 'bk-avail-cards' ? 'Đặt phòng' : 'Thêm');
        });
    },

    bookFromAvailability(checkIn, checkOut, roomTypeId, roomTypeName, price, available = 1, maxGuests = 2) {
        this.openCreate();
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
        set('bk-form-check-in-at', `${checkIn}T14:00`);
        set('bk-form-check-out-at', `${checkOut}T12:00`);
        this.syncBookingDateHiddenFields();
        set('bk-form-status', 'CONFIRMED');
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
        if (submitBtn) submitBtn.style.display = step === 3 ? 'inline-flex' : 'none';
        if (step === 2) {
            this.onBookingIdTypeChange();
            this.switchBookingAddressMode(this.getBookingAddressMode(), true);
            setTimeout(() => document.getElementById('bk-form-guest-name')?.focus(), 150);
        } else if (step === 3) {
            this.onBookingPaymentMethodChange();
            this.previewBookingPrice();
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
            if (!this.getRoomCartQuantity() && !this.state.editingBookingId) {
                pmsToast('Vui lòng chọn ít nhất một phòng bằng cách click vào thẻ phòng', false);
                return;
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
        const total = Number(this.value('bk-form-total') || 0) || Math.round(Number(selected.base_price || 0) * nights);
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
            deposit_amount: Number(this.value('bk-form-deposit') || 0),
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
                el.addEventListener('input', () => {
                    this.updateBookingTotalPreview();
                    this.renderPaymentRoomSummary();
                });
                el.dataset.bkMoneyBound = '1';
            }
        });
        [
            'bk-form-guest-name', 'bk-form-guest-cccd', 'bk-form-id-expire', 'bk-form-gender',
            'bk-form-date-of-birth', 'bk-form-nationality', 'bk-form-guests', 'bk-form-booking-type',
            'bk-form-status', 'bk-form-sales-name', 'bk-form-booking-code', 'bk-form-zalo-name',
            'bk-form-source-phone', 'bk-form-guest-phone', 'bk-form-province', 'bk-form-district',
            'bk-form-ward', 'bk-form-address'
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el && !el.dataset.bkValidationBound) {
                el.addEventListener('input', () => el.classList.remove('is-invalid'));
                el.addEventListener('change', () => el.classList.remove('is-invalid'));
                el.dataset.bkValidationBound = '1';
            }
        });
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
        if (!input || !input.value) return true;
        const today = this.toDateInput(new Date());
        input.classList.toggle('is-invalid', input.value < today);
        if (input.value < today) pmsToast('Giấy tờ đã hết hạn', false);
        return input.value >= today;
    },

    checkBookingBirth(input) {
        if (!input || !input.value) return true;
        const today = this.toDateInput(new Date());
        input.classList.toggle('is-invalid', input.value >= today);
        return input.value < today;
    },

    isOtaBookingForm() {
        return this.value('bk-form-booking-type') === 'OTA';
    },

    getPmsReferenceTotal() {
        return this.getRoomCart().reduce((sum, item) => {
            return sum + Number(item.unit_total || item.base_price || 0) * Number(item.quantity || 1);
        }, 0);
    },

    updateBookingTotalPreview() {
        const total = Number(this.value('bk-form-total') || 0);
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
        this.loadAvailabilityBar();
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
            if (totalInput && !isOta) totalInput.value = String(total);
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
            const targets = cart.length ? cart : [rt];
            const fallbackTotal = targets.reduce((sum, item) => {
                const unit = Math.round(Number(item.base_price || 0) * Math.max(1, this.dateDiff(ci.slice(0, 10), co.slice(0, 10))));
                item.unit_total = unit;
                return sum + unit * Number(item.quantity || 1);
            }, 0);
            if (totalInput && !isOta) totalInput.value = String(fallbackTotal);
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
            expire.disabled = noExpire || crmLocked;
            if (noExpire) {
                expire.value = '';
                expire.classList.remove('is-invalid');
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
        const select = document.getElementById('bk-form-payment-method');
        if (select) select.value = method || 'Chi nhánh';
        this.onBookingPaymentMethodChange();
    },

    updateBookingPaymentMethodCards() {
        const method = this.value('bk-form-payment-method') || 'Chi nhánh';
        const locked = this.isOtaBookingForm();
        document.querySelectorAll('#bk-create-modal .bk-payment-method-card').forEach((card) => {
            const active = card.dataset.method === method;
            card.classList.toggle('active', active);
            card.classList.toggle('disabled', locked);
            card.disabled = locked;
            card.setAttribute('aria-checked', active ? 'true' : 'false');
            card.setAttribute('aria-disabled', locked ? 'true' : 'false');
        });
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

    validateReservationGuestFields({ requirePhone = false, requireCrmAddress = false } = {}) {
        const idType = this.value('bk-form-id-type') || 'cccd';
        const isForeign = ['passport', 'visa'].includes(idType);
        const addressMode = this.getBookingAddressMode();
        const isCrmGuest = Boolean(this.value('bk-form-guest-id'));

        const bookingType = this.value('bk-form-booking-type');
        const isOta = bookingType === 'OTA';
        document.getElementById('bk-step-2')?.classList.toggle('bk-ota-guest-relaxed', Boolean(isOta));
        if (isOta || !isCrmGuest) return true;
        if (!this.value('bk-form-guest-name')) return this.failReservationValidation('bk-form-guest-name', 'Vui lòng nhập họ tên khách');
        if (!idType) return this.failReservationValidation('bk-form-id-type', 'Vui lòng chọn loại giấy tờ');
        if (!this.value('bk-form-guest-cccd')) return this.failReservationValidation('bk-form-guest-cccd', 'Vui lòng nhập số giấy tờ');
        if (this.getBookingIdExpireRequired(idType) && !this.value('bk-form-id-expire')) return this.failReservationValidation('bk-form-id-expire', 'Vui lòng nhập ngày hết hạn giấy tờ');
        if (!this.value('bk-form-gender')) return this.failReservationValidation('bk-form-gender', 'Vui lòng chọn giới tính');
        if (!this.value('bk-form-date-of-birth')) return this.failReservationValidation('bk-form-date-of-birth', 'Vui lòng nhập ngày sinh');
        if (!this.value('bk-form-nationality')) return this.failReservationValidation('bk-form-nationality', 'Vui lòng nhập quốc tịch');
        if (requirePhone && !this.value('bk-form-guest-phone')) return this.failReservationValidation('bk-form-guest-phone', 'Vui lòng nhập số điện thoại');
        if (requireCrmAddress && !isForeign) {
            if (!this.value('bk-form-province')) return this.failReservationValidation('bk-form-province', 'Vui lòng chọn Tỉnh/Thành phố');
            if (addressMode === 'old' && !this.value('bk-form-district')) return this.failReservationValidation('bk-form-district', 'Vui lòng chọn Quận/Huyện');
            if (!this.value('bk-form-ward')) return this.failReservationValidation('bk-form-ward', 'Vui lòng chọn Phường/Xã');
        }
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
        if (this.isOtaBookingForm() && Number(this.value('bk-form-total') || 0) <= 0) return this.failReservationValidation('bk-form-total', 'Vui lòng nhập tổng tiền OTA thực thu');
        if (!this.value('bk-form-guest-id') && !this.value('bk-form-guest-name')) return this.failReservationValidation('bk-form-guest-name', 'Vui lòng nhập họ tên khách');
        if ((!this.getRoomCartQuantity() && !this.state.editingBookingId) || !this.value('bk-form-check-in') || !this.value('bk-form-check-out')) {
            pmsToast('Thiếu ngày ở hoặc phòng đã chọn', false);
            return false;
        }
        return true;
    },

    validateReservationGuestStep() {
        this.clearReservationValidation();
        return this.validateReservationGuestFields({ requirePhone: true, requireCrmAddress: true });
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
        const method = this.value('bk-form-payment-method') || 'Chi nhánh';
        const ref = this.value('bk-form-payment-ref');
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
        const isEdit = Boolean(this.state.editingBookingId);
        const depositMethod = this.value('bk-form-payment-method') || 'Chi nhánh';
        const guestIdType = this.value('bk-form-id-type') || 'cccd';
        const depositMeta = this.getBookingDepositMeta();
        const addressPayload = this.getBookingAddressPayload();
        const otaPricing = this.isOtaBookingForm()
            ? {
                ota_price_mode: 'manual_channel_total',
                ota_actual_total: Number(this.value('bk-form-total') || 0),
                pms_reference_total: this.getPmsReferenceTotal(),
                ota_price_delta: Number(this.value('bk-form-total') || 0) - this.getPmsReferenceTotal(),
                ota_group_total: Number(this.value('bk-form-total') || 0),
                ota_room_count: this.getRoomCartQuantity() || 1,
            }
            : {};
        const payload = {
            booking_type: this.value('bk-form-booking-type') || 'DIRECT',
            booking_source: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-ota-channel') : '',
            external_id: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-booking-code') : '',
            reservation_status: this.value('bk-form-status') || 'CONFIRMED',
            branch_id: this.state.branchId,
            room_type_id: Number(this.value('bk-form-room-type')),
            guest_name: this.value('bk-form-guest-name'),
            guest_phone: this.value('bk-form-guest-phone'),
            guest_id: this.value('bk-form-guest-id') ? Number(this.value('bk-form-guest-id')) : null,
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
            total_price: Number(this.value('bk-form-total') || 0),
            deposit_amount: Number(this.value('bk-form-deposit') || 0),
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
                source_label: this.getBookingSourceLabel(),
                booking_reference_code: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-booking-code') : '',
                ota_channel: this.value('bk-form-booking-type') === 'OTA' ? this.value('bk-form-ota-channel') : '',
                ...otaPricing,
                sales_name: this.value('bk-form-booking-type') === 'SALES' ? this.value('bk-form-sales-name') : '',
                ...this.getBookingSourceExtraPayload(),
                ...addressPayload.raw,
            },
        };
        if (!isEdit) {
            const isOta = this.isOtaBookingForm();
            payload.room_items = this.getRoomCart().map((item) => ({
                room_type_id: Number(item.room_type_id),
                quantity: Number(item.quantity || 1),
                unit_total: isOta ? 0 : Number(item.unit_total || 0),
                reference_unit_total: Number(item.unit_total || 0),
                room_type: item.room_type,
            }));
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
            'bk-form-province', 'bk-form-district', 'bk-form-ward',
            'bk-form-new-province', 'bk-form-new-ward'
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.value = id === 'bk-form-total' || id === 'bk-form-deposit' ? '0' : '';
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
        if (status) status.value = 'PENDING';
        const bookingType = document.getElementById('bk-form-booking-type');
        if (bookingType) bookingType.value = 'DIRECT';
        this.state.editingBookingId = null;
        this.state.selectedRoomType = null;
        this.state.roomCart = [];
        this.renderRoomCart();
        this.setCreateMode(false);
        this.setBookingCrmFieldsLocked(false);
        const selected = document.getElementById('bk-selected-guest');
        if (selected) {
            selected.style.display = 'none';
            selected.textContent = '';
        }
        const box = document.getElementById('bk-crm-results');
        if (box) {
            box.classList.remove('show');
            box.innerHTML = '';
        }
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
        if (event.key === 'Enter') this.searchCrmGuests();
    },

    async searchCrmGuests() {
        const q = this.value('bk-crm-search-input') || this.value('bk-form-guest-phone') || this.value('bk-form-guest-name');
        if (!q || q.length < 2) {
            pmsToast('Nhập ít nhất 2 ký tự để tìm khách CRM', false);
            return;
        }
        const box = document.getElementById('bk-crm-results');
        if (box) {
            box.classList.add('show');
            box.innerHTML = '<div style="padding:12px;color:#64748b;">Đang tìm khách...</div>';
        }
        try {
            const data = this.apiData(await pmsApi(`/api/pms/crm/guests/search?q=${encodeURIComponent(q)}&page_size=8`), {});
            const guests = data.items || data.guests || [];
            if (!box) return;
            if (!guests.length) {
                box.innerHTML = '<div style="padding:12px;color:#64748b;">Không tìm thấy khách phù hợp.</div>';
                return;
            }
            box.innerHTML = guests.map((g) => `
                <button class="bk-crm-item" type="button" onclick="BookingHub.selectCrmGuest(${this.escape(JSON.stringify(g))})">
                    <span>
                        <strong>${this.escape(g.full_name || 'Khách')}</strong>
                        <div style="font-size:12px;color:#64748b;margin-top:2px;">${this.escape(g.phone || g.cccd || g.email || 'Chưa có định danh')}</div>
                    </span>
                    <span style="font-size:11px;font-weight:850;color:#0e7490;">${this.escape(g.tier_display || g.tier || 'BASIC')}</span>
                </button>
            `).join('');
        } catch (err) {
            if (box) box.innerHTML = `<div style="padding:12px;color:#b91c1c;">${this.escape(err.message || 'Lỗi tìm khách')}</div>`;
        }
    },

    setBookingCrmFieldsLocked(locked) {
        [
            'bk-form-guest-name',
            'bk-form-guest-cccd', 'bk-form-id-type', 'bk-form-gender',
            'bk-form-date-of-birth', 'bk-form-nationality', 'bk-form-id-expire',
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
        await this.switchBookingAddressMode(mode, false);

        if (mode === 'old') {
            set('bk-form-address', addressDetail);
            set('bk-form-province', guest.old_city || fallback.city || '');
            await this.onBookingProvinceChange(document.getElementById('bk-form-province'), true);
            set('bk-form-district', guest.old_district || fallback.district || '');
            await this.onBookingDistrictChange(document.getElementById('bk-form-district'), true);
            set('bk-form-ward', guest.old_ward || fallback.ward || '');
            set('bk-form-new-province', guest.city || '');
            set('bk-form-new-ward', guest.ward || '');
            await this.onBookingWardChange(document.getElementById('bk-form-ward'));
            return;
        }

        set('bk-form-address', addressDetail);
        set('bk-form-province', guest.city || fallback.city || '');
        await this.onBookingProvinceChange(document.getElementById('bk-form-province'), true);
        set('bk-form-district', guest.district || fallback.district || '');
        set('bk-form-ward', guest.ward || fallback.ward || '');
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
        set('bk-form-id-expire', guest.id_expire);
        await this.fillBookingAddressFromGuest(guest);
        this.onBookingIdTypeChange();
        this.setBookingCrmFieldsLocked(true);
        this.clearReservationValidation();
        const selected = document.getElementById('bk-selected-guest');
        if (selected) {
            selected.style.display = 'block';
            selected.textContent = `Đã chọn CRM: ${guest.full_name || 'Khách'} • ${guest.tier_display || guest.tier || 'BASIC'}`;
        }
        const box = document.getElementById('bk-crm-results');
        if (box) box.classList.remove('show');
        pmsToast('Đã điền thông tin khách CRM', true);
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
        if (parsed.expiry_date && parsed.expiry_date !== 'Không thời hạn' && typeof pmsScanDateToISO === 'function') {
            set('bk-form-id-expire', pmsScanDateToISO(parsed.expiry_date));
            this.checkBookingIdExpire(document.getElementById('bk-form-id-expire'));
        }
        set('bk-form-nationality', 'VNM - Việt Nam');
        await this.fillBookingAddressFromScan(parsed.address, parsed.card_type || 'CCCD_CU');
        this.onBookingIdTypeChange();
        this.clearReservationValidation();

        const selected = document.getElementById('bk-selected-guest');
        if (selected) {
            selected.style.display = 'none';
            selected.textContent = '';
        }
        const box = document.getElementById('bk-crm-results');
        if (box) box.classList.remove('show');
        document.getElementById('bk-form-guest-phone')?.focus();
    },

    resetBookingGuestFields() {
        this.setBookingCrmFieldsLocked(false);
        [
            'bk-form-guest-id', 'bk-form-guest-name', 'bk-form-guest-phone',
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
        this.onBookingIdTypeChange();
        this.clearReservationValidation();
    },

    clearSelectedGuest(showToast = true) {
        this.resetBookingGuestFields();
        this.setBookingCrmFieldsLocked(false);
        const selected = document.getElementById('bk-selected-guest');
        if (selected) {
            selected.style.display = 'none';
            selected.textContent = '';
        }
        const box = document.getElementById('bk-crm-results');
        if (box) {
            box.classList.remove('show');
            box.innerHTML = '';
        }
        if (showToast) pmsToast('Chuyển sang tạo khách mới', true);
    }
});
