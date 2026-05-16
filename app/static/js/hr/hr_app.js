function hrApp() {
    return {
            // State
            activeTab: 'overview',
            loading: true,
            loadingDashboard: true,
            saving: false,

            // Data
            allEmployees: [],
            filteredEmployees: [],
            branches: [],
            departments: [],

            stats: { active: 0, inactive: 0 },
            dashboard: {
                period: {},
                summary: {},
                rankings: { most_work: [], most_absent: [], most_laundry: [], most_ironing: [] },
                birthdays: [],
                gender_counts: {},
                today_active_employees: [],
                branch_staff: [],
                employees: [],
            },
            dashboardMonth: new Date().toISOString().slice(0, 7),
            dashboardBranch: '',
            dashboardDept: '',
            dashboardSearch: '',
            insightTab: 'work',
            profile: {
                name: window._hrBoot.userName,
                roleLabel: window._hrBoot.userRole,
                avatar_url: window._hrBoot.userAvatar,
            },

            // Filters
            filterSearch: '',
            filterBranch: '',
            filterDept: '',
            filterStatus: '',

            // Sorting
            sortKey: 'branch',
            sortDirection: 'asc',

            // Modals
            showEmployeeModal: false,
            showPasswordModal: false,
            showBranchModal: false,

            editingEmployee: null,
            form: {},

            passwordTarget: null,
            newPassword: '',

            editingBranch: null,
            branchNewName: '',

            toast: { show: false, message: '', type: 'success' },

            // ===========================================================
            // INIT
            // ===========================================================
            async init() {
                await Promise.all([
                    this.fetchEmployees(),
                    this.fetchBranches(),
                    this.fetchDepartments()
                ]);
                await this.loadDashboard();
                this.loading = false;
            },

            // ===========================================================
            // DATA FETCHING
            // ===========================================================
            async fetchEmployees() {
                try {
                    const params = new URLSearchParams({
                        sort_by: this.sortKey,
                        sort_dir: this.sortDirection,
                    });
                    const res = await fetch(`/api/hr/employees?${params.toString()}`);
                    if (!res.ok) throw new Error(await res.text());
                    this.allEmployees = await res.json();
                    this.computeStats();
                    this.applyFilters();
                } catch (e) {
                    this.showToast('Lỗi tải danh sách nhân viên: ' + e.message, 'error');
                }
            },

            async fetchBranches() {
                try {
                    const res = await fetch('/api/hr/branches');
                    if (!res.ok) throw new Error(await res.text());
                    this.branches = await res.json();
                } catch (e) {
                    this.showToast('Lỗi tải danh sách chi nhánh.', 'error');
                }
            },

            hotelBranches() {
                return this.branches.filter(b => /^B\d+$/i.test(b.branch_code));
            },

            async fetchDepartments() {
                try {
                    const res = await fetch('/api/hr/departments');
                    if (!res.ok) throw new Error(await res.text());
                    this.departments = await res.json();
                } catch (e) {
                    this.showToast('Lỗi tải danh sách phòng ban.', 'error');
                }
            },

            async loadDashboard() {
                this.loadingDashboard = true;
                try {
                    const [year, month] = this.dashboardMonth.split('-');
                    const params = new URLSearchParams({ year, month });
                    if (this.dashboardBranch) params.set('branch_id', this.dashboardBranch);
                    if (this.dashboardDept) params.set('department_id', this.dashboardDept);
                    if (this.dashboardSearch.trim()) params.set('search', this.dashboardSearch.trim());

                    const res = await fetch(`/api/hr/dashboard?${params.toString()}`);
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Không tải được dashboard.');
                    this.dashboard = data;
                } catch (e) {
                    this.showToast('Lỗi tải dashboard nhân sự: ' + e.message, 'error');
                } finally {
                    this.loadingDashboard = false;
                }
            },

            async refreshAll() {
                await Promise.all([
                    this.fetchEmployees(),
                    this.fetchBranches(),
                    this.fetchDepartments(),
                    this.loadDashboard(),
                ]);
            },

            syncDashboardBranch() {
                this.filterBranch = this.dashboardBranch;
                this.applyFilters();
                this.loadDashboard();
            },

            syncDashboardDept() {
                this.filterDept = this.dashboardDept;
                this.applyFilters();
                this.loadDashboard();
            },

            syncDashboardSearch() {
                this.filterSearch = this.dashboardSearch;
                this.applyFilters();
                this.loadDashboard();
            },

            resetDashboardFilters() {
                this.dashboardMonth = new Date().toISOString().slice(0, 7);
                this.dashboardBranch = '';
                this.dashboardDept = '';
                this.dashboardSearch = '';
                this.filterSearch = '';
                this.filterBranch = '';
                this.filterDept = '';
                this.filterStatus = '';
                this.applyFilters();
                this.loadDashboard();
            },

            async resetTableFilters() {
                this.filterSearch = '';
                this.filterBranch = '';
                this.filterDept = '';
                this.filterStatus = '';
                await this.fetchEmployees();
                this.applyFilters();
            },

            computeStats() {
                this.stats.active = this.allEmployees.filter(e => e.is_active).length;
                this.stats.inactive = this.allEmployees.filter(e => !e.is_active).length;
            },

            // ===========================================================
            // FILTERING / SORTING
            // ===========================================================
            applyFilters() {
                let result = [...this.allEmployees];

                if (this.filterSearch) {
                    const q = this.filterSearch.toLowerCase();
                    result = result.filter(e =>
                        (e.name || '').toLowerCase().includes(q) ||
                        (e.employee_code || '').toLowerCase().includes(q) ||
                        (e.employee_id || '').toLowerCase().includes(q)
                    );
                }
                if (this.filterBranch) {
                    result = result.filter(e => e.main_branch_id == this.filterBranch);
                }
                if (this.filterDept) {
                    result = result.filter(e => e.department_id == this.filterDept);
                }
                if (this.filterStatus !== '') {
                    const active = this.filterStatus === 'true';
                    result = result.filter(e => e.is_active === active);
                }

                this.filteredEmployees = result;
                this.applySort();
            },

            setSort(key) {
                if (this.sortKey === key) {
                    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
                } else {
                    this.sortKey = key;
                    this.sortDirection = 'asc';
                }
                this.applyFilters();
            },

            sortIcon(key) {
                if (this.sortKey !== key) return 'bi-chevron-expand';
                return this.sortDirection === 'asc' ? 'bi-chevron-up' : 'bi-chevron-down';
            },

            getSortValue(emp, key) {
                const valueMap = {
                    employee_id: emp.employee_id,
                    name: emp.name,
                    employee_code: emp.employee_code,
                    branch: `${emp.branch_code || ''} ${emp.branch_name || ''}`,
                    role: emp.department_name || emp.role_code,
                    shift: emp.shift,
                    status: emp.is_active ? 1 : 0,
                };
                return valueMap[key] ?? '';
            },

            compareEmployees(a, b) {
                const aValue = this.getSortValue(a, this.sortKey);
                const bValue = this.getSortValue(b, this.sortKey);
                let result;

                if (typeof aValue === 'number' && typeof bValue === 'number') {
                    result = aValue - bValue;
                } else {
                    result = String(aValue || '').localeCompare(String(bValue || ''), 'vi', {
                        numeric: true,
                        sensitivity: 'base',
                    });
                }
                if (result !== 0) return this.sortDirection === 'desc' ? -result : result;

                result = String(a.name || '').localeCompare(String(b.name || ''), 'vi', {
                    numeric: true,
                    sensitivity: 'base',
                });
                if (result === 0) result = (a.id || 0) - (b.id || 0);
                return result;
            },

            applySort() {
                this.filteredEmployees.sort((a, b) => this.compareEmployees(a, b));
            },

            getEmployeesByBranch(branchId) {
                return this.allEmployees.filter(e => e.main_branch_id === branchId && e.is_active);
            },

            // ===========================================================
            // RANKINGS / CHARTS
            // ===========================================================
            currentRanking() {
                const map = {
                    work: this.dashboard.rankings?.most_work || [],
                    absent: this.dashboard.rankings?.most_absent || [],
                    laundry: this.dashboard.rankings?.most_laundry || [],
                    ironing: this.dashboard.rankings?.most_ironing || [],
                };
                return map[this.insightTab] || [];
            },

            rankingValue(emp) {
                if (this.insightTab === 'work') return `${this.formatNumber(emp.total_work_units || 0)} công`;
                if (this.insightTab === 'absent') return `${emp.absence_days || 0} ngày`;
                if (this.insightTab === 'laundry') return `${emp.laundry_quantity || 0} món`;
                if (this.insightTab === 'ironing') return `${emp.ironing_quantity || 0} món`;
                return '0';
            },

            rankingRawValue(emp) {
                if (this.insightTab === 'work') return Number(emp.total_work_units || 0);
                if (this.insightTab === 'absent') return Number(emp.absence_days || 0);
                if (this.insightTab === 'laundry') return Number(emp.laundry_quantity || 0);
                if (this.insightTab === 'ironing') return Number(emp.ironing_quantity || 0);
                return 0;
            },

            rankingSubtitle() {
                const map = {
                    work: 'Top nhân viên làm nhiều công nhất',
                    absent: 'Top nhân viên nghỉ nhiều nhất',
                    laundry: 'Top nhân viên giặt đồ nhiều nhất',
                    ironing: 'Top nhân viên ủi đồ nhiều nhất',
                };
                return map[this.insightTab] || '';
            },

            rankingBarStyle(emp) {
                const values = this.currentRanking().map(item => this.rankingRawValue(item));
                const max = Math.max(...values, 1);
                const width = Math.max(4, Math.round((this.rankingRawValue(emp) / max) * 100));
                const colors = {
                    work: 'var(--hr-grad-green)',
                    absent: 'var(--hr-grad-rose)',
                    laundry: 'var(--hr-grad-blue)',
                    ironing: 'var(--hr-grad-amber)',
                };
                return `width: ${width}%; --bar: ${colors[this.insightTab] || 'var(--hr-grad-blue)'};`;
            },

            vbarStyle(emp, idx) {
                const values = this.currentRanking().map(item => this.rankingRawValue(item));
                const max = Math.max(...values, 1);
                const height = Math.max(4, Math.round((this.rankingRawValue(emp) / max) * 100));
                const colors = {
                    work: 'var(--hr-grad-green)',
                    absent: 'var(--hr-grad-rose)',
                    laundry: 'var(--hr-grad-blue)',
                    ironing: 'var(--hr-grad-amber)',
                };
                return `height: ${height}%; --bar: ${colors[this.insightTab] || 'var(--hr-grad-blue)'};`;
            },

            rankClass(idx) {
                if (idx === 0) return 'top1';
                if (idx === 1) return 'top2';
                if (idx === 2) return 'top3';
                return '';
            },

            topName(type) {
                const key = type === 'absent' ? 'most_absent' : 'most_work';
                return this.dashboard.rankings?.[key]?.[0]?.name || '—';
            },

            genderTotal() {
                const counts = this.dashboard.gender_counts || {};
                return Number(counts.male || 0) + Number(counts.female || 0) + Number(counts.other || 0);
            },

            genderDonutStyle() {
                const counts = this.dashboard.gender_counts || {};
                const total = this.genderTotal();
                if (!total) return 'background: conic-gradient(var(--bk-line) 0deg 360deg);';
                const maleDeg = (Number(counts.male || 0) / total) * 360;
                const femaleDeg = maleDeg + (Number(counts.female || 0) / total) * 360;
                return `background: conic-gradient(#3b82f6 0deg ${maleDeg}deg, #ec4899 ${maleDeg}deg ${femaleDeg}deg, #94a3b8 ${femaleDeg}deg 360deg);`;
            },

            serviceTotal() {
                return Number(this.dashboard.summary.total_laundry || 0) + Number(this.dashboard.summary.total_ironing || 0);
            },

            serviceBarStyle(type, color) {
                const value = type === 'laundry'
                    ? Number(this.dashboard.summary.total_laundry || 0)
                    : Number(this.dashboard.summary.total_ironing || 0);
                const total = Math.max(this.serviceTotal(), 1);
                const width = Math.max(value > 0 ? 6 : 0, Math.round((value / total) * 100));
                return `width: ${width}%; --bar: ${color};`;
            },

            serviceDonutStyle() {
                const laundry = Number(this.dashboard.summary.total_laundry || 0);
                const ironing = Number(this.dashboard.summary.total_ironing || 0);
                const total = laundry + ironing;
                if (!total) return 'background: conic-gradient(var(--bk-line) 0deg 360deg);';
                const laundryDeg = (laundry / total) * 360;
                return `background: conic-gradient(#3b82f6 0deg ${laundryDeg}deg, #10b981 ${laundryDeg}deg 360deg);`;
            },

            formatNumber(value) {
                const number = Number(value || 0);
                return Number.isInteger(number) ? String(number) : number.toFixed(1);
            },

            getInitials(name) {
                const parts = String(name || '?').trim().split(/\s+/).filter(Boolean);
                if (parts.length === 0) return '?';
                if (parts.length === 1) return parts[0][0].toUpperCase();
                return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
            },

            formatBirthDate(value) {
                if (!value) return '—';
                const parts = value.split('-');
                if (parts.length !== 3) return value;
                return `${parts[2]}/${parts[1]}`;
            },

            selectedBranchLabel() {
                if (!this.dashboardBranch) return 'Tất cả chi nhánh';
                const branch = this.branches.find(b => String(b.id) === String(this.dashboardBranch));
                return branch ? `${branch.branch_code} — ${branch.name}` : 'Chi nhánh đã chọn';
            },

            selectedDeptLabel() {
                if (!this.dashboardDept) return 'Tất cả vai trò';
                const dept = this.departments.find(d => String(d.id) === String(this.dashboardDept));
                return dept ? dept.name : 'Vai trò đã chọn';
            },

            dashboardRows() {
                return this.dashboard.employees || [];
            },

            attendanceRate() {
                const active = Number(this.dashboard.summary.active_employees || 0);
                const days = Number(this.dashboard.period?.days_to_count || 0);
                const possible = active * days;
                if (!possible) return 0;
                const rate = (Number(this.dashboard.summary.total_work_units || 0) / possible) * 100;
                return Math.max(0, Math.min(100, Math.round(rate)));
            },

            workPerEmployee() {
                const active = Number(this.dashboard.summary.active_employees || 0);
                if (!active) return 0;
                return Number(this.dashboard.summary.total_work_units || 0) / active;
            },

            workPerEmployeeScore() {
                const days = Number(this.dashboard.period?.days_to_count || 0);
                if (!days) return 0;
                return Math.max(0, Math.min(100, Math.round((this.workPerEmployee() / days) * 100)));
            },

            absencePerEmployee() {
                const active = Number(this.dashboard.summary.active_employees || 0);
                if (!active) return 0;
                return Number(this.dashboard.summary.total_absence_days || 0) / active;
            },

            absencePressure() {
                const days = Number(this.dashboard.period?.days_to_count || 0);
                if (!days) return 0;
                return Math.max(0, Math.min(100, Math.round((this.absencePerEmployee() / days) * 100)));
            },

            todayPool() {
                return Number(this.dashboard.summary.branch_staff_count || this.dashboard.summary.active_employees || 0);
            },

            todayCoverage() {
                const pool = this.todayPool();
                if (!pool) return 0;
                return Math.max(0, Math.min(100, Math.round((Number(this.dashboard.summary.today_active_count || 0) / pool) * 100)));
            },

            notActiveTodayCount() {
                return Math.max(0, this.todayPool() - Number(this.dashboard.summary.today_active_count || 0));
            },

            notActiveTodayRate() {
                const pool = this.todayPool();
                if (!pool) return 0;
                return Math.max(0, Math.min(100, Math.round((this.notActiveTodayCount() / pool) * 100)));
            },

            signalStyle(value, color) {
                const number = Number(value || 0);
                const width = Math.max(number > 0 ? 3 : 0, Math.min(100, Math.round(number)));
                return `width: ${width}%; --bar: ${color};`;
            },

            branchDistribution() {
                const map = new Map();
                this.dashboardRows().forEach(row => {
                    const key = row.main_branch_id || row.branch_code || 'other';
                    if (!map.has(key)) {
                        map.set(key, {
                            key,
                            label: row.branch_code || 'Khác',
                            sub: row.branch_name || 'Chưa có chi nhánh',
                            value: 0,
                        });
                    }
                    map.get(key).value += 1;
                });
                return Array.from(map.values())
                    .sort((a, b) => b.value - a.value || String(a.label).localeCompare(String(b.label), 'vi'))
                    .slice(0, 7);
            },

            branchDistributionMax() {
                return Math.max(...this.branchDistribution().map(item => item.value), 1);
            },

            roleDistribution() {
                const map = new Map();
                const colors = ['var(--hr-grad-blue)', 'var(--hr-grad-green)', 'var(--hr-grad-amber)', 'var(--hr-grad-rose)', 'var(--hr-grad-violet)', 'var(--hr-grad-cyan)'];
                this.dashboardRows().forEach(row => {
                    const key = row.department_id || row.role_code || 'other';
                    if (!map.has(key)) {
                        map.set(key, {
                            key,
                            label: row.department_name || row.role_code || 'Khác',
                            value: 0,
                        });
                    }
                    map.get(key).value += 1;
                });
                const total = Math.max(Number(this.dashboard.summary.active_employees || 0), this.dashboardRows().length, 1);
                return Array.from(map.values())
                    .sort((a, b) => b.value - a.value || String(a.label).localeCompare(String(b.label), 'vi'))
                    .slice(0, 6)
                    .map((item, index) => ({
                        ...item,
                        color: colors[index % colors.length],
                        percent: Math.round((item.value / total) * 100),
                    }));
            },

            roleDistributionMax() {
                return Math.max(...this.roleDistribution().map(item => item.value), 1);
            },

            distributionStyle(value, max, color) {
                const width = Math.max(value > 0 ? 4 : 0, Math.round((Number(value || 0) / Math.max(Number(max || 0), 1)) * 100));
                return `width: ${width}%; --bar: ${color};`;
            },

            // ===========================================================
            // ROLE HELPERS
            // ===========================================================
            getRoleClass(roleCode) {
                const map = {
                    'letan': 'role-letan',
                    'buongphong': 'role-buongphong',
                    'baove': 'role-baove',
                    'ktv': 'role-ktv',
                    'quanly': 'role-quanly',
                    'admin': 'role-admin',
                    'boss': 'role-boss',
                };
                return map[roleCode?.toLowerCase()] || 'role-other';
            },

            getRoleLabel(roleCode) {
                const map = {
                    'letan': 'LT',
                    'buongphong': 'BP',
                    'baove': 'BV',
                    'ktv': 'KTV',
                    'quanly': 'QL',
                    'admin': 'ADM',
                    'boss': 'BOSS',
                };
                return map[roleCode?.toLowerCase()] || roleCode || '?';
            },

            formatAccountAge(days) {
                if (days === null || days === undefined) return '—';
                if (days < 30) return days + ' ngày';
                if (days < 365) return Math.floor(days / 30) + ' tháng ' + (days % 30) + ' ngày';
                const years = Math.floor(days / 365);
                const rem = Math.floor((days % 365) / 30);
                return years + ' năm' + (rem > 0 ? ' ' + rem + ' tháng' : '');
            },

            parseAddress(fullAddress) {
                if (!fullAddress) return { street: '', ward: '', district: '', province: '' };
                const parts = fullAddress.split(',').map(p => p.trim());
                if (parts.length >= 4) {
                    return { street: parts[0], ward: parts[1], district: parts[2], province: parts.slice(3).join(', ') };
                }
                if (parts.length === 3) {
                    return { street: '', ward: parts[0], district: parts[1], province: parts[2] };
                }
                if (parts.length === 2) {
                    return { street: '', ward: '', district: parts[0], province: parts[1] };
                }
                return { street: fullAddress, ward: '', district: '', province: '' };
            },

            buildAddress() {
                const parts = [this.form.address, this.form.ward, this.form.district, this.form.province].filter(p => p && p.trim());
                return parts.join(', ');
            },

            // Address & Scan — delegated to HrAddress/HrScan modules
            hrSwitchAddrMode() {
                HrAddress.switchMode(this.form.addressMode || 'new');
            },

            hrOnProvinceChange() {
                HrAddress.onProvinceChange(this.form.province, this.form.addressMode || 'new');
            },

            hrOnDistrictChange() {
                HrAddress.onDistrictChange(this.form.district, this.form.province);
            },

            hrScanCCCD() {
                HrScan.scan(this);
            },

            // ===========================================================
            // MODALS
            // ===========================================================
            openAddModal() {
                this.editingEmployee = null;
                this.form = {
                    employee_id: '',
                    employee_code: '',
                    name: '',
                    department_id: '',
                    main_branch_id: '',
                    shift: '',
                    password: '123456',
                    phone_number: '',
                    email: '',
                    is_active: true,
                    cccd: '',
                    date_of_birth: '',
                    province: '',
                    district: '',
                    ward: '',
                    address: '',
                    gender: '',
                    addressMode: 'new',
                };
                this.showEmployeeModal = true;
                this.$nextTick(() => this.hrSwitchAddrMode());
            },

            openEditModal(emp) {
                this.editingEmployee = emp;
                const addrParts = this.parseAddress(emp.address || '');
                this.form = {
                    employee_id: emp.employee_id,
                    employee_code: emp.employee_code,
                    name: emp.name,
                    department_id: emp.department_id,
                    main_branch_id: emp.main_branch_id,
                    shift: emp.shift || '',
                    password: '',
                    phone_number: emp.phone_number || '',
                    email: emp.email || '',
                    is_active: emp.is_active,
                    cccd: emp.cccd || '',
                    date_of_birth: emp.date_of_birth || '',
                    province: addrParts.province,
                    district: addrParts.district,
                    ward: addrParts.ward,
                    address: addrParts.street,
                    gender: emp.gender || '',
                    addressMode: addrParts.district ? 'old' : 'new',
                };
                this.showEmployeeModal = true;
                this.$nextTick(() => this.hrSwitchAddrMode());
            },

            openResetPasswordModal(emp) {
                this.passwordTarget = emp;
                this.newPassword = '';
                this.showPasswordModal = true;
            },

            openEditBranchModal(branch) {
                this.editingBranch = branch;
                this.branchNewName = branch.name;
                this.showBranchModal = true;
            },

            // ===========================================================
            // SAVE EMPLOYEE
            // ===========================================================
            async saveEmployee() {
                if (!this.form.name?.trim()) { this.showToast('Vui lòng nhập tên nhân viên.', 'error'); return; }
                if (!this.form.employee_code?.trim()) { this.showToast('Vui lòng nhập mã đăng nhập.', 'error'); return; }
                if (!this.form.main_branch_id) { this.showToast('Vui lòng chọn chi nhánh.', 'error'); return; }
                if (!this.form.department_id) { this.showToast('Vui lòng chọn vai trò.', 'error'); return; }

                this.saving = true;
                try {
                    let res;
                    const body = {
                        ...this.form,
                        department_id: parseInt(this.form.department_id),
                        main_branch_id: parseInt(this.form.main_branch_id),
                        address: this.buildAddress(),
                    };
                    delete body.province;
                    delete body.district;
                    delete body.ward;

                    if (this.editingEmployee) {
                        res = await fetch(`/api/hr/employees/${this.editingEmployee.id}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(body)
                        });
                    } else {
                        if (!this.form.employee_id?.trim()) { this.showToast('Vui lòng nhập mã nhân viên (VD: NV099).', 'error'); this.saving = false; return; }
                        res = await fetch('/api/hr/employees', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(body)
                        });
                    }

                    const data = await res.json();
                    if (!res.ok) {
                        this.showToast(data.detail || 'Có lỗi xảy ra.', 'error');
                        return;
                    }

                    if (this.editingEmployee) {
                        const idx = this.allEmployees.findIndex(e => e.id === this.editingEmployee.id);
                        if (idx !== -1) this.allEmployees[idx] = data.employee;
                    } else {
                        this.allEmployees.push(data.employee);
                    }

                    this.computeStats();
                    this.applyFilters();
                    this.showEmployeeModal = false;
                    this.showToast(this.editingEmployee ? 'Đã cập nhật thông tin nhân viên!' : 'Đã thêm nhân viên mới!', 'success');
                } catch (e) {
                    this.showToast('Lỗi kết nối: ' + e.message, 'error');
                } finally {
                    this.saving = false;
                }
            },

            // ===========================================================
            // TOGGLE ACTIVE
            // ===========================================================
            async toggleActive(emp) {
                const action = emp.is_active ? 'vô hiệu hoá' : 'kích hoạt lại';
                if (!confirm(`Bạn có chắc muốn ${action} nhân viên "${emp.name}"?`)) return;

                try {
                    const res = await fetch(`/api/hr/employees/${emp.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ is_active: !emp.is_active })
                    });
                    const data = await res.json();
                    if (!res.ok) { this.showToast(data.detail || 'Lỗi cập nhật.', 'error'); return; }

                    const idx = this.allEmployees.findIndex(e => e.id === emp.id);
                    if (idx !== -1) this.allEmployees[idx] = data.employee;
                    this.computeStats();
                    this.applyFilters();
                    this.showToast(`Đã ${action} nhân viên ${emp.name}.`, 'success');
                } catch (e) {
                    this.showToast('Lỗi kết nối.', 'error');
                }
            },

            // ===========================================================
            // RESET PASSWORD
            // ===========================================================
            async doResetPassword() {
                if (!this.newPassword || this.newPassword.length < 4) {
                    this.showToast('Mật khẩu phải có ít nhất 4 ký tự.', 'error'); return;
                }
                this.saving = true;
                try {
                    const res = await fetch(`/api/hr/employees/${this.passwordTarget.id}/reset-password`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ new_password: this.newPassword })
                    });
                    const data = await res.json();
                    if (!res.ok) { this.showToast(data.detail || 'Lỗi.', 'error'); return; }
                    this.showPasswordModal = false;
                    this.showToast(data.message || 'Đã đặt lại mật khẩu thành công!', 'success');
                } catch (e) {
                    this.showToast('Lỗi kết nối.', 'error');
                } finally {
                    this.saving = false;
                }
            },

            // ===========================================================
            // UPDATE BRANCH
            // ===========================================================
            async doUpdateBranch() {
                if (!this.branchNewName?.trim()) {
                    this.showToast('Tên chi nhánh không được để trống.', 'error'); return;
                }
                this.saving = true;
                try {
                    const res = await fetch(`/api/hr/branches/${this.editingBranch.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: this.branchNewName.trim() })
                    });
                    const data = await res.json();
                    if (!res.ok) { this.showToast(data.detail || 'Lỗi.', 'error'); return; }

                    const idx = this.branches.findIndex(b => b.id === this.editingBranch.id);
                    if (idx !== -1) this.branches[idx].name = data.branch.name;
                    this.allEmployees.forEach(e => {
                        if (e.main_branch_id === this.editingBranch.id) {
                            e.branch_name = data.branch.name;
                        }
                    });
                    this.applyFilters();
                    this.showBranchModal = false;
                    this.showToast(data.message || 'Đã đổi tên chi nhánh!', 'success');
                } catch (e) {
                    this.showToast('Lỗi kết nối.', 'error');
                } finally {
                    this.saving = false;
                }
            },

            // ===========================================================
            // TOAST
            // ===========================================================
            showToast(message, type = 'success') {
                this.toast = { show: true, message, type };
                setTimeout(() => { this.toast.show = false; }, 3500);
            },
        }
    }
