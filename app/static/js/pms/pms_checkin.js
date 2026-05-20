// static/js/pms/pms_checkin.js
// PMS Check-in - Check-in modal, guest management, price calculation
'use strict';

let pmsCi = {};
let pmsCiRoomNumber = null;
let pmsCiGuestList = [];
let pmsCiServiceList = [];
let pmsCiSurchargeList = [];
window._pmsCiRiskConfirmed = false;
window._pmsCiRiskFlags = null;
let pmsCiMaxGuests = 2;
let pmsCiSubmitting = false;

function pmsCiSetBusy(isBusy, text = 'Đang nhận phòng...') {
    const dialog = document.getElementById('ci-dialog');
    if (!dialog) return;
    dialog.classList.toggle('ci-busy', !!isBusy);
    const label = document.getElementById('ci-busy-text');
    if (label && text) label.textContent = text;
}

function pmsCiOpenModal() {
    const modal = document.getElementById('ciModal');
    if (!modal) return;
    if (modal.parentElement !== document.body) {
        document.body.appendChild(modal);
    }
    document.body.classList.add('ci-modal-open');
    const body = document.getElementById('ci-body');
    if (body) body.scrollTop = 0;
    requestAnimationFrame(() => modal.classList.add('show'));
}

function pmsCiCloseModal() {
    const modal = document.getElementById('ciModal');
    if (!modal) return;
    modal.classList.remove('show');
    document.body.classList.remove('ci-modal-open');
}

window.pmsCiOpenModal = pmsCiOpenModal;
window.pmsCiCloseModal = pmsCiCloseModal;

function openCI(id) {
    window._pmsCiReservationMode = false;
    window._pmsCiReservationContext = null;
    const r = PMS.roomMap[id]; if (!r) return;
    pmsCi = r;
    pmsCiRoomNumber = r.room_number;
    pmsCiMaxGuests = r.max_guests || 2;
    pmsCiGuestList = [];
    pmsCiServiceList = [];
    pmsCiSurchargeList = [];
    pmsCiSubmitting = false;
    pmsCiSetBusy(false);
    window._pmsBookingCheckinId = null;
    window._pmsCiRiskConfirmed = false;
    window._pmsCiRiskFlags = null;
    window._ciRoomNumber = r.room_number;
    window._pmsLastPricingPreview = null;
    clearTimeout(_pmsCalcPriceTimer);
    _pmsCalcPriceSeq++;
    const elRoomId = document.getElementById('ci-room-id');
    if (elRoomId) elRoomId.value = id;
    const elTitle = document.getElementById('ci-title');
    if (elTitle) elTitle.textContent = 'Nhận phòng nhanh';
    pmsCiSetModalAction('Nhận phòng');
    const elSub = document.getElementById('ci-sub');
    if (elSub) elSub.textContent = `Phòng ${r.room_number} | ${r.room_type_name || '—'} | Tối đa ${pmsCiMaxGuests} khách`;
    
    const opt = document.getElementById('ci-room-type-opt');
    if (opt) { opt.textContent = r.room_type_name || '—'; opt.value = r.room_type_id || ''; }
    const rn = document.getElementById('ci-room-num');
    if (rn) rn.value = r.room_number || '';

    // Initialize Flatpickr datetime pickers
    pmsCiInitFlatpickr();

    const elDep = document.getElementById('ci-deposit');
    if (elDep) elDep.value = '0';
    const elNotes = document.getElementById('ci-notes');
    if (elNotes) elNotes.value = '';
    const elHero = document.getElementById('ci-hero-amount');
    if (elHero) elHero.textContent = '—';
    
    // Reset service inputs
    const svcName = document.getElementById('ci-svc-name');
    const svcPrice = document.getElementById('ci-svc-price');
    const surName = document.getElementById('ci-sur-name');
    const surPrice = document.getElementById('ci-sur-price');
    if (svcName) svcName.value = '';
    if (svcPrice) svcPrice.value = '';
    if (surName) surName.value = '';
    if (surPrice) surPrice.value = '';
    
    pmsCiRenderItems();

    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    const elGList = document.getElementById('ci-guest-list-panel');
    if (elGList) elGList.classList.remove('show');
    const elCWarn = document.getElementById('ci-capacity-warn');
    if (elCWarn) elCWarn.classList.remove('show');
    // Initialize dynamic datalists
    if (typeof pmsPopulateNationalities === 'function') pmsPopulateNationalities('dl-nationality');
    if (typeof vnInitAddressFields === 'function') vnInitAddressFields();
    pmsCiOpenModal();
}

function pmsCiSetModalAction(label) {
    const btn = document.querySelector('#ciModal .v-footer .v-btn.success');
    if (btn) {
        const icon = btn.querySelector('svg') ? btn.querySelector('svg').outerHTML : '';
        btn.innerHTML = `${icon}${label}`;
    }
}

function pmsCiSetDepositMethod(method = 'Chi nhánh', meta = {}) {
    const cards = Array.from(document.querySelectorAll('.ci-dep-method-item'));
    let card = cards.find(item => item.dataset.value === method);
    if (!card) card = cards.find(item => item.dataset.value === 'Chi nhánh');

    cards.forEach(item => item.classList.remove('selected'));
    if (card) card.classList.add('selected');

    const selectedMethod = card?.dataset.value || 'Chi nhánh';
    const metaGrp = document.getElementById('ci-deposit-meta-grp');
    const metaCompany = document.getElementById('ci-meta-company');
    const metaOta = document.getElementById('ci-meta-ota');
    if (metaGrp) metaGrp.style.display = 'none';
    if (metaCompany) metaCompany.style.display = 'none';
    if (metaOta) metaOta.style.display = 'none';

    if (selectedMethod === 'Công ty') {
        if (metaGrp) metaGrp.style.display = 'flex';
        if (metaCompany) metaCompany.style.display = 'block';
    } else if (selectedMethod === 'OTA') {
        if (metaGrp) metaGrp.style.display = 'flex';
        if (metaOta) metaOta.style.display = 'block';
    }

    const beneficiary = document.getElementById('ci-deposit-beneficiary');
    const otaChannel = document.getElementById('ci-deposit-ota');
    const refCode = document.getElementById('ci-deposit-ref');
    if (beneficiary) beneficiary.value = meta.beneficiary || '';
    if (otaChannel) otaChannel.value = meta.ota_channel || '';
    if (refCode) refCode.value = meta.ref_code || '';
    if (selectedMethod === 'OTA' && meta.ota_channel && otaChannel && otaChannel.value !== meta.ota_channel) {
        const option = document.createElement('option');
        option.value = meta.ota_channel;
        option.textContent = meta.ota_channel;
        otaChannel.appendChild(option);
        otaChannel.value = meta.ota_channel;
    }
}

function pmsCiSetDateTime(inputId, value) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.value = value || '';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    pmsCiSyncDateTimePicker(inputId);
}

function pmsCiParseDateTime(value) {
    if (!value) return null;
    const next = new Date(value);
    return Number.isNaN(next.getTime()) ? null : next;
}

function pmsCiFormatDisplayDateTime(value) {
    const dt = pmsCiParseDateTime(value);
    if (!dt) return '';
    const d = String(dt.getDate()).padStart(2, '0');
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const y = dt.getFullYear();
    const hh = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    return `${d}/${m}/${y}, ${hh}:${mm}`;
}

function pmsCiSetDateTimeDisplay(inputId) {
    const input = document.getElementById(inputId);
    const displayInput = document.getElementById(`${inputId}-display`);
    if (input && displayInput) displayInput.value = pmsCiFormatDisplayDateTime(input.value);
}

function pmsCiSyncDateTimePicker(inputId) {
    const input = document.getElementById(inputId);
    const displayInput = document.getElementById(`${inputId}-display`);
    if (!input || !displayInput) return;
    const instance = displayInput._flatpickr;
    if (!instance) {
        pmsCiSetDateTimeDisplay(inputId);
        return;
    }
    const nextDate = pmsCiParseDateTime(input.value);
    if (!nextDate) {
        instance.clear(false);
        return;
    }
    const currentDate = instance.selectedDates[0];
    if (!currentDate || currentDate.getTime() !== nextDate.getTime()) {
        instance.setDate(nextDate, false);
    }
}

function pmsCiEnsureDateTimePickers() {
    const fields = [
        { hiddenId: 'ci-in', displayId: 'ci-in-display', role: 'check-in' },
        { hiddenId: 'ci-out', displayId: 'ci-out-display', role: 'check-out' },
    ];
    const locale = typeof flatpickr !== 'undefined' && flatpickr.l10ns && flatpickr.l10ns.vn
        ? flatpickr.l10ns.vn
        : undefined;

    fields.forEach(({ hiddenId, displayId, role }) => {
        const hiddenInput = document.getElementById(hiddenId);
        const displayInput = document.getElementById(displayId);
        if (!hiddenInput || !displayInput) return;

        if (typeof flatpickr !== 'function') {
            pmsCiSetDateTimeDisplay(hiddenId);
            return;
        }
        if (displayInput._flatpickr) {
            pmsCiSyncDateTimePicker(hiddenId);
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
            defaultDate: pmsCiParseDateTime(hiddenInput.value),
            prevArrow: '<i class="bi bi-chevron-left"></i>',
            nextArrow: '<i class="bi bi-chevron-right"></i>',
            onReady: (_selectedDates, _dateStr, instance) => {
                instance.input.readOnly = true;
                instance.calendarContainer.classList.add('bk-planner-flatpickr-popup');
                instance.calendarContainer.dataset.plannerRole = role;
                pmsCiSyncDateTimePicker(hiddenId);
            },
            onOpen: (_selectedDates, _dateStr, instance) => {
                instance.calendarContainer.dataset.plannerRole = role;
            },
            onChange: (selectedDates) => {
                hiddenInput.value = selectedDates.length
                    ? flatpickr.formatDate(selectedDates[0], 'Y-m-d\\TH:i')
                    : '';
                hiddenInput.dispatchEvent(new Event('change'));
            },
        });
    });
}

function pmsCiResetGuestInputChrome() {
    [
        'ci-name', 'ci-cccd', 'ci-id-expire', 'ci-birth', 'ci-phone',
        'ci-guest-notes', 'ci-address', 'ci-province', 'ci-district',
        'ci-ward', 'ci-vehicle', 'ci-nationality', 'ci-new-province',
        'ci-new-ward', 'ci-tax-code', 'ci-tax-contact',
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.readOnly = id === 'ci-new-province' || id === 'ci-new-ward';
        el.disabled = false;
        el.classList.remove('is-invalid', 'is-warning');
        el.style.background = '';
        el.style.backgroundColor = '';
        if (!['ci-new-province', 'ci-new-ward'].includes(id)) {
            el.style.color = '';
            el.style.cursor = '';
        }
    });

    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) idTypeEl.disabled = false;
    const genderEl = document.getElementById('ci-gender');
    if (genderEl) genderEl.disabled = false;
    document.querySelectorAll('#ciModal input[name="ci-area"], #ciModal input[name="ci-invoice"]').forEach((radio) => {
        radio.disabled = false;
        radio.style.display = '';
    });
}

function pmsCiRenderReservationNotice(data = {}) {
    const notice = document.getElementById('ci-reservation-notice');
    if (!notice) return;
    const total = Number(data.group_total || 0);
    const index = Number(data.group_index || 0);
    if (total > 1) {
        const summary = data.group_summary ? ` • ${pmsEscapeHtml(data.group_summary)}` : '';
        notice.innerHTML = `
            <strong>Đặt nhiều phòng ${index || 1}/${total}</strong>
            <span>${pmsEscapeHtml(data.guest_name || 'Khách này')} có booking nhóm${summary}. Mỗi phòng cần hồ sơ khách lưu trú riêng; không dùng cùng một số giấy tờ để nhận nhiều phòng.</span>
        `;
        notice.style.display = 'flex';
        return;
    }
    if (data.mode === 'checkin') {
        notice.innerHTML = `
            <strong>Nhận phòng từ đặt trước</strong>
            <span>Thông tin khách và tiền cọc được lấy từ booking. Cọc đã thu chỉ đối soát ở giao ca, không nhập lại vào folio khi nhận phòng.</span>
        `;
        notice.style.display = 'flex';
        return;
    }
    notice.style.display = 'none';
}

function pmsCiSetDepositLocked(isLocked, message = '') {
    const input = document.getElementById('ci-deposit');
    const strip = input ? input.closest('.ci-deposit-strip') : null;
    if (input) {
        input.readOnly = !!isLocked;
        input.disabled = !!isLocked;
        input.classList.toggle('ci-readonly-money', !!isLocked);
    }
    if (strip) strip.classList.toggle('locked', !!isLocked);
    document.querySelectorAll('.ci-dep-method-item').forEach((item) => {
        item.classList.toggle('disabled', !!isLocked);
        item.setAttribute('aria-disabled', isLocked ? 'true' : 'false');
        item.style.pointerEvents = isLocked ? 'none' : '';
    });
    ['ci-deposit-beneficiary', 'ci-deposit-ota', 'ci-deposit-ref'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !!isLocked;
    });
    const label = document.getElementById('ci-deposit-help');
    if (label) {
        label.textContent = message || 'Tổng số tiền khách thanh toán trước khi nhận phòng';
    }
}

async function pmsCiApplyReservationGuest(data = {}) {
    pmsCiResetGuestInputChrome();
    const set = (id, value) => {
        const el = document.getElementById(id);
        if (el && value !== undefined && value !== null) el.value = value || '';
    };
    set('ci-name', data.guest_name || '');
    set('ci-cccd', data.guest_cccd || '');
    set('ci-phone', data.guest_phone || '');
    set('ci-gender', data.gender || '');
    set('ci-birth', data.date_of_birth ? String(data.date_of_birth).slice(0, 10) : '');
    if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(document.getElementById('ci-id-expire'), data.id_expire);
    else set('ci-id-expire', data.id_expire ? String(data.id_expire).slice(0, 10) : '');
    set('ci-nationality', data.nationality || 'VNM - Việt Nam');
    set('ci-address', data.address_detail || data.address || '');
    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) {
        idTypeEl.value = (data.guest_id_type || 'cccd').toLowerCase();
        pmsCiToggleIdFields(idTypeEl);
    }

    const addressType = data.address_type || 'new';
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
    const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
    if (addressType === 'old') {
        if (oldRadio) oldRadio.checked = true;
        if (typeof vnSwitchMode === 'function') await vnSwitchMode('old');
        set('ci-province', data.old_city || '');
        const provinceEl = document.getElementById('ci-province');
        if (provinceEl && provinceEl.value && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(provinceEl);
        set('ci-district', data.old_district || '');
        const districtEl = document.getElementById('ci-district');
        if (districtEl && districtEl.value && typeof vnOnDistrictChange === 'function') await vnOnDistrictChange(districtEl);
        set('ci-ward', data.old_ward || '');
        set('ci-new-province', data.new_city || data.city || '');
        set('ci-new-ward', data.new_ward || data.ward || '');
    } else {
        if (newRadio) newRadio.checked = true;
        if (typeof vnSwitchMode === 'function') await vnSwitchMode('new');
        set('ci-province', data.city || data.new_city || '');
        const provinceEl = document.getElementById('ci-province');
        if (provinceEl && provinceEl.value && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(provinceEl);
        set('ci-district', data.district || '');
        set('ci-ward', data.ward || data.new_ward || '');
    }
    pmsCiResetGuestInputChrome();
    if (idTypeEl) pmsCiToggleIdFields(idTypeEl);
    window._pmsCiExistingGuestId = data.guest_id || null;
    window._pmsCiIsOldGuest = false;
}

function pmsCiOpenReservationModal(context) {
    const data = context || {};
    const isBookingCheckin = data.mode === 'checkin' || !!data.booking_id;
    const raw = data.raw_data || {};
    const bookingType = String(data.booking_type || raw.booking_type || '').toUpperCase();
    const isCompanyBooking = bookingType === 'COMPANY';
    const isOtaBooking = !isCompanyBooking && (
        bookingType === 'OTA'
        || raw.ota_price_mode === 'manual_channel_total'
        || Boolean(data.booking_source || raw.ota_channel || raw.ota_group_code)
    );
    const otaChannel = data.booking_source || raw.ota_channel || raw.booking_source || '';
    const otaReferenceCode = raw.booking_reference_code || raw.ota_group_code || data.external_id || raw.external_id || '';
    window._pmsCiReservationMode = !isBookingCheckin;
    window._pmsCiReservationContext = data;
    window._pmsLastPricingPreview = null;
    clearTimeout(_pmsCalcPriceTimer);
    _pmsCalcPriceSeq++;
    window._pmsCiOtaPricing = isOtaBooking
        ? {
            actualTotal: Number(data.total_price || 0),
            channel: otaChannel,
            referenceTotal: Number(raw.pms_reference_total || 0),
        }
        : null;
    pmsCi = {
        id: data.room_id || 0,
        room_number: data.room_number || 'Chưa gán',
        room_type_id: data.room_type_id || null,
        branch_id: data.branch_id || null,
        room_type_name: data.room_type_name || data.room_type || '—',
        max_guests: data.max_guests || 2,
        price_per_night: Number(data.price_per_night || data.base_price || 0),
        price_per_hour: Number(data.price_per_hour || 0),
        price_next_hour: Number(data.price_next_hour || 0),
        min_hours: Number(data.min_hours || 0),
    };
    pmsCiRoomNumber = pmsCi.room_number;
    pmsCiMaxGuests = pmsCi.max_guests || 2;
    pmsCiGuestList = [];
    pmsCiServiceList = [];
    pmsCiSurchargeList = [];
    pmsCiSubmitting = false;
    pmsCiSetBusy(false);
    window._pmsBookingCheckinId = isBookingCheckin ? data.booking_id : null;
    window._pmsCiBranchId = pmsCi.branch_id || (window.PMS ? window.PMS.branchId : null) || null;
    window._pmsCiRiskConfirmed = false;
    window._pmsCiRiskFlags = null;
    window._ciRoomNumber = pmsCi.room_number;

    const elRoomId = document.getElementById('ci-room-id');
    if (elRoomId) elRoomId.value = pmsCi.id;
    const elTitle = document.getElementById('ci-title');
    if (elTitle) elTitle.textContent = data.title || 'Tạo đặt phòng';
    const elSub = document.getElementById('ci-sub');
    if (elSub) {
        const availableText = data.available_rooms ? ` | Còn ${data.available_rooms} phòng` : '';
        elSub.textContent = `${pmsCi.room_type_name} | ${data.check_in || '—'} → ${data.check_out || '—'} | Tối đa ${pmsCiMaxGuests} khách${availableText}`;
    }
    const opt = document.getElementById('ci-room-type-opt');
    if (opt) { opt.textContent = pmsCi.room_type_name || '—'; opt.value = pmsCi.room_type_id || ''; }
    const rn = document.getElementById('ci-room-num');
    if (rn) rn.value = pmsCi.room_number || 'Chưa gán';

    pmsCiInitFlatpickr();
    const arrival = raw.check_in_time || raw.estimated_arrival || data.estimated_arrival || '14:00';
    const departure = raw.check_out_time || raw.estimated_departure || data.estimated_departure || '12:00';
    if (data.check_in) pmsCiSetDateTime('ci-in', `${data.check_in}T${arrival}`);
    if (data.check_out) pmsCiSetDateTime('ci-out', `${data.check_out}T${departure}`);

    const elHero = document.getElementById('ci-hero-amount');
    if (elHero) elHero.textContent = data.total_price ? pmsMoney(Number(data.total_price)) : '—';

    pmsCiRenderItems();
    pmsCiRefreshGuestForm();
    pmsCiRenderReservationNotice(data);
    const elDep = document.getElementById('ci-deposit');
    if (elDep) elDep.value = isOtaBooking ? '0' : String(Math.round(Number(data.deposit_amount || 0)));
    const otaSelect = document.getElementById('ci-deposit-ota');
    if (isOtaBooking && otaSelect && otaChannel && !Array.from(otaSelect.options).some((option) => option.value === otaChannel)) {
        const option = document.createElement('option');
        option.value = otaChannel;
        option.textContent = otaChannel;
        otaSelect.appendChild(option);
    }
    pmsCiSetDepositMethod(
        isCompanyBooking ? 'Công ty'
            : isOtaBooking ? 'OTA'
            : (data.deposit_type || data.payment_method || 'Chi nhánh'),
        isCompanyBooking
            ? { beneficiary: raw.company_name || data.booking_source || '' }
            : isOtaBooking
                ? { ota_channel: otaChannel, ref_code: otaReferenceCode }
                : (data.deposit_meta || {})
    );
    pmsCiSetDepositLocked(
        isOtaBooking || (isBookingCheckin && Number(data.deposit_amount || 0) > 0),
        isOtaBooking
            ? 'Đặt phòng OTA không nhập tiền cọc trước; kênh và mã tham chiếu được tự động đối soát.'
            : isCompanyBooking
                ? 'Đặt phòng công ty — thanh toán theo hợp đồng.'
                : (isBookingCheckin && Number(data.deposit_amount || 0) > 0
                    ? 'Cọc đã ghi nhận vào giao ca từ booking; nhận phòng không nhập khoản này vào folio.'
                    : '')
    );
    const elNotes = document.getElementById('ci-notes');
    if (elNotes) elNotes.value = data.notes || '';
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    const elGList = document.getElementById('ci-guest-list-panel');
    if (elGList) elGList.classList.remove('show');
    const elCWarn = document.getElementById('ci-capacity-warn');
    if (elCWarn) elCWarn.classList.remove('show');
    if (typeof pmsPopulateNationalities === 'function') pmsPopulateNationalities('dl-nationality');
    if (typeof vnInitAddressFields === 'function') vnInitAddressFields();
    if (isBookingCheckin) pmsCiApplyReservationGuest(data).catch((err) => console.warn('[CI] Reservation guest autofill failed', err));
    if (isCompanyBooking) {
        const invoiceRadio1 = document.querySelector('input[name="ci-invoice"][value="1"]');
        if (invoiceRadio1) {
            invoiceRadio1.checked = true;
            pmsCiToggleInvoice(invoiceRadio1);
        }
        const companyNameEl = document.getElementById('ci-company-name');
        if (companyNameEl) companyNameEl.value = raw.company_name || data.booking_source || '';
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.value = raw.company_tax_code || '';
    }
    pmsCiSetModalAction(data.submit_label || 'Lưu đặt phòng');
    setTimeout(pmsCalcPrice, 150);
    if (window._pmsCiOtaPricing?.actualTotal) {
        window._pmsLastPricingPreview = {
            ...(window._pmsLastPricingPreview || {}),
            ota_price_mode: 'manual_channel_total',
            ota_actual_total: window._pmsCiOtaPricing.actualTotal,
            ota_channel: window._pmsCiOtaPricing.channel,
        };
    }
    pmsCiOpenModal();
}

// ─────────────────────────────────────────────────────────────────────────────
// Time input Initialization
// ─────────────────────────────────────────────────────────────────────────────

function pmsCiInitFlatpickr() {
    const ciInEl = document.getElementById('ci-in');
    const ciOutEl = document.getElementById('ci-out');

    if (ciInEl) {
        const now = new Date();
        const tzOffset = now.getTimezoneOffset() * 60000;
        const localISOTime = (new Date(now.getTime() - tzOffset)).toISOString().slice(0, 16);
        ciInEl.value = localISOTime;
    }
    if (ciOutEl) ciOutEl.value = '';

    pmsCiEnsureDateTimePickers();

    if (typeof pmsCalcPrice === 'function') setTimeout(pmsCalcPrice, 200);
}

function pmsCiGetFormGuest() {
    // Get invoice info
    const invoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    const taxCode = invoiceVal === '1' ? (document.getElementById('ci-tax-code')?.value?.trim() || '') : '';
    const invoiceContact = invoiceVal === '1' ? (document.getElementById('ci-tax-contact')?.value?.trim() || '') : '';
    const companyName = invoiceVal === '1' ? (document.getElementById('ci-company-name')?.value?.trim() || '') : '';
    const companyAddress = invoiceVal === '1' ? (document.getElementById('ci-company-address')?.value?.trim() || '') : '';

    // address_type drives which fields feed the submission
    // ── OLD mode: ci-province/ci-district/ci-ward hold OLD values;
    //              ci-new-province/ci-new-ward hold the READONLY converted new values.
    // ── NEW mode: ci-province/ci-ward hold NEW values; ci-new-* are empty.
    const addrType = document.querySelector('input[name="ci-area"]:checked')?.value || 'new';
    const _city = document.getElementById('ci-province')?.value?.trim() || '';
    const _ward = document.getElementById('ci-ward')?.value?.trim() || '';
    const _dist = addrType === 'old'
        ? (document.getElementById('ci-district')?.value?.trim() || '')
        : (document.getElementById('ci-district')?.value?.trim() || '');
    const _newCity = addrType === 'old'
        ? (document.getElementById('ci-new-province')?.value?.trim() || '')
        : _city;
    const _newWard = addrType === 'old'
        ? (document.getElementById('ci-new-ward')?.value?.trim() || '')
        : _ward;

    return {
        // Include guest id when autofilling an existing guest
        ...(window._pmsCiExistingGuestId ? { id: window._pmsCiExistingGuestId } : {}),
        full_name: document.getElementById('ci-name')?.value?.trim() || '',
        id_type: document.getElementById('ci-id-type')?.value || 'cccd',
        cccd: document.getElementById('ci-cccd')?.value?.trim() || '',
        id_expire: document.getElementById('ci-id-expire')?.value || '',
        gender: document.getElementById('ci-gender')?.value || '',
        birth_date: document.getElementById('ci-birth')?.value || '',
        phone: document.getElementById('ci-phone')?.value?.trim() || '',
        vehicle: document.getElementById('ci-vehicle')?.value?.trim() || '',
        // city/ward = what user typed (OLD values in old-mode; NEW values in new-mode)
        city: _city,
        district: _dist,
        ward: _ward,
        address: document.getElementById('ci-address')?.value?.trim() || '',
        address_type: addrType,
        // new_city/new_ward = post-reform values (from readonly conversion display)
        new_city: _newCity,
        new_ward: _newWard,
        // old_* = explicitly typed OLD values (only in old-mode)
        old_city: addrType === 'old' ? _city : null,
        old_district: addrType === 'old' ? _dist : null,
        old_ward: addrType === 'old' ? _ward : null,
        nationality: document.getElementById('ci-nationality')?.value?.trim() || 'VNM - Việt Nam',
        notes: document.getElementById('ci-guest-notes')?.value?.trim() || '',
        tax_code: taxCode,
        invoice_contact: invoiceContact,
        company_name: companyName,
        company_address: companyAddress,
        from_old: window._pmsCiIsOldGuest || false
    };
}

function pmsCiFormatRiskWarnings(riskFlags) {
    const warnings = riskFlags?.warnings || [];
    if (!warnings.length) return '';
    return warnings.map(w => {
        if (w.type === 'debt') return `- Còn nợ: ${pmsMoney(w.amount || riskFlags.unpaid_debt_amount || 0)}`;
        if (w.type === 'blacklist') return '- Đang trong danh sách đen';
        return `- ${w.message || 'Có cảnh báo CRM'}`;
    }).join('\n');
}

function pmsCiExtractRiskError(err) {
    if (err?.payload?.detail?.code === 'GUEST_RISK_CONFIRM_REQUIRED') return err.payload.detail;
    if (err?.payload?.code === 'GUEST_RISK_CONFIRM_REQUIRED') return err.payload;
    if (err?.detail?.code === 'GUEST_RISK_CONFIRM_REQUIRED') return err.detail;
    if (err?.detail?.detail?.code === 'GUEST_RISK_CONFIRM_REQUIRED') return err.detail.detail;
    if (typeof err?.message === 'string') {
        try {
            const parsed = JSON.parse(err.message);
            if (parsed?.code === 'GUEST_RISK_CONFIRM_REQUIRED') return parsed;
            if (parsed?.detail?.code === 'GUEST_RISK_CONFIRM_REQUIRED') return parsed.detail;
        } catch (_) {}
    }
    return null;
}

function pmsCiConfirmRiskGuest(guest) {
    const riskFlags = guest?.risk_flags || {
        is_blacklisted: !!guest?.is_blacklisted,
        has_unpaid_debt: !!guest?.has_unpaid_debt,
        unpaid_debt_amount: guest?.unpaid_debt_amount || 0,
        warnings: [],
    };
    if (!riskFlags.is_blacklisted && !riskFlags.has_unpaid_debt) {
        window._pmsCiRiskConfirmed = false;
        window._pmsCiRiskFlags = null;
        return true;
    }

    const warningText = pmsCiFormatRiskWarnings(riskFlags);
    const ok = window.confirm(
        `Cảnh báo CRM cho khách "${guest.full_name || guest.cccd || ''}":\n\n${warningText}\n\nBạn vẫn muốn tiếp tục nhận phòng cho khách này?`
    );
    window._pmsCiRiskConfirmed = ok;
    window._pmsCiRiskFlags = ok ? riskFlags : null;
    return ok;
}

function pmsCiRefreshGuestForm() {
    ['ci-name', 'ci-cccd', 'ci-id-expire', 'ci-birth', 'ci-phone', 'ci-guest-notes', 'ci-address', 'ci-province', 'ci-district', 'ci-ward', 'ci-vehicle'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.value = '';
            el.readOnly = false;
            el.classList.remove('is-invalid', 'is-warning');
            el.style.background = '';
            el.style.backgroundColor = '';
            el.style.color = '';
            el.style.cursor = '';
        }
    });
    // Also clear readonly conversion display fields
    ['ci-new-province', 'ci-new-ward'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.value = ''; el.style.color = ''; }
    });
    const g = document.getElementById('ci-gender');
    if (g) { g.value = ''; g.disabled = false; }

    // Reset to old-mode radio (default)
    const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
    if (oldRadio) oldRadio.checked = true;
    if (newRadio) { newRadio.disabled = false; newRadio.style.display = ''; }
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');
    if (distGrp) distGrp.style.display = '';
    if (convGrp) convGrp.style.display = 'none';
    if (typeof vnSwitchMode === 'function') vnSwitchMode('old', false);

    // Reset toolbar
    document.getElementById('ci-add-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-update-guest-btn').style.display = 'none';
    document.getElementById('ci-cancel-edit-btn').style.display = 'none';
    document.getElementById('ci-refresh-btn').style.display = 'inline-flex';

    // Clear tax/invoice fields as well
    const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
    if (invoiceRadio0) {
        invoiceRadio0.checked = true;
        pmsCiToggleInvoice(invoiceRadio0);
    }
    document.getElementById('ci-tax-code').value = '';
    document.getElementById('ci-tax-contact').value = '';
    const companyNameReset = document.getElementById('ci-company-name');
    if (companyNameReset) companyNameReset.value = '';
    const companyAddressReset = document.getElementById('ci-company-address');
    if (companyAddressReset) companyAddressReset.value = '';

    // Remove any hint and reset existing guest ID
    const hintEl = document.getElementById('ci-cccd-hint');
    if (hintEl) hintEl.remove();
    window._pmsCiExistingGuestId = null;
    window._pmsCiIsOldGuest = false;

    // Remove autofill notice
    const autofillNotice = document.getElementById('ci-autofill-notice');
    if (autofillNotice) autofillNotice.remove();

    // Remove edit address button
    const editAddrBtn = document.getElementById('ci-edit-addr-btn');
    if (editAddrBtn) editAddrBtn.remove();

    // Reset address lock state
    window._pmsCiAddressLocked = false;

    // Hide address validation warning panel
    const warnPanel = document.getElementById('ci-addr-warning-panel');
    if (warnPanel) warnPanel.style.display = 'none';

    // Remove state badge
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.clearStateBadge) {
        PMS_ADDR.clearStateBadge();
    }

    pmsCiSetDepositMethod('Chi nhánh');
    pmsCiSetDepositLocked(false);
    pmsCiRenderReservationNotice({});

    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) { idTypeEl.value = 'cccd'; idTypeEl.disabled = false; pmsCiToggleIdFields(idTypeEl); }
    pmsCiUnlockAllRequiredFields();
    pmsCiResetGuestInputChrome();
}

async function pmsCiAddGuest() {
    const idx = window._ciEditIndex;
    if (idx !== undefined && idx !== null) {
        await pmsCiUpdateGuest();
        return;
    }
    const g = pmsCiGetFormGuest();
    const v = pmsCiValidateGuestForm(g);
    if (!v.valid) { return; }

    // Check for duplicates in JS list - if found, verify DB status
    if (g.cccd && pmsCiGuestList.some(xg => xg.cccd === g.cccd)) {
        const existingGuest = pmsCiGuestList.find(xg => xg.cccd === g.cccd);
        console.log('[CI] DUPLICATE found in local list:', existingGuest);

        // Cảnh báo khách đã có trong danh sách chờ nhận phòng
        pmsToast(`CẢNH BÁO: Khách với số giấy tờ ${g.cccd} đã có trong danh sách chờ nhận phòng.`, false);
        return;
    }

    // Real-time block for active CCCDs (for new CCCDs not in local list)
    if (g.cccd && g.cccd.length >= 3 && !pmsCiGuestList.some(xg => xg.cccd === g.cccd)) {
        try {
            const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
            console.log('[CI] Checking CCCD in DB:', g.cccd, 'URL:', url);
            const res = await pmsApi(url);
            console.log('[CI] CCCD check result:', JSON.stringify(res));

            if (res && res.is_active) {
                const currentRoom = pmsCiRoomNumber;
                const branchInfo = res.branch_name ? ` (${res.branch_name})` : '';
                console.log('[CI] CCCD is active at room:', res.room_number, 'Branch:', res.branch_name, 'Current room:', currentRoom);
                if (res.room_number === currentRoom) {
                    pmsToast(`CẢNH BÁO: Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}${branchInfo}.`, false);
                } else {
                    pmsToast(`CẢNH BÁO: Khách ${g.cccd} đang lưu trú tại phòng ${res.room_number}${branchInfo}.`, false);
                }
                return;
            } else {
                console.log('[CI] CCCD check: NOT active in DB');
            }
        } catch (e) {
            console.error('[CI] Error checking active CCCD', e);
            pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
            return;
        }
    }

    const total = pmsCiGuestList.length + 1;
    if (total > pmsCiMaxGuests) {
        pmsCiUpdateCapacityWarn();
    }
    pmsCiGuestList.push(g);
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
    // Tự động bật panel danh sách khách để user thấy đã thêm
    const panel = document.getElementById('ci-guest-list-panel');
    const btn = document.getElementById('ci-toggle-list-btn');
    if (panel && !panel.classList.contains('show')) {
        panel.classList.add('show');
    }
    if (btn) {
        btn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" stroke-width="2">
              <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
            Ẩn danh sách (<span id="ci-guest-count">${pmsCiGuestList.length}</span>)
        `;
    }
}

function pmsCiRenderGuestList() {
    const panel = document.getElementById('ci-guest-list-panel');
    if (!panel) return;
    if (pmsCiGuestList.length === 0) {
        panel.innerHTML = '<p style="margin:0;font-size:13px;color:#64748b;">Chưa thêm khách nào. Nhập thông tin và bấm "Thêm khách".</p>';
        return;
    }
    panel.innerHTML = pmsCiGuestList.map((g, i) => `
        <span class="guest-chip">
          <span class="ci-chip-icon">${pmsGenderIcon(g.gender)}</span>
          <span onclick="pmsCiEditGuest(${i})" style="cursor:pointer;">${pmsEscapeHtml(g.full_name)}</span>
          <button type="button" onclick="pmsCiRemoveGuest(${i})" style="background:none;border:none;cursor:pointer;padding:0 4px;color:#94a3b8;font-size:16px;line-height:1;" title="Xóa">×</button>
        </span>
    `).join('');
}

async function pmsCiEditGuest(i) {
    const g = pmsCiGuestList[i];
    if (!g) return;

    // Store edit index first
    window._ciEditIndex = i;

    // ========== PHASE 1: Fill ALL values first ==========
    document.getElementById('ci-name').value = g.full_name || '';
    document.getElementById('ci-gender').value = g.gender || '';
    document.getElementById('ci-birth').value = g.birth_date ? String(g.birth_date).slice(0, 10) : '';
    document.getElementById('ci-phone').value = g.phone || '';
    document.getElementById('ci-cccd').value = g.cccd || '';
    document.getElementById('ci-id-type').value = g.id_type || 'cccd';
    if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(document.getElementById('ci-id-expire'), g.id_expire);
    else document.getElementById('ci-id-expire').value = g.id_expire ? String(g.id_expire).slice(0, 10) : '';
    document.getElementById('ci-vehicle').value = g.vehicle || '';
    document.getElementById('ci-guest-notes').value = g.notes || '';
    document.getElementById('ci-nationality').value = g.nationality || 'VNM - Việt Nam';
    document.getElementById('ci-address').value = g.address || '';

    // Restore invoice fields (both old and new guests can have invoice)
    if (g.tax_code || g.invoice_contact || g.company_name) {
        const invoiceRadio1 = document.querySelector('input[name="ci-invoice"][value="1"]');
        if (invoiceRadio1) invoiceRadio1.checked = true;
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.value = g.tax_code || '';
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.value = g.invoice_contact || '';
        const companyNameEl = document.getElementById('ci-company-name');
        if (companyNameEl) companyNameEl.value = g.company_name || '';
        const companyAddressEl = document.getElementById('ci-company-address');
        if (companyAddressEl) companyAddressEl.value = g.company_address || '';
        // Show invoice fields wrapper
        const invoiceFields = document.getElementById('ci-invoice-fields');
        if (invoiceFields) invoiceFields.style.display = 'block';
        // Call toggle to sync visibility state
        if (invoiceRadio1) pmsCiToggleInvoice(invoiceRadio1);
    } else {
        const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
        if (invoiceRadio0) invoiceRadio0.checked = true;
        const invoiceFields = document.getElementById('ci-invoice-fields');
        if (invoiceFields) invoiceFields.style.display = 'none';
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.value = '';
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.value = '';
        const companyNameEl = document.getElementById('ci-company-name');
        if (companyNameEl) companyNameEl.value = '';
        // Call toggle to sync visibility state
        if (invoiceRadio0) pmsCiToggleInvoice(invoiceRadio0);
    }

    // Handle address - load province/ward data and set values
    const hasOldData = !!(g.old_city || g.old_ward || g.old_district);
    const addrType = g.address_type || 'new';

    const pEl = document.getElementById('ci-province');
    const wEl = document.getElementById('ci-ward');
    const dEl = document.getElementById('ci-district');
    const nProvEl = document.getElementById('ci-new-province');
    const nWardEl = document.getElementById('ci-new-ward');
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
    const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');

    if (hasOldData) {
        // Load OLD province datalist and fill OLD datalist inputs
        if (typeof vnLoadOldProvinces === 'function') {
            const oldProvinces = await vnLoadOldProvinces();
            vnPopulateDatalist('dl-province', oldProvinces);
        }
        // Fill NEW readonly conversion display FIRST
        if (nProvEl) { nProvEl.value = g.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = g.ward || ''; nWardEl.style.color = '#15803d'; }
        // Set OLD values
        if (pEl) pEl.value = g.old_city || '';
        if (pEl && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(pEl);
        if (dEl) dEl.value = g.old_district || '';
        if (dEl && typeof vnOnDistrictChange === 'function') await vnOnDistrictChange(dEl);
        if (wEl) wEl.value = g.old_ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ward');
            if (dl) {
                for (const opt of dl.options) {
                    if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                        wEl.value = opt.value;
                        break;
                    }
                }
            }
            wEl.dispatchEvent(new Event('blur'));
        }
        if (dEl) dEl.dispatchEvent(new Event('blur'));
        if (pEl) pEl.dispatchEvent(new Event('blur'));
        // Set radio
        if (oldRadio) oldRadio.checked = true;
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = '';
    } else {
        // Load NEW province datalist
        if (typeof vnLoadNewProvinces === 'function' && typeof vnPopulateDatalist === 'function') {
            const provinces = await vnLoadNewProvinces();
            vnPopulateDatalist('dl-province', provinces.map(p => ({ name: p.name, short: p.short })));
        }
        if (pEl) pEl.value = g.city || '';
        if (pEl && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(pEl);
        if (wEl) wEl.value = g.ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ward');
            if (dl) {
                for (const opt of dl.options) {
                    if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                        wEl.value = opt.value;
                        break;
                    }
                }
            }
            wEl.dispatchEvent(new Event('blur'));
        }
        if (pEl) pEl.dispatchEvent(new Event('blur'));
        if (newRadio) newRadio.checked = true;
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
    }

    // ALWAYS hide conversion chip when editing from list (only appears for new manual input in old mode)
    if (convGrp) convGrp.style.display = 'none';

    pmsCiToggleIdFields(document.getElementById('ci-id-type'));

    // ========== PHASE 2: Set lock state based on guest type ==========
    if (g.from_old) {
        // OLD GUEST: Lock most fields
        window._pmsCiIsOldGuest = true;
        window._pmsCiExistingGuestId = g.id || null;

        // Lock ALL fields
        pmsCiLockAllFields();

        // Unlock specific editable fields only
        const unlockFields = ['ci-phone', 'ci-guest-notes', 'ci-id-expire', 'ci-vehicle'];
        unlockFields.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.readOnly = false;
        });

        // Unlock invoice fields
        const invoiceRadios = document.querySelectorAll('input[name="ci-invoice"]');
        invoiceRadios.forEach(r => r.disabled = false);
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.readOnly = false;
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.readOnly = false;

        // Lock address inputs (they're already locked by pmsCiLockAllFields)
        [pEl, dEl, wEl].forEach(el => {
            if (el) el.readOnly = true;
        });

        // Show autofill notice
        pmsCiShowAutofillNotice(g.full_name, g.cccd);
    } else {
        // NEW GUEST: Unlock all fields
        window._pmsCiIsOldGuest = false;
        window._pmsCiExistingGuestId = null;
        pmsCiUnlockAllFields();

        // Remove autofill notice
        const existingNotice = document.getElementById('ci-autofill-notice');
        if (existingNotice) existingNotice.remove();
    }

    // Show/hide buttons
    document.getElementById('ci-add-guest-btn').style.display = 'none';
    document.getElementById('ci-update-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-cancel-edit-btn').style.display = 'inline-flex';
    document.getElementById('ci-refresh-btn').style.display = 'none';

    pmsToast('Đang chỉnh sửa khách. Bấm "Cập nhật" để lưu.');
}

function pmsCiCancelEdit() {
    window._ciEditIndex = null;
    pmsCiRefreshGuestForm();
    document.getElementById('ci-add-guest-btn').style.display = 'inline-flex';
    document.getElementById('ci-update-guest-btn').style.display = 'none';
    document.getElementById('ci-cancel-edit-btn').style.display = 'none';
    document.getElementById('ci-refresh-btn').style.display = 'inline-flex';
}

async function pmsCiUpdateGuest() {
    const idx = window._ciEditIndex;
    if (idx === undefined || idx === null || idx < 0 || idx >= pmsCiGuestList.length) {
        pmsToast('Không tìm thấy khách cần cập nhật', false);
        return;
    }
    const g = pmsCiGetFormGuest();
    if (!window.confirm(`Cập nhật thông tin khách "${g.full_name}"?`)) return;
    const v = pmsCiValidateGuestForm(g);
    if (!v.valid) { return; }

    // Check for duplicates in JS list
    if (g.cccd && pmsCiGuestList.some((xg, i) => i !== idx && xg.cccd === g.cccd)) {
        window.alert(`CẢNH BÁO: Số giấy tờ ${g.cccd} đã có trong danh sách khách chờ nhận phòng.\n\nVui lòng chọn khách khác hoặc xóa khách trùng lặp.`);
        pmsToast(`Số giấy tờ ${g.cccd} đã có trong danh sách. Không thể cập nhật trùng.`, false);
        return;
    }

    // Real-time block for active CCCDs
    if (g.cccd && g.cccd.length >= 3) {
        try {
            const url = `/api/pms/guests/check-active-cccd?cccd=${encodeURIComponent(g.cccd)}`;
            const res = await pmsApi(url);
            if (res && res.is_active) {
                const currentRoom = pmsCiRoomNumber;
                const branchInfo = res.branch_name ? ` (${res.branch_name})` : '';
                if (res.room_number === currentRoom) {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}${branchInfo}. Không thể thêm trùng.`);
                    pmsToast(`Khách ${g.cccd} đã có trong danh sách phòng ${currentRoom}${branchInfo}. Không thể thêm trùng.`, false);
                } else {
                    window.alert(`CẢNH BÁO: Khách ${g.cccd} đang lưu trú tại phòng ${res.room_number}${branchInfo}. Không thể Cập nhật.`);
                    pmsToast(`Khách hàng có số giấy tờ ${g.cccd} đang lưu trú tại phòng ${res.room_number}${branchInfo}. Không thể Cập nhật.`, false);
                }
                return;
            }
        } catch (e) {
            console.error('Error checking active CCCD', e);
            pmsToast('Lỗi hệ thống khi kiểm tra CCCD: ' + e.message, false);
            return;
        }
    }
    pmsCiGuestList[idx] = g;
    window._ciEditIndex = null;
    pmsCiRefreshGuestForm();
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
    pmsToast('Đã cập nhật thông tin khách');
}

function pmsCiRemoveGuest(i) {
    pmsCiGuestList.splice(i, 1);
    pmsCiUpdateGuestCount();
    pmsCiUpdateCapacityWarn();
    pmsCiRenderGuestList();
}

// ─── Service & Surcharge Management ──────────────────────────────────────────
function pmsCiAddItem(type) {
    const prefix = type === 'SERVICE' ? 'svc' : 'sur';
    const nameEl = document.getElementById(`ci-${prefix}-name`);
    const priceEl = document.getElementById(`ci-${prefix}-price`);

    const name = nameEl.value.trim();
    const priceRaw = priceEl.value.replace(/[^0-9]/g, '');
    const price = parseInt(priceRaw) || 0;

    if (!name) { pmsToast(`Vui lòng nhập tên ${type === 'SERVICE' ? 'dịch vụ' : 'phát sinh'}`, false); nameEl.focus(); return; }
    if (price <= 0) { pmsToast('Vui lòng nhập số tiền', false); priceEl.focus(); return; }

    const item = { name, price, qty: 1 };
    if (type === 'SERVICE') pmsCiServiceList.push(item);
    else pmsCiSurchargeList.push(item);
    
    // Clear inputs
    nameEl.value = '';
    priceEl.value = '';
    nameEl.focus();

    pmsCiRenderItems();
    if (typeof pmsCalcPrice === 'function') pmsCalcPrice();
}

function pmsCiRemoveItem(type, i) {
    if (type === 'SERVICE') pmsCiServiceList.splice(i, 1);
    else pmsCiSurchargeList.splice(i, 1);
    pmsCiRenderItems();
    if (typeof pmsCalcPrice === 'function') pmsCalcPrice();
}

function pmsCiRenderItems() {
    const renderList = (list, elementId, type) => {
        const listEl = document.getElementById(elementId);
        if (!listEl) return;
        listEl.innerHTML = list.map((s, i) => {
            const qtyStr = s.qty > 1 ? ` <span style="opacity:0.6; font-size:10px;">x${s.qty}</span>` : '';
            return `
            <div class="rd-mini-list-item" style="margin-bottom: 4px; animation: ciSlideUp 0.3s ease;">
                <span class="rd-mini-list-name" style="font-size: 11.5px;">${pmsEscapeHtml(s.name)}${qtyStr}</span>
                <span class="rd-mini-list-val" style="font-size: 12px;">${pmsMoney(s.price * s.qty)}</span>
                <button type="button" class="rd-mini-delete-btn" style="opacity: 1;" onclick="pmsCiRemoveItem('${type}', ${i})">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </button>
            </div>
            `;
        }).join('');
    };

    renderList(pmsCiServiceList, 'ci-svc-list', 'SERVICE');
    renderList(pmsCiSurchargeList, 'ci-sur-list', 'SURCHARGE');

    // Update totals
    const svcTot = pmsCiServiceList.reduce((acc, s) => acc + s.price * s.qty, 0);
    const surTot = pmsCiSurchargeList.reduce((acc, s) => acc + s.price * s.qty, 0);
    
    const elST = document.getElementById('ci-svc-total');
    const elSurT = document.getElementById('ci-sur-total');
    if (elST) elST.textContent = pmsMoney(svcTot);
    if (elSurT) elSurT.textContent = pmsMoney(surTot);

    // Cập nhật Chi phí dự kiến bên Thanh toán
    _renderBreakdown(window._pmsLastPricingPreview);
}

function pmsCiUpdateGuestCount() {
    const el = document.getElementById('ci-guest-count');
    if (el) el.textContent = String(pmsCiGuestList.length);
}

function pmsCiUpdateCapacityWarn() {
    const primary = pmsCiGetFormGuest().full_name ? 1 : 0;
    const total = pmsCiGuestList.length + primary;
    const warnEl = document.getElementById('ci-capacity-warn');
    if (!warnEl) return;
    if (total > pmsCiMaxGuests) {
        warnEl.textContent = `Số khách (${total}) vượt quá giới hạn phòng (tối đa ${pmsCiMaxGuests} người). Vui lòng giảm số lượng khách hoặc chọn phòng khác.`;
        warnEl.classList.add('show');
    } else {
        warnEl.classList.remove('show');
    }
}

function pmsCiScanCode() {
    openScanModal(async (parsed) => {
        await pmsCiFillFromScan(parsed);
        pmsToast(`Đã quét: ${parsed.name}`, true);
    });
}

// ─── Fill checkin form from parsed CCCD scan data ──────────────────────────────
async function pmsCiFillFromScan(parsed) {
    if (!parsed.is_valid) return;

    const cccdEl  = document.getElementById('ci-cccd');
    const idTypeEl = document.getElementById('ci-id-type');
    const nameEl   = document.getElementById('ci-name');

    const isCmnd = parsed.card_type === 'CMND';
    const idValue = isCmnd
        ? (parsed.old_id || parsed.id_number || parsed.cccd || '')
        : (parsed.id_number || parsed.cccd || '');

    // ── Step 1: Check if CCCD exists in DB ────────────────────────────────
    const cccdToCheck = idValue.trim().toUpperCase();
    if (cccdToCheck && cccdToCheck.length >= 3) {
        try {
            const searchRes = await pmsApi(`/api/pms/crm/guests/search?cccd=${encodeURIComponent(cccdToCheck)}`);
            if (searchRes && searchRes.guests && searchRes.guests.length > 0) {
                const guest = searchRes.guests[0];
                // Found existing guest — use DB data and lock form
                if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.markAutofill) {
                    PMS_ADDR.markAutofill();
                }
                await pmsCiFillFromExisting(guest);
                if (cccdEl) cccdEl.value = cccdToCheck;
                pmsToast(`Đã tìm thấy khách: ${guest.full_name || cccdToCheck}`, true);
                return;
            }
        } catch (e) {
            console.warn('[CI] Scan: DB lookup failed, filling from scan data:', e);
        }
    }

    // ── Step 2: No DB match — fill from scan, unlock all fields ───────────
    if (cccdEl) {
        cccdEl.value = idValue;
        cccdEl.classList.remove('is-invalid');
    }
    if (idTypeEl) {
        idTypeEl.value = isCmnd ? 'cmnd' : 'cccd';
        pmsCiToggleIdFields(idTypeEl);
    }
    if (nameEl) {
        nameEl.value = pmsTitleCase(parsed.name || '');
        nameEl.classList.remove('is-invalid');
    }
    const genderEl = document.getElementById('ci-gender');
    if (genderEl && parsed.gender) genderEl.value = parsed.gender;
    const birthEl = document.getElementById('ci-birth');
    if (birthEl && parsed.dob) {
        birthEl.value = pmsScanDateToISO(parsed.dob);
        pmsCiCheckBirth(birthEl);
    }
    const expireEl = document.getElementById('ci-id-expire');
    if (expireEl && parsed.expiry_date) {
        if (parsed.expiry_date === 'Không thời hạn' && typeof pmsSetCCCDPermanentExpiry === 'function') {
            pmsSetCCCDPermanentExpiry(expireEl);
        } else {
            if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(expireEl, parsed.expiry_date);
            else expireEl.value = pmsScanDateToISO(parsed.expiry_date);
            pmsCiCheckIdExpire(expireEl);
        }
    }

    const cardType = parsed.card_type || 'CCCD_CU';
    if (typeof pmsMatchAddressToForm === 'function') {
        await pmsMatchAddressToForm({ ...(parsed.address || {}), address_mode: parsed.address_mode }, 'ci', cardType);
    }

    if (typeof pmsShowAddressValidationIssues === 'function') {
        pmsShowAddressValidationIssues('ci');
    }

    // Unlock fields for manual entry
    pmsCiUnlockAllFields();
    if (typeof pmsSyncCCCDExpiryReadonly === 'function') {
        pmsSyncCCCDExpiryReadonly({
            idTypeEl: document.getElementById('ci-id-type'),
            birthEl: document.getElementById('ci-birth'),
            expireEl: document.getElementById('ci-id-expire'),
            checkExpire: pmsCiCheckIdExpire,
        });
    }
    window._pmsCiExistingGuestId = null;
    window._pmsCiIsOldGuest = false;
    const existingNotice = document.getElementById('ci-autofill-notice');
    if (existingNotice) existingNotice.remove();

    const phoneEl = document.getElementById('ci-phone');
    if (phoneEl) phoneEl.focus();
}

/**
 * Fill CI form from existing guest (DB data) — lock all fields except editable ones.
 * Mirrors pmsCiFillGuestFromOld logic.
 */
async function pmsCiFillFromExisting(guest) {
    if (!pmsCiConfirmRiskGuest(guest)) return;

    // 1. Fill basic fields
    const nameEl = document.getElementById('ci-name');
    const genderEl = document.getElementById('ci-gender');
    const nationalityEl = document.getElementById('ci-nationality');
    const idTypeEl = document.getElementById('ci-id-type');
    const cccdEl = document.getElementById('ci-cccd');
    const idExpireEl = document.getElementById('ci-id-expire');
    const birthEl = document.getElementById('ci-birth');
    const phoneEl = document.getElementById('ci-phone');
    const vehicleEl = document.getElementById('ci-vehicle');
    const notesEl = document.getElementById('ci-guest-notes');
    const addrDetailEl = document.getElementById('ci-address');

    if (nameEl) nameEl.value = guest.full_name || '';
    if (genderEl) genderEl.value = guest.gender || '';
    if (nationalityEl) nationalityEl.value = guest.nationality || 'VNM - Việt Nam';
    if (cccdEl) cccdEl.value = guest.cccd || '';
    if (idTypeEl) {
        idTypeEl.value = (guest.id_type || 'cccd').toLowerCase();
        pmsCiToggleIdFields(idTypeEl);
    }
    if (idExpireEl) {
        if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(idExpireEl, guest.id_expire);
        else idExpireEl.value = guest.id_expire ? String(guest.id_expire).slice(0, 10) : '';
        pmsCiCheckIdExpire(idExpireEl);
    }
    if (birthEl && guest.birth_date) {
        birthEl.value = String(guest.birth_date).slice(0, 10);
        pmsCiCheckBirth(birthEl);
    }
    if (phoneEl) phoneEl.value = guest.phone || '';
    if (vehicleEl) vehicleEl.value = guest.vehicle || '';
    if (notesEl) notesEl.value = guest.notes || '';

    // Invoice
    if (guest.tax_code || guest.invoice_contact || guest.company_name) {
        const invoiceRadio1 = document.querySelector('input[name="ci-invoice"][value="1"]');
        const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
        if (invoiceRadio1) invoiceRadio1.checked = true;
        const taxCodeEl = document.getElementById('ci-tax-code');
        const taxContactEl = document.getElementById('ci-tax-contact');
        const companyNameEl = document.getElementById('ci-company-name');
        const companyAddressEl = document.getElementById('ci-company-address');
        if (taxCodeEl) taxCodeEl.value = guest.tax_code || '';
        if (taxContactEl) taxContactEl.value = guest.invoice_contact || '';
        if (companyNameEl) companyNameEl.value = guest.company_name || '';
        if (companyAddressEl) companyAddressEl.value = guest.company_address || '';
        const invoiceFields = document.getElementById('ci-invoice-fields');
        if (invoiceFields) invoiceFields.style.display = 'block';
        if (invoiceRadio1) pmsCiToggleInvoice(invoiceRadio1);
    } else {
        const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
        if (invoiceRadio0) invoiceRadio0.checked = true;
        const invoiceFields = document.getElementById('ci-invoice-fields');
        if (invoiceFields) invoiceFields.style.display = 'none';
        if (invoiceRadio0) pmsCiToggleInvoice(invoiceRadio0);
    }

    // 2. Fill address
    const hasOldData = !!(guest.old_city || guest.old_district || guest.old_ward);
    const addrType = hasOldData ? 'old' : 'new';
    const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
    const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');

    if (addrType === 'old') {
        if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = true; }
        if (newRadio) newRadio.disabled = true;
        if (distGrp) distGrp.style.display = '';
        if (convGrp) convGrp.style.display = 'none';
    } else {
        if (newRadio) newRadio.checked = true;
        if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }
        if (distGrp) distGrp.style.display = 'none';
        if (convGrp) convGrp.style.display = 'none';
    }

    const pEl = document.getElementById('ci-province');
    const wEl = document.getElementById('ci-ward');
    const dEl = document.getElementById('ci-district');
    const nProvEl = document.getElementById('ci-new-province');
    const nWardEl = document.getElementById('ci-new-ward');

    if (hasOldData) {
        if (typeof vnLoadOldProvinces === 'function') {
            const oldProvinces = await vnLoadOldProvinces();
            vnPopulateDatalist('dl-province', oldProvinces);
        }
        if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }
        if (pEl) pEl.value = guest.old_city || '';
        if (pEl && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(pEl);
        if (dEl) dEl.value = guest.old_district || '';
        if (dEl && typeof vnOnDistrictChange === 'function') await vnOnDistrictChange(dEl);
        if (wEl) wEl.value = guest.old_ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ward');
            if (dl) {
                for (const opt of dl.options) {
                    if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                        wEl.value = opt.value; break;
                    }
                }
            }
            wEl.dispatchEvent(new Event('blur'));
        }
        if (dEl) dEl.dispatchEvent(new Event('blur'));
        if (pEl) pEl.dispatchEvent(new Event('blur'));
    } else {
        if (typeof vnLoadNewProvinces === 'function' && typeof vnPopulateDatalist === 'function') {
            const provinces = await vnLoadNewProvinces();
            vnPopulateDatalist('dl-province', provinces.map(p => ({ name: p.name, short: p.short })));
        }
        if (pEl) pEl.value = guest.city || '';
        if (pEl && typeof vnOnProvinceChange === 'function') await vnOnProvinceChange(pEl);
        if (wEl) wEl.value = guest.ward || '';
        if (wEl && wEl.value) {
            const dl = document.getElementById('dl-ward');
            if (dl) {
                for (const opt of dl.options) {
                    if (opt.value.trim().toLowerCase() === wEl.value.trim().toLowerCase()) {
                        wEl.value = opt.value; break;
                    }
                }
            }
            wEl.dispatchEvent(new Event('blur'));
        }
        if (pEl) pEl.dispatchEvent(new Event('blur'));
    }
    if (addrDetailEl) addrDetailEl.value = guest.address || '';

    // 3. Lock all fields
    pmsCiLockAllFields();

    // Unlock invoice fields
    document.querySelectorAll('input[name="ci-invoice"]').forEach(r => r.disabled = false);
    const taxCodeEl = document.getElementById('ci-tax-code');
    if (taxCodeEl) taxCodeEl.readOnly = false;
    const taxContactEl = document.getElementById('ci-tax-contact');
    if (taxContactEl) taxContactEl.readOnly = false;

    // Force critical fields after lock
    if (cccdEl) { cccdEl.value = guest.cccd || ''; cccdEl.readOnly = true; }
    if (idTypeEl) idTypeEl.disabled = true;
    if (nameEl) nameEl.readOnly = true;
    if (genderEl) genderEl.disabled = true;
    if (birthEl) birthEl.readOnly = true;
    if (nationalityEl) nationalityEl.readOnly = true;

    if (pEl) { pEl.readOnly = true; pEl.style.background = '#f0fdf4'; }
    if (dEl) { dEl.readOnly = true; dEl.style.background = '#f0fdf4'; }
    if (wEl) { wEl.readOnly = true; wEl.style.background = '#f0fdf4'; }
    if (addrDetailEl) { addrDetailEl.readOnly = true; addrDetailEl.style.background = '#f0fdf4'; }

    if (phoneEl) phoneEl.readOnly = false;
    if (notesEl) notesEl.readOnly = false;
    if (vehicleEl) vehicleEl.readOnly = false;
    if (idExpireEl) idExpireEl.readOnly = false;

    // 4. Store state
    window._pmsCiExistingGuestId = guest.id;
    window._pmsCiIsOldGuest = true;

    // 5. State badge
    if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR._updateStateBadge) {
        PMS_ADDR._updateStateBadge('TRUSTED', 'Địa chỉ từ dữ liệu cũ', 'green');
    }

    // 6. Autofill notice
    pmsCiShowAutofillNotice(guest.full_name, guest.cccd);
}

window.pmsCiFillFromScan = pmsCiFillFromScan;
window.pmsCiFillFromExisting = pmsCiFillFromExisting;
window.pmsCiScanCode = pmsCiScanCode;

function pmsCiToggleGuestList() {
    if (pmsCiGuestList.length === 0) {
        alert('Danh sách khách đang trống!');
        return;
    }
    const panel = document.getElementById('ci-guest-list-panel');
    const btn = document.getElementById('ci-toggle-list-btn');
    if (panel) {
        panel.classList.toggle('show');
        if (btn) {
            const isShown = panel.classList.contains('show');
            btn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="2">
                  <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
                  <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
                </svg>
                ${isShown ? 'Ẩn danh sách' : 'Hiện danh sách'} (<span id="ci-guest-count">${pmsCiGuestList.length}</span>)
            `;
        }
    }
}

let _pmsCalcPriceTimer = null;
let _pmsCalcPriceSeq = 0;

async function pmsCalcPrice() {
    clearTimeout(_pmsCalcPriceTimer);
    _pmsCalcPriceTimer = setTimeout(_pmsCalcPriceExec, 250);
}

async function _pmsCalcPriceExec() {
    const ciV = document.getElementById('ci-in')?.value;
    const coV = document.getElementById('ci-out')?.value;
    const hero = document.getElementById('ci-hero-amount');
    const heroPrice = document.getElementById('ci-hero-price');
    if (!ciV) { if (hero) hero.textContent = '—'; if (heroPrice) heroPrice.classList.remove('ci-hero-loading'); _hideBreakdown(); return; }

    const roomTypeId = pmsCi.room_type_id;
    if (!roomTypeId) { if (hero) hero.textContent = '—'; if (heroPrice) heroPrice.classList.remove('ci-hero-loading'); _hideBreakdown(); return; }

    if (heroPrice) heroPrice.classList.add('ci-hero-loading');

    const stayType = coV ? 'NIGHT' : 'AUTO';
    const seq = ++_pmsCalcPriceSeq;

    // Xác định check_out gửi lên backend:
    // - Có checkout → dùng giá trị user nhập
    // - Không có checkout + check-in đã qua → dùng now (tính giá live)
    // - Không có checkout + check-in = now/tương lai → gửi rỗng (backend fallback min_hours)
    let effectiveCo = '';
    if (coV) {
        effectiveCo = coV;
    } else {
        const ciDate = new Date(ciV);
        const now = new Date();
        const diffMs = now.getTime() - ciDate.getTime();
        if (diffMs > 600000) {
            const tzOff = now.getTimezoneOffset() * 60000;
            effectiveCo = new Date(now.getTime() - tzOff).toISOString().slice(0, 16);
        }
    }

    try {
        const data = await pmsApi('/api/pms/pricing/preview', {
            method: 'POST',
            body: new URLSearchParams({
                room_type_id: roomTypeId,
                check_in: ciV,
                check_out: effectiveCo,
                stay_type: stayType,
            }),
        });
        // Bỏ qua response cũ nếu đã có request mới hơn
        if (seq !== _pmsCalcPriceSeq) return;
        if (window._pmsCiOtaPricing?.actualTotal) {
            data.ota_price_mode = 'manual_channel_total';
            data.ota_actual_total = window._pmsCiOtaPricing.actualTotal;
            data.ota_channel = window._pmsCiOtaPricing.channel;
            data.pms_reference_total = Number(data.total || 0);
            window._pmsCiOtaPricing.referenceTotal = Number(data.total || 0);
        }
        window._pmsLastPricingPreview = data;
        if (heroPrice) heroPrice.classList.remove('ci-hero-loading');
        _renderBreakdown(data);
    } catch (e) {
        if (seq !== _pmsCalcPriceSeq) return;
        console.warn('[pmsCalcPrice] preview failed:', e);
        if (hero) hero.textContent = '—';
        if (heroPrice) heroPrice.classList.remove('ci-hero-loading');
        _hideBreakdown();
    }
}


function _renderBreakdown(data) {
    const heroAmount = document.getElementById('ci-hero-amount');
    const heroStd     = document.getElementById('ci-bd-std-label');
    const rowsEl      = document.getElementById('ci-bd-rows');
    const totalEl     = document.getElementById('ci-bd-total');
    const bdCard      = document.getElementById('ci-bd-card');
    const bdEmpty     = document.getElementById('ci-bd-empty');

    // 1. Luôn tính toán tổng tiền (Phòng + Dịch vụ + Phát sinh)
    let finalTotal = (data && data.total) ? data.total : 0;
    const pmsReferenceTotal = finalTotal;
    const otaPricing = window._pmsCiOtaPricing;
    if (otaPricing?.actualTotal) finalTotal = otaPricing.actualTotal;
    if (pmsCiServiceList) {
        pmsCiServiceList.forEach(s => {
            finalTotal += (parseFloat(s.price) || 0) * (parseInt(s.qty) || 1);
        });
    }
    if (pmsCiSurchargeList) {
        pmsCiSurchargeList.forEach(s => {
            finalTotal += (parseFloat(s.price) || 0) * (parseInt(s.qty) || 1);
        });
    }

    // 2. Cập nhật Hero Amount ngay lập tức
    if (heroAmount) {
        if (finalTotal > 0) heroAmount.textContent = pmsMoney(finalTotal);
        else heroAmount.textContent = '—';
    }

    if (!rowsEl) return;

    // Std range label
    const cfg = (data && data.config) ? data.config : {};
    const coV = document.getElementById('ci-out')?.value;
    const ciV = document.getElementById('ci-in')?.value;
    if (heroStd) {
        if (otaPricing?.actualTotal) {
            heroStd.textContent = `Giá OTA thực thu${otaPricing.channel ? ` • ${otaPricing.channel}` : ''}`;
        } else if (!coV && data?.pricing_mode === 'HOUR') {
            const ciDate = ciV ? new Date(ciV) : null;
            const diffMs = ciDate ? (Date.now() - ciDate.getTime()) : 0;
            heroStd.textContent = diffMs > 600000
                ? `Phòng giờ • Tính đến hiện tại`
                : `Phòng giờ • Tối thiểu ${cfg.min_hours || 1}h`;
        } else {
            heroStd.textContent = `Khung chuẩn ${cfg.std_checkin_time || '14:00'} → ${cfg.std_checkout_time || '12:00'}`;
        }
    }

    const hasServices = (pmsCiServiceList && pmsCiServiceList.length > 0) || (pmsCiSurchargeList && pmsCiSurchargeList.length > 0);

    if ((!data || !data.breakdown || data.breakdown.length === 0) && !hasServices) {
        if (bdCard) bdCard.style.display = 'none';
        if (bdEmpty) bdEmpty.style.display = 'block';
        return;
    }

    if (bdCard) bdCard.style.display = 'block';
    if (bdEmpty) bdEmpty.style.display = 'none';

    if (bdCard) bdCard.style.display = 'block';
    if (bdEmpty) bdEmpty.style.display = 'none';

    const _hh = (iso) => {
        if (!iso) return '';
        const d = pmsParseDate(iso);
        if (isNaN(d.getTime())) return '';
        const p = n => String(n).padStart(2, '0');
        return `${p(d.getHours())}:${p(d.getMinutes())}`;
    };

    const labelMap = {
        EARLY_CHECKIN_FEE: 'Phí nhận sớm',
        LATE_CHECKOUT_FEE: 'Phí trả muộn',
        ROOM_CHARGE: 'Tiền phòng',
        HOURLY_CHARGE: 'Tiền phòng (giờ)',
        REFUND: 'Hoàn tiền',
        DISCOUNT_MANUAL: 'Giảm giá',
    };

    const iconMap = {
        EARLY_CHECKIN_FEE: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        LATE_CHECKOUT_FEE: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        ROOM_CHARGE: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
        HOURLY_CHARGE: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        REFUND: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>',
        DISCOUNT_MANUAL: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="19" y1="5" x2="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/></svg>',
    };

    const _fmtDate = (iso) => {
        if (!iso) return '';
        const d = pmsParseDate(iso);
        if (isNaN(d.getTime())) return '';
        const days = ['CN','T2','T3','T4','T5','T6','T7'];
        const p = n => String(n).padStart(2,'0');
        return `${days[d.getDay()]}, ${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
    };

    rowsEl.innerHTML = (data?.breakdown || []).map(item => {
        const name = labelMap[item.type] || item.type;
        const icon = iconMap[item.type] || iconMap.ROOM_CHARGE;
        const isRefund = item.amount < 0 || ['REFUND', 'DISCOUNT_MANUAL'].includes(item.type);
        const amtStr = isRefund
            ? `-${pmsMoney(Math.abs(item.amount))}`
            : pmsMoney(item.amount);

        const timeRange = item.start_iso && item.end_iso
            ? `${_hh(item.start_iso)} <span style="opacity:0.4; margin:0 4px;">→</span> ${_hh(item.end_iso)}`
            : '';
        const dateStr = item.start_iso ? _fmtDate(item.start_iso) : '';
        const durationStr = item.days ? `${item.days} ngày` : (item.hours ? `${item.hours} giờ` : '');

        return `
            <div style="
                background: #f8fafc;
                border-radius: 18px;
                padding: 14px 18px;
                display: grid;
                grid-template-columns: 2fr 2.5fr 1fr 1.5fr;
                align-items: center;
                gap: 20px;
                flex-shrink: 0;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                border: 1px solid transparent;
                white-space: nowrap;
            " onmouseover="this.style.borderColor='#e2e8f0'; this.style.transform='translateY(-1px)';" onmouseout="this.style.borderColor='transparent'; this.style.transform='none';">
                <div style="display:flex; align-items:center; gap:12px; min-width:0;">
                    <div style="width:36px; height:36px; background:white; border-radius:12px; color:#088395; display:flex; align-items:center; justify-content:center; flex-shrink:0; box-shadow: 0 4px 12px rgba(0,0,0,0.04);">
                        ${icon}
                    </div>
                    <div style="font-weight:850; font-size:13px; color:#093C5D; line-height:1.2; white-space:nowrap;" title="${name}">
                        ${name}
                    </div>
                </div>
                <div style="min-width:0;">
                    <div style="display:flex; flex-direction:column; gap:2px;">
                        <div style="font-weight:700; color:#093C5D; font-size:13px; font-family:'Outfit', sans-serif;">
                            ${timeRange || '—'}
                        </div>
                        <div style="font-size:10px; color:#64748b; font-weight:700;">
                            ${dateStr}
                        </div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:13px; font-weight:850; color:#093C5D;">${durationStr || '—'}</div>
                </div>
                <div style="text-align:right;">
                    <div style="font-family:'Outfit', sans-serif; font-weight:900; font-size:16px; color:${isRefund ? '#dc2626' : '#088395'}; white-space:nowrap;">
                        ${amtStr}
                    </div>
                </div>
            </div>`;
    }).join('');

    let additionalRows = '';
    if (pmsCiServiceList && pmsCiServiceList.length > 0) {
        additionalRows += pmsCiServiceList.map(s => {
            const qtyStr = s.qty > 1 ? `x${s.qty}` : '';
            return `
            <div style="background:#f0fdfa; border-radius:18px; padding:14px 18px; display:grid; grid-template-columns:2fr 2.5fr 1fr 1.5fr; align-items:center; gap:20px; border:1px solid transparent;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="width:36px; height:36px; background:white; border-radius:12px; color:#0891b2; display:flex; align-items:center; justify-content:center; flex-shrink:0; box-shadow:0 4px 12px rgba(0,0,0,0.04);">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
                    </div>
                    <div style="font-weight:850; font-size:13px; color:#0891b2;">Dịch vụ: ${pmsEscapeHtml(s.name)}</div>
                </div>
                <div></div>
                <div style="text-align:right; font-size:13px; font-weight:850; color:#093C5D;">${qtyStr || '—'}</div>
                <div style="text-align:right; font-family:'Outfit',sans-serif; font-weight:900; font-size:16px; color:#088395;">${pmsMoney(s.price * s.qty)}</div>
            </div>`;
        }).join('');
    }

    if (pmsCiSurchargeList && pmsCiSurchargeList.length > 0) {
        additionalRows += pmsCiSurchargeList.map(s => {
            const qtyStr = s.qty > 1 ? `x${s.qty}` : '';
            return `
            <div style="background:#fffbeb; border-radius:18px; padding:14px 18px; display:grid; grid-template-columns:2fr 2.5fr 1fr 1.5fr; align-items:center; gap:20px; border:1px solid transparent;">
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="width:36px; height:36px; background:white; border-radius:12px; color:#d97706; display:flex; align-items:center; justify-content:center; flex-shrink:0; box-shadow:0 4px 12px rgba(0,0,0,0.04);">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/></svg>
                    </div>
                    <div style="font-weight:850; font-size:13px; color:#d97706;">Phát sinh: ${pmsEscapeHtml(s.name)}</div>
                </div>
                <div></div>
                <div style="text-align:right; font-size:13px; font-weight:850; color:#093C5D;">${qtyStr || '—'}</div>
                <div style="text-align:right; font-family:'Outfit',sans-serif; font-weight:900; font-size:16px; color:#088395;">${pmsMoney(s.price * s.qty)}</div>
            </div>`;
        }).join('');
    }

    if (additionalRows) {
        rowsEl.innerHTML += `<div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #cbd5e1;"></div>` + additionalRows;
    }

    if (otaPricing?.actualTotal) {
        const delta = otaPricing.actualTotal - pmsReferenceTotal;
        rowsEl.innerHTML += `
            <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #cbd5e1;"></div>
            <div class="ci-bd-row fee-core">
                <span class="ci-bd-row-label"><span class="ci-bd-row-name">PMS tham chiếu</span></span>
                <span class="ci-bd-row-amount">${pmsMoney(pmsReferenceTotal)}</span>
            </div>
            <div class="ci-bd-row">
                <span class="ci-bd-row-label"><span class="ci-bd-row-name">Chênh lệch OTA</span></span>
                <span class="ci-bd-row-amount">${delta >= 0 ? '+' : '-'}${pmsMoney(Math.abs(delta))}</span>
            </div>`;
    }

    if (totalEl) totalEl.textContent = pmsMoney(finalTotal);
}

function _hideBreakdown() {
    const heroAmount = document.getElementById('ci-hero-amount');
    const bdCard = document.getElementById('ci-bd-card');
    const bdEmpty = document.getElementById('ci-bd-empty');
    if (heroAmount) heroAmount.textContent = '—';
    if (bdCard) bdCard.style.display = 'none';
    if (bdEmpty) bdEmpty.style.display = 'block';
}

async function submitCI() {
    console.log('[CI SUBMIT] ===== START submitCI =====');
    if (window._pmsCiReservationMode === true) {
        if (window.BookingHub && typeof window.BookingHub.submitReservationFromCi === 'function') {
            return window.BookingHub.submitReservationFromCi();
        }
        pmsToast('Không tìm thấy luồng lưu đặt phòng', false);
        return;
    }
    if (pmsCiSubmitting) return;
    
    try {
    // Check-in Time is required
    const ciAt = document.getElementById('ci-in').value;
    if (!ciAt) { pmsToast('Vui lòng chọn Thời gian nhận phòng', false); return; }

    // Address validation is handled inside pmsCiValidateGuestForm() below

    const formGuest = pmsCiGetFormGuest();
    const hasFormGuest = !!formGuest.full_name;
    const allGuests = [...pmsCiGuestList];

    console.log('[CI SUBMIT] formGuest:', JSON.stringify(formGuest));
    console.log('[CI SUBMIT] hasFormGuest:', hasFormGuest);
    console.log('[CI SUBMIT] pmsCiGuestList length:', pmsCiGuestList.length);
    console.log('[CI SUBMIT] pmsCiGuestList:', JSON.stringify(pmsCiGuestList.map(g => ({ name: g.full_name, cccd: g.cccd }))));

    // ─── VALIDATION: Stay Type & Time ───
    const stayType = document.getElementById('ci-type')?.value;
    const coVal = document.getElementById('ci-out')?.value;
    if (stayType === 'NIGHT' && !coVal) {
        pmsToast('Vui lòng chọn Ngày trả phòng dự kiến cho thuê Qua đêm.', false);
        const coEl = document.getElementById('ci-out');
        if (coEl) { coEl.classList.add('is-invalid'); coEl.focus(); }
        return;
    }

    // ─── TRƯỜNG HỢP 1: Có thông tin khách đang nhập trên form ───
    if (hasFormGuest) {
        console.log('[CI SUBMIT] Processing form guest (hasFormGuest = true)');

        console.log('[CI SUBMIT] Calling pmsCiValidateGuestForm...');
        const v = pmsCiValidateGuestForm(formGuest);
        if (!v.valid) { return; }

        // Check if this guest is already in pmsCiGuestList (prevent duplicates)
        const formCccd = (formGuest.cccd || '').trim().toUpperCase();
        console.log('[CI SUBMIT] formCccd:', formCccd);
        console.log('[CI SUBMIT] pmsCiGuestList:', JSON.stringify(pmsCiGuestList.map(g => ({ cccd: (g.cccd || '').trim().toUpperCase() }))));

        if (formCccd) {
            const foundIndex = pmsCiGuestList.findIndex(xg => (xg.cccd || '').trim().toUpperCase() === formCccd);
            console.log('[CI SUBMIT] foundIndex:', foundIndex);
            if (foundIndex !== -1) {
                console.log('[CI SUBMIT] DUPLICATE FOUND - Showing alert');
                window.alert(`CẢNH BÁO: Khách với số giấy tờ ${formGuest.cccd} đã có trong danh sách chờ nhận phòng.\n\nVui lòng xóa khách khỏi danh sách trước khi nhận phòng, hoặc chọn khách trong danh sách để chỉnh sửa.`);
                pmsToast(`Khách ${formGuest.cccd} đã có trong danh sách chờ. Vui lòng xóa trước khi nhận phòng.`, false);
                return;
            }
        }
        console.log('[CI SUBMIT] No duplicate found in local list');

        // Backend still blocks active/duplicate CCCD; skip the extra preflight call to keep check-in faster.

        // Thêm form guest làm primary vào đầu danh sách
        allGuests.unshift(formGuest);
        console.log('[CI SUBMIT] Added form guest to list, allGuests length:', allGuests.length);
    }
    
    // ─── TRƯỜNG HỢP 2: Form trống hoàn toàn ───
    // Khi form không có full_name và danh sách trống, kiểm tra các required fields để báo lỗi cụ thể
    // Thứ tự: Số giấy tờ -> Loại giấy tờ -> Ngày hết hạn -> Họ và tên -> Giới tính -> Ngày sinh -> Quốc tịch -> Địa chỉ
    if (!hasFormGuest && pmsCiGuestList.length === 0) {
        const cccdEl = document.getElementById('ci-cccd');
        const idTypeEl = document.getElementById('ci-id-type');
        const idExpireEl = document.getElementById('ci-id-expire');
        const nameEl = document.getElementById('ci-name');
        const genderEl = document.getElementById('ci-gender');
        const birthEl = document.getElementById('ci-birth');
        const natEl = document.getElementById('ci-nationality');

        // 1. Số giấy tờ
        if (!cccdEl?.value.trim()) {
            cccdEl?.classList.add('is-invalid');
            cccdEl?.focus();
            pmsToast('Vui lòng nhập Số giấy tờ', false);
            return;
        }
        // 2. Loại giấy tờ
        if (!idTypeEl?.value) {
            idTypeEl?.classList.add('is-invalid');
            idTypeEl?.focus();
            pmsToast('Vui lòng chọn Loại giấy tờ', false);
            return;
        }
        // 3. Ngày hết hạn (chỉ kiểm tra nếu giấy tờ có hạn)
        const idType = idTypeEl?.value || 'cccd';
        const noExpire = idType === 'cmnd' || idType === 'gplx';
        if (!noExpire && !idExpireEl?.value) {
            idExpireEl?.classList.add('is-invalid');
            idExpireEl?.focus();
            pmsToast('Vui lòng nhập Ngày hết hạn giấy tờ', false);
            return;
        }
        // 4. Họ và tên
        if (!nameEl?.value.trim()) {
            nameEl?.classList.add('is-invalid');
            nameEl?.focus();
            pmsToast('Vui lòng nhập Họ và tên', false);
            return;
        }
        // 5. Giới tính
        if (!genderEl?.value) {
            genderEl?.classList.add('is-invalid');
            genderEl?.focus();
            pmsToast('Vui lòng chọn Giới tính', false);
            return;
        }
        // 6. Ngày sinh
        if (!birthEl?.value) {
            birthEl?.classList.add('is-invalid');
            birthEl?.focus();
            pmsToast('Vui lòng nhập Ngày sinh', false);
            return;
        }
        // 7. Quốc tịch
        if (!natEl?.value.trim()) {
            natEl?.classList.add('is-invalid');
            natEl?.focus();
            pmsToast('Vui lòng chọn Quốc tịch', false);
            return;
        }
        // 8. Địa chỉ (chỉ kiểm tra nếu KHÔNG phải Passport/Visa và KHÔNG phải khách cũ auto-fill)
        const isForeign = idType === 'passport' || idType === 'visa';
        const isOldGuest = window._pmsCiIsOldGuest === true;
        if (!isForeign && !isOldGuest) {
            const provEl = document.getElementById('ci-province');
            const wardEl = document.getElementById('ci-ward');
            const addrEl = document.getElementById('ci-address');
            
            // Kiểm tra Tỉnh/TP - phải có giá trị
            if (!provEl?.value.trim()) {
                provEl?.classList.add('is-invalid');
                provEl?.focus();
                pmsToast('Vui lòng chọn Tỉnh/Thành phố', false);
                return;
            }
            // Kiểm tra Tỉnh/TP có trong datalist không
            if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-province', provEl.value)) {
                provEl.classList.add('is-invalid');
                provEl.focus();
                pmsToast(`"${provEl.value}" không hợp lệ.`, false);
                return;
            }
            
            // Kiểm tra Phường/Xã - phải có giá trị
            if (!wardEl?.value.trim()) {
                wardEl?.classList.add('is-invalid');
                wardEl?.focus();
                pmsToast('Vui lòng chọn Phường/Xã', false);
                return;
            }
            // Kiểm tra Phường/Xã có trong datalist không
            if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-ward', wardEl.value)) {
                wardEl.classList.add('is-invalid');
                wardEl.focus();
                pmsToast(`"${wardEl.value}" không hợp lệ.`, false);
                return;
            }
            
            if (!addrEl?.value.trim()) {
                addrEl?.classList.add('is-invalid');
                addrEl?.focus();
                pmsToast('Vui lòng nhập Địa chỉ chi tiết', false);
                return;
            }
        }
    }

    // ─── TRƯỜNG HỢP 3: Có CCCD/phone/id_type nhưng không có tên ───
    else if (formGuest.cccd || formGuest.phone || formGuest.address || formGuest.birth_date || (formGuest.id_type && formGuest.id_type !== 'cccd')) {
        console.log('[CI SUBMIT] TRƯỜNG HỢP 3 triggered - has data but checking...');
        console.log('[CI SUBMIT] formGuest.full_name:', formGuest.full_name);
        if (!formGuest.full_name) {
            pmsToast('Vui lòng nhập đầy đủ thông tin khách (Họ tên, CCCD, ngày sinh...) hoặc xoá các trường đã nhập.', false);
            const nameEl = document.getElementById('ci-name');
            if (nameEl) { nameEl.classList.add('is-invalid'); nameEl.focus(); }
            return;
        }
        console.log('[CI SUBMIT] TRƯỜNG HỢP 3 - formGuest has full_name, continuing...');
    }

    // ─── KIỂM TRA: Cần ít nhất 1 khách ───
    if (allGuests.length === 0) {
        pmsToast('Vui lòng nhập thông tin khách hàng và bấm "Nhận phòng" để tiếp tục.', false);
        return;
    }

    // ─── KIỂM TRA SỐ KHÁCH VƯỢT QUÁ ───
    if (allGuests.length > pmsCiMaxGuests) {
        pmsCiUpdateCapacityWarn();
    }

    // ─── KIỂM TRA TRÙNG CCCD TRONG DANH SÁCH ───
    const cccdMap = {};
    for (let i = 0; i < allGuests.length; i++) {
        const guest = allGuests[i];
        if (guest.cccd && guest.cccd.length >= 3) {
            const up = (guest.cccd || '').trim().toUpperCase();
            if (!cccdMap[up]) cccdMap[up] = [];
            cccdMap[up].push(i);
        }
    }
    // Check for duplicates in the combined list
    for (const cccd in cccdMap) {
        if (cccdMap[cccd].length > 1) {
            const indices = cccdMap[cccd];
            const names = indices.map(i => `"${allGuests[i].full_name}"`).join(', ');
            window.alert(`CẢNH BÁO: Số giấy tờ ${cccd} bị trùng lặp trong danh sách khách (${indices.length} lần): ${names}.\n\nVui lòng xóa bớt các khách trùng lặp.`);
            pmsToast(`Số giấy tờ ${cccd} bị trùng lặp ${indices.length} lần trong danh sách. Vui lòng xóa bớt.`, false);
            return;
        }
    }

    // ─── VALIDATE ALL GUESTS IN LIST ───
    for (let i = 0; i < allGuests.length; i++) {
        const g = allGuests[i];
        if (!g.full_name || !g.cccd || !g.gender || !g.birth_date) {
            const guestName = g.full_name || `Khách thứ ${i + 1}`;
            window.alert(`Thông tin khách "${guestName}" chưa đầy đủ (Thiếu Họ tên, Số giấy tờ, Giới tính hoặc Ngày sinh). Vui lòng kiểm tra lại.`);
            pmsToast(`Khách "${guestName}" thiếu thông tin bắt buộc.`, false);
            
            // Try to focus the guest for user to fix
            if (i === 0 && hasFormGuest) {
                 document.getElementById('ci-name')?.focus();
            } else {
                 const listIdx = hasFormGuest ? i - 1 : i;
                 if (typeof pmsCiEditGuest === 'function') pmsCiEditGuest(listIdx);
                 else pmsToast('Vui lòng chọn khách trong danh sách để bổ sung thông tin.', false);
            }
            return;
        }
    }

    const submitBtn = document.querySelector('button[onclick="submitCI()"]');
    let oriText = 'Nhận phòng';
    pmsCiSubmitting = true;
    pmsCiSetBusy(true, 'Đang nhận phòng...');
    if (submitBtn) {
        oriText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" style="margin-right:8px;" role="status" aria-hidden="true"></span> Đang xử lý...';
        submitBtn.style.opacity = '0.7';
    }

    const primary = allGuests[0];
    const fd = new FormData();
    const coV = document.getElementById('ci-out').value || '';
    fd.append('room_id', document.getElementById('ci-room-id').value);
    if (window._pmsBookingCheckinId) fd.append('booking_id', window._pmsBookingCheckinId);
    fd.append('stay_type', coV ? 'NIGHT' : 'HOUR');
    fd.append('check_in_at', document.getElementById('ci-in').value);
    const co_val = document.getElementById('ci-out').value;
    if (co_val) fd.append('check_out_at', co_val);

    // Deposit handling: remove dots/commas
    const rawDeposit = document.getElementById('ci-deposit').value || '0';
    const depositNum = rawDeposit.toString().replace(/[^0-9]/g, '');
    fd.append('deposit', depositNum);

    // Get selected deposit method from card UI
    const selectedCard = document.querySelector('.ci-dep-method-item.selected');
    const depositType = selectedCard ? selectedCard.dataset.value : 'Chi nhánh';
    fd.append('deposit_type', depositType);

    let meta = {};
    if (depositType === 'Công ty') {
        meta.beneficiary = document.getElementById('ci-deposit-beneficiary')?.value || '';
    } else if (depositType === 'OTA') {
        meta.ota_channel = document.getElementById('ci-deposit-ota')?.value || '';
        meta.ref_code = document.getElementById('ci-deposit-ref')?.value || '';
    }
    fd.append('deposit_meta', JSON.stringify(meta));

    fd.append('notes', document.getElementById('ci-notes').value || '');

    // Invoice handling
    // Check if the current form has an invoice being filled out
    const formInvoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    if (formInvoiceVal === '1') {
        const tCode = document.getElementById('ci-tax-code')?.value?.trim();
        const tContact = document.getElementById('ci-tax-contact')?.value?.trim();
        if (!tCode || !tContact) {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = oriText;
                submitBtn.style.opacity = '1';
            }
            pmsCiSubmitting = false;
            pmsCiSetBusy(false);
            alert("Vui lòng nhập Mã số thuế và Liên hệ gửi hoá đơn cho khách hiện tại!");
            return;
        }
    }

    // ── Get full guest data for primary guest ──
    // If form has guest from autofill preview, get data from form
    // Guest from list may be incomplete (only full_name + cccd)
    let guestData = primary;
    if (hasFormGuest && (!primary || window._pmsCiIsOldGuest)) {
        // Guest from autofill preview or new guest being typed
        guestData = Object.assign({}, primary || {}, pmsCiGetFormGuest());
        // Preserve the guest_id if it was set during autofill
        if (window._pmsCiExistingGuestId) {
            guestData.id = window._pmsCiExistingGuestId;
        }
    }

    // Decide the main room invoice
    const mainInvoiceGuest = allGuests.find(g => g.tax_code) || guestData || {};
    const requireInvoice = !!mainInvoiceGuest.tax_code;
    fd.append('require_invoice', requireInvoice ? 'true' : 'false');
    if (requireInvoice) {
        fd.append('tax_code', mainInvoiceGuest.tax_code);
        fd.append('tax_contact', mainInvoiceGuest.invoice_contact || '');
        fd.append('company_name', mainInvoiceGuest.company_name || '');
        fd.append('company_address', mainInvoiceGuest.company_address || '');
    }

    // Use guestData (from form) with fallback to primary (from list)
    const getGuest = (field, fallback = '') => guestData[field] || primary[field] || fallback;

    fd.append('guest_name', getGuest('full_name'));
    fd.append('guest_cccd', getGuest('cccd'));
    fd.append('guest_id_expire', getGuest('id_expire'));
    fd.append('guest_gender', getGuest('gender'));
    fd.append('guest_birth', getGuest('birth_date'));
    fd.append('guest_phone', getGuest('phone'));
    fd.append('guest_nationality', getGuest('nationality', 'VNM - Việt Nam'));

    // Send existing guest ID if found (for auto-update)
    if (window._pmsCiExistingGuestId) {
        fd.append('guest_id', window._pmsCiExistingGuestId);
    }

    // Address fields
    fd.append('vehicle', getGuest('vehicle'));
    fd.append('city', getGuest('city'));
    fd.append('district', getGuest('district'));
    fd.append('ward', getGuest('ward'));
    fd.append('address', getGuest('address'));
    fd.append('address_type', getGuest('address_type', 'new'));
    fd.append('new_city', getGuest('new_city', ''));
    fd.append('new_ward', getGuest('new_ward', ''));
    if (getGuest('old_city')) fd.append('old_city', getGuest('old_city'));
    if (getGuest('old_district')) fd.append('old_district', getGuest('old_district'));
    if (getGuest('old_ward')) fd.append('old_ward', getGuest('old_ward'));
    fd.append('guest_notes', getGuest('notes', ''));
    fd.append('guest_id_type', getGuest('id_type', 'cccd'));
    fd.append('risk_confirmed', window._pmsCiRiskConfirmed ? 'true' : 'false');
    const extra = allGuests.slice(1);
    if (extra.length) fd.append('extra_guests', JSON.stringify(extra));
    
    // Combine services and surcharges
    const combinedServices = [
        ...pmsCiServiceList.map(s => ({ ...s, category: 'SERVICE' })),
        ...pmsCiSurchargeList.map(s => ({ ...s, category: 'SURCHARGE' }))
    ];
    if (combinedServices.length) fd.append('services', JSON.stringify(combinedServices));
    if (window._pmsCiOtaPricing?.actualTotal) {
        fd.append('ota_actual_total', String(window._pmsCiOtaPricing.actualTotal));
        fd.append('pms_reference_total', String(window._pmsCiOtaPricing.referenceTotal || window._pmsLastPricingPreview?.total || 0));
        fd.append('ota_channel', window._pmsCiOtaPricing.channel || '');
    }

    try {
        console.log('[CI SUBMIT] Calling API /api/pms/checkin...');
        const r = await pmsApi('/api/pms/checkin', { method: 'POST', body: fd });
        console.log('[CI SUBMIT] API Success:', JSON.stringify(r));
        pmsCiCloseModal();
        pmsToast(r.message);

        const roomId = document.getElementById('ci-room-id')?.value;
        if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(roomId);
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
    } catch (e) {
        console.error('[CI SUBMIT] API Error:', e);
        const riskError = pmsCiExtractRiskError(e);
        if (riskError && pmsCiConfirmRiskGuest({
            full_name: getGuest('full_name'),
            cccd: getGuest('cccd'),
            risk_flags: riskError.risk_flags,
        })) {
            pmsCiSetBusy(true, 'Đang xác nhận cảnh báo...');
            fd.set('risk_confirmed', 'true');
            try {
                const retry = await pmsApi('/api/pms/checkin', { method: 'POST', body: fd });
                pmsCiCloseModal();
                pmsToast(retry.message);
                const roomId = document.getElementById('ci-room-id')?.value;
                if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(roomId);
                if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
                return;
            } catch (retryErr) {
                pmsToast(retryErr.message || 'Không thể nhận phòng', false);
                return;
            }
        }
        pmsToast(e.message, false);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = oriText;
            submitBtn.style.opacity = '1';
        }
        pmsCiSubmitting = false;
        pmsCiSetBusy(false);
    }
    } catch (outerError) {
        console.error('[CI SUBMIT] OUTER ERROR:', outerError);
        pmsToast('Lỗi: ' + outerError.message, false);
        pmsCiSubmitting = false;
        pmsCiSetBusy(false);
    }
}

// Export globally
window.openCI = openCI;
window.pmsCiOpenReservationModal = pmsCiOpenReservationModal;
window.pmsCiSetDepositMethod = pmsCiSetDepositMethod;
window.submitCI = submitCI;
window.pmsCalcPrice = pmsCalcPrice;
window.vnValidateDatalist = vnValidateDatalist;
window.vnValidateAddressFields = vnValidateAddressFields;

// Export ci- functions for HTML onclick handlers
window.ciRefreshGuestForm = pmsCiRefreshGuestForm;
window.ciAddGuest = pmsCiAddGuest;
window.ciEditGuest = pmsCiEditGuest;
window.ciCancelEdit = pmsCiCancelEdit;
window.ciUpdateGuest = pmsCiUpdateGuest;
window.ciRemoveGuest = pmsCiRemoveGuest;
window.ciToggleGuestList = pmsCiToggleGuestList;
window.ciScanCode = pmsCiScanCode;

// Service functions
window.pmsCiAddItem = pmsCiAddItem;
window.pmsCiRemoveItem = pmsCiRemoveItem;
window.pmsCiRenderItems = pmsCiRenderItems;

/**
 * Mở popup dịch vụ/phát sinh với mode Check-in
 */
function pmsCiOpenPopup(type) {
    window.isCiMode = true; // Bật flag để popup biết đang ở chế độ check-in
    if (type === 'SERVICE') {
        if (typeof pmsRdOpenService === 'function') pmsRdOpenService();
        else pmsToast('Popup dịch vụ chưa sẵn sàng. Vui lòng tải lại trang.', false);
    } else {
        if (typeof pmsRdOpenSurcharge === 'function') pmsRdOpenSurcharge();
        else pmsToast('Popup phát sinh chưa sẵn sàng. Vui lòng tải lại trang.', false);
    }
}
window.pmsCiOpenPopup = pmsCiOpenPopup;

function pmsCiToggleIdFields(select) {
    const val = select.value;
    const isForeign = val === 'passport' || val === 'visa';
    const noExpire = val === 'cmnd' || val === 'gplx';
    const expireEl = document.getElementById('ci-grp-expire');
    const addrSection = document.getElementById('ci-addr-section');
    const overlay = document.getElementById('ci-addr-lock-overlay');

    if (expireEl) expireEl.style.display = noExpire ? 'none' : 'block';

    if (isForeign) {
        if (addrSection) addrSection.classList.add('ci-addr-disabled');
        if (overlay) overlay.style.display = 'flex';
    } else {
        if (addrSection) addrSection.classList.remove('ci-addr-disabled');
        if (overlay) overlay.style.display = 'none';
    }

    if (typeof pmsSyncCCCDExpiryReadonly === 'function') {
        pmsSyncCCCDExpiryReadonly({
            idTypeEl: select,
            birthEl: document.getElementById('ci-birth'),
            expireEl: document.getElementById('ci-id-expire'),
            checkExpire: pmsCiCheckIdExpire,
        });
    }
}
window.pmsCiToggleIdFields = pmsCiToggleIdFields;

function pmsCiApplyCCCDExpiryFromBirth() {
    if (typeof pmsApplyCCCDExpiryFromBirth !== 'function') return false;
    return pmsApplyCCCDExpiryFromBirth({
        idTypeEl: document.getElementById('ci-id-type'),
        birthEl: document.getElementById('ci-birth'),
        expireEl: document.getElementById('ci-id-expire'),
        checkExpire: pmsCiCheckIdExpire,
    });
}

function pmsCiToggleInvoice(radio) {
    const val = radio.value;
    // New layout: toggle wrapper div
    const fieldsEl = document.getElementById('ci-invoice-fields');
    if (fieldsEl) fieldsEl.style.display = val === '1' ? 'block' : 'none';
    // Legacy fallback for individual fields
    const taxEl = document.getElementById('ci-grp-tax');
    const contactEl = document.getElementById('ci-grp-tax-contact');
    const companyEl = document.getElementById('ci-grp-company-name');
    const companyAddrEl = document.getElementById('ci-grp-company-address');
    if (companyEl) companyEl.style.display = val === '1' ? 'flex' : 'none';
    if (companyAddrEl) companyAddrEl.style.display = val === '1' ? 'flex' : 'none';
    if (taxEl) taxEl.style.display = val === '1' ? 'flex' : 'none';
    if (contactEl) contactEl.style.display = val === '1' ? 'flex' : 'none';
}
window.pmsCiToggleInvoice = pmsCiToggleInvoice;
function pmsCiToggleArea(val) {
    // Delegate to vnSwitchMode
    if (typeof vnSwitchMode === 'function') vnSwitchMode(val);
}
window.pmsCiToggleArea = pmsCiToggleArea;

function pmsCiFormatCurrency(input) {
    let val = input.value.replace(/[^0-9]/g, '');
    if (!val) {
        input.value = '0';
        return;
    }
    input.value = parseInt(val).toLocaleString('vi-VN');
}
window.pmsCiFormatCurrency = pmsCiFormatCurrency;

function pmsCiFormatID(input) {
    // Chỉ xoá khoảng trắng và chuyển in hoa, cho phép nhập cả chữ và số tự do
    input.value = input.value.replace(/\s+/g, '').toUpperCase();
}
window.pmsCiFormatID = pmsCiFormatID;

function pmsCiFormatCapitalize(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
window.pmsCiFormatCapitalize = pmsCiFormatCapitalize;

function pmsCiFormatSentence(input) {
    let val = input.value.trim().toLowerCase();
    if (!val) return;
    input.value = val.charAt(0).toUpperCase() + val.slice(1);
}
window.pmsCiFormatSentence = pmsCiFormatSentence;

function pmsCiFormatBasicNumeric(input) {
    input.value = input.value.replace(/\s+/g, '').replace(/\D/g, ''); // Xoá trắng, chỉ để lại số
}
window.pmsCiFormatBasicNumeric = pmsCiFormatBasicNumeric;

function pmsCiValidateID(input) {
    if (!input) return { valid: true };
    const type = document.getElementById('ci-id-type')?.value || 'cccd';
    const val = input.value.trim();
    if (!val) {
        input.classList.remove('is-invalid');
        return { valid: true };
    }

    let isValid = true;
    let msg = '';

    if (type === 'cccd') {
        // Kiểm tra CCCD: phải là 12 chữ số
        if (!/^\d{12}$/.test(val)) {
            isValid = false;
            msg = 'Số CCCD phải có đúng 12 chữ số!';
        }
    } else if (type === 'cmnd') {
        // Kiểm tra CMND: phải là 9 chữ số
        if (!/^\d{9}$/.test(val)) {
            isValid = false;
            msg = 'Số CMND phải có đúng 9 chữ số!';
        }
    }

    if (!isValid) {
        input.classList.add('is-invalid');
    } else {
        input.classList.remove('is-invalid');
    }

    return { valid: isValid, message: msg };
}
window.pmsCiValidateID = pmsCiValidateID;

function pmsCiFailValidation(inputId, message) {
    const el = document.getElementById(inputId);
    if (el) { el.classList.add('is-invalid'); el.focus(); }
    window.alert(message);
    return { valid: false, message: message };
}

function pmsCiClearValidation() {
    document.querySelectorAll('#ciModal .is-invalid').forEach(el => el.classList.remove('is-invalid'));
    document.querySelectorAll('#ciModal .is-warning').forEach(el => el.classList.remove('is-warning'));
}

function pmsCiValidateGuestForm(g) {
    pmsCiClearValidation();

    // 1. Số giấy tờ (kiểm tra trước loại giấy tờ)
    if (!g.cccd) return pmsCiFailValidation('ci-cccd', 'Vui lòng nhập Số giấy tờ');
    // 2. Loại giấy tờ
    if (!g.id_type) return pmsCiFailValidation('ci-id-type', 'Vui lòng chọn Loại giấy tờ');
    // 3. Ngày hết hạn (chỉ kiểm tra nếu giấy tờ có hạn)
    pmsCiApplyCCCDExpiryFromBirth();
    if (!g.id_expire) g.id_expire = document.getElementById('ci-id-expire')?.value || '';
    const permanentCccd = g.id_type === 'cccd'
        && typeof pmsIsCCCDPermanentExpiry === 'function'
        && pmsIsCCCDPermanentExpiry(document.getElementById('ci-id-expire'));
    const noExpire = g.id_type === 'cmnd' || g.id_type === 'gplx' || permanentCccd;
    if (!noExpire) {
        if (!g.id_expire) return pmsCiFailValidation('ci-id-expire', 'Vui lòng nhập Ngày hết hạn giấy tờ!');
        const today = new Date();
        const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
        if (g.id_expire <= todayStr) return pmsCiFailValidation('ci-id-expire', 'Giấy tờ này đã quá ngày hết hạn!');
    }
    // 4. Validate ID format sau khi biết loại giấy tờ
    const idInput = document.getElementById('ci-cccd');
    const idValid = pmsCiValidateID(idInput);
    if (!idValid.valid) return pmsCiFailValidation('ci-cccd', idValid.message);
    // 5. Họ và tên
    if (!g.full_name) return pmsCiFailValidation('ci-name', 'Vui lòng nhập Họ và tên');
    // 6. Giới tính
    if (!g.gender) return pmsCiFailValidation('ci-gender', 'Vui lòng chọn Giới tính');
    // 7. Ngày sinh
    if (!g.birth_date) return pmsCiFailValidation('ci-birth', 'Vui lòng nhập Ngày sinh');
    // 8. Quốc tịch
    if (!g.nationality) return pmsCiFailValidation('ci-nationality', 'Vui lòng chọn Quốc tịch');

    // 8b. Invoice validation — chỉ kiểm tra khi chọn "Có xuất hoá đơn"
    const invoiceVal = document.querySelector('input[name="ci-invoice"]:checked')?.value || '0';
    if (invoiceVal === '1') {
        const taxCodeEl = document.getElementById('ci-tax-code');
        const invoiceContactEl = document.getElementById('ci-tax-contact');
        if (!taxCodeEl?.value?.trim()) {
            return pmsCiFailValidation('ci-tax-code', 'Vui lòng nhập Mã số thuế');
        }
        if (!invoiceContactEl?.value?.trim()) {
            return pmsCiFailValidation('ci-tax-contact', 'Vui lòng nhập Liên hệ hoá đơn (Email hoặc SĐT)');
        }
    }

    // 9. Địa chỉ - CHỈ validation cho khách MỚI (auto-fill khách cũ thì bỏ qua)
    const isForeign = g.id_type === 'passport' || g.id_type === 'visa';
    const isOldGuest = window._pmsCiIsOldGuest === true;
    
    if (!isForeign && !isOldGuest) {
        // KHÁCH MỚI: Phải chọn Tỉnh/TP từ datalist
        if (!g.city) {
            return pmsCiFailValidation('ci-province', 'Vui lòng chọn Tỉnh/Thành phố từ danh sách');
        }
        // Kiểm tra Tỉnh/TP có trong datalist không
        if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-province', g.city)) {
            const provEl = document.getElementById('ci-province');
            if (provEl) provEl.classList.add('is-invalid');
            return pmsCiFailValidation('ci-province', `"${g.city}" không có trong danh sách. Vui lòng chọn Tỉnh/Thành phố từ danh sách!`);
        }

        // KHÁCH MỚI: Phải chọn Phường/Xã từ datalist
        if (!g.ward) {
            return pmsCiFailValidation('ci-ward', 'Vui lòng chọn Phường/Xã từ danh sách');
        }
        // Kiểm tra Phường/Xã có trong datalist không
        if (typeof addrIsInDatalist === 'function' && !addrIsInDatalist('dl-ward', g.ward)) {
            const wardEl = document.getElementById('ci-ward');
            if (wardEl) wardEl.classList.add('is-invalid');
            return pmsCiFailValidation('ci-ward', `"${g.ward}" không có trong danh sách. Vui lòng chọn Phường/Xã từ danh sách!`);
        }

        // Chỉ yêu cầu Quận/Huyện trong chế độ địa bàn cũ
        const addrType = g.address_type || 'new';
        if (addrType === 'old' && !g.district) {
            return pmsCiFailValidation('ci-district', 'Vui lòng chọn Quận/Huyện');
        }

        // Luôn yêu cầu địa chỉ chi tiết
        if (!g.address) return pmsCiFailValidation('ci-address', 'Vui lòng nhập Địa chỉ chi tiết');
    }

    // Kiểm tra tuổi < 18 sau khi đã nhập ngày sinh
    const birthInput = document.getElementById('ci-birth');
    if (g.birth_date && birthInput) {
        const parts = g.birth_date.split('-');
        if (parts.length === 3) {
            const birth = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
            const today = new Date();
            let age = today.getFullYear() - birth.getFullYear();
            const m = today.getMonth() - birth.getMonth();
            if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
            if (age < 18) birthInput.classList.add('is-warning');
            else birthInput.classList.remove('is-warning');
        }
    }

    return { valid: true, message: '' };
}
window.pmsCiValidateGuestForm = pmsCiValidateGuestForm;

function pmsCiGetDepositSnapshot() {
    const rawDeposit = document.getElementById('ci-deposit')?.value || '0';
    const amount = Number(rawDeposit.toString().replace(/[^0-9]/g, '') || 0);
    const selectedCard = document.querySelector('.ci-dep-method-item.selected');
    const method = selectedCard ? selectedCard.dataset.value : 'Chi nhánh';
    const meta = {};
    if (method === 'Công ty') {
        meta.beneficiary = document.getElementById('ci-deposit-beneficiary')?.value || '';
    } else if (method === 'OTA') {
        meta.ota_channel = document.getElementById('ci-deposit-ota')?.value || '';
        meta.ref_code = document.getElementById('ci-deposit-ref')?.value || '';
    }
    return { amount, method, meta };
}

function pmsCiCollectReservationData() {
    const formGuest = pmsCiGetFormGuest();
    const hasFormGuest = !!formGuest.full_name;
    const allGuests = [...pmsCiGuestList];

    if (hasFormGuest) {
        const v = pmsCiValidateGuestForm(formGuest);
        if (!v.valid) return null;
        const formCccd = (formGuest.cccd || '').trim().toUpperCase();
        if (formCccd && pmsCiGuestList.find(xg => (xg.cccd || '').trim().toUpperCase() === formCccd)) {
            window.alert(`CẢNH BÁO: Khách với số giấy tờ ${formGuest.cccd} đã có trong danh sách.`);
            return null;
        }
        allGuests.unshift(formGuest);
    }

    if (!allGuests.length) {
        const v = pmsCiValidateGuestForm(formGuest);
        if (!v.valid) return null;
        return null;
    }

    const cccdMap = {};
    for (let i = 0; i < allGuests.length; i++) {
        const g = allGuests[i];
        const key = (g.cccd || '').trim().toUpperCase();
        if (!key) continue;
        if (!cccdMap[key]) cccdMap[key] = [];
        cccdMap[key].push(i);
    }
    for (const key in cccdMap) {
        if (cccdMap[key].length > 1) {
            window.alert(`CẢNH BÁO: Số giấy tờ ${key} bị trùng trong danh sách khách.`);
            return null;
        }
    }

    for (let i = 0; i < allGuests.length; i++) {
        const g = allGuests[i];
        const noExpire = ['cmnd', 'gplx'].includes(g.id_type || 'cccd');
        if (!g.full_name || !g.cccd || !g.id_type || !g.gender || !g.birth_date || !g.nationality || (!noExpire && !g.id_expire)) {
            const guestName = g.full_name || `Khách thứ ${i + 1}`;
            window.alert(`Thông tin khách "${guestName}" chưa đầy đủ. Vui lòng kiểm tra họ tên, giấy tờ, giới tính, ngày sinh, quốc tịch và ngày hết hạn giấy tờ.`);
            return null;
        }
    }

    const primary = allGuests[0];
    const guestData = hasFormGuest
        ? Object.assign({}, primary || {}, formGuest, window._pmsCiExistingGuestId ? { id: window._pmsCiExistingGuestId } : {})
        : primary;
    const mainInvoiceGuest = allGuests.find(g => g.tax_code) || guestData || {};
    const deposit = pmsCiGetDepositSnapshot();
    const combinedServices = [
        ...pmsCiServiceList.map(s => ({ ...s, category: 'SERVICE' })),
        ...pmsCiSurchargeList.map(s => ({ ...s, category: 'SURCHARGE' })),
    ];

    return {
        guest: guestData,
        guests: allGuests,
        deposit,
        check_in_at: document.getElementById('ci-in')?.value || '',
        check_out_at: document.getElementById('ci-out')?.value || '',
        notes: document.getElementById('ci-notes')?.value || '',
        require_invoice: !!mainInvoiceGuest.tax_code,
        tax_code: mainInvoiceGuest.tax_code || '',
        tax_contact: mainInvoiceGuest.invoice_contact || '',
        services: combinedServices,
        pricing: window._pmsLastPricingPreview || null,
        risk_confirmed: window._pmsCiRiskConfirmed === true,
    };
}
window.pmsCiCollectReservationData = pmsCiCollectReservationData;

// ─────────────────────────────────────────────────────────────────────────────
// Guest Search & Fill Functions
// ─────────────────────────────────────────────────────────────────────────────

// Lock ALL fields (full read-only) — used when auto-fill from old guest
// For old guests: lock everything including address radios
function pmsCiLockAllFields() {
    ['ci-name', 'ci-cccd', 'ci-birth', 'ci-nationality',
        'ci-address', 'ci-vehicle', 'ci-guest-notes',
        'ci-province', 'ci-district', 'ci-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.readOnly = true; el.classList.remove('is-invalid', 'is-warning'); }
        });
    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) idTypeEl.disabled = true;
    const genderEl = document.getElementById('ci-gender');
    if (genderEl) genderEl.disabled = true;
    // Lock address radios to prevent switching modes
    const areaRadios = document.querySelectorAll('input[name="ci-area"]');
    areaRadios.forEach(r => r.disabled = true);
    const staySection = document.getElementById('ci-section-stay');
    if (staySection) staySection.classList.add('ci-section-disabled');
}
window.pmsCiLockAllFields = pmsCiLockAllFields;

// Unlock ALL fields — used when starting new checkin or cancelling edit
function pmsCiUnlockAllFields() {
    ['ci-name', 'ci-cccd', 'ci-id-expire', 'ci-birth', 'ci-nationality',
        'ci-address', 'ci-vehicle', 'ci-guest-notes',
        'ci-province', 'ci-district', 'ci-ward'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.readOnly = false;
                el.classList.remove('is-invalid', 'is-warning');
                el.style.background = '';
                el.style.backgroundColor = '';
                el.style.color = '';
                el.style.cursor = '';
            }
        });
    const idTypeEl = document.getElementById('ci-id-type');
    if (idTypeEl) { idTypeEl.disabled = false; pmsCiToggleIdFields(idTypeEl); }
    const genderEl = document.getElementById('ci-gender');
    if (genderEl) genderEl.disabled = false;
    const invoiceRadios = document.querySelectorAll('input[name="ci-invoice"]');
    invoiceRadios.forEach(r => r.disabled = false);
    const areaRadios = document.querySelectorAll('input[name="ci-area"]');
    areaRadios.forEach(r => {
        // Only enable if it was not hidden (old mode radio is hidden for non-old guests)
        if (r.style.display !== 'none') r.disabled = false;
    });
    const staySection = document.getElementById('ci-section-stay');
    if (staySection) staySection.classList.remove('ci-section-disabled');
    pmsCiResetGuestInputChrome();
    if (idTypeEl) pmsCiToggleIdFields(idTypeEl);
}
window.pmsCiUnlockAllFields = pmsCiUnlockAllFields;

// Legacy aliases
function pmsCiLockAllRequiredFields() { pmsCiLockAllFields(); }
function pmsCiUnlockAllRequiredFields() { pmsCiUnlockAllFields(); }
window.pmsCiLockAllRequiredFields = pmsCiLockAllRequiredFields;
window.pmsCiUnlockAllRequiredFields = pmsCiUnlockAllRequiredFields;

// Fill guest form from old data (TRUSTED DATA - for preview only)
// Flow: Fill form → Lock address → User decides: "Thêm khách" or "Nhận phòng"
async function pmsCiFillGuestFromOld(guest) {
    try {
        if (typeof guest === 'string') guest = JSON.parse(guest);
        if (!pmsCiConfirmRiskGuest(guest)) return;

        // 0. Mark as trusted BEFORE filling (PMS_ADDR progressive normalization)
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.markAutofill) {
            PMS_ADDR.markAutofill();
        }

        // 1. Fill basic fields (sync - immediate)
        const nameEl = document.getElementById('ci-name');
        if (nameEl) nameEl.value = guest.full_name || '';
        const genderEl = document.getElementById('ci-gender');
        if (genderEl) genderEl.value = guest.gender || '';
        const nationalityEl = document.getElementById('ci-nationality');
        if (nationalityEl) nationalityEl.value = guest.nationality || 'VNM - Việt Nam';
        const idTypeEl = document.getElementById('ci-id-type');
        if (idTypeEl) {
            idTypeEl.value = (guest.id_type || 'cccd').toLowerCase();
            // Trigger visibility toggle for passport/visa (hide address sections)
            pmsCiToggleIdFields(idTypeEl);
        }
        const cccdEl = document.getElementById('ci-cccd');
        if (cccdEl) cccdEl.value = guest.cccd || '';
        const idExpireEl = document.getElementById('ci-id-expire');
        if (idExpireEl) {
            if (typeof pmsSetGuestIdExpireValue === 'function') pmsSetGuestIdExpireValue(idExpireEl, guest.id_expire);
            else idExpireEl.value = guest.id_expire ? String(guest.id_expire).slice(0, 10) : '';
            pmsCiCheckIdExpire(idExpireEl);
        }
        const birthEl = document.getElementById('ci-birth');
        if (birthEl && guest.birth_date) {
            birthEl.value = String(guest.birth_date).slice(0, 10);
            pmsCiCheckBirth(birthEl);
        }
        const phoneEl = document.getElementById('ci-phone');
        if (phoneEl) phoneEl.value = guest.phone || '';
        const vehicleEl = document.getElementById('ci-vehicle');
        if (vehicleEl) vehicleEl.value = guest.vehicle || '';
        const notesEl = document.getElementById('ci-guest-notes');
        if (notesEl) notesEl.value = guest.notes || '';

        // 1b. Fill invoice info (UNLOCKED - user can update) - invoice is per-guest
        if (guest.tax_code || guest.invoice_contact || guest.company_name) {
            const invoiceRadio1 = document.querySelector('input[name="ci-invoice"][value="1"]');
            const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
            if (invoiceRadio1) invoiceRadio1.checked = true;
            const taxCodeEl = document.getElementById('ci-tax-code');
            if (taxCodeEl) taxCodeEl.value = guest.tax_code || '';
            const taxContactEl = document.getElementById('ci-tax-contact');
            if (taxContactEl) taxContactEl.value = guest.invoice_contact || '';
            const companyNameEl = document.getElementById('ci-company-name');
            if (companyNameEl) companyNameEl.value = guest.company_name || '';
            const companyAddressEl = document.getElementById('ci-company-address');
            if (companyAddressEl) companyAddressEl.value = guest.company_address || '';
            // Show invoice fields in LEFT column and call toggle to sync state
            const invoiceFields = document.getElementById('ci-invoice-fields');
            if (invoiceFields) invoiceFields.style.display = 'block';
            if (invoiceRadio1) pmsCiToggleInvoice(invoiceRadio1);
        } else {
            // Reset invoice section
            const invoiceRadio0 = document.querySelector('input[name="ci-invoice"][value="0"]');
            if (invoiceRadio0) invoiceRadio0.checked = true;
            const invoiceFields = document.getElementById('ci-invoice-fields');
            if (invoiceFields) invoiceFields.style.display = 'none';
            if (invoiceRadio0) pmsCiToggleInvoice(invoiceRadio0);
        }

        // 1c. Auto-fill done — user can scroll to see invoice data if needed

        // 2. Fill address fields (READONLY - trusted from DB)
        // Không dùng guest.ward để suy ra "cũ" — ward là phường mới sau chuẩn hóa.
        const hasOldData = guest.address_type === 'old' || !!(guest.old_city || guest.old_district || guest.old_ward);
        const addrType = hasOldData ? 'old' : 'new';

        // Set address mode radio
        const oldRadio = document.querySelector('input[name="ci-area"][value="old"]');
        const newRadio = document.querySelector('input[name="ci-area"][value="new"]');
        if (addrType === 'old') {
            if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = true; }
            if (newRadio) { newRadio.disabled = true; }
        } else {
            if (newRadio) { newRadio.checked = true; }
            if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }
        }

        // Fill province
        const pEl = document.getElementById('ci-province');
        if (pEl) pEl.value = hasOldData ? (guest.old_city || '') : (guest.city || '');

        // Fill ward
        const wEl = document.getElementById('ci-ward');
        if (wEl) wEl.value = hasOldData ? (guest.old_ward || '') : (guest.ward || '');

        // Fill district (for old mode)
        const dEl = document.getElementById('ci-district');
        if (dEl) dEl.value = hasOldData ? (guest.old_district || '') : '';

        // Fill address detail
        const addrDetailEl = document.getElementById('ci-address');
        if (addrDetailEl) addrDetailEl.value = guest.address || '';

        // Fill NEW conversion display (for old mode - read only info)
        const nProvEl = document.getElementById('ci-new-province');
        const nWardEl = document.getElementById('ci-new-ward');
        if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
        if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }

        // 3. Hiển thị đủ hàng Quận/Huyện + khối chuẩn hóa (đọc từ DB, không ẩn như helper nhập tay)
        pmsCiShowAddressHelpers();
        
        // 4. ẨN khối chuyển đổi địa bàn (chỉ dùng cho khách mới nhập tay)
        const convGrp = document.getElementById('ci-conversion-grp');
        if (convGrp) convGrp.style.display = 'none';

        // 4. Lock ALL fields (read-only for trusted data)
        pmsCiLockAllFields();

        // 4b. UNLOCK invoice fields - user can update invoice info per-guest
        const invoiceRadios = document.querySelectorAll('input[name="ci-invoice"]');
        invoiceRadios.forEach(r => r.disabled = false);
        const taxCodeEl = document.getElementById('ci-tax-code');
        if (taxCodeEl) taxCodeEl.readOnly = false;
        const taxContactEl = document.getElementById('ci-tax-contact');
        if (taxContactEl) taxContactEl.readOnly = false;

        // Force critical fields after lock
        if (cccdEl) { cccdEl.value = guest.cccd || ''; cccdEl.readOnly = true; }
        if (idTypeEl) idTypeEl.disabled = true;
        if (nameEl) nameEl.readOnly = true;
        if (genderEl) genderEl.disabled = true;
        if (birthEl) birthEl.readOnly = true;
        if (nationalityEl) nationalityEl.readOnly = true;

        // Lock address fields (trusted data)
        if (pEl) { pEl.readOnly = true; pEl.style.background = '#f0fdf4'; }
        if (dEl) { dEl.readOnly = true; dEl.style.background = '#f0fdf4'; }
        if (wEl) { wEl.readOnly = true; wEl.style.background = '#f0fdf4'; }
        if (addrDetailEl) { addrDetailEl.readOnly = true; addrDetailEl.style.background = '#f0fdf4'; }

        // Unlock editable fields only
        if (phoneEl) phoneEl.readOnly = false;
        if (notesEl) notesEl.readOnly = false;
        if (vehicleEl) vehicleEl.readOnly = false;
        if (idExpireEl) idExpireEl.readOnly = false;

        // 5. Show state badge for trusted data
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR._updateStateBadge) {
            PMS_ADDR._updateStateBadge('TRUSTED', 'Địa chỉ từ dữ liệu cũ', 'green');
        }

        // 6. Store existing guest ID for auto-update
        window._pmsCiExistingGuestId = guest.id;
        window._pmsCiIsOldGuest = true;

        // 7. Remove hint
        const hintEl = document.getElementById('ci-cccd-hint');
        if (hintEl) hintEl.remove();

        // 8. Show info message that data is from DB
        pmsCiShowAutofillNotice(guest.full_name, guest.cccd);

        pmsToast(`Đã tìm thấy khách: ${guest.full_name || guest.cccd}`);

    } catch (e) {
        console.error('Error filling guest data:', e);
        pmsToast('Lỗi khi điền thông tin', false);
    }
}
window.pmsCiFillGuestFromOld = pmsCiFillGuestFromOld;

// ─── Address Helper Visibility ──────────────────────────────────────────────────

function pmsCiShowAddressHelpers() {
    const distGrp = document.getElementById('ci-grp-district');
    const convGrp = document.getElementById('ci-conversion-grp');
    const mode = document.querySelector('input[name="ci-area"]:checked')?.value || 'new';

    if (distGrp) distGrp.style.display = mode === 'old' ? '' : 'none';
    if (convGrp) convGrp.style.display = mode === 'old' ? '' : 'none';
}

// ─── Autofill Notice ─────────────────────────────────────────────────────────

function pmsCiShowAutofillNotice(name, cccd) {
    // Remove existing notice
    const existing = document.getElementById('ci-autofill-notice');
    if (existing) existing.remove();

    const infoBar = document.getElementById('ci-section-stay');
    if (!infoBar) return;

    const notice = document.createElement('div');
    notice.id = 'ci-autofill-notice';
    notice.style.cssText = `
        background: linear-gradient(135deg, #f0fdf4, #dcfce7);
        border: 1px solid #86efac;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 13px;
    `;
    notice.innerHTML = `
        <div style="width: 32px; height: 32px; background: #22c55e; border-radius: 50%; display: flex; align-items: center; justify-content: center;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
        </div>
        <div style="flex: 1;">
            <div style="font-weight: 600; color: #15803d;">Dữ liệu từ lưu trú trước</div>
            <div style="color: #64748b; font-size: 12px;">Khách <strong>${name || cccd}</strong> - Địa chỉ đã được xác nhận từ hệ thống</div>
        </div>
    `;

    infoBar.insertBefore(notice, infoBar.firstChild);
}

// ─── Premium Search Popup ─────────────────────────────────────────────────────

function _pmsCiCloseSearchPopup() {
    const modal = document.getElementById('ci-search-results-modal');
    if (modal) {
        modal.style.opacity = '0';
        setTimeout(() => modal.remove(), 200);
    }
}
window._pmsCiCloseSearchPopup = _pmsCiCloseSearchPopup;

function _pmsCiSelectGuest(index) {
    if (!window._pmsCiSearchResults || !window._pmsCiSearchResults[index]) return;
    const guest = window._pmsCiSearchResults[index];
    _pmsCiCloseSearchPopup();
    pmsCiFillGuestFromOld(guest);
}
window._pmsCiSelectGuest = _pmsCiSelectGuest;

async function pmsCiSearchOldGuest() {
    const query = document.getElementById('ci-crm-search-input')?.value?.trim() || '';
    if (!query || query.length < 5) {
        pmsToast('Vui lòng nhập ít nhất 5 ký tự để tìm khách CRM', false);
        return;
    }

    try {
        const r = await pmsApi(`/api/pms/crm/guests/search?q=${encodeURIComponent(query)}&page_size=8`);
        const guests = r.guests || r.items || [];

        if (guests.length === 0) {
            alert(`Không tìm thấy khách hàng phù hợp với "${query}".\n\nVui lòng kiểm tra lại hoặc nhập thông tin khách mới.`);
            pmsToast(`Không tìm thấy khách CRM với "${query}"`, false);
            return;
        }

        // Store results globally for selection
        window._pmsCiSearchResults = guests;

        // Build premium popup for multiple results
        const resultsHtml = guests.map((g, idx) => {
            const initials = (g.full_name || '?').split(' ').map(w => w[0]).join('').slice(-2).toUpperCase();
            const genderColor = g.gender === 'Nam' ? '#3b82f6' : g.gender === 'Nữ' ? '#ec4899' : '#8b5cf6';
            const addressParts = [g.address, g.ward, g.city].filter(Boolean);
            const addressStr = addressParts.length > 0 ? addressParts.join(', ') : '—';
            const riskBadges = [
                g.is_blacklisted ? '<span class="ci-search-risk danger">Blacklist</span>' : '',
                g.has_unpaid_debt ? `<span class="ci-search-risk warn">Nợ ${pmsMoney(g.unpaid_debt_amount || 0)}</span>` : '',
            ].join('');

            return `
                <div class="ci-search-card" onclick="_pmsCiSelectGuest(${idx})" tabindex="0">
                    <div class="ci-search-avatar" style="background:linear-gradient(135deg, ${genderColor}, ${genderColor}dd);">
                        ${initials}
                    </div>
                    <div class="ci-search-info">
                        <div class="ci-search-name">${pmsEscapeHtml(g.full_name)} ${riskBadges}</div>
                        <div class="ci-search-detail">
                            <span class="ci-search-tag">
                                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                                ${pmsEscapeHtml(g.cccd)}
                            </span>
                            ${g.phone ? `<span class="ci-search-tag">
                                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                                ${pmsEscapeHtml(g.phone)}
                            </span>` : ''}
                            ${g.gender ? `<span class="ci-search-tag">${pmsEscapeHtml(g.gender)}</span>` : ''}
                        </div>
                        <div class="ci-search-address">
                            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                            ${pmsEscapeHtml(addressStr)}
                        </div>
                    </div>
                    <div class="ci-search-arrow">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                    </div>
                </div>
            `;
        }).join('');

        // Remove existing popup if any
        const existing = document.getElementById('ci-search-results-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'ci-search-results-modal';
        modal.innerHTML = `
            <style>
                #ci-search-results-modal {
                    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(15, 23, 42, 0.6);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    z-index: 100004;
                    display: flex; align-items: center; justify-content: center;
                    opacity: 0;
                    transition: opacity 0.2s ease;
                }
                .ci-search-popup {
                    background: #fff;
                    border-radius: 16px;
                    max-width: 520px; width: 92%;
                    max-height: 70vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 25px 60px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.1);
                    transform: translateY(12px);
                    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                }
                #ci-search-results-modal.ci-show .ci-search-popup { transform: translateY(0); }
                .ci-search-header {
                    padding: 20px 24px 16px; border-bottom: 1px solid #f1f5f9;
                    display: flex; align-items: center; gap: 14px;
                }
                .ci-search-header-icon {
                    width: 42px; height: 42px; border-radius: 12px;
                    background: linear-gradient(135deg, #dbeafe, #bfdbfe);
                    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
                }
                .ci-search-header-icon svg { stroke: #2563eb; }
                .ci-search-header h5 { margin: 0; font-size: 16px; font-weight: 700; color: #1e293b; }
                .ci-search-header p { margin: 4px 0 0; font-size: 13px; color: #64748b; }
                .ci-search-close {
                    margin-left: auto; padding: 8px; background: none;
                    border: none; border-radius: 8px; cursor: pointer; color: #94a3b8; transition: all 0.15s;
                }
                .ci-search-close:hover { background: #f1f5f9; color: #475569; }
                .ci-search-list { flex: 1; overflow-y: auto; padding: 12px 16px 16px; }
                .ci-search-card {
                    display: flex; align-items: center; gap: 14px;
                    padding: 14px 16px; border-radius: 12px;
                    border: 1px solid #e2e8f0; background: #fff;
                    cursor: pointer; transition: all 0.15s ease; margin-bottom: 10px;
                }
                .ci-search-card:last-child { margin-bottom: 0; }
                .ci-search-card:hover {
                    border-color: #93c5fd; background: linear-gradient(135deg, #f0f9ff, #eff6ff);
                    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1); transform: translateY(-1px);
                }
                .ci-search-card:active { transform: translateY(0); }
                .ci-search-avatar {
                    width: 44px; height: 44px; border-radius: 12px;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 14px; font-weight: 700; color: #fff; flex-shrink: 0; letter-spacing: 0.5px;
                }
                .ci-search-info { flex: 1; min-width: 0; }
                .ci-search-name {
                    font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 4px;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                }
                .ci-search-risk {
                    display:inline-flex; margin-left:6px; padding:2px 7px; border-radius:999px;
                    font-size:10px; font-weight:800; vertical-align:1px;
                }
                .ci-search-risk.danger { background:#fee2e2; color:#b91c1c; }
                .ci-search-risk.warn { background:#fef3c7; color:#92400e; }
                .ci-search-detail { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
                .ci-search-tag {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 2px 8px; border-radius: 6px;
                    background: #f1f5f9; color: #475569; font-size: 11.5px; font-weight: 500;
                }
                .ci-search-address {
                    display: flex; align-items: center; gap: 4px;
                    font-size: 12px; color: #94a3b8;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
                }
                .ci-search-arrow { flex-shrink: 0; color: #cbd5e1; transition: all 0.15s; }
                .ci-search-card:hover .ci-search-arrow { color: #3b82f6; transform: translateX(2px); }
            </style>
            <div class="ci-search-popup">
                <div class="ci-search-header">
                    <div class="ci-search-header-icon">
                        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                        </svg>
                    </div>
                    <div>
                        <h5>Tìm thấy ${guests.length} khách hàng</h5>
                        <p>Chọn khách hàng để điền thông tin vào form</p>
                    </div>
                    <button class="ci-search-close" onclick="_pmsCiCloseSearchPopup()" title="Đóng">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="ci-search-list">${resultsHtml}</div>
            </div>
        `;
        document.body.appendChild(modal);

        // Trigger animation
        requestAnimationFrame(() => {
            modal.style.opacity = '1';
            modal.classList.add('ci-show');
        });

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) _pmsCiCloseSearchPopup();
        });

        // Close on Escape
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                _pmsCiCloseSearchPopup();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

    } catch (e) {
        console.error('Error searching:', e);
        pmsToast('Lỗi tìm kiếm', false);
    }
}
window.pmsCiSearchOldGuest = pmsCiSearchOldGuest;



// ─────────────────────────────────────────────────────────────────────────────
// Expiration Check
// ─────────────────────────────────────────────────────────────────────────────
let _pmsCiIdExpireTimer = null;
function pmsCiCheckIdExpire(inputEl) {
    if (typeof pmsIsCCCDPermanentExpiry === 'function' && pmsIsCCCDPermanentExpiry(inputEl)) {
        inputEl.classList.remove('is-invalid');
        return;
    }
    if (!inputEl.value) {
        inputEl.classList.remove('is-invalid');
        return;
    }
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');

    if (inputEl.value <= todayStr) {
        inputEl.classList.add('is-invalid');
        clearTimeout(_pmsCiIdExpireTimer);
        _pmsCiIdExpireTimer = setTimeout(() => {
            alert('⚠️ Cảnh báo: Giấy tờ này đã quá ngày hết hạn! Vui lòng cập nhật.');
        }, 100);
    } else {
        inputEl.classList.remove('is-invalid');
    }
}
// ─────────────────────────────────────────────────────────────────────────────
// Birth Check
// ─────────────────────────────────────────────────────────────────────────────
let _pmsCiBirthTimer = null;
function pmsCiCheckBirth(inputEl) {
    if (!inputEl.value) {
        inputEl.classList.remove('is-warning');
        return;
    }
    pmsCiApplyCCCDExpiryFromBirth();
    const parts = inputEl.value.split('-');
    if (parts.length === 3) {
        const birth = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const today = new Date();
        let age = today.getFullYear() - birth.getFullYear();
        const m = today.getMonth() - birth.getMonth();
        if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
        if (age < 18) {
            inputEl.classList.add('is-warning');
            clearTimeout(_pmsCiBirthTimer);
            _pmsCiBirthTimer = setTimeout(() => {
                alert(`⚠️ Cảnh báo: Khách hàng hiện mới ${age} tuổi. Việc nhận phòng có thể yêu cầu người giám hộ!`);
            }, 500);
        } else {
            inputEl.classList.remove('is-warning');
        }
    }
}
window.pmsCiCheckIdExpire = pmsCiCheckIdExpire;
function pmsCiOnDepositTypeChange(select) {
    const val = select.value;
    const metaGrp = document.getElementById('ci-deposit-meta-grp');
    const metaCompany = document.getElementById('ci-meta-company');
    const metaOta = document.getElementById('ci-meta-ota');
    const metaUnc = document.getElementById('ci-meta-unc');

    if (!metaGrp) return;

    // Hide all first
    metaGrp.style.display = 'none';
    if (metaCompany) metaCompany.style.display = 'none';
    if (metaOta) metaOta.style.display = 'none';
    if (metaUnc) metaUnc.style.display = 'none';

    if (val === 'Công ty') {
        metaGrp.style.display = 'flex';
        if (metaCompany) metaCompany.style.display = 'block';
    } else if (val === 'OTA') {
        metaGrp.style.display = 'flex';
        if (metaOta) metaOta.style.display = 'block';
    } else if (val === 'UNC') {
        metaGrp.style.display = 'flex';
        if (metaUnc) metaUnc.style.display = 'block';
    }
}
window.pmsCiOnDepositTypeChange = pmsCiOnDepositTypeChange;

// ─── Deposit Method Card Selection ─────────────────────────────────────────────
window.ciDepSelectMethod = function(el, method) {
    if (el?.classList?.contains('disabled') || el?.getAttribute('aria-disabled') === 'true') return;
    // Update card selection visual
    document.querySelectorAll('.ci-dep-method-item').forEach(item => {
        item.classList.remove('selected');
    });
    el.classList.add('selected');

    // Show/hide meta fields
    const metaGrp = document.getElementById('ci-deposit-meta-grp');
    const metaCompany = document.getElementById('ci-meta-company');
    const metaOta = document.getElementById('ci-meta-ota');
    if (!metaGrp) return;

    metaGrp.style.display = 'none';
    if (metaCompany) metaCompany.style.display = 'none';
    if (metaOta) metaOta.style.display = 'none';

    if (method === 'Công ty') {
        metaGrp.style.display = 'flex';
        if (metaCompany) metaCompany.style.display = 'block';
    } else if (method === 'OTA') {
        metaGrp.style.display = 'flex';
        if (metaOta) metaOta.style.display = 'block';
    }
};

// ─── SHADCN-STYLE DATETIME PICKER ──────────────────────────────────────────────

class ShadDateTimePicker {
  constructor(wrapperEl) {
    this.wrapper = wrapperEl;
    if (!this.wrapper || this.wrapper.dataset.shadDtBound === '1') return;
    const targetId = this.wrapper.dataset.target;
    this.input = document.getElementById(targetId);
    this.displayInput = document.getElementById(`${targetId}-display`);
    if (!this.input || !this.displayInput) return;
    this.wrapper.dataset.shadDtBound = '1';
    this.wrapper._shadDateTimePicker = this;

    this.date = null;
    this.time = null;
    this.suppressSync = false;
    
    this.buildPopover();
    this.attachEvents();
    
    // Override the value setter for the hidden input
    const originalSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    const self = this;
    Object.defineProperty(this.input, "value", {
      set: function(val) {
        originalSet.call(this, val);
        if (!self.suppressSync) self.syncFromInput();
      },
      get: function() {
        return Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").get.call(this);
      }
    });

    this.syncFromInput();
  }

  getPortalContainer() {
    if (this.wrapper.closest('#pms-booking-page')) return document.body;
    return this.wrapper.closest('.bk-dialog-body') || document.getElementById('ci-body') || document.body;
  }

  syncFromInput() {
    const val = this.input.value;
    if (val) {
      const dt = new Date(val);
      if (!isNaN(dt.getTime())) {
        this.date = dt;
        this.time = `${dt.getHours().toString().padStart(2, '0')}:${dt.getMinutes().toString().padStart(2, '0')}`;
        this.updateDisplayStr();
        return;
      }
    }
    this.date = null;
    this.time = null;
    this.displayInput.value = '';
  }

  updateDisplayStr() {
    if (!this.date || !this.time) return;
    const d = this.date.getDate().toString().padStart(2, '0');
    const m = (this.date.getMonth() + 1).toString().padStart(2, '0');
    const y = this.date.getFullYear();
    this.displayInput.value = `${d}/${m}/${y}, ${this.time}`;
  }

  buildPopover() {
    this.popover = document.createElement('div');
    this.popover.className = 'shad-dt-popover';
    
    const calHtml = `
      <div class="shad-dt-calendar">
         <div class="shad-dt-header">
            <button class="shad-dt-btn shad-dt-prev"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m15 18-6-6 6-6"/></svg></button>
            <div class="shad-dt-month" id="shad-month-${this.input.id}">Tháng -</div>
            <button class="shad-dt-btn shad-dt-next"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg></button>
         </div>
         <div class="shad-dt-grid" id="shad-days-${this.input.id}">
            <div class="shad-dt-dayname">CN</div><div class="shad-dt-dayname">T2</div><div class="shad-dt-dayname">T3</div><div class="shad-dt-dayname">T4</div><div class="shad-dt-dayname">T5</div><div class="shad-dt-dayname">T6</div><div class="shad-dt-dayname">T7</div>
         </div>
      </div>
      <div class="shad-dt-times">
         <div class="shad-dt-time-head">
            <div style="display:flex; gap:4px; align-items:center;">
                <input type="text" id="shad-manual-time-${this.input.id}" placeholder="HHmm" style="width:100%; padding:4px 8px; border:1px solid #e2e8f0; border-radius:4px; font-size:12px;">
                <button class="shad-dt-btn shad-apply-time" style="padding:4px 8px; font-size:11px; background:#0f172a; color:#fff;">OK</button>
            </div>
         </div>
         <div class="shad-dt-time-scroll" id="shad-times-${this.input.id}"></div>
      </div>
    `;
    this.popover.innerHTML = calHtml;
    this.getPortalContainer().appendChild(this.popover);
  }

  attachEvents() {
    this.popover.querySelector('.shad-dt-prev').onclick = (e) => {
      e.stopPropagation();
      this.currentMonth.setMonth(this.currentMonth.getMonth() - 1);
      this.renderCalendar();
    };
    this.popover.querySelector('.shad-dt-next').onclick = (e) => {
      e.stopPropagation();
      this.currentMonth.setMonth(this.currentMonth.getMonth() + 1);
      this.renderCalendar();
    };
    
    // Quick time apply
    const timeInput = this.popover.querySelector(`#shad-manual-time-${this.input.id}`);
    const applyBtn = this.popover.querySelector('.shad-apply-time');
    
    const handleManualTime = () => {
        let val = timeInput.value.replace(/\D/g, '');
        if (val.length >= 3) {
            const h = val.slice(0, 2);
            const m = val.slice(2, 4).padEnd(2, '0');
            if (parseInt(h) < 24 && parseInt(m) < 60) {
                this.time = `${h.padStart(2, '0')}:${m}`;
                this.applyValue();
                this.close();
            }
        }
    };

    applyBtn.onclick = (e) => { e.stopPropagation(); handleManualTime(); };
    timeInput.onkeydown = (e) => { if(e.key === 'Enter') { e.stopPropagation(); handleManualTime(); } };
    timeInput.onclick = (e) => e.stopPropagation();

    this.displayInput.addEventListener('click', (e) => {
      e.stopPropagation();
      this.open();
    });

    this.displayInput.addEventListener('input', (e) => {
        // Smart format: DDMMYYYYHHmm
        let val = e.target.value.replace(/\D/g, '');
        if (val.length > 12) val = val.slice(0, 12);
        
        let formatted = '';
        if (val.length > 0) formatted += val.slice(0, 2);
        if (val.length > 2) formatted += '/' + val.slice(2, 4);
        if (val.length > 4) formatted += '/' + val.slice(4, 8);
        if (val.length > 8) formatted += ', ' + val.slice(8, 10);
        if (val.length > 10) formatted += ':' + val.slice(10, 12);
        
        e.target.value = formatted;
        
        if (val.length === 12) {
            const d = val.slice(0, 2);
            const m = val.slice(2, 4);
            const y = val.slice(4, 8);
            const hh = val.slice(8, 10);
            const mm = val.slice(10, 12);
            
            const testDate = new Date(y, m - 1, d, hh, mm);
            if (!isNaN(testDate.getTime())) {
                this.date = testDate;
                this.time = `${hh}:${mm}`;
                this.suppressSync = true;
                this.input.value = `${y}-${m}-${d}T${hh}:${mm}`;
                this.suppressSync = false;
                const evt = new Event('change');
                this.input.dispatchEvent(evt);
                this.close();
            }
        }
    });

    document.addEventListener('click', (e) => {
      if (this.popover.classList.contains('show') && !this.wrapper.contains(e.target) && !this.popover.contains(e.target)) {
        this.close();
      }
    });

    this.popover.addEventListener('click', e => e.stopPropagation());
    
    this.wrapper.addEventListener('click', (e) => {
        e.stopPropagation();
        // Toggle
        if (this.popover.classList.contains('show')) {
            this.close();
        } else {
            this.open();
        }
    });
  }

  renderCalendar() {
    const y = this.currentMonth.getFullYear();
    const m = this.currentMonth.getMonth();
    const monthEl = document.getElementById(`shad-month-${this.input.id}`);
    if (monthEl) monthEl.textContent = `Tháng ${m+1}, ${y}`;
    
    const daysContainer = document.getElementById(`shad-days-${this.input.id}`);
    if (!daysContainer) return;

    // Remove all children except the first 7 (weekday headers CN, T2, T3, T4, T5, T6, T7)
    // If the container is empty (first render), we need to handle it.
    if (daysContainer.children.length < 7) {
        daysContainer.innerHTML = `
            <div class="shad-dt-dayname">CN</div><div class="shad-dt-dayname">T2</div><div class="shad-dt-dayname">T3</div><div class="shad-dt-dayname">T4</div><div class="shad-dt-dayname">T5</div><div class="shad-dt-dayname">T6</div><div class="shad-dt-dayname">T7</div>
        `;
    } else {
        while (daysContainer.children.length > 7) {
            daysContainer.removeChild(daysContainer.lastChild);
        }
    }
    
    const firstDay = new Date(y, m, 1).getDay();
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    
    for(let i=0; i<firstDay; i++) daysContainer.appendChild(document.createElement('div'));
    
    const today = new Date(); today.setHours(0,0,0,0);
    
    for(let i=1; i<=daysInMonth; i++) {
        const btn = document.createElement('button');
        btn.className = 'shad-dt-day' + (this.date && this.date.getDate() === i && this.date.getMonth() === m && this.date.getFullYear() === y ? ' selected' : '');
        btn.textContent = i;
        if (new Date(y, m, i) < today) btn.disabled = true;
        else {
            btn.onclick = (e) => {
                e.stopPropagation();
                this.date = new Date(y, m, i);
                this.renderCalendar();
                this.renderTimes();
            };
        }
        daysContainer.appendChild(btn);
    }
    
    const displayDate = this.date || today;
  }

  renderTimes() {
     const timesContainer = document.getElementById(`shad-times-${this.input.id}`);
     if (!timesContainer) return;
     timesContainer.innerHTML = '';
     for (let h=0; h<24; h++) {
         for (let m=0; m<60; m+=15) { // Use 15m for cleaner list but allow any via manual
             const hh = h.toString().padStart(2, '0');
             const mm = m.toString().padStart(2, '0');
             const timeStr = `${hh}:${mm}`;
             const btn = document.createElement('button');
             btn.className = 'shad-dt-time-btn' + (this.time === timeStr ? ' selected' : '');
             btn.textContent = timeStr;
             btn.onclick = (e) => {
                 e.stopPropagation();
                 this.time = timeStr;
                 this.applyValue();
                 this.close();
             };
             timesContainer.appendChild(btn);
         }
     }
  }

  applyValue() {
     if (this.date && this.time) {
         const y = this.date.getFullYear();
         const m = (this.date.getMonth() + 1).toString().padStart(2, '0');
         const d = this.date.getDate().toString().padStart(2, '0');
         this.suppressSync = true;
         this.input.value = `${y}-${m}-${d}T${this.time}`;
         this.suppressSync = false;
         this.updateDisplayStr();
         const evt = new Event('change');
         this.input.dispatchEvent(evt);
     }
  }

  updatePosition() {
    const rect = this.wrapper.getBoundingClientRect();
    
    // Relative to the ci-body container if we appended there
    const parentContainer = this.getPortalContainer();
    const isPagePicker = parentContainer === document.body;
    const isMobile = window.innerWidth <= 600 && !isPagePicker;
    
    if (isMobile) {
        this.popover.style.width = '100%';
        this.popover.style.left = '0px';
        this.popover.style.position = 'relative';
        this.popover.style.transform = 'none';
        this.popover.style.marginTop = '8px';
        // When mobile, just inject it into the wrapper dynamically
        if (this.popover.parentElement !== this.wrapper) {
             this.wrapper.appendChild(this.popover);
        }
        return;
    }

    if (this.popover.parentElement === this.wrapper) {
         parentContainer.appendChild(this.popover);
         this.popover.style.position = 'absolute';
    }
    
    const parentRect = parentContainer === document.body
      ? { top: 0, left: 0 }
      : parentContainer.getBoundingClientRect();
    const scrollTop = parentContainer === document.body ? window.scrollY : parentContainer.scrollTop;
    const scrollLeft = parentContainer === document.body ? window.scrollX : parentContainer.scrollLeft;
    
    // Calculate position
    let top = rect.bottom - parentRect.top + scrollTop + 8;
    let left = rect.left - parentRect.left + scrollLeft;
    
    // Check overflow bottom
    if (rect.bottom + 320 > window.innerHeight) {
       top = rect.top - parentRect.top + scrollTop - 320 - 8;
    }
    
    // Check overflow right
    const containerWidth = parentContainer === document.body ? window.innerWidth : parentContainer.clientWidth;
    if (left + 390 > containerWidth) {
       left = containerWidth - 390 - 20;
    }
    if (left < 8) left = 8;
    
    this.popover.style.top = `${top}px`;
    this.popover.style.left = `${left}px`;
  }
  
  open() {
      // close others dynamically
      if (document.shadActivePicker && document.shadActivePicker !== this) {
          document.shadActivePicker.close();
      }
      document.shadActivePicker = this;
      
      // Initialize starting month frame
      let startD = this.date;
      if (!startD) {
          startD = new Date();
          // if it's ci-out, we want to start from check-in time if available
          if (this.input.id === 'ci-out') {
              const ciInVal = document.getElementById('ci-in')?.value;
              if (ciInVal) {
                  const dt = new Date(ciInVal);
                  if (!isNaN(dt.getTime())) startD = dt;
              }
          }
      }
      
      this.currentMonth = new Date(startD.getFullYear(), startD.getMonth(), 1);
      
      this.renderCalendar();
      this.renderTimes();
      this.updatePosition();
      this.popover.classList.add('show');
      
      // Auto-scroll times slightly
      const timesContainer = document.getElementById(`shad-times-${this.input.id}`);
      if (timesContainer) {
          const selected = timesContainer.querySelector('.selected');
          if (selected) {
              timesContainer.scrollTop = selected.offsetTop - 50;
          } else {
              timesContainer.scrollTop = (startD.getHours() * 12) * 28;
          }
      }
  }
  
  close() {
      this.popover.classList.remove('show');
      if (document.shadActivePicker === this) document.shadActivePicker = null;
  }
}

// Auto-init on load
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.ci-shad-dt-wrap').forEach(el => {
        new ShadDateTimePicker(el);
    });
});

(function initCiVietnameseDateInputs() {
    const init = () => {
        if (typeof pmsEnsureVietnameseDateInputs === 'function') {
            pmsEnsureVietnameseDateInputs(['ci-id-expire', 'ci-birth']);
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
