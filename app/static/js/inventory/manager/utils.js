import sharedUtils from '../shared/utils.js?v=3.4-pagination';

export default {
    ...sharedUtils,

    getCurrentWarehouseId() {
        return this.currentWarehouseId;
    },

    createPaginationHTML(currentPage, totalPages, fetchMethodName) {
        if (totalPages <= 1) return '';

        const dispatch = `Alpine.$data(this.closest('#inventory-page [x-data*=&quot;InventoryRequestAppFactory&quot;]') || this.closest('[x-data]')).${fetchMethodName}`;
        let html = '';

        // Previous Button
        html += `<button class="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 disabled:opacity-50"
            ${currentPage === 1 ? 'disabled' : `onclick="${dispatch}(${currentPage - 1})"`}>
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
            </svg>
        </button>`;

        // Page Numbers
        let startPage = Math.max(1, currentPage - 2);
        let endPage = Math.min(totalPages, currentPage + 2);

        if (startPage > 1) {
            html += `<button class="px-3 py-1 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600"
                onclick="${dispatch}(1)">1</button>`;
            if (startPage > 2) {
                html += `<span class="px-1 text-slate-400">...</span>`;
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            const activeClass = i === currentPage
                ? 'bg-red-50 text-red-600 font-bold border border-red-200'
                : 'hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600';

            html += `<button class="px-3 py-1 rounded-md text-sm ${activeClass}"
                onclick="${dispatch}(${i})">${i}</button>`;
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                html += `<span class="px-1 text-slate-400">...</span>`;
            }
            html += `<button class="px-3 py-1 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600"
                onclick="${dispatch}(${totalPages})">${totalPages}</button>`;
        }

        // Next Button
        html += `<button class="p-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500 disabled:opacity-50"
            ${currentPage === totalPages ? 'disabled' : `onclick="${dispatch}(${currentPage + 1})"`}>
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
        </button>`;

        return html;
    }
};
