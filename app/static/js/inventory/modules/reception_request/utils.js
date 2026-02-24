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

        // 1. Hiển thị Loading Overlay
        const loadingId = 'capture-loading-overlay';
        if (!document.getElementById(loadingId)) {
            const overlay = document.createElement('div');
            overlay.id = loadingId;
            overlay.className = 'fixed inset-0 z-[9999] bg-slate-900/80 backdrop-blur-sm flex flex-col items-center justify-center transition-opacity duration-300';
            overlay.innerHTML = `
                <div class="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                <p class="text-white font-bold text-lg animate-pulse">Đang xử lý hình ảnh...</p>
                <p class="text-slate-400 text-sm mt-2">Đang đồng bộ màu sắc và layout...</p>
            `;
            document.body.appendChild(overlay);
        }

        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 50)));

        try {
            let content = element.classList.contains('max-w-5xl') ? element :
                element.closest('.max-w-5xl, .max-w-full') ||
                element.querySelector('.max-w-5xl, .max-w-full') ||
                element.querySelector('.bg-white, .dark\\:bg-slate-800') ||
                element;

            // Kiểm tra xem website đang ở chế độ sáng hay tối
            const isDarkMode = document.documentElement.classList.contains('dark') ||
                document.body.classList.contains('dark') ||
                (content.closest('.dark') !== null);

            // Chọn màu nền gốc dựa trên Mode
            const baseBgColor = isDarkMode ? '#1e293b' : '#ffffff';

            // Đồng bộ dữ liệu Input
            const inputs = content.querySelectorAll('input, textarea');
            inputs.forEach(input => {
                if (input.type !== 'radio' && input.type !== 'checkbox') {
                    input.setAttribute('value', input.value);
                }
                if (input.tagName === 'TEXTAREA') {
                    input.innerHTML = input.value;
                }
            });

            // --- ĐIỂM CHỐT 2: CSS INJECTION ĐÃ ĐƯỢC NÂNG CẤP ---
            const styleId = 'capture-temp-style';
            let styleEl = document.getElementById(styleId);
            if (!styleEl) {
                styleEl = document.createElement('style');
                styleEl.id = styleId;
                document.head.appendChild(styleEl);
            }

            styleEl.innerHTML = `
                /* Giữ nguyên độ rộng tự nhiên để capture chuẩn Form Desktop */
                .capture-mode-active {
                    position: relative !important;
                    transform: none !important;
                    max-height: none !important;
                    height: auto !important;
                    min-width: 1024px !important;
                    width: max-content !important;
                    max-width: none !important;
                    overflow: visible !important;
                    background-color: ${baseBgColor} !important;
                    margin: 0 auto !important;
                    padding: 24px !important;
                    border-radius: 0 !important;
                    box-shadow: none !important;
                    border: none !important;
                    box-sizing: border-box !important;
                }

                /* Ẩn thanh cuộn để ảnh không bị dính scrollbar */
                .capture-mode-active::-webkit-scrollbar,
                .capture-mode-active *::-webkit-scrollbar {
                    display: none !important;
                }

                /* TẮT CÁC HIỆU ỨNG GÂY XUYÊN THẤU RENDER CANVAS (GÂY LỖI CARO TRONG SUỐT) */
                .capture-mode-active * {
                    overflow: visible !important;
                    max-height: none !important;
                    backdrop-filter: none !important;
                    -webkit-backdrop-filter: none !important;
                    /* BẮT BUỘC bỏ box-shadow, vì khi vẽ bóng lên canvas, vùng bóng bị biến thành trong suốt (caro) */
                    box-shadow: none !important;
                }

                /* Ẩn triệt để các cục màu Blur (Decoration blobs) và thành phần overlay */
                .capture-mode-active [class*="absolute"][class*="blur"],
                .capture-mode-active [class*="absolute"][class*="-z-"],
                .capture-mode-active .fixed.inset-0:not([class*="bg-"]) {
                    display: none !important;
                    opacity: 0 !important;
                }

                /* Ẩn các Nút bấm tiện ích (Đóng, Chụp) nằm ở góc phải Header */
                .capture-mode-active > .rounded-t-2xl .flex.items-center.gap-2 > button {
                    display: none !important;
                }

                /* Ẩn Footer thao tác của Phiếu (Các nút Đóng / Duyệt ở đáy màn hình) */
                .capture-mode-active > .rounded-b-2xl {
                    display: none !important;
                    height: 0 !important;
                    overflow: hidden !important;
                    padding: 0 !important;
                    border: none !important;
                    margin: 0 !important;
                }

                .capture-mode-active .truncate,
                .capture-mode-active .text-ellipsis {
                    white-space: normal !important;
                    text-overflow: clip !important;
                }

                .capture-mode-active {
                    height: max-content !important;
                    min-height: 100% !important;
                }

                /* Tối ưu render Text cho ảnh được Mượt và Nét */
                .capture-mode-active {
                    -webkit-font-smoothing: antialiased !important;
                    -moz-osx-font-smoothing: grayscale !important;
                    text-rendering: optimizeLegibility !important;
                }

                /* Ép lại màu nền Solid để chống trong suốt (Vấn đề khiến html2canvas bị tối đen nền) */
                ${isDarkMode ? `
                    .capture-mode-active .bg-slate-50\\/50,
                    .capture-mode-active .bg-slate-50\\/95,
                    .capture-mode-active .bg-slate-900\\/50,
                    .capture-mode-active .bg-white\\/5 { background-color: #1e293b !important; }
                    .capture-mode-active .bg-green-50\\/30,
                    .capture-mode-active .bg-green-900\\/10,
                    .capture-mode-active .bg-green-500\\/10 { background-color: rgba(20, 83, 45, 0.8) !important; }
                    .capture-mode-active .bg-red-50\\/30,
                    .capture-mode-active .bg-red-900\\/10,
                    .capture-mode-active .bg-red-500\\/10 { background-color: rgba(127, 29, 29, 0.8) !important; }
                    .capture-mode-active .bg-blue-500\\/10 { background-color: rgba(30, 58, 138, 0.8) !important; }
                    .capture-mode-active .text-slate-800,
                    .capture-mode-active .text-slate-700 { color: #f8fafc !important; }
                ` : `
                    .capture-mode-active .bg-slate-50\\/50,
                    .capture-mode-active .bg-slate-50\\/95,
                    .capture-mode-active .bg-slate-900\\/50,
                    .capture-mode-active .bg-white\\/50,
                    .capture-mode-active .bg-white\\/80 { background-color: #f8fafc !important; }
                    .capture-mode-active .bg-green-50\\/30,
                    .capture-mode-active .bg-green-900\\/10,
                    .capture-mode-active .bg-green-500\\/10 { background-color: #f0fdf4 !important; }
                    .capture-mode-active .bg-red-50\\/30,
                    .capture-mode-active .bg-red-900\\/10,
                    .capture-mode-active .bg-red-500\\/10 { background-color: #fef2f2 !important; }
                    .capture-mode-active .bg-blue-500\\/10 { background-color: #eff6ff !important; }
                    /* Ép các thẻ có nền trắng mờ thành trắng đặc, tuyệt đối không dùng box-shadow */
                    .capture-mode-active .bg-white { background-color: #ffffff !important; }
                `}
            `;

            content.classList.add('capture-mode-active');

            // Đợi lâu hơn một chút để trình duyệt xóa hẳn các element bị ẩn (500ms)
            await new Promise(resolve => setTimeout(resolve, 500));

            const scale = Math.min(window.devicePixelRatio || 2, 2);

            const canvas = await html2canvas(content, {
                scale: scale,
                useCORS: true,
                logging: false,
                backgroundColor: baseBgColor,
                windowWidth: content.scrollWidth,
                windowHeight: content.scrollHeight
            });

            // Dọn dẹp
            content.classList.remove('capture-mode-active');

            // Chép vào Clipboard
            canvas.toBlob(async (blob) => {
                try {
                    const item = new ClipboardItem({ 'image/png': blob });
                    await navigator.clipboard.write([item]);
                    alert("Đã chụp phiếu thành công và lưu vào Clipboard!");
                } catch (err) {
                    console.error('Lỗi lưu clipboard:', err);
                    alert("Không thể tự động lưu vào clipboard do trình duyệt chặn.");
                }
            }, 'image/png', 1.0);

        } catch (e) {
            console.error(e);
            alert("Lỗi khi chụp màn hình: " + e.message);
        } finally {
            const overlay = document.getElementById('capture-loading-overlay');
            if (overlay) {
                overlay.classList.add('opacity-0');
                setTimeout(() => {
                    if (overlay && overlay.parentNode) {
                        overlay.parentNode.removeChild(overlay);
                    }
                }, 300);
            }
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
            return `${y} -${m} -${d} `;
        };

        return {
            start: formatDate(firstDay),
            end: formatDate(lastDay)
        };
    }
};
