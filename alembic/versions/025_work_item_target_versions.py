"""Add work_item_target_versions junction table for version targeting.

Revision ID: 025_work_item_target_versions
Revises: 024_deployments
Create Date: 2025-11-28

RAAS-FEAT-099: Work Item Lifecycle & Version Targeting

This migration implements:
- work_item_target_versions junction table linking WorkItem → RequirementVersion
- Enables Work Items to target specific immutable version snapshots
- Supports semantic drift detection ("you're targeting v3, current is v5")
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '025_work_item_target_versions'
down_revision = '024_deployments'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # Create work_item_target_versions junction table
    # Links WorkItem to RequirementVersion (immutable version snapshots)
    # ==========================================================================
    op.create_table(
        'work_item_target_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('work_item_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('requirement_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('requirement_versions.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'),
                  nullable=False),
        sa.UniqueConstraint('work_item_id', 'requirement_version_id',
                            name='uq_work_item_target_version'),
    )


def downgrade() -> None:
    op.drop_table('work_item_target_versions')
