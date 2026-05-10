
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
                source_warehouse_id: this.currentBranchId, // Usually Admin Warehouse ID
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
    }
};
