"""Schema Simplification: Move content fields to RequirementVersion (CR-009).

Revision ID: 046
Revises: 045
Create Date: 2025-11-29

CR-009: Complete the schema simplification started in CR-006.
The Requirement table currently duplicates content fields that should live
exclusively on RequirementVersion.

Changes:
1. Add missing fields to requirement_versions: tags, adheres_to, content_length, quality_score
2. Backfill these fields from requirements to their versions
3. Remove duplicate fields from requirements table

Target Requirement schema (7 fields):
- id, human_readable_id, type, parent_id, organization_id, project_id, deployed_version_id

Target RequirementVersion schema (all content + metadata):
- All existing fields plus: tags, adheres_to, content_length, quality_score
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '046'
down_revision: Union[str, None] = '045'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply CR-009 schema simplification."""

    # =========================================================================
    # Step 1: Add new columns to requirement_versions
    # =========================================================================

    # Add tags column
    op.add_column(
        'requirement_versions',
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True, server_default='{}')
    )

    # Add adheres_to column
    op.add_column(
        'requirement_versions',
        sa.Column('adheres_to', postgresql.ARRAY(sa.String()), nullable=True, server_default='{}')
    )

    # Add content_length column
    op.add_column(
        'requirement_versions',
        sa.Column('content_length', sa.Integer(), nullable=True, server_default='0')
    )

    # Add quality_score column (using existing enum)
    op.execute("""
        ALTER TABLE requirement_versions
        ADD COLUMN quality_score quality_score DEFAULT 'OK'
    """)

    # =========================================================================
    # Step 2: Backfill new columns from requirements to their versions
    # =========================================================================

    # For each requirement, copy tags/adheres_to/content_length/quality_score
    # to ALL versions (they share the same metadata since it was on the parent)
    op.execute("""
        UPDATE requirement_versions rv
        SET
            tags = r.tags,
            adheres_to = r.adheres_to,
            content_length = COALESCE(r.content_length, LENGTH(rv.content)),
            quality_score = r.quality_score
        FROM requirements r
        WHERE rv.requirement_id = r.id
    """)

    # Set NOT NULL constraints now that data is backfilled
    op.alter_column('requirement_versions', 'tags', nullable=False, server_default=None)
    op.alter_column('requirement_versions', 'adheres_to', nullable=False, server_default=None)
    op.alter_column('requirement_versions', 'content_length', nullable=False, server_default=None)
    op.alter_column('requirement_versions', 'quality_score', nullable=False, server_default=None)

    # =========================================================================
    # Step 3: Drop duplicate columns from requirements table
    # =========================================================================

    # Drop indexes first (if they exist)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_requirements_quality_score') THEN
                DROP INDEX ix_requirements_quality_score;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_requirements_status') THEN
                DROP INDEX ix_requirements_status;
            END IF;
        END $$;
    """)

    # Drop content/metadata columns
    op.drop_column('requirements', 'title')
    op.drop_column('requirements', 'description')
    op.drop_column('requirements', 'content')
    op.drop_column('requirements', 'status')
    op.drop_column('requirements', 'tags')
    op.drop_column('requirements', 'adheres_to')
    op.drop_column('requirements', 'content_length')
    op.drop_column('requirements', 'quality_score')
    op.drop_column('requirements', 'content_hash')

    # Drop audit columns (v1 captures creation, versions track changes)
    op.drop_column('requirements', 'created_at')
    op.drop_column('requirements', 'updated_at')
    op.drop_column('requirements', 'created_by_user_id')
    op.drop_column('requirements', 'updated_by_user_id')


def downgrade() -> None:
    """Revert CR-009 schema simplification."""

    # =========================================================================
    # Step 1: Restore columns to requirements table
    # =========================================================================

    # Restore audit columns
    op.add_column('requirements', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('requirements', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('requirements', sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('requirements', sa.Column('updated_by_user_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Restore content/metadata columns
    op.add_column('requirements', sa.Column('title', sa.String(200), nullable=True))
    op.add_column('requirements', sa.Column('description', sa.String(500), nullable=True))
    op.add_column('requirements', sa.Column('content', sa.Text(), nullable=True))
    op.add_column('requirements', sa.Column('content_hash', sa.String(64), nullable=True))
    op.add_column('requirements', sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True, server_default='{}'))
    op.add_column('requirements', sa.Column('adheres_to', postgresql.ARRAY(sa.String()), nullable=True, server_default='{}'))
    op.add_column('requirements', sa.Column('content_length', sa.Integer(), nullable=True, server_default='0'))

    # Restore status using raw SQL (existing enum)
    op.execute("""
        ALTER TABLE requirements
        ADD COLUMN status lifecycle_status DEFAULT 'draft'
    """)

    # Restore quality_score using raw SQL (existing enum)
    op.execute("""
        ALTER TABLE requirements
        ADD COLUMN quality_score quality_score DEFAULT 'OK'
    """)

    # =========================================================================
    # Step 2: Restore data from latest versions to requirements
    # =========================================================================

    # Get content fields from resolved version (deployed or latest approved or latest)
    op.execute("""
        UPDATE requirements r
        SET
            title = rv.title,
            description = rv.description,
            content = rv.content,
            content_hash = rv.content_hash,
            status = rv.status,
            tags = rv.tags,
            adheres_to = rv.adheres_to,
            content_length = rv.content_length,
            quality_score = rv.quality_score
        FROM requirement_versions rv
        WHERE rv.id = (
            -- Resolve version: deployed > latest approved > latest
            SELECT COALESCE(
                r.deployed_version_id,
                (
                    SELECT id FROM requirement_versions
                    WHERE requirement_id = r.id AND status = 'approved'
                    ORDER BY version_number DESC LIMIT 1
                ),
                (
                    SELECT id FROM requirement_versions
                    WHERE requirement_id = r.id
                    ORDER BY version_number DESC LIMIT 1
                )
            )
        )
    """)

    # Restore audit fields from v1
    op.execute("""
        UPDATE requirements r
        SET
            created_at = (
                SELECT created_at FROM requirement_versions
                WHERE requirement_id = r.id AND version_number = 1
            ),
            created_by_user_id = (
                SELECT created_by_user_id FROM requirement_versions
                WHERE requirement_id = r.id AND version_number = 1
            ),
            updated_at = (
                SELECT created_at FROM requirement_versions
                WHERE requirement_id = r.id
                ORDER BY version_number DESC LIMIT 1
            ),
            updated_by_user_id = (
                SELECT created_by_user_id FROM requirement_versions
                WHERE requirement_id = r.id
                ORDER BY version_number DESC LIMIT 1
            )
    """)

    # Set NOT NULL on required columns
    op.alter_column('requirements', 'title', nullable=False)
    op.alter_column('requirements', 'created_at', nullable=False)
    op.alter_column('requirements', 'updated_at', nullable=False)

    # Restore indexes
    op.create_index('ix_requirements_status', 'requirements', ['status'])
    op.create_index('ix_requirements_quality_score', 'requirements', ['quality_score'])

    # =========================================================================
    # Step 3: Drop new columns from requirement_versions
    # =========================================================================

    op.drop_column('requirement_versions', 'tags')
    op.drop_column('requirement_versions', 'adheres_to')
    op.drop_column('requirement_versions', 'content_length')
    op.drop_column('requirement_versions', 'quality_score')
