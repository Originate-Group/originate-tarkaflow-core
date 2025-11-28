"""Add Release work item type and includes relationship.

Revision ID: 023_release_work_items
Revises: 022_work_items_and_versioning
Create Date: 2025-11-28

RAAS-FEAT-102: Release Work Item & Bundled Deployment

This migration implements:
- Release type added to WorkItemType enum
- release_tag and github_release_url columns for Release metadata
- release_includes association table for Release → IR/CR/BUG bundling
- Updated trigger function for REL-### human-readable IDs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '023_release_work_items'
down_revision = '022_work_items_and_versioning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # Add 'release' to workitemtype enum
    # ==========================================================================
    op.execute("ALTER TYPE workitemtype ADD VALUE IF NOT EXISTS 'release'")

    # ==========================================================================
    # Add release-specific columns to work_items table
    # ==========================================================================
    op.add_column(
        'work_items',
        sa.Column('release_tag', sa.String(50), nullable=True)
    )
    op.add_column(
        'work_items',
        sa.Column('github_release_url', sa.String(500), nullable=True)
    )

    # ==========================================================================
    # Create release_includes association table
    # Links Release work items to the IR/CR/BUG work items they bundle
    # ==========================================================================
    op.create_table(
        'release_includes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('release_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('work_item_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('release_id', 'work_item_id', name='uq_release_includes_work_item'),
    )

    # ==========================================================================
    # Update trigger function to handle 'release' type with REL prefix
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION generate_work_item_human_readable_id()
        RETURNS TRIGGER AS $$
        DECLARE
            org_slug TEXT;
            type_prefix TEXT;
            next_num INTEGER;
        BEGIN
            -- Determine prefix based on work item type
            CASE NEW.work_item_type
                WHEN 'ir' THEN type_prefix := 'IR';
                WHEN 'cr' THEN type_prefix := 'CR';
                WHEN 'bug' THEN type_prefix := 'BUG';
                WHEN 'task' THEN type_prefix := 'WI';
                WHEN 'release' THEN type_prefix := 'REL';
                ELSE type_prefix := 'WI';
            END CASE;

            -- Get or create sequence for this org + type
            INSERT INTO id_sequences (project_id, requirement_type, next_number)
            VALUES (
                COALESCE(NEW.project_id, '00000000-0000-0000-0000-000000000000'::uuid),
                'work_item_' || NEW.work_item_type,
                1
            )
            ON CONFLICT (project_id, requirement_type) DO UPDATE
            SET next_number = id_sequences.next_number + 1,
                updated_at = NOW()
            RETURNING next_number INTO next_num;

            -- Generate human-readable ID
            NEW.human_readable_id := type_prefix || '-' || LPAD(next_num::TEXT, 3, '0');

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Drop trigger function update (original will be restored by migration 022)
    # Note: Cannot remove enum value in PostgreSQL, so 'release' remains

    # Drop release_includes table
    op.drop_table('release_includes')

    # Drop release-specific columns
    op.drop_column('work_items', 'github_release_url')
    op.drop_column('work_items', 'release_tag')
