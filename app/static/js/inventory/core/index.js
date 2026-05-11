import initialState from './state.js';
import utils from './utils.js';
import requests from './requests.js';
import approvals from './approvals.js';
import imports from './imports.js';
import overview from './overview.js';

export function createInventoryApp(config = {}) {
    return function (totalRecords, currentPage, totalPages) {
        const exportsMixin = config.exports || {};

        return {
            ...initialState(totalRecords, currentPage, totalPages, config),
            ...utils,
            ...requests,
            ...approvals,
            ...imports,
            ...exportsMixin,
            ...overview,

            initApp() {
                this.initCurrentTab();

                this.$watch('currentTab', (newTab) => {
                    localStorage.setItem(this._storageKey, newTab);
                });

                try {
                    let rawProducts = [];
                    let rawCategories = [];

                    if (window.PRODUCT_DB) rawProducts = window.PRODUCT_DB;
                    if (window.CATEGORY_DB) rawCategories = window.CATEGORY_DB;
                    if (window.CURRENT_WAREHOUSE_ID) this.currentWarehouseId = window.CURRENT_WAREHOUSE_ID;
                    if (window.CURRENT_BRANCH_ID) this.currentBranchId = window.CURRENT_BRANCH_ID;
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
                    this.initOverview();
                    this.fetchPendingApprovals();
                    this.fetchImports(1);

                    if (this.currentTab === 'approvals') {
                        this.fetchApprovals();
                    } else if (this.currentTab === 'export' && this._hasExportTab) {
                        this.fetchExports(1);
                    }
                }
            },
        };
    };
}
