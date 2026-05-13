import createRequests from '../../shared/requests.js?v=3.1';

export default createRequests({
    buildFetchUrl(app, page) {
        const whId = app.currentWarehouseId || '';
        const branchId = app.currentBranchId || '';
        let url = `/api/inventory/requests?page=${page}&per_page=${app.perPage}`;
        if (whId) url += `&dest_warehouse_id=${whId}`;
        else if (branchId) url += `&branch_id=${branchId}`;
        return url;
    }
});
