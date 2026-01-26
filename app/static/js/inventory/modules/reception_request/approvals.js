export default {
    async fetchApprovals(page = 1) {
        if (!this.currentBranchId) return;
        this.loadingApprovals = true;
        this.currentApprovalPage = page;
        this.approvalsList = [];

        let statusParam = 'PENDING';
        if (this.approvalFilter === 'HISTORY') {
            // Priority: Specific status filter > Default History status list
            if (this.approvalFilters.status) {
                statusParam = this.approvalFilters.status;
            } else {
                statusParam = 'APPROVED,SHIPPING,COMPLETED,REJECTED,CANCELLED';
            }
        }

        let url = `/api/inventory/requests?source_branch_id=${this.currentBranchId}&status=${statusParam}&page=${page}&per_page=${this.perPage}`;

        // Add search filter if exists
        if (this.approvalFilters && this.approvalFilters.search) {
            url += `&search=${encodeURIComponent(this.approvalFilters.search)}`;
        }
        if (this.approvalFilters && this.approvalFilters.requester) {
            url += `&requester_name=${encodeURIComponent(this.approvalFilters.requester)}`;
        }
        if (this.approvalFilters && this.approvalFilters.date_from) {
            url += `&date_from=${this.approvalFilters.date_from}`;
        }
        if (this.approvalFilters && this.approvalFilters.date_to) {
            url += `&date_to=${this.approvalFilters.date_to}`;
        }

        try {
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                if (data.records) {
                    this.approvalsList = data.records;
                    this.totalApprovalRecords = data.totalRecords;
                    this.totalApprovalPages = data.totalPages;
                } else if (Array.isArray(data)) {
                    this.approvalsList = data;
                    this.totalApprovalRecords = data.length;
                    this.totalApprovalPages = 1;
                } else {
                    this.approvalsList = [];
                    this.totalApprovalRecords = 0;
                    this.totalApprovalPages = 1;
                }

                if (this.approvalFilter === 'PENDING') {
                    this.pendingCount = this.approvalsList.length; // Might be inaccurate if paginated, but acceptable used for badge?
                    // Actually if paginated, pending count should ideally come from a separate "count" API or just show "99+" or distinct from list.
                    // For now, let's keep it simple.
                    this.pendingCount = data.totalRecords || this.approvalsList.length;
                }
                this.renderApprovalPagination();
            }
        } catch (e) { console.error(e); }
        finally { this.loadingApprovals = false; }
    },

    renderApprovalPagination() {
        const paginationEl = document.getElementById('approval-pagination-controls');
        const countEl = document.getElementById('approval-record-count');
        if (!paginationEl || !countEl) return;

        paginationEl.innerHTML = '';

        if (this.totalApprovalRecords === 0) {
            countEl.textContent = 'Không có yêu cầu nào.';
            return;
        }

        countEl.innerHTML = `Hiển thị <span class="font-bold text-slate-700 dark:text-slate-300">${this.approvalsList.length}</span> / <span class="font-bold text-slate-700 dark:text-slate-300">${this.totalApprovalRecords}</span> phiếu`;

        if (this.totalApprovalPages <= 1) return;

        const createButton = (text, page, isDisabled = false, isCurrent = false) => {
            const button = document.createElement('button');
            button.innerHTML = text;
            let baseClasses = 'px-3 py-1 rounded-lg border text-sm font-semibold transition-colors';
            if (isCurrent) button.className = `${baseClasses} bg-orange-600 text-white border-orange-600 cursor-default shadow-sm`;
            else if (isDisabled) button.className = `${baseClasses} bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700 cursor-not-allowed`;
            else button.className = `${baseClasses} bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300`;

            if (!isDisabled && !isCurrent) {
                button.addEventListener('click', () => {
                    this.fetchApprovals(page);
                });
            }
            return button;
        };

        paginationEl.appendChild(createButton('&laquo;', 1, this.currentApprovalPage === 1));
        paginationEl.appendChild(createButton('&lsaquo;', this.currentApprovalPage - 1, this.currentApprovalPage === 1));

        let startPage = Math.max(1, this.currentApprovalPage - 2);
        let endPage = Math.min(this.totalApprovalPages, this.currentApprovalPage + 2);

        if (this.currentApprovalPage <= 3) endPage = Math.min(5, this.totalApprovalPages);
        if (this.currentApprovalPage > this.totalApprovalPages - 3) startPage = Math.max(1, this.totalApprovalPages - 4);

        if (startPage > 1) {
            paginationEl.appendChild(createButton('1', 1));
            if (startPage > 2) paginationEl.insertAdjacentHTML('beforeend', `<span class="px-2 text-slate-400">...</span>`);
        }

        for (let i = startPage; i <= endPage; i++) {
            paginationEl.appendChild(createButton(i, i, false, i === this.currentApprovalPage));
        }

        if (endPage < this.totalApprovalPages) {
            if (endPage < this.totalApprovalPages - 1) paginationEl.insertAdjacentHTML('beforeend', `<span class="px-2 text-slate-400">...</span>`);
            paginationEl.appendChild(createButton(this.totalApprovalPages, this.totalApprovalPages));
        }

        paginationEl.appendChild(createButton('&rsaquo;', this.currentApprovalPage + 1, this.currentApprovalPage === this.totalApprovalPages));
        paginationEl.appendChild(createButton('&raquo;', this.totalApprovalPages, this.currentApprovalPage === this.totalApprovalPages));
    },

    resetApprovalDateFilter() {
        const range = this.getCurrentMonthRange();
        this.approvalFilters.date_from = range.start;
        this.approvalFilters.date_to = range.end;
        this.approvalFilters.status = '';
        this.approvalFilters.requester = '';
        this.approvalFilters.search = '';
        this.fetchApprovals();
    },

    fetchPendingApprovals() {
        this.approvalFilter = 'PENDING';
        return this.fetchApprovals();
    },

    // --- APPROVAL DETAIL ---
    openApprovalDetailModal(t) { this.viewingApprovalTicket = t; },
    closeApprovalDetailModal() { this.viewingApprovalTicket = null; },

    // --- APPROVAL ACTION ---
    openApprovalModal(t) {
        this.approvingTicket = t;
        this.approvalForm.items = t.items.map(i => {
            const product = this.productList.find(p => p.id == i.product_id);
            return {
                ...i,
                approved_quantity: i.request_quantity,
                category_name: product ? (product.category_name || 'Khác') : 'Khác'
            };
        });
        this.approvalForm.approver_notes = '';

        const groups = {};
        this.approvalForm.items.forEach(item => {
            const cat = item.category_name || 'Khác';
            if (!groups[cat]) groups[cat] = [];
            groups[cat].push(item);
        });
        this.approvalGroups = Object.entries(groups).map(([category, items]) => ({ category, items }));
    },

    closeApprovalModal() { this.approvingTicket = null; },

    async submitApproval() {
        if (!this.approvingTicket) return;

        this.isSubmitting = true;
        try {
            const payload = {
                items: this.approvalForm.items.map(i => ({
                    id: i.id, product_id: i.product_id, approved_quantity: i.approved_quantity
                })),
                approver_notes: this.approvalForm.approver_notes
            };
            const res = await fetch(`/api/inventory/approve/${this.approvingTicket.id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.closeApprovalModal();
                this.fetchApprovals();
            } else { alert(data.detail); }
        } catch (e) { alert("Lỗi server"); }
        finally { this.isSubmitting = false; }
    },

    async submitRejection() {
        if (!this.approvingTicket) return;
        const notes = prompt("Nhập lý do từ chối:");
        if (notes === null) return;

        this.isSubmitting = true;
        try {
            const res = await fetch(`/api/inventory/reject/${this.approvingTicket.id}?rejection_notes=${encodeURIComponent(notes)}`, {
                method: 'POST'
            });
            const data = await res.json();
            if (res.ok) {
                alert(data.message);
                this.closeApprovalModal();
                this.fetchApprovals();
            } else { alert(data.detail); }
        } catch (e) { alert("Lỗi server"); }
        finally { this.isSubmitting = false; }
    },

    // --- RECEIPT/INBOUND ---
    openReceiptModal(t) {
        const parent = this.viewingRequestTicket || this.viewingApprovalTicket || {};
        this.receivingTicket = {
            ...t,
            source_warehouse_name: t.source_warehouse_name || parent.source_warehouse_name || 'N/A',
            requester_name: t.requester_name || parent.requester_name || 'N/A',
            approver_name: t.approver_name || parent.approver_name,
            approver_notes: t.approver_notes || parent.approver_notes
        };

        let hasCutQuantity = false;

        this.receiptForm.items = t.items.map(i => {
            // Check for cut quantity
            if (i.approved_quantity < (i.request_quantity - 0.01)) {
                hasCutQuantity = true;
            }

            return {
                id: i.id,
                product_id: i.product_id,
                product_name: i.product_name,
                category_name: this.productList.find(p => p.id == i.product_id)?.category_name || 'Khác',
                request_quantity: i.request_quantity,
                request_unit: i.request_unit,
                approved_quantity: i.approved_quantity,
                received_quantity: i.approved_quantity, // Default
                loss_quantity: 0,
                loss_reason: ''
            }
        });

        this.receivingTicket.canCompensateRoot = hasCutQuantity;
        this.receiptForm.compensation_mode = 'none';

        // [NEW] Reset images
        this.receiptForm.images = [];
        this.isReceiptModalOpen = true;
    },

    closeReceiptModal() {
        if (this.receiptForm.images) {
            this.receiptForm.images.forEach(img => {
                if (img.preview) URL.revokeObjectURL(img.preview);
            });
        }
        this.receiptForm.images = [];
        this.isReceiptModalOpen = false;
        this.receivingTicket = null;
    },

    async submitReceipt() {
        if (!this.receivingTicket) return;

        this.isSubmitting = true;
        try {
            const payload = {
                items: this.receiptForm.items.map(i => ({
                    id: i.id,
                    product_id: i.product_id,
                    received_quantity: i.received_quantity,
                    loss_quantity: i.loss_quantity,
                    loss_reason: i.loss_reason
                })),
                compensation_mode: this.receiptForm.compensation_mode
            };

            const res = await fetch(`/api/inventory/receive/${this.receivingTicket.id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok) {
                // Upload images if any
                if (this.receiptForm.images && this.receiptForm.images.length > 0) {
                    await this.uploadReceiptImages(this.receivingTicket.id);
                }

                alert(data.message);
                this.closeReceiptModal();
                this.fetchHistory(this.currentPage);
                this.fetchApprovals(); // Refresh approvals tab too if needed
            } else {
                alert(data.detail || "Lỗi khi nhận hàng");
            }
        } catch (e) { alert("Lỗi kết nối"); }
        finally { this.isSubmitting = false; }
    },

    hasAnyLoss() {
        return this.receiptForm.items.some(i => i.loss_quantity > 0);
    },

    // --- RECEIPT IMAGES ---
    async handleReceiptImageUpload(event) {
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
                // Use imported compressImage from utils/imports or ensure it's available. 
                // Assuming it's mixed in index.js via imports object, but compressImage is in imports.js?
                // Wait, compressImage is likely in imports.js but attached to 'this'.
                // If it's not present, I need to define it or ensure it's available.
                // Assuming imports.js is mixed in, `this.compressImage` might refer to imports.js's method IF imports.js is mixed in the SAME object.
                // Yes, index.js mixes `...imports`.

                let compressedFile = file;
                if (this.compressImage) {
                    compressedFile = await this.compressImage(file);
                }

                this.receiptForm.images.push({
                    file: compressedFile || file,
                    preview: preview,
                    name: file.name,
                    size: compressedFile ? compressedFile.size : file.size
                });
            } catch (error) { console.error('Error processing image:', error); }
        }
        event.target.value = '';
    },

    removeReceiptImage(index) {
        if (this.receiptForm.images[index].preview) {
            URL.revokeObjectURL(this.receiptForm.images[index].preview);
        }
        this.receiptForm.images.splice(index, 1);
    },

    async uploadReceiptImages(ticketId) {
        if (!this.receiptForm.images || this.receiptForm.images.length === 0) return;
        try {
            const formData = new FormData();
            this.receiptForm.images.forEach((img) => {
                formData.append('files', img.file);
            });
            const res = await fetch(`/api/inventory/transfer/${ticketId}/images`, {
                method: 'POST',
                body: formData
            });
            return await res.json();
        } catch (error) {
            console.error(error);
        }
    }
};
