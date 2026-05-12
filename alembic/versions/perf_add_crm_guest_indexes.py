"""perf: add CRM guest indexes for profile and stays queries

Revision ID: perf_add_crm_guest_indexes
Revises:
Create Date: 2026-05-12

Indexes added:
- guest_activities: (guest_id, stay_id) for batch activity load in stays list
- guest_stay_summaries: (guest_id, branch_id) for filtered stays query
- guest_payment_summaries: (guest_id, is_voided) for preferred payment method query
"""
from alembic import op

revision = 'perf_add_crm_guest_indexes'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_guest_activities_guest_stay',
        'guest_activities',
        ['guest_id', 'stay_id'],
    )
    op.create_index(
        'ix_guest_stay_summary_guest_branch',
        'guest_stay_summaries',
        ['guest_id', 'branch_id'],
    )
    op.create_index(
        'ix_guest_payment_summary_guest_voided',
        'guest_payment_summaries',
        ['guest_id', 'is_voided'],
    )


def downgrade():
    op.drop_index('ix_guest_activities_guest_stay', 'guest_activities')
    op.drop_index('ix_guest_stay_summary_guest_branch', 'guest_stay_summaries')
    op.drop_index('ix_guest_payment_summary_guest_voided', 'guest_payment_summaries')
