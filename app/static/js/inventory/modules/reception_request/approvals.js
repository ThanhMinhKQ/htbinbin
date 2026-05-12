import createApprovals from '../../shared/approvals.js?v=2.0';

export default createApprovals({
    canFetch(app) {
        return Boolean(app.currentBranchId);
    },
    buildApprovalUrl(app, statusParam, page) {
        return `/api/inventory/requests?source_branch_id=${app.currentBranchId}&status=${statusParam}&page=${page}&per_page=${app.perPage}`;
    },
    refreshApprovalDetail: false
});
