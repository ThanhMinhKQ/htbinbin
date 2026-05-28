export default function(config = {}) {
    return {
    stats: {
        totalRequests: 0,
        pendingRequests: 0,
        shippingRequests: 0,
        completedRequests: 0,
        stockWarningCount: 0,
        stockWarningPercentage: 0,
        totalImports: 0,
        totalImportAmount: 0,
        recentImportsCount: 0,
        totalExports: 0,
        totalSalesAmount: 0
    },
    groupedStocks: {},
    stockSearch: '', // Search term for filtering stocks
    selectedCategory: '', // Selected category filter (empty = 'Tất cả')
    stockStatusFilter: 'ALL', // ALL | STABLE | WARNING
    stockSortField: '', // '', 'product_name', 'categoryName', 'quantity', 'total_import', 'total_export', 'status'
    stockSortDir: 'asc', // 'asc' | 'desc'
    stockViewMode: 'list',
    selectedMonth: new Date().getMonth() + 1, // 1-12 (kept for backward compat / stock-list gating)
    selectedYear: new Date().getFullYear(),
    selectedMonthInput: `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`, // For input type="month" (YYYY-MM format)
    overviewDateFrom: '', // YYYY-MM-DD; default = first day of current month
    overviewDateTo: '',   // YYYY-MM-DD; default = today
    loadingOverview: true,

    // Product History Modal State
    isHistoryModalOpen: false,
    viewingHistoryProduct: null,
    loadingHistory: false,
    productHistoryList: [],
    historyFilterType: 'ALL', // ALL, IMPORT, EXPORT, ADJUSTMENT

    // Shift Sales Quick View State
    isShiftSalesModalOpen: false,
    loadingShiftSales: false,
    shiftSalesStaff: [],
    shiftSalesTargetUserId: null,
    shiftSales: {
        shift: null,
        actor: null,
        items: [],
        transactions: [],
        totals: { total_qty: 0, total_amount: 0, tx_count: 0 },
    },

    transactionTypeMap: {
        'IMPORT_PO': 'Nhập từ NCC',
        'IMPORT_TRANSFER': 'Nhập chuyển kho',
        'EXPORT_TRANSFER': 'Xuất chuyển kho',
        'EXPORT_SERVICE': 'Xuất dịch vụ PMS',
        'VOID_SERVICE': 'Hoàn kho (void dịch vụ)',
        'ADJUSTMENT': 'Cân chỉnh / Kiểm kê',
        'TRANSIT_TO_DEST': 'Chuyển từ kho vận chuyển',
        'TRANSFER_TO_TRANSIT': 'Xuất sang kho vận chuyển'
    },

    // Get list of available categories for the filter dropdown
    getAvailableCategories() {
        const categories = Object.keys(this.groupedStocks).sort((a, b) => {
            if (a === 'Khác') return 1;
            if (b === 'Khác') return -1;
            return a.localeCompare(b);
        });
        return ['Tất cả', ...categories];
    },

    matchesStockStatusFilter(item) {
        if (this.stockStatusFilter === 'ALL') return true;
        const isWarning = item.status === 'Cảnh báo';
        if (this.stockStatusFilter === 'WARNING') return isWarning;
        if (this.stockStatusFilter === 'STABLE') return !isWarning;
        return true;
    },

    getStockCountByStatus(status) {
        if (!this.stocks) return 0;
        if (status === 'ALL') return this.stocks.length;
        if (status === 'WARNING') return this.stocks.filter(s => s.status === 'Cảnh báo').length;
        if (status === 'STABLE') return this.stocks.filter(s => s.status !== 'Cảnh báo').length;
        return 0;
    },

    // Function to get filtered grouped stocks (not a getter because spread operator doesn't preserve getters)
    filteredGroupedStocks() {
        let result = this.groupedStocks;

        // First, filter by category if selected
        if (this.selectedCategory && this.selectedCategory !== 'Tất cả') {
            result = {
                [this.selectedCategory]: this.groupedStocks[this.selectedCategory] || []
            };
        }

        const searchTerm = (this.stockSearch || '').toLowerCase().trim();
        const filtered = {};

        Object.keys(result).forEach(categoryName => {
            const filteredItems = result[categoryName].filter(item => {
                if (!this.matchesStockStatusFilter(item)) return false;
                if (!searchTerm) return true;
                const productName = (item.product_name || '').toLowerCase();
                const productCode = (item.product_code || '').toLowerCase();
                return productName.includes(searchTerm) || productCode.includes(searchTerm);
            });

            if (filteredItems.length > 0) {
                filtered[categoryName] = filteredItems;
            }
        });

        return filtered;
    },

    getFlatFilteredStocks() {
        const flat = Object.entries(this.filteredGroupedStocks()).flatMap(([categoryName, items]) => {
            return items.map(item => ({ ...item, categoryName }));
        });

        if (!this.stockSortField) return flat;

        const field = this.stockSortField;
        const dir = this.stockSortDir === 'desc' ? -1 : 1;
        const numericFields = ['quantity', 'total_import', 'total_export'];

        return flat.slice().sort((a, b) => {
            let av, bv;
            if (field === 'quantity') {
                av = Number(a.quantity ?? a.closing_balance ?? a.quantity_base ?? 0);
                bv = Number(b.quantity ?? b.closing_balance ?? b.quantity_base ?? 0);
            } else if (numericFields.includes(field)) {
                av = Number(a[field] ?? 0);
                bv = Number(b[field] ?? 0);
            } else {
                av = (a[field] ?? '').toString().toLowerCase();
                bv = (b[field] ?? '').toString().toLowerCase();
            }
            if (av < bv) return -1 * dir;
            if (av > bv) return 1 * dir;
            return 0;
        });
    },

    setStockSort(field) {
        if (this.stockSortField === field) {
            if (this.stockSortDir === 'asc') {
                this.stockSortDir = 'desc';
            } else if (this.stockSortDir === 'desc') {
                this.stockSortField = '';
                this.stockSortDir = 'asc';
            }
        } else {
            this.stockSortField = field;
            this.stockSortDir = 'asc';
        }
    },

    getStockSortIcon(field) {
        if (this.stockSortField !== field) return '↕';
        return this.stockSortDir === 'asc' ? '↑' : '↓';
    },

    getCashInflow() {
        return Number(this.stats.cashflow?.inflow ?? this.stats.totalSalesAmount ?? 0);
    },

    getCashOutflow() {
        return Number(this.stats.cashflow?.outflow ?? this.stats.totalImportAmount ?? 0);
    },

    getNetCashflow() {
        return Number(this.stats.cashflow?.net ?? (this.getCashInflow() - this.getCashOutflow()));
    },

    getCashflowWidth(value) {
        const max = Math.max(Math.abs(this.getCashInflow()), Math.abs(this.getCashOutflow()), Math.abs(this.getNetCashflow()), 1);
        return `${Math.max(8, Math.round((Math.abs(Number(value) || 0) / max) * 100))}%`;
    },

    getStockProgress(item) {
        const qty = Number(item.quantity ?? item.closing_balance ?? item.quantity_base ?? 0);
        const min = Number(item.min_stock ?? 0);
        if (min <= 0) return qty > 0 ? 100 : 0;
        return Math.min(100, Math.round((qty / Math.max(min * 2, 1)) * 100));
    },

    getStockStatusClass(item) {
        return item.status === 'Cảnh báo'
            ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-700/50'
            : 'bg-teal-100 dark:bg-teal-900/40 text-teal-800 dark:text-teal-300 border border-teal-200 dark:border-teal-700/50';
    },

    isOverviewMainScope() {
        return Boolean(this.isCurrentWarehouseMain || this.isCurrentBranchAdmin);
    },

    // Check if the date range covers the entire current month (for stock-list gating)
    isCurrentMonth() {
        const now = new Date();
        const todayStr = this.formatLocalDate(now);
        if (this.overviewDateTo && this.overviewDateTo !== todayStr) {
            const toDate = new Date(this.overviewDateTo);
            if (toDate.getFullYear() !== now.getFullYear() || toDate.getMonth() !== now.getMonth()) {
                return false;
            }
        }
        return this.selectedMonth === (now.getMonth() + 1) && this.selectedYear === now.getFullYear();
    },

    formatLocalDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    },

    formatVietnameseDate(dateStr) {
        if (!dateStr) return '';
        const [y, m, d] = dateStr.split('-');
        return `${d}/${m}/${y}`;
    },

    getOverviewRangeLabel() {
        if (!this.overviewDateFrom || !this.overviewDateTo) return '';
        if (this.overviewDateFrom === this.overviewDateTo) {
            return this.formatVietnameseDate(this.overviewDateFrom);
        }
        return `${this.formatVietnameseDate(this.overviewDateFrom)} → ${this.formatVietnameseDate(this.overviewDateTo)}`;
    },

    ensureOverviewRangeDefaults() {
        if (this.overviewDateFrom && this.overviewDateTo) return;
        const now = new Date();
        const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
        this.overviewDateFrom = this.formatLocalDate(firstDay);
        this.overviewDateTo = this.formatLocalDate(now);
    },

    syncMonthFromRange() {
        if (!this.overviewDateFrom) return;
        const [y, m] = this.overviewDateFrom.split('-');
        this.selectedYear = Number(y);
        this.selectedMonth = Number(m);
        this.selectedMonthInput = `${y}-${m}`;
    },

    normalizeOverviewMonth() {
        this.ensureOverviewRangeDefaults();
        this.syncMonthFromRange();
    },

    async initOverview() {
        if (!this.currentBranchId && !this.currentWarehouseId) {
            this.loadingOverview = false;
            return;
        }
        this.normalizeOverviewMonth();
        await this.fetchOverview();
    },

    getMonthDateRange() {
        this.ensureOverviewRangeDefaults();
        this.syncMonthFromRange();
        return {
            dateFrom: this.overviewDateFrom,
            dateTo: this.overviewDateTo
        };
    },

    onOverviewRangeChange() {
        if (this.overviewDateFrom && this.overviewDateTo && this.overviewDateFrom > this.overviewDateTo) {
            const tmp = this.overviewDateFrom;
            this.overviewDateFrom = this.overviewDateTo;
            this.overviewDateTo = tmp;
            this._syncRangePickers();
        }
        this.syncMonthFromRange();
        this.fetchOverview();
    },

    _parseISODate(iso) {
        if (!iso) return null;
        const [y, m, d] = iso.split('-').map(Number);
        return new Date(y, (m || 1) - 1, d || 1);
    },

    _syncRangePickers() {
        if (this._overviewPickerFrom && this.overviewDateFrom) {
            this._overviewPickerFrom.setDate(this._parseISODate(this.overviewDateFrom), false);
        }
        if (this._overviewPickerTo && this.overviewDateTo) {
            this._overviewPickerTo.setDate(this._parseISODate(this.overviewDateTo), false);
        }
    },

    initOverviewRangePickers(rootEl) {
        if (typeof flatpickr === 'undefined') return;
        this.ensureOverviewRangeDefaults();
        const fromInput = rootEl.querySelector('[data-overview-date="from"]');
        const toInput = rootEl.querySelector('[data-overview-date="to"]');
        if (!fromInput || !toInput) return;

        const locale = (flatpickr.l10ns && flatpickr.l10ns.vn) ? 'vn' : 'default';
        const common = {
            dateFormat: 'd/m/Y',
            allowInput: false,
            locale,
        };

        if (this._overviewPickerFrom) this._overviewPickerFrom.destroy();
        if (this._overviewPickerTo) this._overviewPickerTo.destroy();

        this._overviewPickerFrom = flatpickr(fromInput, {
            ...common,
            defaultDate: this._parseISODate(this.overviewDateFrom),
            onChange: (dates) => {
                if (!dates.length) return;
                this.overviewDateFrom = this.formatLocalDate(dates[0]);
                if (this._overviewPickerTo) this._overviewPickerTo.set('minDate', this._parseISODate(this.overviewDateFrom));
                this.onOverviewRangeChange();
            }
        });
        this._overviewPickerTo = flatpickr(toInput, {
            ...common,
            defaultDate: this._parseISODate(this.overviewDateTo),
            minDate: this._parseISODate(this.overviewDateFrom),
            onChange: (dates) => {
                if (!dates.length) return;
                this.overviewDateTo = this.formatLocalDate(dates[0]);
                this.onOverviewRangeChange();
            }
        });
    },

    updateMonth() {
        // Backward compat for any month input still wired
        const match = String(this.selectedMonthInput || '').match(/^(\d{4})-(\d{2})$/);
        if (!match) return;
        const y = Number(match[1]);
        const m = Number(match[2]);
        const now = new Date();
        const firstDay = new Date(y, m - 1, 1);
        const lastDay = new Date(y, m, 0);
        const isCurrent = (y === now.getFullYear() && m === (now.getMonth() + 1));
        this.overviewDateFrom = this.formatLocalDate(firstDay);
        this.overviewDateTo = this.formatLocalDate(isCurrent ? now : lastDay);
        this.syncMonthFromRange();
        this.fetchOverview();
    },

    resetToCurrentMonth() {
        const now = new Date();
        const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
        this.overviewDateFrom = this.formatLocalDate(firstDay);
        this.overviewDateTo = this.formatLocalDate(now);
        this.syncMonthFromRange();
        this._syncRangePickers();
        this.stockSearch = '';
        this.selectedCategory = '';
        this.fetchOverview();
    },

    async fetchOverview() {
        if (!this.currentBranchId && !this.currentWarehouseId) {
            this.loadingOverview = false;
            return;
        }
        this.loadingOverview = true;
        const { dateFrom, dateTo } = this.getMonthDateRange();
        const wh = this.currentWarehouseId;
        const br = this.currentBranchId;
        const param = wh ? `warehouse_id=${wh}` : `branch_id=${br}`;

        try {
            if (wh) {
                const combinedRes = await fetch(`/api/inventory/overview-combined?warehouse_id=${wh}&date_from=${dateFrom}&date_to=${dateTo}`);
                if (combinedRes.ok) {
                    const json = await combinedRes.json();
                    this.stocks = (json.stock?.data || []).map(s => ({
                        ...s,
                        quantity: s.closing_balance ?? s.quantity_base ?? 0
                    }));
                    this.groupStocksByCategory();

                    const data = json.stats || {};
                    this.stats.totalRequests = data.requests?.total || 0;
                    this.stats.pendingRequests = data.requests?.pending || 0;
                    this.stats.shippingRequests = data.requests?.shipping || 0;
                    this.stats.completedRequests = data.requests?.completed || 0;
                    this.stats.totalImports = data.imports?.total || 0;
                    this.stats.totalImportAmount = data.imports?.total_amount || 0;
                    this.stats.recentImportsCount = data.imports?.total || 0;
                    this.stats.totalExports = data.exports?.total || 0;
                    this.stats.totalSalesAmount = data.sales?.total_amount || 0;
                    this.stats.cashflow = data.cashflow || {
                        inflow: this.stats.totalSalesAmount,
                        outflow: this.stats.totalImportAmount,
                        net: this.stats.totalSalesAmount - this.stats.totalImportAmount
                    };

                    const warningCount = this.stocks.filter(s => s.status === 'Cảnh báo').length;
                    this.stats.stockWarningCount = warningCount;
                    this.stats.stockWarningPercentage = this.stocks.length > 0
                        ? Math.round((warningCount / this.stocks.length) * 100) : 0;
                    return;
                }
            }

            const [stockRes, statsRes] = await Promise.all([
                fetch(`/api/inventory/report-realtime?${param}`),
                fetch(`/api/inventory/dashboard-stats?${param}&date_from=${dateFrom}&date_to=${dateTo}`)
            ]);

            if (stockRes.ok) {
                const json = await stockRes.json();
                this.stocks = (json.data || []).map(s => ({
                    ...s,
                    quantity: s.quantity_base
                }));
                this.groupStocksByCategory();
                const warningCount = this.stocks.filter(s => s.status === 'Cảnh báo').length;
                this.stats.stockWarningCount = warningCount;
                this.stats.stockWarningPercentage = this.stocks.length > 0
                    ? Math.round((warningCount / this.stocks.length) * 100) : 0;
            }

            if (statsRes.ok) {
                const data = await statsRes.json();
                this.stats.totalRequests = data.requests?.total || 0;
                this.stats.pendingRequests = data.requests?.pending || 0;
                this.stats.shippingRequests = data.requests?.shipping || 0;
                this.stats.completedRequests = data.requests?.completed || 0;
                this.stats.totalImports = data.imports?.total || 0;
                this.stats.totalImportAmount = data.imports?.total_amount || 0;
                this.stats.recentImportsCount = data.imports?.total || 0;
                this.stats.totalExports = data.exports?.total || 0;
                this.stats.totalSalesAmount = data.sales?.total_amount || 0;
                this.stats.cashflow = data.cashflow || {
                    inflow: this.stats.totalSalesAmount,
                    outflow: this.stats.totalImportAmount,
                    net: this.stats.totalSalesAmount - this.stats.totalImportAmount
                };
            }
        } catch (e) {
            console.error("Error fetching overview:", e);
        } finally {
            this.loadingOverview = false;
        }
    },

    async fetchStock() {
        return this.fetchOverview();
    },

    async fetchStockOnly() {
        if (!this.currentWarehouseId && !this.currentBranchId) return;
        const wh = this.currentWarehouseId;
        const br = this.currentBranchId;
        const param = wh ? `warehouse_id=${wh}` : `branch_id=${br}`;
        try {
            const res = await fetch(`/api/inventory/report-realtime?${param}`);
            if (res.ok) {
                const json = await res.json();
                this.stocks = (json.data || []).map(s => ({
                    ...s,
                    quantity: s.quantity_base
                }));
                this.groupStocksByCategory();
                const warningCount = this.stocks.filter(s => s.status === 'Cảnh báo').length;
                this.stats.stockWarningCount = warningCount;
                this.stats.stockWarningPercentage = this.stocks.length > 0
                    ? Math.round((warningCount / this.stocks.length) * 100) : 0;
            }
        } catch (e) {
            console.error("Error fetching stock:", e);
        }
    },

    async fetchDashboardStats() {
        return this.fetchOverview();
    },

    getMaxRequestCount() {
        return Math.max(
            this.stats.totalRequests,
            this.stats.pendingRequests + this.stats.shippingRequests + this.stats.completedRequests
        ) || 1; // Avoid division by zero
    },

    groupStocksByCategory() {
        // 1. Pre-compute lookups for O(1) access
        const productMap = new Map();
        if (this.normalizedProducts) {
            this.normalizedProducts.forEach(p => {
                productMap.set(p.code, p);
                productMap.set(String(p.id), p);
            });
        }
        // Fallback to productList if normalizedProducts isn't populated or different structure
        if (this.productList && productMap.size === 0) {
            this.productList.forEach(p => {
                productMap.set(p.code, p);
                productMap.set(String(p.id), p);
            });
        }

        const categoryMap = new Map();
        if (this.categoryList) {
            this.categoryList.forEach(c => categoryMap.set(String(c.id), c.name));
        }

        // 2. Iterate stocks once
        const groups = {};
        this.stocks.forEach(item => {
            let catName = 'Khác';

            // Try lookup by ID first, then code
            let product = null;
            if (item.product_id) product = productMap.get(String(item.product_id));
            if (!product && item.product_code) product = productMap.get(item.product_code);

            if (product) {
                const catId = product.category_id;
                if (catId && catId !== 'OTHER') {
                    const name = categoryMap.get(String(catId));
                    if (name) catName = name;
                }
                // Enrich item with product details for display
                item.base_unit = product.base_unit;
                item.packing_unit = product.packing_unit;
                item.conversion_rate = product.conversion_rate;
            }

            if (!groups[catName]) {
                groups[catName] = [];
            }
            groups[catName].push(item);
        });

        // 3. Sort Keys and Items
        this.groupedStocks = Object.keys(groups).sort((a, b) => {
            if (a === 'Khác') return 1;
            if (b === 'Khác') return -1;
            return a.localeCompare(b);
        }).reduce((obj, key) => {
            // Sort items within category by name
            obj[key] = groups[key].sort((a, b) => (a.product_name || '').localeCompare(b.product_name || ''));
            return obj;
        }, {});
    },

    async openProductHistory(item) {
        if (!item || !item.product_id) return;

        this.viewingHistoryProduct = item;
        this.isHistoryModalOpen = true;
        this.loadingHistory = true;
        this.productHistoryList = [];
        this.historyFilterType = 'ALL'; // Reset filter

        try {
            const scope = this.currentWarehouseId
                ? `warehouse_id=${this.currentWarehouseId}`
                : `branch_id=${this.currentBranchId || ''}`;
            const url = `/api/inventory/product-history?product_id=${item.product_id}&${scope}`;
            const res = await fetch(url);
            if (res.ok) {
                this.productHistoryList = await res.json();
            } else {
                console.error("Failed to load product history");
            }
        } catch (e) {
            console.error("Error fetching product history:", e);
        } finally {
            this.loadingHistory = false;
        }
    },

    getLocalizedTransactionType(type) {
        return this.transactionTypeMap[type] || type;
    },

    getFilteredHistory() {
        if (this.historyFilterType === 'ALL') {
            return this.productHistoryList;
        }

        return this.productHistoryList.filter(h => {
            if (this.historyFilterType === 'IMPORT') {
                return ['IMPORT_PO', 'IMPORT_TRANSFER', 'TRANSIT_TO_DEST'].includes(h.type) || (h.type === 'ADJUSTMENT' && h.quantity_change > 0);
            }
            if (this.historyFilterType === 'EXPORT') {
                return ['EXPORT_TRANSFER', 'TRANSFER_TO_TRANSIT', 'EXPORT_SERVICE', 'VOID_SERVICE'].includes(h.type) || (h.type === 'ADJUSTMENT' && h.quantity_change < 0);
            }
            return h.type === this.historyFilterType;
        });
    },

    resetStockFilters() {
        this.selectedCategory = '';
        this.stockSearch = '';
        this.stockStatusFilter = 'ALL';
        this.stockSortField = '';
        this.stockSortDir = 'asc';
    },

    exportStockToExcel() {
        const rows = this.getFlatFilteredStocks();
        if (!rows.length) {
            alert('Không có dữ liệu để xuất.');
            return;
        }
        if (typeof XLSX === 'undefined') {
            alert('Thư viện xuất Excel chưa tải xong, vui lòng thử lại.');
            return;
        }

        const warehouseName = (this.allWarehouses || []).find(w => String(w.id) === String(this.currentWarehouseId))?.name || 'Kho';
        const monthLabel = this.selectedMonthInput || '';
        const exportedAt = new Date().toLocaleString('vi-VN');

        // Build data rows
        const headers = ['STT', 'Mã SP', 'Tên sản phẩm', 'Nhóm', 'Tồn kho', 'Đơn vị', 'Nhập', 'Xuất', 'Trạng thái'];
        const dataRows = rows.map((item, i) => [
            i + 1,
            item.product_code || '',
            item.product_name || '',
            item.categoryName || '',
            item.display_quantity !== undefined ? item.display_quantity : (item.quantity ?? 0),
            item.base_unit || '',
            item.total_import ?? 0,
            item.total_export ?? 0,
            item.status || '',
        ]);

        // Title rows
        const titleRows = [
            [`BÁO CÁO TỒN KHO — ${warehouseName.toUpperCase()}`],
            [`Kỳ: ${monthLabel}   |   Xuất lúc: ${exportedAt}`],
            [],
            headers,
            ...dataRows,
        ];

        const ws = XLSX.utils.aoa_to_sheet(titleRows);

        // Column widths
        ws['!cols'] = [
            { wch: 5 },   // STT
            { wch: 22 },  // Mã SP
            { wch: 36 },  // Tên SP
            { wch: 28 },  // Nhóm
            { wch: 12 },  // Tồn kho
            { wch: 10 },  // Đơn vị
            { wch: 10 },  // Nhập
            { wch: 10 },  // Xuất
            { wch: 12 },  // Trạng thái
        ];

        // Merge title cells A1:I1 and A2:I2
        ws['!merges'] = [
            { s: { r: 0, c: 0 }, e: { r: 0, c: 8 } },
            { s: { r: 1, c: 0 }, e: { r: 1, c: 8 } },
        ];

        // Style helpers
        const titleStyle = {
            font: { bold: true, sz: 14, color: { rgb: '1A5276' } },
            alignment: { horizontal: 'center', vertical: 'center' },
            fill: { fgColor: { rgb: 'D6EAF8' } },
        };
        const subtitleStyle = {
            font: { sz: 10, italic: true, color: { rgb: '555555' } },
            alignment: { horizontal: 'center' },
        };
        const headerStyle = {
            font: { bold: true, sz: 10, color: { rgb: 'FFFFFF' } },
            fill: { fgColor: { rgb: '1A5276' } },
            alignment: { horizontal: 'center', vertical: 'center', wrapText: true },
            border: {
                top: { style: 'thin', color: { rgb: 'AAAAAA' } },
                bottom: { style: 'thin', color: { rgb: 'AAAAAA' } },
                left: { style: 'thin', color: { rgb: 'AAAAAA' } },
                right: { style: 'thin', color: { rgb: 'AAAAAA' } },
            },
        };
        const cellBorder = {
            border: {
                top: { style: 'thin', color: { rgb: 'DDDDDD' } },
                bottom: { style: 'thin', color: { rgb: 'DDDDDD' } },
                left: { style: 'thin', color: { rgb: 'DDDDDD' } },
                right: { style: 'thin', color: { rgb: 'DDDDDD' } },
            },
        };
        const warningStyle = {
            ...cellBorder,
            fill: { fgColor: { rgb: 'FEF9E7' } },
            font: { color: { rgb: 'B7770D' } },
        };
        const evenRowStyle = {
            ...cellBorder,
            fill: { fgColor: { rgb: 'F4F6F7' } },
        };

        // Apply title styles
        if (ws['A1']) ws['A1'].s = titleStyle;
        if (ws['A2']) ws['A2'].s = subtitleStyle;

        // Apply header row styles (row index 3 = 0-based row 3)
        headers.forEach((_, ci) => {
            const addr = XLSX.utils.encode_cell({ r: 3, c: ci });
            if (ws[addr]) ws[addr].s = headerStyle;
        });

        // Apply data row styles
        dataRows.forEach((row, ri) => {
            const isWarning = row[8] === 'Cảnh báo';
            const isEven = ri % 2 === 1;
            row.forEach((_, ci) => {
                const addr = XLSX.utils.encode_cell({ r: ri + 4, c: ci });
                if (!ws[addr]) return;
                if (isWarning) {
                    ws[addr].s = warningStyle;
                } else if (isEven) {
                    ws[addr].s = evenRowStyle;
                } else {
                    ws[addr].s = cellBorder;
                }
            });
        });

        // Row heights
        ws['!rows'] = [
            { hpt: 28 }, // title
            { hpt: 16 }, // subtitle
            { hpt: 6 },  // spacer
            { hpt: 22 }, // header
        ];

        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, 'Tồn kho');

        const fileName = `ton-kho_${warehouseName}_${monthLabel}.xlsx`.replace(/\s+/g, '-');
        XLSX.writeFile(wb, fileName);
    },

    openReference(item) {
        if (!item.ref_ticket_id) return;

        if (item.ref_ticket_type === 'IMPORT_PO') {
            // Close history modal first
            this.closeHistoryModal();
            if (config.switchToImportOnReference) {
                this.currentTab = 'import';
            }
            this.openImportDetail(item.ref_ticket_id);
            return;
        }

        // [NEW] Handle Transfer/Request Link
        if (item.ref_ticket_type && (item.ref_ticket_type.includes('TRANSFER') || item.ref_ticket_type === 'REQ')) {
            // Close history modal
            this.closeHistoryModal();
            // Open detail
            this.fetchRequestDetail(item.ref_ticket_id);
            return;
        }

        if (item.ref_code && item.ref_code !== 'N/A') {
            // Try modern API
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(item.ref_code).then(() => {
                    alert("Đã sao chép mã phiếu: " + item.ref_code);
                }).catch(err => {
                    console.error('Could not copy text: ', err);
                    this.copyToClipboardFallback(item.ref_code);
                });
            } else {
                // Fallback
                this.copyToClipboardFallback(item.ref_code);
            }
        }
    },

    copyToClipboardFallback(text) {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.top = "0";
        textArea.style.left = "0";
        textArea.style.position = "fixed";

        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        try {
            const successful = document.execCommand('copy');
            if (successful) {
                alert("Đã sao chép mã phiếu: " + text);
            } else {
                alert("Không thể sao chép. Mã phiếu: " + text);
            }
        } catch (err) {
            console.error('Fallback: Oops, unable to copy', err);
            alert("Không thể sao chép. Mã phiếu: " + text);
        }

        document.body.removeChild(textArea);
    },

    closeHistoryModal() {
        this.isHistoryModalOpen = false;
        this.viewingHistoryProduct = null;
        this.productHistoryList = [];
    },

    isCurrentWarehouseBranch() {
        if (!this.currentWarehouseId) return false;
        const wh = (this.allWarehouses || []).find(w => String(w.id) === String(this.currentWarehouseId));
        return wh ? wh.type === 'BRANCH' : false;
    },

    // --- SHIFT SALES QUICK VIEW ---
    async openShiftSales() {
        this.isShiftSalesModalOpen = true;
        this.shiftSalesTargetUserId = null;
        this.shiftSalesStaff = [];
        await Promise.all([
            this.fetchShiftSales(),
            this.fetchShiftSalesStaff(),
        ]);
    },

    closeShiftSales() {
        this.isShiftSalesModalOpen = false;
    },

    isAdminRole() {
        const role = window.USER_ROLE || '';
        return ['boss', 'admin', 'quanly'].includes(role);
    },

    formatShiftRange(shift) {
        if (!shift || !shift.start || !shift.end) return '';
        try {
            const fmt = (iso) => new Date(iso).toLocaleString('vi-VN', {
                hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit'
            });
            return `${fmt(shift.start)} → ${fmt(shift.end)}`;
        } catch (e) {
            return '';
        }
    },

    async fetchShiftSales() {
        this.loadingShiftSales = true;
        try {
            const params = new URLSearchParams();
            if (this.currentWarehouseId) params.set('warehouse_id', this.currentWarehouseId);
            if (this.shiftSalesTargetUserId) params.set('target_user_id', this.shiftSalesTargetUserId);
            const res = await fetch(`/api/inventory/my-shift-sales?${params.toString()}`, {
                credentials: 'same-origin'
            });
            if (res.ok) {
                const data = await res.json();
                this.shiftSales = {
                    shift: data.shift || null,
                    actor: data.actor || null,
                    items: data.items || [],
                    transactions: data.transactions || [],
                    totals: data.totals || { total_qty: 0, total_amount: 0, tx_count: 0 },
                };
            } else {
                console.error('Failed to load shift sales', res.status);
            }
        } catch (e) {
            console.error('Error fetching shift sales:', e);
        } finally {
            this.loadingShiftSales = false;
        }
    },

    async fetchShiftSalesStaff() {
        if (!this.isAdminRole()) return;
        try {
            const params = new URLSearchParams();
            if (this.currentWarehouseId) params.set('warehouse_id', this.currentWarehouseId);
            const res = await fetch(`/api/inventory/shift-sales-staff?${params.toString()}`, {
                credentials: 'same-origin'
            });
            if (res.ok) {
                this.shiftSalesStaff = await res.json();
            }
        } catch (e) {
            console.error('Error fetching shift sales staff:', e);
        }
    },

    async onShiftSalesStaffChange() {
        await this.fetchShiftSales();
    },
};
}
