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
        if (!this.normalizedProducts) return; // Guard clause
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

    viewImage(img) {
        this.viewingImage = img;
    },

    // --- MAIN IMPROVEMENT HERE ---
    async captureModal(element) {
        if (!element) return;

        // 1. Show Loading Overlay
        const loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'fixed inset-0 z-[9999] bg-slate-900/80 backdrop-blur-sm flex flex-col items-center justify-center transition-opacity duration-300';
        loadingOverlay.id = 'capture-loading-overlay';
        loadingOverlay.innerHTML = `
            <div class="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
            <p class="text-white font-bold text-lg animate-pulse">Đang xử lý hình ảnh...</p>
            <p class="text-slate-400 text-sm mt-2">Vui lòng đợi giây lát</p>
        `;
        document.body.appendChild(loadingOverlay);

        // Force a layout paint
        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 100)));

        try {
            // 2. Find Content Smartly
            let content;
            if (element.classList.contains('max-w-3xl') || element.classList.contains('max-w-4xl') || element.classList.contains('max-w-5xl') || element.classList.contains('max-w-6xl') || element.classList.contains('max-w-7xl') || element.classList.contains('max-w-full')) {
                content = element;
            }
            if (!content) content = element.querySelector('.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full');
            if (!content) {
                const fixedContainer = element.closest('.fixed') || element;
                content = fixedContainer.querySelector('.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full');
            }
            if (!content) content = element.querySelector('.bg-white') || element;

            // --- SAVE STATE & PREPARE ---
            const originalStyles = [];
            // Helper to save and apply style
            const modifyStyle = (el, styles) => {
                const originalState = { element: el, styles: {} };
                for (const prop in styles) {
                    originalState.styles[prop] = el.style[prop];
                    el.style[prop] = styles[prop];
                }
                originalStyles.push(originalState);
            };

            // 3. Hide Controls
            const buttons = content.querySelectorAll('button, .close-btn, [role="button"]');
            buttons.forEach(btn => modifyStyle(btn, { display: 'none' }));

            // 4. Setup Container for Capture
            modifyStyle(content, {
                transform: 'none',
                transition: 'none',
                maxHeight: 'none',
                height: 'auto',
                overflow: 'visible',
                boxShadow: 'none',
                borderRadius: '0', // Vuông vức cho đẹp
                margin: '0'
            });

            // 5. "FORCE EXPANSION" STRATEGY (QUAN TRỌNG)
            // Quét TẤT CẢ phần tử để đảm bảo không có text nào bị ẩn
            const allElements = content.querySelectorAll('*');

            allElements.forEach(el => {
                const computed = window.getComputedStyle(el);

                // a. Xử lý Scroll/Overflow (Bung toàn bộ chiều cao)
                if (computed.overflow !== 'visible' || computed.overflowY !== 'visible') {
                    modifyStyle(el, {
                        overflow: 'visible',
                        maxHeight: 'none',
                        height: 'auto'
                    });
                }

                // b. Xử lý Text bị cắt (Truncate/Ellipsis/Line-clamp)
                // Phát hiện mọi kiểu cắt chữ
                if (
                    el.classList.contains('truncate') ||
                    el.classList.contains('line-clamp-1') ||
                    el.classList.contains('line-clamp-2') ||
                    computed.textOverflow === 'ellipsis' ||
                    computed.whiteSpace === 'nowrap'
                ) {
                    modifyStyle(el, {
                        whiteSpace: 'normal',       // Cho phép xuống dòng
                        textOverflow: 'clip',       // Bỏ dấu ...
                        overflow: 'visible',        // Hiển thị phần tràn
                        width: 'auto',              // Tự động giãn chiều rộng
                        maxWidth: 'none',           // Bỏ giới hạn chiều rộng
                        minWidth: '0',              // Fix lỗi flex item không co giãn
                        display: computed.display === 'inline' ? 'inline-block' : computed.display // Đảm bảo box model hoạt động
                    });
                }

                // c. Tinh chỉnh Grid/Flex items
                // Thêm padding nhẹ để tránh html2canvas cắt mất đuôi chữ (g, y, j)
                if (['SPAN', 'P', 'H3', 'H4', 'H5', 'DIV'].includes(el.tagName) && el.innerText.trim().length > 0) {
                    // Chỉ thêm padding nếu không phá vỡ layout quá nhiều
                    if (computed.display !== 'inline') {
                        modifyStyle(el, { paddingBottom: '1px' });
                    }
                }
            });

            // Wait for DOM layout update
            await new Promise(resolve => setTimeout(resolve, 500));

            const scrollHeight = content.scrollHeight;

            // 6. Capture with html2canvas
            const canvas = await html2canvas(content, {
                scale: 2, // Scale 2.0 là đủ nét và nhẹ, tăng lên 3 nếu cần in ấn
                useCORS: true,
                allowTaint: true,
                backgroundColor: '#ffffff',
                height: scrollHeight,
                windowHeight: scrollHeight,
                onclone: (clonedDoc) => {
                    // Logic thay thế Input/Textarea bằng Text tĩnh (Giữ lại từ code cũ của bạn vì nó tốt)
                    const clonedContent = clonedDoc.body.querySelector('.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full') || clonedDoc.body.firstChild;
                    if (clonedContent) {
                        const inputs = clonedContent.querySelectorAll('input, textarea');
                        inputs.forEach(input => {
                            if (input.type === 'hidden' || input.style.display === 'none') return;

                            const value = input.value || input.getAttribute('placeholder') || '';
                            const replacement = clonedDoc.createElement('div');

                            // Copy style cơ bản
                            const s = window.getComputedStyle(input);
                            replacement.textContent = value;
                            replacement.style.cssText = s.cssText;

                            // Override một số style để hiển thị đẹp như text
                            replacement.style.display = 'flex';
                            replacement.style.alignItems = 'center';
                            replacement.style.whiteSpace = 'pre-wrap';
                            replacement.style.overflow = 'visible';
                            replacement.style.height = 'auto';
                            replacement.style.minHeight = s.height;
                            replacement.style.border = 'none';
                            replacement.style.background = 'transparent';
                            replacement.style.padding = '4px 0'; // Clean padding

                            if (input.parentNode) input.parentNode.replaceChild(replacement, input);
                        });
                    }
                }
            });

            // --- RESTORE STATE ---
            // Hoàn trả lại giao diện cũ ngay lập tức
            for (let i = originalStyles.length - 1; i >= 0; i--) {
                const { element, styles } = originalStyles[i];
                for (const prop in styles) {
                    element.style[prop] = styles[prop];
                }
            }

            // 7. Output Result
            canvas.toBlob(async (blob) => {
                try {
                    const item = new ClipboardItem({ 'image/png': blob });
                    await navigator.clipboard.write([item]);
                    alert("Đã chụp toàn bộ phiếu và lưu vào Clipboard! (Ctrl+V để gửi)");
                } catch (err) {
                    console.error('Clipboard failed:', err);
                    // Fallback: Tải file xuống nếu clipboard lỗi
                    const link = document.createElement('a');
                    link.download = `Phieu_${Date.now()}.png`;
                    link.href = canvas.toDataURL();
                    link.click();
                }
            });

        } catch (e) {
            console.error("Capture Error:", e);
            alert("Lỗi khi chụp màn hình: " + e.message);
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

        return {
            start: formatDate(firstDay),
            end: formatDate(lastDay)
        };
    }
};
