import initialState from './state.js?v=1.6';
import utils from './utils.js?v=1.6';
import requests from './requests.js?v=1.6';
import approvals from './approvals.js?v=1.6';
import imports from './imports.js?v=1.6';
import exports from './exports.js?v=1.6';
import overview from './overview.js?v=1.6';

function inventoryManagerApp(totalRecords, currentPage, totalPages) {
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
                localStorage.setItem('manager_currentTab', newTab);
            });

            // Initialize data from global variables if available
            try {
                let rawProducts = [];
                let rawCategories = [];

                if (window.PRODUCT_DB) rawProducts = window.PRODUCT_DB;
                if (window.CATEGORY_DB) rawCategories = window.CATEGORY_DB;
                if (window.CURRENT_WAREHOUSE_ID) this.currentWarehouseId = window.CURRENT_WAREHOUSE_ID;
                if (window.WAREHOUSES_DB) this.allWarehouses = window.WAREHOUSES_DB;
                if (window.BRANCHES_DB) this.branches = window.BRANCHES_DB;

                // [NEW] Determine if Main Warehouse
                if (this.currentWarehouseId && this.allWarehouses.length > 0) {
                    const cw = this.allWarehouses.find(w => w.id == this.currentWarehouseId);
                    // Loose equality check (==) for ID safety
                    if (cw) {
                        // Check 1: No Branch ID (Main)
                        // Check 2: Branch Name is 'Kho Tổng'
                        // Check 3: Branch Code is ADMIN/BOSS (if available in future)
                        if (!cw.branch_id || cw.branch_name === 'Kho Tổng' || (cw.branch && ['ADMIN', 'BOSS', 'HEAD'].includes(cw.branch.code))) {
                            this.isCurrentWarehouseMain = true;
                        }
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

            // [FIX] Initialize historyList from server data
            if (window.INITIAL_RECORDS) {
                this.historyList = window.INITIAL_RECORDS;
                // Also sync pagination state if provided in separate variables or inferred
                // For now, index.html passed total_records etc to factory, which passed to initialState
            }

            if (this.currentWarehouseId) {
                this.initOverview();
                this.fetchPendingApprovals();
                this.fetchImports(1);

                // [NEW] Fetch data for restored tab
                if (this.currentTab === 'approvals') {
                    this.fetchApprovals();
                } else if (this.currentTab === 'export') {
                    this.fetchExports(1);
                }
                // Note: 'requests' data is already loaded from INITIAL_RECORDS
                // 'import' is already fetched above
                // 'overview' is already initialized above
            }
        },


    };
}

// Export for dynamic import usage
export { inventoryManagerApp };

// Keep window assignment for debugging or fallback
window.inventoryManagerApp = inventoryManagerApp;
