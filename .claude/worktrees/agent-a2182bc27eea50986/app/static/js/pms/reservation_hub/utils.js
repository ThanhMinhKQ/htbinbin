// PMS Reservation Hub - shared UI and formatting helpers
'use strict';

Object.assign(BookingHub, {
    setLoading(isLoading) {
        this.state.loading = isLoading;
        const loading = document.getElementById('bk-loading');
        const wrap = document.getElementById('bk-table-wrap');
        const empty = document.getElementById('bk-empty');
        if (loading) loading.style.display = isLoading ? 'flex' : 'none';
        if (wrap) wrap.style.display = isLoading ? 'none' : 'block';
        if (empty) empty.style.display = 'none';
    },

    showModal(id) {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.parentElement !== document.body) document.body.appendChild(el);
        document.body.classList.add('bk-modal-open');
        el.classList.add('show');
    },

    hideModal(id) {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('show');
        if (!document.querySelector('.bk-modal.show')) {
            document.body.classList.remove('bk-modal-open');
        }
    },

    setButtonBusy(btn, busy, text) {
        if (!btn) return;
        btn.disabled = busy;
        btn.textContent = text;
    },

    text(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    },

    value(id) {
        const el = document.getElementById(id);
        return el ? String(el.value || '').trim() : '';
    },

    apiData(response, fallback = null) {
        if (response && typeof response === 'object' && response.success === true && Object.prototype.hasOwnProperty.call(response, 'data')) {
            return response.data;
        }
        return response ?? fallback;
    },

    bindModalListeners() {
        if (this.state.modalListenersBound) return;
        this.state.modalListenersBound = true;
        document.addEventListener('click', (event) => {
            const modal = event.target;
            if (modal && modal.classList && modal.classList.contains('bk-modal')) {
                this.hideModal(modal.id);
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            const openModals = Array.from(document.querySelectorAll('.bk-modal.show'));
            const topModal = openModals[openModals.length - 1];
            if (topModal) this.hideModal(topModal.id);
        });
    },

    toDateInput(date) {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    },

    isCheckinDateReached(value) {
        if (!value) return false;
        return String(value).slice(0, 10) <= this.toDateInput(new Date());
    },

    isPastCheckoutDate(value) {
        if (!value) return false;
        return String(value).slice(0, 10) < this.toDateInput(new Date());
    },

    formatDate(value) {
        if (!value) return '—';
        const [y, m, d] = String(value).slice(0, 10).split('-');
        if (!y || !m || !d) return value;
        return `${d}/${m}/${y}`;
    },

    formatStayDateTime(value, fallbackTime = '') {
        const date = this.formatDate(value);
        if (date === '—') return date;
        const raw = String(value || '');
        const time = (raw.includes('T') ? raw.split('T')[1] : fallbackTime || '').slice(0, 5);
        return time ? `${date}, ${time}` : date;
    },

    formatDateTime(value) {
        if (!value) return '';
        try {
            return new Date(value).toLocaleString('vi-VN', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch (e) {
            return value;
        }
    },

    dateDiff(start, end) {
        const a = new Date(`${start}T00:00:00`);
        const b = new Date(`${end}T00:00:00`);
        return Math.round((b - a) / (24 * 60 * 60 * 1000));
    },

    statusLabel(status) {
        return {
            PENDING: 'Chờ xác nhận',
            CONFIRMED: 'Đã xác nhận',
            CHECKED_IN: 'Đã nhận phòng',
            CHECKED_OUT: 'Đã trả phòng',
            CANCELLED: 'Đã hủy',
            NO_SHOW: 'No-show',
        }[status] || status || '—';
    },

    escape(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }
});
