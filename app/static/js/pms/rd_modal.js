// static/js/pms/rd_modal.js
'use strict';

let rdStayData = null;
let rdGuestList = [];
let rdMaxGuests = 2;
let rdTlAllActivities = [];
let rdTempServices = [];
let rdTempSurcharges = [];
let rdAllServices = [];
let rdIsCheckedOut = false;  // TRUE khi stay đã checkout (từ lịch sử)
let rdNotesSaveTimer = null;
let rdNotesLastSavedValue = '';
let rdLastBreakdownRows = [];
let rdLastBreakdownTotal = 0;

// ── Session counter: mỗi lần openRoomDetail tăng 1, dùng để phát hiện stale response ──
let _rdSessionId = 0;

// ── Shared Folio State (used by both Room tab and Payment tab) ──
let rdCurrentFolio = null;
let rdCurrentFolios = [];
let rdActiveFolioIndex = 0;
let rdFolioLoaded = false;   // Guard: has Folio data been fetched for this session?
let rdBillTransferState = {
    target: null,
    requestId: 0,
    submiting: false,
    searchTimer: null,
};
let rdFolioLoadPromise = null;
let rdFolioHasFullData = false;
let rdPaymentRenderKey = '';
let rdRoomInfoRenderKey = '';
let rdRoomInfoSkeletonKey = '';

function rdGetRoomInfoRenderKey(stayId, data = null) {
    const txs = rdCurrentFolio?.transactions || [];
    const lastTx = txs[txs.length - 1] || {};
    return [
        stayId || rdStayData?.id || '',
        rdStayData?.check_in_at || '',
        rdStayData?.check_out_at || '',
        rdStayData?.deposit || 0,
        rdCurrentFolio?.id || '',
        txs.length,
        lastTx.id || '',
        lastTx.created_at || lastTx.updated_at || '',
        data?.total ?? data?.room_charge ?? '',
        data?.existing_charges ?? '',
        data?.projected_balance ?? '',
    ].join('|');
}

function rdResetRoomInfoRenderCache() {
    rdRoomInfoRenderKey = '';
    rdRoomInfoSkeletonKey = '';
}

function pmsRdNotifyInventoryInvalidated(stayId, detail = {}) {
    const payload = {
        stay_id: Number(stayId) || Number(rdStayData?.id) || null,
        branch_id: rdStayData?.branch_id || null,
        check_in_at: detail.check_in_at ?? rdStayData?.check_in_at ?? null,
        check_out_at: detail.check_out_at ?? rdStayData?.check_out_at ?? null,
        reason: detail.reason || 'stay_updated',
        ts: Date.now(),
    };
    try {
        window.dispatchEvent(new CustomEvent('pms:stay-updated', { detail: payload }));
        window.dispatchEvent(new CustomEvent('pms:inventory-invalidated', { detail: payload }));
    } catch { /* noop */ }
    try {
        localStorage.setItem('pms:inventory-invalidated', JSON.stringify(payload));
    } catch { /* noop */ }
}

function rdSetBusy(isBusy, text = 'Đang tải dữ liệu...') {
    const dialog = document.getElementById('rd-dialog');
    if (!dialog) return;
    dialog.classList.toggle('rd-busy', !!isBusy);

    let overlay = dialog.querySelector('.rd-modal-busy-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'rd-modal-busy-overlay';
        overlay.setAttribute('aria-live', 'polite');
        overlay.setAttribute('aria-busy', 'true');
        overlay.innerHTML = `
            <div class="rd-modal-busy-panel">
                <span class="rd-modal-busy-spinner"></span>
                <span id="rd-modal-busy-text">Đang tải dữ liệu...</span>
            </div>
        `;
        dialog.appendChild(overlay);
    }

    overlay.style.display = isBusy ? 'flex' : 'none';
    overlay.style.position = 'absolute';
    overlay.style.inset = '0';
    overlay.style.zIndex = '1000';
    overlay.style.alignItems = 'center';
    overlay.style.justifyContent = 'center';
    overlay.style.background = document.documentElement.classList.contains('dark')
        ? 'rgba(15, 23, 42, 0.7)'
        : 'rgba(248, 250, 252, 0.72)';
    overlay.style.backdropFilter = 'blur(2px)';

    const label = overlay.querySelector('#rd-modal-busy-text') || document.getElementById('rd-modal-busy-text');
    if (label && text) label.textContent = text;
}

function rdNum(value) {
    const n = parseFloat(value);
    return Number.isFinite(n) ? n : 0;
}

function rdGetTxType(t) {
    return t?.type || t?.transaction_type || '';
}

function rdTxTime(t) {
    const raw = t?.created_at || t?.paid_at || t?.posted_at || t?.updated_at;
    const d = raw ? pmsParseDate(raw) : null;
    return d && !Number.isNaN(d.getTime()) ? d.getTime() : 0;
}

function rdSortLedgerTransactions(txs) {
    const order = {
        DEPOSIT_USED: 5,
        ROOM_CHARGE: 10,
        HOURLY_CHARGE: 10,
        EARLY_CHECKIN_FEE: 11,
        LATE_CHECKOUT_FEE: 12,
        SERVICE_CHARGE: 20,
        SURCHARGE: 30,
        DISCOUNT: 40,
        PAYMENT: 60,
        DEBT_PAYMENT: 60,
        REFUND: 70,
        REFUND_PAYMENT: 70,
    };
    return [...(txs || [])].sort((a, b) => {
        const timeDiff = rdTxTime(a) - rdTxTime(b);
        if (timeDiff !== 0) return timeDiff;
        const aType = rdGetTxType(a);
        const bType = rdGetTxType(b);
        return (order[aType] || 99) - (order[bType] || 99);
    });
}

function rdTxAmount(t) {
    return rdNum(t?.amount);
}

function rdCalculateFolioBalance(folio = rdCurrentFolio, options = {}) {
    const txs = (folio?.transactions || []).filter(t => !t.is_voided);
    const includePaymentState = options.includePaymentState !== false && folio === rdCurrentFolio;

    if (includePaymentState && rdPaymentState) {
        const projected = rdPaymentState.projected_balance ?? rdPaymentState.balance;
        if (projected !== undefined && projected !== null && projected !== '') {
            return rdNum(projected);
        }
    }

    if (txs.length > 0) {
        const charges = txs
            .filter(t => rdTxAmount(t) > 0 && !['REFUND', 'REFUND_PAYMENT'].includes(rdGetTxType(t)))
            .reduce((acc, t) => acc + rdTxAmount(t), 0);
        const discounts = txs
            .filter(t => t.category === 'DISCOUNT')
            .reduce((acc, t) => acc + Math.abs(rdTxAmount(t)), 0);
        const payments = txs
            .filter(t => rdTxAmount(t) < 0 && ['PAYMENT', 'DEBT_PAYMENT', 'DEPOSIT_USED'].includes(rdGetTxType(t)))
            .reduce((acc, t) => acc + Math.abs(rdTxAmount(t)), 0);
        return (charges - discounts) - payments;
    }

    return rdNum(folio?.balance);
}

function rdGetCheckedOutDisplayBalance() {
    const projected = rdPaymentState?.projected_balance ?? rdPaymentState?.balance;
    if (projected !== undefined && projected !== null && projected !== '') return rdNum(projected);

    const paidFromParts = rdNum(rdPaymentState?.effective_paid) + rdNum(rdPaymentState?.deposit_used);
    const paid = paidFromParts > 0
        ? paidFromParts
        : rdNum(rdPaymentState?.total_paid ?? rdCurrentFolio?.total_paid ?? 0);
    const totalRaw = rdPaymentState?.net_charge ?? rdPaymentState?.final_total ?? rdPaymentState?.total_charge ?? rdCurrentFolio?.total_charge ?? 0;
    const total = rdNum(totalRaw);
    if (total > 0 || paid > 0) return total - paid;
    return rdNum(rdCurrentFolio?.balance ?? 0);
}

function rdMergeChargeResult(resp, fallback = {}) {
    if (!rdCurrentFolio || !resp) return;

    if (resp.folio) {
        Object.assign(rdCurrentFolio, {
            total_charge: resp.folio.total_charge ?? rdCurrentFolio.total_charge,
            total_discount: resp.folio.total_discount ?? rdCurrentFolio.total_discount,
            total_paid: resp.folio.total_paid ?? rdCurrentFolio.total_paid,
            balance: resp.folio.balance ?? rdCurrentFolio.balance,
            status: resp.folio.status ?? rdCurrentFolio.status,
        });
    }

    const tx = resp.transaction || null;
    if (tx && !tx.is_voided) {
        rdCurrentFolio.transactions = rdCurrentFolio.transactions || [];
        const exists = rdCurrentFolio.transactions.some(t => String(t.id) === String(tx.id));
        if (!exists) rdCurrentFolio.transactions.push(tx);
    } else if (fallback.description && fallback.amount > 0) {
        rdCurrentFolio.transactions = rdCurrentFolio.transactions || [];
        rdCurrentFolio.transactions.push({
            id: `pending-${Date.now()}-${Math.random().toString(16).slice(2)}`,
            folio_id: rdCurrentFolio.id,
            transaction_type: fallback.transaction_type,
            category: fallback.category,
            description: fallback.description,
            amount: fallback.amount,
            quantity: fallback.quantity || 1,
            unit_price: fallback.unit_price || null,
            created_at: new Date().toISOString(),
            created_by_name: 'Tạm tính',
            is_voided: false,
            is_virtual: true,
        });
    }

    if (rdPaymentState) {
        rdPaymentState.folios = rdCurrentFolios;
    }
}

function rdMergeTransactionUpdate(tx) {
    if (!tx || !rdCurrentFolio) return;
    rdCurrentFolio.transactions = rdCurrentFolio.transactions || [];
    const idx = rdCurrentFolio.transactions.findIndex(t => String(t.id) === String(tx.id));
    if (idx >= 0) {
        rdCurrentFolio.transactions[idx] = { ...rdCurrentFolio.transactions[idx], ...tx };
    } else {
        rdCurrentFolio.transactions.push(tx);
    }
}

async function rdRefreshFolioAfterCharge(stayId) {
    const targetStayId = stayId || rdCurrentFolio?.stay_id || rdStayData?.id;
    if (!targetStayId) {
        rdSetPriceCardUpdating(false);
        return;
    }

    rdSetPriceCardUpdating(true);
    try {
        await fetchFolio(targetStayId);
        if (typeof rdRenderRoomInfoCard === 'function') {
            await rdRenderRoomInfoCard({ force: true });
        }
    } catch (e) {
        console.warn('[rdRefreshFolioAfterCharge]', e);
        throw e;
    } finally {
        rdSetPriceCardUpdating(false);
    }
}

window.rdCalculateFolioBalance = rdCalculateFolioBalance;

function rdSetPriceCardUpdating(isUpdating, text = 'Đang cập nhật giá') {
    const card = document.getElementById('rd-price-card');
    if (!card) return;
    card.classList.toggle('is-updating', !!isUpdating);
    const label = document.getElementById('rd-price-card-loader-text');
    if (label && text) label.textContent = text;
}

function rdReadOtaMetaFromFolio() {
    const raw = rdCurrentFolio?.notes;
    if (!raw || typeof raw !== 'string' || !raw.trim().startsWith('{')) return null;
    try {
        const meta = JSON.parse(raw);
        if (meta?.pricing_mode !== 'manual_channel_total') return null;
        return meta;
    } catch {
        return null;
    }
}

function rdIsOtaManualStay() {
    const folioMeta = rdReadOtaMetaFromFolio();
    return rdStayData?.pricing_mode_initial === 'OTA_MANUAL'
        || rdStayData?.pricing_mode_final === 'OTA_MANUAL'
        || rdPaymentState?.ota_price_mode === 'manual_channel_total'
        || rdNum(rdPaymentState?.ota_actual_total) > 0
        || rdNum(folioMeta?.ota_actual_total) > 0;
}

function rdGetOtaPricingInfo() {
    if (!rdIsOtaManualStay()) return null;
    const folioMeta = rdReadOtaMetaFromFolio();
    const actual = rdNum(rdPaymentState?.ota_actual_total) || rdNum(folioMeta?.ota_actual_total) || rdNum(rdStayData?.total_price);
    const reference = rdNum(rdPaymentState?.pms_reference_total) || rdNum(folioMeta?.pms_reference_total);
    const delta = actual - reference;
    if (!actual) return null;
    return { actual, reference, delta };
}

function rdRenderOtaPricingNotice(rowsEl, info) {
    if (!rowsEl || !info) return;
    const fallbackRef = info.reference > 0
        ? info.reference
        : rdLastBreakdownRows
            .filter(b => ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(b.type))
            .reduce((acc, b) => acc + rdNum(b.amount), 0);
    const referenceText = fallbackRef > 0 ? pmsMoney(fallbackRef) : '—';
    const deltaText = fallbackRef > 0
        ? `${info.actual - fallbackRef >= 0 ? '+' : '-'}${pmsMoney(Math.abs(info.actual - fallbackRef))}`
        : '—';
    rowsEl.insertAdjacentHTML('afterbegin', `
        <div class="rd-ri-ota-notice" style="background:rgba(255,255,255,0.96); border:1px solid rgba(111,209,215,0.55); border-left:4px solid #6FD1D7; border-radius:18px; padding:14px 16px; display:grid; grid-template-columns:1.2fr 1fr 1fr; gap:12px; align-items:center; color:#093C5D; box-shadow:0 10px 24px rgba(9,60,93,0.08);">
            <div>
                <div style="font-size:10px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; color:#3B7597;">Phòng OTA</div>
                <div style="font-size:12px; font-weight:850; margin-top:3px;">Giá OTA thực thu là giá tính tiền phòng</div>
                <div style="font-size:11px; font-weight:700; color:#64748b; margin-top:2px;">Chênh lệch PMS chỉ dùng để đối soát, không phải hoàn/thu thêm khách.</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:10px; font-weight:850; color:#64748b; text-transform:uppercase;">PMS tham chiếu</div>
                <div style="font-size:14px; font-weight:900; font-family:'Outfit',sans-serif; color:#3B7597;">${referenceText}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:10px; font-weight:850; color:#64748b; text-transform:uppercase;">Chênh lệch OTA</div>
                <div style="font-size:14px; font-weight:900; font-family:'Outfit',sans-serif; color:#093C5D;">${deltaText}</div>
            </div>
        </div>
    `);
}

function rdGetRoomInfoProjection() {
    const ps = rdPaymentState || {};
    const txs = rdCurrentFolio?.transactions || [];
    const service = txs
        .filter(t => !t.is_voided && t.category === 'SERVICE' && rdTxAmount(t) > 0)
        .reduce((acc, t) => acc + rdTxAmount(t), 0);
    const surcharge = txs
        .filter(t => !t.is_voided && (t.category === 'SURCHARGE' || t.category === 'OTHER') && rdTxAmount(t) > 0)
        .reduce((acc, t) => acc + rdTxAmount(t), 0);
    const room = rdNum(rdGetOtaPricingInfo()?.actual)
        || rdNum(ps.room_charge)
        || (ps.breakdown || [])
            .filter(b => ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(b.type))
            .reduce((acc, b) => acc + rdNum(b.amount), 0);
    const currentHero = pmsParseCurrency(document.getElementById('rd-ri-hero-amount')?.textContent || '0');
    const paid = rdNum(ps.effective_paid) + rdNum(ps.deposit_used || ps.total_paid);
    const discount = rdNum(ps.total_discounts || ps.existing_discounts || ps.discount);
    const total = room + service + surcharge;
    const projectedBalance = total - discount - paid;
    return { room, service, surcharge, total, projectedBalance, paid, currentHero };
}

function rdUpdateRoomPriceCardFromCache() {
    if (!rdCurrentFolio) return;
    const projection = rdGetRoomInfoProjection();
    if (projection.room <= 0 && projection.currentHero <= 0) {
        return;
    }
    const displayTotal = projection.room > 0
        ? projection.total
        : Math.max(projection.currentHero, projection.service + projection.surcharge);
    const displayBalance = projection.room > 0
        ? projection.projectedBalance
        : null;
    const heroAmount = document.getElementById('rd-ri-hero-amount');
    const subEl = document.getElementById('rd-ri-subtotal');
    const needDiv = document.getElementById('rd-ri-need');
    const needAmount = document.getElementById('rd-ri-need-amount');
    const excessDiv = document.getElementById('rd-ri-excess-row');
    const excessAmount = document.getElementById('rd-ri-excess-amount');
    const depEl = document.getElementById('rd-ri-deposit');

    if (heroAmount) heroAmount.textContent = pmsMoney(displayTotal);
    if (subEl) subEl.textContent = pmsMoney(displayTotal);
    if (depEl) depEl.textContent = pmsMoney(projection.paid);

    if (displayBalance === null) {
        // Chưa có nền tiền phòng: giữ nguyên dòng cần thu hiện tại, chỉ cập nhật danh sách phụ.
    } else if (displayBalance > 0) {
        if (needDiv) needDiv.style.opacity = '1';
        if (needAmount) needAmount.textContent = pmsMoney(displayBalance);
        if (excessDiv) excessDiv.style.opacity = '0';
    } else if (displayBalance < 0) {
        if (excessDiv) excessDiv.style.opacity = '1';
        if (excessAmount) excessAmount.textContent = pmsMoney(Math.abs(displayBalance));
        if (needDiv) needDiv.style.opacity = '0';
    } else {
        if (needDiv) needDiv.style.opacity = '0';
        if (excessDiv) excessDiv.style.opacity = '0';
    }

    const rowsEl = document.getElementById('rd-ri-bd-rows');
    if (rowsEl && rdLastBreakdownRows.length) {
        const rows = rdLastBreakdownRows.filter(r => !['SERVICE', 'SURCHARGE'].includes(r.type));
        if (projection.service > 0) rows.push({ type: 'SERVICE', label: 'Chi phí dịch vụ', amount: projection.service });
        if (projection.surcharge > 0) rows.push({ type: 'SURCHARGE', label: 'Chi phí phát sinh', amount: projection.surcharge });
        _renderRiRows(rows, rowsEl, displayTotal);
        rdRenderOtaPricingNotice(rowsEl, rdGetOtaPricingInfo());
    }
}

function rdFormatFullAddress(g) {
    if (!g) return '—';
    const parts = [];
    const detail = (g.address || '').trim();
    const ward = (g.ward || g.old_ward || '').trim();
    const district = (g.district || g.old_district || '').trim();
    const city = (g.city || g.old_city || '').trim();
    [detail, ward, district, city].forEach(part => {
        if (part && !parts.includes(part)) parts.push(part);
    });
    return parts.length ? parts.join(', ') : '—';
}

function rdSetNotesSaveState(text, state = 'idle') {
    const el = document.getElementById('rd-notes-save-state');
    if (!el) return;
    el.textContent = text || '';
    const colorMap = {
        saving: '#d97706',
        saved: '#059669',
        error: '#dc2626',
        idle: 'var(--rd-text-muted)',
    };
    el.style.color = colorMap[state] || colorMap.idle;
}

function pmsRdQueueNotesAutosave(value) {
    const hiddenNotes = document.getElementById('rd-notes');
    if (hiddenNotes) hiddenNotes.value = value || '';
    if (!rdStayData?.id) return;
    if (value === rdNotesLastSavedValue) {
        rdSetNotesSaveState('', 'idle');
        return;
    }
    rdSetNotesSaveState('Đang chờ lưu...', 'saving');
    clearTimeout(rdNotesSaveTimer);
    rdNotesSaveTimer = setTimeout(() => pmsRdSaveRoomNotes(value || ''), 650);
}

async function pmsRdSaveRoomNotes(value) {
    if (!rdStayData?.id) return;
    const normalizedValue = (value || '').trim();
    rdSetNotesSaveState('Đang lưu...', 'saving');
    try {
        await pmsApi(`/api/pms/stays/${rdStayData.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes: normalizedValue }),
        });
        rdNotesLastSavedValue = normalizedValue;
        const notesRoom = document.getElementById('rd-notes-room');
        const hiddenNotes = document.getElementById('rd-notes');
        if (notesRoom && notesRoom.value !== normalizedValue) notesRoom.value = normalizedValue;
        if (hiddenNotes) hiddenNotes.value = normalizedValue;
        if (rdStayData) rdStayData.notes = normalizedValue;
        rdSetNotesSaveState('Đã lưu', 'saved');
        setTimeout(() => {
            if ((document.getElementById('rd-notes-room')?.value || '') === rdNotesLastSavedValue) {
                rdSetNotesSaveState('', 'idle');
            }
        }, 1200);
    } catch (e) {
        rdSetNotesSaveState('Lưu thất bại', 'error');
        console.error('[pmsRdSaveRoomNotes]', e);
    }
}

let rdVehicleSaveTimer = null;
let rdVehicleLastSavedValue = '';

function rdSetVehicleSaveState(text, state = 'idle') {
    const el = document.getElementById('rd-vehicle-save-state');
    if (!el) return;
    el.textContent = text || '';
    const colorMap = { saving: '#d97706', saved: '#059669', error: '#dc2626', idle: 'var(--rd-text-muted)' };
    el.style.color = colorMap[state] || colorMap.idle;
}

function pmsRdQueueVehicleAutosave(value) {
    if (!rdStayData?.id) return;
    if (value === rdVehicleLastSavedValue) {
        rdSetVehicleSaveState('', 'idle');
        return;
    }
    rdSetVehicleSaveState('...', 'saving');
    clearTimeout(rdVehicleSaveTimer);
    rdVehicleSaveTimer = setTimeout(() => pmsRdSaveVehicle(value || ''), 650);
}

async function pmsRdSaveVehicle(value) {
    if (!rdStayData?.id) return;
    const normalized = (value || '').trim();
    rdSetVehicleSaveState('...', 'saving');
    const primaryGuest = rdGuestList.find(g => g.is_primary) || rdGuestList[0];
    if (!primaryGuest?.id) {
        rdSetVehicleSaveState('Lỗi', 'error');
        return;
    }
    try {
        await pmsApi(`/api/pms/guests/${primaryGuest.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vehicle: normalized }),
        });
        rdVehicleLastSavedValue = normalized;
        primaryGuest.vehicle = normalized;
        const hiddenVeh = document.getElementById('rd-vehicle');
        if (hiddenVeh) hiddenVeh.value = normalized;
        rdSetVehicleSaveState('Đã lưu', 'saved');
        setTimeout(() => {
            const el = document.getElementById('rd-ri-vehicle');
            if (el && el.value === rdVehicleLastSavedValue) rdSetVehicleSaveState('', 'idle');
        }, 1200);
    } catch (e) {
        rdSetVehicleSaveState('Lỗi', 'error');
        console.error('[pmsRdSaveVehicle]', e);
    }
}

function rdUpdateClosedRoomRight() {
    const box = document.getElementById('rd-room-right-checkedout-summary');
    const text = document.getElementById('rd-room-right-checkedout-text');
    if (!box) return;
    const balance = rdIsCheckedOut
        ? rdGetCheckedOutDisplayBalance()
        : rdNum(rdPaymentState?.projected_balance ?? rdCurrentFolio?.balance ?? 0);
    const shouldShow = rdIsCheckedOut && Math.abs(balance) > 0.5;
    box.style.display = shouldShow ? 'block' : 'none';
    if (!shouldShow || !text) return;
    if (balance > 0) {
        text.textContent = `Hoá đơn còn nợ ${pmsMoney(balance)}. Các thao tác ghi thêm đã khoá; chỉ xử lý thu nợ ở tab Thanh toán.`;
    } else {
        text.textContent = `Hoá đơn đang dư ${pmsMoney(Math.abs(balance))}. Các thao tác ghi thêm đã khoá để giữ nguyên dữ liệu checkout.`;
    }
}

function rdUpdateCheckedOutPaymentActions() {
    const note = document.getElementById('rd-pay-closed-note');
    if (note) note.style.display = 'none';

    const checkoutBtn = document.getElementById('rd-pay-checkout-btn');
    if (checkoutBtn && rdIsCheckedOut) {
        checkoutBtn.style.display = 'none';
        checkoutBtn.disabled = true;
    }

    const openPayBtn = document.getElementById('rd-pay-open-btn');
    if (openPayBtn && rdIsCheckedOut) {
        const balance = rdGetCheckedOutDisplayBalance();
        if (balance > 0.5) {
            openPayBtn.style.display = '';
            openPayBtn.disabled = false;
            openPayBtn.style.opacity = '';
            openPayBtn.style.pointerEvents = '';
            openPayBtn.style.background = '#f59e0b';
            openPayBtn.style.color = '#fff';
            openPayBtn.style.borderColor = '#f59e0b';
            openPayBtn.style.boxShadow = '0 8px 16px -4px rgba(245, 158, 11, 0.4)';
            openPayBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> Thu nợ`;
        } else {
            openPayBtn.style.display = 'none';
            openPayBtn.disabled = true;
        }
    }

    const tools = document.querySelector('.chk-ledger-tools');
    if (tools) tools.style.display = rdIsCheckedOut ? 'none' : 'flex';
}

function rdModalSkeletonCards(count = 3) {
    return `<div class="rd-modal-skeleton">${Array.from({ length: count }).map((_, idx) => `
        <div class="rd-skeleton-card">
            <div class="rd-skeleton-avatar"></div>
            <div style="flex:1;display:flex;flex-direction:column;gap:8px;">
                <div class="rd-skeleton-line" style="width:${idx === 0 ? 68 : 54}%;"></div>
                <div class="rd-skeleton-line" style="width:${idx === 1 ? 42 : 34}%;height:10px;"></div>
            </div>
        </div>
    `).join('')}</div>`;
}

function rdLedgerSkeletonRows(count = 4) {
    return `<div class="rd-modal-skeleton">${Array.from({ length: count }).map((_, idx) => `
        <div class="rd-skeleton-card" style="justify-content:space-between;">
            <div style="flex:1;display:flex;flex-direction:column;gap:8px;">
                <div class="rd-skeleton-line" style="width:${idx % 2 ? 48 : 62}%;"></div>
                <div class="rd-skeleton-line" style="width:30%;height:10px;"></div>
            </div>
            <div class="rd-skeleton-line" style="width:88px;height:14px;"></div>
        </div>
    `).join('')}</div>`;
}

function rdPaymentStayTypeLabel(stayType) {
    const normalized = String(stayType || '').toUpperCase();
    if (['HOURLY', 'HOUR', 'FORCE_HOURLY', 'HOURLY_CHARGE'].includes(normalized)) return 'Thuê giờ';
    if (['DAILY', 'DAY', 'DAY_USE', 'FORCE_DAILY'].includes(normalized)) return 'Thuê ngày';
    if (['OVERNIGHT', 'NIGHT', 'FORCE_OVERNIGHT'].includes(normalized)) return 'Qua đêm';
    if (normalized === 'OTA_MANUAL') return 'OTA';
    return normalized ? 'Qua đêm' : '';
}

function rdResolvePaymentPricingMode(data = {}, paymentState = null) {
    const breakdown = paymentState?.breakdown || data?.breakdown || [];
    const itemModes = breakdown
        .map(item => String(item?.mode || '').toUpperCase())
        .filter(Boolean);

    if (itemModes.includes('OVERNIGHT')) return 'FORCE_OVERNIGHT';
    if (itemModes.includes('DAILY')) return 'FORCE_DAILY';

    const itemTypes = breakdown.map(item => String(item?.type || '').toUpperCase());
    if (itemTypes.includes('ROOM_CHARGE')) return 'FORCE_DAILY';
    if (itemModes.includes('HOURLY')) return 'FORCE_HOURLY';
    if (itemTypes.includes('HOURLY_CHARGE')) return 'FORCE_HOURLY';

    return paymentState?.pricing_mode_final
        || data?.pricing_mode_final
        || paymentState?.pricing_mode
        || data?.pricing_mode
        || paymentState?.mode
        || data?.mode
        || data?.pricing_mode_initial
        || data?.stay_type
        || '';
}

function rdFormatPaymentHeaderDate(value) {
    if (!value) return '—';
    if (typeof pmsFormatDateTimeVN === 'function') return pmsFormatDateTimeVN(value);
    return String(value);
}

function rdUpdatePaymentRoomHeader(data = null, roomNum = '', paymentState = rdPaymentState) {
    const d = data || {};
    const guests = d.guests || [];
    const primaryGuest = guests.find(g => g.is_primary) || guests[0] || null;
    const pricingMode = rdResolvePaymentPricingMode(d, paymentState);
    const headerData = {
        room: roomNum || d.room_number || '',
        type: d.room_type || '',
        guest: primaryGuest?.full_name || d.guest_name || '',
        stayType: rdPaymentStayTypeLabel(pricingMode),
        checkIn: rdFormatPaymentHeaderDate(d.check_in_at || paymentState?.check_in_at),
        checkOut: rdFormatPaymentHeaderDate(d.check_out_at || paymentState?.check_out_at),
    };

    const setText = (id, value, fallback = '—') => {
        const el = document.getElementById(id);
        if (el) el.textContent = value || fallback;
    };

    setText('rd-pay-room-number', headerData.room);
    setText('rd-pay-room-type', headerData.type, 'Đang tải...');
    setText('rd-pay-room-guest', headerData.guest);
    setText('rd-pay-room-stay-type', headerData.stayType);
    setText('rd-pay-room-checkin', headerData.checkIn);
    setText('rd-pay-room-checkout', headerData.checkOut);
}

/**
 * Reset TẤT CẢ các phần tử UI hiển thị về trạng thái placeholder/skeleton
 * ngay lập tức khi mở phòng mới, TRƯỚC KHI gọi bất kỳ API nào.
 * → Người dùng KHÔNG BAO GIỜ nhìn thấy dữ liệu của phòng cũ.
 */
function _rdResetVisualUI() {
    // ── Room tab: Price Card ──
    const heroAmt = document.getElementById('rd-ri-hero-amount');
    if (heroAmt) heroAmt.textContent = '—';
    const subEl = document.getElementById('rd-ri-subtotal');
    if (subEl) subEl.textContent = '—';
    const depEl = document.getElementById('rd-ri-deposit');
    if (depEl) depEl.textContent = '—';
    const ciEl = document.getElementById('rd-ri-ci');
    if (ciEl) ciEl.textContent = '—';
    const coEl = document.getElementById('rd-ri-co');
    if (coEl) { coEl.textContent = '—'; coEl.className = 'rd-ri-stat-val'; }
    const coNow = document.getElementById('rd-ri-co-now');
    if (coNow) coNow.style.display = 'none';
    const coCard = document.getElementById('rd-ri-co-card');
    if (coCard) coCard.classList.remove('overdue');
    const typeBadge = document.getElementById('rd-ri-type-badge');
    if (typeBadge) typeBadge.textContent = '';
    const needDiv = document.getElementById('rd-ri-need');
    if (needDiv) needDiv.style.opacity = '0';
    const excessDiv = document.getElementById('rd-ri-excess-row');
    if (excessDiv) excessDiv.style.opacity = '0';
    const stdLabel = document.getElementById('rd-ri-std-label');
    if (stdLabel) stdLabel.innerHTML = '<span class="rd-live-dot"></span> LIVE';
    const rowsEl = document.getElementById('rd-ri-bd-rows');
    if (rowsEl) rowsEl.innerHTML = _rdRiSkeleton();

    // ── Room tab: Folio Mirror (service/surcharge sidebar) ──
    const elSM = document.getElementById('rd-pay-dash-service-mirror');
    const elSurM = document.getElementById('rd-pay-dash-surcharge-mirror');
    if (elSM) elSM.textContent = '0';
    if (elSurM) elSurM.textContent = '0';
    const svList = document.getElementById('rd-services-active-list');
    const surList = document.getElementById('rd-surcharges-active-list');
    if (svList) svList.innerHTML = '';
    if (surList) surList.innerHTML = '';
    rdUpdateClosedRoomRight();

    // ── Room tab: Guest list ──
    const guestPanel = document.getElementById('rd-guest-list-panel');
    if (guestPanel) guestPanel.innerHTML = rdModalSkeletonCards(3);
    const guestCount = document.getElementById('rd-guest-count-display');
    if (guestCount) guestCount.textContent = '0';

    // ── Room tab: Notes ──
    const notesRoom = document.getElementById('rd-notes-room');
    if (notesRoom) notesRoom.value = '';

    // ── Payment tab: Dashboard cards ──
    rdUpdatePaymentRoomHeader();
    const dashIds = ['rd-pay-dash-room', 'rd-pay-dash-service', 'rd-pay-dash-extra', 'rd-pay-dash-paid', 'rd-pay-dash-discount', 'rd-pay-dash-balance'];
    dashIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = '0';
    });

    // ── Payment tab: Ledger ──
    const ledgerBody = document.getElementById('rd-pay-ledger-body');
    if (ledgerBody) ledgerBody.innerHTML = rdLedgerSkeletonRows(4);

    // ── Payment tab: Timeline ──
    const timeline = document.getElementById('rd-pay-timeline');
    if (timeline) timeline.innerHTML = rdModalSkeletonCards(2);

    // ── Payment tab: Folio tabs ──
    const tabsContainer = document.getElementById('rd-folio-tabs-container');
    if (tabsContainer) tabsContainer.innerHTML = '';

    // ── Deposit badges ──
    document.querySelectorAll('.deposit-badge').forEach(b => b.remove());

    // ── Debt badge ──
    const debtBadge = document.getElementById('rd-debt-badge');
    if (debtBadge) debtBadge.style.display = 'none';

    // ── Checkout badge ──
    const coBadge = document.getElementById('rd-checked-out-badge');
    if (coBadge) coBadge.remove();
}

function rdSwitchTab(tabName) {
    if (tabName === 'general') tabName = 'room';
    if (tabName === 'payment') rdCloseBillTransferModal();
    if (tabName === 'room' && rdStayData?.id) {
        rdSetPriceCardUpdating(true, 'Đang tính giá');
    }
    // Hide all tab contents
    document.querySelectorAll('.rd-tab-content').forEach(el => {
        el.style.display = 'none';
    });

    // Show selected tab content
    const target = document.getElementById(`rd-tab-${tabName}`);
    if (target) {
        const displayType = target.dataset.display || 'flex';
        target.style.display = displayType;
    }

    // Update tab states
    document.querySelectorAll('.rd-tab').forEach(el => {
        if (el.dataset.tab === tabName) {
            el.classList.add('active');
            el.style.borderBottom = '2px solid #3b82f6';
            el.style.color = '#3b82f6';
        } else {
            el.classList.remove('active');
            el.style.borderBottom = 'none';
            el.style.color = '#475569';
        }
    });

    // Load timeline when switching to timeline tab
    if (tabName === 'timeline') {
        rdLoadTimeline();
    } else if (tabName === 'payment') {
        // Chỉ gọi rdLoadPayment khi rdStayData đã load xong
        // (tránh gọi trước khi API set data → lỗi)
        if (rdStayData && rdStayData.id) {
            if (!rdFolioLoaded) pmsRdResetPaymentUI();
            if (typeof rdLoadPayment === 'function') {
                rdLoadPayment();
            }
        }
    } else if (tabName === 'room' && rdStayData) {
        rdLoadRoomTabData();
    }
}

function pmsRdResetPaymentUI() {
    // Reset all payment state
    rdFolioLoaded = false;
    rdFolioHasFullData = false;
    rdFolioLoading = false;
    rdFolioLightLoading = false;
    rdFolioJustRendered = false;
    rdCurrentFolio = null;
    rdCurrentFolios = [];
    rdActiveFolioIndex = 0;
    rdPaymentState = null;
    rdPayTabLoaded = false;
    rdResetPaymentRenderCache();
    rdResetRoomInfoRenderCache();

    // Reset dashboard cards
    const dashIds = ['rd-pay-dash-room', 'rd-pay-dash-service', 'rd-pay-dash-extra', 'rd-pay-dash-paid', 'rd-pay-dash-discount', 'rd-pay-dash-balance'];
    dashIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = '0';
    });

    // Remove deposit badge from previous room
    document.querySelectorAll('.deposit-badge').forEach(b => b.remove());

    // Reset folio tabs container
    const tabsContainer = document.getElementById('rd-folio-tabs-container');
    if (tabsContainer) tabsContainer.innerHTML = '';

    // Reset ledger body
    const ledgerBody = document.getElementById('rd-pay-ledger-body');
    if (ledgerBody) ledgerBody.innerHTML = `<div style="padding:40px; color:#94a3b8; font-size:14px; text-align:center; font-style:italic;">Đang tải dữ liệu...</div>`;

    // Reset timeline
    const timeline = document.getElementById('rd-pay-timeline');
    if (timeline) timeline.innerHTML = '';

    // Reset checkout button
    const btnCO = document.getElementById('rd-pay-checkout-btn');
    if (btnCO) {
        btnCO.disabled = true;
        btnCO.style.opacity = '0.65';
        btnCO.style.cursor = 'not-allowed';
        btnCO.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> Trả phòng`;
    }
    rdUpdateCheckedOutPaymentActions();

    // Reset debt badge
    const debtBadge = document.getElementById('rd-debt-badge');
    if (debtBadge) debtBadge.style.display = 'none';

    // Reset mirror in Room tab
    const mirrorEl = document.getElementById('rd-room-folio-mirror');
    if (mirrorEl) mirrorEl.innerHTML = '';
    const elSM = document.getElementById('rd-pay-dash-service-mirror');
    const elSurM = document.getElementById('rd-pay-dash-surcharge-mirror');
    if (elSM) elSM.textContent = '0';
    if (elSurM) elSurM.textContent = '0';
    const svList = document.getElementById('rd-services-active-list');
    const surList = document.getElementById('rd-surcharges-active-list');
    if (svList) svList.innerHTML = '';
    if (surList) surList.innerHTML = '';
    rdUpdateClosedRoomRight();
}

// ── Unified Payment State (single source of truth) ──────────────────────
// Lưu trữ dữ liệu payment tab: pricing preview + folio state
let rdPaymentState = null;
// Nếu true → sau khi load payment xong sẽ tự động mở popup thanh toán
let rdAutoOpenPaymentPopup = false;
let rdFolioLightLoading = false;

function rdSetAutoPay(val) {
    rdAutoOpenPaymentPopup = !!val;
}

function rdSetPaymentState(data) {
    rdPaymentState = data;
    rdFolioLoaded = !!(data?.folios?.length);
    rdCurrentFolios = data?.folios || [];
    rdActiveFolioIndex = 0;
    rdCurrentFolio = rdCurrentFolios[0] || null;
    // Đảm bảo stay_id luôn có trên rdCurrentFolio
    if (rdCurrentFolio && !rdCurrentFolio.stay_id) {
        rdCurrentFolio.stay_id = rdStayData?.id;
    }
}

async function rdLoadRoomTabData() {
    if (!rdStayData?.id || typeof rdRenderRoomInfoCard !== 'function') return;

    rdSetPriceCardUpdating(true, 'Đang tính giá');
    if (rdIsCheckedOut) {
        try {
            if (!rdFolioLoaded && typeof fetchFolio === 'function') {
                await fetchFolio(rdStayData.id);
            }
            await rdRenderRoomInfoCard({ force: true });
        } finally {
            rdSetPriceCardUpdating(false);
        }
        return;
    }

    try {
        if (!rdFolioLoaded && typeof fetchFolioLight === 'function') {
            await fetchFolioLight(rdStayData.id, { skipRoomInfoRefresh: true });
        } else if (rdFolioLoaded) {
            pmsRdMirrorFolio();
        }
        await rdRenderRoomInfoCard({ force: true });
    } finally {
        rdSetPriceCardUpdating(false);
    }
}

// ── rdLoadPayment: gọi /checkout/{id}/preview (1 API duy nhất) ────────
// Dùng merge thay vì replace hoàn toàn rdPaymentState để tránh mất
// transactions từ fetchFolio() khi cả hai cùng resolve gần nhau.
let rdFolioLoading = false; // Guard: đang fetch folio?
let rdFolioJustRendered = false; // Folio vừa được render bởi fetchFolio()?
let rdPayTabLoaded = false; // Payment tab đã load xong chưa


function rdResetPaymentRenderCache() {
    rdPaymentRenderKey = '';
}

function rdBuildPaymentRenderKey() {
    const folio = rdCurrentFolio || {};
    const txs = folio.transactions || [];
    const last = txs[txs.length - 1] || {};
    return [
        rdStayData?.id || '',
        folio.id || '',
        txs.length,
        last.id || '',
        last.created_at || '',
        rdPaymentState?.projected_balance ?? rdPaymentState?.balance ?? folio.balance ?? '',
        rdActiveFolioIndex,
    ].join('|');
}

function rdRenderPaymentIfChanged(force = false) {
    const key = rdBuildPaymentRenderKey();
    if (!force && key && key === rdPaymentRenderKey) return false;
    rdPaymentRenderKey = key;
    if (typeof pmsRdRenderFolioTabs === 'function') pmsRdRenderFolioTabs();
    if (typeof pmsRdRenderFolio === 'function') pmsRdRenderFolio();
    pmsRdMirrorFolio();
    return true;
}

function rdUpdateBillTransferButton(balance = rdBillTransferBalance()) {
    const btn = document.getElementById('rd-pay-transfer-bill-btn');
    if (!btn) return;
    const canTransfer = !rdIsCheckedOut && rdStayData?.id && rdNum(balance) > 0;
    btn.style.display = canTransfer ? '' : 'none';
    btn.disabled = !canTransfer;
    btn.style.opacity = canTransfer ? '' : '0.55';
    btn.style.pointerEvents = canTransfer ? '' : 'none';
}

function rdBillTransferBalance() {
    return rdNum(rdPaymentState?.projected_balance ?? rdCurrentFolio?.balance ?? 0);
}

function rdSetBillTransferError(message) {
    const el = document.getElementById('rd-transfer-error');
    if (!el) return;
    el.textContent = message || '';
    el.style.display = message ? 'block' : 'none';
}

function rdRenderBillTransferTargets(items = []) {
    const list = document.getElementById('rd-transfer-target-list');
    if (!list) return;
    if (!items.length) {
        list.innerHTML = '<div style="padding:14px; color:#64748b; font-size:12px; text-align:center;">Không tìm thấy phòng đang lưu trú phù hợp</div>';
        return;
    }
    list.innerHTML = items.map(item => {
        const balance = rdNum(item.balance || 0);
        const balanceLabel = balance > 0 ? `Thiếu ${pmsMoney(balance)}` : (balance < 0 ? `Dư ${pmsMoney(Math.abs(balance))}` : 'Đủ tiền');
        const balanceColor = balance > 0 ? '#dc2626' : (balance < 0 ? '#059669' : '#64748b');
        return `
        <button type="button" data-stay-id="${item.stay_id}" onclick="rdSelectBillTransferTarget(${item.stay_id})" style="text-align:left; border:1px solid ${rdBillTransferState.target?.stay_id === item.stay_id ? '#2563eb' : '#e2e8f0'}; background:${rdBillTransferState.target?.stay_id === item.stay_id ? '#eff6ff' : '#fff'}; border-radius:10px; padding:10px 12px; cursor:pointer; display:flex; justify-content:space-between; gap:12px; align-items:center;">
            <span style="display:flex; flex-direction:column; gap:2px; min-width:0;">
                <strong style="font-size:13px; color:#0f172a;">Phòng ${pmsEscapeHtml(item.room_number || '—')}</strong>
                <small style="font-size:12px; color:#64748b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${pmsEscapeHtml(item.guest_name || 'Khách lưu trú')}${item.guest_phone ? ' · ' + pmsEscapeHtml(item.guest_phone) : ''}</small>
            </span>
            <span style="font-size:12px; color:${balanceColor}; font-weight:800; white-space:nowrap;">${balanceLabel}</span>
        </button>`;
    }).join('');
    rdBillTransferState.targets = items;
}

function rdSelectBillTransferTarget(stayId) {
    const target = (rdBillTransferState.targets || []).find(item => Number(item.stay_id) === Number(stayId));
    rdBillTransferState.target = target || null;
    rdRenderBillTransferTargets(rdBillTransferState.targets || []);
    rdSetBillTransferError('');
}

function rdSearchBillTransferTargets() {
    if (!rdStayData?.id) return;
    clearTimeout(rdBillTransferState.searchTimer);
    rdBillTransferState.searchTimer = setTimeout(async () => {
        const requestId = ++rdBillTransferState.requestId;
        const list = document.getElementById('rd-transfer-target-list');
        const search = document.getElementById('rd-transfer-target-search')?.value || '';
        if (list) list.innerHTML = '<div style="padding:14px; color:#64748b; font-size:12px; text-align:center;">Đang tìm phòng...</div>';
        try {
            const params = new URLSearchParams({ source_stay_id: rdStayData.id, q: search });
            const data = await pmsApi(`/api/pms/checkout/transfer-targets?${params.toString()}`);
            if (requestId !== rdBillTransferState.requestId) return;
            rdBillTransferState.targets = data.items || [];
            if (rdBillTransferState.target && !rdBillTransferState.targets.some(item => item.stay_id === rdBillTransferState.target.stay_id)) {
                rdBillTransferState.target = null;
            }
            rdRenderBillTransferTargets(rdBillTransferState.targets);
        } catch (e) {
            if (requestId !== rdBillTransferState.requestId) return;
            rdSetBillTransferError(e.message || 'Không thể tìm phòng nhận');
            rdRenderBillTransferTargets([]);
        }
    }, 250);
}

function rdOpenBillTransferModal() {
    const balance = rdBillTransferBalance();
    if (!rdStayData?.id || balance <= 0) {
        pmsToast('Phòng hiện không còn số tiền cần gộp', false);
        return;
    }
    rdBillTransferState = { target: null, targets: [], requestId: rdBillTransferState.requestId + 1, submiting: false };
    const modal = document.getElementById('rd-sub-modal-bill-transfer');
    const amount = document.getElementById('rd-transfer-amount');
    const note = document.getElementById('rd-transfer-note');
    const search = document.getElementById('rd-transfer-target-search');
    const summary = document.getElementById('rd-transfer-source-summary');
    if (amount) amount.value = Math.round(balance);
    if (note) note.value = '';
    if (search) search.value = '';
    if (summary) summary.textContent = `Nguồn: phòng ${document.getElementById('rd-room-num')?.textContent || '—'} · Còn phải thu ${pmsMoney(balance)}`;
    rdSetBillTransferError('');
    if (modal) modal.style.display = 'flex';
    rdSearchBillTransferTargets();
    setTimeout(() => search?.focus(), 50);
}

function rdCloseBillTransferModal() {
    const modal = document.getElementById('rd-sub-modal-bill-transfer');
    if (modal) modal.style.display = 'none';
    rdBillTransferState.target = null;
    rdBillTransferState.targets = [];
    rdSetBillTransferError('');
    const list = document.getElementById('rd-transfer-target-list');
    if (list) list.innerHTML = '';
}

async function rdSubmitBillTransfer() {
    if (rdBillTransferState.submiting) return;
    const target = rdBillTransferState.target;
    const amountValue = document.getElementById('rd-transfer-amount')?.value || '';
    const note = document.getElementById('rd-transfer-note')?.value || '';
    const amount = rdNum(amountValue);
    const balance = rdBillTransferBalance();
    if (!target) {
        rdSetBillTransferError('Vui lòng chọn phòng nhận thanh toán');
        return;
    }
    if (amount <= 0 || amount > balance) {
        rdSetBillTransferError('Số tiền gộp phải lớn hơn 0 và không vượt quá số còn phải thu');
        return;
    }
    const targetRoom = target.room_number || target.stay_id;
    if (!confirm(`Xác nhận gộp ${pmsMoney(amount)} từ phòng hiện tại sang phòng ${targetRoom}?\nThao tác này có thể hoàn tác từ phòng nhận.`)) return;
    const btn = document.getElementById('rd-transfer-submit-btn');
    rdBillTransferState.submiting = true;
    if (btn) {
        btn.disabled = true;
        btn.style.opacity = '0.65';
        btn.textContent = 'Đang gộp...';
    }
    try {
        const params = new URLSearchParams({ target_stay_id: target.stay_id, amount: amountValue, note });
        const data = await pmsApi(`/api/pms/checkout/${rdStayData.id}/transfer-bill?${params.toString()}`, { method: 'POST' });
        rdCloseBillTransferModal();
        pmsToast(data.message || 'Đã gộp hoá đơn', true);
        rdResetPaymentRenderCache();
        rdFolioLoaded = false;
        await fetchFolio(rdStayData.id);
    } catch (e) {
        rdSetBillTransferError(e.message || 'Không thể gộp hoá đơn');
    } finally {
        rdBillTransferState.submiting = false;
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '';
            btn.textContent = 'Xác nhận gộp hoá đơn';
        }
    }
}

async function rdLoadPayment(autoOpenPayment) {
    const sessionAtStart = _rdSessionId;
    if (!rdStayData || !document.getElementById('rd-tab-payment')) return;
    rdSetBusy(true, 'Đang tải thanh toán...');
    const roomNumDisplay = document.querySelector('.rd-room-num-pay');
    if (roomNumDisplay) roomNumDisplay.textContent = document.getElementById('rd-room-num')?.textContent || '';

    const btn = document.getElementById('rd-pay-open-btn');
    if (btn) {
        btn.disabled = true;
        btn.style.opacity = '0.65';
        btn.style.transition = 'all 0.3s ease';
        btn.style.background = '#fff';
        btn.style.color = '#4a5568';
        btn.style.borderColor = '#c8dcdc';
        btn.style.boxShadow = 'none';
    }

    try {
        let shouldFetchPreview = true;

        if (!rdFolioHasFullData || !rdFolioLoaded || rdCurrentFolios.length === 0) {
            await fetchFolio(rdStayData.id);
            // fetchFolio already fetched the preview and stored it in rdPaymentState
            shouldFetchPreview = false;
        }

        if (shouldFetchPreview) {
            const endpoint = rdIsCheckedOut
                ? `/api/pms/checkout/${rdStayData.id}/preview-checked-out`
                : `/api/pms/checkout/${rdStayData.id}/preview?include_transactions=0`;
            const data = await pmsApi(endpoint, { method: 'GET' });

            // ── SESSION CHECK: bỏ qua nếu đã chuyển phòng ──
            if (sessionAtStart !== _rdSessionId) return;

            rdSetPaymentState({
                ...(rdPaymentState || {}),
                ...data,
                folios: (rdPaymentState && rdPaymentState.folios && rdPaymentState.folios.length > 0)
                    ? rdPaymentState.folios
                    : (data.folios || []),
            });
            if (rdCurrentFolios.length > 0) {
                rdPaymentState.folios = rdCurrentFolios;
                rdCurrentFolio = rdCurrentFolios[rdActiveFolioIndex] || rdCurrentFolios[0];
            }
        }

        rdUpdatePaymentRoomHeader(rdStayData, document.getElementById('rd-room-num')?.textContent || '', rdPaymentState);
        if (!rdFolioJustRendered) {
            rdRenderPaymentIfChanged();
        }
        rdFolioJustRendered = false;
        rdPayTabLoaded = true;

        // Cập nhật nút Thanh toán dựa trên balance + checked-out
        const balance = rdPaymentState?.projected_balance ?? rdCurrentFolio?.balance ?? 0;
        const btnFinal = document.getElementById('rd-pay-open-btn');
        if (btnFinal) {
            if (rdIsCheckedOut) {
                if (balance > 0) {
                    btnFinal.disabled = false;
                    btnFinal.style.opacity = '';
                    btnFinal.style.pointerEvents = '';
                    btnFinal.style.background = '#f59e0b';
                    btnFinal.style.color = '#fff';
                    btnFinal.style.borderColor = '#f59e0b';
                    btnFinal.style.boxShadow = '0 8px 16px -4px rgba(245, 158, 11, 0.4)';
                    btnFinal.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> Thu nợ`;
                } else {
                    btnFinal.disabled = true;
                    btnFinal.style.opacity = '0.55';
                    btnFinal.style.pointerEvents = 'none';
                    btnFinal.style.background = '#94a3b8';
                    btnFinal.style.color = '#fff';
                    btnFinal.style.borderColor = '#94a3b8';
                    btnFinal.style.boxShadow = 'none';
                    btnFinal.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><polyline points="20 6 9 17 4 12"/></svg> Đã tất toán`;
                }
            } else {
                // Phòng đang ở: cho phép thanh toán thêm
                if (balance > 0) {
                    btnFinal.disabled = false;
                    btnFinal.style.opacity = '';
                    btnFinal.style.pointerEvents = '';
                    btnFinal.style.background = '#10b981';
                    btnFinal.style.color = '#fff';
                    btnFinal.style.borderColor = '#10b981';
                    btnFinal.style.boxShadow = '0 8px 16px -4px rgba(16, 185, 129, 0.4)';
                    btnFinal.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg> Thanh toán`;
                } else if (balance < 0) {
                    // Khách dư → cho nạp thêm
                    btnFinal.disabled = false;
                    btnFinal.style.opacity = '';
                    btnFinal.style.pointerEvents = '';
                    btnFinal.style.background = '#3b82f6';
                    btnFinal.style.color = '#fff';
                    btnFinal.style.borderColor = '#3b82f6';
                    btnFinal.style.boxShadow = '0 8px 16px -4px rgba(59, 130, 246, 0.4)';
                    btnFinal.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> Nạp thêm`;
                } else {
                    // Balance = 0: Vẫn hiện nút "Nạp thêm" màu xanh dương để có thể thêm dịch vụ/phát sinh
                    btnFinal.disabled = false;
                    btnFinal.style.opacity = '';
                    btnFinal.style.pointerEvents = '';
                    btnFinal.style.background = '#3b82f6';
                    btnFinal.style.color = '#fff';
                    btnFinal.style.borderColor = '#3b82f6';
                    btnFinal.style.boxShadow = '0 8px 16px -4px rgba(59, 130, 246, 0.4)';
                    btnFinal.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> Nạp thêm`;
                }
            }
        }
        rdUpdateBillTransferButton(balance);
        rdUpdateCheckedOutPaymentActions();
        rdUpdateClosedRoomRight();
    } catch (e) {
        console.error('[rdLoadPayment]', e);
        pmsToast('Không thể tải dữ liệu thanh toán: ' + e.message, false);
    } finally {
        if (sessionAtStart === _rdSessionId) rdSetBusy(false);
    }

    // Auto open payment popup nếu được yêu cầu
    if (autoOpenPayment || rdAutoOpenPaymentPopup) {
        rdAutoOpenPaymentPopup = false;
        setTimeout(() => {
            if (typeof rdPayOpenPopup === 'function') rdPayOpenPopup('rd-sub-modal-payment');
        }, 200);
    }
}

async function openRoomDetail(stayId, num, targetTab = 'room') {
        // ── SESSION GUARD: tăng counter, mọi API response cũ sẽ bị bỏ qua ──
        const thisSession = ++_rdSessionId;

        const elRdStayId = document.getElementById('rd-stay-id');
        if (elRdStayId) elRdStayId.value = stayId;

        // === STEP 1: HỦY live refresh interval cũ ===
        if (_rdRiInterval) {
            clearInterval(_rdRiInterval);
            _rdRiInterval = null;
        }
        _rdRiUnbindCoEstListener();

        // === STEP 2: RESET ALL STATE DATA ===
        rdStayData = null;
        rdGuestList = [];
        rdTempServices = [];
        rdTempSurcharges = [];
        rdCurrentFolio = null;
        rdCurrentFolios = [];
        rdActiveFolioIndex = 0;
        rdFolioLoaded = false;
        rdFolioHasFullData = false;
        rdFolioLoading = false;
        rdFolioLightLoading = false;
        rdFolioJustRendered = false;
        rdPaymentState = null;
        rdPayTabLoaded = false;
        rdIsCheckedOut = false;
        rdFolioLoadPromise = null;
        rdResetPaymentRenderCache();
        rdResetRoomInfoRenderCache();
        rdCloseBillTransferModal();
        rdBillTransferState = { target: null, targets: [], requestId: rdBillTransferState.requestId + 1, submiting: false, searchTimer: null };
        rdNotesLastSavedValue = '';
        clearTimeout(rdNotesSaveTimer);

        // === STEP 3: RESET VISUAL UI NGAY LẬP TỨC (trước mọi API call) ===
        _rdResetVisualUI();
        rdSetBusy(true, 'Đang tải dữ liệu phòng...');
        rdSetPriceCardUpdating(true, 'Đang tải giá');

        // === STEP 4: STORE targetTab for post-fetch callback ===
        const _targetTab = targetTab;

        // === STEP 5: SWITCH TAB (hiện skeleton) ===
        if (typeof rdSwitchTab === 'function') {
            rdSwitchTab(targetTab);
        }

        const rdModalEl = document.getElementById('rdModal');
        if (typeof openModal === 'function') {
            openModal('rdModal');
        } else if (typeof pmsOpenModal === 'function') {
            pmsOpenModal('rdModal');
        } else if (rdModalEl) {
            rdModalEl.style.removeProperty('display');
            void rdModalEl.offsetWidth;
            rdModalEl.classList.add('show');
        }

        // === STEP 6: FETCH API (chạy nền, modal đã hiển thị skeleton) ===
        const elSearch = document.getElementById('rd-search-guest');
        if (elSearch) elSearch.value = '';
        const elFilterStatus = document.getElementById('rd-filter-status');
        if (elFilterStatus) elFilterStatus.value = 'all';

        try {
            const d = await pmsApi(`/api/pms/stays/${stayId}`);

            // ── SESSION CHECK: Nếu người dùng đã mở phòng khác → bỏ qua ──
            if (thisSession !== _rdSessionId) return;

            rdStayData = d;
            rdMaxGuests = d.max_guests || 2;
            rdIsCheckedOut = d.is_checked_out === true;

            // Cập nhật giao diện cho checked-out stays
            if (rdIsCheckedOut) {
                pmsRdApplyCheckedOutMode();
            } else {
                pmsRdRemoveCheckedOutMode();
            }

            // --- Cập nhật Tab 1: Thông tin chung ---
            document.getElementById('rd-ci').value = d.check_in_at ? pmsDateToDatetimeLocalVN(pmsParseDate(d.check_in_at)) : '';
            if (d.check_out_at) {
                const coEst = pmsParseDate(d.check_out_at);
                document.getElementById('rd-co-est').value = pmsDateToDatetimeLocalVN(coEst);
            } else {
                document.getElementById('rd-co-est').value = '';
            }
            document.getElementById('rd-notes').value = d.notes || '';
            const elNotesRoom = document.getElementById('rd-notes-room');
            if (elNotesRoom) elNotesRoom.value = d.notes || '';
            rdNotesLastSavedValue = d.notes || '';
            rdSetNotesSaveState('', 'idle');
            const elRoomNumNotes = document.getElementById('rd-room-num-notes');
            if (elRoomNumNotes) elRoomNumNotes.textContent = num;

            // Room info (read-only)
            const elRoomNumRo = document.getElementById('rd-room-num-ro');
            if (elRoomNumRo) elRoomNumRo.value = num;
            const elRoomTypeRo = document.getElementById('rd-room-type-ro');
            if (elRoomTypeRo) elRoomTypeRo.value = d.room_type || '';
            const elRoomNum = document.getElementById('rd-room-num');
            if (elRoomNum) elRoomNum.textContent = num;

            // Deposit
            const elDeposit = document.getElementById('rd-deposit');
            if (elDeposit) elDeposit.value = pmsMoney(d.deposit || 0);

            const elRoomNumDisp = document.getElementById('rd-room-num-display');
            if (elRoomNumDisp) elRoomNumDisp.textContent = num;
            const elRoomDropdown = document.getElementById('rd-room-selector-dropdown');
            if (elRoomDropdown) {
                elRoomDropdown.innerHTML = `<option value="${num}">Phòng ${num} — ${d.room_type || ''}</option>`;
            }

            // Vehicle
            const primaryGuest = (d.guests || []).find(g => g.is_primary) || (d.guests || [])[0];
            rdUpdatePaymentRoomHeader(d, num);
            const elVehicle = document.getElementById('rd-vehicle');
            const elVehDisp = document.getElementById('rd-ri-vehicle');
            const elVehPill = document.getElementById('rd-ri-vehicle-pill');
            const vehVal = (primaryGuest && primaryGuest.vehicle) ? primaryGuest.vehicle : '';
            if (elVehicle) elVehicle.value = vehVal;
            if (elVehDisp) elVehDisp.value = vehVal;
            rdVehicleLastSavedValue = vehVal;
            rdSetVehicleSaveState('', 'idle');
            if (elVehPill) {
                elVehPill.style.display = 'flex';
            }

            // Legacy debug fields
            const oldRmType = document.getElementById('rd-room-type');
            if (oldRmType) oldRmType.textContent = d.room_type || '';
            const oldStyType = document.getElementById('rd-stay-type');
            if (oldStyType) oldStyType.textContent = d.stay_type === 'hour' ? 'Thuê giờ' : 'Qua đêm';

            // Payment tab prep
            const rNumPay = document.querySelectorAll('.rd-room-num-pay');
            rNumPay.forEach(el => el.textContent = num);


            // Stay type badge
            const elStayType = document.getElementById('rd-stay-type-badge');
            if (elStayType) {
                const st = d.stay_type || 'NIGHT';
                elStayType.textContent = st;
                elStayType.style.background = st === 'HOURLY' ? 'rgba(245,158,11,0.15)' : 'rgba(59,130,246,0.12)';
                elStayType.style.color = st === 'HOURLY' ? '#d97706' : '#3b82f6';
            }

            // Guest list
            rdGuestList = (d.guests || []).map(g => ({
                id: g.id,
                crm_guest_id: g.crm_guest_id != null ? g.crm_guest_id : null,
                full_name: g.full_name || '',
                gender: g.gender || '',
                birth_date: g.birth_date || '',
                phone: g.phone || '',
                cccd: g.cccd || '',
                is_primary: g.is_primary || false,
                vehicle: g.vehicle || '',
                notes: g.notes || '',
                address: g.address || '',
                address_type: g.address_type || 'new',
                city: g.city || '',
                district: g.district || '',
                ward: g.ward || '',
                id_expire: g.id_expire || '',
                id_type: g.id_type || 'cccd',
                tax_code: g.tax_code || '',
                invoice_contact: g.invoice_contact || '',
                company_name: g.company_name || '',
                company_address: g.company_address || '',
                nationality: g.nationality || 'VNM - Việt Nam',
                check_in_at: g.check_in_at || d.check_in_at,
                check_out_at: g.check_out_at || null,
            }));

            const primaryG = rdGuestList.find(g => g.is_primary) || rdGuestList[0];
            if (primaryG) {
                document.getElementById('rd-rep-name').value = primaryG.full_name || '';
                const elRepPhone = document.getElementById('rd-rep-phone');
                if (elRepPhone) elRepPhone.value = primaryG.phone || '';
                const idTypeMap = { 'cccd': 'Căn cước công dân', 'cmnd': 'CMND', 'passport': 'Hộ chiếu', 'gplx': 'GPLX', 'other': 'Khác' };
                const elRepIdTypeRo = document.getElementById('rd-rep-id-type-ro');
                if (elRepIdTypeRo) elRepIdTypeRo.value = idTypeMap[primaryG.id_type || 'cccd'] || 'Căn cước';
                const elRepIdType = document.getElementById('rd-rep-id-type');
                if (elRepIdType) elRepIdType.value = primaryG.id_type || 'cccd';
                const elRepCccd = document.getElementById('rd-rep-cccd');
                if (elRepCccd) elRepCccd.value = primaryG.cccd || '';
                const elRepBirth = document.getElementById('rd-rep-birth');
                if (elRepBirth) elRepBirth.value = primaryG.birth_date || '';
                const elRepAddr = document.getElementById('rd-rep-address');
                if (elRepAddr) elRepAddr.value = rdFormatFullAddress(primaryG);
            }

            const elMaxGuests = document.getElementById('rd-max-guests-display');
            if (elMaxGuests) elMaxGuests.textContent = rdMaxGuests;

            // ── SESSION CHECK lần 2 trước khi render ──
            if (thisSession !== _rdSessionId) return;

            const filterEl = document.getElementById('rd-filter-status');
            if (rdIsCheckedOut && filterEl) filterEl.value = 'all';
            const filterStatus = filterEl?.value || 'all';
            pmsRdRenderGuestList('', filterStatus);
            pmsRdRenderActiveLists();
            pmsRdUpdateCapacityWarn();

            if (_targetTab === 'payment') {
                rdSwitchTab('payment');  // Đã có rdStayData → rdLoadPayment sẽ chạy đúng
            } else if (_targetTab === 'room') {
                await rdLoadRoomTabData();
                rdSetBusy(false);
            } else {
                rdSetBusy(false);
            }

        } catch (e) {
        // ── SESSION CHECK: bỏ qua lỗi của phiên cũ ──
        if (thisSession !== _rdSessionId) return;
        rdSetBusy(false);
        console.error('[rd] API fetch failed:', e);
        const rdModalEl = document.getElementById('rdModal');
        if (rdModalEl) {
            rdModalEl.classList.remove('show');
            setTimeout(() => rdModalEl.style.removeProperty('display'), 200);
        }
        if (typeof pmsToast === 'function') pmsToast('Không tải được chi tiết: ' + e.message, false);
        else alert('Không tải được chi tiết: ' + e.message);
        return;
    }
}
async function pmsRdUpdateStay() {
    if (rdIsCheckedOut) {
        pmsToast('Phòng đã trả. Không thể cập nhật.', false);
        return;
    }

    const stayId = document.getElementById('rd-stay-id').value;
    const ciVal = document.getElementById('rd-ci')?.value;
    const coEstVal = document.getElementById('rd-co-est')?.value;
    const depositVal = document.getElementById('rd-deposit')?.value;
    const notesVal = document.getElementById('rd-notes')?.value;

    try {
        const r = await pmsApi(`/api/pms/stays/${stayId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                check_in_at: ciVal || null,
                check_out_at: coEstVal || null,
                deposit: depositVal ? parseFloat(depositVal.replace(/[.,\s]/g, '')) || 0 : 0,
                notes: notesVal || null,
            })
        });
        
        pmsToast('Cập nhật thành công');
        if (rdStayData) {
            rdStayData = {
                ...rdStayData,
                check_in_at: ciVal || rdStayData.check_in_at || null,
                check_out_at: r?.check_out_at || coEstVal || null,
                deposit: depositVal ? parseFloat(depositVal.replace(/[.,\s]/g, '')) || 0 : 0,
                notes: notesVal || null,
            };
        }

        // Re-fetch pricing preview to update Room Info Card
        rdRenderRoomInfoCard();

        pmsRdNotifyInventoryInvalidated(stayId, {
            check_in_at: ciVal || null,
            check_out_at: r?.check_out_at || coEstVal || null,
            reason: 'stay_time_updated',
        });

        const elRdRoomNum = document.getElementById('rd-room-num');
        const roomNum = elRdRoomNum ? elRdRoomNum.textContent : '';
        if (typeof pmsSetRoomLoading === 'function') pmsSetRoomLoading(null, roomNum);
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
        return r;

    } catch (e) {
        console.error('[rd] updateStay failed:', e);
        pmsToast(e.message, false);
        return null;
    }
}
function pmsRdUpdateCapacityWarn() {
    const gcb = document.querySelector('.rd-guest-count-bar');
    const statusPill = document.getElementById('rd-gcb-status-pill');
    const warnSvg = document.getElementById('rd-capacity-warn-svg');

    if (!gcb) return;
    const activeCount = rdIsCheckedOut
        ? rdGuestList.length
        : rdGuestList.filter(g => !g.check_out_at).length;

    const countEl = document.getElementById('rd-guest-count-display');
    if (countEl) countEl.textContent = activeCount;

    if (rdIsCheckedOut) {
        const filterEl = document.getElementById('rd-filter-status');
        if (filterEl && filterEl.value === 'staying') filterEl.value = 'all';
        gcb.classList.remove('over');
        gcb.classList.add('checked-out');
        if (statusPill) {
            statusPill.textContent = 'Đã trả';
            statusPill.classList.remove('over');
        }
        if (warnSvg) warnSvg.style.display = 'none';
        return;
    }

    gcb.classList.remove('checked-out');

    if (activeCount > rdMaxGuests) {
        gcb.classList.add('over');
        if (statusPill) {
            statusPill.textContent = 'Vượt giới hạn';
            statusPill.classList.add('over');
        }
        if (warnSvg) warnSvg.style.display = 'flex';
    } else {
        gcb.classList.remove('over');
        if (statusPill) {
            statusPill.textContent = 'Còn chỗ';
            statusPill.classList.remove('over');
        }
        if (warnSvg) warnSvg.style.display = 'none';
    }
}

function pmsRdSearchGuest() {
    const text = document.getElementById('rd-search-guest')?.value || '';
    const status = document.getElementById('rd-filter-status')?.value || 'all';
    pmsRdRenderGuestList(text, status);
}

// ── Listener: recalculate pricing when expected checkout time changes ───────
let _rdCoEstListener = null;

function _rdRiBindCoEstListener() {
    if (_rdCoEstListener) return; // already bound
    const el = document.getElementById('rd-co-est');
    if (!el) return;
    _rdCoEstListener = () => {
        if (!rdIsCheckedOut && rdStayData && rdStayData.id) {
            rdRenderRoomInfoCard();
        }
    };
    el.addEventListener('change', _rdCoEstListener);
    el.addEventListener('input', _rdCoEstListener);
}

function _rdRiUnbindCoEstListener() {
    if (!_rdCoEstListener) return;
    const el = document.getElementById('rd-co-est');
    if (el) {
        el.removeEventListener('change', _rdCoEstListener);
        el.removeEventListener('input', _rdCoEstListener);
    }
    _rdCoEstListener = null;
}
function pmsRdResetFilter() {
    const elSearch = document.getElementById('rd-search-guest');
    if (elSearch) elSearch.value = '';
    const elFilterStatus = document.getElementById('rd-filter-status');
    if (elFilterStatus) elFilterStatus.value = 'all';
    pmsRdSearchGuest();
}

/**
 * Bật chế độ "đã trả phòng" — ẩn các action không phù hợp cho checked-out stays
 */
function pmsRdApplyCheckedOutMode() {
    // Thêm class vào modal header để CSS hiển thị badge
    const rdModal = document.getElementById('rdModal');
    if (rdModal) rdModal.classList.add('rd-checked-out');

    // Ẩn nút gia hạn
    const extBtn = document.getElementById('rd-extend-btn');
    if (extBtn) extBtn.style.display = 'none';

    // Giữ layout cột phải giống lúc đang ở, nhưng khóa thao tác ghi nhận.
    const svBtn = document.getElementById('rd-add-service-btn');
    const surBtn = document.getElementById('rd-add-surcharge-btn');
    [svBtn, surBtn].forEach(btn => {
        if (!btn) return;
        btn.style.display = 'flex';
        btn.style.opacity = '0.46';
        btn.style.pointerEvents = 'none';
        btn.style.cursor = 'not-allowed';
        btn.style.filter = 'grayscale(0.2)';
        btn.setAttribute('aria-disabled', 'true');
    });

    // Ẩn nút trong tab thanh toán
    const paySvBtn = document.getElementById('rd-pay-add-service-btn');
    if (paySvBtn) paySvBtn.style.display = 'none';
    const paySurBtn = document.getElementById('rd-pay-add-surcharge-btn');
    if (paySurBtn) paySurBtn.style.display = 'none';

    // Ẩn nút giảm giá trong tab thanh toán
    const discBtn = document.getElementById('rd-pay-add-discount-btn');
    if (discBtn) discBtn.style.display = 'none';

    // Ẩn nút Thanh toán trong tab thanh toán (CHỈ khi balance <= 0)
    // rdLoadPayment sẽ quyết định hiện/ẩn dựa trên balance
    // const openPayBtn = document.getElementById('rd-pay-open-btn');
    // if (openPayBtn) {
    //     openPayBtn.disabled = true;
    //     openPayBtn.style.opacity = '0';
    //     openPayBtn.style.pointerEvents = 'none';
    // }

    // Ẩn nút thêm khách trong tab thông tin chung
    const addGuestBtns = document.querySelectorAll('[id^="rd-add-guest"]');
    addGuestBtns.forEach(b => { b.style.display = 'none'; });

    // Ẩn nút checkout trong tab thanh toán
    const coBtn = document.getElementById('rd-pay-checkout-btn');
    if (coBtn) {
        coBtn.disabled = true;
        coBtn.style.display = 'none';
        coBtn.style.opacity = '0.45';
        coBtn.style.cursor = 'not-allowed';
        coBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> Đã trả phòng`;
    }

    const badge = document.getElementById('rd-checked-out-badge');
    if (badge) badge.remove();

    const typeBadge = document.getElementById('rd-ri-type-badge');
    if (typeBadge) typeBadge.style.display = 'none';

    rdUpdateClosedRoomRight();
    rdUpdateCheckedOutPaymentActions();
    }

/**
 * Gỡ chế độ checked-out — khôi phục UI cho stay đang hoạt động
 */
function pmsRdRemoveCheckedOutMode() {
    const rdModal = document.getElementById('rdModal');
    if (rdModal) rdModal.classList.remove('rd-checked-out');

    // Hiện lại các nút đã ẩn
    const extBtn = document.getElementById('rd-extend-btn');
    if (extBtn) extBtn.style.display = '';
    const svBtn = document.getElementById('rd-add-service-btn');
    if (svBtn) {
        svBtn.style.display = '';
        svBtn.style.opacity = '';
        svBtn.style.pointerEvents = '';
        svBtn.style.cursor = '';
        svBtn.style.filter = '';
        svBtn.removeAttribute('aria-disabled');
    }
    const surBtn = document.getElementById('rd-add-surcharge-btn');
    if (surBtn) {
        surBtn.style.display = '';
        surBtn.style.opacity = '';
        surBtn.style.pointerEvents = '';
        surBtn.style.cursor = '';
        surBtn.style.filter = '';
        surBtn.removeAttribute('aria-disabled');
    }
    const paySvBtn = document.getElementById('rd-pay-add-service-btn');
    if (paySvBtn) paySvBtn.style.display = '';
    const paySurBtn = document.getElementById('rd-pay-add-surcharge-btn');
    if (paySurBtn) paySurBtn.style.display = '';
    const discBtn = document.getElementById('rd-pay-add-discount-btn');
    if (discBtn) discBtn.style.display = '';

    const addGuestBtns = document.querySelectorAll('[id^="rd-add-guest"]');
    addGuestBtns.forEach(b => { b.style.display = ''; });

    // Hiện lại nút checkout (mặc định payment.html đã ẩn)
    const coBtn = document.getElementById('rd-pay-checkout-btn');
    if (coBtn) {
        coBtn.disabled = false;
        coBtn.style.display = '';
        coBtn.style.opacity = '';
        coBtn.style.cursor = '';
        coBtn.style.background = '#088395';
        coBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> Trả phòng`;
    }

    // Hiện lại nút Thanh toán
    const openPayBtn = document.getElementById('rd-pay-open-btn');
    if (openPayBtn) {
        openPayBtn.disabled = false;
        openPayBtn.style.opacity = '';
        openPayBtn.style.display = '';
        openPayBtn.style.pointerEvents = '';
    }

    // Xóa badge
    const badge = document.getElementById('rd-checked-out-badge');
    if (badge) badge.remove();
    const typeBadge = document.getElementById('rd-ri-type-badge');
    if (typeBadge) typeBadge.style.display = '';
    rdUpdateClosedRoomRight();
    rdUpdateCheckedOutPaymentActions();
}
function pmsRdRenderGuestList(filterText = '', filterStatus = 'staying') {
    const panel = document.getElementById('rd-guest-list-panel');
    if (!panel) return;

    let filteredList = rdGuestList;

    // 1. Filter by Status
    if (filterStatus === 'staying') {
        filteredList = filteredList.filter(g => !g.check_out_at);
    } else if (filterStatus === 'out') {
        filteredList = filteredList.filter(g => !!g.check_out_at);
    }

    // 2. Filter by Search Text
    if (filterText) {
        const f = filterText.toLowerCase();
        filteredList = filteredList.filter(g =>
            (g.full_name || '').toLowerCase().includes(f) ||
            (g.cccd || '').toLowerCase().includes(f)
        );
    }

    if (filteredList.length === 0) {
        let msg = 'Chưa có khách trong danh sách.';
        if (filterText || filterStatus !== 'all') msg = 'Không tìm thấy khách phù hợp.';
        panel.innerHTML = `<p style="margin:0;font-size:13px;color:#64748b;text-align:center;padding:24px;">${msg}</p>`;
        return;
    }
    panel.innerHTML = filteredList.map((g, i) => {
        const isOut = !!g.check_out_at;
        const bg = isOut ? '#f8fafc' : '#fff';
        const borderColor = isOut ? '#e2e8f0' : 'rgba(122, 178, 178, 0.5)';
        const ciStr = g.check_in_at ? pmsFormatDateTimeVN(g.check_in_at) : '—';
        const coStr = g.check_out_at ? pmsFormatDateTimeVN(g.check_out_at) : (isOut ? '—' : 'Đang ở');

        // Gender Icon
        let genderIcon = `
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        `;
        if (g.gender === 'Nam') {
            genderIcon = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5" title="Nam">
              <circle cx="10" cy="14" r="5"/><path d="M14 10l7-7m-4 0h4v4"/>
            </svg>
          `;
        } else if (g.gender === 'Nữ') {
            genderIcon = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ec4899" stroke-width="2.5" title="Nữ">
              <circle cx="12" cy="8" r="5"/><path d="M12 13v8m-3-3h6"/>
            </svg>
          `;
        }

        return `
        <div style="flex-shrink:0; border:none; border-radius:12px; padding:12px; background:${bg}; display:flex; justify-content:space-between; align-items:flex-start; box-shadow:0 2px 8px rgba(0,0,0,0.04); margin-bottom:8px; transition: all 0.2s;">
          <div style="display:flex; gap:14px; align-items:flex-start; flex:1;">
            <!-- Column 1: Identity -->
            <div style="flex:1; border-right:1px solid #f1f5f9; padding-right:14px;">
              <div style="font-weight:700; color:#334155; font-size:14px; display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                ${genderIcon}
                ${g.is_primary ? '<span style="background:#dcfce7;color:#16a34a;padding:1px 8px;border-radius:10px;font-size:9px;letter-spacing:0.3px;">CHÍNH</span>' : ''} 
                <span style="letter-spacing:0.2px;">${pmsEscapeHtml(g.full_name || 'CHƯA NHẬP TÊN').toUpperCase()}</span>
                ${isOut ? '<span style="background:#f1f5f9;color:#64748b;padding:1px 8px;border-radius:10px;font-size:9px;">ĐÃ RA</span>' : ''}
              </div>
              <div style="display:flex; flex-direction:column; gap:3px;">
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  Giấy tờ: <strong style="color:#475569;">${pmsEscapeHtml(g.id_type?.toUpperCase() || 'CCCD')}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  Số: <strong style="color:#1e293b;">${pmsEscapeHtml(g.cccd || '—')}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f43f5e" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                  Ngày hết hạn: <strong style="color:#475569;">${g.id_expire ? pmsFormatDateVN(g.id_expire) : '—'}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
                  SĐT: <strong style="color:#1e293b;">${pmsEscapeHtml(g.phone || '—')}</strong>
                </div>
              </div>
            </div>

            <!-- Column 2: Stay Info & Address -->
            <div style="flex:1;">
              <div style="display:flex; flex-direction:column; gap:3px;">
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                  Ngày sinh: <strong style="color:#475569;">${g.birth_date ? pmsFormatDateVN(g.birth_date) : '—'}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                  Vào: <strong style="color:#059669;">${ciStr}</strong>
                </div>
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; color:#09637E;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  Ra: <strong style="color:#dc2626;">${coStr}</strong>
                </div>
                <div style="display:flex; align-items:flex-start; gap:8px; font-size:12px; color:#64748b; border-top:1px dashed #e2e8f0; padding-top:4px; margin-top:2px;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                  <div style="color:#475569; font-weight:500;">
                    ${pmsEscapeHtml(rdFormatFullAddress(g))}
                  </div>
                </div>
                <div style="display:flex; align-items:flex-start; gap:8px; font-size:12px; color:#64748b; margin-top:2px;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  <div style="color:#475569; font-style:italic;">
                    ${g.notes ? pmsEscapeHtml(g.notes) : '—'}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div style="display:flex; flex-direction:column; gap:10px; padding-left:20px; border-left:1px solid #f1f5f9; margin-left:10px; height:100%; justify-content:center;">
            <button onclick="pmsRdEditGuest(${i})" style="background:#fff; border:1px solid #e2e8f0; color:#64748b; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer;" title="Sửa thông tin">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            ${!g.is_primary && !g.check_out_at ? `
            <button onclick="pmsRdCheckoutGuest(${i})" style="background:#fff; border:1px solid #e2e8f0; color:#ef4444; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer;" title="Trả phòng">
               <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                 <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                 <polyline points="16 17 21 12 16 7" />
                 <line x1="21" y1="12" x2="9" y2="12" />
               </svg>
            </button>
            ` : ''}
          </div>
        </div>
        `;
    }).join('');
    pmsRdUpdateCapacityWarn();
}
async function pmsRdCheckoutGuest(i) {
    const g = rdGuestList[i];
    if (!g) return;
    if (g.is_primary) {
        pmsToast('Khách chính không thể trả phòng riêng. Vui lòng trả phòng toàn bộ.', false);
        return;
    }
    if (g.check_out_at) {
        pmsToast('Khách này đã trả phòng rồi.', false);
        return;
    }
    if (!confirm(`Bạn có chắc muốn trả phòng cho khách "${g.full_name}"?`)) return;

    try {
        const stayId = document.getElementById('rd-stay-id').value;
        const r = await pmsApi(`/api/pms/guests/${g.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ check_out_at: true })
        });

        const coAt = r.check_out_at || null;
        rdGuestList[i] = { ...rdGuestList[i], check_out_at: coAt };

        if (rdStayData && rdStayData.guests) {
            const guestInData = rdStayData.guests.find(g2 => g2.id === g.id);
            if (guestInData) guestInData.check_out_at = coAt;
        }

        pmsToast(`Đã trả phòng cho "${g.full_name}"`);

        // Switch filter to 'all' so user can see the checked-out guest with status badge
        const filterEl = document.getElementById('rd-filter-status');
        if (filterEl) {
            filterEl.value = 'all';
        }

        // Re-render guest list (show all including checked-out)
        pmsRdRenderGuestList('', 'all');
        pmsRdUpdateCapacityWarn();

        // Refresh dashboard room cards after guest checkout
        if (typeof pmsLoadRooms === 'function') pmsLoadRooms(undefined, true);

    } catch (e) {
        console.error('[rd] checkoutGuest failed:', e);
        pmsToast(e.message, false);
    }
}
function pmsRdEditGuest(i) {
    const g = rdGuestList[i];
    if (!g) return;

    const elRdStayId = document.getElementById('rd-stay-id');
    const stayId = elRdStayId ? elRdStayId.value : '';
    const guestId = g.id;

    if (!stayId || !guestId) {
        pmsToast('Thiếu thông tin lưu trú hoặc khách', false);
        return;
    }

    // Open the dedicated Edit Guest modal (ID fields LOCKED)
    if (typeof openEG === 'function') {
        openEG(parseInt(stayId), guestId);
    } else {
        pmsToast('Chức năng sửa khách chưa sẵn sàng', false);
    }
}


async function fetchFolio(stayId) {
    if (rdFolioLoadPromise) return rdFolioLoadPromise;
    rdFolioLoadPromise = (async () => {
        const sessionAtStart = _rdSessionId;

    // Fallback: nếu stayId undefined nhưng có rdCurrentFolio hoặc rdStayData
    if (!stayId) {
        stayId = rdCurrentFolio?.stay_id || rdStayData?.id;
        if (!stayId) {
            console.warn('[fetchFolio] stayId is undefined — rdCurrentFolio may not be loaded yet');
            return;
        }
    }

    if (rdFolioLoading) {
        console.warn('[fetchFolio] Already loading, skipped duplicate call.');
        return;
    }

    rdFolioLoading = true;
    rdFolioJustRendered = false;
    let previewData = null;

    try {
        // ── Bước 1 & 2: FETCH PARALLEL ĐỂ TĂNG TỐC ──
        // Khởi chạy load folios và load preview đồng thời thay vì chờ tuần tự
        const folioUrl = `/api/pms/folio/${stayId}?include_transactions=1`;
        const folioPromise = pmsApi(folioUrl);
        let previewPromise = Promise.resolve(null);

        if (rdIsCheckedOut) {
            previewPromise = pmsApi(`/api/pms/checkout/${stayId}/preview-checked-out`).catch(previewErr => {
                console.warn('[fetchFolio] /preview-checked-out thất bại:', previewErr);
                return 'FALLBACK_CHECKED_OUT';
            });
        } else {
             previewPromise = pmsApi(`/api/pms/checkout/${stayId}/preview?include_transactions=0`).catch(previewErr => {
                console.warn('[fetchFolio] /preview thất bại:', previewErr);
                return null;
            });
        }

        // Đợi cả hai fetch hoàn thành
        const [r, previewDataResult] = await Promise.all([folioPromise, previewPromise]);

        // ── SESSION CHECK: Nếu người dùng đã mở phòng khác → bỏ qua kết quả ──
        if (sessionAtStart !== _rdSessionId) {
            console.warn(`[fetchFolio] Discarded stale response (session ${sessionAtStart} vs current ${_rdSessionId})`);
            return;
        }

        // ── Xử lý folios ──
        const rawFolios = r.folios || [];

        rdCurrentFolios = rawFolios.map(f => ({
            ...f,
            stay_id: f.stay_id || stayId,
            transactions: f.transactions || [],
        }));

        if (rdActiveFolioIndex >= rdCurrentFolios.length) rdActiveFolioIndex = 0;
        rdCurrentFolio = rdCurrentFolios[rdActiveFolioIndex] || rdCurrentFolios[0];
        if (rdCurrentFolio && !rdCurrentFolio.stay_id) {
            rdCurrentFolio.stay_id = stayId;
        }
        rdFolioLoaded = true;
        rdFolioHasFullData = true;
        if (previewDataResult === 'FALLBACK_CHECKED_OUT') {
             // Áp dụng fallback nếu preview lỗi
             previewData = {
                 projected_balance: rdCurrentFolio?.balance ?? 0,
                 effective_paid: 0,
                 deposit_used: 0,
                 total_paid: 0,
                 transactions: rdCurrentFolio?.transactions || [],
                 folio_summary: rdCurrentFolios.map(f => ({
                     id: f.id,
                     folio_code: f.folio_code,
                     total_charge: f.total_charge || 0,
                     total_discount: f.total_discount || 0,
                     net_charge: (f.total_charge || 0) - (f.total_discount || 0),
                     total_paid: f.total_paid || 0,
                     balance: f.balance || 0,
                     effective_paid: 0,
                     deposit_used: 0,
                     status: f.status,
                 })),
             };
        } else {
             previewData = previewDataResult;
        }

        // ── Bước 3: Merge preview data vào rdPaymentState ──
        if (previewData) {
            // Trộn preview (balance, effective_paid, deposit_used) + folios (transactions)
            // Chỉ ghi đè đúng fields cần thiết, giữ nguyên các fields khác nếu có
            rdPaymentState = {
                ...(rdPaymentState || {}),
                ...previewData,
                folios: rdCurrentFolios,
            };

            // ── Checked-out stays: dùng full ledger từ /folio?include_transactions=1.
            // /preview-checked-out chỉ giữ số tổng nhanh, không thay ledger chi tiết.
            if (rdIsCheckedOut) {
                if (previewData.transactions && previewData.transactions.length > 0) {
                    // Merge vào rdCurrentFolio.transactions để pmsRdRenderFolio dùng
                    if (rdCurrentFolio) {
                        rdCurrentFolio.transactions = previewData.transactions;
                    }
                }
                rdPaymentState.folios = rdCurrentFolios;
                
                // ── Inject breakdown charges vào transactions cho checked-out stays ──
                // Vì ROOM_CHARGE/SURCHARGE bị xóa sau checkout, cần lấy từ breakdown
                if (previewData.breakdown && previewData.breakdown.length > 0) {
                    const checkoutTime = previewData.check_out_at || rdStayData?.check_out_at || new Date().toISOString();
                    const checkInIso = rdStayData?.check_in_at || previewData.check_in_at || null;
                    const checkInMs = checkInIso ? (pmsParseDate(checkInIso)?.getTime() || null) : null;

                    // Deduplicate breakdown: chỉ giữ entry CUỐI cho mỗi transaction_type
                    // (tránh trùng lặp khi breakdown có nhiều dòng cùng loại)
                    const seenTypes = new Set();
                    const dedupedBreakdown = [];
                    for (let i = previewData.breakdown.length - 1; i >= 0; i--) {
                        const b = previewData.breakdown[i];
                        if (!seenTypes.has(b.type)) {
                            seenTypes.add(b.type);
                            dedupedBreakdown.unshift(b);
                        }
                    }

                    let cumulativeHourlyHrs = 0;
                    const virtualTxs = dedupedBreakdown.map((b, idx) => {
                        const isRoomType = ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(b.type);
                        let chargedAt = null;
                        if (b.type === 'HOURLY_CHARGE' && checkInMs) {
                            const hrs = parseInt(b.hours) || 0;
                            cumulativeHourlyHrs += hrs;
                            const offsetHrs = Math.max(0, cumulativeHourlyHrs - 1);
                            chargedAt = new Date(checkInMs + offsetHrs * 3600 * 1000).toISOString();
                        } else if (isRoomType) {
                            chargedAt = b.start_iso || checkInIso || checkoutTime;
                        } else {
                            chargedAt = b.created_at || checkoutTime;
                        }
                        return {
                            id: 'virtual-' + (b.type || 'charge') + '-' + idx,
                            category: isRoomType ? 'ROOM' : 'SURCHARGE',
                            transaction_type: b.type,
                            description: b.description || (isRoomType ? 'Tiền phòng' : 'Phí phát sinh'),
                            amount: parseFloat(b.amount) || 0,
                            quantity: b.hours || b.days || 1,
                            created_at: chargedAt,
                            created_by_name: 'Tạm tính',
                            is_virtual: true,
                            is_voided: false,
                        };
                    });
                    
                    if (rdCurrentFolio) {
                        // Chỉ thêm virtual transaction nếu chưa tồn tại (theo transaction_type)
                        const existingTypes = new Set(rdCurrentFolio.transactions.map(t => t.transaction_type || t.type));
                        const persistedCheckoutTypes = new Set(['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE', 'SURCHARGE']);
                        const uniqueVirtuals = virtualTxs.filter(vt => !existingTypes.has(vt.transaction_type) && !persistedCheckoutTypes.has(vt.transaction_type));
                        rdCurrentFolio.transactions = [...uniqueVirtuals, ...rdCurrentFolio.transactions];
                    }
                }
            }
            
            // ── Active stays: thêm breakdown charges vào transactions để hiển thị trong ledger ──
            // Vì ROOM_CHARGE/SURCHARGE chưa được lưu vào DB, cần lấy từ pricing preview
            if (!rdIsCheckedOut && previewData.breakdown && previewData.breakdown.length > 0) {
                const isOtaManualPreview = previewData.ota_price_mode === 'manual_channel_total' || rdIsOtaManualStay();
                const virtualSource = isOtaManualPreview
                    ? previewData.breakdown.filter(b => !['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(b.type))
                    : previewData.breakdown;
                const checkInIso = rdStayData?.check_in_at || previewData.check_in_at || null;
                const checkInMs = checkInIso ? (pmsParseDate(checkInIso)?.getTime() || null) : null;
                let cumulativeHourlyHrs = 0;
                const virtualTxs = virtualSource.map((b, idx) => {
                    const isRoomType = ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(b.type);
                    let chargedAt = null;
                    if (b.type === 'HOURLY_CHARGE' && checkInMs) {
                        const hrs = parseInt(b.hours) || 0;
                        cumulativeHourlyHrs += hrs;
                        // Timestamp = thời điểm BẮT ĐẦU của giờ cuối cùng được tính trong dòng này
                        const offsetHrs = Math.max(0, cumulativeHourlyHrs - 1);
                        chargedAt = new Date(checkInMs + offsetHrs * 3600 * 1000).toISOString();
                    } else if (isRoomType) {
                        chargedAt = b.start_iso || checkInIso || new Date().toISOString();
                    } else {
                        chargedAt = b.created_at || checkInIso || new Date().toISOString();
                    }
                    return {
                        id: 'virtual-' + (b.type || 'charge') + '-' + idx,
                        category: isRoomType ? 'ROOM' : 'SURCHARGE',
                        transaction_type: b.type,
                        description: b.description || (isRoomType ? 'Tiền phòng' : 'Phí phát sinh'),
                        amount: parseFloat(b.amount) || 0,
                        quantity: b.hours || b.days || 1,
                        created_at: chargedAt,
                        created_by_name: 'Tạm tính',
                        is_virtual: true,
                        is_voided: false,
                    };
                });
                
                // Thêm virtual transactions vào rdCurrentFolio để ledger hiển thị
                if (rdCurrentFolio) {
                    const existingIds = new Set(rdCurrentFolio.transactions.map(t => t.id));
                    virtualTxs.forEach(vt => {
                        if (!existingIds.has(vt.id)) {
                            rdCurrentFolio.transactions.push(vt);
                        }
                    });
                }
            }
        } else if (!rdPaymentState) {
            // Không có preview — tạo state tối thiểu từ folio
            const folioBal = rdCurrentFolio?.balance ?? 0;
            rdPaymentState = {
                projected_balance: folioBal,
                effective_paid: rdCurrentFolio?.total_paid ?? 0,
                deposit_used: 0,
                total_paid: rdCurrentFolio?.total_paid ?? 0,
                total_charge: rdCurrentFolio?.total_charge ?? 0,
                total_discount: rdCurrentFolio?.total_discount ?? 0,
                net_charge: (rdCurrentFolio?.total_charge ?? 0) - (rdCurrentFolio?.total_discount ?? 0),
                folio_summary: rdCurrentFolios.map(f => ({
                    id: f.id,
                    folio_code: f.folio_code,
                    total_charge: f.total_charge || 0,
                    total_discount: f.total_discount || 0,
                    net_charge: (f.total_charge || 0) - (f.total_discount || 0),
                    total_paid: f.total_paid || 0,
                    balance: f.balance || 0,
                    effective_paid: f.total_paid || 0,
                    deposit_used: 0,
                    status: f.status,
                })),
                folios: rdCurrentFolios,
            };
        } else {
            // rdPaymentState đã có (từ rdLoadPayment) — chỉ cập nhật folios
            rdPaymentState.folios = rdCurrentFolios;
        }

        // ── Bước 4: Render UI ──
        rdUpdatePaymentRoomHeader(rdStayData, rdStayData?.room_number || '', rdPaymentState);
        rdRenderPaymentIfChanged();
        rdFolioJustRendered = true;

        // ── Bước 5: Cập nhật debt badge ──
        const debtBadge = document.getElementById('rd-debt-badge');
        if (debtBadge) {
            debtBadge.style.display = (rdCurrentFolio && rdCurrentFolio.status === 'DEBT') ? 'inline-block' : 'none';
        }

    } catch (e) {
        console.error('[fetchFolio] Folio Fetch Error:', e);
        pmsToast('Không thể tải dữ liệu sổ cái: ' + e.message, false);
    } finally {
        rdFolioLoading = false;
        rdFolioLoadPromise = null;
    }
    })();
    return rdFolioLoadPromise;
}

// Render Folio summary into Room tab's mirror display (service + surcharge only)
function pmsRdMirrorFolio() {
    if (!rdFolioLoaded || !rdCurrentFolio) {
        const elSM = document.getElementById('rd-pay-dash-service-mirror');
        const elSurM = document.getElementById('rd-pay-dash-surcharge-mirror');
        if (elSM) elSM.textContent = '0';
        if (elSurM) elSurM.textContent = '0';
        const svList = document.getElementById('rd-services-active-list');
        const surList = document.getElementById('rd-surcharges-active-list');
        if (svList) svList.innerHTML = '';
        if (surList) surList.innerHTML = '';
        return;
    }

    const txs = rdCurrentFolio.transactions || [];

    const servTot = txs.length ? txs
        .filter(t => t.category === 'SERVICE' && !t.is_voided)
        .reduce((acc, t) => acc + rdNum(t.amount), 0) : 0;
    const surTot = txs.length ? txs
        .filter(t => (t.category === 'SURCHARGE' || t.category === 'OTHER') && !t.is_voided)
        .reduce((acc, t) => acc + rdNum(t.amount), 0) : 0;

    const elSM = document.getElementById('rd-pay-dash-service-mirror');
    const elSurM = document.getElementById('rd-pay-dash-surcharge-mirror');
    if (elSM) elSM.textContent = pmsMoney(servTot);
    if (elSurM) elSurM.textContent = pmsMoney(surTot);
    if (rdPaymentState || rdLastBreakdownRows.length > 0) {
        rdUpdateRoomPriceCardFromCache();
    }

    // Service list
    const svList = document.getElementById('rd-services-active-list');
            if (svList) {
                const svTxs = txs.filter(t => t.category === 'SERVICE' && !t.is_voided);
                svList.innerHTML = svTxs.map(t => {
            let desc = t.description || 'Dịch vụ';
            if (t.quantity >= 1) {
                desc = desc.replace(/\s*x\s*\d+$/i, '').trim();
            }
            const qtyStr = t.quantity >= 1 ? ` <span style="opacity:0.6; font-size:10px;">x${t.quantity}</span>` : '';
            const clickable = !rdIsCheckedOut && !t.is_virtual;
            return `<div class="rd-mini-list-item${clickable ? ' rd-mini-list-clickable' : ''}" ${clickable ? `onclick="pmsRdOpenRefundPopup(${t.id}, '${pmsEscapeHtml(desc).replace(/'/g, "\\'")}', ${parseInt(t.quantity) || 1}, ${parseFloat(t.unit_price || t.amount / (t.quantity || 1))})"` : ''}>
                <span class="rd-mini-list-name">${pmsEscapeHtml(desc)}${qtyStr}</span>
                <span class="rd-mini-list-val">${pmsMoney(t.amount)}</span>
            </div>`;
        }).join('');
    }

    // Surcharge list
    const surList = document.getElementById('rd-surcharges-active-list');
    if (surList) {
        const surTxs = txs.filter(t => (t.category === 'SURCHARGE' || t.category === 'OTHER') && !t.is_voided);
        surList.innerHTML = surTxs.map(t => {
            let desc = t.description || 'Phát sinh';
            if (t.quantity >= 1) {
                desc = desc.replace(/\s*x\s*\d+$/i, '').trim();
            }
            const qtyStr = t.quantity >= 1 ? ` <span style="opacity:0.6; font-size:10px;">x${t.quantity}</span>` : '';
            const clickable = !rdIsCheckedOut && !t.is_virtual;
            return `<div class="rd-mini-list-item${clickable ? ' rd-mini-list-clickable' : ''}" ${clickable ? `onclick="pmsRdOpenRefundPopup(${t.id}, '${pmsEscapeHtml(desc).replace(/'/g, "\\'")}', ${parseInt(t.quantity) || 1}, ${parseFloat(t.unit_price || t.amount / (t.quantity || 1))})"` : ''}>
                <span class="rd-mini-list-name">${pmsEscapeHtml(desc)}${qtyStr}</span>
                <span class="rd-mini-list-val">${pmsMoney(t.amount)}</span>
            </div>`;
        }).join('');
    }
    rdUpdateClosedRoomRight();
}

// Reset Folio state when modal is closed
function pmsRdResetFolioState() {
    rdFolioLoaded = false;
    rdFolioHasFullData = false;
    rdFolioLoading = false;
    rdFolioLightLoading = false;
    rdCurrentFolio = null;
    rdCurrentFolios = [];
    rdActiveFolioIndex = 0;
    rdPaymentState = null;
    rdPayTabLoaded = false;
    rdResetRoomInfoRenderCache();
}

/**
 * fetchFolioLight — phiên bản nhẹ của fetchFolio, chỉ fetch 1 API folio.
 * Dùng sau khi ghi/xoá dịch vụ để refresh Room Tab nhanh mà không cần gọi /preview.
 */
async function fetchFolioLight(stayId, options = {}) {
    stayId = stayId || rdCurrentFolio?.stay_id || rdStayData?.id;
    if (!stayId) return;
    // Nếu đang load nặng → đợi không gọi duplicate
    if (rdFolioLoading || rdFolioLightLoading) return;
    rdFolioLightLoading = true;
    try {
        const r = await pmsApi(`/api/pms/folio/${stayId}`);
        const rawFolios = r.folios || [];
        rdCurrentFolios = rawFolios.map(f => ({
            ...f,
            stay_id: f.stay_id || stayId,
            transactions: f.transactions || [],
        }));
        if (rdActiveFolioIndex >= rdCurrentFolios.length) rdActiveFolioIndex = 0;
        rdCurrentFolio = rdCurrentFolios[rdActiveFolioIndex] || rdCurrentFolios[0];
        if (rdCurrentFolio && !rdCurrentFolio.stay_id) rdCurrentFolio.stay_id = stayId;
        rdFolioLoaded = true;
        rdFolioHasFullData = false;
        // Chỉ update Room Tab mirror (nhanh, không render Payment Tab)
        pmsRdMirrorFolio();
        if (!options.skipRoomInfoRefresh && typeof rdRenderRoomInfoCard === 'function') {
            await rdRenderRoomInfoCard();
        }
    } catch (e) {
        console.warn('[fetchFolioLight]', e.message);
    } finally {
        rdFolioLightLoading = false;
        if (options.priceCardUpdating) rdSetPriceCardUpdating(false);
    }
}
window.fetchFolioLight = fetchFolioLight;

/**
 * Xoá giao dịch (void) từ tab Phòng — gọi chung API với Payment tab.
 * Dùng Optimistic UI: ẩn item ngay lập tức, rồi mới fetch lại nhẹ từ server.
 */
async function pmsRdVoidTx(txId) {
    if (!rdCurrentFolio) {
        pmsToast('Chưa mở Folio. Vui lòng vào tab Thanh toán trước.', false);
        return;
    }
    // ── Optimistic UI: Ẩn ngay item trong local state ──
    if (rdCurrentFolio.transactions) {
        const tx = rdCurrentFolio.transactions.find(t => t.id === txId);
        if (tx) tx.is_voided = true;
    }
    pmsRdMirrorFolio(); // Cập nhật UI ngay không chờ API
    rdSetPriceCardUpdating(true, 'Đang xoá dòng phí');

    try {
        const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/void/${txId}?reason=${encodeURIComponent('Xoá mềm từ tab Phòng')}`, { method: 'POST' });
        if (resp?.transaction) rdMergeTransactionUpdate(resp.transaction);
        pmsToast('Đã xoá mềm dòng phí');
        // Sau khi API xong → fetch folio và pricing-preview trước khi tắt overlay.
        await fetchFolioLight(rdStayData?.id, { skipRoomInfoRefresh: true });
        if (typeof pmsRdRenderFolioTabs === 'function') pmsRdRenderFolioTabs();
        if (typeof pmsRdRenderFolio === 'function') pmsRdRenderFolio();
        if (typeof rdRenderRoomInfoCard === 'function') await rdRenderRoomInfoCard({ force: true });
        rdSetPriceCardUpdating(false);
    } catch (e) {
        // Rollback optimistic update nếu API lỗi
        if (rdCurrentFolio.transactions) {
            const tx = rdCurrentFolio.transactions.find(t => t.id === txId);
            if (tx) tx.is_voided = false;
        }
        pmsRdMirrorFolio();
        rdSetPriceCardUpdating(false);
        pmsToast('Lỗi xoá: ' + e.message, false);
    }
}

function pmsSwitchTabAndFetchFolio(tabName) {
    if (tabName === 'payment' && rdFolioLoaded) {
        // Payment Tab: fetch fresh data from DB
        if (rdStayData && typeof fetchFolio === 'function') fetchFolio(rdStayData.id);
    }
    // Room Tab: just mirror existing rdCurrentFolio (already loaded)
}

function rdFormatDateTime(dt) {
    if (!dt) return '---';
    const HH = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    const DD = String(dt.getDate()).padStart(2, '0');
    const MM = String(dt.getMonth() + 1).padStart(2, '0');
    const YYYY = dt.getFullYear();
    const weekdays = ['Chủ Nhật', 'Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7'];
    const weekday = weekdays[dt.getDay()];
    return `${DD} - ${MM} - ${YYYY} | ${HH}:${mm} | ${weekday}`;
}

function rdNormalizeDateTimeLocal(value) {
    if (!value) return '';
    if (value instanceof Date) return pmsDateToDatetimeLocalVN(value);
    const raw = String(value).trim().replace(' ', 'T');
    const localMatch = raw.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?$/);
    if (localMatch) return `${localMatch[1]}T${localMatch[2]}`;
    const parsed = pmsParseDate(raw);
    return parsed && !Number.isNaN(parsed.getTime()) ? pmsDateToDatetimeLocalVN(parsed) : '';
}

function rdNowDateTimeLocalVN() {
    return pmsDateToDatetimeLocalVN(new Date());
}

function rdBuildDateTimeLocalVN(date, time) {
    if (!date || !time) return '';
    return `${date}T${String(time).slice(0, 5)}`;
}

function rdDateTimeLocalVNToDate(value) {
    const local = rdNormalizeDateTimeLocal(value);
    if (!local) return null;
    const normalized = local.length === 16 ? `${local}:00` : local;
    const dt = new Date(`${normalized}+07:00`);
    return Number.isNaN(dt.getTime()) ? null : dt;
}

function rdFormatDateTimeLocalVN(value) {
    const local = rdNormalizeDateTimeLocal(value);
    if (!local) return '---';
    const [datePart, timePart] = local.split('T');
    const [yyyy, mm, dd] = datePart.split('-');
    const weekdayDate = rdDateTimeLocalVNToDate(`${datePart}T00:00`);
    const weekday = weekdayDate
        ? new Intl.DateTimeFormat('vi-VN', { timeZone: PMS_VN_TZ, weekday: 'long' }).format(weekdayDate)
        : '';
    return `${dd} - ${mm} - ${yyyy} | ${timePart} | ${weekday}`;
}
// ═══════════════════════════════════════════════════════════════════════════════
// ROOM INFO CARD — pricing breakdown display
// ═══════════════════════════════════════════════════════════════════════════════

// Interval ID cho rd-ri-card live refresh
let _rdRiInterval = null;
let _rdRiStayId = null;
let _rdRiPending = false;

async function rdRenderRoomInfoCard(options = {}) {
    const sessionAtStart = _rdSessionId;
    const stayId = document.getElementById('rd-stay-id')?.value;
    if (!stayId) return;

    const heroStd = document.getElementById('rd-ri-std-label');
    const typeBadge = document.getElementById('rd-ri-type-badge');
    const ciEl = document.getElementById('rd-ri-ci');
    const coEl = document.getElementById('rd-ri-co');
    const depEl = document.getElementById('rd-ri-deposit');
    const rowsEl = document.getElementById('rd-ri-bd-rows');

    // Quick stats always update from DOM
    const ciVal = document.getElementById('rd-ci')?.value;
    const coVal = document.getElementById('rd-co-est')?.value;
    const depAmt = parseFloat((document.getElementById('rd-deposit')?.value || '0').replace(/[.,\s]/g, '')) || 0;
    const hasCo = !!(coVal);
    const isRealtime = !hasCo;

    if (ciEl) ciEl.textContent = ciVal ? pmsFormatDateTimeVN(ciVal) : '—';
    if (coEl) {
        coEl.textContent = hasCo
            ? pmsFormatDateTimeVN(coVal)
            : '—';
        coEl.className = `rd-ri-stat-val ${hasCo ? 'amber' : ''}`;
    }
    // Detect overdue ngay khi render lần đầu
    _updateCoOverdueStatus(null);
    if (depEl) depEl.textContent = pmsMoney(depAmt);

    // LIVE badge hoặc static label
    if (heroStd) {
        if (rdIsOtaManualStay()) {
            heroStd.innerHTML = `OTA`;
        } else {
            heroStd.innerHTML = `<span class="rd-live-dot"></span> LIVE`;
        }
    }

    // Bind co-est listener (hourly stays recalculate when user changes checkout time)
    if (!rdIsCheckedOut) {
        _rdRiBindCoEstListener();
    }

    const baseRenderKey = rdGetRoomInfoRenderKey(stayId);

    // Skeleton while fetching
    if (rowsEl && (options.forceSkeleton || rdRoomInfoSkeletonKey !== baseRenderKey || !rowsEl.children.length)) {
        rowsEl.innerHTML = _rdRiSkeleton();
        rdRoomInfoSkeletonKey = baseRenderKey;
    }

    // Tránh gọi overlapping
    if (_rdRiPending && _rdRiStayId === stayId && !options.force) return;
    _rdRiPending = true;
    _rdRiStayId = stayId;

    try {
        let data;
        let breakdown = [];

        if (rdIsCheckedOut && rdCurrentFolio) {
            // Checked-out stays: ưu tiên dùng rdPaymentState (từ /preview-checked-out)
            // vì nó tính trực tiếp từ FolioTransaction (source of truth).
            // folio.balance / folio.total_charge có thể STALE (ví dụ folio.total_charge = 0
            // nếu rebalance_folio chưa chạy đúng lúc checkout).
            const ps = rdPaymentState || {};

            // Lấy dữ liệu từ rdPaymentState (chính xác) → fallback folio cache
            const totalCharge = ps.room_charge ?? ps.total_charge ?? rdCurrentFolio.total_charge ?? 0;
            const effPaidNum = parseFloat(ps.effective_paid ?? rdCurrentFolio.total_paid ?? 0);
            const depUsed = parseFloat(ps.deposit_used ?? 0);
            const paidForDisplay = effPaidNum + depUsed;

            // Phân tách breakdown từ transactions trong folio
            const txs = rdCurrentFolio.transactions || [];
            const roomItems = [];
            const serviceItems = [];
            const surchargeItems = [];
            const discountItems = [];
            const discountTotal = txs
                .filter(tx => !tx.is_voided && tx.category === 'DISCOUNT')
                .reduce((sum, tx) => sum + Math.abs(parseFloat(tx.amount) || 0), 0)
                || Math.abs(rdNum(ps.total_discounts || ps.existing_discounts || ps.discount));
            txs.forEach(tx => {
                if (tx.is_voided) return;
                const amt = parseFloat(tx.amount) || 0;
                if (amt <= 0) return; // bỏ payment/refund/deposit_used
                // Bỏ qua REFUND / REFUND_PAYMENT (không phải charge thực)
                const txType = tx.transaction_type || tx.type || '';
                if (txType === 'REFUND' || txType === 'REFUND_PAYMENT') return;
                if (tx.category === 'ROOM' || txType === 'ROOM_CHARGE' || txType === 'HOURLY_CHARGE') {
                    roomItems.push({ type: txType || 'ROOM_CHARGE', description: tx.description, amount: amt });
                } else if (tx.category === 'SERVICE') {
                    serviceItems.push({ type: 'SERVICE', description: tx.description, amount: amt });
                } else if (tx.category === 'SURCHARGE' || tx.category === 'OTHER') {
                    surchargeItems.push({ type: 'SURCHARGE', description: tx.description, amount: amt });
                } else if (tx.category === 'DISCOUNT') {
                    discountItems.push({ type: 'DISCOUNT', description: tx.description, amount: amt });
                }
            });

            breakdown = [...roomItems, ...serviceItems, ...surchargeItems];

            // Tính room_charge từ transactions nếu có, fallback totalCharge
            const roomChargeFromTx = roomItems.reduce((s, i) => s + i.amount, 0);
            const displayTotalCharge = roomChargeFromTx > 0
                ? roomChargeFromTx + serviceItems.reduce((s, i) => s + i.amount, 0) + surchargeItems.reduce((s, i) => s + i.amount, 0)
                : parseFloat(totalCharge) || 0;

            data = {
                room_charge: roomChargeFromTx || parseFloat(totalCharge) || 0,
                existing_charges: 0,
                existing_service_charges: serviceItems.reduce((s, i) => s + i.amount, 0),
                existing_surcharge_charges: surchargeItems.reduce((s, i) => s + i.amount, 0),
                existing_discount: discountTotal,
                effective_paid: effPaidNum,
                deposit_used: depUsed,
                projected_balance: displayTotalCharge - discountTotal - paidForDisplay,
                mode: rdStayData?.stay_type || '',
            };

            // Đã thu = effective_paid + deposit_used
            const depEl2 = document.getElementById('rd-ri-deposit');
            if (depEl2) depEl2.textContent = pmsMoney(paidForDisplay);
            // Tổng = total charge thực tế (từ transactions hoặc API)
            const heroAmount = document.getElementById('rd-ri-hero-amount');
            if (heroAmount) heroAmount.textContent = pmsMoney(displayTotalCharge);
            const subEl = document.getElementById('rd-ri-subtotal');
            if (subEl) subEl.textContent = pmsMoney(displayTotalCharge);
            // Badge: "ĐÃ CHECKOUT" thay vì LIVE
            if (heroStd) {
                if (rdIsOtaManualStay()) {
                    heroStd.innerHTML = `OTA`;
                } else {
                    heroStd.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> ĐÃ TRẢ`;
                }
            }
            if (typeBadge) typeBadge.style.display = 'none';

            // Balance info
            const needDiv = document.getElementById('rd-ri-need');
            const needAmount = document.getElementById('rd-ri-need-amount');
            const excessDiv = document.getElementById('rd-ri-excess-row');
            const excessAmount = document.getElementById('rd-ri-excess-amount');
            const displayBalance = displayTotalCharge - discountTotal - paidForDisplay;

            if (displayBalance > 0.5) {
                if (needDiv) needDiv.style.opacity = '1';
                if (needAmount) needAmount.textContent = pmsMoney(displayBalance);
                if (excessDiv) excessDiv.style.opacity = '0';
            } else if (displayBalance < -0.5) {
                if (excessDiv) excessDiv.style.opacity = '1';
                if (excessAmount) excessAmount.textContent = pmsMoney(Math.abs(displayBalance));
                if (needDiv) needDiv.style.opacity = '0';
            } else {
                if (needDiv) needDiv.style.opacity = '0';
                if (excessDiv) excessDiv.style.opacity = '0';
            }

            if (rowsEl) {
                _renderRiRows(breakdown, rowsEl, displayTotalCharge);
                rdRenderOtaPricingNotice(rowsEl, rdGetOtaPricingInfo());
            }

            _rdRiPending = false;
            return;
        }

        // Active stays: dùng pricing preview bình thường
        data = await pmsApi(`/api/pms/stays/${stayId}/pricing-preview`, { method: 'GET' });

        // ── SESSION CHECK: bỏ qua nếu đã chuyển phòng ──
        if (sessionAtStart !== _rdSessionId) { _rdRiPending = false; return; }

        const mode = data?.mode || '';
        const isHourly = mode === 'HOURLY' || mode === 'FORCE_HOURLY';
        const isDaily = mode === 'DAY_USE' || mode === 'FORCE_DAILY';
        const isOvernight = mode === 'FORCE_OVERNIGHT';
        breakdown = data?.breakdown || [];
        const total = data?.total || 0;
        const projectedBal = data?.projected_balance;
        if (rdIsOtaManualStay()) {
            rdPaymentState = {
                ...(rdPaymentState || {}),
                ...data,
                folios: rdCurrentFolios,
            };
        }

        // Hero amount = room_charge + existing folio charges (services/surcharges)
        const heroAmt = (data?.room_charge || 0) + (data?.existing_charges || 0);
        const otaInfo = rdGetOtaPricingInfo();

        // Update hero amount & badge
        const heroAmount = document.getElementById('rd-ri-hero-amount');
        if (heroAmount) heroAmount.textContent = pmsMoney(heroAmt);
        if (typeBadge) {
            if (otaInfo) {
                typeBadge.textContent = 'OTA • Giá thực thu';
                typeBadge.className = 'rd-ri-type-badge night';
                typeBadge.style.display = 'inline-block';
            } else {
                let labelType = 'Qua đêm';
                if (isHourly) labelType = 'Thuê giờ';
                else if (isDaily) labelType = 'Thuê ngày';
                else if (isOvernight) labelType = 'Qua đêm (Ép)';

                typeBadge.textContent = labelType;
                typeBadge.className = `rd-ri-type-badge ${isHourly ? 'hour' : 'night'}`;
            }
        }

        // Giá tạm tính = total charge (room + existing charges)
        const subEl = document.getElementById('rd-ri-subtotal');
        if (subEl) subEl.textContent = pmsMoney(heroAmt);

        // Đã thu = effective_paid
        const depEl = document.getElementById('rd-ri-deposit');
        if (depEl) depEl.textContent = pmsMoney(data?.effective_paid || 0);

        // Update "Cần thu" / "Khách dư" row
        const needRow = document.getElementById('rd-ri-need-row');
        const needDiv = document.getElementById('rd-ri-need');
        const needAmount = document.getElementById('rd-ri-need-amount');
        const excessDiv = document.getElementById('rd-ri-excess-row');
        const excessAmount = document.getElementById('rd-ri-excess-amount');

        if (projectedBal !== undefined && projectedBal !== null) {
            if (projectedBal > 0) {
                // Cần thu thêm
                if (needDiv) needDiv.style.opacity = '1';
                if (needAmount) needAmount.textContent = pmsMoney(projectedBal);
                if (excessDiv) excessDiv.style.opacity = '0';
            } else if (projectedBal < 0) {
                // Khách dư
                if (excessDiv) excessDiv.style.opacity = '1';
                if (excessAmount) excessAmount.textContent = pmsMoney(Math.abs(projectedBal));
                if (needDiv) needDiv.style.opacity = '0';
            } else {
                // Đã tất toán
                if (needDiv) needDiv.style.opacity = '0';
                if (excessDiv) excessDiv.style.opacity = '0';
            }
        } else {
            if (needDiv) needDiv.style.opacity = '0';
            if (excessDiv) excessDiv.style.opacity = '0';
        }

        // Show breakdown rows with separate SERVICE and SURCHARGE lines
        if (rowsEl) {
            const breakdownWithExtras = [...breakdown];
            const ecSvc = data?.existing_service_charges || 0;
            const ecSur = data?.existing_surcharge_charges || 0;
            if (ecSvc > 0) {
                breakdownWithExtras.push({ type: 'SERVICE', label: 'Chi phí dịch vụ', amount: ecSvc });
            }
            if (ecSur > 0) {
                breakdownWithExtras.push({ type: 'SURCHARGE', label: 'Chi phí phát sinh', amount: ecSur });
            }
            _renderRiRows(breakdownWithExtras, rowsEl, heroAmt);
            rdRenderOtaPricingNotice(rowsEl, otaInfo);
        }

        // For hourly: show live end time if API returned it
        if (isHourly && data?.end_time) {
            const liveCo = document.getElementById('rd-ri-live-co');
            if (liveCo) {
                liveCo.textContent = pmsFormatDateTimeVN(data.end_time);
                liveCo.style.display = '';
            }
        } else {
            const liveCo = document.getElementById('rd-ri-live-co');
            if (liveCo) liveCo.style.display = 'none';
        }

        if (rdIsOtaManualStay() && rdCurrentFolio && data) {
            rdPaymentState = {
                ...(rdPaymentState || {}),
                ...data,
                folios: rdCurrentFolios,
            };
        }
        _scheduleRiRefresh(stayId, isRealtime);
    } catch {
        if (rowsEl) rowsEl.innerHTML = `<div style="padding:12px 18px; color:#94a3b8; font-size:12px;">Không tải được giá</div>`;
        const heroAmount = document.getElementById('rd-ri-hero-amount');
        if (heroAmount) heroAmount.textContent = '—';
    } finally {
        _rdRiPending = false;
    }
}

function pmsRdOpenBreakdown() {
    const modal = document.getElementById('rd-sub-modal-breakdown');
    const rowsEl = document.getElementById('rd-ri-bd-rows');
    if (rowsEl) {
        _renderRiRows(rdLastBreakdownRows, rowsEl, rdLastBreakdownTotal);
        rdRenderOtaPricingNotice(rowsEl, rdGetOtaPricingInfo());
    }
    if (modal) modal.style.display = 'flex';
}

function _renderRiRows(breakdown, rowsEl, totalAmount) {
    if (!rowsEl) return;
    rdLastBreakdownRows = Array.isArray(breakdown) ? breakdown : [];
    rdLastBreakdownTotal = totalAmount || 0;
    const renderKey = rdGetRoomInfoRenderKey(rdStayData?.id, {
        total: totalAmount || 0,
        room_charge: rdLastBreakdownRows.reduce((acc, item) => acc + rdNum(item?.amount), 0),
        existing_charges: rdLastBreakdownRows.length,
        projected_balance: rdPaymentState?.projected_balance ?? '',
    });
    const modalTotal = document.getElementById('rd-bd-modal-total');
    if (modalTotal) modalTotal.textContent = pmsMoney(totalAmount || 0);
    if (rdRoomInfoRenderKey === renderKey && rowsEl.children.length) return;
    rdRoomInfoRenderKey = renderKey;
    if (!breakdown || breakdown.length === 0) {
        rowsEl.innerHTML = `<div style="padding:40px; text-align:center; font-size:13px; color:var(--rd-text-muted); font-weight:700; opacity:0.6;">Chưa có chi tiết giá</div>`;
        return;
    }

    const iconMap = {
        EARLY_CHECKIN_FEE: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
        LATE_CHECKOUT_FEE:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
        HOURLY_CHARGE:     `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
        ROOM_CHARGE:       `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
        SERVICE:           `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`,
        SURCHARGE:         `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>`,
    };

    rowsEl.innerHTML = breakdown.map(item => {
        const type = item.type || '';
        const icon = iconMap[type] || iconMap.ROOM_CHARGE;
        let label = item.description || type;
        // Clean label: remove parts in parentheses (e.g., " (1 đêm)")
        label = label.replace(/\s*\(.*?\)/g, '').trim();

        const amount = item.amount;
        const start = item.start_iso || item.start_at || item.start || item.from_iso || item.from;
        const end = item.end_iso || item.end_at || item.end || item.to_iso || item.to;
        const durationArr = _rdRiFmtDur(item);

        return `
        <div class="rd-ri-bd-row" style="
            background: var(--rd-bg-primary);
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
        " onmouseover="this.style.borderColor='var(--rd-bg-secondary)'; this.style.transform='translateY(-1px)';" 
          onmouseout="this.style.borderColor='transparent'; this.style.transform='none';">
            
            <!-- Column 1: Type -->
            <div style="display:flex; align-items:center; gap:12px; min-width:0;">
                <div style="width:36px; height:36px; background:white; border-radius:12px; color:var(--rd-accent-soft); display:flex; align-items:center; justify-content:center; flex-shrink:0; box-shadow: 0 4px 12px rgba(0,0,0,0.04);">
                    ${icon}
                </div>
                <div style="font-weight:850; font-size: 13px; color:var(--rd-accent-bold); line-height:1.2; white-space:nowrap;" title="${pmsEscapeHtml(label)}">
                    ${pmsEscapeHtml(label)}
                </div>
            </div>

            <!-- Column 2: Period -->
            <div style="min-width:0;">
                ${start && end ? `
                <div style="display:flex; flex-direction:column; gap:2px;">
                    <div style="font-weight:700; color:var(--rd-accent-bold); font-size:13px; font-family:'Outfit', sans-serif;">
                        ${_rdRiFmtTimeOnly(start)} <span style="opacity:0.4; margin:0 4px;">→</span> ${_rdRiFmtTimeOnly(end)}
                    </div>
                    <div style="font-size:10px; color:var(--rd-text-muted); font-weight:700;">
                        ${_rdRiFmtDateOnly(start)}
                    </div>
                </div>
                ` : `<span style="color:var(--rd-text-muted); font-size:12px; font-weight:600;">—</span>`}
            </div>

            <!-- Column 3: Duration -->
            <div style="text-align:right;">
                <div style="font-size:13px; font-weight:850; color:var(--rd-accent-bold);">${durationArr[0]}</div>
                <div style="font-size:10px; font-weight:700; color:var(--rd-text-muted);">${durationArr[1] || ''}</div>
            </div>

            <!-- Column 4: Amount -->
            <div style="text-align:right;">
                <div style="font-family:'Outfit', sans-serif; font-weight:900; font-size:16px; color:var(--rd-accent-soft); white-space:nowrap;">
                    ${pmsMoney(amount)}
                </div>
            </div>
        </div>`;
    }).join('');
}

function _rdRiFmtTimeOnly(iso) {
    const d = pmsParseDate(iso);
    if (!d || isNaN(d.getTime())) return '??:??';
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

function _rdRiFmtDateOnly(iso) {
    const d = pmsParseDate(iso);
    if (!d || isNaN(d.getTime())) return '';
    const DD = String(d.getDate()).padStart(2, '0');
    const MM = String(d.getMonth() + 1).padStart(2, '0');
    const YYYY = d.getFullYear();
    const weekdays = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];
    return `${weekdays[d.getDay()]}, ${DD}/${MM}/${YYYY}`;
}

function _rdRiFmtDur(item) {
    let h = item.hours || item.duration_hours;
    const start = item.start_iso || item.start_at || item.start || item.from_iso || item.from;
    const end = item.end_iso || item.end_at || item.end || item.to_iso || item.to;
    if (!h && start && end) {
        const s = pmsParseDate(start);
        const e = pmsParseDate(end);
        if (s && e && !Number.isNaN(s.getTime()) && !Number.isNaN(e.getTime())) {
            h = Math.max(0, (e - s) / 3600000);
        }
    }
    if (!h) return ['—', ''];
    
    // Nếu là tiền phòng theo đêm
    if (item.type === 'ROOM_CHARGE' && h >= 12) {
        const days = Math.round(h / 24) || 1;
        return [`${days} ngày`, item.hours ? `${item.hours} giờ` : ''];
    }
    
    // Nếu là tiền giờ hoặc phụ phí
    const hh = Math.floor(h);
    const mm = Math.round((h - hh) * 60);
    if (mm === 0) return [`${hh} giờ`, ''];
    return [`${hh}g ${mm}p`, ''];
}

function _rdRiFmtRange(startIso, endIso) {
    if (!startIso || !endIso) return '—';
    return `${_rdRiFmtTimeOnly(startIso)} → ${_rdRiFmtTimeOnly(endIso)}`;
}

function _rdRiSkeleton() {
    return [0,1,2].map(() =>
        `<div class="rd-ri-bd-row">
            <div style="display:flex; align-items:center; gap:8px; flex:1;">
                <div style="width:7px;height:7px;border-radius:50%;background:#e2e8f0;"></div>
                <div>
                    <div class="rd-ri-skel" style="width:110px;height:13px;margin-bottom:4px;"></div>
                    <div class="rd-ri-skel" style="width:70px;height:10px;"></div>
                </div>
            </div>
            <div class="rd-ri-skel" style="width:60px;height:14px;"></div>
        </div>`
    ).join('');
}

function _updateCoOverdueStatus(data) {
    const card = document.getElementById('rd-ri-co-card');
    const coNowEl = document.getElementById('rd-ri-co-now');
    if (!card || !coNowEl) return;

    const coVal = document.getElementById('rd-co-est')?.value;
    let coDate = coVal ? new Date(coVal) : null;
    if (!coDate && data?.end_time) {
        coDate = new Date(data.end_time);
    }
    if (!coDate) {
        card.classList.remove('overdue');
        coNowEl.style.display = 'none';
        return;
    }

    const now = new Date();
    const isOverdue = rdIsCheckedOut ? false : coDate < now;

    if (isOverdue) {
        card.classList.add('overdue');
        coNowEl.style.display = '';
        coNowEl.textContent = `Hiện tại: ${pmsFormatDateTimeVN(now.toISOString())}`;
    } else {
        card.classList.remove('overdue');
        coNowEl.style.display = 'none';
    }
}

function _scheduleRiRefresh(stayId, isRealtime) {
    if (_rdRiInterval) {
        clearInterval(_rdRiInterval);
        _rdRiInterval = null;
    }
    if (!isRealtime) return; // Chỉ live refresh cho active stays

    _rdRiInterval = setInterval(async () => {
        const modal = document.getElementById('rdModal');
        const tab = document.getElementById('rd-tab-room');
        if (!modal || modal.style.display === 'none' || !tab || tab.style.display === 'none') {
            clearInterval(_rdRiInterval);
            _rdRiInterval = null;
            return;
        }
        const currentId = document.getElementById('rd-stay-id')?.value;
        if (!currentId || currentId !== stayId) {
            clearInterval(_rdRiInterval);
            _rdRiInterval = null;
            return;
        }
        try {
            const data = await pmsApi(`/api/pms/stays/${stayId}/pricing-preview`, { method: 'GET' });
            const rowsEl = document.getElementById('rd-ri-bd-rows');
            const typeBadge = document.getElementById('rd-ri-type-badge');
            const heroAmount = document.getElementById('rd-ri-hero-amount');
            const subEl = document.getElementById('rd-ri-subtotal');
            const depEl = document.getElementById('rd-ri-deposit');
            const mode = data?.mode || '';
            const isHourly = mode === 'HOURLY' || mode === 'FORCE_HOURLY';
            const isDaily = mode === 'DAY_USE' || mode === 'FORCE_DAILY';
            const isOvernight = mode === 'FORCE_OVERNIGHT';
            const total = data?.total || 0;
            const heroAmt = (data?.room_charge || 0) + (data?.existing_charges || 0);
            if (rdIsOtaManualStay()) {
                rdPaymentState = {
                    ...(rdPaymentState || {}),
                    ...data,
                    folios: rdCurrentFolios,
                };
            }
            const otaInfo = rdGetOtaPricingInfo();

            if (heroAmount) heroAmount.textContent = pmsMoney(heroAmt);
            if (subEl) subEl.textContent = pmsMoney(heroAmt);
            if (depEl) depEl.textContent = pmsMoney(data?.effective_paid || 0);
            if (typeBadge) {
                if (otaInfo) {
                    typeBadge.textContent = 'OTA • Giá thực thu';
                    typeBadge.className = 'rd-ri-type-badge night';
                    typeBadge.style.display = 'inline-block';
                } else {
                    let labelType = 'Qua đêm';
                    if (isHourly) labelType = 'Thuê giờ';
                    else if (isDaily) labelType = 'Thuê ngày';
                    else if (isOvernight) labelType = 'Qua đêm (Ép)';

                    typeBadge.textContent = labelType;
                    typeBadge.className = `rd-ri-type-badge ${isHourly ? 'hour' : 'night'}`;
                }
            }

            // ── Trả dự kiến: detect overdue ──
            _updateCoOverdueStatus(data);

            if (rowsEl) {
                const ecSvc = data?.existing_service_charges || 0;
                const ecSur = data?.existing_surcharge_charges || 0;
                const extras = [...(data?.breakdown || [])];
                if (ecSvc > 0) extras.push({ type: 'SERVICE', label: 'Chi phí dịch vụ', amount: ecSvc });
                if (ecSur > 0) extras.push({ type: 'SURCHARGE', label: 'Chi phí phát sinh', amount: ecSur });
                _renderRiRows(extras, rowsEl, heroAmt);
                rdRenderOtaPricingNotice(rowsEl, otaInfo);
            }

            // Update "Cần thu" row
            const projectedBal = data?.projected_balance;
            const needDiv = document.getElementById('rd-ri-need');
            const needAmount = document.getElementById('rd-ri-need-amount');
            const excessDiv = document.getElementById('rd-ri-excess-row');
            const excessAmount = document.getElementById('rd-ri-excess-amount');
            if (projectedBal !== undefined && projectedBal !== null) {
                if (projectedBal > 0) {
                    if (needDiv) needDiv.style.opacity = '1';
                    if (needAmount) needAmount.textContent = pmsMoney(projectedBal);
                    if (excessDiv) excessDiv.style.opacity = '0';
                } else if (projectedBal < 0) {
                    if (excessDiv) excessDiv.style.opacity = '1';
                    if (excessAmount) excessAmount.textContent = pmsMoney(Math.abs(projectedBal));
                    if (needDiv) needDiv.style.opacity = '0';
                } else {
                    if (needDiv) needDiv.style.opacity = '0';
                    if (excessDiv) excessDiv.style.opacity = '0';
                }
            }
        } catch { /* silent */ }
    }, 60000); // 60 giây
}

function pmsRdOpenExtension() {
    if (rdIsCheckedOut) {
        pmsToast('Phòng đã trả. Không thể gia hạn.', false);
        return;
    }
    const elDate = document.getElementById('rd-sm-ext-date');
    const elTime = document.getElementById('rd-sm-ext-time');
    if (elDate && elTime) {
        const coString = rdNormalizeDateTimeLocal(document.getElementById('rd-co-est')?.value) || rdNowDateTimeLocalVN();
        elDate.value = coString.split('T')[0];
        elTime.value = "12:00"; // Default to 12:00 for user convenience

        // Show current checkout time as reference
        const elCurrent = document.getElementById('rd-sm-ext-current');
        if (elCurrent) {
            elCurrent.textContent = rdFormatDateTimeLocalVN(coString);
        }
    }
    rdUpdateExtPreview();
    document.getElementById('rd-sub-modal-extension').style.display = 'flex';
}
function rdUpdateExtPreview() {
    const dateVal = document.getElementById('rd-sm-ext-date').value;
    const timeVal = document.getElementById('rd-sm-ext-time').value;
    const preview = document.getElementById('rd-sm-ext-preview');
    if (!dateVal || !timeVal) {
        preview.textContent = '---';
        return;
    }
    preview.textContent = rdFormatDateTimeLocalVN(rdBuildDateTimeLocalVN(dateVal, timeVal));
}
function rdQuickExt(hours) {
    const elDate = document.getElementById('rd-sm-ext-date');
    const elTime = document.getElementById('rd-sm-ext-time');
    if (!elDate.value || !elTime.value) return;

    const dt = rdDateTimeLocalVNToDate(rdBuildDateTimeLocalVN(elDate.value, elTime.value));
    if (!dt) return;
    dt.setTime(dt.getTime() + (hours * 60 * 60 * 1000));

    const nextLocal = rdNormalizeDateTimeLocal(dt);
    elDate.value = nextLocal.slice(0, 10);
    elTime.value = nextLocal.slice(11, 16);
    rdUpdateExtPreview();
}
async function pmsRdSaveExtension() {
    const date = document.getElementById('rd-sm-ext-date').value;
    const time = document.getElementById('rd-sm-ext-time').value;
    if (!date || !time) return pmsToast('Vui lòng chọn thời gian', false);

    const newCo = rdBuildDateTimeLocalVN(date, time);
    const coInp = document.getElementById('rd-co-est');
    const previousCo = coInp?.value || '';
    if (coInp) {
        coInp.value = newCo;
        coInp.dispatchEvent(new Event('input', { bubbles: true }));
    }

    // Auto-save to backend
    const saved = await pmsRdUpdateStay();
    if (!saved) {
        if (coInp) {
            coInp.value = previousCo;
            coInp.dispatchEvent(new Event('input', { bubbles: true }));
        }
        return;
    }

    document.getElementById('rd-sub-modal-extension').style.display = 'none';
}
const pmsSurchargeData = {
    'DAMAGE': [
        { name: 'Làm hỏng cốc', price: 30000 },
        { name: 'Làm hỏng khăn tắm', price: 50000 },
        { name: 'Làm hỏng ga giường', price: 200000 },
        { name: 'Mất chìa khoá', price: 200000 },
        { name: 'Làm hỏng điều khiển', price: 150000 },
    ],
    'GUESTS': [
        { name: 'Thêm 1 người lớn', price: 150000 },
        { name: 'Thêm 1 trẻ em', price: 100000 },
        { name: 'Ngủ ghép', price: 200000 },
    ],
    'OTHER': [
        { name: 'Dọn phòng gấp', price: 50000 },
        { name: 'Giặt mền/chăn', price: 70000 },
        { name: 'Phí ship hàng', price: 20000 },
    ]
};

function pmsRdOpenSurcharge() {
    // Refresh modal state
    rdTempSurcharges = [];
    const elContent = document.getElementById('rd-sm-sur-content');
    const elAmount = document.getElementById('rd-sm-sur-amount');
    if (elContent) elContent.value = '';
    if (elAmount) elAmount.value = '0';
    
    pmsRdRenderTempSurcharge();
    document.getElementById('rd-sub-modal-surcharge').style.display = 'flex';
    
    // Auto-select first cat (DAMAGE)
    const firstCat = document.querySelector('#rd-sm-sur-cats .rd-sm-cat-item');
    if (firstCat) {
        pmsRdSwitchSurCat(firstCat, 'DAMAGE');
    }
}

function pmsRdSwitchSurCat(el, catId) {
    document.querySelectorAll('#rd-sm-sur-cats .rd-sm-cat-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    
    const grid = document.getElementById('rd-sm-sur-item-grid');
    if (!grid) return;
    
    const items = pmsSurchargeData[catId] || [];
    grid.innerHTML = items.map(item => `
      <div class="rd-sm-chip" onclick="pmsRdQuickSelectSurcharge('${item.name}', ${item.price})" 
           style="padding: 16px; height: auto; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; text-align: center; background: var(--rd-bg-primary); border-color: transparent;">
        <div style="font-weight: 850; font-size: 13px; color: var(--rd-accent-bold);">${item.name}</div>
        <div style="font-size: 11px; color: var(--rd-accent-soft); font-weight: 700; font-family: 'Outfit', sans-serif;">${item.price.toLocaleString()}đ</div>
      </div>
    `).join('');
}

function pmsRdQuickSelectSurcharge(name, price) {
    const elContent = document.getElementById('rd-sm-sur-content');
    const elAmount = document.getElementById('rd-sm-sur-amount');
    
    if (elContent) elContent.value = name;
    if (elAmount) {
        elAmount.value = price;
        // Check formatting hook
        if (typeof pmsFormatCurrency === 'function') {
            pmsFormatCurrency(elAmount);
        }
    }
}
function pmsRdAddTempSurcharge() {
    const note = document.getElementById('rd-sm-sur-content').value;
    const amtStr = document.getElementById('rd-sm-sur-amount').value.replace(/\D/g, '');
    const amount = parseInt(amtStr || '0');

    if (!note || amount <= 0) return pmsToast('Thông tin phát sinh không hợp lệ', false);

    rdTempSurcharges.push({ note, amount });
    pmsRdRenderTempSurcharge();
    document.getElementById('rd-sm-sur-content').value = '';
    document.getElementById('rd-sm-sur-amount').value = '0';
}
function pmsRdRenderTempSurcharge() {
    const list = document.getElementById('rd-sm-sur-bill-list');
    if (!list) return;
    let total = 0;
    if (rdTempSurcharges.length === 0) {
        list.innerHTML = `<div class="rd-sv-empty" style="display:flex; flex-direction:column; align-items:center; justify-content:center; flex:1; min-height:200px; color:var(--rd-text-muted); opacity:0.6; width:100%;">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:16px;">
          <rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>
        </svg>
        <p style="margin:0; font-size:14px; font-weight:700;">Trống</p>
      </div>`;
    } else {
        list.innerHTML = rdTempSurcharges.map((s, i) => {
            total += s.amount;
            return `
        <div class="rd-sm-bill-item" style="border-left: 4px solid var(--rd-accent-soft); padding: 16px;">
          <div style="flex:1;">
            <div style="font-weight:850; color:var(--rd-accent-bold); font-size:13px;">${pmsEscapeHtml(s.note)}</div>
            <div style="font-size:10px; color:var(--rd-text-muted); font-weight:700; margin-top:2px;">Ghi vào phiếu tạm</div>
          </div>
          <div style="text-align:right;">
             <div style="font-weight:850; color:var(--rd-accent-bold); font-family:'Outfit', sans-serif; font-size:15px;">${s.amount.toLocaleString()}</div>
             <span style="color:#ef4444; cursor:pointer; font-size:10px; font-weight:850; text-transform:uppercase; letter-spacing:0.05em;" onclick="pmsRdRemoveTempSurcharge(${i})">Gỡ bỏ</span>
          </div>
        </div>
      `;
        }).join('');
    }
    document.getElementById('rd-sm-sur-total').textContent = total.toLocaleString();
}
function pmsRdRemoveTempSurcharge(i) {
    rdTempSurcharges.splice(i, 1);
    pmsRdRenderTempSurcharge();
}
let _invProducts = [];
let _invCategories = [];
let _invActiveCat = null;
let _invCacheKey = null;
let _invLoadPromise = null;

function _invGetBranchId() {
    if (window.isCiMode) {
        return window._pmsCiBranchId
            || (typeof pmsCi !== 'undefined' && pmsCi ? pmsCi.branch_id : null)
            || (window.PMS ? window.PMS.branchId : null)
            || '';
    }
    if (typeof rdStayData !== 'undefined' && rdStayData && rdStayData.branch_id) return rdStayData.branch_id;
    return '';
}

async function pmsRdOpenService() {
    rdTempServices = [];
    const searchInp = document.querySelector('#rd-sub-modal-service .rd-sv-search-input');
    if (searchInp) searchInp.value = '';
    pmsRdRenderTempService();
    document.getElementById('rd-sub-modal-service').style.display = 'flex';

    const list = document.getElementById('rd-sm-sv-list');
    const cats = document.getElementById('rd-sm-sv-cats');
    const branchId = _invGetBranchId();
    const cacheKey = `branch:${branchId || 'default'}`;
    const hasValidCache = _invCacheKey === cacheKey && _invProducts.length > 0;

    if (hasValidCache) {
        _invRenderCatSidebar();
        pmsRdRenderServiceList();
        return;
    }

    _invProducts = [];
    _invCategories = [];
    _invActiveCat = null;
    _invCacheKey = cacheKey;
    if (cats) cats.innerHTML = '';
    if (list) {
        list.className = 'rd-sv-grid rd-sv-empty-state';
        list.innerHTML = `<div class="rd-sv-loading">Đang tải sản phẩm...</div>`;
    }

    if (!_invLoadPromise || _invLoadPromise.cacheKey !== cacheKey) {
        const branchIdQ = branchId ? `?branch_id=${encodeURIComponent(branchId)}` : '';
        _invLoadPromise = pmsApi('/api/pms/inventory/products' + branchIdQ);
        _invLoadPromise.cacheKey = cacheKey;
    }

    try {
        const data = await _invLoadPromise;
        if (_invCacheKey !== cacheKey) return;
        _invProducts = data.products || [];
        _invCategories = data.categories || [];
        _invActiveCat = _invCategories.length > 0 ? _invCategories[0].name : 'All';
        _invRenderCatSidebar();
        pmsRdRenderServiceList();
    } catch (e) {
        if (_invCacheKey === cacheKey && list) {
            list.innerHTML = `<div class="rd-sv-error">Lỗi tải sản phẩm: ${e.message}<br><small>Hãy kiểm tra kho chi nhánh đã được thiết lập</small></div>`;
        }
    } finally {
        if (_invLoadPromise && _invLoadPromise.cacheKey === cacheKey) _invLoadPromise = null;
    }
}

function _invRenderCatSidebar() {
    const container = document.getElementById('rd-sm-sv-cats');
    if (!container || _invCategories.length === 0) return;
    container.innerHTML = _invCategories.map((c, i) =>
        `<div class="rd-sm-cat-item ${c.name === _invActiveCat ? 'active' : ''}" onclick="window.pmsRdSwitchSvCat(this)" data-cat="${c.name}">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>
            ${c.name}
        </div>`
    ).join('');
}

function pmsRdRenderServiceList(filter = '', cat = null) {
    const list = document.getElementById('rd-sm-sv-list');
    if (!list) return;
    if (cat) _invActiveCat = cat;
    const activeCat = _invActiveCat || 'All';

    let filtered = _invProducts;
    if (activeCat !== 'All') {
        filtered = filtered.filter(s => {
            const cname = (s.category_name || '').toLowerCase();
            const fCat = activeCat.toLowerCase();
            return cname === fCat || cname.includes(fCat) || fCat.includes(cname) ||
                   (fCat === 'đồ uống' && (cname.includes('nước') || cname.includes('giải khát')));
        });
    }
    if (filter) filtered = filtered.filter(s => s.name.toLowerCase().includes(filter.toLowerCase()));

    if (filtered.length === 0) {
        list.className = 'rd-sv-grid rd-sv-empty-state';
        const noProductsAtAll = _invProducts.length === 0;
        list.innerHTML = `<div class="rd-sv-empty">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <p>${noProductsAtAll ? 'Chưa có sản phẩm nào được bật bán tại PMS' : 'Không tìm thấy sản phẩm'}</p>
            ${noProductsAtAll ? '<small style="opacity:0.7">Vào Kho → Danh mục sản phẩm → bật toggle "Bán tại PMS" cho sản phẩm muốn bán</small>' : ''}
        </div>`;
    } else {
        list.className = 'rd-sv-grid';
        list.innerHTML = filtered.map((s, idx) => {
            const tempItem = rdTempServices.find(temp => temp.product_id === s.id);
            const currentStock = tempItem ? s.stock - tempItem.qty : s.stock;
            const outOfStock = currentStock <= 0;
            const isLow = currentStock <= (s.min_stock || 0);
            const stockClass = outOfStock ? 'out' : (isLow ? 'low' : 'ok');
            const safeName = s.name.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            return `
                <div class="rd-sv-card ${outOfStock ? 'disabled' : ''}">
                    <span class="rd-sv-stock ${stockClass}">${outOfStock ? 'Hết' : Math.floor(currentStock) + ' ' + (s.base_unit || 'Cái')}</span>
                    <div class="rd-sv-card-name" title="${s.name}">${s.name}</div>
                    <div class="rd-sv-card-price">${(s.sell_price || 0).toLocaleString()}<small>đ</small></div>
                    <div class="rd-sv-card-actions">
                        <div class="rd-sm-pm-field">
                            <button class="rd-sm-pm-btn" onclick="window.rdStepSvQty(this, -1); event.stopPropagation();">-</button>
                            <input type="text" class="rd-sm-pm-input" value="1" id="sv-qty-${idx}" oninput="this.value=this.value.replace(/\\D/g,'')" onclick="event.stopPropagation();">
                            <button class="rd-sm-pm-btn" onclick="window.rdStepSvQty(this, 1); event.stopPropagation();">+</button>
                        </div>
                        <button class="rd-sv-add-btn" onclick="window.pmsRdAddTempService('${safeName}', ${s.sell_price || 0}, 'sv-qty-${idx}', ${s.id}); event.stopPropagation();" ${outOfStock ? 'disabled' : ''}>
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12h14m-7-7v14"/></svg>
                        </button>
                    </div>
                </div>`;
        }).join('');
    }
}
window.pmsRdRenderServiceList = pmsRdRenderServiceList;

function rdStepSvQty(btn, step) {
    const inp = btn.parentElement.querySelector('input');
    if (!inp) return;
    let val = parseInt(inp.value) || 1;
    val = Math.max(1, val + step);
    inp.value = val;
}
window.rdStepSvQty = rdStepSvQty;

function pmsRdSearchService(input) {
    const activeCat = document.querySelector('#rd-sm-sv-cats .rd-sm-cat-item.active')?.dataset?.cat || _invActiveCat;
    pmsRdRenderServiceList(input.value, activeCat);
}
window.pmsRdSearchService = pmsRdSearchService;

function pmsRdSwitchSvCat(el) {
    document.querySelectorAll('#rd-sm-sv-cats .rd-sm-cat-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    const cat = el.dataset?.cat || el.textContent.trim();
    const searchVal = document.querySelector('#rd-sub-modal-service input')?.value || '';
    pmsRdRenderServiceList(searchVal, cat);
}
window.pmsRdSwitchSvCat = pmsRdSwitchSvCat;

function pmsRdAddTempService(name, price, qtyInpId, productId) {
    const qtyInp = document.getElementById(qtyInpId);
    const qty = parseInt(qtyInp?.value || '1');
    if (qty <= 0) return;

    const existing = rdTempServices.find(s => s.product_id === productId);
    const product = _invProducts.find(p => p.id === productId);
    const currentQty = existing ? existing.qty : 0;
    
    // Check stock limit
    if (product && product.stock !== null && product.stock !== undefined) {
        if (currentQty + qty > product.stock) {
            if (typeof pmsToast === 'function') pmsToast(`Không đủ số lượng. Tồn kho: ${product.stock}`, false);
            return;
        }
    }

    if (existing) {
        existing.qty += qty;
    } else {
        rdTempServices.push({ name, amount: price, qty, product_id: productId });
    }
    pmsRdRenderTempService();
    pmsRdRenderServiceList(); // Update stock badge immediately
    if (qtyInp) qtyInp.value = '1';
}
window.pmsRdAddTempService = pmsRdAddTempService;
function pmsRdRenderTempService() {
    const list = document.getElementById('rd-sm-sv-bill-list');
    if (!list) return;
    let total = 0;
    if (rdTempServices.length === 0) {
        list.innerHTML = `<div class="rd-sv-empty" style="display:flex; flex-direction:column; align-items:center; justify-content:center; flex:1; min-height:200px; color:var(--rd-text-muted); opacity:0.6; width:100%;">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:16px;">
          <rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>
        </svg>
        <p style="margin:0; font-size:14px; font-weight:700;">Trống</p>
      </div>`;
    } else {
        list.innerHTML = rdTempServices.map((s, i) => {
            total += s.amount * s.qty;
            return `
        <div class="rd-sm-bill-item" style="border-left: 4px solid var(--rd-accent-soft); padding: 16px;">
          <div style="flex:1;">
            <div style="font-weight:850; color:var(--rd-accent-bold); font-size:13px;">${pmsEscapeHtml(s.name)}</div>
            <div style="font-size:10px; color:var(--rd-text-muted); font-weight:700; margin-top:2px;">Số lượng: <strong>${s.qty}</strong></div>
          </div>
          <div style="text-align:right;">
            <div style="font-weight:850; color:var(--rd-accent-bold); font-family:'Outfit', sans-serif; font-size:15px;">${(s.amount * s.qty).toLocaleString()}</div>
            <span style="color:#ef4444; cursor:pointer; font-size:10px; font-weight:850; text-transform:uppercase; letter-spacing:0.05em;" onclick="pmsRdRemoveTempService(${i})">Gỡ</span>
          </div>
        </div>
      `;
        }).join('');
    }
    document.getElementById('rd-sm-sv-total').textContent = total.toLocaleString();
}
function pmsRdRemoveTempService(i) {
    rdTempServices.splice(i, 1);
    pmsRdRenderTempService();
    pmsRdRenderServiceList(); // Restore stock badge
}
async function pmsRdApplyService() {
    if (rdTempServices.length === 0) return pmsToast('Vui lòng thêm ít nhất một dịch vụ', false);

    const applyBtn = document.querySelector('button[onclick="pmsRdApplyService()"]');
    if (applyBtn) {
        if (applyBtn.disabled) return;
        applyBtn.disabled = true;
        applyBtn.innerHTML = 'Đang xử lý...';
    }

    if (window.isCiMode) {
        document.getElementById('rd-sub-modal-service').style.display = 'none';
        for (let s of rdTempServices) {
            pmsCiServiceList.push({ name: s.name, price: s.amount, qty: s.qty, product_id: s.product_id, category: 'SERVICE' });
        }
        rdTempServices = [];
        pmsRdRenderTempService();
        if (typeof pmsCiRenderItems === 'function') pmsCiRenderItems();
        window.isCiMode = false;
        if (applyBtn) { applyBtn.disabled = false; applyBtn.innerHTML = 'Xác nhận dịch vụ'; }
        return;
    }

    if (!rdFolioLoaded || !rdCurrentFolio) {
        pmsToast('Vui lòng mở Folio trước bằng cách vào tab Thanh toán', false);
        if (applyBtn) { applyBtn.disabled = false; applyBtn.innerHTML = 'Xác nhận dịch vụ'; }
        return;
    }

    document.getElementById('rd-sub-modal-service').style.display = 'none';
    rdSetPriceCardUpdating(true, 'Đang ghi dịch vụ');

    // Check if any item has product_id (inventory-linked) vs legacy
    const hasInventory = rdTempServices.some(s => s.product_id);

    try {
        if (hasInventory) {
            // ── Inventory Consume API: trừ kho + charge Folio (atomic) ──
            const inventoryServices = rdTempServices.filter(s => s.product_id);
            const legacyServices = rdTempServices.filter(s => !s.product_id);
            const items = inventoryServices.map(s => ({
                product_id: s.product_id,
                quantity: s.qty,
                unit_price: String(s.amount),
            }));
            const resp = await pmsApi('/api/pms/inventory/consume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folio_id: rdCurrentFolio.id, items }),
            });
            // Low stock warnings
            if (resp.low_stock_warnings && resp.low_stock_warnings.length > 0) {
                const warns = resp.low_stock_warnings.map(w => `${w.product_name}: còn ${w.current_stock} ${w.unit}`).join(', ');
                pmsToast(`⚠ Sắp hết hàng: ${warns}`, 'warning');
            }
            inventoryServices.forEach(s => {
                const itemResp = { ...resp };
                delete itemResp.transaction;
                rdMergeChargeResult(itemResp, {
                    transaction_type: 'MINIBAR_CHARGE',
                    category: 'SERVICE',
                    description: `${s.name} x${s.qty}`,
                    amount: (s.amount || s.price || 0) * s.qty,
                    quantity: s.qty,
                    unit_price: s.amount || s.price || 0,
                });
            });
            if (legacyServices.length > 0) {
                const batchPayload = legacyServices.map(s => ({
                    transaction_type: 'SERVICE_CHARGE',
                    amount: String((s.amount || s.price) * s.qty),
                    quantity: String(s.qty),
                    description: s.name,
                }));
                const legacyResp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/charges-batch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(batchPayload),
                });
                legacyServices.forEach((s, idx) => {
                    rdMergeChargeResult(legacyResp, {
                        transaction_type: 'SERVICE_CHARGE',
                        category: 'SERVICE',
                        description: s.name,
                        amount: (s.amount || s.price || 0) * s.qty,
                        quantity: s.qty,
                        unit_price: s.amount || s.price || 0,
                    });
                });
            }
            pmsToast(resp.message || 'Đã ghi nhận dịch vụ + trừ kho', true);
        } else {
            // ── Legacy: batch charge trực tiếp không qua kho (1 request thay vì N) ──
            const batchPayload = rdTempServices.map(s => ({
                transaction_type: 'SERVICE_CHARGE',
                amount: String((s.amount || s.price) * s.qty),
                quantity: String(s.qty),
                description: s.name,
            }));
            const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/charges-batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(batchPayload),
            });
            rdTempServices.forEach((s, idx) => {
                rdMergeChargeResult(resp, {
                    transaction_type: 'SERVICE_CHARGE',
                    category: 'SERVICE',
                    description: s.name,
                    amount: (s.amount || s.price || 0) * s.qty,
                    quantity: s.qty,
                    unit_price: s.amount || s.price || 0,
                });
            });
            pmsToast('Dịch vụ đã được ghi nhận vào Folio', true);
        }
        rdTempServices = [];
        pmsRdRenderTempService();
        await rdRefreshFolioAfterCharge(rdStayData?.id);
    } catch (e) {
        rdSetPriceCardUpdating(false);
        pmsToast('Lỗi ghi nhận dịch vụ: ' + e.message, false);
    } finally {
        const applyBtn = document.querySelector('button[onclick="pmsRdApplyService()"]');
        if (applyBtn) {
            applyBtn.disabled = false;
            applyBtn.innerHTML = 'Xác nhận dịch vụ';
        }
    }
}


async function pmsRdApplySurcharge() {
    if (rdTempSurcharges.length === 0) return pmsToast('Vui lòng thêm ít nhất một khoản phát sinh', false);

    if (window.isCiMode) {
        document.getElementById('rd-sub-modal-surcharge').style.display = 'none';
        for (let s of rdTempSurcharges) {
            pmsCiSurchargeList.push({ name: s.note, price: s.amount, qty: 1 });
        }
        rdTempSurcharges = [];
        pmsRdRenderTempSurcharge();
        if (typeof pmsCiRenderItems === 'function') pmsCiRenderItems();
        window.isCiMode = false;
        return;
    }

    if (!rdFolioLoaded || !rdCurrentFolio) {
        pmsToast('Vui lòng mở Folio trước bằng cách vào tab Thanh toán', false);
        return;
    }

    document.getElementById('rd-sub-modal-surcharge').style.display = 'none';
    rdSetPriceCardUpdating(true, 'Đang ghi phát sinh');

    try {
        const batchPayload = rdTempSurcharges.map(s => ({
            transaction_type: 'SURCHARGE',
            amount: String(s.amount),
            quantity: '1',
            description: s.note,
        }));
        const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/charges-batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(batchPayload),
        });
        rdTempSurcharges.forEach((s, idx) => {
            rdMergeChargeResult(resp, {
                transaction_type: 'SURCHARGE',
                category: 'SURCHARGE',
                description: s.note,
                amount: s.amount,
                quantity: 1,
                unit_price: s.amount,
            });
        });
        pmsToast('Phát sinh đã được ghi nhận vào Folio', true);
        rdTempSurcharges = [];
        pmsRdRenderTempSurcharge();
        await rdRefreshFolioAfterCharge(rdStayData?.id);
    } catch (e) {
        rdSetPriceCardUpdating(false);
        pmsToast('Lỗi ghi nhận phát sinh: ' + e.message, false);
    }
}

function pmsRdRenderActiveLists() {
    // Services and surcharges are now rendered from shared Folio cache via pmsRdMirrorFolio().
    // No-op: pmsRdMirrorFolio() handles both service and surcharge list rendering.
}
window.openRoomDetail = openRoomDetail;
window.rdSwitchTab = rdSwitchTab;
window.pmsRdUpdateStay = pmsRdUpdateStay;
window.rdRenderRoomInfoCard = rdRenderRoomInfoCard;
window.pmsRdRenderGuestList = pmsRdRenderGuestList;
window.pmsRdEditGuest = pmsRdEditGuest;
window.pmsRdCheckoutGuest = pmsRdCheckoutGuest;
window.pmsRdUpdateCapacityWarn = pmsRdUpdateCapacityWarn;
window.pmsRdApplyCheckedOutMode = pmsRdApplyCheckedOutMode;
window.pmsRdRemoveCheckedOutMode = pmsRdRemoveCheckedOutMode;
window.pmsRdOpenExtension = pmsRdOpenExtension;
window.pmsRdSaveExtension = pmsRdSaveExtension;
window.rdUpdateExtPreview = rdUpdateExtPreview;
window.rdQuickExt = rdQuickExt;
window.rdStepSvQty = rdStepSvQty;
window.pmsRdOpenSurcharge = pmsRdOpenSurcharge;
window.pmsRdAddTempSurcharge = pmsRdAddTempSurcharge;
window.pmsRdRemoveTempSurcharge = pmsRdRemoveTempSurcharge;
window.pmsRdApplySurcharge = pmsRdApplySurcharge;
window.pmsRdOpenService = pmsRdOpenService;
window.pmsRdSearchService = pmsRdSearchService;
window.pmsRdSwitchSvCat = pmsRdSwitchSvCat;
window.pmsRdAddTempService = pmsRdAddTempService;
window.pmsRdRemoveTempService = pmsRdRemoveTempService;
window.pmsRdApplyService = pmsRdApplyService;
window.pmsRdSearchGuest = pmsRdSearchGuest;
window.pmsRdRenderActiveLists = pmsRdRenderActiveLists;
window.pmsRdResetPaymentUI = pmsRdResetPaymentUI;
window.fetchFolio = fetchFolio;
window.pmsRdMirrorFolio = pmsRdMirrorFolio;
window.rdLoadPayment = rdLoadPayment;
window.rdSetBusy = rdSetBusy;
window.rdSetAutoPay = rdSetAutoPay;
window.rdSortLedgerTransactions = rdSortLedgerTransactions;
window.rdMergeTransactionUpdate = rdMergeTransactionUpdate;
window.pmsRdQueueNotesAutosave = pmsRdQueueNotesAutosave;
window.pmsRdVoidTx = pmsRdVoidTx;

// ─────────────────────────── Partial Refund Popup ───────────────────────────
let _rdRefundState = { txId: null, desc: '', qty: 0, unitPrice: 0, submitting: false };

function pmsRdEnsureRefundPopup() {
    let modal = document.getElementById('rd-sub-modal-refund');

    const requiredIds = [
        'rd-refund-desc',
        'rd-refund-current-qty',
        'rd-refund-unit-price',
        'rd-refund-remaining-qty',
        'rd-refund-qty-input',
        'rd-refund-amount-preview',
        'rd-refund-mode-hint',
        'rd-refund-reason',
        'rd-refund-error',
        'rd-refund-submit-btn',
    ];

    const hasAllRequired = () => requiredIds.every((id) => document.getElementById(id));

    if (!document.getElementById('rd-refund-style')) {
        document.body.insertAdjacentHTML('beforeend', `
            <style id="rd-refund-style">
                .rd-refund-modal { background:#fff; border-radius:20px; box-shadow:0 24px 60px rgba(2,6,23,.28); border:1px solid rgba(122,178,178,.25); width:min(520px, 96vw); overflow:hidden; }
                .rd-refund-hero { padding:16px 18px; background:linear-gradient(135deg,#ef4444 0%, #dc2626 100%); color:#fff; display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
                .rd-refund-hero-title { font-size:16px; font-weight:850; margin:0; line-height:1.2; }
                .rd-refund-hero-sub { font-size:12px; opacity:.9; margin-top:4px; }
                .rd-refund-close { width:30px; height:30px; border:0; border-radius:10px; background:rgba(255,255,255,.16); color:#fff; font-size:18px; cursor:pointer; }
                .rd-refund-body { padding:16px; display:flex; flex-direction:column; gap:12px; }
                .rd-refund-product { border:1px solid #e2e8f0; border-radius:12px; padding:12px; background:#fff; }
                .rd-refund-product-name { font-size:14px; font-weight:800; color:#0f172a; margin-bottom:10px; }
                .rd-refund-metrics { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
                .rd-refund-metric { background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:8px; }
                .rd-refund-metric-label { font-size:11px; color:#64748b; margin-bottom:4px; }
                .rd-refund-metric-value { font-size:13px; font-weight:800; color:#0f172a; }
                .rd-refund-qty-wrap { border:1px solid #e2e8f0; border-radius:12px; padding:10px; background:#fff; }
                .rd-refund-label { font-size:12px; font-weight:700; color:#334155; margin-bottom:8px; display:block; }
                .rd-refund-qty-control { display:flex; align-items:center; gap:8px; }
                .rd-refund-qty-btn { width:34px; height:34px; border-radius:10px; border:1px solid #dbe3ef; background:#f8fafc; color:#334155; font-weight:800; cursor:pointer; }
                .rd-refund-qty-input { flex:1; text-align:center; padding:8px 10px; border:1px solid #dbe3ef; border-radius:10px; font-size:15px; font-weight:800; color:#0f172a; }
                .rd-refund-quick { margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; }
                .rd-refund-quick-btn { padding:6px 10px; border-radius:999px; border:1px solid #dbe3ef; background:#fff; font-size:12px; font-weight:700; color:#334155; cursor:pointer; }
                .rd-refund-impact { border:1px solid #fecaca; background:#fef2f2; border-radius:12px; padding:10px; }
                .rd-refund-impact-main { font-size:13px; font-weight:800; color:#b91c1c; }
                .rd-refund-impact-hint { font-size:12px; color:#7f1d1d; margin-top:4px; }
                .rd-refund-error { display:none; border:1px solid #fecaca; background:#fef2f2; color:#b91c1c; border-radius:10px; padding:8px 10px; font-size:12px; }
                .rd-refund-reason { width:100%; padding:10px 12px; border:1px solid #dbe3ef; border-radius:10px; font-size:13px; }
                .rd-refund-footer { display:flex; gap:8px; }
                .rd-refund-cancel, .rd-refund-submit { flex:1; padding:10px; border:0; border-radius:10px; font-weight:800; font-size:13px; cursor:pointer; }
                .rd-refund-cancel { background:#f1f5f9; color:#475569; }
                .rd-refund-submit { background:#ef4444; color:#fff; }
            </style>
        `);
    }

    if (modal && !hasAllRequired()) {
        modal.remove();
        modal = null;
    }

    if (!modal) {
        document.body.insertAdjacentHTML('beforeend', `
            <div id="rd-sub-modal-refund" class="rd-sub-modal-overlay" style="display:none;z-index:20000;">
                <div class="rd-refund-modal">
                    <div class="rd-refund-hero">
                        <div>
                            <h4 class="rd-refund-hero-title">Hoàn trả dịch vụ</h4>
                            <div class="rd-refund-hero-sub">Ghi nhận trả lại hoặc giảm số lượng đã dùng</div>
                        </div>
                        <button type="button" class="rd-refund-close" onclick="pmsRdCloseRefundPopup()">&times;</button>
                    </div>
                    <div class="rd-refund-body">
                        <div class="rd-refund-product">
                            <div id="rd-refund-desc" class="rd-refund-product-name"></div>
                            <div class="rd-refund-metrics">
                                <div class="rd-refund-metric"><div class="rd-refund-metric-label">Đang ghi nhận</div><div id="rd-refund-current-qty" class="rd-refund-metric-value"></div></div>
                                <div class="rd-refund-metric"><div class="rd-refund-metric-label">Đơn giá</div><div id="rd-refund-unit-price" class="rd-refund-metric-value"></div></div>
                                <div class="rd-refund-metric"><div class="rd-refund-metric-label">Còn lại sau hoàn</div><div id="rd-refund-remaining-qty" class="rd-refund-metric-value"></div></div>
                            </div>
                        </div>
                        <div class="rd-refund-qty-wrap">
                            <label class="rd-refund-label" for="rd-refund-qty-input">Số lượng hoàn trả</label>
                            <div class="rd-refund-qty-control">
                                <button type="button" class="rd-refund-qty-btn" onclick="pmsRdStepRefundQty(-1)">−</button>
                                <input type="number" id="rd-refund-qty-input" class="rd-refund-qty-input" min="1" oninput="pmsRdRefundQtyChanged()">
                                <button type="button" class="rd-refund-qty-btn" onclick="pmsRdStepRefundQty(1)">+</button>
                            </div>
                            <div class="rd-refund-quick">
                                <button type="button" class="rd-refund-quick-btn" onclick="pmsRdSetRefundQty(1)">1</button>
                                <button type="button" class="rd-refund-quick-btn" id="rd-refund-quick-half" onclick="pmsRdSetRefundQty(Math.max(1, Math.floor(_rdRefundState.qty / 2)))">50%</button>
                                <button type="button" class="rd-refund-quick-btn" onclick="pmsRdSetRefundQty(_rdRefundState.qty)">Tất cả</button>
                            </div>
                        </div>
                        <div class="rd-refund-impact">
                            <div id="rd-refund-amount-preview" class="rd-refund-impact-main"></div>
                            <div id="rd-refund-mode-hint" class="rd-refund-impact-hint"></div>
                        </div>
                        <div>
                            <label class="rd-refund-label" for="rd-refund-reason">Lý do (tuỳ chọn)</label>
                            <input type="text" id="rd-refund-reason" class="rd-refund-reason" placeholder="VD: Khách trả lại 1 chai nước">
                        </div>
                        <div id="rd-refund-error" class="rd-refund-error"></div>
                        <div class="rd-refund-footer">
                            <button type="button" class="rd-refund-cancel" onclick="pmsRdCloseRefundPopup()">Huỷ</button>
                            <button type="button" id="rd-refund-submit-btn" class="rd-refund-submit" onclick="pmsRdSubmitRefund()">Hoàn trả một phần</button>
                        </div>
                    </div>
                </div>
            </div>
        `);
        modal = document.getElementById('rd-sub-modal-refund');
    }

    if (!modal || !hasAllRequired()) return null;
    return modal;
}

function pmsRdOpenRefundPopup(txId, desc, qty, unitPrice) {
    _rdRefundState = { txId, desc, qty, unitPrice, submitting: false };

    const modal = pmsRdEnsureRefundPopup();
    const descEl = document.getElementById('rd-refund-desc');
    const currentQtyEl = document.getElementById('rd-refund-current-qty');
    const unitPriceEl = document.getElementById('rd-refund-unit-price');
    const remainingQtyEl = document.getElementById('rd-refund-remaining-qty');
    const qtyInput = document.getElementById('rd-refund-qty-input');
    const reasonEl = document.getElementById('rd-refund-reason');
    const errorEl = document.getElementById('rd-refund-error');
    const halfBtn = document.getElementById('rd-refund-quick-half');

    if (!modal || !descEl || !currentQtyEl || !unitPriceEl || !remainingQtyEl || !qtyInput) {
        pmsToast('Không mở được popup hoàn trả', false);
        return;
    }

    descEl.textContent = desc;
    currentQtyEl.textContent = qty;
    unitPriceEl.textContent = pmsMoney(unitPrice);
    remainingQtyEl.textContent = Math.max(0, qty - 1);
    qtyInput.max = qty;
    qtyInput.value = 1;
    if (halfBtn) halfBtn.style.display = qty > 2 ? '' : 'none';
    if (reasonEl) reasonEl.value = '';
    if (errorEl) {
        errorEl.textContent = '';
        errorEl.style.display = 'none';
    }
    pmsRdRefundQtyChanged();
    modal.style.display = 'flex';
    setTimeout(() => qtyInput.focus(), 50);
}

function pmsRdCloseRefundPopup() {
    const modal = document.getElementById('rd-sub-modal-refund');
    if (modal) modal.style.display = 'none';
    _rdRefundState = { txId: null, desc: '', qty: 0, unitPrice: 0, submitting: false };
}

function pmsRdClampRefundQty(value) {
    const maxQty = Math.max(1, parseInt(_rdRefundState.qty) || 1);
    const qty = parseInt(value) || 1;
    return Math.min(maxQty, Math.max(1, qty));
}

function pmsRdSetRefundQty(value) {
    const qtyInput = document.getElementById('rd-refund-qty-input');
    if (!qtyInput) return;
    qtyInput.value = pmsRdClampRefundQty(value);
    pmsRdRefundQtyChanged();
}

function pmsRdStepRefundQty(delta) {
    const qtyInput = document.getElementById('rd-refund-qty-input');
    if (!qtyInput) return;
    pmsRdSetRefundQty((parseInt(qtyInput.value) || 1) + delta);
}

function pmsRdRefundQtyChanged() {
    const qtyInput = document.getElementById('rd-refund-qty-input');
    const preview = document.getElementById('rd-refund-amount-preview');
    const hint = document.getElementById('rd-refund-mode-hint');
    const remaining = document.getElementById('rd-refund-remaining-qty');
    const btn = document.getElementById('rd-refund-submit-btn');
    if (!qtyInput || !preview || !btn) return;

    const qty = pmsRdClampRefundQty(qtyInput.value);
    if (String(qtyInput.value) !== String(qty)) qtyInput.value = qty;

    const amount = qty * _rdRefundState.unitPrice;
    const remainingQty = Math.max(0, (_rdRefundState.qty || 0) - qty);
    preview.textContent = `Số tiền hoàn: ${pmsMoney(amount)}`;
    if (remaining) remaining.textContent = `${remainingQty}`;

    if (qty >= _rdRefundState.qty) {
        if (hint) hint.textContent = 'Xoá toàn bộ dòng dịch vụ này khỏi danh sách đang ghi nhận.';
        btn.textContent = 'Xoá toàn bộ dịch vụ';
        btn.style.background = '#dc2626';
    } else {
        if (hint) hint.textContent = 'Hoàn trả một phần, dòng dịch vụ còn lại vẫn nằm trong danh sách.';
        btn.textContent = 'Hoàn trả một phần';
        btn.style.background = '#ef4444';
    }
}

async function pmsRdSubmitRefund() {
    if (_rdRefundState.submitting || !_rdRefundState.txId || !rdCurrentFolio) return;
    const qtyInput = document.getElementById('rd-refund-qty-input');
    const refundQty = parseInt(qtyInput?.value || '0');
    const reason = document.getElementById('rd-refund-reason')?.value || '';
    const errorEl = document.getElementById('rd-refund-error');

    if (refundQty < 1) {
        if (errorEl) { errorEl.textContent = 'Số lượng phải >= 1'; errorEl.style.display = 'block'; }
        return;
    }
    if (refundQty > _rdRefundState.qty) {
        if (errorEl) { errorEl.textContent = `Tối đa ${_rdRefundState.qty}`; errorEl.style.display = 'block'; }
        return;
    }

    _rdRefundState.submitting = true;
    const btn = document.getElementById('rd-refund-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Đang xử lý...'; }

    try {
        const params = new URLSearchParams({ refund_qty: refundQty, reason });
        const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/partial-refund/${_rdRefundState.txId}?${params.toString()}`, { method: 'POST' });

        pmsRdCloseRefundPopup();

        if (resp.voided) {
            pmsToast(`Đã xoá toàn bộ "${_rdRefundState.desc}"`);
        } else {
            pmsToast(`Đã hoàn trả ${refundQty}x "${_rdRefundState.desc}"`);
        }

        // Refresh folio + UI
        rdSetPriceCardUpdating(true, 'Đang cập nhật');
        await fetchFolioLight(rdStayData?.id, { skipRoomInfoRefresh: true });
        if (typeof pmsRdRenderFolioTabs === 'function') pmsRdRenderFolioTabs();
        if (typeof pmsRdRenderFolio === 'function') pmsRdRenderFolio();
        if (typeof rdRenderRoomInfoCard === 'function') await rdRenderRoomInfoCard({ force: true });
        rdSetPriceCardUpdating(false);
    } catch (e) {
        if (errorEl) { errorEl.textContent = e.message || 'Lỗi hoàn trả'; errorEl.style.display = 'block'; }
    } finally {
        _rdRefundState.submitting = false;
        if (btn) { btn.disabled = false; pmsRdRefundQtyChanged(); }
    }
}

window.pmsRdOpenRefundPopup = pmsRdOpenRefundPopup;
window.pmsRdCloseRefundPopup = pmsRdCloseRefundPopup;
window.pmsRdRefundQtyChanged = pmsRdRefundQtyChanged;
window.pmsRdStepRefundQty = pmsRdStepRefundQty;
window.pmsRdSetRefundQty = pmsRdSetRefundQty;
window.pmsRdSubmitRefund = pmsRdSubmitRefund;
Object.defineProperty(window, 'rdPayTabLoaded', {
    get: () => rdPayTabLoaded,
    set: (v) => { rdPayTabLoaded = v; }
});

// ══════════════════════════════════════════════════════
// TIMELINE - Guest Activity Timeline
// ══════════════════════════════════════════════════════

// ─── Icon map per activity type ───
const RD_TL_ICONS = {
    CHECK_IN: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 15 3 9"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`,
    CHECK_OUT: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    ROOM_CHANGE: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`,
    EXTEND_STAY: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="12" y1="14" x2="12" y2="18"/><line x1="10" y1="16" x2="14" y2="16"/></svg>`,
    EARLY_CHECKIN: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    LATE_CHECKOUT: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    GUEST_ADDED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`,
    BOOKING_CREATED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
    BOOKING_CANCELLED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    NO_SHOW: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="18" y1="8" x2="23" y2="13"/><line x1="23" y1="8" x2="18" y2="13"/></svg>`,
    PAYMENT_RECEIVED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`,
    PAYMENT_REFUND: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
    DEPOSIT_ADDED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>`,
    DEPOSIT_USED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><line x1="12" y1="14" x2="12" y2="18"/><line x1="10" y1="16" x2="14" y2="16"/></svg>`,
    SERVICE_USED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93l-1.41 1.41"/><path d="M6.34 17.66l-1.41 1.41"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="M4.93 4.93l1.41 1.41"/><path d="M17.66 17.66l1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/></svg>`,
    MINIBAR_USED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2z"/></svg>`,
    COMPLAINT: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
    FEEDBACK: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
    REVIEW: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
    LOST_ITEM: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    PROFILE_UPDATED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    BLACKLISTED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>`,
    MERGED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>`,
    BOOKING_MODIFIED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
    INVOICE_SPLIT_CREATED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="12" x2="12" y2="18"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
    INVOICE_SPLIT_PRINTED: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>`,
};

// ─── CSS class map per activity type ───
const RD_TL_CLASS = {
    CHECK_IN: 'rd-tl-checkin',
    CHECK_OUT: 'rd-tl-checkout',
    ROOM_CHANGE: 'rd-tl-roomchange',
    EARLY_CHECKIN: 'rd-tl-checkin',
    LATE_CHECKOUT: 'rd-tl-checkout',
    EXTEND_STAY: 'rd-tl-checkin',
    GUEST_ADDED: 'rd-tl-guestadd',
    BOOKING_CREATED: 'rd-tl-booking',
    BOOKING_MODIFIED: 'rd-tl-booking',
    BOOKING_CANCELLED: 'rd-tl-default',
    NO_SHOW: 'rd-tl-default',
    PAYMENT_RECEIVED: 'rd-tl-payment',
    PAYMENT_REFUND: 'rd-tl-payment',
    DEPOSIT_ADDED: 'rd-tl-deposit',
    DEPOSIT_USED: 'rd-tl-deposit',
    SERVICE_USED: 'rd-tl-service',
    MINIBAR_USED: 'rd-tl-service',
    COMPLAINT: 'rd-tl-complaint',
    FEEDBACK: 'rd-tl-default',
    REVIEW: 'rd-tl-default',
    LOST_ITEM: 'rd-tl-default',
    PROFILE_UPDATED: 'rd-tl-system',
    BLACKLISTED: 'rd-tl-system',
    MERGED: 'rd-tl-system',
    INVOICE_SPLIT_CREATED: 'rd-tl-payment',
    INVOICE_SPLIT_PRINTED: 'rd-tl-payment',
};

// ─── Format time HH:MM (VN wall clock) ───
function rdTlTime(iso) {
    if (!iso) return '—';
    try {
        const d = pmsParseDate(iso);
        if (Number.isNaN(d.getTime())) return '—';
        const parts = new Intl.DateTimeFormat('vi-VN', {
            timeZone: PMS_VN_TZ,
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).formatToParts(d);
        const p = (t) => parts.find((x) => x.type === t)?.value ?? '00';
        return `${p('hour')}:${p('minute')}`;
    } catch { return '—'; }
}

// ─── Format date for group header (VN calendar) ───
function rdTlDate(iso) {
    if (!iso) return '—';
    try {
        const d = pmsParseDate(iso);
        if (Number.isNaN(d.getTime())) return '—';
        const df = new Intl.DateTimeFormat('en-CA', { timeZone: PMS_VN_TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
        const dKey = df.format(d);
        const todayKey = df.format(new Date());
        const toMs = (k) => {
            const [y, m, day] = k.split('-').map(Number);
            return Date.UTC(y, m - 1, day);
        };
        const diff = Math.round((toMs(todayKey) - toMs(dKey)) / 86400000);
        if (diff === 0) return 'Hôm nay';
        if (diff === 1) return 'Hôm qua';
        if (diff < 7 && diff > 0) return `${diff} ngày trước`;
        const [yy, mm, dd] = dKey.split('-');
        return `${dd}/${mm}/${yy}`;
    } catch { return '—'; }
}

// ─── Get actor display name ───
function rdTlActor(actor_type, actor_id, extra_data) {
    if (actor_type === 'system') return 'Hệ thống';
    if (actor_type === 'user' && actor_id) return `NV #${actor_id}`;
    return '';
}

// ─── Render single activity item ───
function rdTlRenderItem(act) {
    const cls = RD_TL_CLASS[act.activity_type] || 'rd-tl-default';
    const icon = RD_TL_ICONS[act.activity_type] || RD_TL_ICONS.SERVICE_USED;
    const time = rdTlTime(act.created_at);
    const title = act.title || act.activity_type;
    const desc = act.description || '';
    const amount = '';
    const actor = rdTlActor(act.actor_type, act.actor_id, act.extra_data);

    return `
    <div class="rd-tl-item">
        <div class="rd-tl-node">
            <div class="rd-tl-dot ${cls}">${icon}</div>
        </div>
        <div class="rd-tl-card ${cls}">
            <div class="rd-tl-main">
                <div class="rd-tl-title-row">
                    <div class="rd-tl-title">${title}</div>
                    ${amount ? `<div class="rd-tl-amount">${amount}</div>` : ''}
                </div>
                ${desc ? `<div class="rd-tl-desc">${desc}</div>` : ''}
                <div class="rd-tl-meta">
                    <span class="rd-tl-time">${time}</span>
                    ${actor ? `<span class="rd-tl-actor">· ${actor}</span>` : ''}
                </div>
            </div>
        </div>
    </div>`;
}

// ─── Group activities by date (VN calendar) ───
function rdTlGroupByDate(activities) {
    const groups = {};
    const df = new Intl.DateTimeFormat('en-CA', { timeZone: PMS_VN_TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
    activities.forEach(a => {
        const d = pmsParseDate(a.created_at);
        const key = df.format(d);
        if (!groups[key]) groups[key] = [];
        groups[key].push(a);
    });
    Object.values(groups).forEach(g => g.sort((a, b) => pmsParseDate(b.created_at) - pmsParseDate(a.created_at)));
    return groups;
}

// ─── Main: Load & render timeline ───
async function rdLoadTimeline() {
    const stayId = rdStayData && rdStayData.id;
    if (!stayId) {
        const loadingEl = document.getElementById('rd-tl-loading');
        const emptyEl = document.getElementById('rd-tl-empty');
        if (loadingEl) loadingEl.style.display = 'none';
        if (emptyEl) {
            emptyEl.style.display = 'flex';
            const p = emptyEl.querySelector('p');
            if (p) p.textContent = 'Chưa mở chi tiết lưu trú — không tải được lịch sử.';
        }
        return;
    }

    const listEl = document.getElementById('rd-tl-list');
    const loadingEl = document.getElementById('rd-tl-loading');
    const emptyEl = document.getElementById('rd-tl-empty');

    if (loadingEl) loadingEl.style.display = 'flex';
    if (listEl) listEl.style.display = 'none';
    if (emptyEl) emptyEl.style.display = 'none';

    try {
        const actsData = await pmsApi(`/api/pms/stays/${stayId}/activities?limit=100`);

        rdTlAllActivities = rdTlNormalizeActivities(actsData.activities || []);

        if (loadingEl) loadingEl.style.display = 'none';

        if (rdTlAllActivities.length === 0) {
            if (emptyEl) emptyEl.style.display = 'flex';
            return;
        }

        if (listEl) {
            listEl.style.display = 'flex';

            // Apply current filter
            const activeBtn = document.querySelector('.rd-tl-filter-btn.active');
            const filter = activeBtn ? activeBtn.dataset.filter : 'all';

            rdTlRenderTimelineList(rdTlAllActivities, filter);
        }
    } catch (e) {
        if (loadingEl) loadingEl.style.display = 'none';
        pmsToast(`Không thể tải lịch sử: ${e.message}`, false);
    }
}

// ─── Render timeline list with filter ───
function rdTlRenderTimelineList(activities, filter = 'all') {
    const listEl = document.getElementById('rd-tl-list');
    if (!listEl) return;

    let filtered = rdTlNormalizeActivities(activities);
    if (filter !== 'all') {
        filtered = filtered.filter(a => a.activity_group === filter);
    }

    if (filtered.length === 0) {
        listEl.innerHTML = '';
        const emptyEl = document.getElementById('rd-tl-empty');
        if (emptyEl) {
            emptyEl.style.display = 'flex';
            emptyEl.querySelector('p').textContent = filter === 'all'
                ? 'Chưa có hoạt động nào được ghi nhận'
                : 'Không có hoạt động nào trong nhóm này';
        }
        return;
    }

    const emptyEl = document.getElementById('rd-tl-empty');
    if (emptyEl) emptyEl.style.display = 'none';

    const groups = rdTlGroupByDate(filtered);
    const sortedKeys = Object.keys(groups).sort((a, b) => b.localeCompare(a));

    let html = '';
    sortedKeys.forEach(key => {
        const acts = groups[key];
        const firstAct = acts[0];
        const dateLabel = rdTlDate(firstAct.created_at);
        html += `<div class="rd-tl-group-header">
            <span class="rd-tl-group-date">${dateLabel}</span>
            <div class="rd-tl-group-line"></div>
        </div>`;
        acts.forEach(a => { html += rdTlRenderItem(a); });
    });

    listEl.innerHTML = html;
}

function rdTlNormalizeActivities(activities) {
    const allowedGroups = new Set(['stay', 'system']);
    const seen = new Set();
    return (activities || [])
        .filter(a => allowedGroups.has(a.activity_group) || ['CHECK_IN', 'CHECK_OUT', 'ROOM_CHANGE', 'EXTEND_STAY', 'GUEST_ADDED', 'PROFILE_UPDATED', 'BLACKLISTED', 'INVOICE_SPLIT_CREATED', 'INVOICE_SPLIT_PRINTED'].includes(a.activity_type))
        .map(a => ({ ...a, activity_group: a.activity_group === 'system' ? 'system' : 'stay' }))
        .sort((a, b) => pmsParseDate(a.created_at) - pmsParseDate(b.created_at))
        .filter(a => {
            const keyTime = Math.floor((pmsParseDate(a.created_at).getTime() || 0) / 60000);
            const key = `${a.activity_type}|${keyTime}|${a.title || ''}|${a.description || ''}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
}

// ─── Filter handler ───
let rdTlCurrentFilter = 'all';

function rdTlFilter(filter) {
    rdTlCurrentFilter = filter;

    // Update button states
    document.querySelectorAll('.rd-tl-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });

    rdTlRenderTimelineList(rdTlAllActivities, filter);
}
