export default {
    formatMoney(amount) {
        return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(amount);
    },

    formatDate(dateString) {
        if (!dateString) return '';
        try {
            // Parse the date string
            // If the string doesn't have timezone info, treat it as UTC
            let date;
            if (typeof dateString === 'string') {
                // If no timezone indicator, assume it's UTC from server
                if (dateString.indexOf('Z') === -1 && dateString.indexOf('+') === -1 && dateString.indexOf('-', 10) === -1) {
                    date = new Date(dateString + 'Z');
                } else {
                    date = new Date(dateString);
                }
            } else {
                date = new Date(dateString);
            }

            if (isNaN(date.getTime())) return dateString; // Return original if parse fails

            // Format with Vietnam timezone
            return new Intl.DateTimeFormat('vi-VN', {
                hour: '2-digit',
                minute: '2-digit',
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                timeZone: 'Asia/Ho_Chi_Minh'
            }).format(date);
        } catch (e) {
            console.error("Date formatting error:", e, dateString);
            return dateString;
        }
    },

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    },

    getStatusClass(status) {
        const map = {
            'PENDING': 'bg-yellow-100 text-yellow-700 border-yellow-200',
            'APPROVED': 'bg-green-100 text-green-700 border-green-200',
            'SHIPPING': 'bg-blue-100 text-blue-700 border-blue-200 animate-pulse',
            'COMPLETED': 'bg-slate-200 text-slate-700 border-slate-300',
            'REJECTED': 'bg-red-100 text-red-700 border-red-200',
            'CANCELLED': 'bg-slate-100 text-slate-700 border-slate-200'
        };
        return map[status] || 'bg-gray-100 text-gray-700 border-gray-200';
    },

    getStatusLabel(status) {
        const map = {
            'PENDING': 'Chờ duyệt',
            'APPROVED': 'Đã duyệt',
            'SHIPPING': 'Đang giao',
            'COMPLETED': 'Đã nhận',
            'REJECTED': 'Từ chối',
            'CANCELLED': 'Đã hủy'
        };
        return map[status] || status;
    },

    createEmptyGroup() {
        return {
            id: Date.now() + Math.random(),
            category_id: '',
            items: [this.createEmptyItem()]
        };
    },

    createEmptyItem() {
        return {
            id: Date.now() + Math.random(),
            product_id: '',
            quantity: 1,
            unit: '',
            available_units: []
        };
    },

    updateItemUnit(item) {
        const product = this.normalizedProducts.find(p => p.id === item.product_id);
        if (product) {
            item.available_units = [product.base_unit];
            if (product.packing_unit && product.conversion_rate > 1) {
                item.available_units.unshift(product.packing_unit);
            }
            item.unit = item.available_units[0];
        }
    },

    async compressImage(file) {
        return new Promise((resolve) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');

                    let width = img.width;
                    let height = img.height;
                    const maxWidth = 1920;
                    const maxHeight = 1080;

                    if (width > maxWidth || height > maxHeight) {
                        const ratio = Math.min(maxWidth / width, maxHeight / height);
                        width = width * ratio;
                        height = height * ratio;
                    }

                    canvas.width = width;
                    canvas.height = height;
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob(
                        (blob) => {
                            if (blob && blob.size < file.size) {
                                const compressedFile = new File([blob], file.name, {
                                    type: 'image/jpeg',
                                    lastModified: Date.now()
                                });
                                resolve(compressedFile);
                            } else {
                                resolve(null);
                            }
                        },
                        'image/jpeg',
                        0.85
                    );
                };
                img.src = e.target.result;
            };

            reader.readAsDataURL(file);
        });
    },

    // View Image method commonly used
    viewImage(img) {
        this.viewingImage = img;
    },

    async captureModal(element) {
        if (!element) return;

        try {
            // Find the actual content wrapper to capture, or use the element itself
            // Modals usually have a white background container.
            const content = element.querySelector('.bg-white') || element;

            // Visual feedback
            const originalOpacity = content.style.opacity;
            content.style.opacity = '0.7';

            const canvas = await html2canvas(content, {
                scale: 1.5, // Better quality but not too huge
                useCORS: true,
                logging: false,
                backgroundColor: '#ffffff'
            });

            content.style.opacity = originalOpacity;

            canvas.toBlob(async (blob) => {
                try {
                    const item = new ClipboardItem({ 'image/png': blob });
                    await navigator.clipboard.write([item]);
                    alert("Đã chụp và lưu ảnh vào Clipboard!");
                } catch (err) {
                    console.error('Clipboard failed:', err);
                    alert("Không thể lưu vào clipboard. Bạn có thể lưu ảnh thủ công bằng cách chuột phải -> Lưu.");
                    // Fallback: Open image in new tab or show it? 
                    // For now, simpler is better.
                }
            });
        } catch (e) {
            console.error(e);
            alert("Lỗi khi chụp màn hình: " + e.message);
        }
    },

    getCurrentMonthRange() {
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
    },

    getCurrentWarehouseId() {
        return this.currentWarehouseId;
    },

    createPaginationHTML(currentPage, totalPages, fetchMethodName) {
        if (totalPages <= 1) return '';

        let html = '';

        // Previous Button
        html += `<button class="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 disabled:opacity-50" 
            ${currentPage === 1 ? 'disabled' : `onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${currentPage - 1})"`}>
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
            </svg>
        </button>`;

        // Page Numbers
        let startPage = Math.max(1, currentPage - 2);
        let endPage = Math.min(totalPages, currentPage + 2);

        if (startPage > 1) {
            html += `<button class="px-3 py-1 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600"
                onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(1)">1</button>`;
            if (startPage > 2) {
                html += `<span class="px-1 text-slate-400">...</span>`;
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            const activeClass = i === currentPage
                ? 'bg-red-50 text-red-600 font-bold border border-red-200'
                : 'hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600';

            html += `<button class="px-3 py-1 rounded-md text-sm ${activeClass}"
                onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${i})">${i}</button>`;
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                html += `<span class="px-1 text-slate-400">...</span>`;
            }
            html += `<button class="px-3 py-1 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600"
                onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${totalPages})">${totalPages}</button>`;
        }

        // Next Button
        html += `<button class="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 disabled:opacity-50" 
            ${currentPage === totalPages ? 'disabled' : `onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${currentPage + 1})"`}>
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
        </button>`;

        return html;
    }
};
