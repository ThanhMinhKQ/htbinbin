import createRequests from '../../shared/requests.js?v=3.0';

export default createRequests({
    buildFetchUrl(app, page) {
        return `/api/inventory/requests?branch_id=${app.currentBranchId || 0}&page=${page}&per_page=${app.perPage}`;
    }
});
