import initialState from './state.js?v=1.3';
import utils from './utils.js?v=1.3';
import requests from './requests.js?v=1.3';
import approvals from './approvals.js?v=1.3';
import imports from './imports.js?v=1.3';
import exports from './exports.js?v=1.3';
import overview from './overview.js?v=1.3';

function receptionRequestApp(totalRecords, currentPage, totalPages) {
    return {
        ...initialState(totalRecords, currentPage, totalPages),
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
                // Priority 1: active tab first
                if (this.currentTab === 'approvals') {
                    this.fetchApprovals();
                } else if (this.currentTab === 'import') {
                    this.fetchImports(1);
                } else if (this.currentTab === 'overview') {
                    this.initOverview();
                }

                // Priority 2: background loads staggered
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
