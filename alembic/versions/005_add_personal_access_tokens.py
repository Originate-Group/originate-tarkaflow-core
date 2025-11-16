"""add personal access tokens

Revision ID: 005
Revises: 004
Create Date: 2025-01-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create personal_access_tokens table for MCP/API authentication."""
    op.create_table(
        'personal_access_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('scopes', sa.ARRAY(sa.String), server_default='{}'),
        sa.Column('last_used_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('revoked_at', sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    """Drop personal_access_tokens table."""
    op.drop_table('personal_access_tokens')
