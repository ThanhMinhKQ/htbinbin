import initialState from '../shared/state.js?v=3.2';
import utils from './utils.js?v=3.2-pagination';
import requests from './requests.js?v=3.2';
import approvals from './approvals.js?v=3.5';
import imports from './imports.js?v=3.2';
import exports from './exports.js?v=3.2';
import overview from './overview.js?v=3.2-shift';

function inventoryManagerApp(totalRecords, currentPage, totalPages) {
    return {
        ...initialState(totalRecords, currentPage, totalPages, {
            storageKey: 'manager_currentTab',
            defaultTab: 'overview',
            validTabs: ['requests', 'approvals', 'import', 'export', 'overview'],
        }),
        ...utils,
        ...requests,
        ...approvals,
        ...imports,
        ...exports,
        ...overview,

        initApp() {
            // Khi mở "Quản lý kho" luôn land ở tab "Tổng quan", không nhớ tab cũ.
            try { localStorage.removeItem('manager_currentTab'); } catch (_) {}
            this.currentTab = 'overview';

            this.$watch('currentTab', (newTab) => {
                localStorage.setItem('manager_currentTab', newTab);
            });

            this.$watch('pendingCount', (newVal) => {
                window.dispatchEvent(new CustomEvent('inventory:set-pending-count', { detail: newVal }));
            });

            try {
                let rawProducts = [];
                let rawCategories = [];

                if (window.PRODUCT_DB) rawProducts = window.PRODUCT_DB;
                if (window.CATEGORY_DB) rawCategories = window.CATEGORY_DB;
                if (window.CURRENT_WAREHOUSE_ID) this.currentWarehouseId = window.CURRENT_WAREHOUSE_ID;
                if (window.WAREHOUSES_DB) this.allWarehouses = window.WAREHOUSES_DB;
                if (window.BRANCHES_DB) this.branches = window.BRANCHES_DB;

                if (this.currentWarehouseId && this.allWarehouses.length > 0) {
                    const cw = this.allWarehouses.find(w => w.id == this.currentWarehouseId);
                    if (cw) {
                        if (!cw.branch_id || cw.is_headoffice || cw.branch_name === 'Kho Tổng' || (cw.type === 'MAIN')) {
                            this.isCurrentWarehouseMain = true;
                        }
                    }
                }

                this.normalizedCategories = rawCategories.map(c => ({
                    id: String(c.id),
                    name: c.name
                }));

                this.normalizedProducts = rawProducts.map(p => ({
                    ...p,
                    id: String(p.id),
                    category_id: (p.category_id !== null && p.category_id !== undefined) ? String(p.category_id) : 'OTHER',
                }));

                this.categoryList = this.normalizedCategories;
                this.productList = this.normalizedProducts;

            } catch (e) { console.error("Error initializing app data", e); }

            setTimeout(() => {
                this.updateSortIndicators();
            }, 0);

            if (window.INITIAL_RECORDS) {
                if (window.INITIAL_RECORDS.records) {
                    this.historyList = window.INITIAL_RECORDS.records;
                    this.totalRecords = window.INITIAL_RECORDS.totalRecords || 0;
                    this.totalPages = window.INITIAL_RECORDS.totalPages || 1;
                } else if (Array.isArray(window.INITIAL_RECORDS)) {
                    this.historyList = window.INITIAL_RECORDS;
                    this.totalRecords = window.INITIAL_RECORDS.length;
                    this.totalPages = 1;
                }
            }

            if (this.currentWarehouseId) {
                this._pageLoad();
            }
        },

        async _pageLoad() {
            if (!this.currentWarehouseId) return;
            const { dateFrom, dateTo } = this.getMonthDateRange();

            try {
                const res = await fetch(
                    `/api/inventory/page-load?warehouse_id=${this.currentWarehouseId}&date_from=${dateFrom}&date_to=${dateTo}&overview_date_from=${dateFrom}&overview_date_to=${dateTo}`,
                    { credentials: 'same-origin' }
                );
                if (!res.ok) return;
                const d = await res.json();

                // Approvals
                if (d.approvals) {
                    this.approvalsList = d.approvals.records || [];
                    this.totalApprovalRecords = d.approvals.totalRecords || 0;
                    this.totalApprovalPages = d.approvals.totalPages || 1;
                    this.pendingCount = d.approvals.pendingCount || 0;
                }

                // Imports
                if (d.imports) {
                    this.importsList = d.imports.records || [];
                    this.totalImportPages = d.imports.totalPages || 1;
                    this.totalImportRecords = d.imports.totalRecords || this.importsList.length || 0;
                }

                // Overview stats
                if (d.stats) {
                    this.stats = this.stats || {};
                    this.stats.totalRequests = d.stats.requests?.total || 0;
                    this.stats.pendingRequests = d.stats.requests?.pending || 0;
                    this.stats.shippingRequests = d.stats.requests?.shipping || 0;
                    this.stats.completedRequests = d.stats.requests?.completed || 0;
                    this.stats.totalImports = d.stats.imports?.total || 0;
                    this.stats.totalImportAmount = d.stats.imports?.total_amount || 0;
                    this.stats.totalExports = d.stats.exports?.total || 0;
                    this.stats.totalSalesAmount = d.stats.sales?.total_amount || 0;
                    this.stats.cashflow = d.stats.cashflow || {
                        inflow: this.stats.totalSalesAmount,
                        outflow: this.stats.totalImportAmount,
                        net: this.stats.totalSalesAmount - this.stats.totalImportAmount
                    };
                }

                // Lazy load non-active tabs after primary data is ready
                const tab = this.currentTab;
                if (tab === 'overview') {
                    setTimeout(() => this.initOverview(), 100);
                } else if (tab === 'approvals') {
                    setTimeout(() => this.fetchApprovals(), 100);
                } else if (tab === 'import') {
                    setTimeout(() => this.fetchImports(1), 100);
                } else if (tab === 'export') {
                    setTimeout(() => this.fetchExports(1), 100);
                } else {
                    setTimeout(() => this.fetchPendingApprovals(), 100);
                    setTimeout(() => this.fetchStockOnly(), 2000);
                }

            } catch (e) {
                console.error('Page load error:', e);
                // Fallback to individual requests
                this.fetchPendingApprovals();
                this.fetchImports(1);
                this.initOverview();
            }
        },
    };
}

export { inventoryManagerApp };
window.inventoryManagerApp = inventoryManagerApp;
