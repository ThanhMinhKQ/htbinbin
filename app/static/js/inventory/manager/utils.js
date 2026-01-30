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

        // 1. Show Loading Overlay immediately
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
        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 50)));

        try {
            // Find the actual modal container more intelligently
            let content;

            // 0. Check if the element itself IS the modal container (often the case if passed directly)
            // Look for max-w-* classes which indicate it's the main container
            if (element.classList.contains('max-w-3xl') ||
                element.classList.contains('max-w-4xl') ||
                element.classList.contains('max-w-5xl') ||
                element.classList.contains('max-w-6xl') ||
                element.classList.contains('max-w-7xl') ||
                element.classList.contains('max-w-full') ||
                element.classList.contains('max-w-screen-xl')) {
                content = element;
            }

            // 1. Look for the main modal container by size class
            if (!content) {
                content = element.querySelector('.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full');
            }

            // 2. If not found, try to find it by going up to the fixed container first
            if (!content) {
                const fixedContainer = element.closest('.fixed') || element;
                content = fixedContainer.querySelector('.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full');
            }

            // 3. If still not found, look for bg-white/slate-50 container with flex flex-col (modal structure)
            if (!content) {
                const candidates = element.querySelectorAll('.bg-white, .bg-slate-50, .dark\\:bg-slate-900');
                for (const candidate of candidates) {
                    if (candidate.classList.contains('flex') && candidate.classList.contains('flex-col')) {
                        content = candidate;
                        break;
                    }
                }
            }

            // 4. Fallback to the element itself
            if (!content) {
                content = element.querySelector('.bg-white') || element;
            }

            // --- PREPARE FOR CAPTURE ---

            // 1. Remove transforms to avoid blurring
            const originalTransform = content.style.transform;
            content.style.transform = 'none';
            const hadTransformClass = content.classList.contains('transform');
            if (hadTransformClass) content.classList.remove('transform');

            // 2. Hide control buttons (Close/Capture/Etc)
            const actionButtons = [];

            // Header buttons (usually top right)
            const headerActions = content.querySelectorAll('button');
            headerActions.forEach(btn => {
                // Heuristic: Header buttons usually contain SVGs (icons) and are in the top part
                if (btn.querySelector('svg') && btn.offsetParent !== null) {
                    actionButtons.push({
                        element: btn,
                        originalDisplay: btn.style.display
                    });
                    btn.style.display = 'none';
                }
            });

            // Footer buttons (usually in border-t area)
            const footerButtons = content.querySelectorAll('.border-t button');
            footerButtons.forEach(btn => {
                actionButtons.push({
                    element: btn,
                    originalDisplay: btn.style.display
                });
                btn.style.display = 'none';
            });

            // Save and expand the modal container itself if it has max-height
            const modalOriginalMaxHeight = content.style.maxHeight;
            const modalOriginalHeight = content.style.height;
            const modalOriginalOverflow = content.style.overflow;

            content.style.maxHeight = 'none';
            content.style.height = 'auto';
            content.style.overflow = 'visible';

            // Find all scrollable areas that need to be expanded
            const scrollableAreas = content.querySelectorAll('.overflow-y-auto');
            const savedStyles = [];

            // Save original styles and expand all scrollable areas
            scrollableAreas.forEach((area) => {
                savedStyles.push({
                    element: area,
                    maxHeight: area.style.maxHeight,
                    overflow: area.style.overflow,
                    height: area.style.height
                });

                // Temporarily expand to show all content
                area.style.maxHeight = 'none';
                area.style.overflow = 'visible';
                area.style.height = 'auto';
            });

            // Find and expand all truncated text elements
            const truncatedElements = content.querySelectorAll('.truncate, .overflow-hidden, .text-ellipsis');
            const savedClasses = [];

            truncatedElements.forEach((el) => {
                const classes = {
                    element: el,
                    hadTruncate: el.classList.contains('truncate'),
                    hadOverflowHidden: el.classList.contains('overflow-hidden'),
                    hadTextEllipsis: el.classList.contains('text-ellipsis'),
                    originalWhiteSpace: el.style.whiteSpace,
                    originalOverflow: el.style.overflow,
                    originalTextOverflow: el.style.textOverflow
                };
                savedClasses.push(classes);

                // Remove truncation classes and styles
                el.classList.remove('truncate', 'overflow-hidden', 'text-ellipsis');
                el.style.whiteSpace = 'normal';
                el.style.overflow = 'visible';
                el.style.textOverflow = 'clip';
            });

            // Wait longer for the DOM to fully render layout changes
            await new Promise(resolve => setTimeout(resolve, 500));

            // Calculate dynamic scale - Prioritize quality
            const contentHeight = content.scrollHeight;
            let scale = 2.0;

            // Adjust scale only if image is extremely large to prevent browser crash
            if (contentHeight > 5000) {
                scale = 1.5;
            }
            if (contentHeight > 8000) {
                scale = 1.0;
            }

            // Capture the entire expanded content WITHOUT opacity change
            // Disable transitions and animations to prevent ghosting
            const originalTransition = content.style.transition;
            const originalAnimation = content.style.animation;
            content.style.transition = 'none';
            content.style.animation = 'none';

            const canvas = await html2canvas(content, {
                scale: scale,
                useCORS: true,
                logging: false,
                backgroundColor: '#ffffff',
                windowHeight: content.scrollHeight,
                height: content.scrollHeight,
                scrollY: -window.scrollY,
                scrollX: -window.scrollX,
                onclone: (clonedDoc) => {
                    // Find the cloned content using the same robust selectors
                    const contentSelectors = '.max-w-3xl, .max-w-4xl, .max-w-5xl, .max-w-6xl, .max-w-7xl, .max-w-full, .max-w-screen-xl, .bg-white, .bg-slate-50, .dark\\:bg-slate-900';
                    const clonedContent = clonedDoc.body.querySelector(contentSelectors) || clonedDoc.body.firstChild;

                    if (clonedContent && clonedContent.style) {
                        clonedContent.style.transform = 'none';
                        clonedContent.style.transition = 'none';
                        clonedContent.style.animation = 'none';
                        clonedContent.style.display = 'flex'; // Ensure flex layout is preserved
                        clonedContent.style.maxHeight = 'none';
                        clonedContent.style.height = 'auto';
                        clonedContent.style.overflow = 'visible';

                        // Replace all inputs and textareas with static text for clear capture
                        const inputs = clonedContent.querySelectorAll('input, textarea');
                        inputs.forEach(input => {
                            // skip hidden inputs
                            if (input.type === 'hidden' || input.style.display === 'none') return;

                            const value = input.value;
                            const replacement = clonedDoc.createElement('div');

                            // Copy relevant styles to maintain look
                            const computedStyle = window.getComputedStyle(input);
                            replacement.style.fontSize = computedStyle.fontSize;
                            replacement.style.fontWeight = computedStyle.fontWeight;
                            replacement.style.color = computedStyle.color;
                            replacement.style.padding = computedStyle.padding; // Copy exact padding
                            replacement.style.lineHeight = computedStyle.lineHeight; // Copy exact line-height
                            replacement.style.height = computedStyle.height; // Copy height to fill the box

                            // Use Flexbox for vertical centering, mimicking input behavior
                            replacement.style.display = 'flex';
                            replacement.style.alignItems = 'center';

                            // Map text-align to justify-content
                            const textAlign = computedStyle.textAlign;
                            if (textAlign === 'center') replacement.style.justifyContent = 'center';
                            else if (textAlign === 'right' || textAlign === 'end') replacement.style.justifyContent = 'flex-end';
                            else replacement.style.justifyContent = 'flex-start';

                            // Specific styling for clarity
                            replacement.textContent = value;
                            replacement.style.border = 'none';
                            replacement.style.background = 'transparent';
                            replacement.style.width = '100%';
                            replacement.style.whiteSpace = 'pre'; // Use 'pre' to respect spaces but stay single line if input is single line
                            replacement.style.overflow = 'hidden'; // Clip overflow like valid input

                            if (input.parentNode) {
                                input.parentNode.replaceChild(replacement, input);
                            }
                        });
                    }
                }
            });

            // --- RESTORE ORIGINAL STATE ---

            // Restore transforms and transitions
            content.style.transform = originalTransform;
            content.style.transition = originalTransition;
            content.style.animation = originalAnimation;
            if (hadTransformClass) content.classList.add('transform');

            // Restore buttons
            actionButtons.forEach(btn => {
                btn.element.style.display = btn.originalDisplay;
            });

            // Restore modal container styles
            content.style.maxHeight = modalOriginalMaxHeight;
            content.style.height = modalOriginalHeight;
            content.style.overflow = modalOriginalOverflow;

            // Restore all scrollable area styles
            savedStyles.forEach(({ element, maxHeight, overflow, height }) => {
                element.style.maxHeight = maxHeight;
                element.style.overflow = overflow;
                element.style.height = height;
            });

            // Restore all truncated text classes and styles
            savedClasses.forEach(({ element, hadTruncate, hadOverflowHidden, hadTextEllipsis, originalWhiteSpace, originalOverflow, originalTextOverflow }) => {
                if (hadTruncate) element.classList.add('truncate');
                if (hadOverflowHidden) element.classList.add('overflow-hidden');
                if (hadTextEllipsis) element.classList.add('text-ellipsis');
                element.style.whiteSpace = originalWhiteSpace;
                element.style.overflow = originalOverflow;
                element.style.textOverflow = originalTextOverflow;
            });

            // Copy to clipboard
            canvas.toBlob(async (blob) => {
                try {
                    const item = new ClipboardItem({ 'image/png': blob });
                    await navigator.clipboard.write([item]);
                    alert("Đã chụp toàn bộ phiếu và lưu vào Clipboard!");
                } catch (err) {
                    console.error('Clipboard failed:', err);
                    alert("Không thể lưu vào clipboard. Bạn có thể lưu ảnh thủ công bằng cách chuột phải -> Lưu.");
                }
            });
        } catch (e) {
            console.error(e);
            alert("Lỗi khi chụp màn hình: " + e.message);
        } finally {
            // Remove Loading Overlay
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
