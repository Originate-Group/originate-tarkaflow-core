"""Add task routing rules tables.

Revision ID: 021_add_task_routing_rules
Revises: 020_add_task_queue
Create Date: 2025-11-26

RAAS-COMP-067: Task Assignment and Routing
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '021_add_task_routing_rules'
down_revision = '020_add_task_queue'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create routing rule scope enum
    routingrulescope = postgresql.ENUM(
        'organization',
        'project',
        name='routingrulescope',
        create_type=True
    )
    routingrulescope.create(op.get_bind())

    # Create routing rule match type enum
    routingrulematchtype = postgresql.ENUM(
        'task_type',           # Match by task type (review, approval, etc.)
        'source_type',         # Match by source type (requirement_review, etc.)
        'priority',            # Match by priority level
        'requirement_type',    # Match by requirement type (epic, feature, etc.)
        'tag',                 # Match by tag on source artifact
        name='routingrulematchtype',
        create_type=True
    )
    routingrulematchtype.create(op.get_bind())

    # Create task routing rules table
    op.create_table(
        'task_routing_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=True, index=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),

        # Rule matching criteria
        sa.Column('scope', routingrulescope, nullable=False, default='organization'),
        sa.Column('match_type', routingrulematchtype, nullable=False),
        sa.Column('match_value', sa.String(100), nullable=False),
        # Match value examples:
        # - task_type: "review", "approval", "clarification"
        # - source_type: "requirement_review", "approval_request"
        # - priority: "critical", "high"
        # - requirement_type: "epic", "feature"
        # - tag: "security", "compliance"

        # Assignment configuration
        sa.Column('assignee_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('assignee_role', sa.String(50), nullable=True),
        # assignee_role: "product_owner", "scrum_master", "developer", etc.
        # Used with artifact ownership to find the right person

        sa.Column('fallback_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),

        # Rule priority (lower = higher priority, matched first)
        sa.Column('priority', sa.Integer, nullable=False, default=100),

        # Status
        sa.Column('is_active', sa.Boolean, nullable=False, default=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # Create index for efficient rule lookup
    op.create_index(
        'ix_task_routing_rules_lookup',
        'task_routing_rules',
        ['organization_id', 'is_active', 'match_type', 'priority']
    )

    # Create index for project-scoped rules
    op.create_index(
        'ix_task_routing_rules_project_lookup',
        'task_routing_rules',
        ['project_id', 'is_active', 'match_type', 'priority']
    )

    # Create task delegation table for tracking delegations
    op.create_table(
        'task_delegations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tasks.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('delegated_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('delegated_to', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('original_assignee', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reason', sa.Text, nullable=True),
        sa.Column('delegated_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
    )

    # Create escalation tracking table
    op.create_table(
        'task_escalations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tasks.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('escalated_from', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('escalated_to', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('reason', sa.String(50), nullable=False),
        # reason: "unassigned", "overdue", "unresponsive", "manual"
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('escalated_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('escalated_by_system', sa.Boolean, nullable=False, default=False),
    )


def downgrade() -> None:
    # Drop tables
    op.drop_table('task_escalations')
    op.drop_table('task_delegations')
    op.drop_index('ix_task_routing_rules_project_lookup', table_name='task_routing_rules')
    op.drop_index('ix_task_routing_rules_lookup', table_name='task_routing_rules')
    op.drop_table('task_routing_rules')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS routingrulematchtype')
    op.execute('DROP TYPE IF EXISTS routingrulescope')
