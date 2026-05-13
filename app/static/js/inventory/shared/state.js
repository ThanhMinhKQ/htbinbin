export default function (totalRecords, currentPage, totalPages, config = {}) {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const formatDate = (date) => {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    };
    const defaultStart = formatDate(firstDay);
    const defaultEnd = formatDate(lastDay);

    return {
        currentTab: 'requests',
        productList: [],
        categoryList: [],
        currentBranchId: null,
        currentWarehouseId: null,
        userRole: window.USER_ROLE || null,

        historyList: [],
        approvalsList: [],
        stocks: [],

        allWarehouses: [],
        branches: [],
        isCurrentWarehouseMain: false,
        isCurrentBranchAdmin: false,

        normalizedCategories: [],
        normalizedProducts: [],

        currentPage: currentPage || 1,
        totalPages: totalPages || 1,
        totalRecords: totalRecords || 0,
        perPage: 10,

        currentApprovalPage: 1,
        totalApprovalPages: 1,
        totalApprovalRecords: 0,

        currentSortBy: 'created_at',
        currentSortOrder: 'desc',

        filters: {
            status: '',
            search: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },

        approvalFilter: 'PENDING',
        approvalFilters: {
            search: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },
        pendingCount: 0,
        loadingApprovals: false,
        isLoadingApprovalDetails: false,

        selectedIds: [],
        lastCheckedId: null,

        loading: false,
        isCreateModalOpen: false,
        isEditModalOpen: false,
        isReceiptModalOpen: false,

        editingId: null,

        viewingRequestTicket: null,
        viewingImage: null,
        viewingApprovalTicket: null,

        viewingChildTicket: null,
        approvingTicket: null,
        receivingTicket: null,
        isSubmitting: false,

        isImportModalOpen: false,
        isEditImportModalOpen: false,
        importsList: [],
        currentImportPage: 1,
        totalImportPages: 1,
        totalImportRecords: 0,
        loadingImports: false,

        selectedImportIds: [],
        importSort: { column: 'created_at', order: 'desc' },
        importFilters: {
            search: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },
        lastCheckedImportIndex: null,

        isImportDetailModalOpen: false,
        importDetail: null,
        loadingImportDetail: false,
        editingImportId: null,

        createForm: {
            source_warehouse_id: '',
            product_search: '',
            is_search_open: false,
            itemGroups: [],
            notes: ''
        },
        importForm: {
            warehouse_id: '',
            supplier_name: '',
            notes: '',
            product_search: '',
            is_search_open: false,
            itemGroups: [],
            images: []
        },
        editForm: {
            source_warehouse_id: '',
            itemGroups: [],
            notes: ''
        },
        itemGroups: [],

        editImportForm: {
            supplier_name: '',
            notes: '',
            itemGroups: [],
            existingImages: [],
            newImages: [],
            pendingDeletes: []
        },

        approvalForm: { items: [], approver_notes: '' },
        approvalGroups: [],
        receiptForm: { items: [], compensation_mode: 'none' },

        isDirectExportModalOpen: false,
        exportForm: {
            dest_warehouse_id: '',
            notes: '',
            product_search: '',
            is_search_open: false,
            itemGroups: []
        },

        exportList: [],
        currentExportPage: 1,
        totalExportPages: 1,
        totalExportRecords: 0,
        loadingExports: false,
        exportFilters: {
            search: '',
            status: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },
        viewingExportTicket: null,
        isExportDetailModalOpen: false,

        getAllSelectableChecked() {
            const selectable = this.historyList.filter(t => t.status === 'PENDING');
            return selectable.length > 0 && this.selectedIds.length === selectable.length;
        },

        getAllImportsSelected() {
            return this.importsList.length > 0 && this.selectedImportIds.length === this.importsList.length;
        },

        getUniqueCategories() {
            if (this.categoryList && this.categoryList.length > 0) {
                return this.categoryList;
            }
            const cats = new Map();
            this.productList.forEach(p => {
                if (p.category_id && p.category_name) {
                    cats.set(p.category_id, p.category_name);
                }
            });
            return Array.from(cats.entries()).map(([id, name]) => ({ id, name }));
        },

        getFlatCreateFormItems() {
            let all = [];
            this.createForm.itemGroups.forEach(g => {
                if (g.category_id) {
                    g.items.forEach(i => {
                        all.push({ ...i, category_id: g.category_id });
                    });
                }
            });
            return all;
        },

        getFlatEditFormItems() {
            let all = [];
            this.editForm.itemGroups.forEach(g => {
                if (g.category_id) {
                    g.items.forEach(i => {
                        all.push({ ...i, category_id: g.category_id });
                    });
                }
            });
            return all;
        },

        getFlatImportFormItems() {
            let all = [];
            this.importForm.itemGroups.forEach(g => {
                if (g.category_id) {
                    g.items.forEach(i => {
                        all.push({ ...i, category_id: g.category_id });
                    });
                }
            });
            return all;
        },

        initCurrentTab() {
            const savedTab = localStorage.getItem(config.storageKey);
            const validTabs = config.validTabs || ['requests', 'approvals', 'import', 'export', 'overview'];
            if (savedTab && validTabs.includes(savedTab)) {
                this.currentTab = savedTab;
            } else if (config.defaultTab && validTabs.includes(config.defaultTab)) {
                this.currentTab = config.defaultTab;
            }
        },

        getFlatEditImportFormItems() {
            let all = [];
            this.editImportForm.itemGroups.forEach(g => {
                if (g.category_id) {
                    g.items.forEach(i => {
                        all.push({ ...i, category_id: g.category_id });
                    });
                }
            });
            return all;
        }
    };
}
