// static/js/hr/hr_scan.js
// HR Employee Form — CCCD Scan Integration
// Reuses openScanModal() from scan_modal.js
'use strict';

window.HrScan = (function() {

    function parseScanDate(dateStr) {
        if (!dateStr) return '';
        if (dateStr === 'Không thời hạn') return '';
        const parts = dateStr.match(/(\d{2})\/(\d{2})\/(\d{4})/);
        if (parts) return `${parts[3]}-${parts[2]}-${parts[1]}`;
        return dateStr;
    }

    function titleCase(str) {
        if (!str) return '';
        return str.split(' ').map(w =>
            w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
        ).join(' ');
    }

    function scan(alpineComponent) {
        if (typeof openScanModal !== 'function') {
            alpineComponent.showToast('Chức năng quét CCCD chưa sẵn sàng. Vui lòng tải lại trang.', 'error');
            return;
        }

        openScanModal(function(parsed) {
            if (!parsed || !parsed.is_valid) {
                alpineComponent.showToast('Không đọc được thông tin từ CCCD.', 'error');
                return;
            }

            // Fill basic info
            alpineComponent.form.name = titleCase(parsed.name || '');
            alpineComponent.form.cccd = parsed.id_number || parsed.cccd || parsed.old_id || '';
            alpineComponent.form.gender = parsed.gender || '';
            alpineComponent.form.date_of_birth = parseScanDate(parsed.dob || '');

            // Fill address
            if (parsed.address) {
                const addr = parsed.address;
                alpineComponent.form.province = addr.city || addr.province || '';
                alpineComponent.form.district = addr.district || '';
                alpineComponent.form.ward = addr.ward || '';
                alpineComponent.form.address = addr.street || addr.detail || '';

                // Determine address mode based on scan data
                if (addr.district) {
                    alpineComponent.form.addressMode = 'old';
                } else {
                    alpineComponent.form.addressMode = 'new';
                }

                // Trigger address datalist reload
                HrAddress.switchMode(alpineComponent.form.addressMode).then(function() {
                    if (alpineComponent.form.province) {
                        HrAddress.onProvinceChange(
                            alpineComponent.form.province,
                            alpineComponent.form.addressMode
                        ).then(function() {
                            if (alpineComponent.form.addressMode === 'old' && alpineComponent.form.district) {
                                HrAddress.onDistrictChange(
                                    alpineComponent.form.district,
                                    alpineComponent.form.province
                                );
                            }
                        });
                    }
                });
            }

            alpineComponent.showToast('Đã quét CCCD: ' + alpineComponent.form.name, 'success');
        });
    }

    return { scan, parseScanDate, titleCase };
})();
