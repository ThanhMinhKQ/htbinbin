"""merge multiple heads

Revision ID: cfb2a8b3f522
Revises: add_branch_company_bank, add_export_service_enum_values, add_hourly_to_daily_threshold, migrate_folio_total_discount, perf_add_crm_guest_indexes, pms_shift_integration_v1
Create Date: 2026-05-15 16:25:07.839513

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfb2a8b3f522'
down_revision: Union[str, Sequence[str], None] = ('add_branch_company_bank', 'add_export_service_enum_values', 'add_hourly_to_daily_threshold', 'migrate_folio_total_discount', 'perf_add_crm_guest_indexes', 'pms_shift_integration_v1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
