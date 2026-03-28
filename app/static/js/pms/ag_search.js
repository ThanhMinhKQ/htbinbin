// static/js/pms/ag_search.js
// AG Modal — Search Old Guest & Fill From Existing
'use strict';

let agCurrentSearchResults = [];

function _agCloseSearchPopup() {
    const m = document.getElementById('ag-search-results-modal');
    if (m) {
        m.classList.remove('ci-show');
        setTimeout(() => m.remove(), 200);
    }
}
window._agCloseSearchPopup = _agCloseSearchPopup;

async function _agSelectGuest(idx) {
    const g = agCurrentSearchResults[idx];
    if (g) {
        await agFillGuestFromOld(g);
        _agCloseSearchPopup();
    }
}
window._agSelectGuest = _agSelectGuest;

async function agSearchOldGuest() {
    const cccd = document.getElementById('ag-cccd')?.value?.trim();
    if (!cccd || cccd.length < 3) { pmsToast('Vui lòng nhập ít nhất 3 ký tự để tìm kiếm', false); return; }
    try {
        const r = await pmsApi(`/api/pms/guests/search?cccd=${encodeURIComponent(cccd)}`);
        if (!r.guests || r.guests.length === 0) {
            alert(`⚠️ Không tìm thấy khách hàng nào với số giấy tờ "${cccd}".\n\nVui lòng kiểm tra lại số giấy tờ hoặc nhập thông tin khách mới.`);
            pmsToast(`Không tìm thấy khách với CCCD "${cccd}"`, false);
            return;
        }

        if (r.guests.length === 1) {
            await agFillGuestFromOld(r.guests[0]);
            return;
        }

        agCurrentSearchResults = r.guests;

        const resultsHtml = r.guests.map((g, idx) => {
            const initials = (g.full_name || '?').split(' ').map(w => w[0]).join('').slice(-2).toUpperCase();
            const genderColor = g.gender === 'Nam' ? '#3b82f6' : g.gender === 'Nữ' ? '#ec4899' : '#8b5cf6';
            const addressParts = [g.address, g.ward, g.city].filter(Boolean);
            const addressStr = addressParts.length > 0 ? addressParts.join(', ') : '—';

            return `
                <div class="ci-search-card" onclick="_agSelectGuest(${idx})" tabindex="0">
                    <div class="ci-search-avatar" style="background:linear-gradient(135deg, ${genderColor}, ${genderColor}dd);">
                        ${initials}
                    </div>
                    <div class="ci-search-info">
                        <div class="ci-search-name">${pmsEscapeHtml(g.full_name)}</div>
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

        const existing = document.getElementById('ag-search-results-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'ag-search-results-modal';
        modal.innerHTML = `
            <style>
                #ag-search-results-modal {
                    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(15, 23, 42, 0.6);
                    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
                    z-index: 10000;
                    display: flex; align-items: center; justify-content: center;
                    opacity: 0; transition: opacity 0.2s ease;
                }
                .ci-search-popup {
                    background: #fff; border-radius: 16px;
                    max-width: 520px; width: 92%; max-height: 70vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 25px 60px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.1);
                    transform: translateY(12px); transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                }
                #ag-search-results-modal.ci-show .ci-search-popup { transform: translateY(0); }
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
                        <h5>Tìm thấy ${r.guests.length} khách hàng</h5>
                        <p>Chọn khách hàng để điền thông tin vào form</p>
                    </div>
                    <button class="ci-search-close" onclick="_agCloseSearchPopup()" title="Đóng">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="ci-search-list">${resultsHtml}</div>
            </div>
        `;
        document.body.appendChild(modal);

        requestAnimationFrame(() => {
            modal.style.opacity = '1';
            modal.classList.add('ci-show');
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) _agCloseSearchPopup();
        });

        const escHandler = (e) => {
            if (e.key === 'Escape') {
                _agCloseSearchPopup();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

    } catch (e) {
        console.error('Error searching:', e);
        pmsToast('Lỗi tìm kiếm: ' + e.message, false);
    }
}
window.agSearchOldGuest = agSearchOldGuest;

async function agFillGuestFromOld(guest) {
    try {
        if (typeof guest === 'string') guest = JSON.parse(guest);
        _agIsOldGuest = true;

        // 0. Mark as trusted BEFORE filling (PMS_ADDR progressive normalization)
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.markAutofill) {
            PMS_ADDR.markAutofill();
        }

        // 1. Fill basic fields (sync - immediate, no loading)
        const idTypeEl = document.getElementById('ag-id-type');
        if (idTypeEl) idTypeEl.value = (guest.id_type || 'cccd').toLowerCase();
        const cccdEl = document.getElementById('ag-cccd');
        if (cccdEl) { cccdEl.value = guest.cccd || ''; cccdEl.readOnly = true; }
        document.getElementById('ag-name').value = guest.full_name || '';
        document.getElementById('ag-gender').value = guest.gender || '';
        document.getElementById('ag-phone').value = guest.phone || '';
        const vEl = document.getElementById('ag-vehicle');
        if (vEl) vEl.value = guest.vehicle || '';
        document.getElementById('ag-notes').value = guest.notes || '';
        document.getElementById('ag-address').value = guest.address || '';

        // Expiration check
        const idExpireEl = document.getElementById('ag-id-expire');
        if (idExpireEl) {
            idExpireEl.value = guest.id_expire || '';
            agCheckIdExpire(idExpireEl);
        }

        // Age check
        const birthEl = document.getElementById('ag-birth');
        if (birthEl) {
            birthEl.value = guest.birth_date ? String(guest.birth_date).slice(0, 10) : '';
            agCheckBirth(birthEl);
        }

        // Nationality
        const natEl = document.getElementById('ag-nationality');
        if (natEl) natEl.value = guest.nationality || 'VNM - Việt Nam';

        // Invoice fields
        if (guest.tax_code || guest.invoice_contact) {
            const invoiceRadio1 = document.querySelector('input[name="ag-invoice"][value="1"]');
            if (invoiceRadio1) { invoiceRadio1.checked = true; agToggleInvoice(invoiceRadio1); }
            const taxCodeEl = document.getElementById('ag-tax-code');
            if (taxCodeEl) taxCodeEl.value = guest.tax_code || '';
            const taxContactEl = document.getElementById('ag-tax-contact');
            if (taxContactEl) taxContactEl.value = guest.invoice_contact || '';
        } else {
            const invoiceRadio0 = document.querySelector('input[name="ag-invoice"][value="0"]');
            if (invoiceRadio0) { invoiceRadio0.checked = true; agToggleInvoice(invoiceRadio0); }
            const taxCodeEl = document.getElementById('ag-tax-code');
            if (taxCodeEl) taxCodeEl.value = '';
            const taxContactEl = document.getElementById('ag-tax-contact');
            if (taxContactEl) taxContactEl.value = '';
        }

        // 2. Address: detect mode (sync - no loading needed)
        const hasOldData = !!(guest.old_city || guest.old_ward || guest.old_district);
        const addrType = hasOldData ? 'old' : 'new';

        // Set radio WITHOUT triggering agSwitchMode
        const oldRadio = document.querySelector('input[name="ag-area"][value="old"]');
        const newRadio = document.querySelector('input[name="ag-area"][value="new"]');
        const distGrp = document.getElementById('ag-grp-district');
        const convGrp = document.getElementById('ag-conversion-grp');

        if (addrType === 'old') {
            if (oldRadio) { oldRadio.checked = true; oldRadio.disabled = false; }
            if (newRadio) newRadio.disabled = false;
            if (distGrp) distGrp.style.display = '';
            if (convGrp) convGrp.style.display = 'none';
        } else {
            if (newRadio) { newRadio.checked = true; }
            if (distGrp) distGrp.style.display = 'none';
            if (convGrp) convGrp.style.display = 'none';
            if (oldRadio) { oldRadio.disabled = true; oldRadio.style.display = 'none'; }
        }

        // 3. Fill address fields
        const pEl = document.getElementById('ag-province');
        const dEl = document.getElementById('ag-district');
        const wEl = document.getElementById('ag-ward');
        const nProvEl = document.getElementById('ag-new-province');
        const nWardEl = document.getElementById('ag-new-ward');

        if (addrType === 'old') {
            // Load OLD province datalist first
            if (typeof agLoadOldProvinces === 'function') {
                const oldProvinces = await agLoadOldProvinces();
                agPopulateDatalist('dl-ag-province', oldProvinces);
            }
            // Fill NEW readonly conversion display FIRST (values from DB)
            if (nProvEl) { nProvEl.value = guest.city || ''; nProvEl.style.color = '#15803d'; }
            if (nWardEl) { nWardEl.value = guest.ward || ''; nWardEl.style.color = '#15803d'; }
            // Set province FIRST, then load districts via province change
            if (pEl) pEl.value = guest.old_city || '';
            if (typeof agOnOldProvinceChange === 'function' && pEl) await agOnOldProvinceChange(pEl);
            // NOW set district value (after districts are loaded)
            if (dEl) dEl.value = guest.old_district || '';
            if (typeof agOnOldDistrictChange === 'function' && dEl) await agOnOldDistrictChange(dEl);
            // NOW set ward value (after wards are loaded)
            if (wEl) wEl.value = guest.old_ward || '';
            // Match ward value to datalist option
            if (wEl && wEl.value) {
                const dl = document.getElementById('dl-ag-ward');
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
        } else {
            // Load NEW province datalist first
            if (typeof agLoadNewProvinces === 'function') {
                const provinces = await agLoadNewProvinces();
                agPopulateDatalist('dl-ag-province', provinces.map(p => ({ name: p.name, short: p.short })));
            }
            // Set province FIRST, then load wards via province change
            if (pEl) pEl.value = guest.city || '';
            if (typeof agOnNewProvinceChange === 'function' && pEl) await agOnNewProvinceChange(pEl);
            // NOW set ward value (after wards are loaded)
            if (wEl) wEl.value = guest.ward || '';
            // Match ward value to datalist option
            if (wEl && wEl.value) {
                const dl = document.getElementById('dl-ag-ward');
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
        }

        // 4. Toggle ID fields (show/hide address based on id_type) - SAU KHI SET VALUE
        if (idTypeEl) { idTypeEl.disabled = true; agToggleIdFields(idTypeEl); }

        // 5. Lock ALL fields AFTER async operations complete
        if (typeof agLockAllFields === 'function') agLockAllFields();

        // 5b. Unlock invoice fields (user can update invoice info per-guest)
        document.querySelectorAll('input[name="ag-invoice"]').forEach(r => r.disabled = false);
        const taxCodeEl2 = document.getElementById('ag-tax-code');
        if (taxCodeEl2) taxCodeEl2.readOnly = false;
        const taxContactEl2 = document.getElementById('ag-tax-contact');
        if (taxContactEl2) taxContactEl2.readOnly = false;

        // 6. Unlock ONLY editable fields
        const cccdLockEl = document.getElementById('ag-cccd');
        if (cccdLockEl) { cccdLockEl.value = guest.cccd || ''; cccdLockEl.readOnly = true; }
        if (idTypeEl) idTypeEl.disabled = true;
        ['ag-phone','ag-notes','ag-vehicle'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.readOnly = false;
        });
        const expireEl = document.getElementById('ag-id-expire');
        if (expireEl) expireEl.readOnly = false;

        // 7. Update UI state
        if (typeof agRenderGuestList === 'function') agRenderGuestList();

        // 7b. Show state badge for trusted data (PMS_ADDR progressive normalization)
        if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR._updateStateBadge) {
            PMS_ADDR._updateStateBadge('RAW', 'Địa chỉ từ dữ liệu cũ - sẽ được chuẩn hóa', 'blue');
        }

        // 7c. Reset trusted flag after fill (allow validation for subsequent edits)
        setTimeout(() => {
            if (typeof PMS_ADDR !== 'undefined' && PMS_ADDR.reset) {
                PMS_ADDR.reset();
            }
        }, 500);

        pmsToast('Đã điền thông tin khách cũ');
    } catch (e) {
        console.error('[agFillGuestFromOld] Error:', e);
        pmsToast('Lỗi khi điền thông tin', false);
    }
}
window.agFillGuestFromOld = agFillGuestFromOld;
