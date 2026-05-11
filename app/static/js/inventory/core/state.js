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

    const storageKey = config.storageKey || 'inventory_currentTab';
    const validTabs = config.validTabs || ['requests', 'approvals', 'import', 'export', 'overview'];
    const hasExportTab = validTabs.includes('export');

    return {
        currentTab: 'requests',
        productList: [],
        categoryList: [],
        currentWarehouseId: null,
        currentBranchId: config.branchId || null,
        userRole: window.USER_ROLE || null,
        isManagerMode: config.isManager !== false,

        historyList: [],
        approvalsList: [],
        stocks: [],

        allWarehouses: [],
        branches: [],
        isCurrentWarehouseMain: false,

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
            dest_warehouse_id: '',
            product_search: '',
            is_search_open: false,
            notes: '',
            itemGroups: []
        },

        _storageKey: storageKey,
        _validTabs: validTabs,
        _hasExportTab: hasExportTab,

        initCurrentTab() {
            const savedTab = localStorage.getItem(this._storageKey);
            if (savedTab && this._validTabs.includes(savedTab)) {
                this.currentTab = savedTab;
            }
        },

        getCurrentMonthRange() {
            return { start: defaultStart, end: defaultEnd };
        }
    };
}
