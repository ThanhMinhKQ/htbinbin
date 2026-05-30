import createRequests from '../shared/requests.js?v=3.2';

export default createRequests({
    buildFetchUrl(app, page) {
        let url = `/api/inventory/requests?page=${page}&per_page=${app.perPage}`;
        if (app.currentWarehouseId) url += `&dest_warehouse_id=${app.currentWarehouseId}`;
        return url;
    },
    emptyCreateSearchResults: true
});
