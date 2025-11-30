"""Add AcceptanceCriteria entity (CR-017).

Revision ID: 051
Revises: 050
Create Date: 2025-11-30

CR-017: Extract Acceptance Criteria as Separate Entity with Mutable Status

Extracts Acceptance Criteria from requirement content into a dedicated entity.
Each AC belongs to a specific RequirementVersion with immutable specification
text but mutable completion status.

Key design decisions per TARKA-REQ-104:
- criteria_text is immutable (authored content)
- met status is mutable (no version impact)
- content_hash enables strict text matching for carry-forward
- source_ac_id provides lineage tracking across versions

This migration:
1. Creates acceptance_criteria table with all required fields
2. Adds unique constraint on (requirement_version_id, ordinal)
3. Adds index on requirement_version_id for efficient lookups
4. Adds self-referential FK for lineage tracking
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '051'
down_revision: Union[str, None] = '050'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create acceptance_criteria table."""

    op.create_table(
        'acceptance_criteria',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('requirement_version_id', UUID(as_uuid=True), sa.ForeignKey('requirement_versions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('criteria_text', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('met', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('met_at', sa.DateTime(), nullable=True),
        sa.Column('met_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_ac_id', UUID(as_uuid=True), sa.ForeignKey('acceptance_criteria.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
    )

    # Unique constraint: ordinal must be unique within a version
    op.create_unique_constraint(
        'uq_acceptance_criteria_version_ordinal',
        'acceptance_criteria',
        ['requirement_version_id', 'ordinal']
    )

    # Index for lineage queries
    op.create_index(
        'ix_acceptance_criteria_source_ac_id',
        'acceptance_criteria',
        ['source_ac_id']
    )

    # Check constraint: met_at and met_by_user_id must both be set or both be NULL
    op.execute("""
        ALTER TABLE acceptance_criteria
        ADD CONSTRAINT ck_acceptance_criteria_met_consistency
        CHECK (
            (met_at IS NULL AND met_by_user_id IS NULL) OR
            (met_at IS NOT NULL AND met_by_user_id IS NOT NULL)
        )
    """)


def downgrade() -> None:
    """Drop acceptance_criteria table."""
    op.drop_table('acceptance_criteria')
