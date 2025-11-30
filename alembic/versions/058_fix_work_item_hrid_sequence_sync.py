"""Fix work item HRID sequence sync (BUG-018).

Revision ID: 058
Revises: 057
Create Date: 2025-11-30

BUG-018: CR Work Item Creation Fails with Internal Server Error

Root Cause:
- The id_sequences table has stale/wrong next_number values
- When creating a CR, the trigger generates TARKA-CR-017 but that already exists
- Sequence needs to be synced to max existing HRID + 1

Solution:
- Query max HRID number per project + work item type
- Update sequences to be >= max existing + 1
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '058'
down_revision: Union[str, None] = '057'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sync work item HRID sequences to match actual max values."""

    # Update sequences to be at least max existing + 1
    # This handles all work item types: cr, bug, debt, release
    op.execute("""
        WITH max_hrids AS (
            SELECT
                w.project_id,
                w.work_item_type,
                'work_item_' || w.work_item_type AS seq_key,
                MAX(
                    CAST(
                        SPLIT_PART(w.human_readable_id, '-', 3) AS INTEGER
                    )
                ) AS max_num
            FROM work_items w
            WHERE w.human_readable_id IS NOT NULL
              AND w.project_id IS NOT NULL
              -- Format is PROJ-TYPE-NNN, get the NNN part
              AND SPLIT_PART(w.human_readable_id, '-', 3) ~ '^[0-9]+$'
            GROUP BY w.project_id, w.work_item_type
        )
        UPDATE id_sequences s
        SET next_number = m.max_num + 1,
            updated_at = NOW()
        FROM max_hrids m
        WHERE s.project_id = m.project_id
          AND s.requirement_type = m.seq_key
          AND s.next_number <= m.max_num
    """)

    # Also insert any missing sequences (shouldn't happen but defensive)
    op.execute("""
        WITH max_hrids AS (
            SELECT
                w.project_id,
                w.work_item_type,
                'work_item_' || w.work_item_type AS seq_key,
                MAX(
                    CAST(
                        SPLIT_PART(w.human_readable_id, '-', 3) AS INTEGER
                    )
                ) AS max_num
            FROM work_items w
            WHERE w.human_readable_id IS NOT NULL
              AND w.project_id IS NOT NULL
              AND SPLIT_PART(w.human_readable_id, '-', 3) ~ '^[0-9]+$'
            GROUP BY w.project_id, w.work_item_type
        )
        INSERT INTO id_sequences (project_id, requirement_type, next_number, created_at, updated_at)
        SELECT
            m.project_id,
            m.seq_key,
            m.max_num + 1,
            NOW(),
            NOW()
        FROM max_hrids m
        WHERE NOT EXISTS (
            SELECT 1 FROM id_sequences s
            WHERE s.project_id = m.project_id
              AND s.requirement_type = m.seq_key
        )
    """)


def downgrade() -> None:
    """No downgrade - sequence values are data, not schema."""
    pass
