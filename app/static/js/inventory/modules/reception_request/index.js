import initialState from '../../shared/state.js?v=3.0';
import utils from './utils.js?v=3.0';
import requests from './requests.js?v=3.0';
import approvals from './approvals.js?v=3.0';
import imports from './imports.js?v=3.0';
import exports from './exports.js?v=3.0';
import overview from './overview.js?v=3.0';

function receptionRequestApp(totalRecords, currentPage, totalPages) {
    return {
        ...initialState(totalRecords, currentPage, totalPages, {
            storageKey: 'reception_currentTab',
            defaultTab: 'overview',
            validTabs: ['requests', 'approvals', 'import', 'export', 'overview']
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
                localStorage.setItem('reception_currentTab', newTab);
            });

            try {
                let rawProducts = [];
                let rawCategories = [];

                if (window.PRODUCT_DB) rawProducts = window.PRODUCT_DB;
                if (window.CATEGORY_DB) rawCategories = window.CATEGORY_DB;
                if (window.CURRENT_BRANCH_ID) this.currentBranchId = window.CURRENT_BRANCH_ID;
                if (window.CURRENT_WAREHOUSE_ID) this.currentWarehouseId = window.CURRENT_WAREHOUSE_ID;
                if (window.INITIAL_RECORDS) {
                    if (window.INITIAL_RECORDS.records) {
                        this.historyList = window.INITIAL_RECORDS.records;
                        this.totalRecords = window.INITIAL_RECORDS.totalRecords;
                        this.totalPages = window.INITIAL_RECORDS.totalPages;
                    } else if (Array.isArray(window.INITIAL_RECORDS)) {
                        this.historyList = window.INITIAL_RECORDS;
                        this.totalRecords = this.historyList.length;
                    }
                }

                if (window.BRANCH_ID_DATA) this.currentBranchId = window.BRANCH_ID_DATA;

                if (document.getElementById('warehouses-data')) {
                    this.allWarehouses = JSON.parse(document.getElementById('warehouses-data').textContent || '[]');
                }
                if (document.getElementById('branches-data')) {
                    this.branches = JSON.parse(document.getElementById('branches-data').textContent || '[]');
                }

                if (this.currentBranchId && this.branches.length > 0) {
                    const cb = this.branches.find(b => b.id == this.currentBranchId);
                    if (cb && (cb.code.toLowerCase() === 'admin' || cb.name.toLowerCase().includes('admin'))) {
                        this.isCurrentBranchAdmin = true;
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

            if (this.currentBranchId || this.currentWarehouseId) {
                this._pageLoad();
            }
        },

        async _pageLoad() {
            const whId = this.currentWarehouseId || '';
            const dateFrom = this.filterDateFrom || '';
            const dateTo = this.filterDateTo || '';
            try {
                const res = await fetch(
                    `/api/inventory/reception-page-load?warehouse_id=${whId}&date_from=${dateFrom}&date_to=${dateTo}&overview_date_from=${dateFrom}&overview_date_to=${dateTo}`,
                    { credentials: 'same-origin' }
                );
                if (!res.ok) throw new Error('page-load failed');
                const d = await res.json();

                if (d.approvals) {
                    this.approvalsList = d.approvals.records || [];
                    this.totalApprovalRecords = d.approvals.totalRecords || 0;
                    this.totalApprovalPages = d.approvals.totalPages || 0;
                    this.pendingCount = d.approvals.pendingCount || 0;
                }
                if (d.imports) {
                    this.importsList = d.imports.records || [];
                    this.totalImportRecords = d.imports.totalRecords || 0;
                    this.totalImportPages = d.imports.totalPages || 0;
                }
                if (d.stats) {
                    this.dashboardStats = d.stats;
                }

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
                    setTimeout(() => this.fetchStockOnly(), 2000);
                }
            } catch (e) {
                console.warn('Reception page-load failed, falling back to individual calls', e);
                if (this.currentTab === 'approvals') {
                    this.fetchApprovals();
                } else if (this.currentTab === 'import') {
                    this.fetchImports(1);
                } else if (this.currentTab === 'overview') {
                    this.initOverview();
                }
                setTimeout(() => {
                    if (this.currentTab !== 'approvals') this.fetchPendingApprovals();
                }, 100);
                setTimeout(() => {
                    if (this.currentTab !== 'import') this.fetchImports(1);
                }, 200);
                setTimeout(() => {
                    if (this.currentTab !== 'overview') this.initOverview();
                }, 300);
            }
        }
    };
}

export { receptionRequestApp };
window.receptionRequestApp = receptionRequestApp;
