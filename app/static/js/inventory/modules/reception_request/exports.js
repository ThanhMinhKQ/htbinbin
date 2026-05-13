
export default {

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
        this.exportForm.itemGroups = [this.createEmptyGroup()];
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
                item.available_units.unshift(product.packing_unit);
            }
            item.unit = item.available_units[0];
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
                source_warehouse_id: this.currentWarehouseId,
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

    // --- EXPORT HISTORY (Read-only) ---
    async fetchExports(page = 1) {
        this.loadingExports = true;
        this.currentExportPage = page;
        try {
            const params = new URLSearchParams({
                page: page,
                per_page: this.perPage || 10,
                dest_warehouse_id: this.currentWarehouseId || ''
            });
            if (this.exportFilters.search) params.set('search', this.exportFilters.search);
            if (this.exportFilters.status) params.set('status', this.exportFilters.status);
            if (this.exportFilters.date_from) params.set('date_from', this.exportFilters.date_from);
            if (this.exportFilters.date_to) params.set('date_to', this.exportFilters.date_to);

            const res = await fetch(`/api/inventory/requests/list?${params.toString()}`, { credentials: 'same-origin' });
            const data = await res.json();

            if (res.ok) {
                this.exportList = data.records || data || [];
                this.totalExportRecords = data.totalRecords || this.exportList.length;
                this.totalExportPages = data.totalPages || 1;
            }
        } catch (e) {
            console.error("Error fetching export history:", e);
        } finally {
            this.loadingExports = false;
        }
    },

    async openExportDetail(ticketId) {
        this.isExportDetailModalOpen = true;
        this.viewingExportTicket = null;
        try {
            const res = await fetch(`/api/inventory/request/${ticketId}`, { credentials: 'same-origin' });
            if (res.ok) {
                this.viewingExportTicket = await res.json();
            }
        } catch (e) {
            console.error("Error fetching export detail:", e);
        }
    },

    closeExportDetail() {
        this.isExportDetailModalOpen = false;
        this.viewingExportTicket = null;
    }
};
