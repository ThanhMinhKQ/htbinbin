
// Helper for default dates (Module Level to ensure distinct defaults)
function getExportsMonthRange() {
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

    return {
        start: formatDate(firstDay),
        end: formatDate(lastDay)
    };
}

export default {

    // --- STATE ---
    isDirectExportModalOpen: false,
    exportForm: {
        dest_warehouse_id: '',
        notes: '',
        product_search: '',
        is_search_open: false,
        itemGroups: []
    },

    // --- EXPORT HISTORY STATE ---
    exportsList: [],
    loadingExports: false,
    totalExportPages: 0,
    currentExportPage: 1,
    exportPerPage: 10,
    totalExportRecords: 0,
    exportFilters: {
        search: '',
        date_from: getExportsMonthRange().start,
        date_to: getExportsMonthRange().end,
        status: ''
    },
    exportSort: {
        column: 'created_at',
        order: 'desc'
    },

    // --- EXPORT DETAIL STATE ---
    isExportDetailModalOpen: false,
    loadingExportDetail: false,
    exportDetail: null,

    // --- DIRECT EXPORT MODAL ---
    openDirectExportModal() {
        this.resetDirectExportForm();
        this.isDirectExportModalOpen = true;
    },

    closeDirectExportModal() {
        this.isDirectExportModalOpen = false;
    },

    resetDirectExportForm() {
        this.exportForm.dest_warehouse_id = '';
        this.exportForm.notes = '';
        this.exportForm.product_search = '';
        this.exportForm.is_search_open = false;
        this.exportForm.itemGroups = [this.createEmptyGroup()];
    },

    // --- EXPORT HISTORY ACTIONS ---
    initExports() {
        // Dates are already initialized in state
        this.fetchExports(1);
    },

    getCurrentMonthRange() {
        return getExportsMonthRange();
    },

    async fetchExports(page = 1) {
        if (!this.currentWarehouseId) return;
        this.loadingExports = true;
        this.currentExportPage = page;

        try {
            const params = new URLSearchParams({
                page: page,
                per_page: this.exportPerPage,
                sort_by: this.exportSort.column,
                sort_order: this.exportSort.order,
                source_warehouse_id: this.currentWarehouseId,
                status: this.exportFilters.status || 'SHIPPING,COMPLETED'
            });

            if (this.exportFilters.search) params.append('search', this.exportFilters.search);
            if (this.exportFilters.date_from) params.append('date_from', this.exportFilters.date_from);
            if (this.exportFilters.date_to) params.append('date_to', this.exportFilters.date_to);

            const res = await fetch(`/api/inventory/requests/list?${params.toString()}`);
            const data = await res.json();

            this.exportsList = data.records || [];
            this.totalExportPages = data.totalPages || 0;
            this.totalExportRecords = data.totalRecords || 0;

            this.renderExportPagination();
            this.updateExportRecordCount();

        } catch (e) {
            console.error("Error fetching exports:", e);
            this.exportsList = [];
        } finally {
            this.loadingExports = false;
        }
    },

    sortExports(column) {
        if (this.exportSort.column === column) {
            this.exportSort.order = this.exportSort.order === 'asc' ? 'desc' : 'asc';
        } else {
            this.exportSort.column = column;
            this.exportSort.order = 'desc';
        }
        this.fetchExports(1);
    },

    resetExportDateFilter() {
        const range = this.getCurrentMonthRange();
        this.exportFilters.date_from = range.start;
        this.exportFilters.date_to = range.end;
        this.exportFilters.search = '';
        this.exportFilters.status = '';
        this.fetchExports(1);
    },

    renderExportPagination() {
        const container = document.getElementById('export-pagination-controls');
        if (!container) return;
        container.innerHTML = this.createPaginationHTML(this.currentExportPage, this.totalExportPages, 'fetchExports');
    },

    updateExportRecordCount() {
        const el = document.getElementById('export-record-count');
        if (el) {
            const start = (this.currentExportPage - 1) * this.exportPerPage + 1;
            const end = Math.min(start + this.exportPerPage - 1, this.totalExportRecords);
            el.textContent = this.totalExportRecords > 0
                ? `Hiển thị ${start}-${end} trên ${this.totalExportRecords} phiếu`
                : 'Không có dữ liệu';
        }
    },

    // --- EXPORT DETAIL ACTIONS ---
    async openExportDetail(id) {
        this.isExportDetailModalOpen = true;
        this.loadingExportDetail = true;
        this.exportDetail = null;

        try {
            const res = await fetch(`/api/inventory/request/${id}`);
            if (res.ok) {
                this.exportDetail = await res.json();
            } else {
                alert("Không thể tải chi tiết phiếu.");
                this.closeExportDetailModal();
            }
        } catch (e) {
            console.error(e);
            alert("Lỗi kết nối.");
        } finally {
            this.loadingExportDetail = false;
        }
    },

    closeExportDetailModal() {
        this.isExportDetailModalOpen = false;
        this.exportDetail = null;
    },

    // --- EXPORT FORM ITEMS ---
    addCategoryGroupToExport() {
        this.exportForm.itemGroups.push(this.createEmptyGroup());
    },

    removeCategoryGroupFromExport(index) {
        if (this.exportForm.itemGroups.length > 1) {
            this.exportForm.itemGroups.splice(index, 1);
        }
    },

    addItemToExportGroup(groupIndex) {
        this.exportForm.itemGroups[groupIndex].items.push(this.createEmptyItem());
    },

    getExportProductSearchResults() {
        const query = (this.exportForm.product_search || '').toLowerCase().trim();
        if (!query) return [];

        const categoriesById = new Map(this.normalizedCategories.map(c => [String(c.id), c.name]));

        return this.normalizedProducts
            .filter(product => {
                const categoryName = categoriesById.get(String(product.category_id)) || '';
                const haystack = `${product.name || ''} ${product.code || ''} ${categoryName}`.toLowerCase();
                return haystack.includes(query);
            })
            .slice(0, 10);
    },

    addExportProductQuick(product) {
        const categoryId = product.category_id ? String(product.category_id) : '';

        // Build fully-hydrated item upfront
        const available_units = [product.base_unit];
        if (product.packing_unit && product.conversion_rate > 1) {
            available_units.unshift(product.packing_unit);
        }
        const unit = available_units[0];

        const newItem = {
            id: Date.now() + Math.random(),
            product_id: String(product.id),
            product_name: product.name,
            quantity: 1,
            unit: unit,
            available_units: available_units,
            source: 'quick'
        };

        // Find existing group with same category
        let groupIndex = this.exportForm.itemGroups.findIndex(g => g.category_id == categoryId);

        const category = this.normalizedCategories.find(c => String(c.id) === categoryId);
        const categoryName = category ? category.name : '';

        if (groupIndex !== -1) {
            this.exportForm.itemGroups[groupIndex].items.push(newItem);
        } else {
            const emptyIndex = this.exportForm.itemGroups.findIndex(g =>
                !g.category_id && g.items.length === 1 && !g.items[0].product_id
            );
            if (emptyIndex !== -1) {
                this.exportForm.itemGroups.splice(emptyIndex, 1, {
                    id: Date.now() + Math.random(),
                    category_id: categoryId,
                    category_name: categoryName,
                    source: 'quick',
                    items: [newItem]
                });
            } else {
                this.exportForm.itemGroups.push({
                    id: Date.now() + Math.random(),
                    category_id: categoryId,
                    category_name: categoryName,
                    source: 'quick',
                    items: [newItem]
                });
            }
        }

        this.exportForm.product_search = '';
        this.exportForm.is_search_open = false;
    },

    clearExportProductSearch() {
        this.exportForm.product_search = '';
        this.exportForm.is_search_open = false;
    },

    removeItemFromExportGroup(groupIndex, itemIndex) {
        if (this.exportForm.itemGroups[groupIndex].items.length > 1) {
            this.exportForm.itemGroups[groupIndex].items.splice(itemIndex, 1);
        }
    },

    onExportProductChange(groupIndex, itemIndex) {
        const group = this.exportForm.itemGroups[groupIndex];
        const item = group.items[itemIndex];
        const product = this.normalizedProducts.find(p => p.id == item.product_id);

        if (product) {
            item.available_units = [product.base_unit];
            if (product.packing_unit && product.conversion_rate > 1) {
                item.available_units.unshift(product.packing_unit); // [FIX] Unshift to put packing unit first (Default)
            }
            item.unit = item.available_units[0]; // Select first unit (packing_unit if exists, else base_unit)
        }
    },

    // --- FORM DATA PROCESSING ---
    getFlatExportFormItems() {
        let flatItems = [];
        this.exportForm.itemGroups.forEach(group => {
            if (group.items && group.items.length > 0) {
                group.items.forEach(item => {
                    flatItems.push({
                        ...item,
                        category_id: group.category_id
                    });
                });
            }
        });
        return flatItems;
    },

    // --- SUBMIT ---
    async submitDirectExport() {
        if (!this.exportForm.dest_warehouse_id) {
            alert("Vui lòng chọn Kho Đích.");
            return;
        }

        const validItems = this.getFlatExportFormItems().filter(i => i.product_id && i.quantity > 0);
        if (validItems.length === 0) {
            alert("Vui lòng nhập ít nhất 1 sản phẩm.");
            return;
        }

        // Confirmation
        if (!confirm("BẠN CHẮC CHẮN CHỨ?\n\nHành động này sẽ lập tức TRỪ KHO của bạn và tạo phiếu xuất hàng cho chi nhánh đích.")) {
            return;
        }

        this.isSubmitting = true;
        try {
            const payload = {
                source_warehouse_id: this.currentWarehouseId, // Resolved Warehouse ID
                dest_warehouse_id: this.exportForm.dest_warehouse_id,
                notes: this.exportForm.notes,
                items: validItems
            };

            const res = await fetch('/api/inventory/direct-export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.closeDirectExportModal();
                // Optionally refresh overview or stay on tab
                // this.fetchOverview(); 
            } else {
                alert("Lỗi: " + (data.detail || data.message || "Unknown Error"));
            }
        } catch (e) {
            alert("Lỗi kết nối server");
            console.error(e);
        } finally {
            this.isSubmitting = false;
        }
    },

    // --- EXPORT EDIT (SHIPPING) ---
    isExportEditModalOpen: false,
    editingExport: null,
    exportEditForm: {
        notes: '',
        product_search: '',
        is_search_open: false,
        itemGroups: []
    },

    async openExportEditModal(id) {
        // Fetch fresh detail first
        this.loadingExportDetail = true; // Use existing loading state if acceptable, or new one
        try {
            const res = await fetch(`/api/inventory/request/${id}`);
            if (res.ok) {
                this.editingExport = await res.json();

                // Populate Form
                this.exportEditForm.notes = this.editingExport.notes || '';

                // Group items by Category to match UI structure
                // Logic similar to modal_export_detail view
                const itemsByCategory = (this.editingExport.items || []).reduce((acc, item) => {
                    const catId = item.category_id ? String(item.category_id) : 'OTHER';
                    if (!acc[catId]) acc[catId] = { id: 'grp_' + catId + '_' + Date.now(), category_id: item.category_id ? String(item.category_id) : '', items: [] };

                    acc[catId].items.push({
                        id: 'item_' + item.product_id + '_' + Math.random().toString(36).slice(2, 8),
                        product_id: String(item.product_id),
                        quantity: parseFloat(item.approved_quantity),
                        unit: item.request_unit,
                        available_units: [item.request_unit]
                    });
                    return acc;
                }, {});

                this.exportEditForm.itemGroups = Object.values(itemsByCategory);

                // If no items (shouldn't happen), add empty group
                if (this.exportEditForm.itemGroups.length === 0) {
                    this.exportEditForm.itemGroups = [this.createEmptyGroup()];
                }

                // Important: Need to hydrate available units properly
                // We do this by iterating and calling logic similar to onProductChange, 
                // but we also need to respect the unit that was already saved.
                this.exportEditForm.itemGroups.forEach(group => {
                    group.items.forEach(item => {
                        const product = this.normalizedProducts.find(p => p.id == item.product_id);
                        if (product) {
                            item.available_units = [product.base_unit];
                            if (product.packing_unit && product.conversion_rate > 1) {
                                item.available_units.push(product.packing_unit);
                            }
                            // item.unit is already set from DB, ensure it's in available list (it should be)
                        }
                    });
                });

                this.closeExportDetailModal(); // Close detail modal
                this.isExportEditModalOpen = true;

            } else {
                alert("Không thể tải chi tiết phiếu.");
            }
        } catch (e) {
            console.error(e);
            alert("Lỗi kết nối.");
        } finally {
            this.loadingExportDetail = false;
        }
    },

    closeExportEditModal() {
        this.isExportEditModalOpen = false;
        this.editingExport = null;
        this.exportEditForm.itemGroups = [];
    },

    addCategoryGroupToEditExport() {
        this.exportEditForm.itemGroups.push(this.createEmptyGroup());
    },

    removeCategoryGroupFromEditExport(index) {
        if (this.exportEditForm.itemGroups.length > 1) {
            this.exportEditForm.itemGroups.splice(index, 1);
        }
    },

    addItemToEditExportGroup(groupIndex) {
        this.exportEditForm.itemGroups[groupIndex].items.push(this.createEmptyItem());
    },

    removeItemFromEditExportGroup(groupIndex, itemIndex) {
        if (this.exportEditForm.itemGroups[groupIndex].items.length > 1) {
            this.exportEditForm.itemGroups[groupIndex].items.splice(itemIndex, 1);
        }
    },

    onEditExportProductChange(groupIndex, itemIndex) {
        const group = this.exportEditForm.itemGroups[groupIndex];
        const item = group.items[itemIndex];
        const product = this.normalizedProducts.find(p => p.id == item.product_id);

        if (product) {
            item.available_units = [product.base_unit];
            if (product.packing_unit && product.conversion_rate > 1) {
                item.available_units.push(product.packing_unit);
            }
            item.unit = item.available_units[0];
        }
    },

    getEditExportProductSearchResults() {
        const query = (this.exportEditForm.product_search || '').toLowerCase().trim();
        if (!query) return [];

        const categoriesById = new Map(this.normalizedCategories.map(c => [String(c.id), c.name]));

        return this.normalizedProducts
            .filter(product => {
                const categoryName = categoriesById.get(String(product.category_id)) || '';
                const haystack = `${product.name || ''} ${product.code || ''} ${categoryName}`.toLowerCase();
                return haystack.includes(query);
            })
            .slice(0, 10);
    },

    addEditExportProductQuick(product) {
        const categoryId = product.category_id ? String(product.category_id) : '';

        const available_units = [product.base_unit];
        if (product.packing_unit && product.conversion_rate > 1) {
            available_units.unshift(product.packing_unit);
        }
        const unit = available_units[0];

        const newItem = {
            id: Date.now() + Math.random(),
            product_id: String(product.id),
            product_name: product.name,
            quantity: 1,
            unit: unit,
            available_units: available_units,
            source: 'quick'
        };

        let groupIndex = this.exportEditForm.itemGroups.findIndex(g => g.category_id == categoryId);

        const category = this.normalizedCategories.find(c => String(c.id) === categoryId);
        const categoryName = category ? category.name : '';

        if (groupIndex !== -1) {
            this.exportEditForm.itemGroups[groupIndex].items.push(newItem);
        } else {
            const emptyIndex = this.exportEditForm.itemGroups.findIndex(g =>
                !g.category_id && g.items.length === 1 && !g.items[0].product_id
            );
            if (emptyIndex !== -1) {
                this.exportEditForm.itemGroups.splice(emptyIndex, 1, {
                    id: Date.now() + Math.random(),
                    category_id: categoryId,
                    category_name: categoryName,
                    source: 'quick',
                    items: [newItem]
                });
            } else {
                this.exportEditForm.itemGroups.push({
                    id: Date.now() + Math.random(),
                    category_id: categoryId,
                    category_name: categoryName,
                    source: 'quick',
                    items: [newItem]
                });
            }
        }

        this.exportEditForm.product_search = '';
        this.exportEditForm.is_search_open = false;
    },

    getFlatExportEditFormItems() {
        let flatItems = [];
        this.exportEditForm.itemGroups.forEach(group => {
            if (group.items && group.items.length > 0) {
                group.items.forEach(item => {
                    flatItems.push({
                        ...item,
                        category_id: group.category_id
                    });
                });
            }
        });
        return flatItems;
    },

    async submitExportUpdate() {
        const validItems = this.getFlatExportEditFormItems().filter(i => i.product_id && i.quantity > 0);
        if (validItems.length === 0) {
            alert("Vui lòng nhập ít nhất 1 sản phẩm.");
            return;
        }

        if (!confirm("Xác nhận cập nhật phiếu xuất kho?\nKho sẽ được tính toán lại dựa trên thay đổi của bạn.")) {
            return;
        }

        this.isSubmitting = true;
        try {
            const payload = {
                items: validItems.map(item => ({
                    product_id: parseInt(item.product_id),
                    quantity: parseFloat(item.quantity),
                    unit: item.unit
                })),
                notes: this.exportEditForm.notes
            };

            const res = await fetch(`/api/inventory/direct-export/${this.editingExport.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.closeExportEditModal();
                this.fetchExports(this.currentExportPage); // Refresh list
            } else {
                alert("Lỗi: " + (data.detail || data.message));
            }
        } catch (e) {
            alert("Lỗi kết nối server");
            console.error(e);
        } finally {
            this.isSubmitting = false;
        }
    }
};
