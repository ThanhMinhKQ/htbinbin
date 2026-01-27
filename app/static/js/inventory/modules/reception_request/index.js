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
            // [NEW] Restore tab from localStorage
            this.initCurrentTab();

            // [NEW] Watch currentTab and save to localStorage
            this.$watch('currentTab', (newTab) => {
                localStorage.setItem('reception_currentTab', newTab);
            });

            // Initialize data from global variables if available
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

                if (window.BRANCH_ID_DATA) this.currentBranchId = window.BRANCH_ID_DATA; // Fallback

                // [NEW] Load Warehouses & Branches
                if (document.getElementById('warehouses-data')) {
                    this.allWarehouses = JSON.parse(document.getElementById('warehouses-data').textContent || '[]');
                }
                if (document.getElementById('branches-data')) {
                    this.branches = JSON.parse(document.getElementById('branches-data').textContent || '[]');
                }

                // [NEW] Determine if Admin
                if (this.currentBranchId && this.branches.length > 0) {
                    const cb = this.branches.find(b => b.id == this.currentBranchId);
                    if (cb && (cb.code.toLowerCase() === 'admin' || cb.name.toLowerCase().includes('admin'))) {
                        this.isCurrentBranchAdmin = true;
                    }
                }

                // NORMALIZE DATA
                // 1. Categories
                this.normalizedCategories = rawCategories.map(c => ({
                    id: String(c.id),
                    name: c.name
                }));

                // 2. Products
                this.normalizedProducts = rawProducts.map(p => ({
                    ...p,
                    id: String(p.id),
                    category_id: (p.category_id !== null && p.category_id !== undefined) ? String(p.category_id) : 'OTHER',
                }));

                // Assign to main lists for compatibility
                this.categoryList = this.normalizedCategories;
                this.productList = this.normalizedProducts;

            } catch (e) { console.error("Error initializing app data", e); }

            setTimeout(() => {
                this.renderPagination();
                this.updateSortIndicators();
            }, 0);
            if (this.currentBranchId) {
                this.initOverview();
                this.fetchPendingApprovals();
                this.fetchImports(1);

                // [NEW] Fetch data for restored tab
                if (this.currentTab === 'approvals') {
                    this.fetchApprovals();
                }
                // Note: 'requests' data is already loaded from INITIAL_RECORDS
                // 'import' is already fetched above
                // 'overview' is already initialized above
            }
        }
    };
}

// Export for dynamic import usage
export { receptionRequestApp };

// Keep window assignment for debugging or fallback
window.receptionRequestApp = receptionRequestApp;
