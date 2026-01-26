export default {

    resetImportDateFilter() {
        const range = this.getCurrentMonthRange();
        this.importFilters.date_from = range.start;
        this.importFilters.date_to = range.end;
        this.importFilters.search = '';
        this.fetchImports(1);
    },



    closeImportModal() {
        if (this.importForm.images) {
            this.importForm.images.forEach(img => {
                if (img.preview) URL.revokeObjectURL(img.preview);
            });
        }
        this.importForm.images = [];
        this.isImportModalOpen = false;
    },

    resetImportForm() {
        this.importForm.supplier_name = '';
        this.importForm.notes = '';
        this.importForm.itemGroups = [this.createEmptyGroup()];
    },

    // --- IMPORT LIST ---
    async fetchImports(page = 1) {
        if (!this.currentWarehouseId) return;
        this.loadingImports = true;
        this.currentImportPage = page;
        this.selectedImportIds = [];
        this.lastCheckedImportIndex = null;
        this.totalImportRecords = 0;

        try {
            const params = new URLSearchParams({
                warehouse_id: this.currentWarehouseId,
                page: page,
                per_page: this.perPage,
                sort_by: this.importSort.column,
                sort_order: this.importSort.order
            });

            // Add search filter if exists
            if (this.importFilters && this.importFilters.search) {
                params.append('search', this.importFilters.search);
            }
            if (this.importFilters && this.importFilters.date_from) {
                params.append('date_from', this.importFilters.date_from);
            }
            if (this.importFilters && this.importFilters.date_to) {
                params.append('date_to', this.importFilters.date_to);
            }

            const res = await fetch(`/api/inventory/receipts?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();
                if (data.records) {
                    this.importsList = data.records;
                    this.totalImportPages = data.totalPages;
                    this.totalImportRecords = data.totalRecords;
                } else if (Array.isArray(data)) {
                    this.importsList = data;
                    this.totalImportPages = 1;
                    this.totalImportRecords = data.length;
                } else {
                    this.importsList = [];
                    this.totalImportPages = 1;
                    this.totalImportRecords = 0;
                }
                this.renderImportPagination();
            }
        } catch (e) { console.error(e); }
        finally { this.loadingImports = false; }
    },

    renderImportPagination() {
        const paginationEl = document.getElementById('import-pagination-controls');
        const countEl = document.getElementById('import-record-count');
        if (!paginationEl || !countEl) return;

        paginationEl.innerHTML = '';

        if (this.totalImportRecords === 0) {
            countEl.textContent = 'Chưa có dữ liệu.';
            return;
        }

        countEl.innerHTML = `Hiển thị <span class="font-bold text-slate-700 dark:text-slate-300">${this.importsList.length}</span> / <span class="font-bold text-slate-700 dark:text-slate-300">${this.totalImportRecords}</span> phiếu`;

        if (this.totalImportPages <= 1) return;

        const createButton = (text, page, isDisabled = false, isCurrent = false) => {
            const button = document.createElement('button');
            button.innerHTML = text;
            let baseClasses = 'px-3 py-1 rounded-lg border text-sm font-semibold transition-colors';
            if (isCurrent) button.className = `${baseClasses} bg-green-600 text-white border-green-600 cursor-default shadow-sm`;
            else if (isDisabled) button.className = `${baseClasses} bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700 cursor-not-allowed`;
            else button.className = `${baseClasses} bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300`;

            if (!isDisabled && !isCurrent) {
                button.addEventListener('click', () => {
                    this.fetchImports(page);
                });
            }
            return button;
        };

        paginationEl.appendChild(createButton('&laquo;', 1, this.currentImportPage === 1));
        paginationEl.appendChild(createButton('&lsaquo;', this.currentImportPage - 1, this.currentImportPage === 1));

        let startPage = Math.max(1, this.currentImportPage - 2);
        let endPage = Math.min(this.totalImportPages, this.currentImportPage + 2);

        if (this.currentImportPage <= 3) endPage = Math.min(5, this.totalImportPages);
        if (this.currentImportPage > this.totalImportPages - 3) startPage = Math.max(1, this.totalImportPages - 4);

        if (startPage > 1) {
            paginationEl.appendChild(createButton('1', 1));
            if (startPage > 2) paginationEl.insertAdjacentHTML('beforeend', `<span class="px-2 text-slate-400">...</span>`);
        }

        for (let i = startPage; i <= endPage; i++) {
            paginationEl.appendChild(createButton(i, i, false, i === this.currentImportPage));
        }

        if (endPage < this.totalImportPages) {
            if (endPage < this.totalImportPages - 1) paginationEl.insertAdjacentHTML('beforeend', `<span class="px-2 text-slate-400">...</span>`);
            paginationEl.appendChild(createButton(this.totalImportPages, this.totalImportPages));
        }

        paginationEl.appendChild(createButton('&rsaquo;', this.currentImportPage + 1, this.currentImportPage === this.totalImportPages));
        paginationEl.appendChild(createButton('&raquo;', this.totalImportPages, this.currentImportPage === this.totalImportPages));
    },

    sortImports(column) {
        if (this.importSort.column === column) {
            this.importSort.order = this.importSort.order === 'asc' ? 'desc' : 'asc';
        } else {
            this.importSort.column = column;
            this.importSort.order = 'desc';
        }
        this.fetchImports(1);
    },

    toggleSelectAllImports() {
        if (this.selectedImportIds.length === this.importsList.length) {
            this.selectedImportIds = [];
        } else {
            this.selectedImportIds = this.importsList.map(i => i.id);
        }
        this.lastCheckedImportIndex = null;
    },

    handleImportCheckboxClick(event, id, index) {
        event.stopPropagation();
        const isChecked = !this.selectedImportIds.includes(id);

        if (event.shiftKey && this.lastCheckedImportIndex !== null) {
            const start = Math.min(this.lastCheckedImportIndex, index);
            const end = Math.max(this.lastCheckedImportIndex, index);

            for (let i = start; i <= end; i++) {
                const itemId = this.importsList[i].id;
                if (isChecked) {
                    if (!this.selectedImportIds.includes(itemId)) {
                        this.selectedImportIds.push(itemId);
                    }
                } else {
                    this.selectedImportIds = this.selectedImportIds.filter(x => x !== itemId);
                }
            }
        } else {
            if (this.selectedImportIds.includes(id)) {
                this.selectedImportIds = this.selectedImportIds.filter(i => i !== id);
            } else {
                this.selectedImportIds.push(id);
            }
        }
        this.lastCheckedImportIndex = index;
    },

    async batchDeleteImports() {
        if (!confirm(`Bạn có chắc muốn xóa ${this.selectedImportIds.length} phiếu nhập đã chọn? Hành động này sẽ hoàn tác tồn kho!`)) return;

        try {
            const res = await fetch('/api/inventory/receipts/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: this.selectedImportIds })
            });

            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.fetchImports(1);
            } else {
                alert("Lỗi: " + (data.detail || data.message));
            }
        } catch (e) {
            console.error(e);
            alert("Lỗi kết nối server");
        }
    },

    // --- IMPORT FORM ITEMS ---
    addCategoryGroupToImport() {
        this.importForm.itemGroups.push(this.createEmptyGroup());
    },

    removeCategoryGroupFromImport(index) {
        if (this.importForm.itemGroups.length > 1) {
            this.importForm.itemGroups.splice(index, 1);
        }
    },

    addItemToImportGroup(groupIndex) {
        this.importForm.itemGroups[groupIndex].items.push(this.createEmptyItem());
    },

    removeItemFromImportGroup(groupIndex, itemIndex) {
        if (this.importForm.itemGroups[groupIndex].items.length > 1) {
            this.importForm.itemGroups[groupIndex].items.splice(itemIndex, 1);
        }
    },

    onImportProductChange(groupIndex, itemIndex) {
        const group = this.importForm.itemGroups[groupIndex];
        const item = group.items[itemIndex];
        const product = this.productList.find(p => p.id == item.product_id);

        if (product) {
            item.available_units = [product.base_unit];
            if (product.packing_unit && product.conversion_rate > 1) {
                item.available_units.unshift(product.packing_unit);
            }

            item.unit = item.available_units[0];
            // Fix initial price calculation
            if (item.unit === product.packing_unit) {
                item.unit_price = Math.round((product.cost_price || 0) * (product.conversion_rate || 1));
            } else {
                item.unit_price = product.cost_price || 0;
            }
        }
    },

    onImportUnitChange(groupIndex, itemIndex) {
        const group = this.importForm.itemGroups[groupIndex];
        const item = group.items[itemIndex];
        // Ensure we find the product from the list (using same list as onImportProductChange)
        const product = this.productList.find(p => p.id == item.product_id) || this.normalizedProducts.find(p => p.id == item.product_id);

        if (product) {
            if (item.unit === product.packing_unit && product.conversion_rate > 1) {
                item.unit_price = Math.round((product.cost_price || 0) * product.conversion_rate);
            } else {
                item.unit_price = product.cost_price || 0;
            }
        }
    },

    calculateImportTotal() {
        let total = 0;
        this.getFlatImportFormItems().forEach(item => {
            total += (parseFloat(item.quantity) || 0) * (parseFloat(item.unit_price) || 0);
        });
        return this.formatMoney(total);
    },

    async submitImport() {
        if (!this.currentWarehouseId) {
            alert("Lỗi hệ thống: Không xác định được ID Kho hiện tại. Vui lòng tải lại trang.");
            return;
        }

        if (!this.importForm.supplier_name || !this.importForm.supplier_name.trim()) {
            alert("Vui lòng nhập tên Nhà cung cấp.");
            return;
        }

        const validItems = this.getFlatImportFormItems().filter(i => i.product_id && i.quantity > 0);

        if (validItems.length === 0) {
            alert("Vui lòng nhập ít nhất 1 sản phẩm (và phải chọn danh mục nhóm)");
            return;
        }

        this.isSubmitting = true;
        try {
            const payload = {
                warehouse_id: this.currentWarehouseId,
                supplier_name: this.importForm.supplier_name,
                notes: this.importForm.notes,
                items: validItems
            };

            const res = await fetch('/api/inventory/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok) {
                // Upload images if any
                if (this.importForm.images && this.importForm.images.length > 0 && data.receipt_id) {
                    const imageResult = await this.uploadImportImages(data.receipt_id);
                    if (imageResult.success && imageResult.count > 0) {
                        alert(data.message + `\nĐã upload ${imageResult.count} hình ảnh.`);
                    } else {
                        alert(data.message);
                    }
                } else {
                    alert(data.message);
                }
                this.closeImportModal();
                this.fetchImports(1);
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

    // --- IMPORT DETAIL ---
    async openImportDetail(id) {
        this.isImportDetailModalOpen = true;
        this.loadingImportDetail = true;
        this.importDetail = null;

        try {
            const res = await fetch(`/api/inventory/receipts/${id}`);
            if (res.ok) {
                const data = await res.json();

                // Construct the object locally first
                const detailObj = {
                    ...data,
                    items: data.items.map(i => {
                        const product = this.normalizedProducts.find(p => p.id == i.product_id);
                        return {
                            ...i,
                            product_name: product ? product.name : i.product_name,
                            category_name: product ? (product.category_name || 'Khác') : 'Khác',
                            product_code: product ? product.code : '',
                            unit_price: i.unit_price || 0,
                            total_price: (i.quantity || 0) * (i.unit_price || 0)
                        };
                    }),
                    images: []
                };

                // Fetch images separately and add to local object
                try {
                    const imgRes = await fetch(`/api/inventory/import/${id}/images`);
                    if (imgRes.ok) {
                        const imgData = await imgRes.json();
                        detailObj.images = imgData.images || [];
                    }
                } catch (e) {
                    console.error('Failed to load images:', e);
                    // Keep empty array as defined above
                }

                // Final assignment to state
                this.importDetail = detailObj;

            } else {
                alert("Không thể tải chi tiết phiếu nhập.");
                this.closeImportDetailModal();
            }
        } catch (e) {
            console.error(e);
            alert("Lỗi kết nối.");
            this.closeImportDetailModal();
        } finally {
            this.loadingImportDetail = false;
        }
    },

    getGroupedImportDetailItems(items) {
        if (!items) return {};
        return items.reduce((acc, item) => {
            const cat = item.category_name || 'Khác';
            if (!acc[cat]) acc[cat] = [];
            acc[cat].push(item);
            return acc;
        }, {});
    },

    closeImportDetailModal() {
        this.isImportDetailModalOpen = false;
        this.importDetail = null;
    },

    // --- EDIT IMPORT ---
    async openEditImportModal(id) {
        this.closeImportDetailModal();
        this.loading = true;

        try {
            const res = await fetch(`/api/inventory/receipts/${id}`);
            if (!res.ok) throw new Error("Không thể tải dữ liệu phiếu nhập");

            const t = await res.json();
            this.editingImportId = id;
            this.isEditImportModalOpen = true;

            setTimeout(() => {
                this.editImportForm.supplier_name = t.supplier_name;
                this.editImportForm.notes = t.notes || '';

                const groupsMap = {};

                if (t.items && t.items.length > 0) {
                    t.items.forEach(item => {
                        const product = this.normalizedProducts.find(p => String(p.id) === String(item.product_id));
                        let catId = 'OTHER';
                        if (product && product.category_id) catId = String(product.category_id);

                        if (!groupsMap[catId]) {
                            groupsMap[catId] = {
                                id: Date.now() + Math.random(),
                                category_id: catId === 'OTHER' ? '' : ('' + catId),
                                items: []
                            };
                        }

                        let available_units = [item.unit];
                        if (product) {
                            available_units = [product.base_unit];
                            if (product.packing_unit && product.conversion_rate > 1) {
                                available_units.unshift(product.packing_unit);
                            }
                        }

                        groupsMap[catId].items.push({
                            id: Date.now() + Math.random(),
                            product_id: '' + String(item.product_id),
                            quantity: parseFloat(item.quantity),
                            unit: String(item.unit),
                            unit_price: parseFloat(item.unit_price || 0),
                            available_units: available_units
                        });
                    });
                    this.editImportForm.itemGroups = Object.values(groupsMap);
                } else {
                    this.editImportForm.itemGroups = [{
                        id: Date.now(),
                        category_id: '',
                        items: [this.createEmptyItem()]
                    }];
                }
            }, 50);

            this.editImportForm.existingImages = [];
            this.editImportForm.newImages = [];
            try {
                const imgRes = await fetch(`/api/inventory/import/${id}/images`);
                if (imgRes.ok) {
                    const imgData = await imgRes.json();
                    this.editImportForm.existingImages = imgData.images || [];
                }
            } catch (e) {
                console.error("Failed to load images for edit:", e);
            }

        } catch (e) {
            alert(e.message);
            this.isEditImportModalOpen = false;
        } finally {
            this.loading = false;
        }
    },

    closeEditImportModal() {
        this.isEditImportModalOpen = false;
        this.editingImportId = null;
        if (this.editImportForm.newImages) {
            this.editImportForm.newImages.forEach(img => {
                if (img.preview) URL.revokeObjectURL(img.preview);
            });
        }
        this.editImportForm = { supplier_name: '', notes: '', itemGroups: [], existingImages: [], newImages: [], pendingDeletes: [] };
    },

    addCategoryGroupToEditImport() {
        this.editImportForm.itemGroups.push({
            id: Date.now() + Math.random(),
            category_id: '',
            items: [this.createEmptyItem()]
        });
    },
    removeCategoryGroupFromEditImport(index) {
        this.editImportForm.itemGroups.splice(index, 1);
    },
    addItemToEditImportGroup(groupIndex) {
        this.editImportForm.itemGroups[groupIndex].items.push(this.createEmptyItem());
    },
    removeItemFromEditImportGroup(groupIndex, itemIndex) {
        this.editImportForm.itemGroups[groupIndex].items.splice(itemIndex, 1);
    },
    onEditImportProductChange(groupIndex, itemIndex) {
        const group = this.editImportForm.itemGroups[groupIndex];
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

    async submitUpdateImport() {
        if (!this.editingImportId) return;

        const validItems = this.getFlatEditImportFormItems().filter(i => i.product_id && i.quantity > 0);
        if (validItems.length === 0) return alert("Vui lòng nhập ít nhất 1 sản phẩm hợp lệ.");

        this.isSubmitting = true;
        try {
            if (this.editImportForm.pendingDeletes.length > 0) {
                for (const imageId of this.editImportForm.pendingDeletes) {
                    try {
                        await fetch(`/api/inventory/images/${imageId}`, { method: 'DELETE' });
                    } catch (e) { console.error("Failed to delete image", imageId, e); }
                }
            }

            const payload = {
                supplier_name: this.editImportForm.supplier_name,
                warehouse_id: this.currentWarehouseId,
                notes: this.editImportForm.notes,
                items: validItems
            };

            const res = await fetch(`/api/inventory/receipts/${this.editingImportId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok) {
                let msg = data.message;
                if (this.editImportForm.newImages && this.editImportForm.newImages.length > 0) {
                    const imageResult = await this.uploadEditImportImages(this.editingImportId);
                    if (imageResult.success && imageResult.count > 0) {
                        msg += `\nĐã upload thêm ${imageResult.count} hình ảnh.`;
                    }
                }

                alert(msg);
                this.closeEditImportModal();
                this.fetchImports(this.currentImportPage);
            } else {
                alert("Lỗi: " + (data.detail || data.message));
            }
        } catch (e) {
            alert("Lỗi kết nối");
            console.error(e);
        } finally {
            this.isSubmitting = false;
        }
    },

    // --- IMAGES ---
    async handleEditImageUpload(event) {
        const files = Array.from(event.target.files);
        for (const file of files) {
            if (!file.type.startsWith('image/')) {
                alert(`File ${file.name} không phải là hình ảnh`);
                continue;
            }
            if (file.size > 10 * 1024 * 1024) {
                alert(`File ${file.name} quá lớn (tối đa 10MB)`);
                continue;
            }
            try {
                const preview = URL.createObjectURL(file);
                const compressedFile = await this.compressImage(file);
                this.editImportForm.newImages.push({
                    file: compressedFile || file,
                    preview: preview,
                    name: file.name,
                    size: compressedFile ? compressedFile.size : file.size
                });
            } catch (error) { console.error('Error processing image:', error); }
        }
        event.target.value = '';
    },

    removeEditNewImage(index) {
        if (this.editImportForm.newImages[index].preview) {
            URL.revokeObjectURL(this.editImportForm.newImages[index].preview);
        }
        this.editImportForm.newImages.splice(index, 1);
    },

    async deleteEditExistingImage(imageId) {
        if (this.editImportForm.pendingDeletes.includes(imageId)) return;
        this.editImportForm.pendingDeletes.push(imageId);
    },

    async uploadEditImportImages(receiptId) {
        if (!this.editImportForm.newImages || this.editImportForm.newImages.length === 0) {
            return { success: true, count: 0 };
        }
        try {
            const formData = new FormData();
            this.editImportForm.newImages.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/import/${receiptId}/images`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok) {
                return { success: true, count: data.images?.length || 0 };
            } else {
                return { success: false, error: data.detail || 'Upload failed' };
            }
        } catch (error) {
            return { success: false, error: error.message };
        }
    },

    async handleImageUpload(event) {
        const files = Array.from(event.target.files);
        for (const file of files) {
            if (!file.type.startsWith('image/')) {
                alert(`File ${file.name} không phải là hình ảnh`);
                continue;
            }
            if (file.size > 10 * 1024 * 1024) {
                alert(`File ${file.name} quá lớn (tối đa 10MB)`);
                continue;
            }
            try {
                const preview = URL.createObjectURL(file);
                const compressedFile = await this.compressImage(file);
                this.importForm.images.push({
                    file: compressedFile || file,
                    preview: preview,
                    name: file.name,
                    size: compressedFile ? compressedFile.size : file.size
                });
            } catch (error) { console.error('Error processing image:', error); }
        }
        event.target.value = '';
    },

    removeImage(index) {
        if (this.importForm.images[index].preview) {
            URL.revokeObjectURL(this.importForm.images[index].preview);
        }
        this.importForm.images.splice(index, 1);
    },

    async uploadImportImages(receiptId) {
        if (!this.importForm.images || this.importForm.images.length === 0) {
            return { success: true, count: 0 };
        }
        try {
            const formData = new FormData();
            this.importForm.images.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/import/${receiptId}/images`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok) {
                return { success: true, count: data.images?.length || 0 };
            } else {
                return { success: false, error: data.detail || 'Upload failed' };
            }
        } catch (error) {
            return { success: false, error: error.message };
        }
    },
    // --- IMPORT MODAL ---
    openImportModal() {
        this.resetImportForm();
        this.isImportModalOpen = true;
    },



    async handleImportPaste(event) {
        if (!this.isImportModalOpen) return;

        const items = (event.clipboardData || event.originalEvent.clipboardData).items;
        const files = [];

        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf("image") !== -1) {
                const file = items[i].getAsFile();
                if (file) files.push(file);
            }
        }

        if (files.length > 0) {
            // Process pasted files
            for (const file of files) {
                if (file.size > 10 * 1024 * 1024) {
                    alert(`File ${file.name} quá lớn (tối đa 10MB)`);
                    continue;
                }
                try {
                    const preview = URL.createObjectURL(file);
                    const compressedFile = await this.compressImage(file);
                    this.importForm.images.push({
                        file: compressedFile || file,
                        preview: preview,
                        name: file.name, // Usually 'image.png' for clipboard
                        size: compressedFile ? compressedFile.size : file.size
                    });
                } catch (error) { console.error('Error processing image:', error); }
            }
        }
    },

    async handleEditPaste(event) {
        if (!this.isEditImportModalOpen) return;

        const items = (event.clipboardData || event.originalEvent.clipboardData).items;
        const files = [];

        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf("image") !== -1) {
                const file = items[i].getAsFile();
                if (file) files.push(file);
            }
        }

        if (files.length > 0) {
            for (const file of files) {
                if (file.size > 10 * 1024 * 1024) {
                    alert(`File ${file.name} quá lớn (tối đa 10MB)`);
                    continue;
                }
                try {
                    const preview = URL.createObjectURL(file);
                    const compressedFile = await this.compressImage(file);
                    this.editImportForm.newImages.push({
                        file: compressedFile || file,
                        preview: preview,
                        name: file.name,
                        size: compressedFile ? compressedFile.size : file.size
                    });
                } catch (error) { console.error('Error processing image (edit):', error); }
            }
        }
    }
};
