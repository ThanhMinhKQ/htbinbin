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

        // 1. Show Loading Overlay immediately explicitly blocking the screen
        const loadingOverlay = document.createElement('div');
        loadingOverlay.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#0f172a;display:flex;flex-direction:column;align-items:center;justify-content:center;transition:opacity 0.3s ease;';
        loadingOverlay.id = 'capture-loading-overlay';
        loadingOverlay.innerHTML = `
            <div style="width:56px;height:56px;border:4px solid rgba(59,130,246,0.3);border-top-color:#3b82f6;border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:16px;"></div>
            <p style="color:#ffffff;font-weight:700;font-size:16px;">Đang xử lý hình ảnh...</p>
            <p style="color:#94a3b8;font-size:13px;margin-top:6px;">Quá trình này có thể mất vài giây</p>
        `;
        document.body.appendChild(loadingOverlay);

        // Force browser to paint overlay
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        await new Promise(resolve => setTimeout(resolve, 50));

        const originalStyles = new Map();
        const temporaryElements = [];

        try {
            // --- STEP 1: Find the target content inside modal ---
            let content =
                element.querySelector('[data-capture-target]') ||
                element.closest('[data-capture-target]') ||
                element.querySelector('.max-w-3xl,.max-w-4xl,.max-w-5xl,.max-w-6xl,.max-w-7xl,.max-w-full[class*="bg-white"]') ||
                element.querySelector('.bg-white') ||
                element;

            const sizeClasses = ['max-w-3xl', 'max-w-4xl', 'max-w-5xl', 'max-w-6xl', 'max-w-7xl', 'max-w-full'];
            if (content === element && !sizeClasses.some(c => element.classList.contains(c))) {
                const child = element.querySelector('.flex.flex-col');
                if (child) content = child;
            }

            const saveStyle = (el, props) => {
                if (!originalStyles.has(el)) originalStyles.set(el, { inline: {}, classes: [] });
                const state = originalStyles.get(el);
                props.forEach(p => { if (!(p in state.inline)) state.inline[p] = el.style[p]; });
            };

            // --- STEP 2: Mutate LIVE DOM temporarily (Hidden behind overlay) ---

            // 2a. Expand scrollable areas explicitly
            content.querySelectorAll('.overflow-y-auto, .overflow-auto, .max-h-[80vh], .max-h-[calc(100vh-10rem)]').forEach(el => {
                saveStyle(el, ['overflow', 'maxHeight', 'height']);
                el.style.overflow = 'visible';
                el.style.maxHeight = 'none';
                el.style.height = 'auto';
            });

            // Expand the main content wrapper
            saveStyle(content, ['maxHeight', 'height', 'overflow', 'transform', 'borderRadius']);
            content.style.maxHeight = 'none';
            content.style.height = 'auto';
            content.style.overflow = 'visible';
            content.style.transform = 'none';
            content.style.borderRadius = '0'; // Flat corners for capture

            // 2b. Hide buttons (footer / headers)
            content.querySelectorAll('button').forEach(btn => {
                const inHeader = btn.closest('div[class*="border-b"]') && btn.querySelector('svg');
                const inFooter = btn.closest('div[class*="border-t"]');
                if (inHeader || inFooter || btn.textContent.toLowerCase().includes('chụp')) {
                    saveStyle(btn, ['display']);
                    btn.style.display = 'none';
                }
            });

            // 2c. Fix sticky headers
            content.querySelectorAll('.sticky').forEach(el => {
                saveStyle(el, ['position', 'top']);
                const state = originalStyles.get(el);
                if (el.classList.contains('sticky')) {
                    state.classes.push('sticky');
                    el.classList.remove('sticky');
                }
                el.style.position = 'relative';
                el.style.top = 'auto';
            });

            // 2d. Prevent Safari & html2canvas bugs with backdrop-blur
            const globalFixStyle = document.createElement('style');
            globalFixStyle.textContent = `
                [data-capture-temp-scope] * { backdrop-filter: none !important; -webkit-backdrop-filter: none !important; animation: none !important; transition: none !important; }
                [data-capture-temp-scope] .backdrop-blur-sm, [data-capture-temp-scope] .backdrop-blur-md, [data-capture-temp-scope] .backdrop-blur { backdrop-filter: none !important; -webkit-backdrop-filter: none !important; }
                [data-capture-temp-scope] .truncate, [data-capture-temp-scope] .text-ellipsis { overflow: visible !important; text-overflow: clip !important; white-space: normal !important; }
            `;
            document.head.appendChild(globalFixStyle);
            content.setAttribute('data-capture-temp-scope', 'true');

            // 2e. Replace inputs/textareas to prevent text clipping
            content.querySelectorAll('input:not([type="hidden"]), textarea, select').forEach(input => {
                const cs = window.getComputedStyle(input);
                if (cs.display === 'none') return;

                const div = document.createElement('div');
                div.style.cssText = `
                    font-size: ${cs.fontSize};
                    font-weight: ${cs.fontWeight};
                    font-family: ${cs.fontFamily};
                    color: ${cs.color};
                    background: ${cs.backgroundColor !== 'rgba(0, 0, 0, 0)' ? cs.backgroundColor : 'transparent'};
                    padding: ${cs.paddingTop} ${cs.paddingRight} ${cs.paddingBottom} ${cs.paddingLeft};
                    border: ${cs.borderWidth} ${cs.borderStyle} ${cs.borderColor !== 'rgba(0, 0, 0, 0)' ? cs.borderColor : 'transparent'};
                    border-radius: ${cs.borderRadius};
                    min-height: ${cs.height !== 'auto' ? cs.height : '38px'};
                    width: ${cs.width !== 'auto' ? cs.width : '100%'};
                    display: flex;
                    align-items: ${input.tagName.toLowerCase() === 'textarea' ? 'flex-start' : 'center'};
                    justify-content: ${cs.textAlign === 'center' ? 'center' : cs.textAlign === 'right' ? 'flex-end' : 'flex-start'};
                    line-height: ${cs.lineHeight !== 'normal' ? cs.lineHeight : '1.5'};
                    white-space: pre-wrap;
                    word-break: break-word;
                    box-sizing: border-box;
                    overflow: visible;
                `;

                if (input.tagName.toLowerCase() === 'select') {
                    const selected = input.options[input.selectedIndex];
                    div.textContent = selected ? selected.text : '';
                } else {
                    div.textContent = input.value || '';
                }

                input.parentNode.insertBefore(div, input);
                saveStyle(input, ['display']);
                input.style.display = 'none';
                temporaryElements.push(div);
            });

            // Let browser paint the expanded layout behind overlay
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

            // STEP 3: CAPTURE
            // Ensure no scroll offset disrupts html2canvas
            const currentScrollX = window.scrollX;
            const currentScrollY = window.scrollY;
            window.scrollTo(0, 0);

            const captureW = content.scrollWidth;
            const captureH = content.scrollHeight;

            const textOverlay = document.querySelector('#capture-loading-overlay p:first-of-type');
            if (textOverlay) textOverlay.textContent = 'Đang trích xuất ảnh siêu nét...';

            await new Promise(resolve => setTimeout(resolve, 50));

            const canvas = await html2canvas(content, {
                scale: window.devicePixelRatio > 1 ? 2 : 2, // High resolution
                useCORS: true,
                allowTaint: true,
                logging: false,
                backgroundColor: '#ffffff',
                width: captureW,
                height: captureH,
                windowWidth: Math.max(captureW, window.innerWidth),
                windowHeight: Math.max(captureH, window.innerHeight),
                x: window.scrollX,
                y: window.scrollY,
                scrollX: 0,
                scrollY: 0
            });

            window.scrollTo(currentScrollX, currentScrollY);

            // STEP 4: RESULT
            const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));

            if (!blob) {
                alert('Lỗi: Trình duyệt không thể tạo ảnh. Vui lòng tải lại trang và thử lại.');
                return;
            }

            try {
                const item = new ClipboardItem({ 'image/png': blob });
                await navigator.clipboard.write([item]);
                alert('Đã chụp siêu nét toàn bộ phiếu và tự động Copy (Lưu vào bộ nhớ tạm)! Bạn có thể dán (Paste) vào bất cứ đâu.');
            } catch (err) {
                console.warn('Clipboard fallback to download:', err);
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `Phieu_${Date.now()}.png`;
                a.click();
                setTimeout(() => URL.revokeObjectURL(url), 5000);
                alert('Đã chụp và tải ảnh xuống thiết bị thành công!');
            }

        } catch (e) {
            console.error('Lỗi captureModal:', e);
            alert('Lỗi khởi tạo chụp phiếu: ' + e.message);
        } finally {
            // STEP 5: RESTORE ALL LIVE DOM MANIPULATIONS smoothly!
            content.removeAttribute('data-capture-temp-scope');
            document.head.querySelectorAll('style').forEach(s => {
                if (s.textContent.includes('data-capture-temp-scope')) {
                    s.parentNode.removeChild(s);
                }
            });

            // Restore all element styles and classes
            originalStyles.forEach((state, el) => {
                Object.entries(state.inline).forEach(([prop, val]) => {
                    el.style[prop] = val;
                });
                state.classes.forEach(cls => {
                    el.classList.add(cls);
                });
            });

            // Remove temporary divs
            temporaryElements.forEach(el => {
                if (el.parentNode) el.parentNode.removeChild(el);
            });

            // Fade out overlay
            const overlay = document.getElementById('capture-loading-overlay');
            if (overlay) {
                overlay.style.opacity = '0';
                setTimeout(() => overlay.parentNode && overlay.parentNode.removeChild(overlay), 300);
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
