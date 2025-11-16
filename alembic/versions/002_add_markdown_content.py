"""Add markdown content field to requirements.

Revision ID: 002
Revises: 001
Create Date: 2025-01-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add content column to store full markdown representation."""
    op.add_column(
        'requirements',
        sa.Column('content', sa.Text, nullable=True)
    )


def downgrade() -> None:
    """Remove content column."""
    op.drop_column('requirements', 'content')
