import createRequests from '../shared/requests.js?v=2.0';

export default createRequests({
    buildFetchUrl(app, page) {
        return `/api/inventory/requests?dest_warehouse_id=${app.currentWarehouseId || 0}&page=${page}&per_page=${app.perPage}`;
    },
    emptyCreateSearchResults: true
});
