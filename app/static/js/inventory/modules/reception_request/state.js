export default function (totalRecords, currentPage, totalPages) {
    // Determine default date range: Current Month
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
        currentTab: 'requests', // 'requests', 'approvals', 'overview'
        productList: [],
        categoryList: [],
        currentBranchId: null,
        userRole: window.USER_ROLE || null,  // User's role for permission checks

        // Data Lists
        historyList: [],
        approvalsList: [],
        stocks: [],

        // [NEW] Global Data for Exports/Admin
        allWarehouses: [],
        branches: [],
        isCurrentBranchAdmin: false,

        // [NEW] Normalized Data for Stable Rendering
        normalizedCategories: [],
        normalizedProducts: [],

        // Pagination
        currentPage: currentPage || 1,
        totalPages: totalPages || 1,
        totalRecords: totalRecords || 0,
        perPage: 10,

        // Approval Pagination
        currentApprovalPage: 1,
        totalApprovalPages: 1,
        totalApprovalRecords: 0,

        // Sorting
        currentSortBy: 'created_at',
        currentSortOrder: 'desc',

        // Filters
        filters: {
            status: '',
            search: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },

        // [NEW] Filters for Approvals
        approvalFilter: 'PENDING',
        approvalFilters: {
            search: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },
        pendingCount: 0,
        loadingApprovals: false,

        // Selection
        selectedIds: [],
        lastCheckedId: null,

        // UI States
        loading: false,
        isCreateModalOpen: false,
        isEditModalOpen: false,
        isReceiptModalOpen: false,

        editingId: null,

        viewingRequestTicket: null,
        viewingImage: null,  // For image lightbox
        viewingApprovalTicket: null,

        viewingChildTicket: null,
        approvingTicket: null,
        receivingTicket: null,
        isSubmitting: false,

        // Import Tab States
        isImportModalOpen: false,
        isEditImportModalOpen: false,
        importsList: [],
        currentImportPage: 1,
        totalImportPages: 1,
        loadingImports: false,

        // Import Sorting & Selection
        selectedImportIds: [],
        importSort: { column: 'created_at', order: 'desc' },
        importFilters: {
            search: '',
            date_from: defaultStart,
            date_to: defaultEnd
        },
        lastCheckedImportIndex: null,

        // Import Detail & Edit States
        isImportDetailModalOpen: false,
        importDetail: null,
        loadingImportDetail: false,
        editingImportId: null,

        // Forms
        createForm: {
            source_warehouse_id: '',
            itemGroups: [],
            notes: ''
        },
        importForm: {
            warehouse_id: '',
            supplier_name: '',
            notes: '',
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

        // [NEW] Direct Export Form
        isDirectExportModalOpen: false,
        exportForm: {
            dest_warehouse_id: '',
            notes: '',
            itemGroups: []
        },

        getAllSelectableChecked() {
            return this.historyList.length > 0 && this.selectedIds.length === this.historyList.length;
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

        // Computed Helpers for Forms (Moved from generic getters to here or keep as getters)
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

        // [NEW] Initialize currentTab from localStorage
        initCurrentTab() {
            const savedTab = localStorage.getItem('reception_currentTab');
            const validTabs = ['requests', 'approvals', 'import', 'overview'];
            if (savedTab && validTabs.includes(savedTab)) {
                this.currentTab = savedTab;
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
