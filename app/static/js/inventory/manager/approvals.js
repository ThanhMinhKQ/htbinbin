import createApprovals from '../shared/approvals.js?v=3.3';

export default createApprovals({
    canFetch(app) {
        return Boolean(app.currentWarehouseId);
    },
    buildApprovalUrl(app, statusParam, page) {
        return `/api/inventory/requests?source_warehouse_id=${app.currentWarehouseId}&status=${statusParam}&page=${page}&per_page=${app.perPage}`;
    },
    refreshApprovalDetail: true
});
