"""add_guest_documents

Revision ID: 4c3c30f314f2
Revises: 2b7f0b17e1a8
Create Date: 2026-05-26 07:02:47.800271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c3c30f314f2'
down_revision: Union[str, Sequence[str], None] = '2b7f0b17e1a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'guest_documents',
        sa.Column('id', sa.BIGINT(), nullable=False),
        sa.Column('guest_id', sa.BIGINT(), nullable=False),
        sa.Column('doc_type', sa.String(length=20), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('thumbnail_path', sa.Text(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.BIGINT(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['guest_id'], ['guests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guest_documents_guest_id', 'guest_documents', ['guest_id'], unique=False)
    op.create_index('uq_guest_doc_type', 'guest_documents', ['guest_id', 'doc_type'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_guest_doc_type', table_name='guest_documents')
    op.drop_index('ix_guest_documents_guest_id', table_name='guest_documents')
    op.drop_table('guest_documents')
