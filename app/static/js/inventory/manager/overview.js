export default {
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
        totalExports: 0
    },
    groupedStocks: {},
    stockSearch: '', // Search term for filtering stocks
    selectedCategory: '', // Selected category filter (empty = 'Tất cả')
    selectedMonth: new Date().getMonth() + 1, // 1-12
    selectedYear: new Date().getFullYear(),
    selectedMonthInput: '', // For input type="month" (YYYY-MM format)

    // Product History Modal State
    isHistoryModalOpen: false,
    viewingHistoryProduct: null,
    loadingHistory: false,
    loadingHistory: false,
    productHistoryList: [],
    historyFilterType: 'ALL', // ALL, IMPORT, EXPORT, ADJUSTMENT

    transactionTypeMap: {
        'IMPORT_PO': 'Nhập từ NCC',
        'IMPORT_TRANSFER': 'Nhập chuyển kho',
        'EXPORT_TRANSFER': 'Xuất chuyển kho',
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

    // Function to get filtered grouped stocks (not a getter because spread operator doesn't preserve getters)
    filteredGroupedStocks() {
        let result = this.groupedStocks;

        // First, filter by category if selected
        if (this.selectedCategory && this.selectedCategory !== 'Tất cả') {
            result = {
                [this.selectedCategory]: this.groupedStocks[this.selectedCategory] || []
            };
        }

        // Then, filter by search term if provided
        if (!this.stockSearch || this.stockSearch.trim() === '') {
            return result;
        }

        const searchTerm = this.stockSearch.toLowerCase().trim();
        const filtered = {};

        Object.keys(result).forEach(categoryName => {
            const filteredItems = result[categoryName].filter(item => {
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

    // Check if the selected month/year is the current month
    isCurrentMonth() {
        const now = new Date();
        const currentMonth = now.getMonth() + 1; // 1-12
        const currentYear = now.getFullYear();
        return this.selectedMonth === currentMonth && this.selectedYear === currentYear;
    },

    async initOverview() {
        if (!this.currentWarehouseId) return;
        // Initialize month input to current month
        const now = new Date();
        this.selectedMonthInput = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
        await this.fetchStock();
        await this.fetchDashboardStats();
    },

    getMonthDateRange() {
        const firstDay = new Date(this.selectedYear, this.selectedMonth - 1, 1);
        const lastDay = new Date(this.selectedYear, this.selectedMonth, 0);
        return {
            dateFrom: firstDay.toISOString().split('T')[0],
            dateTo: lastDay.toISOString().split('T')[0]
        };
    },

    updateMonth() {
        // Parse YYYY-MM format from input
        if (this.selectedMonthInput) {
            const [year, month] = this.selectedMonthInput.split('-');
            this.selectedYear = parseInt(year);
            this.selectedMonth = parseInt(month);
            this.fetchDashboardStats();
            this.fetchStock();
        }
    },

    resetToCurrentMonth() {
        const now = new Date();
        this.selectedMonth = now.getMonth() + 1;
        this.selectedYear = now.getFullYear();
        this.selectedMonthInput = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
        this.stockSearch = '';
        this.selectedCategory = '';
        this.stockSearch = '';
        this.selectedCategory = '';
        this.fetchDashboardStats();
        this.fetchStock();
    },

    async fetchStock() {
        if (!this.currentWarehouseId) return;

        const { dateFrom, dateTo } = this.getMonthDateRange();

        try {
            const res = await fetch(`/api/inventory/stock-summary?warehouse_id=${this.currentWarehouseId}&date_from=${dateFrom}&date_to=${dateTo}`);
            if (res.ok) {
                const json = await res.json();
                this.stocks = (json.data || []).map(s => ({
                    ...s,
                    quantity: s.closing_balance // Map closing_balance to quantity for compatibility
                }));

                this.groupStocksByCategory();

                // Calculate Stock KPIs
                const warningCount = this.stocks.filter(s => s.status === 'Cảnh báo').length;
                this.stats.stockWarningCount = warningCount;
                this.stats.stockWarningPercentage = this.stocks.length > 0
                    ? Math.round((warningCount / this.stocks.length) * 100)
                    : 0;
            }
        } catch (e) {
            console.error("Error fetching stock:", e);
        }
    },

    async fetchDashboardStats() {
        if (!this.currentWarehouseId) return;

        const { dateFrom, dateTo } = this.getMonthDateRange();

        try {
            const res = await fetch(`/api/inventory/dashboard-stats?warehouse_id=${this.currentWarehouseId}&date_from=${dateFrom}&date_to=${dateTo}`);
            if (res.ok) {
                const data = await res.json();

                // Update Request Stats
                this.stats.totalRequests = data.requests.total;
                this.stats.pendingRequests = data.requests.pending;
                this.stats.shippingRequests = data.requests.shipping;
                this.stats.completedRequests = data.requests.completed;

                // Update Import Stats
                this.stats.totalImports = data.imports.total;
                this.stats.totalImportAmount = data.imports.total_amount;
                this.stats.recentImportsCount = data.imports.total;

                // Update Export Stats
                this.stats.totalExports = (data.exports && data.exports.total) ? data.exports.total : 0;
            }
        } catch (e) {
            console.error("Error fetching dashboard stats:", e);
        }
    },

    getMaxRequestCount() {
        return Math.max(
            this.stats.totalRequests,
            this.stats.pendingRequests + this.stats.shippingRequests + this.stats.completedRequests
        ) || 1; // Avoid division by zero
    },

    groupStocksByCategory() {
        // 1. Pre-compute category lookup
        const categoryMap = new Map();
        if (this.categoryList) {
            this.categoryList.forEach(c => categoryMap.set(String(c.id), c.name));
        }

        // 2. Iterate stocks once
        const groups = {};
        this.stocks.forEach(item => {
            let catName = 'Khác';

            // Use category_id directly from API response
            if (item.category_id) {
                const name = categoryMap.get(String(item.category_id));
                if (name) catName = name;
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
            const url = `/api/inventory/product-history?product_id=${item.product_id}&warehouse_id=${this.currentWarehouseId || ''}`;
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
                return ['EXPORT_TRANSFER', 'TRANSFER_TO_TRANSIT'].includes(h.type) || (h.type === 'ADJUSTMENT' && h.quantity_change < 0);
            }
            return h.type === this.historyFilterType;
        });
    },

    resetStockFilters() {
        this.selectedCategory = '';
        this.stockSearch = '';
    },

    openReference(item) {
        if (!item.ref_ticket_id) return;

        if (item.ref_ticket_type === 'IMPORT_PO') {
            // Close history modal first
            this.closeHistoryModal();
            // Open import detail modal (stays on current tab)
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
    }
};
