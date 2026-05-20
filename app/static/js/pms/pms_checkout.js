// static/js/pms/pms_checkout.js
// PMS Check-out - Backend-first financial calculations
// Nguyên tắc: Backend là nguồn duy nhất cho số liệu tài chính.
// Frontend CHỈ HIỂN THỊ dữ liệu từ API, không tự tính toán.
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// Open Check-out from Dashboard
// ─────────────────────────────────────────────────────────────────────────────
async function openCO(stayId, roomNum) {
    if (!stayId) {
        pmsToast('Thiếu ID lưu trú.', false);
        return;
    }
    if (typeof openRoomDetail === 'function') {
        openRoomDetail(stayId, roomNum, 'payment');
    } else {
        pmsToast('Lỗi: Gọi chức năng thanh toán thất bại.', false);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper: Lấy balance REAL-TIME từ backend
// ─────────────────────────────────────────────────────────────────────────────
async function rdPayFetchBalance(folioId) {
    try {
        const resp = await pmsApi(`/api/pms/folio/${folioId}/balance`);
        return resp;
    } catch (e) {
        console.error('[rdPayFetchBalance]', e);
        return null;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Render Folio Tabs
// ─────────────────────────────────────────────────────────────────────────────
function pmsRdRenderFolioTabs() {
    const c = document.getElementById('rd-folio-tabs-container');
    if (!c || rdCurrentFolios.length === 0) return;

    // Tính tổng bill từ transactions
    const getFolioBillTotal = (folio) => {
        if (!folio) return 0;
        const txs = folio.transactions || [];
        if (rdIsCheckedOut && txs.length === 0) {
            return (parseFloat(folio.total_charge) || 0) - (parseFloat(folio.total_discount) || 0);
        }
        const charges = txs
            .filter(t => !t.is_voided && rdPayNum(t.amount) > 0 && !['PAYMENT', 'DEBT_PAYMENT', 'DEPOSIT_USED', 'REFUND', 'REFUND_PAYMENT'].includes(t.type || t.transaction_type))
            .reduce((acc, t) => acc + rdPayNum(t.amount), 0);
        const discounts = txs
            .filter(t => !t.is_voided && t.category === 'DISCOUNT')
            .reduce((acc, t) => acc + Math.abs(rdPayNum(t.amount)), 0);
        return charges - discounts;
    };

    // Active stay: cộng thêm virtual charges từ pricing preview
    const addVirtualCharges = (folioBill) => {
        if (rdIsCheckedOut || !rdPaymentState?.breakdown) return folioBill;
        const activeFolio = rdCurrentFolios[rdActiveFolioIndex] || rdCurrentFolios[0];
        const hasVirtualRoom = (activeFolio?.transactions || []).some(t => (
            !t.is_voided
            && t.is_virtual
            && ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(t.type || t.transaction_type)
        ));
        if (hasVirtualRoom) return folioBill;
        const virtual = rdPaymentState.breakdown
            .filter(b => ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'].includes(b.type))
            .reduce((acc, b) => acc + (parseFloat(b.amount) || 0), 0);
        return folioBill + virtual;
    };

    let tabsHtml = rdCurrentFolios.map((f, i) => {
        const folioBill = addVirtualCharges(getFolioBillTotal(f));
        return `<div class="rd-folio-tab ${i === rdActiveFolioIndex ? 'active' : ''}" onclick="rdPaySelectFolio(${i})">${pmsEscapeHtml(f.notes || ('Hóa đơn ' + (i+1)))}<span class="badge">${pmsMoney(folioBill)}</span></div>`;
    }).join('');
    
    let actionsHtml = `<div class="rd-folio-actions"><button class="rd-folio-btn primary" onclick="rdPayOpenAddFolio()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>Tách Hoá Đơn</button>${rdCurrentFolios.length > 1 ? '<button class="rd-folio-btn" onclick="rdPayOpenMergeFolio()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>Gộp Bill</button>' : ''}</div>`;
    
    c.innerHTML = `<div class="rd-folio-tab-group">${tabsHtml}</div>${actionsHtml}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Add/Merge Folio
// ─────────────────────────────────────────────────────────────────────────────
let _rdSplitSummary = { net_charge: 0, total_split: 0, remaining: 0 };

async function rdPayOpenAddFolio() {
    const modal = document.getElementById('rd-sub-modal-folio-create');
    if (!modal) return;
    const guests = (typeof rdGuestList !== 'undefined' ? rdGuestList : []) || [];
    const guestSel = document.getElementById('rd-folio-create-guest');
    if (guestSel) {
        guestSel.innerHTML = `<option value="">Không gắn khách cụ thể</option>` + guests.map(g => (
            `<option value="${pmsEscapeHtml(String(g.id || ''))}">${pmsEscapeHtml(g.full_name || 'Khách chưa tên')}${g.is_primary ? ' - khách chính' : ''}</option>`
        )).join('');
        const primary = guests.find(g => g.is_primary) || guests[0];
        guestSel.value = primary?.id ? String(primary.id) : '';
    }

    ['rd-folio-create-invoice-name', 'rd-folio-create-tax-code', 'rd-folio-create-invoice-contact', 'rd-folio-create-invoice-address'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const amountInput = document.getElementById('rd-split-amount');
    if (amountInput) amountInput.value = '';

    _rdSplitSummary = { net_charge: 0, total_split: 0, remaining: 0 };
    rdPaySyncSplitBillGuest();
    rdPayRenderSplitBillTxList();
    rdPayValidateSplitAmount();
    modal.style.display = 'flex';

    if (rdCurrentFolio?.id) {
        try {
            const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/splits`);
            _rdSplitSummary = resp?.summary || { net_charge: 0, total_split: 0, remaining: 0 };
            rdPayValidateSplitAmount();
        } catch(e) {
            _rdSplitSummary = { net_charge: 0, total_split: 0, remaining: 0 };
            rdPayValidateSplitAmount();
        }
    }
}

function rdPaySplitBillGuestById(id) {
    const guests = (typeof rdGuestList !== 'undefined' ? rdGuestList : []) || [];
    return guests.find(g => String(g.id || '') === String(id || '')) || null;
}

function rdPaySyncSplitBillGuest() {
    const guestSel = document.getElementById('rd-folio-create-guest');
    const guest = rdPaySplitBillGuestById(guestSel?.value);
    const nameInput = document.getElementById('rd-folio-create-name');
    const invoiceName = document.getElementById('rd-folio-create-invoice-name');
    const taxInput = document.getElementById('rd-folio-create-tax-code');
    const contactInput = document.getElementById('rd-folio-create-invoice-contact');
    const addressInput = document.getElementById('rd-folio-create-invoice-address');
    if (guest) {
        if (nameInput && !nameInput.value.trim()) nameInput.value = `Hóa đơn - ${guest.full_name || 'Khách'}`;
        if (invoiceName) invoiceName.value = guest.company_name || '';
        if (taxInput) taxInput.value = guest.tax_code || '';
        if (contactInput) contactInput.value = guest.invoice_contact || guest.phone || '';
        if (addressInput) addressInput.value = guest.company_address || '';
    }
}

function rdPaySplitSelectableTxs() {
    const txs = rdCurrentFolio?.transactions || [];
    return (typeof rdSortLedgerTransactions === 'function' ? rdSortLedgerTransactions(txs) : [...txs])
        .filter(t => {
            const txType = t.type || t.transaction_type;
            return !t.is_voided
                && !t.is_virtual
                && rdPayNum(t.amount) > 0
                && !['PAYMENT', 'DEBT_PAYMENT', 'DEPOSIT_USED', 'REFUND', 'REFUND_PAYMENT'].includes(txType);
        });
}

function rdPayRenderSplitBillTxList() {
    const list = document.getElementById('rd-folio-create-tx-list');
    if (!list) return;
    const txs = rdPaySplitSelectableTxs();
    if (!txs.length) {
        list.innerHTML = `<div style="padding:14px; color:#94a3b8; font-size:12px; text-align:center; border:1px dashed #c8dcdc; border-radius:12px;">Chưa có dòng phí có thể chuyển. Có thể tạo hóa đơn phụ trước rồi chuyển sau.</div>`;
        rdPayUpdateSplitSelectionTotal();
        return;
    }
    list.innerHTML = txs.map(t => {
        const txType = t.type || t.transaction_type;
        const label = rdPayIsRoomCharge(t) ? 'Tiền phòng' : (t.category === 'SERVICE' ? 'Dịch vụ' : (t.category === 'SURCHARGE' || t.category === 'OTHER' ? 'Phát sinh' : txType));
        return `<label class="rd-split-tx-row">
            <input type="checkbox" class="rd-folio-create-tx" value="${pmsEscapeHtml(String(t.id))}" data-amount="${rdPayNum(t.amount)}" onchange="rdPayUpdateSplitSelectionTotal()">
            <span>
                <strong>${pmsEscapeHtml(t.description || label)}</strong>
                <small>${pmsEscapeHtml(label)} · ${pmsFdt(t.created_at)}</small>
            </span>
            <b>${pmsMoney(t.amount)}</b>
        </label>`;
    }).join('');
    rdPayUpdateSplitSelectionTotal();
}

function rdPayUpdateSplitSelectionTotal() {
    const selected = Array.from(document.querySelectorAll('.rd-folio-create-tx:checked'));
    const total = selected.reduce((acc, el) => acc + rdPayNum(el.dataset.amount), 0);
    const countEl = document.getElementById('rd-folio-create-selected-count');
    const totalEl = document.getElementById('rd-folio-create-transfer-total');
    if (countEl) countEl.textContent = String(selected.length);
    if (totalEl) totalEl.textContent = pmsMoney(total);
    // Auto-fill amount input with selected total
    const amountInput = document.getElementById('rd-split-amount');
    if (amountInput && total > 0) amountInput.value = Math.round(total).toLocaleString('vi-VN');
    rdPayValidateSplitAmount();
}

function rdPayParseSplitAmount() {
    const raw = (document.getElementById('rd-split-amount')?.value || '').replace(/[^\d]/g, '');
    return parseInt(raw) || 0;
}

function rdPayValidateSplitAmount() {
    const amount = rdPayParseSplitAmount();
    const quotaEl = document.getElementById('rd-split-quota');
    const warnEl = document.getElementById('rd-split-warning');
    const remaining = _rdSplitSummary.remaining || 0;
    const netCharge = _rdSplitSummary.net_charge || 0;
    const totalSplit = _rdSplitSummary.total_split || 0;

    if (quotaEl) {
        quotaEl.innerHTML = `Tổng folio: <b>${pmsMoney(netCharge)}</b> · Đã tách: <b>${pmsMoney(totalSplit)}</b> · Còn lại: <b>${pmsMoney(remaining)}</b>`;
    }
    if (warnEl) {
        if (amount > 0 && amount > remaining) {
            warnEl.style.display = 'block';
            warnEl.textContent = `Vượt ${pmsMoney(amount - remaining)} so với số tiền còn lại cho phép tách!`;
        } else {
            warnEl.style.display = 'none';
        }
    }
}

async function rdPaySubmitSplitInvoice() {
    const splitAmount = rdPayParseSplitAmount();
    if (!splitAmount || splitAmount <= 0) return pmsToast('Vui lòng nhập số tiền hoá đơn tách', false);

    const remaining = _rdSplitSummary.remaining || 0;
    if (splitAmount > remaining) return pmsToast('Số tiền vượt quá mức cho phép tách', false);

    const guestSel = document.getElementById('rd-folio-create-guest');
    const invoiceName = document.getElementById('rd-folio-create-invoice-name')?.value?.trim() || '';
    const taxCode = document.getElementById('rd-folio-create-tax-code')?.value?.trim() || '';
    const invoiceContact = document.getElementById('rd-folio-create-invoice-contact')?.value?.trim() || '';
    const invoiceAddress = document.getElementById('rd-folio-create-invoice-address')?.value?.trim() || '';

    const selectedTxs = Array.from(document.querySelectorAll('.rd-folio-create-tx:checked'));
    const lineItems = selectedTxs.map(el => {
        const txId = parseInt(el.value) || null;
        const tx = (rdCurrentFolio?.transactions || []).find(t => String(t.id) === String(txId));
        return {
            tx_id: txId,
            description: tx?.description || '',
            amount: rdPayNum(el.dataset.amount),
        };
    });

    const payload = {
        hotel_guest_id: guestSel?.value ? parseInt(guestSel.value) : null,
        split_amount: splitAmount,
        line_items: lineItems,
        invoice_name: invoiceName || null,
        invoice_tax_code: taxCode || null,
        invoice_contact: invoiceContact || null,
        invoice_address: invoiceAddress || null,
    };

    const btn = document.getElementById('rd-split-submit-btn');
    const oldHtml = btn?.innerHTML;
    if (btn) { btn.disabled = true; btn.innerHTML = 'Đang tạo...'; }
    try {
        await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/splits`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        pmsToast('Đã tạo hoá đơn tách thành công', true);
        document.getElementById('rd-sub-modal-folio-create').style.display = 'none';
        rdPayLoadSplits();
    } catch(e) { pmsToast('Lỗi tạo hoá đơn tách: ' + e.message, false); }
    finally {
        if (btn) { btn.disabled = false; btn.innerHTML = oldHtml || 'Tạo hoá đơn tách'; }
    }
}

async function rdPayLoadSplits() {
    const container = document.getElementById('rd-splits-list');
    if (!container || !rdCurrentFolio?.id) return;

    try {
        const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/splits`);
        const splits = resp?.splits || [];
        _rdSplitSummary = resp?.summary || { net_charge: 0, total_split: 0, remaining: 0 };

        if (!splits.length) {
            container.innerHTML = '';
            container.style.display = 'none';
            return;
        }

        container.style.display = 'block';
        container.innerHTML = `
            <div style="font-size:12px; font-weight:800; color:var(--rd-accent-bold); margin-bottom:8px; text-transform:uppercase; letter-spacing:.3px;">
                Hoá đơn đã tách (${splits.length})
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
                ${splits.map(s => {
                    const printed = !!s.printed_at;
                    const guests = (typeof rdGuestList !== 'undefined' ? rdGuestList : []) || [];
                    const hg = guests.find(g => String(g.id) === String(s.hotel_guest_id));
                    const guestLabel = s.invoice_name || hg?.full_name || 'Khách';
                    return `<div style="display:flex; align-items:center; gap:10px; padding:10px 12px; border:1px solid var(--rd-bg-secondary); border-radius:12px; background:#fff;">
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:12px; font-weight:700; color:var(--rd-accent-bold); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${pmsEscapeHtml(guestLabel)}</div>
                            <div style="font-size:10px; color:#64748b; margin-top:2px;">
                                ${s.invoice_tax_code ? 'MST: ' + pmsEscapeHtml(s.invoice_tax_code) + ' · ' : ''}${printed ? '<span style="color:#16a34a;">Đã in</span>' : '<span style="color:#f59e0b;">Chưa in</span>'}
                            </div>
                        </div>
                        <div style="font-size:13px; font-weight:800; font-family:ui-monospace,'Courier New',monospace; color:var(--rd-accent-bold); white-space:nowrap;">${pmsMoney(s.split_amount)}</div>
                        <div style="display:flex; gap:6px;">
                            <button class="v-btn outline" onclick="rdPayPrintSplit(${s.id})" style="padding:6px 12px; border-radius:8px; font-size:11px;">In</button>
                            ${!printed ? `<button class="v-btn outline" onclick="rdPayDeleteSplit(${s.id})" style="padding:6px 12px; border-radius:8px; font-size:11px; color:#dc2626; border-color:#fecaca;">Xoá</button>` : ''}
                        </div>
                    </div>`;
                }).join('')}
            </div>
            <div style="font-size:11px; color:#64748b; margin-top:6px; padding:4px 0;">
                Đã tách: <b style="color:var(--rd-accent-bold);">${pmsMoney(_rdSplitSummary.total_split)}</b> / ${pmsMoney(_rdSplitSummary.net_charge)}
                · Còn lại: <b style="color:var(--rd-accent-bold);">${pmsMoney(_rdSplitSummary.remaining)}</b>
            </div>
        `;
    } catch(e) {
        container.innerHTML = '';
        container.style.display = 'none';
    }
}

function rdPayPrintSplit(splitId) {
    if (!rdCurrentFolio?.id) return;
    window.open(`/api/pms/folio/${rdCurrentFolio.id}/splits/${splitId}/print`, '_blank');
    setTimeout(() => rdPayLoadSplits(), 1500);
}

async function rdPayDeleteSplit(splitId) {
    if (!rdCurrentFolio?.id) return;
    if (!confirm('Xoá hoá đơn tách này?')) return;
    try {
        await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/splits/${splitId}`, { method: 'DELETE' });
        pmsToast('Đã xoá hoá đơn tách', true);
        rdPayLoadSplits();
    } catch(e) { pmsToast('Lỗi: ' + e.message, false); }
}

function rdPayOpenMergeFolio() {
    if (rdCurrentFolios.length <= 1) return;
    const modal = document.getElementById('rd-sub-modal-folio-merge');
    if (!modal) return;
    const sourceSel = document.getElementById('rd-folio-merge-source');
    const targetSel = document.getElementById('rd-folio-merge-target');
    sourceSel.innerHTML = rdCurrentFolios.map((f, i) => i === 0 ? '' : `<option value="${i}">${f.notes || ('Hóa đơn ' + (i+1))} (${pmsMoney(f.balance || 0)})</option>`).join('');
    targetSel.innerHTML = rdCurrentFolios.map((f, i) => `<option value="${i}">${f.notes || ('Hóa đơn ' + (i+1))} (${pmsMoney(f.balance || 0)})</option>`).join('');
    modal.style.display = 'flex';
}

async function rdPaySubmitMergeFolio() {
    const sIdx = parseInt(document.getElementById('rd-folio-merge-source').value);
    const tIdx = parseInt(document.getElementById('rd-folio-merge-target').value);
    if (sIdx === tIdx) return pmsToast('Không thể gộp vào chính nó', false);
    try {
        await pmsApi(`/api/pms/folio/${rdCurrentFolios[tIdx].id}/merge?source_folio_id=${rdCurrentFolios[sIdx].id}`, { method: 'POST' });
        pmsToast('Gộp Hóa đơn thành công', true);
        document.getElementById('rd-sub-modal-folio-merge').style.display = 'none';
        rdActiveFolioIndex = tIdx; 
        fetchFolio(rdStayData.id);
    } catch(e) { pmsToast('Lỗi gộp bill: ' + e.message, false); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Transfer Transaction
// ─────────────────────────────────────────────────────────────────────────────
function rdPayTransferTx(txId) {
    if (rdCurrentFolios.length <= 1) return;
    const modal = document.getElementById('rd-sub-modal-folio-transfer');
    if (!modal) return;
    document.getElementById('rd-folio-transfer-tx-id').value = txId;
    const targetSel = document.getElementById('rd-folio-transfer-target');
    targetSel.innerHTML = rdCurrentFolios.map((f, i) => i === rdActiveFolioIndex ? '' : `<option value="${i}">${f.notes || ('Hóa đơn ' + (i+1))}</option>`).join('');
    modal.style.display = 'flex';
}

async function rdPaySubmitTransferTx() {
    const txId = document.getElementById('rd-folio-transfer-tx-id').value;
    const tIdx = parseInt(document.getElementById('rd-folio-transfer-target').value);
    if (isNaN(tIdx)) return pmsToast('Vui lòng chọn hóa đơn đích', false);
    try {
        await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/transfer?target_folio_id=${rdCurrentFolios[tIdx].id}&tx_ids=${txId}`, {method: 'POST'});
        pmsToast('Chuyển bill thành công', true);
        document.getElementById('rd-sub-modal-folio-transfer').style.display = 'none';
        fetchFolio(rdStayData.id);
    } catch(e) { pmsToast('Lỗi: ' + e.message, false); }
}

function rdPaySelectFolio(index) {
    rdActiveFolioIndex = index;
    if (rdPaymentState?.folios?.[index]) {
        rdCurrentFolio = rdPaymentState.folios[index];
    } else {
        rdCurrentFolio = rdCurrentFolios[index];
    }
    if (typeof pmsRdRenderFolioTabs === 'function') pmsRdRenderFolioTabs();
    if (typeof pmsRdRenderFolio === 'function') pmsRdRenderFolio();
    if (typeof rdPayLoadSplits === 'function') rdPayLoadSplits();
}

let _rdInvoiceGuests = [];

async function rdPayPrintFolio() {
    if (!rdCurrentFolio) return;
    try {
        const resp = await fetch(`/api/pms/folio/${rdCurrentFolio.id}/invoice-info`);
        if (!resp.ok) throw new Error(resp.status);
        const data = await resp.json();
        const info = data.selected || {};
        _rdInvoiceGuests = data.guests || [];

        // If folio already has structured invoice info (from split bill), print directly
        if (rdCurrentFolio.invoice_tax_code) {
            window.open(`/api/pms/folio/${rdCurrentFolio.id}/print`, '_blank', 'width=850,height=900,scrollbars=yes');
            return;
        }

        // Render guest dropdown
        const selectEl = document.getElementById('rd-invoice-print-guest');
        if (selectEl) {
            let opts = '';
            if (_rdInvoiceGuests.length > 1) {
                _rdInvoiceGuests.forEach((g, i) => {
                    opts += `<option value="${i}">${g.full_name} — ${g.company_name || g.tax_code}</option>`;
                });
                opts += '<option value="manual">Nhập thủ công</option>';
                selectEl.innerHTML = opts;
                selectEl.closest('.rd-sm-input-grp').style.display = '';
                // Pre-fill from first guest in list
                const firstGuest = _rdInvoiceGuests[0];
                document.getElementById('rd-invoice-print-company').value = firstGuest.company_name || '';
                document.getElementById('rd-invoice-print-tax-code').value = firstGuest.tax_code || '';
                document.getElementById('rd-invoice-print-address').value = firstGuest.company_address || '';
                document.getElementById('rd-invoice-print-contact').value = firstGuest.invoice_contact || '';
            } else {
                selectEl.closest('.rd-sm-input-grp').style.display = 'none';
                document.getElementById('rd-invoice-print-company').value = info.company_name || '';
                document.getElementById('rd-invoice-print-tax-code').value = info.tax_code || '';
                document.getElementById('rd-invoice-print-address').value = info.company_address || '';
                document.getElementById('rd-invoice-print-contact').value = info.contact || '';
            }
        } else {
            document.getElementById('rd-invoice-print-company').value = info.company_name || '';
            document.getElementById('rd-invoice-print-tax-code').value = info.tax_code || '';
            document.getElementById('rd-invoice-print-address').value = info.company_address || '';
            document.getElementById('rd-invoice-print-contact').value = info.contact || '';
        }

        document.getElementById('rd-sub-modal-invoice-print').style.display = 'flex';
    } catch (e) {
        window.open(`/api/pms/folio/${rdCurrentFolio.id}/print`, '_blank', 'width=850,height=900,scrollbars=yes');
    }
}

function rdInvoicePrintGuestChange(selectEl) {
    const val = selectEl.value;
    if (val === 'manual') return;
    const g = _rdInvoiceGuests[parseInt(val)];
    if (!g) return;
    document.getElementById('rd-invoice-print-company').value = g.company_name || '';
    document.getElementById('rd-invoice-print-tax-code').value = g.tax_code || '';
    document.getElementById('rd-invoice-print-address').value = g.company_address || '';
    document.getElementById('rd-invoice-print-contact').value = g.invoice_contact || '';
}

function rdInvoicePrintConfirm() {
    if (!rdCurrentFolio) return;
    const params = new URLSearchParams({
        invoice_company: document.getElementById('rd-invoice-print-company').value.trim(),
        invoice_tax_code: document.getElementById('rd-invoice-print-tax-code').value.trim(),
        invoice_address: document.getElementById('rd-invoice-print-address').value.trim(),
        invoice_contact: document.getElementById('rd-invoice-print-contact').value.trim(),
    });
    document.getElementById('rd-sub-modal-invoice-print').style.display = 'none';
    window.open(`/api/pms/folio/${rdCurrentFolio.id}/print?${params.toString()}`, '_blank', 'width=850,height=900,scrollbars=yes');
}

function rdInvoicePrintSkip() {
    if (!rdCurrentFolio) return;
    document.getElementById('rd-sub-modal-invoice-print').style.display = 'none';
    window.open(`/api/pms/folio/${rdCurrentFolio.id}/print`, '_blank', 'width=850,height=900,scrollbars=yes');
}

// ─────────────────────────────────────────────────────────────────────────────
// Render Folio Dashboard + Ledger (Backend-first)
// ─────────────────────────────────────────────────────────────────────────────
const RD_PAY_ROOM_TYPES = ['ROOM_CHARGE', 'HOURLY_CHARGE', 'EARLY_CHECKIN_FEE', 'LATE_CHECKOUT_FEE'];

function rdPayNum(value) {
    const n = parseFloat(value);
    return Number.isFinite(n) ? n : 0;
}

function rdPayIsRoomCharge(t) {
    return RD_PAY_ROOM_TYPES.includes(t?.type || t?.transaction_type);
}

function rdPayPreviewRoomCharge() {
    const ps = rdPaymentState || {};
    const direct = rdPayNum(ps.room_charge);
    if (direct > 0) return direct;

    const breakdownRoom = (ps.breakdown || [])
        .filter(b => RD_PAY_ROOM_TYPES.includes(b.type))
        .reduce((acc, b) => acc + rdPayNum(b.amount), 0);
    if (breakdownRoom > 0) return breakdownRoom;

    const net = rdPayNum(ps.total_charge || ps.net_charge || ps.final_total);
    const existing = rdPayNum(ps.existing_charges)
        || (rdPayNum(ps.existing_service_charges) + rdPayNum(ps.existing_surcharge_charges));
    return Math.max(0, net - existing);
}

function rdPayBuildVirtualRoomTxs(roomFallback) {
    const ps = rdPaymentState || {};
    const breakdownRows = (ps.breakdown || [])
        .filter(b => RD_PAY_ROOM_TYPES.includes(b.type) && rdPayNum(b.amount) > 0);

    if (breakdownRows.length) {
        return breakdownRows.map((b, idx) => ({
            id: `virtual-room-${b.type || 'ROOM_CHARGE'}-${idx}`,
            category: 'ROOM',
            transaction_type: b.type || 'ROOM_CHARGE',
            description: b.description || 'Tiền phòng',
            amount: rdPayNum(b.amount),
            quantity: b.hours || b.days || 1,
            created_at: ps.check_out_at || rdStayData?.check_out_at || rdStayData?.check_in_at || new Date().toISOString(),
            created_by_name: 'Tạm tính',
            is_virtual: true,
            is_voided: false,
        }));
    }

    if (roomFallback > 0) {
        return [{
            id: 'virtual-room-charge',
            category: 'ROOM',
            transaction_type: 'ROOM_CHARGE',
            description: 'Tiền phòng',
            amount: roomFallback,
            quantity: 1,
            created_at: ps.check_out_at || rdStayData?.check_out_at || rdStayData?.check_in_at || new Date().toISOString(),
            created_by_name: 'Tạm tính',
            is_virtual: true,
            is_voided: false,
        }];
    }

    return [];
}

function pmsRdRenderFolio() {
    if (!rdCurrentFolio) {
        const ledgerBody = document.getElementById('rd-pay-ledger-body');
        if (ledgerBody) ledgerBody.innerHTML = `<div style="padding:40px; color:#94a3b8; font-size:14px; text-align:center; font-style:italic;">Đang tải dữ liệu...</div>`;
        const timeline = document.getElementById('rd-pay-timeline');
        if (timeline) timeline.innerHTML = '';
        const btnCO = document.getElementById('rd-pay-checkout-btn');
        if (btnCO) { btnCO.disabled = true; btnCO.style.opacity = '0.65'; }
        return;
    }

    const folioData = rdCurrentFolio;
    const txs = folioData.transactions || [];
    const previewRoomCharge = rdPayPreviewRoomCharge();
    const hasRoomTx = txs.some(t => !t.is_voided && rdPayIsRoomCharge(t) && rdPayNum(t.amount) > 0);
    const roomVirtualTxs = hasRoomTx ? [] : rdPayBuildVirtualRoomTxs(previewRoomCharge);
    
    // Transactions đã bao gồm cả virtual charges (từ rd_modal.js fetchFolio)
    // Xây dựng danh sách transactions đầy đủ
    const allTxs = [...roomVirtualTxs, ...txs];

    // Tính toán từ transactions trực tiếp (Backend-first principle)
    const validTxs = allTxs.filter(t => !t.is_voided);
    const hasLedgerRows = validTxs.length > 0;
    
    const chargesFromTx = validTxs
        .filter(t => rdPayNum(t.amount) > 0 && !['REFUND', 'REFUND_PAYMENT'].includes(t.type || t.transaction_type))
        .reduce((acc, t) => acc + rdPayNum(t.amount), 0);
    const discountsFromTx = validTxs
        .filter(t => t.category === 'DISCOUNT')
        .reduce((acc, t) => acc + Math.abs(rdPayNum(t.amount)), 0);
    const paymentsFromTx = validTxs
        .filter(t => rdPayNum(t.amount) < 0 && ['PAYMENT', 'DEBT_PAYMENT', 'DEPOSIT_USED'].includes(t.type || t.transaction_type))
        .reduce((acc, t) => acc + Math.abs(rdPayNum(t.amount)), 0);
    const hasPreviewBalance = rdPaymentState
        && rdPaymentState.projected_balance !== undefined
        && rdPaymentState.projected_balance !== null
        && rdPaymentState.projected_balance !== '';
    const previewGrossCharge = rdPayNum(rdPaymentState?.room_charge)
        + rdPayNum(rdPaymentState?.existing_charges)
        + rdPayNum(rdPaymentState?.extra_charge);
    const previewDiscount = rdPayNum(rdPaymentState?.total_discounts || rdPaymentState?.existing_discounts || rdPaymentState?.discount);
    const previewPaid = rdPayNum(rdPaymentState?.total_paid)
        || (rdPayNum(rdPaymentState?.effective_paid) + rdPayNum(rdPaymentState?.deposit_used));

    const discounts = previewDiscount > 0 ? previewDiscount : (hasLedgerRows ? discountsFromTx : rdPayNum(folioData.total_discount));
    const payments = previewPaid > 0 ? previewPaid : (hasLedgerRows ? paymentsFromTx : rdPayNum(folioData.total_paid));

    // Phân tách breakdown dựa trên transaction_type
    // ROOM_CHARGE, HOURLY_CHARGE, EARLY_CHECKIN_FEE, LATE_CHECKOUT_FEE → Tiền phòng
    // SERVICE → Dịch vụ
    // SURCHARGE, OTHER (thủ công) → Phát sinh
    let roomTot = 0, servTot = 0, surchargeTot = 0;
    const isRoomCharge = rdPayIsRoomCharge;
    validTxs.forEach(t => {
        if (rdPayNum(t.amount) < 0) return;
        if (['REFUND', 'REFUND_PAYMENT'].includes(t.type || t.transaction_type)) return;
        if (isRoomCharge(t)) roomTot += rdPayNum(t.amount);
        else if (t.category === 'SERVICE') servTot += rdPayNum(t.amount);
        else if (t.category === 'SURCHARGE' || t.category === 'OTHER') surchargeTot += rdPayNum(t.amount);
        else roomTot += rdPayNum(t.amount); // fallback
    });
    if (previewRoomCharge > 0) {
        roomTot = previewRoomCharge;
    } else if (!hasLedgerRows) {
        roomTot = rdPayNum(folioData.total_charge);
    }
    if (rdPaymentState) {
        const previewRoom = rdPayNum(rdPaymentState.room_charge);
        const previewService = rdPayNum(rdPaymentState.existing_service_charges);
        const previewSurcharge = rdPayNum(rdPaymentState.existing_surcharge_charges);
        if (previewRoom > 0) roomTot = previewRoom;
        if (previewService > 0) servTot = previewService;
        if (previewSurcharge > 0) surchargeTot = previewSurcharge;
    }
    const componentCharge = roomTot + servTot + surchargeTot;
    const charges = previewGrossCharge > 0
        ? previewGrossCharge
        : componentCharge > 0
        ? componentCharge
        : (hasLedgerRows ? chargesFromTx : rdPayNum(folioData.total_charge));
    const netCharge = charges - discounts;
    const balance = hasPreviewBalance ? rdPayNum(rdPaymentState.projected_balance) : (netCharge - payments);

    // ── 1. DASHBOARD ──────────────────────────────────────────────
    const elRoom = document.getElementById('rd-pay-dash-room');
    const elServ = document.getElementById('rd-pay-dash-service');
    const elExtra = document.getElementById('rd-pay-dash-extra');
    const elPaid = document.getElementById('rd-pay-dash-paid');
    const elDisc = document.getElementById('rd-pay-dash-discount');
    const elBal = document.getElementById('rd-pay-dash-balance');

    if (elRoom) elRoom.textContent = pmsMoney(roomTot);
    if (elServ) elServ.textContent = pmsMoney(servTot);
    if (elExtra) elExtra.textContent = pmsMoney(surchargeTot);
    if (elDisc) elDisc.textContent = pmsMoney(discounts);
    if (elPaid) elPaid.textContent = pmsMoney(payments);

    if (elBal) {
        const balCard = elBal.closest('.chk-dash-card-v3');
        const balLabel = balCard ? balCard.querySelector('.lbl') : null;
        if (balance < 0) {
            elBal.textContent = `-${pmsMoney(Math.abs(balance))}`;
            elBal.style.color = '#6ee7b7';
            if (balLabel) balLabel.textContent = 'KHÁCH DƯ';
            if (balCard) balCard.style.background = 'linear-gradient(135deg, #065f46 0%, #047857 100%)';
        } else if (balance === 0) {
            elBal.textContent = pmsMoney(0);
            elBal.style.color = '#6ee7b7';
            if (balLabel) balLabel.textContent = 'ĐÃ TẤT TOÁN';
            if (balCard) balCard.style.background = '';
        } else {
            elBal.textContent = pmsMoney(balance);
            elBal.style.color = '#fbbf24';
            if (balLabel) balLabel.textContent = 'CẦN THU THÊM';
            if (balCard) balCard.style.background = '';
        }
    }

    const btnCO = document.getElementById('rd-pay-checkout-btn');
    if (btnCO) {
        if (rdIsCheckedOut) {
            btnCO.disabled = true;
            btnCO.style.display = 'none';
        } else {
            btnCO.disabled = false;
            btnCO.style.display = '';
            btnCO.style.opacity = '';
            btnCO.style.cursor = '';
            btnCO.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg> Trả phòng`;
        }
    }

    // ── 2. LEDGER ────────────────────────────────────────────────
    const ledgerBody = document.getElementById('rd-pay-ledger-body');
    if (!ledgerBody) return;

    const getLgIcon = (cat, type) => {
        if (cat === 'ROOM') return `<div class="chk-ledger-icon" style="background:#EBF4F6; color:#088395;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 7V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2M3 19v-7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7M11 10V7M13 10V7M3 14h18"/></svg></div>`;
        if (cat === 'SURCHARGE' || cat === 'OTHER') return `<div class="chk-ledger-icon" style="background:#c8dcdc; color:#4a5568;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg></div>`;
        if (cat === 'DISCOUNT') return `<div class="chk-ledger-icon" style="background:#EBF4F6; color:#088395;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg></div>`;
        if (['REFUND', 'REFUND_PAYMENT'].includes(type)) return `<div class="chk-ledger-icon" style="background:#7ab2b2; color:#059669;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg></div>`;
        if (type === 'PAYMENT' || type === 'DEBT_PAYMENT') return `<div class="chk-ledger-icon" style="background:#ecfdf5; color:#059669;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg></div>`;
        if (type === 'DEPOSIT_USED') return `<div class="chk-ledger-icon" style="background:#fef3c7; color:#d97706;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><circle cx="12" cy="12" r="2"/></svg></div>`;
        return `<div class="chk-ledger-icon" style="background:#c8dcdc; color:#4a5568;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg></div>`;
    };

    // Ledger transactions (bao gồm DEPOSIT_USED để hiển thị tiền cọc)
    const ledgerTxs = validTxs;

    // Helper lấy nhãn và class cho loại giao dịch
    const getTxTypeBadge = (t) => {
        const isRoomTx = isRoomCharge(t);
        const isPayment = ['PAYMENT', 'DEBT_PAYMENT', 'REFUND', 'REFUND_PAYMENT'].includes(t.type || t.transaction_type);
        const isDepositUsed = t.type === 'DEPOSIT_USED' || t.transaction_type === 'DEPOSIT_USED';
        if (isDepositUsed) return { label: 'Cọc', cls: 'chk-ledger-type deposit' };
        if (isPayment) return { label: 'Thanh toán', cls: 'chk-ledger-type_thanhtoan' };
        if (isRoomTx) return { label: 'Tiền phòng', cls: 'chk-ledger-type phong' };
        if (t.category === 'SERVICE') return { label: 'Dịch vụ', cls: 'chk-ledger-type dichvu' };
        if (t.category === 'SURCHARGE' || t.category === 'OTHER') return { label: 'Phát sinh', cls: 'chk-ledger-type phatsinh' };
        if (t.category === 'DISCOUNT') return { label: 'Giảm giá', cls: 'chk-ledger-type giamgia' };
        return { label: 'Khác', cls: 'chk-ledger-type phatsinh' };
    };
    
    if (ledgerTxs.length === 0) {
        ledgerBody.innerHTML = `<div style="padding:40px; color:#94a3b8; font-size:14px; text-align:center; font-style:italic;">Hóa đơn trống.</div>`;
    } else {
        const sortedTxs = typeof rdSortLedgerTransactions === 'function'
            ? rdSortLedgerTransactions(ledgerTxs)
            : [...ledgerTxs].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));

        const hasMultipleFolios = rdCurrentFolios && rdCurrentFolios.length > 1;
        let html = '';
        sortedTxs.forEach(t => {
            const isDisc = t.category === 'DISCOUNT';
            const txType = t.type || t.transaction_type;
            const isPayment = ['PAYMENT', 'DEBT_PAYMENT', 'REFUND', 'REFUND_PAYMENT'].includes(txType);
            const isDepositUsed = (t.type || t.transaction_type) === 'DEPOSIT_USED';
            const isTransferTarget = !t.is_voided && t.reference_type === 'room_bill_transfer' && txType === 'SURCHARGE';
            const isTransferSource = !t.is_voided && t.reference_type === 'room_bill_transfer' && txType === 'DISCOUNT_MANUAL';
            const txAmount = rdPayNum(t.amount);
            const amtStr = (isPayment || isDepositUsed) ? `-${pmsMoney(Math.abs(txAmount))}` : (isDisc ? `-${pmsMoney(Math.abs(txAmount))}` : pmsMoney(txAmount));
            const iconHtml = getLgIcon(t.category, txType);
            const rowClass = (isPayment || isDepositUsed) ? 'style="background:#f0fdf4;"' : '';
            const amountClass = (isPayment || isDepositUsed) ? 'style="color:#059669;"' : (isDisc ? 'class="discount"' : '');
            const canVoid = !rdIsCheckedOut && !t.is_virtual && !isPayment && !isDepositUsed && !isTransferTarget && !isTransferSource;
            const isRoomTx = isRoomCharge(t);
            const descName = t.description || (isRoomTx ? 'Tiền phòng' : (isPayment ? 'Thanh toán' : (t.category === 'SERVICE' ? 'Dịch vụ' : 'Phí phát sinh')));
            const typeBadge = getTxTypeBadge(t);
            html += `<div class="chk-ledger-row" ${rowClass}>
                <div class="chk-ledger-info">${iconHtml}
                        <div class="chk-ledger-text">
                        <span class="chk-ledger-name">${pmsEscapeHtml(descName)}</span>
                            <span class="chk-ledger-sub">${pmsFdt(t.created_at)}</span>
                        </div>
                    </div>
                    <div class="chk-ledger-qty">x${t.quantity || 1}</div>
                    <div class="chk-ledger-actions">
                    ${isTransferTarget ? `<div class="chk-ledger-btn" title="Hủy gộp" onclick="rdPayUndoTransfer(${t.id})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg></div>` : ''}
                    ${hasMultipleFolios && canVoid ? `<div class="chk-ledger-btn" title="Chuyển bill" onclick="rdPayTransferTx('${t.id}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 10 20 15 15 20"/><path d="M4 4v7a4 4 0 0 0 4 4h12"/></svg></div>` : ''}
                    ${canVoid ? `<div class="chk-ledger-btn void" title="Xóa bỏ" onclick="rdPayVoidTx('${t.id}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></div>` : ''}
                            </div>
                <div class="chk-ledger-type-cell">
                    <span class="${typeBadge.cls}">${typeBadge.label}</span>
                </div>
                <div class="chk-ledger-amount" ${amountClass}>${amtStr}</div>
            </div>`;
        });
        ledgerBody.innerHTML = html;
    }

    // ── 3. TIMELINE ──────────────────────────────────────────────
    const elTimeline = document.getElementById('rd-pay-timeline');
    const auditEvents = allTxs.flatMap(t => {
        const events = [{ ...t, audit_action: 'created', audit_at: t.created_at }];
        if (t.is_voided) {
            events.push({ ...t, audit_action: 'voided', audit_at: t.void_at || t.created_at });
        }
        return events;
    });
    const tlTxs = auditEvents.sort((a, b) => {
        const da = new Date(a.audit_at || a.created_at || 0).getTime() || 0;
        const db = new Date(b.audit_at || b.created_at || 0).getTime() || 0;
        if (da !== db) return da - db;
        const typeOrder = {
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
        const aType = a.type || a.transaction_type;
        const bType = b.type || b.transaction_type;
        const priorityDiff = (typeOrder[aType] || 99) - (typeOrder[bType] || 99);
        if (priorityDiff !== 0) return priorityDiff;
        if (a.audit_action !== b.audit_action) return a.audit_action === 'created' ? -1 : 1;
        return String(a.id || '').localeCompare(String(b.id || ''));
    });
    
    if (tlTxs.length === 0) {
        elTimeline.innerHTML = `<div style="color:#94a3b8; font-size:13px; font-style:italic; padding:16px;">Chưa có lịch sử.</div>`;
    } else {
        let tlHtml = '';
        tlTxs.forEach(t => {
            const isRoomTx = isRoomCharge(t);
            let dotCls = t.audit_action === 'voided'
                ? 'voided'
                : (isRoomTx ? 'room' : (['SERVICE', 'OTHER'].includes(t.category) ? 'service' : (t.category === 'DISCOUNT' ? 'discount' : (['PAYMENT', 'DEBT_PAYMENT', 'DEPOSIT_USED'].includes(t.type || t.transaction_type) ? 'payment' : 'room'))));
            
            const txAmount = rdPayNum(t.amount);
            const amtPrefix = txAmount < 0 ? '' : '+';
            const amtCls = txAmount < 0 ? 'negative' : 'positive';
            const actorName = isRoomTx
                ? 'Hệ thống'
                : t.is_virtual
                ? 'Tạm tính'
                : (t.audit_action === 'voided'
                    ? (t.void_by_name || (t.void_by ? `User #${t.void_by}` : 'Hệ thống'))
                    : (t.created_by_name || (t.created_by ? `User #${t.created_by}` : 'Hệ thống')));
            const actionLabel = t.description || t.type || t.transaction_type;
            const amountText = t.audit_action === 'voided'
                ? `${amtPrefix}${pmsMoney(txAmount)}`
                : `${amtPrefix}${pmsMoney(txAmount)}`;
            tlHtml += `<div class="chk-tl-item ${t.audit_action === 'voided' ? 'is-voided' : ''}">
                    <div class="chk-tl-dot ${dotCls}"></div>
                    <div class="chk-tl-content">
                        <div class="chk-tl-head">
                            <span style="font-weight:600; color:#334155;">${pmsEscapeHtml(actorName)}</span>
                            <span style="color:#94a3b8;">${pmsFdt(t.audit_at || t.created_at)}</span>
                        </div>
                        <div class="chk-tl-body" style="display:flex; justify-content:space-between; margin-top:4px; align-items:center;">
                        <span style="flex:1;">${pmsEscapeHtml(actionLabel)}</span>
                            <span class="chk-tl-amt ${amtCls}" style="font-family:'Courier New', Courier, monospace; ${t.audit_action === 'voided' ? 'text-decoration:line-through; color:#64748b;' : ''}">${amountText}</span>
                    </div>
                </div>
            </div>`;
        });
        elTimeline.innerHTML = tlHtml;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Folio Action APIs
// ─────────────────────────────────────────────────────────────────────────────
async function rdPayAddCharge(txType, amount, qty, desc) {
    if (!rdCurrentFolio) return;
    if (typeof rdSetBusy === 'function') rdSetBusy(true, 'Đang cập nhật hoá đơn...');
    try {
        const url = `/api/pms/folio/${rdCurrentFolio.id}/charge?transaction_type=${encodeURIComponent(txType)}&amount=${amount}&quantity=${qty}&description=${encodeURIComponent(desc)}`;
        await pmsApi(url, { method: 'POST' });
        pmsToast('Đã thêm phí vào hoá đơn', true);
        const stayId = rdCurrentFolio.stay_id || rdStayData?.id;
        if (stayId) {
            await fetchFolio(stayId);
            if (typeof rdRenderRoomInfoCard === 'function') await rdRenderRoomInfoCard({ force: true });
        }
    } catch (e) { pmsToast('Lỗi thêm phí: ' + e.message, false); }
    finally {
        if (typeof rdSetBusy === 'function') rdSetBusy(false);
    }
}

async function rdPaySubmitDiscount() {
    if (!rdCurrentFolio) return;
    const val = pmsParseCurrency(document.getElementById('rd-pay-discount-input').value || '0');
    if (val <= 0) return;
    const desc = document.getElementById('rd-pay-discount-reason').value || 'Giảm giá';
    if (typeof rdSetBusy === 'function') rdSetBusy(true, 'Đang áp dụng giảm giá...');
    try {
        const url = `/api/pms/folio/${rdCurrentFolio.id}/discount?transaction_type=DISCOUNT_MANUAL&amount=${val}&description=${encodeURIComponent(desc)}`;
        await pmsApi(url, { method: 'POST' });
        document.getElementById('rd-sub-modal-discount').style.display = 'none';
        document.getElementById('rd-pay-discount-input').value = '';
        document.getElementById('rd-pay-discount-reason').value = '';
        pmsToast('Áp dụng giảm giá thành công', true);
        const stayId = rdCurrentFolio.stay_id || rdStayData?.id;
        if (stayId) {
            await fetchFolio(stayId);
            if (typeof rdRenderRoomInfoCard === 'function') await rdRenderRoomInfoCard({ force: true });
        }
    } catch(e) { pmsToast(e.message, false); }
    finally {
        if (typeof rdSetBusy === 'function') rdSetBusy(false);
    }
}

async function rdPaySubmitRecord() {
    if (!rdCurrentFolio) return;
    const val = pmsParseCurrency(document.getElementById('rd-pay-record-input').value || '0');
    if (val <= 0) return;
    let method = 'CASH';
    document.getElementsByName('rd-pay-method').forEach(el => { if (el.checked) method = el.value; });
    if (typeof rdSetBusy === 'function') rdSetBusy(true, 'Đang ghi nhận thanh toán...');
    try {
        const url = `/api/pms/folio/${rdCurrentFolio.id}/payment?amount=${val}&method=${encodeURIComponent(method)}`;
        await pmsApi(url, { method: 'POST' });
        document.getElementById('rd-sub-modal-payment').style.display = 'none';
        document.getElementById('rd-pay-record-input').value = '';
        pmsToast('Ghi nhận thanh toán thành công', true);
        const stayId = rdCurrentFolio.stay_id || rdStayData?.id;
        if (stayId) {
            await fetchFolio(stayId);
            if (typeof rdRenderRoomInfoCard === 'function') await rdRenderRoomInfoCard({ force: true });
        }
    } catch(e) { pmsToast(e.message, false); }
    finally {
        if (typeof rdSetBusy === 'function') rdSetBusy(false);
    }
}

async function rdPayVoidTx(txId) {
    if (!rdCurrentFolio) return;
    if (!confirm('Xoá mềm dòng này khỏi hoá đơn? Dòng audit vẫn được giữ lại để truy vết.')) return;
    try {
        const resp = await pmsApi(`/api/pms/folio/${rdCurrentFolio.id}/void/${txId}?reason=${encodeURIComponent('Xoá mềm từ tab Thanh toán')}`, { method: 'POST' });
        if (resp?.transaction && typeof rdMergeTransactionUpdate === 'function') rdMergeTransactionUpdate(resp.transaction);
        pmsToast('Đã xoá mềm dòng phí', true);
        const stayId = rdCurrentFolio.stay_id || rdStayData?.id;
        if (stayId) {
            await fetchFolio(stayId);
            if (typeof rdLoadPayment === 'function') rdLoadPayment();
        }
    } catch(e) { pmsToast(e.message, false); }
}

async function rdPayUndoTransfer(txId) {
    if (!confirm('Hủy gộp hoá đơn này? Cả hai phòng sẽ được hoàn lại số tiền đã gộp.')) return;
    try {
        const resp = await pmsApi(`/api/pms/checkout/transfer/${txId}/undo`, { method: 'POST' });
        pmsToast(resp?.message || 'Đã hủy gộp hoá đơn', true);
        rdResetPaymentRenderCache();
        rdFolioLoaded = false;
        const stayId = rdStayData?.id;
        if (stayId) {
            await fetchFolio(stayId);
            if (typeof rdLoadPayment === 'function') rdLoadPayment();
        }
    } catch (e) {
        pmsToast(e.message || 'Không thể hủy gộp hoá đơn', false);
    }
}

function rdPayOpenPopup(popupId) {
    const popup = document.getElementById(popupId);
    if (!popup) return;
    ['rd-sub-modal-discount', 'rd-sub-modal-payment', 'rd-sub-modal-refund'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    popup.style.display = 'flex';

    if (popupId === 'rd-sub-modal-refund') {
        // Tính balance để hiển thị số tiền hoàn
        const bal = typeof rdCalculateFolioBalance === 'function'
            ? rdCalculateFolioBalance(rdCurrentFolio)
            : rdPayNum(rdCurrentFolio?.balance);
        const amtDisplay = document.getElementById('rd-refund-amount-display');
        if (amtDisplay) amtDisplay.textContent = pmsMoney(Math.max(0, Math.abs(bal < 0 ? bal : 0)));
        return;
    }

    const input = popup.querySelector('input[type="text"]');
    if (input) {
        const bal = typeof rdCalculateFolioBalance === 'function'
            ? rdCalculateFolioBalance(rdCurrentFolio)
            : rdPayNum(rdCurrentFolio?.balance);
        if (popupId === 'rd-sub-modal-payment' && bal > 0) {
            input.value = pmsMoney(bal).replace(' VNĐ', '');
        }
        setTimeout(() => input.focus(), 100);
    }
}

document.addEventListener('change', function(e) {
    if (e.target.name === 'rd-pay-method') {
        const alertEl = document.getElementById('rd-pay-method-alert-text');
        if (!alertEl) return;
        const map = { 'CASH': 'CASH - Tiền mặt', 'BANK_TRANSFER': 'BANK_TRANSFER - Chuyển khoản ngân hàng', 'CREDIT_CARD': 'CREDIT_CARD - Cà Thẻ / Tín dụng' };
        alertEl.textContent = map[e.target.value] || e.target.value;
    }
});

function pmsPayFormatCurrency(el) {
    if (!el) return;
    const val = pmsParseCurrency(el.value);
    el.value = val > 0 ? new Intl.NumberFormat('vi-VN').format(val) : '';
}

// ─────────────────────────────────────────────────────────────────────────────
// Refund APIs
// ─────────────────────────────────────────────────────────────────────────────
async function rdPayRequestRefund() {
    const folioId = rdCurrentFolio?.id;
    if (!folioId) return;
    const folioBalance = typeof rdCalculateFolioBalance === 'function'
        ? rdCalculateFolioBalance(rdCurrentFolio)
        : rdPayNum(rdCurrentFolio?.balance);
    if (folioBalance >= 0) return pmsToast('Không có tiền dư để hoàn', false);
    const overAmt = Math.abs(folioBalance);
    const method = document.getElementById('rd-refund-method')?.value || 'CASH';
    const account = document.getElementById('rd-refund-account')?.value || '';
    const note = document.getElementById('rd-refund-note')?.value || '';
    try {
        await pmsApi(`/api/pms/checkout/overpayment/${folioId}/refund?amount=${overAmt}&method=${encodeURIComponent(method)}&account=${encodeURIComponent(account)}&note=${encodeURIComponent(note)}`, {method:'POST'});
        pmsToast('Đã tạo yêu cầu hoàn tiền, chờ duyệt', true);
        document.getElementById('rd-sub-modal-refund').style.display = 'none';
        const stayId = rdCurrentFolio?.stay_id || rdStayData?.id;
        if (stayId) fetchFolio(stayId);
    } catch(e) { pmsToast(e.message || 'Lỗi hoàn tiền', false); }
}

async function rdPayApproveRefund(refundRecordId) {
    try {
        await pmsApi(`/api/pms/checkout/refund/${refundRecordId}/approve?note=`, {method:'POST'});
        pmsToast('Hoàn tiền thành công!', true);
        const stayId = rdCurrentFolio?.stay_id || rdStayData?.id;
        if (stayId) fetchFolio(stayId);
    } catch(e) { pmsToast(e.message || 'Lỗi duyệt hoàn tiền', false); }
}

// ─────────────────────────────────────────────────────────────────────────────
// SubmitCO - Checkout (sử dụng confirm() native)
// ─────────────────────────────────────────────────────────────────────────────
let pmsCheckoutSubmitting = false;

async function submitCO() {
    if (pmsCheckoutSubmitting) return;
    const id = document.getElementById('rd-stay-id').value;
    if (!id) return;
    const roomNum = document.getElementById('rd-room-num')?.textContent || '';

    // Đọc balance trực tiếp từ dashboard (đã tính sẵn) - NHANH
    const balanceLabel = document.getElementById('rd-pay-dash-balance')?.parentElement?.querySelector('.lbl')?.textContent || '';
    const balanceText = document.getElementById('rd-pay-dash-balance')?.textContent || '0';
    
    // Xác định trạng thái từ label đã hiển thị
    let balanceStatus = 'ĐÃ TẤT TOÁN';
    let balanceMsg = 'Đã thanh toán đủ';
    
    if (balanceLabel.includes('THU THÊM') || balanceLabel.includes('NỢ')) {
        balanceStatus = 'CÒN NỢ';
        balanceMsg = `Còn nợ: ${balanceText}`;
    } else if (balanceLabel.includes('DƯ')) {
        balanceStatus = 'KHÁCH DƯ';
        balanceMsg = `Khách dư: ${balanceText} (sẽ hoàn tiền)`;
    }

    // LUÔN hiện confirm dialog cho tất cả các trường hợp
    const confirmMsg = `XÁC NHẬN TRẢ PHÒNG — Phòng ${roomNum}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Trạng thái: ${balanceStatus}
💰 ${balanceMsg}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bạn có chắc chắn muốn trả phòng này không?`;

    if (!confirm(confirmMsg)) return;
    pmsCheckoutSubmitting = true;
    if (typeof rdSetBusy === 'function') rdSetBusy(true, 'Đang trả phòng...');
    const rdDialog = document.getElementById('rd-dialog');
    if (rdDialog) {
        rdDialog.classList.add('rd-busy');
        const busyText = document.getElementById('rd-modal-busy-text');
        if (busyText) busyText.textContent = 'Đang trả phòng...';
    }

    // Disable button + show loading state
    const btnCO = document.getElementById('rd-pay-checkout-btn');
    const originalBtnHTML = btnCO?.innerHTML || '';
    if (btnCO) {
        btnCO.disabled = true;
        btnCO.style.opacity = '0.65';
        btnCO.style.cursor = 'wait';
        btnCO.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; vertical-align:-3px; animation:rd-spin 1s linear infinite;"><circle cx="12" cy="12" r="10" stroke-opacity="0.3"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/></svg> Đang xử lý...`;
    }

    try {
        await new Promise(resolve => requestAnimationFrame(() => resolve()));
        const r = await pmsApi(`/api/pms/checkout/${id}`, { method: 'POST' });
        if (r.debt_status === 'checked_out_with_debt') pmsToast(`Đã checkout! Khách còn nợ: ${pmsMoney(r.debt_amount)}`, 'warning');
        else if (r.debt_status === 'checked_out_with_refund') pmsToast(`Đã checkout! Khách được hoàn: ${pmsMoney(r.refund_amount)}`, true);
        else pmsToast('Khách đã trả phòng thành công', true);
        if (typeof closeModal === 'function') closeModal('rdModal');
        else document.getElementById('rdModal')?.classList.remove('show');
        if (typeof pmsLoadRooms === 'function') await pmsLoadRooms(undefined, true);
    } catch (e) { pmsToast(e.message, false);
    } finally {
        pmsCheckoutSubmitting = false;
        if (typeof rdSetBusy === 'function') rdSetBusy(false);
        document.getElementById('rd-dialog')?.classList.remove('rd-busy');
        // Restore button state
        if (btnCO) {
            btnCO.disabled = false;
            btnCO.style.opacity = '';
            btnCO.style.cursor = '';
            btnCO.innerHTML = originalBtnHTML;
        }
    }
}

// Export globally
window.openCO = openCO;
window.submitCO = submitCO;
window.pmsRdRenderFolio = pmsRdRenderFolio;
window.rdPayOpenPopup = rdPayOpenPopup;
window.rdPaySubmitDiscount = rdPaySubmitDiscount;
window.rdPaySubmitRecord = rdPaySubmitRecord;
window.rdPayVoidTx = rdPayVoidTx;
window.rdPayUndoTransfer = rdPayUndoTransfer;
window.rdPayAddCharge = rdPayAddCharge;
window.pmsPayFormatCurrency = pmsPayFormatCurrency;
window.rdPayRequestRefund = rdPayRequestRefund;
window.rdPayApproveRefund = rdPayApproveRefund;
window.rdPayFetchBalance = rdPayFetchBalance;
window.rdPaySyncSplitBillGuest = rdPaySyncSplitBillGuest;
window.rdPayUpdateSplitSelectionTotal = rdPayUpdateSplitSelectionTotal;
window.rdPayValidateSplitAmount = rdPayValidateSplitAmount;
window.rdPaySubmitSplitInvoice = rdPaySubmitSplitInvoice;
window.rdPayLoadSplits = rdPayLoadSplits;
window.rdPayPrintSplit = rdPayPrintSplit;
window.rdPayDeleteSplit = rdPayDeleteSplit;
