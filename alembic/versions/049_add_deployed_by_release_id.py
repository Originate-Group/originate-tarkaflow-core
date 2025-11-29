"""Add deployed_by_release_id column to requirements table.

Revision ID: 049_add_deployed_by_release_id
Revises: 048_fix_work_item_hrid_trigger
Create Date: 2025-11-29

TARKA-FEAT-106: Status Tag Injection - Release Tracking

This migration adds the deployed_by_release_id column to track which Release
deployed each requirement. This enables status tags to show "deployed-REL-XXX"
instead of just "deployed-v{N}", providing full traceability from requirements
back to the Release that deployed them.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '049_add_deployed_by_release_id'
down_revision = '048_fix_work_item_hrid_trigger'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # Add deployed_by_release_id column to requirements table
    # ==========================================================================
    op.add_column(
        'requirements',
        sa.Column(
            'deployed_by_release_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('work_items.id', ondelete='SET NULL'),
            nullable=True,
            index=True,
            comment='TARKA-FEAT-106: UUID of the Release work item that deployed this version'
        )
    )

    # Create index for efficient lookups
    op.create_index(
        'ix_requirements_deployed_by_release_id',
        'requirements',
        ['deployed_by_release_id']
    )


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_requirements_deployed_by_release_id', table_name='requirements')

    # Drop column
    op.drop_column('requirements', 'deployed_by_release_id')
