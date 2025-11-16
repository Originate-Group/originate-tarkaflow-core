"""Add field length constraints to requirements.

Revision ID: 004
Revises: 003
Create Date: 2025-01-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add length constraints to title and description fields."""
    # Change title from VARCHAR(500) to VARCHAR(200)
    op.alter_column(
        'requirements',
        'title',
        type_=sa.String(200),
        existing_type=sa.String(500),
        nullable=False
    )

    # Change description from TEXT to VARCHAR(500)
    op.alter_column(
        'requirements',
        'description',
        type_=sa.String(500),
        existing_type=sa.Text,
        nullable=True
    )


def downgrade() -> None:
    """Remove length constraints from title and description fields."""
    # Restore title to VARCHAR(500)
    op.alter_column(
        'requirements',
        'title',
        type_=sa.String(500),
        existing_type=sa.String(200),
        nullable=False
    )

    # Restore description to TEXT
    op.alter_column(
        'requirements',
        'description',
        type_=sa.Text,
        existing_type=sa.String(500),
        nullable=True
    )
