"""Add bidirectional FK between shift_report_transactions and folio_transactions

Revision ID: shift_folio_bidirectional_links
Revises: add_total_discount_to_folios
Create Date: 2026-04-19

- Add folio_transaction_id to shift_report_transactions (link to FolioTransaction)
- Add shift_transaction_id to folio_transactions (reverse link)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'shift_folio_bidirectional_links'
down_revision: Union[str, None] = 'add_total_discount_to_folios'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add folio_transaction_id to shift_report_transactions
    op.add_column(
        'shift_report_transactions',
        sa.Column('folio_transaction_id', sa.BigInteger(),
                  sa.ForeignKey('folio_transactions.id', ondelete='SET NULL'),
                  nullable=True)
    )
    op.create_index(
        'ix_shift_trans_folio_tx_id',
        'shift_report_transactions',
        ['folio_transaction_id']
    )

    # 2. Add shift_transaction_id to folio_transactions
    op.add_column(
        'folio_transactions',
        sa.Column('shift_transaction_id', sa.BigInteger(),
                  sa.ForeignKey('shift_report_transactions.id', ondelete='SET NULL'),
                  nullable=True)
    )
    op.create_index(
        'ix_ft_shift_tx_id',
        'folio_transactions',
        ['shift_transaction_id']
    )


def downgrade() -> None:
    op.drop_index('ix_ft_shift_tx_id', table_name='folio_transactions')
    op.drop_column('folio_transactions', 'shift_transaction_id')

    op.drop_index('ix_shift_trans_folio_tx_id', table_name='shift_report_transactions')
    op.drop_column('shift_report_transactions', 'folio_transaction_id')
