/**
 * CRM Guest Detail - Alpine.js Component
 * Tách riêng để dễ quản lý và bảo trì
 */

function guestDetail() {
  const guestId = GUEST_ID;

  return {
    guestId,
    loading: true,
    activeTab: 'overview',

    // Profile data
    guest: null,
    membership: null,
    next_tier: null,
    profile: null,

    // Stays tab
    stays: [], staysLoading: false,
    staysMeta: { page: 1, pages: 0 },

    // Services tab
    services: [], serviceStats: null, servicesLoading: false,

    // Payments tab
    payments: [], paymentStats: null, paymentsLoading: false,

    // Timeline tab
    timeline: [], timelineLoading: false, timelineLimit: 50,

    // Co-guests tab
    coGuests: [], coGuestsLoading: false,

    // Tier journey
    tierJourney: [],

    async init() {
      await this.loadProfile();
      this.loadStays();
    },

    async loadProfile() {
      this.loading = true;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/profile', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Not found');
        const data = await res.json();
        this.guest = data.guest;
        this.membership = data.membership;
        this.profile = data;
        // Extract next_tier from membership for compatibility
        this.next_tier = data.membership?.next_tier;
      } catch (e) {
        console.error('Profile error:', e);
      } finally {
        this.loading = false;
      }
    },

    computeTierJourney() {
      const tiers = [
        { name: 'BASIC', display: 'Basic', icon: '●', color: '#64748b' },
        { name: 'SILVER', display: 'Silver', icon: '◆', color: '#94a3b8' },
        { name: 'GOLD', display: 'Gold', icon: '★', color: '#f59e0b' },
        { name: 'PLATINUM', display: 'Platinum', icon: '♦', color: '#3b82f6' },
        { name: 'VIP', display: 'VIP', icon: '◆', color: '#8b5cf6' }
      ];
      const currentTier = (this.membership?.tier || 'BASIC').toUpperCase();
      const tierOrder = ['BASIC', 'SILVER', 'GOLD', 'PLATINUM', 'VIP'];
      const currentIndex = tierOrder.indexOf(currentTier);
      this.tierJourney = tiers.map(t => ({
        ...t,
        active: tierOrder.indexOf(t.name) <= currentIndex
      }));
    },

    async loadStays(page = 1) {
      this.staysLoading = true;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/stays?page=' + page + '&page_size=10', { credentials: 'same-origin' });
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (page === 1) {
          this.stays = data.items || [];
        } else {
          this.stays = [...this.stays, ...(data.items || [])];
        }
        this.staysMeta.page = page;
        this.staysMeta.pages = data.pages || 0;
      } catch (e) { console.error(e); }
      finally { this.staysLoading = false; }
    },

    async loadServices() {
      if (this.services.length > 0) return;
      this.servicesLoading = true;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/services?page_size=50', { credentials: 'same-origin' });
        if (!res.ok) throw new Error();
        const data = await res.json();
        this.services = data.items || [];
        this.serviceStats = data.stats || null;
      } catch (e) { console.error(e); }
      finally { this.servicesLoading = false; }
    },

    async loadPayments() {
      if (this.payments.length > 0) return;
      this.paymentsLoading = true;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/payments?page_size=50', { credentials: 'same-origin' });
        if (!res.ok) throw new Error();
        const data = await res.json();
        this.payments = data.items || [];
        this.paymentStats = data.stats || null;
      } catch (e) { console.error(e); }
      finally { this.paymentsLoading = false; }
    },

    async loadTimeline() {
      this.timelineLoading = true;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/timeline?limit=' + this.timelineLimit, { credentials: 'same-origin' });
        if (!res.ok) throw new Error();
        const data = await res.json();
        this.timeline = data.items || [];
      } catch (e) { console.error(e); }
      finally { this.timelineLoading = false; }
    },

    async loadCoGuests() {
      if (this.coGuests.length > 0) return;
      this.coGuestsLoading = true;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/co-guests', { credentials: 'same-origin' });
        if (!res.ok) throw new Error();
        const data = await res.json();
        this.coGuests = data.co_guests || [];
      } catch (e) { console.error(e); }
      finally { this.coGuestsLoading = false; }
    },

    async toggleBlacklist() {
      if (!this.guest) return;
      const next = !this.guest.is_blacklisted;
      const reason = window.prompt(next ? 'Lý do đưa khách vào danh sách đen?' : 'Lý do gỡ khỏi danh sách đen?', '');
      if (reason === null) return;
      try {
        const res = await fetch('/api/pms/crm/guests/' + guestId + '/blacklist', {
          method: 'PATCH',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_blacklisted: next, reason }),
        });
        if (!res.ok) throw new Error();
        const data = await res.json();
        this.guest.is_blacklisted = data.is_blacklisted;
        this.guest.risk_flags = data.risk_flags;
      } catch (e) {
        console.error(e);
        alert('Không cập nhật được danh sách đen');
      }
    },

    // ── Helpers ──
    fmtPoints(v) {
      if (!v && v !== 0) return '0';
      return Number(v).toLocaleString('vi-VN');
    },
    fmtMoney(v) {
      if (!v && v !== 0) return '-';
      return Number(v).toLocaleString('vi-VN') + 'đ';
    },
    fmtMoneyFull(v) {
      if (!v && v !== 0) return '0đ';
      return Number(v).toLocaleString('vi-VN') + 'đ';
    },
    fmtShort(v) {
      if (!v) return '0';
      if (v >= 1e9) return (v / 1e9).toFixed(1) + 'tỷ';
      if (v >= 1e6) return (v / 1e6).toFixed(1) + 'tr';
      if (v >= 1e3) return (v / 1e3).toFixed(0) + 'k';
      return v.toLocaleString('vi-VN');
    },
    isExpiringSoon(dateStr) {
      if (!dateStr) return false;
      const expDate = new Date(dateStr);
      const now = new Date();
      const diffDays = (expDate - now) / (1000 * 60 * 60 * 24);
      return diffDays > 0 && diffDays <= 90;
    },
    fmtDate(iso) {
      if (!iso) return '-';
      const d = new Date(iso);
      return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0') + '/' + d.getFullYear();
    },
    fmtDateTime(iso) {
      if (!iso) return '-';
      const d = new Date(iso);
      return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0') + '/' + d.getFullYear()
        + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    },
    fmtPaymentMethod(methods) {
      const labels = {
        CASH: 'Tiền mặt',
        CARD: 'Thẻ',
        OTA: 'OTA',
        COMPANY: 'Công ty',
        BRANCH: 'Tài khoản CN',
        BANK_TRANSFER: 'Chuyển khoản',
        RECORD: 'Ghi nhận',
      };
      if (Array.isArray(methods)) {
        if (!methods.length) return '-';
        return methods.map(m => labels[m] || m).join(', ');
      }
      return labels[methods] || methods || '-';
    },
    preferenceLabel(type) {
      const labels = {
        smoking: 'Hút thuốc',
        bed: 'Giường',
        floor: 'Tầng',
        pillow: 'Gối',
        breakfast: 'Bữa sáng',
        room: 'Phòng',
        payment: 'Thanh toán',
      };
      return labels[type] || type;
    },
    stayActivities(stay) {
      return (stay?.activities || []).slice(0, 4);
    },
    avatarColor(name) {
      const colors = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6'];
      let h = 0;
      for (let i = 0; i < (name || '').length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
      return colors[Math.abs(h) % colors.length];
    },
    tierGradient(tier) {
      const map = {
        BASIC: 'background:linear-gradient(135deg,#64748b,#475569)',
        SILVER: 'background:linear-gradient(135deg,#94a3b8,#64748b)',
        GOLD: 'background:linear-gradient(135deg,#f59e0b,#d97706)',
        PLATINUM: 'background:linear-gradient(135deg,#3b82f6,#1d4ed8)',
        VIP: 'background:linear-gradient(135deg,#8b5cf6,#6d28d9)',
      };
      return map[tier] || map.BASIC;
    },
    tierIcon(tier) {
      const icons = {
        BASIC: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="5"/><path d="M3 21v-2a7 7 0 0 1 14 0v2"/></svg>',
        SILVER: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
        GOLD: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/><circle cx="12" cy="12" r="10"/></svg>',
        PLATINUM: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>',
        VIP: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/><circle cx="12" cy="12" r="4"/></svg>'
      };
      return icons[tier] || icons.BASIC;
    },
    journeyTierIcon(tier) {
      const icons = {
        BASIC: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="8" r="4"/><path d="M6 20v-2a6 6 0 0 1 12 0v2"/></svg>',
        SILVER: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="rgba(255,255,255,0.1)"/></svg>',
        GOLD: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="rgba(255,255,255,0.15)"/></svg>',
        PLATINUM: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z" fill="rgba(255,255,255,0.1)"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>',
        VIP: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="rgba(255,255,255,0.15)"/><circle cx="12" cy="10" r="3"/></svg>'
      };
      return icons[tier] || icons.BASIC;
    },
    benefitLabel(key) {
      const map = {
        name: 'Tên hạng', points_multiplier: 'Nhân điểm', early_checkin: 'Nhận phòng sớm',
        late_checkout: 'Trả phòng trễ', discount_percent: 'Giảm giá',
        priority_service: 'Ưu tiên DV', free_upgrade: 'Nâng phòng', dedicated_manager: 'QL riêng',
      };
      return map[key] || key;
    },
    svcColor(cat) {
      const map = { MINIBAR: '#f59e0b', SERVICE: '#3b82f6', LAUNDRY: '#06b6d4', RESTAURANT: '#10b981', SPA: '#ec4899', OTHER: '#8b5cf6' };
      return map[cat] || '#6366f1';
    },
    benefitIcon(key, val) {
      const icons = {
        points_multiplier: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
        early_checkin: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        late_checkout: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/><path d="M12 2v4"/></svg>',
        discount_percent: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="9" cy="9" r="2"/><circle cx="15" cy="15" r="2"/><path d="M21.41 11.58l-8-8A2 2 0 0 0 11 2H7a2 2 0 0 0-2 2v4a2 2 0 0 0 1.41 1.83l8 8a2 2 0 0 0 2.83 0l4-4a2 2 0 0 0 0-2.83z"/></svg>',
        priority_service: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
        free_upgrade: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
        dedicated_manager: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        name: '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
      };
      return icons[key] || '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>';
    },
    benefitDesc(key, val) {
      const descs = {
        points_multiplier: 'Nhân điểm khi tích lũy',
        early_checkin: 'Nhận phòng trước 14:00',
        late_checkout: 'Trả phòng sau 12:00',
        discount_percent: 'Giảm giá dịch vụ',
        priority_service: 'Được ưu tiên xử lý',
        free_upgrade: 'Nâng cấp phòng miễn phí',
        dedicated_manager: 'Được chăm sóc riêng',
        name: 'Hạng thành viên hiện tại',
      };
      return descs[key] || '';
    },
    benefitValue(key, val) {
      if (typeof val === 'boolean') return val ? 'Có' : 'Không';
      if (key === 'points_multiplier') return '×' + val;
      if (key === 'discount_percent') return val + '%';
      return val;
    },
    isBenefitActive(val) {
      if (typeof val === 'boolean') return val;
      return val > 0;
    },
    tierColor(tier) {
      const colors = {
        BASIC: '#64748b', SILVER: '#94a3b8', GOLD: '#f59e0b', PLATINUM: '#3b82f6', VIP: '#8b5cf6'
      };
      return colors[tier] || '#64748b';
    },
    benefitDisplayValue(key, val) {
      if (key === 'name') return '';
      if (typeof val === 'boolean') return val ? 'Có' : 'Không';
      if (key === 'points_multiplier') return '×' + val;
      if (key === 'discount_percent') return val + '%';
      if (typeof val === 'number') return val;
      return val || '';
    },
    stayStatusLabel(status) {
      const map = {
        'ACTIVE': 'Đang ở',
        'CHECKED_OUT': 'Đã check-out',
        'CANCELLED': 'Đã hủy',
        'checkin': 'Đã check-in',
        'staying': 'Đang ở',
        'checkout': 'Đã check-out',
        'completed': 'Hoàn thành',
        'cancelled': 'Đã hủy',
      };
      return map[status] || status || 'Hoàn thành';
    },
  };
}
