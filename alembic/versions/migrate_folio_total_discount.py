"""Migrate total_discount for existing folios

Revision ID: migrate_folio_total_discount
Revises: add_total_discount_to_folios
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'migrate_folio_total_discount'
down_revision: Union[str, None] = 'add_total_discount_to_folios'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Migrate existing folios:
    1. Tính lại total_charge (loại trừ REFUND/REFUND_PAYMENT)
    2. Tính total_discount từ DISCOUNT transactions
    3. Tính total_paid từ PAYMENT + DEPOSIT_USED
    4. Tính balance = (total_charge - total_discount) - total_paid
    """
    conn = op.get_bind()
    
    # 1. Tính và update total_discount cho tất cả folios
    sql_discount = text("""
        UPDATE folios 
        SET total_discount = COALESCE((
            SELECT SUM(ABS(ft.amount))
            FROM folio_transactions ft
            WHERE ft.folio_id = folios.id
              AND ft.is_voided = FALSE
              AND ft.category = 'DISCOUNT'
        ), 0)
    """)
    conn.execute(sql_discount)
    
    # 2. Tính lại total_charge (loại trừ REFUND/REFUND_PAYMENT)
    sql_charge = text("""
        UPDATE folios 
        SET total_charge = COALESCE((
            SELECT SUM(ft.amount)
            FROM folio_transactions ft
            WHERE ft.folio_id = folios.id
              AND ft.is_voided = FALSE
              AND ft.amount > 0
              AND ft.transaction_type NOT IN ('REFUND', 'REFUND_PAYMENT')
        ), 0)
    """)
    conn.execute(sql_charge)
    
    # 3. Tính lại total_paid (PAYMENT + DEPOSIT_USED)
    sql_paid = text("""
        UPDATE folios 
        SET total_paid = COALESCE((
            SELECT SUM(ABS(ft.amount))
            FROM folio_transactions ft
            WHERE ft.folio_id = folios.id
              AND ft.is_voided = FALSE
              AND ft.amount < 0
              AND ft.transaction_type IN ('PAYMENT', 'DEPOSIT_USED')
        ), 0)
    """)
    conn.execute(sql_paid)
    
    # 4. Tính balance = (total_charge - total_discount) - total_paid
    sql_balance = text("""
        UPDATE folios 
        SET balance = (total_charge - total_discount) - total_paid
    """)
    conn.execute(sql_balance)


def downgrade() -> None:
    """Revert: set total_discount về 0"""
    conn = op.get_bind()
    sql = text("UPDATE folios SET total_discount = 0")
    conn.execute(sql)
