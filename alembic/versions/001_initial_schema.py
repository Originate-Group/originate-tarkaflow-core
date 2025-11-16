"""Initial schema with requirements and history tables.

Revision ID: 001
Revises:
Create Date: 2025-01-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create requirements table (enums will be created automatically)
    op.create_table(
        'requirements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('type', sa.Enum('epic', 'component', 'feature', 'requirement', name='requirementtype'), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('requirements.id', ondelete='CASCADE')),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('status', sa.Enum('draft', 'review', 'approved', 'in_progress', 'implemented', 'validated', 'deployed', name='lifecyclestatus'), nullable=False, server_default='draft'),
        sa.Column('tags', postgresql.ARRAY(sa.String), server_default='{}'),
        sa.Column('priority', sa.Integer, server_default='0'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('created_by', sa.String(255)),
        sa.Column('updated_by', sa.String(255)),
        sa.CheckConstraint(
            "(type = 'epic' AND parent_id IS NULL) OR (type != 'epic' AND parent_id IS NOT NULL)",
            name='valid_parent'
        )
    )

    # Create indexes
    op.create_index('idx_requirements_type', 'requirements', ['type'])
    op.create_index('idx_requirements_parent', 'requirements', ['parent_id'])
    op.create_index('idx_requirements_status', 'requirements', ['status'])
    op.create_index('idx_requirements_created_at', 'requirements', ['created_at'], postgresql_ops={'created_at': 'DESC'})

    # Create requirement_history table
    op.create_table(
        'requirement_history',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('requirement_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('requirements.id', ondelete='CASCADE'), nullable=False),
        sa.Column('change_type', sa.Enum('created', 'updated', 'deleted', 'status_changed', name='changetype'), nullable=False),
        sa.Column('field_name', sa.String(100)),
        sa.Column('old_value', sa.Text),
        sa.Column('new_value', sa.Text),
        sa.Column('changed_by', sa.String(255)),
        sa.Column('changed_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('change_reason', sa.Text),
    )

    # Create indexes for history
    op.create_index('idx_history_requirement', 'requirement_history', ['requirement_id'])
    op.create_index('idx_history_changed_at', 'requirement_history', ['changed_at'], postgresql_ops={'changed_at': 'DESC'})


def downgrade() -> None:
    # Drop tables
    op.drop_table('requirement_history')
    op.drop_table('requirements')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS changetype')
    op.execute('DROP TYPE IF EXISTS lifecyclestatus')
    op.execute('DROP TYPE IF EXISTS requirementtype')
