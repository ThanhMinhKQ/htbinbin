export default {
    // --- QUERY ---
    async fetchHistory(page = 1) {
        this.loading = true;
        this.currentPage = page;
        this.selectedIds = [];
        this.lastCheckedId = null;

        let url = `/api/inventory/requests?branch_id=${this.currentBranchId || 0}&page=${page}&per_page=${this.perPage}`;
        if (this.filters.status) url += `&status=${this.filters.status}`;
        if (this.filters.search) url += `&search=${encodeURIComponent(this.filters.search)}`;
        if (this.filters.date_from) url += `&date_from=${this.filters.date_from}`;
        if (this.filters.date_to) url += `&date_to=${this.filters.date_to}`;

        url += `&sort_by=${this.currentSortBy}&sort_order=${this.currentSortOrder}`;

        try {
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                if (data.records) {
                    this.historyList = data.records;
                    this.totalRecords = data.totalRecords;
                    this.totalPages = data.totalPages;
                } else {
                    this.historyList = data;
                    this.totalRecords = data.length;
                    this.totalPages = 1;
                }
                this.renderPagination();
                this.updateSortIndicators();
            }
        } catch (e) {
            console.error(e);
        } finally {
            this.loading = false;
        }
    },

    resetDateFilter() {
        const range = this.getCurrentMonthRange();
        this.filters.date_from = range.start;
        this.filters.date_to = range.end;
        this.filters.status = '';
        this.filters.search = '';
        this.fetchHistory(1);
    },

    changePage(page) {
        if (page < 1 || page > this.totalPages) return;
        this.fetchHistory(page);
    },

    // --- SORT ---
    sortBy(column) {
        if (this.currentSortBy === column) {
            this.currentSortOrder = this.currentSortOrder === 'asc' ? 'desc' : 'asc';
        } else {
            this.currentSortBy = column;
            this.currentSortOrder = 'desc';
        }
        this.fetchHistory(1);
    },

    updateSortIndicators() {
        document.querySelectorAll('.sortable').forEach(th => {
            th.classList.remove('asc', 'desc');
            const indicator = th.querySelector('.sort-indicator');
            if (!indicator) return;

            if (th.dataset.sort === this.currentSortBy) {
                th.classList.add(this.currentSortOrder);
                indicator.innerHTML = this.currentSortOrder === 'asc' ? '&#9650;' : '&#9660;';
            } else {
                indicator.innerHTML = '&#8693;';
            }
        });
    },

    // --- PAGINATION UI ---
    renderPagination() {
        const paginationEl = document.getElementById('request-pagination-controls');
        const countEl = document.getElementById('request-record-count');
        if (!paginationEl || !countEl) return;

        paginationEl.innerHTML = '';

        if (this.totalRecords === 0) {
            countEl.textContent = 'Không có yêu cầu nào.';
            return;
        }

        countEl.innerHTML = `Hiển thị <span class="font-bold text-slate-700 dark:text-slate-300">${this.historyList.length}</span> / <span class="font-bold text-slate-700 dark:text-slate-300">${this.totalRecords}</span> phiếu`;

        if (this.totalPages <= 1) return;

        const createButton = (text, page, isDisabled = false, isCurrent = false) => {
            const button = document.createElement('button');
            button.innerHTML = text;
            let baseClasses = 'px-3 py-1 rounded-lg border text-sm font-semibold transition-colors';
            if (isCurrent) button.className = `${baseClasses} bg-blue-600 text-white border-blue-600 cursor-default shadow-sm`;
            else if (isDisabled) button.className = `${baseClasses} bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700 cursor-not-allowed`;
            else button.className = `${baseClasses} bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300`;

            if (!isDisabled && !isCurrent) {
                button.addEventListener('click', () => {
                    this.changePage(page);
                });
            }
            return button;
        };

        paginationEl.appendChild(createButton('&laquo;', 1, this.currentPage === 1));
        paginationEl.appendChild(createButton('&lsaquo;', this.currentPage - 1, this.currentPage === 1));

        let startPage = Math.max(1, this.currentPage - 2);
        let endPage = Math.min(this.totalPages, this.currentPage + 2);

        if (this.currentPage <= 3) endPage = Math.min(5, this.totalPages);
        if (this.currentPage > this.totalPages - 3) startPage = Math.max(1, this.totalPages - 4);

        if (startPage > 1) {
            paginationEl.appendChild(createButton('1', 1));
            if (startPage > 2) paginationEl.insertAdjacentHTML('beforeend', `<span class="px-2 text-slate-400">...</span>`);
        }

        for (let i = startPage; i <= endPage; i++) {
            paginationEl.appendChild(createButton(i, i, false, i === this.currentPage));
        }

        if (endPage < this.totalPages) {
            if (endPage < this.totalPages - 1) paginationEl.insertAdjacentHTML('beforeend', `<span class="px-2 text-slate-400">...</span>`);
            paginationEl.appendChild(createButton(this.totalPages, this.totalPages));
        }

        paginationEl.appendChild(createButton('&rsaquo;', this.currentPage + 1, this.currentPage === this.totalPages));
        paginationEl.appendChild(createButton('&raquo;', this.totalPages, this.currentPage === this.totalPages));
    },

    // --- SELECTION ---
    handleCheckboxClick(event, id, index) {
        if (event.shiftKey && this.lastCheckedId !== null) {
            const lastIndex = this.historyList.findIndex(t => t.id === this.lastCheckedId);
            const currentIndex = index;

            if (lastIndex !== -1 && currentIndex !== -1) {
                const start = Math.min(lastIndex, currentIndex);
                const end = Math.max(lastIndex, currentIndex);
                const idsToSelect = this.historyList.slice(start, end + 1).map(t => t.id);
                this.selectedIds = [...new Set([...this.selectedIds, ...idsToSelect])];
            }
        } else {
            this.toggleSelection(id);
        }
        this.lastCheckedId = id;
    },

    toggleSelectAll() {
        if (this.selectedIds.length === this.historyList.length) {
            this.selectedIds = [];
        } else {
            this.selectedIds = this.historyList.filter(t => t.status === 'PENDING').map(t => t.id);
        }
    },

    toggleSelection(id) {
        if (this.selectedIds.includes(id)) {
            this.selectedIds = this.selectedIds.filter(i => i !== id);
        } else {
            this.selectedIds.push(id);
        }
    },

    // --- CRUD ---
    async deleteRequest(id) {
        if (!confirm("Bạn có chắc chắn muốn xóa yêu cầu này không?")) return;
        try {
            const res = await fetch(`/api/inventory/request/${id}`, { method: 'DELETE' });
            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.fetchHistory(this.currentPage);
            } else {
                alert(data.detail || "Không thể xóa");
            }
        } catch (e) { alert("Lỗi kết nối"); }
    },

    async batchDelete() {
        if (!confirm(`Bạn có chắc chắn muốn xóa ${this.selectedIds.length} yêu cầu đã chọn?`)) return;

        this.loading = true;
        let successCount = 0;
        for (let id of this.selectedIds) {
            try {
                const res = await fetch(`/api/inventory/request/${id}`, { method: 'DELETE' });
                if (res.ok) successCount++;
            } catch (e) { }
        }
        this.loading = false;
        alert(`Đã xóa ${successCount}/${this.selectedIds.length} yêu cầu.`);
        this.selectedIds = [];
        this.fetchHistory(this.currentPage);
    },

    // --- CREATE ---
    openCreateModal() {
        this.createForm = {
            source_warehouse_id: '',
            itemGroups: [this.createEmptyGroup()],
            notes: ''
        };
        this.isCreateModalOpen = true;
    },
    closeCreateModal() { this.isCreateModalOpen = false; },

    addCategoryGroupToCreate() {
        this.createForm.itemGroups.push(this.createEmptyGroup());
    },
    removeCategoryGroupFromCreate(index) {
        this.createForm.itemGroups.splice(index, 1);
    },
    addItemToCreateGroup(groupIndex) {
        this.createForm.itemGroups[groupIndex].items.push(this.createEmptyItem());
    },
    removeItemFromCreateGroup(groupIndex, itemIndex) {
        this.createForm.itemGroups[groupIndex].items.splice(itemIndex, 1);
    },
    onCreateProductChange(groupIndex, itemIndex) {
        const group = this.createForm.itemGroups[groupIndex];
        const item = group.items[itemIndex];
        this.updateItemUnit(item);
    },

    async submitCreateRequest() {
        const itemsToSubmit = this.getFlatCreateFormItems();

        if (!this.createForm.source_warehouse_id) return alert("Vui lòng chọn Kho nguồn!");
        if (itemsToSubmit.length === 0) return alert("Vui lòng thêm ít nhất 1 sản phẩm!");

        for (let item of itemsToSubmit) {
            if (!item.product_id || !item.quantity || !item.unit) {
                return alert("Vui lòng điền đầy đủ thông tin sản phẩm (Tên, Số lượng, Đơn vị)");
            }
        }

        this.isSubmitting = true;
        try {
            const payload = {
                source_warehouse_id: this.createForm.source_warehouse_id || null,
                dest_warehouse_id: this.currentWarehouseId,  // [FIX] Use warehouse ID instead of branch ID
                notes: this.createForm.notes,
                items: itemsToSubmit.map(i => ({
                    product_id: i.product_id,
                    quantity: parseFloat(i.quantity),
                    unit: i.unit
                }))
            };

            const res = await fetch('/api/inventory/request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.closeCreateModal();
                this.fetchHistory(1);
            } else {
                alert(data.detail || "Lỗi xử lý");
            }
        } catch (e) { alert("Lỗi kết nối"); }
        finally { this.isSubmitting = false; }
    },

    // --- EDIT ---
    openEditModal(t) {
        this.editingId = t.id;
        this.isEditModalOpen = true;

        setTimeout(() => {
            this.editForm.source_warehouse_id = t.source_warehouse_id ? String(t.source_warehouse_id) : '';
            this.editForm.notes = t.notes || '';

            const groupsMap = {};

            if (t.items && t.items.length > 0) {
                t.items.forEach(item => {
                    let catId = (item.category_id !== null && item.category_id !== undefined) ? String(item.category_id) : null;

                    if (!catId) {
                        const productRef = this.normalizedProducts.find(p => String(p.id) === String(item.product_id));
                        if (productRef && productRef.category_id) {
                            catId = String(productRef.category_id);
                        } else {
                            catId = 'OTHER';
                        }
                    }

                    if (!groupsMap[catId]) {
                        groupsMap[catId] = {
                            id: Date.now() + Math.random(),
                            category_id: catId === 'OTHER' ? '' : ('' + catId),
                            items: []
                        };
                    }

                    let available_units = [item.request_unit];
                    const product = this.normalizedProducts.find(p => String(p.id) === String(item.product_id));

                    if (product) {
                        available_units = [product.base_unit];
                        if (product.packing_unit && product.conversion_rate > 1) {
                            available_units.unshift(product.packing_unit);
                        }
                    }

                    groupsMap[catId].items.push({
                        id: Date.now() + Math.random(),
                        product_id: '' + String(item.product_id),
                        quantity: parseFloat(item.request_quantity),
                        unit: String(item.request_unit),
                        available_units: available_units
                    });
                });

                this.editForm.itemGroups = Object.values(groupsMap);
            } else {
                this.editForm.itemGroups = [this.createEmptyGroup()];
            }
        }, 200);
    },

    closeEditModal() {
        this.isEditModalOpen = false;
        this.editingId = null;
    },

    addCategoryGroupToEdit() {
        this.editForm.itemGroups.push(this.createEmptyGroup());
    },
    removeCategoryGroupFromEdit(index) {
        this.editForm.itemGroups.splice(index, 1);
    },
    addItemToEditGroup(groupIndex) {
        this.editForm.itemGroups[groupIndex].items.push(this.createEmptyItem());
    },
    removeItemFromEditGroup(groupIndex, itemIndex) {
        this.editForm.itemGroups[groupIndex].items.splice(itemIndex, 1);
    },
    onEditProductChange(groupIndex, itemIndex) {
        const group = this.editForm.itemGroups[groupIndex];
        const item = group.items[itemIndex];
        this.updateItemUnit(item);
    },

    async submitEditRequest() {
        const itemsToSubmit = this.getFlatEditFormItems();

        if (!this.editForm.source_warehouse_id) return alert("Vui lòng chọn Kho nguồn!");
        if (itemsToSubmit.length === 0) return alert("Vui lòng thêm ít nhất 1 sản phẩm!");

        for (let item of itemsToSubmit) {
            if (!item.product_id || !item.quantity || !item.unit) {
                return alert("Vui lòng điền đầy đủ thông tin sản phẩm (Tên, Số lượng, Đơn vị)");
            }
        }

        this.isSubmitting = true;
        try {
            const payload = {
                source_warehouse_id: this.editForm.source_warehouse_id || null,
                dest_warehouse_id: this.currentWarehouseId,  // [FIX] Use warehouse ID instead of branch ID
                notes: this.editForm.notes,
                items: itemsToSubmit.map(i => ({
                    product_id: i.product_id,
                    quantity: parseFloat(i.quantity),
                    unit: i.unit
                }))
            };

            const res = await fetch(`/api/inventory/request/${this.editingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.closeEditModal();
                this.fetchHistory(this.currentPage);
            } else {
                alert(data.detail || "Lỗi xử lý");
            }
        } catch (e) { alert("Lỗi kết nối"); }
        finally { this.isSubmitting = false; }
    },

    // --- VIEW DETAIL ---
    async fetchRequestDetail(id) {
        this.loading = true;
        try {
            const res = await fetch(`/api/inventory/request/${id}`);
            if (res.ok) {
                const data = await res.json();
                this.viewingRequestTicket = data;
            } else {
                const err = await res.json();
                alert(err.detail || "Không tìm thấy thông tin phiếu.");
            }
        } catch (e) {
            console.error(e);
            alert("Lỗi kết nối server.");
        } finally {
            this.loading = false;
        }
    },

    openRequestDetailModal(t) { this.viewingRequestTicket = t; },
    closeRequestDetailModal() { this.viewingRequestTicket = null; },

    openChildModal(t) {
        const itemsWithCats = (t.items || []).map(i => {
            const product = this.productList.find(p => p.id == i.product_id);
            return {
                ...i,
                category_name: product ? (product.category_name || 'Khác') : 'Khác'
            };
        });

        const parent = this.viewingRequestTicket || this.viewingApprovalTicket || {};
        this.viewingChildTicket = {
            ...t,
            items: itemsWithCats,
            source_warehouse_name: t.source_warehouse_name || parent.source_warehouse_name || 'N/A',
            requester_name: t.requester_name || parent.requester_name || 'N/A',
            approver_name: t.approver_name || parent.approver_name,
            approver_notes: t.approver_notes || parent.approver_notes
        };
    },
    closeChildModal() { this.viewingChildTicket = null; }
};
