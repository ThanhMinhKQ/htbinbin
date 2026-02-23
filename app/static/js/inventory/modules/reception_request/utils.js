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

        // 1. Hiển thị Loading Overlay ngay lập tức
        const loadingId = 'capture-loading-overlay';
        if (!document.getElementById(loadingId)) {
            const overlay = document.createElement('div');
            overlay.id = loadingId;
            overlay.className = 'fixed inset-0 z-[9999] bg-slate-900/80 backdrop-blur-sm flex flex-col items-center justify-center transition-opacity duration-300';
            overlay.innerHTML = `
                <div class="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                <p class="text-white font-bold text-lg animate-pulse">Đang xử lý hình ảnh...</p>
                <p class="text-slate-400 text-sm mt-2">Vui lòng đợi giây lát</p>
            `;
            document.body.appendChild(overlay);
        }

        // Nhường 1 frame cho trình duyệt render UI loading
        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 50)));

        try {
            // 2. Tìm container chính xác, nhanh gọn hơn
            let content = element.classList.contains('max-w-5xl') ? element :
                element.closest('.max-w-5xl, .max-w-full') ||
                element.querySelector('.max-w-5xl, .max-w-full') ||
                element.querySelector('.bg-white') ||
                element;

            // 3. Xử lý Input thần tốc: Đồng bộ giá trị (value property) vào thuộc tính (attribute)
            // Để html2canvas tự động đọc được chữ trong input mà không cần thay bằng <div>
            const inputs = content.querySelectorAll('input, textarea');
            inputs.forEach(input => {
                if (input.type !== 'radio' && input.type !== 'checkbox') {
                    input.setAttribute('value', input.value);
                }
                if (input.tagName === 'TEXTAREA') {
                    input.innerHTML = input.value;
                }
            });

            // 4. Bơm CSS cục bộ dùng 1 lần (Giải pháp chống Lag triệt để)
            // Thay vì dùng JS lặp qua hàng trăm thẻ để đổi style, ta áp 1 class lên cha là xong.
            const styleId = 'capture-temp-style';
            let styleEl = document.getElementById(styleId);
            if (!styleEl) {
                styleEl = document.createElement('style');
                styleEl.id = styleId;
                styleEl.innerHTML = `
                    .capture-mode-active {
                        max-height: none !important;
                        height: auto !important;
                        overflow: visible !important;
                        transform: none !important;
                        box-shadow: none !important;
                    }
                    .capture-mode-active .overflow-y-auto,
                    .capture-mode-active .overflow-hidden {
                        max-height: none !important;
                        overflow: visible !important;
                        height: auto !important;
                    }
                    .capture-mode-active .truncate,
                    .capture-mode-active .text-ellipsis {
                        white-space: normal !important;
                        overflow: visible !important;
                        text-overflow: clip !important;
                    }
                    /* Tự động ẩn toàn bộ nút bấm khỏi ảnh chụp */
                    .capture-mode-active button {
                        display: none !important;
                    }
                `;
                document.head.appendChild(styleEl);
            }

            // Kích hoạt chế độ mở rộng UI để chụp
            content.classList.add('capture-mode-active');

            // Đợi 150ms để trình duyệt áp dụng xong CSS và Reflow lại khung hình
            await new Promise(resolve => setTimeout(resolve, 150));

            // 5. CHỐNG LỖI ẢNH TRẮNG BẰNG CÁCH GIỚI HẠN SCALE
            // Scale 2 là mức hoàn hảo (tương đương chuẩn Retina), nét căng nhưng không làm crash trình duyệt
            const scale = Math.min(window.devicePixelRatio || 2, 2);

            // 6. Gọi html2canvas với cấu hình tinh gọn
            const canvas = await html2canvas(content, {
                scale: scale,
                useCORS: true,
                logging: false, // Tắt log để tăng tốc độ thực thi
                backgroundColor: '#ffffff',
                windowWidth: content.scrollWidth,
                windowHeight: content.scrollHeight,
            });

            // 7. Dọn dẹp UI ngay lập tức để người dùng không thấy sự thay đổi
            content.classList.remove('capture-mode-active');

            // 8. Chép vào Clipboard
            canvas.toBlob(async (blob) => {
                try {
                    const item = new ClipboardItem({ 'image/png': blob });
                    await navigator.clipboard.write([item]);
                    alert("Đã chụp toàn bộ phiếu và lưu vào Clipboard!");
                } catch (err) {
                    console.error('Lỗi lưu clipboard:', err);
                    alert("Không thể lưu tự động vào clipboard. Có thể do cài đặt bảo mật của trình duyệt.");
                }
            }, 'image/png', 1.0);

        } catch (e) {
            console.error(e);
            alert("Lỗi khi chụp màn hình: " + e.message);
        } finally {
            // Tắt Loading
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
            return `${y}-${m}-${d}`;
        };

        return {
            start: formatDate(firstDay),
            end: formatDate(lastDay)
        };
    }
};
