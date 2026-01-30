export default {
    formatMoney(amount) {
        return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(amount);
    },

    formatDate(dateString) {
        if (!dateString) return '';
        try {
            let date;
            if (typeof dateString === 'string') {
                if (dateString.indexOf('Z') === -1 && dateString.indexOf('+') === -1 && dateString.indexOf('-', 10) === -1) {
                    date = new Date(dateString + 'Z');
                } else {
                    date = new Date(dateString);
                }
            } else {
                date = new Date(dateString);
            }
            if (isNaN(date.getTime())) return dateString;
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
        // Giả định có this.normalizedProducts ở context gọi
        if (this.normalizedProducts) {
            const product = this.normalizedProducts.find(p => p.id === item.product_id);
            if (product) {
                item.available_units = [product.base_unit];
                if (product.packing_unit && product.conversion_rate > 1) {
                    item.available_units.unshift(product.packing_unit);
                }
                item.unit = item.available_units[0];
            }
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
                    canvas.toBlob((blob) => {
                        if (blob && blob.size < file.size) {
                            resolve(new File([blob], file.name, { type: 'image/jpeg', lastModified: Date.now() }));
                        } else {
                            resolve(null);
                        }
                    }, 'image/jpeg', 0.85);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    },

    viewImage(img) {
        this.viewingImage = img;
    },

    // --- CẢI TIẾN LỚN CHO MANAGER (FULL BILL & INPUT FIX) ---
    async captureModal(element) {
        if (!element) return;

        // 1. Hiệu ứng Loading chuyên nghiệp
        const loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'fixed inset-0 z-[9999] bg-slate-900/90 backdrop-blur-md flex flex-col items-center justify-center transition-opacity duration-300';
        loadingOverlay.id = 'capture-loading-overlay';
        loadingOverlay.innerHTML = `
            <div class="relative w-20 h-20 mb-4">
                <div class="absolute top-0 left-0 w-full h-full border-4 border-slate-700 rounded-full"></div>
                <div class="absolute top-0 left-0 w-full h-full border-4 border-blue-500 rounded-full animate-spin border-t-transparent"></div>
            </div>
            <p class="text-white font-bold text-xl tracking-tight animate-pulse">Đang xuất phiếu...</p>
            <p class="text-slate-400 text-sm mt-2">Đang xử lý dữ liệu và định dạng bản in</p>
        `;
        document.body.appendChild(loadingOverlay);

        // Đợi render UI
        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 200)));

        try {
            // 2. Tìm Container chính xác (Smart Detection)
            let content;
            // Ưu tiên tìm content bên trong modal container
            const contentSelectors = '.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full, .max-w-screen-xl';

            if (element.matches(contentSelectors)) {
                content = element;
            } else {
                content = element.querySelector(contentSelectors);
            }

            // Fallback: Tìm container màu trắng/sáng
            if (!content) {
                content = element.querySelector('.bg-white, .bg-slate-50, .dark\\:bg-slate-900') || element;
            }

            // 3. Chuẩn bị Snapshot (Lưu state cũ)
            const originalStyles = [];
            const modifyStyle = (el, styles) => {
                const originalState = { element: el, styles: {} };
                for (const prop in styles) {
                    originalState.styles[prop] = el.style[prop];
                    el.style[prop] = styles[prop];
                }
                originalStyles.push(originalState);
            };

            // Ẩn nút bấm, thanh cuộn, các element thừa
            const ignoredElements = content.querySelectorAll('button, .close-btn, [role="button"], ::-webkit-scrollbar');
            ignoredElements.forEach(el => modifyStyle(el, { display: 'none' }));

            // 4. "FORCE EXPANSION" - Ép bung toàn bộ nội dung
            modifyStyle(content, {
                transform: 'none',
                transition: 'none',
                maxHeight: 'none',
                height: 'auto',
                overflow: 'visible',
                borderRadius: '0',
                boxShadow: 'none',
                margin: '0',
                width: content.scrollWidth + 'px' // Fix cứng chiều rộng để tránh vỡ layout khi bung
            });

            // Xử lý đệ quy tất cả phần tử con
            const allElements = content.querySelectorAll('*');
            allElements.forEach(el => {
                const computed = window.getComputedStyle(el);

                // a. Bung Scroll: Nếu đang có thanh cuộn -> ép hiện hết
                if (computed.overflowY === 'auto' || computed.overflowY === 'scroll' || computed.maxHeight !== 'none') {
                    modifyStyle(el, {
                        maxHeight: 'none',
                        height: 'auto',
                        overflow: 'visible'
                    });
                }

                // b. Bung Text: Nếu text bị cắt (truncate) -> ép xuống dòng
                if (
                    el.classList.contains('truncate') ||
                    computed.textOverflow === 'ellipsis' ||
                    computed.whiteSpace === 'nowrap'
                ) {
                    modifyStyle(el, {
                        whiteSpace: 'normal',
                        textOverflow: 'clip',
                        overflow: 'visible',
                        width: 'auto',
                        maxWidth: 'none'
                    });
                }

                // c. INPUT FREEZER (Quan trọng cho Manager): Biến Input thành Text tĩnh
                // Input số lượng, Input ghi chú...
                if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                    // Sẽ được xử lý triệt để trong onclone của html2canvas
                    // Nhưng ở đây ta set style sơ bộ để tránh layout shift
                    modifyStyle(el, {
                        border: 'none',
                        background: 'transparent',
                        boxShadow: 'none'
                    });
                }
            });

            // Chờ DOM cập nhật layout sau khi bung
            await new Promise(resolve => setTimeout(resolve, 500));

            const finalHeight = content.scrollHeight;
            const finalWidth = content.scrollWidth;

            // 5. Chụp ảnh với cấu hình Manager
            const canvas = await html2canvas(content, {
                scale: 2.5, // Tăng độ nét cho văn bản số
                useCORS: true,
                allowTaint: true,
                backgroundColor: '#ffffff', // Nền trắng chuẩn in ấn
                width: finalWidth,
                height: finalHeight,
                windowWidth: finalWidth,
                windowHeight: finalHeight,
                scrollY: 0,
                scrollX: 0,
                onclone: (clonedDoc) => {
                    const clonedContent = clonedDoc.body.querySelector(contentSelectors) || clonedDoc.body.firstChild;
                    if (!clonedContent) return;

                    // A. Xử lý Input/Textarea trong bản Clone (Để ảnh chụp hiện số rõ nét)
                    const inputs = clonedContent.querySelectorAll('input, textarea');
                    inputs.forEach(input => {
                        if (input.type === 'hidden' || input.style.display === 'none') return;

                        const value = input.value || input.getAttribute('placeholder') || '';
                        const s = window.getComputedStyle(input);

                        const div = clonedDoc.createElement('div');
                        div.textContent = value;

                        // Copy style quan trọng
                        div.style.fontFamily = s.fontFamily;
                        div.style.fontSize = s.fontSize;
                        div.style.fontWeight = 'bold'; // Ép đậm cho dễ đọc
                        div.style.color = s.color;
                        div.style.textAlign = s.textAlign; // Giữ căn giữa/trái/phải
                        div.style.padding = s.padding;
                        div.style.lineHeight = s.lineHeight;

                        // Style hiển thị
                        div.style.display = 'flex';
                        div.style.alignItems = 'center';
                        div.style.justifyContent = s.textAlign === 'center' ? 'center' : (s.textAlign === 'right' ? 'flex-end' : 'flex-start');
                        div.style.whiteSpace = 'pre-wrap'; // Cho phép xuống dòng với textarea
                        div.style.width = '100%';
                        div.style.minHeight = s.height;

                        if (input.parentNode) {
                            input.parentNode.replaceChild(div, input);
                        }
                    });

                    // B. Xóa placeholder trống nếu có
                    const emptyElements = clonedContent.querySelectorAll('.empty-placeholder');
                    emptyElements.forEach(el => el.style.display = 'none');
                }
            });

            // 6. Khôi phục hiện trạng (Undo Changes)
            for (let i = originalStyles.length - 1; i >= 0; i--) {
                const { element, styles } = originalStyles[i];
                for (const prop in styles) {
                    element.style[prop] = styles[prop];
                }
            }

            // 7. Xuất ảnh
            canvas.toBlob(async (blob) => {
                if (!blob) throw new Error("Canvas rỗng");
                try {
                    const item = new ClipboardItem({ 'image/png': blob });
                    await navigator.clipboard.write([item]);

                    // Thông báo custom đẹp
                    const msg = document.createElement('div');
                    msg.className = "fixed top-5 left-1/2 transform -translate-x-1/2 bg-green-600 text-white px-6 py-3 rounded-full shadow-2xl z-[10000] flex items-center gap-2 animate-bounce";
                    msg.innerHTML = `<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> Đã sao chép phiếu! (Ctrl+V)`;
                    document.body.appendChild(msg);
                    setTimeout(() => msg.remove(), 3000);

                } catch (err) {
                    // Fallback tải xuống
                    const link = document.createElement('a');
                    link.download = `Phieu_${Date.now()}.png`;
                    link.href = canvas.toDataURL();
                    link.click();
                }
            });

        } catch (e) {
            console.error("Capture failed:", e);
            alert("Lỗi khi tạo ảnh phiếu: " + e.message);
        } finally {
            const overlay = document.getElementById('capture-loading-overlay');
            if (overlay) overlay.remove();
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
        return { start: formatDate(firstDay), end: formatDate(lastDay) };
    },

    getCurrentWarehouseId() {
        return this.currentWarehouseId;
    },

    createPaginationHTML(currentPage, totalPages, fetchMethodName) {
        if (totalPages <= 1) return '';
        let html = '';
        // Previous Button
        html += `<button class="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 disabled:opacity-50" ${currentPage === 1 ? 'disabled' : `onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${currentPage - 1})"`}><svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" /></svg></button>`;
        // Logic render số trang (giữ nguyên)
        let startPage = Math.max(1, currentPage - 2);
        let endPage = Math.min(totalPages, currentPage + 2);
        if (startPage > 1) {
            html += `<button class="px-3 py-1 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600" onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(1)">1</button>`;
            if (startPage > 2) html += `<span class="px-1 text-slate-400">...</span>`;
        }
        for (let i = startPage; i <= endPage; i++) {
            const activeClass = i === currentPage ? 'bg-red-50 text-red-600 font-bold border border-red-200' : 'hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600';
            html += `<button class="px-3 py-1 rounded-md text-sm ${activeClass}" onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${i})">${i}</button>`;
        }
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) html += `<span class="px-1 text-slate-400">...</span>`;
            html += `<button class="px-3 py-1 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600" onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${totalPages})">${totalPages}</button>`;
        }
        // Next Button
        html += `<button class="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 disabled:opacity-50" ${currentPage === totalPages ? 'disabled' : `onclick="this.closest('[x-data]').__x.$data.${fetchMethodName}(${currentPage + 1})"`}><svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg></button>`;
        return html;
    }
};