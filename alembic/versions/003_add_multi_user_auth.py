"""Add multi-user authentication and organization support.

Revision ID: 003
Revises: 002
Create Date: 2025-01-12

This migration adds:
- organizations table (workspaces/teams)
- users table (authentication)
- organization_members table (membership with roles)
- organization_id to requirements and requirement_history
- user foreign keys to replace string fields

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default IDs for migration
DEFAULT_ORG_ID = uuid.uuid4()
SYSTEM_USER_ID = uuid.uuid4()


def upgrade() -> None:
    """Add multi-user authentication tables and relationships."""

    # 1. Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('settings', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("slug ~ '^[a-z0-9-]+$'", name='valid_slug')
    )
    op.create_index('idx_organizations_slug', 'organizations', ['slug'], unique=True)

    # 2. Create users table (Keycloak integration - no password storage)
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('external_id', sa.String(255), nullable=False, unique=True),  # Keycloak 'sub' claim
        sa.Column('auth_provider', sa.String(50), nullable=False, server_default='keycloak'),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('full_name', sa.String(255)),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('is_superuser', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()'))
    )
    op.create_index('idx_users_external_id', 'users', ['external_id'], unique=True)
    op.create_index('idx_users_email', 'users', ['email'], unique=True)
    op.create_index('idx_users_is_active', 'users', ['is_active'])

    # 3. Create member_role enum and organization_members table
    op.execute("CREATE TYPE member_role AS ENUM ('owner', 'admin', 'member', 'viewer')")
    op.create_table(
        'organization_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.Enum('owner', 'admin', 'member', 'viewer', name='member_role'), nullable=False, server_default='member'),
        sa.Column('joined_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('organization_id', 'user_id', name='unique_org_user')
    )
    op.create_index('idx_org_members_org', 'organization_members', ['organization_id'])
    op.create_index('idx_org_members_user', 'organization_members', ['user_id'])
    op.create_index('idx_org_members_role', 'organization_members', ['role'])

    # 4. Create default organization and system user for existing data
    default_org_id_str = str(DEFAULT_ORG_ID)
    system_user_id_str = str(SYSTEM_USER_ID)

    # Insert default organization
    op.execute(f"""
        INSERT INTO organizations (id, name, slug, settings, created_at, updated_at)
        VALUES (
            '{default_org_id_str}',
            'Default Workspace',
            'default',
            '{{}}'::jsonb,
            NOW(),
            NOW()
        )
    """)

    # Insert system user (for migration purposes)
    # Uses synthetic external_id for system account
    op.execute(f"""
        INSERT INTO users (id, external_id, auth_provider, email, full_name, is_active, is_superuser, created_at, updated_at)
        VALUES (
            '{system_user_id_str}',
            'system-raas-migration',
            'internal',
            'system@raas.local',
            'System User',
            true,
            true,
            NOW(),
            NOW()
        )
    """)

    # Add system user as owner of default organization
    op.execute(f"""
        INSERT INTO organization_members (organization_id, user_id, role, joined_at)
        VALUES (
            '{default_org_id_str}',
            '{system_user_id_str}',
            'owner',
            NOW()
        )
    """)

    # Insert solo developer user (for authentication_enabled=False mode)
    # This user is used when running in solo mode without Keycloak
    solo_user_id = uuid.uuid4()
    solo_user_id_str = str(solo_user_id)

    op.execute(f"""
        INSERT INTO users (id, external_id, auth_provider, email, full_name, is_active, is_superuser, created_at, updated_at)
        VALUES (
            '{solo_user_id_str}',
            'solo-developer',
            'local',
            'solo@raas.local',
            'Solo Developer',
            true,
            false,
            NOW(),
            NOW()
        )
    """)

    # Add solo user as owner of default organization
    op.execute(f"""
        INSERT INTO organization_members (organization_id, user_id, role, joined_at)
        VALUES (
            '{default_org_id_str}',
            '{solo_user_id_str}',
            'owner',
            NOW()
        )
    """)

    # 5. Add new columns to requirements table (nullable for migration)
    op.add_column('requirements', sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('requirements', sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('requirements', sa.Column('updated_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))

    # 6. Migrate existing requirements to default organization and system user
    op.execute(f"""
        UPDATE requirements
        SET
            organization_id = '{default_org_id_str}',
            created_by_user_id = '{system_user_id_str}',
            updated_by_user_id = '{system_user_id_str}'
        WHERE organization_id IS NULL
    """)

    # 7. Make organization_id NOT NULL and add foreign keys
    op.alter_column('requirements', 'organization_id', nullable=False)
    op.create_foreign_key(
        'fk_requirements_organization',
        'requirements', 'organizations',
        ['organization_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_requirements_created_by_user',
        'requirements', 'users',
        ['created_by_user_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_requirements_updated_by_user',
        'requirements', 'users',
        ['updated_by_user_id'], ['id'],
        ondelete='SET NULL'
    )

    # 8. Create indexes for requirements
    op.create_index('idx_requirements_organization', 'requirements', ['organization_id'])
    op.create_index('idx_requirements_created_by_user', 'requirements', ['created_by_user_id'])
    op.create_index('idx_requirements_updated_by_user', 'requirements', ['updated_by_user_id'])

    # 9. Add new columns to requirement_history table (nullable)
    op.add_column('requirement_history', sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('requirement_history', sa.Column('changed_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))

    # 10. Migrate existing history to default organization and system user
    op.execute(f"""
        UPDATE requirement_history
        SET
            organization_id = '{default_org_id_str}',
            changed_by_user_id = '{system_user_id_str}'
        WHERE organization_id IS NULL
    """)

    # 11. Add foreign keys for requirement_history
    op.create_foreign_key(
        'fk_requirement_history_organization',
        'requirement_history', 'organizations',
        ['organization_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_requirement_history_changed_by_user',
        'requirement_history', 'users',
        ['changed_by_user_id'], ['id'],
        ondelete='SET NULL'
    )

    # 12. Create indexes for requirement_history
    op.create_index('idx_requirement_history_organization', 'requirement_history', ['organization_id'])
    op.create_index('idx_requirement_history_changed_by_user', 'requirement_history', ['changed_by_user_id'])


def downgrade() -> None:
    """Remove multi-user authentication tables and relationships."""

    # Drop indexes from requirement_history
    op.drop_index('idx_requirement_history_changed_by_user')
    op.drop_index('idx_requirement_history_organization')

    # Drop foreign keys and columns from requirement_history
    op.drop_constraint('fk_requirement_history_changed_by_user', 'requirement_history')
    op.drop_constraint('fk_requirement_history_organization', 'requirement_history')
    op.drop_column('requirement_history', 'changed_by_user_id')
    op.drop_column('requirement_history', 'organization_id')

    # Drop indexes from requirements
    op.drop_index('idx_requirements_updated_by_user')
    op.drop_index('idx_requirements_created_by_user')
    op.drop_index('idx_requirements_organization')

    # Drop foreign keys and columns from requirements
    op.drop_constraint('fk_requirements_updated_by_user', 'requirements')
    op.drop_constraint('fk_requirements_created_by_user', 'requirements')
    op.drop_constraint('fk_requirements_organization', 'requirements')
    op.drop_column('requirements', 'updated_by_user_id')
    op.drop_column('requirements', 'created_by_user_id')
    op.drop_column('requirements', 'organization_id')

    # Drop organization_members table
    op.drop_table('organization_members')

    # Drop users table
    op.drop_table('users')

    # Drop organizations table
    op.drop_table('organizations')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS member_role')
