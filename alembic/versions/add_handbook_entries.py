"""add handbook_entries table

Revision ID: add_handbook_entries
Revises:
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_handbook_entries'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'handbook_entries',
        sa.Column('id', sa.BIGINT(), primary_key=True, autoincrement=True),
        sa.Column('situation', sa.Text(), nullable=False),
        sa.Column('solution', sa.Text(), nullable=False),
        sa.Column('is_approved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by', sa.BIGINT(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
    )
    op.create_index('ix_handbook_entries_is_approved', 'handbook_entries', ['is_approved'])
    op.create_index('ix_handbook_entries_created_by', 'handbook_entries', ['created_by'])


def downgrade():
    op.drop_table('handbook_entries')
