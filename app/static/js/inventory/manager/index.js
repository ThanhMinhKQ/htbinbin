import initialState from './state.js?v=1.6';
import utils from './utils.js?v=1.6';
import requests from './requests.js?v=1.6';
import approvals from './approvals.js?v=1.6';
import imports from './imports.js?v=1.6';
import exports from './exports.js?v=1.6';
import overview from './overview.js?v=1.6';

function inventoryManagerApp(totalRecords, currentPage, totalPages) {
    return {
        ...initialState(totalRecords, currentPage, totalPages, {
            storageKey: 'manager_currentTab',
            validTabs: ['requests', 'approvals', 'import', 'export', 'overview'],
            isManager: true
        }),
        ...utils,
        ...requests,
        ...approvals,
        ...imports,
        ...exports,
        ...overview,

        initApp() {
            this.initCurrentTab();

            this.$watch('currentTab', (newTab) => {
                localStorage.setItem('manager_currentTab', newTab);
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
                        if (!cw.branch_id || cw.branch_name === 'Kho Tổng' || (cw.branch && ['ADMIN', 'BOSS', 'HEAD'].includes(cw.branch.code))) {
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
                this.renderPagination();
                this.updateSortIndicators();
            }, 0);

            if (window.INITIAL_RECORDS) {
                this.historyList = window.INITIAL_RECORDS;
            }

            if (this.currentWarehouseId) {
                // Single page-load request replaces 3 parallel requests
                this._pageLoad();

                // Active tab specific data
                if (this.currentTab === 'export') {
                    setTimeout(() => this.fetchExports(1), 400);
                }
            }
        },

        async _pageLoad() {
            if (!this.currentWarehouseId) return;
            const now = new Date();
            const y = now.getFullYear(), m = String(now.getMonth() + 1).padStart(2, '0');
            const lastDay = new Date(y, now.getMonth() + 1, 0).getDate();
            const dateFrom = `${y}-${m}-01`;
            const dateTo = `${y}-${m}-${lastDay}`;
            const ovFrom = new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
            const ovFromStr = `${ovFrom.getFullYear()}-${String(ovFrom.getMonth()+1).padStart(2,'0')}-${String(ovFrom.getDate()).padStart(2,'0')}`;

            try {
                const res = await fetch(
                    `/api/inventory/page-load?warehouse_id=${this.currentWarehouseId}&date_from=${dateFrom}&date_to=${dateTo}&overview_date_from=${ovFromStr}&overview_date_to=${dateTo}`,
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
                }

                // Load stock summary separately (heavier query, lower priority)
                setTimeout(() => this.fetchStock(), 100);

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
