"""Make work_items.project_id NOT NULL (BUG-016).

Revision ID: 050
Revises: 049
Create Date: 2025-11-30

BUG-016: Work Item HRID generation fails when project_id is NULL

The HRID trigger uses (project_id, requirement_type) as the sequence key.
When project_id is NULL, it falls back to nil UUID which creates a separate
sequence starting at 1, causing HRID collisions with existing work items.

Fix: Make project_id required. Work items are project-scoped.

This migration:
1. Migrates existing NULL project_id work items to TarkaFlow project
2. Makes project_id NOT NULL
3. Updates trigger to remove nil UUID fallback
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '050'
down_revision: Union[str, None] = '049'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# TarkaFlow project ID - all NULL project_id work items belong here
TARKAFLOW_PROJECT_ID = '0099776f-b0d9-4459-b81b-0a6e3b42895d'


def upgrade() -> None:
    """Make project_id required on work_items."""

    # Step 1: Migrate existing NULL project_id work items to TarkaFlow project
    op.execute(f"""
        UPDATE work_items
        SET project_id = '{TARKAFLOW_PROJECT_ID}'::uuid
        WHERE project_id IS NULL
    """)

    # Step 2: Make project_id NOT NULL
    op.alter_column('work_items', 'project_id',
                    existing_type=sa.UUID(),
                    nullable=False)

    # Step 3: Update trigger to remove nil UUID fallback (no longer needed)
    op.execute("""
        CREATE OR REPLACE FUNCTION generate_work_item_human_readable_id()
        RETURNS TRIGGER AS $$
        DECLARE
            type_prefix TEXT;
            next_num INTEGER;
        BEGIN
            -- Determine prefix based on work item type
            CASE NEW.work_item_type
                WHEN 'cr' THEN type_prefix := 'CR';
                WHEN 'bug' THEN type_prefix := 'BUG';
                WHEN 'debt' THEN type_prefix := 'DEBT';
                WHEN 'release' THEN type_prefix := 'REL';
                ELSE type_prefix := 'WI';  -- Fallback for any future types
            END CASE;

            -- Get or create sequence for this project + type
            -- project_id is now guaranteed NOT NULL
            INSERT INTO id_sequences (project_id, requirement_type, next_number)
            VALUES (
                NEW.project_id,
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
    """Make project_id nullable again (not recommended)."""

    # Make project_id nullable again
    op.alter_column('work_items', 'project_id',
                    existing_type=sa.UUID(),
                    nullable=True)

    # Restore trigger with nil UUID fallback
    op.execute("""
        CREATE OR REPLACE FUNCTION generate_work_item_human_readable_id()
        RETURNS TRIGGER AS $$
        DECLARE
            type_prefix TEXT;
            next_num INTEGER;
        BEGIN
            CASE NEW.work_item_type
                WHEN 'cr' THEN type_prefix := 'CR';
                WHEN 'bug' THEN type_prefix := 'BUG';
                WHEN 'debt' THEN type_prefix := 'DEBT';
                WHEN 'release' THEN type_prefix := 'REL';
                ELSE type_prefix := 'WI';
            END CASE;

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

            NEW.human_readable_id := type_prefix || '-' || LPAD(next_num::TEXT, 3, '0');

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
