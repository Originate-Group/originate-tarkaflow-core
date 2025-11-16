"""Add Projects layer to requirements hierarchy.

Revision ID: 006
Revises: 005
Create Date: 2025-01-15

This migration adds:
- projects table (scope boundaries for requirements)
- project_members table (project-level access control)
- project_id to requirements table
- project_visibility and project_status enums
- project_role enum for project_members
- human-readable ID support (project slug in requirement IDs)
- default project for existing organizations

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Projects layer to requirements hierarchy."""

    # 1. Create enums (only if they don't already exist)
    conn = op.get_bind()

    # Check and create project_visibility enum
    result = conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'project_visibility'"))
    if not result.scalar():
        op.execute("CREATE TYPE project_visibility AS ENUM ('public', 'private')")

    # Check and create project_status enum
    result = conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'project_status'"))
    if not result.scalar():
        op.execute("CREATE TYPE project_status AS ENUM ('active', 'archived', 'planning', 'on_hold')")

    # Check and create project_role enum
    result = conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'project_role'"))
    if not result.scalar():
        op.execute("CREATE TYPE project_role AS ENUM ('admin', 'editor', 'viewer')")

    # 2. Create projects table (if it doesn't exist)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'projects' not in inspector.get_table_names():
        # Create ENUM types that reference the already-created types
        project_visibility_enum = postgresql.ENUM('public', 'private', name='project_visibility', create_type=False)
        project_status_enum = postgresql.ENUM('active', 'archived', 'planning', 'on_hold', name='project_status', create_type=False)

        op.create_table(
            'projects',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('slug', sa.String(4), nullable=False),  # 3-4 uppercase alphanumeric chars
            sa.Column('description', sa.Text),
            sa.Column('visibility', project_visibility_enum, nullable=False, server_default='public'),
            sa.Column('status', project_status_enum, nullable=False, server_default='active'),
            sa.Column('value_statement', sa.Text),
            sa.Column('project_type', sa.String(100)),
            sa.Column('tags', postgresql.ARRAY(sa.String), server_default='{}'),
            sa.Column('settings', postgresql.JSONB, server_default='{}'),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
            sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
            sa.Column('updated_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
            sa.CheckConstraint("slug ~ '^[A-Z0-9]{3,4}$'", name='valid_project_slug'),
            sa.UniqueConstraint('organization_id', 'slug', name='unique_org_project_slug')
        )
        op.create_index('idx_projects_organization', 'projects', ['organization_id'])
        op.create_index('idx_projects_slug', 'projects', ['slug'])
        op.create_index('idx_projects_status', 'projects', ['status'])
        op.create_index('idx_projects_created_by_user', 'projects', ['created_by_user_id'])
        op.create_index('idx_projects_updated_by_user', 'projects', ['updated_by_user_id'])

    # 3. Create project_members table (if it doesn't exist)
    if 'project_members' not in inspector.get_table_names():
        # Create ENUM type that references the already-created type
        project_role_enum = postgresql.ENUM('admin', 'editor', 'viewer', name='project_role', create_type=False)

        op.create_table(
            'project_members',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('role', project_role_enum, nullable=False, server_default='editor'),
            sa.Column('joined_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
            sa.UniqueConstraint('project_id', 'user_id', name='unique_project_user')
        )
        op.create_index('idx_project_members_project', 'project_members', ['project_id'])
        op.create_index('idx_project_members_user', 'project_members', ['user_id'])
        op.create_index('idx_project_members_role', 'project_members', ['role'])

    # 4. Create default projects for each existing organization (only if projects table was just created)
    # Get all organizations and create a default project for each (skip if projects already exist)
    result = conn.execute(sa.text("SELECT COUNT(*) FROM projects"))
    project_count = result.scalar()
    if project_count == 0:
        op.execute("""
            INSERT INTO projects (organization_id, name, slug, description, visibility, status, created_at, updated_at)
            SELECT
                o.id,
                o.name || ' Requirements',
                'RAAS',  -- Default slug for migration
                'Default project for ' || o.name || ' (created during migration to Projects layer)',
                'public',
                'active',
                NOW(),
                NOW()
            FROM organizations o
            WHERE NOT EXISTS (
                SELECT 1 FROM projects p WHERE p.organization_id = o.id AND p.slug = 'RAAS'
            )
        """)

    # 5. Add project_id column to requirements table (if it doesn't exist)
    requirements_columns = [col['name'] for col in inspector.get_columns('requirements')]
    if 'project_id' not in requirements_columns:
        op.add_column('requirements', sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True))

    # 6. Migrate existing epics to their organization's default project
    # Also cascade project_id to all descendants
    op.execute("""
        WITH org_projects AS (
            SELECT o.id as org_id, p.id as project_id
            FROM organizations o
            JOIN projects p ON p.organization_id = o.id AND p.slug = 'RAAS'
        )
        UPDATE requirements r
        SET project_id = op.project_id
        FROM org_projects op
        WHERE r.organization_id = op.org_id AND r.type = 'epic'
    """)

    # Propagate project_id down to all descendants (components, features, requirements)
    # This is a recursive update - we do it iteratively to handle all levels
    op.execute("""
        WITH RECURSIVE requirement_tree AS (
            -- Base case: epics with project_id set
            SELECT id, project_id, organization_id
            FROM requirements
            WHERE type = 'epic' AND project_id IS NOT NULL

            UNION ALL

            -- Recursive case: children inherit project_id from parent
            SELECT r.id, rt.project_id, r.organization_id
            FROM requirements r
            JOIN requirement_tree rt ON r.parent_id = rt.id
        )
        UPDATE requirements r
        SET project_id = rt.project_id
        FROM requirement_tree rt
        WHERE r.id = rt.id AND r.project_id IS NULL
    """)

    # 7. Make project_id NOT NULL and add foreign key (if not already done)
    if 'project_id' in requirements_columns:
        # Check if column is already NOT NULL
        project_id_col = [col for col in inspector.get_columns('requirements') if col['name'] == 'project_id'][0]
        if project_id_col.get('nullable', True):
            op.alter_column('requirements', 'project_id', nullable=False)

        # Check if foreign key already exists
        fks = inspector.get_foreign_keys('requirements')
        fk_exists = any(fk.get('name') == 'fk_requirements_project' for fk in fks)
        if not fk_exists:
            op.create_foreign_key(
                'fk_requirements_project',
                'requirements', 'projects',
                ['project_id'], ['id'],
                ondelete='CASCADE'
            )

        # Check if index already exists
        indexes = inspector.get_indexes('requirements')
        idx_exists = any(idx.get('name') == 'idx_requirements_project' for idx in indexes)
        if not idx_exists:
            op.create_index('idx_requirements_project', 'requirements', ['project_id'])

    # 8. Update the valid_parent constraint to include project_id consistency
    # Check if old constraint exists before dropping
    constraints = inspector.get_check_constraints('requirements')
    old_constraint_exists = any(c.get('name') == 'valid_parent' for c in constraints)
    new_constraint_exists = any(c.get('name') == 'valid_parent_and_project' for c in constraints)

    if old_constraint_exists:
        op.drop_constraint('valid_parent', 'requirements', type_='check')

    if not new_constraint_exists:
        # Add new constraint that ensures:
        # - Epics have no parent
        # - Non-epics have a parent
        # - All requirements belong to a project
        op.create_check_constraint(
            'valid_parent_and_project',
            'requirements',
            """
            (type = 'epic' AND parent_id IS NULL AND project_id IS NOT NULL) OR
            (type != 'epic' AND parent_id IS NOT NULL AND project_id IS NOT NULL)
            """
        )


def downgrade() -> None:
    """Remove Projects layer from requirements hierarchy."""

    # Drop constraint
    op.drop_constraint('valid_parent_and_project', 'requirements', type_='check')

    # Restore old constraint
    op.create_check_constraint(
        'valid_parent',
        'requirements',
        """
        (type = 'epic' AND parent_id IS NULL) OR
        (type != 'epic' AND parent_id IS NOT NULL)
        """
    )

    # Drop index and foreign key from requirements
    op.drop_index('idx_requirements_project')
    op.drop_constraint('fk_requirements_project', 'requirements')
    op.drop_column('requirements', 'project_id')

    # Drop project_members table
    op.drop_index('idx_project_members_role')
    op.drop_index('idx_project_members_user')
    op.drop_index('idx_project_members_project')
    op.drop_table('project_members')

    # Drop projects table
    op.drop_index('idx_projects_updated_by_user')
    op.drop_index('idx_projects_created_by_user')
    op.drop_index('idx_projects_status')
    op.drop_index('idx_projects_slug')
    op.drop_index('idx_projects_organization')
    op.drop_table('projects')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS project_role')
    op.execute('DROP TYPE IF EXISTS project_status')
    op.execute('DROP TYPE IF EXISTS project_visibility')
