"""Extract Acceptance Criteria from existing requirement versions (CR-017).

Revision ID: 052
Revises: 051
Create Date: 2025-11-30

CR-017 Data Migration: Populates the new acceptance_criteria table by parsing
existing requirement version content for markdown checkbox items.

This migration:
1. Scans all RequirementVersion records
2. Extracts AC checkboxes from the "## Acceptance Criteria" section
3. Creates AcceptanceCriteria records with proper content hashes
4. Preserves met status from [x] checkboxes
5. Sets up lineage (source_ac_id) for versions > 1 where AC text matches

IMPORTANT: This is a data-only migration. The schema was created in 051.
"""
from typing import Sequence, Union
import hashlib
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision: str = '052'
down_revision: Union[str, None] = '051'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def compute_ac_hash(criteria_text: str) -> str:
    """Compute SHA-256 hash of criteria text for matching."""
    normalized = criteria_text.strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def extract_acceptance_criteria(content: str) -> list[dict]:
    """Extract Acceptance Criteria from markdown content."""
    if not content:
        return []

    # Find Acceptance Criteria section
    ac_section_pattern = r'##\s+Acceptance\s+Criteria\s*\n(.*?)(?=\n##|\n#\s|\Z)'
    ac_match = re.search(ac_section_pattern, content, re.DOTALL | re.IGNORECASE)

    if not ac_match:
        return []

    ac_section = ac_match.group(1)

    # Extract checkbox items: - [ ] text or - [x] text
    checkbox_pattern = r'^-\s*\[([ xX])\]\s*(.+?)$'

    criteria_list = []
    ordinal = 1

    for line in ac_section.split('\n'):
        line = line.strip()
        match = re.match(checkbox_pattern, line)
        if match:
            checkbox_state = match.group(1)
            criteria_text = match.group(2).strip()

            # Skip placeholder text like "[User-observable outcome 1]"
            if criteria_text.startswith('[') and criteria_text.endswith(']'):
                continue

            # Skip empty or very short criteria
            if len(criteria_text) < 3:
                continue

            met = checkbox_state.lower() == 'x'

            criteria_list.append({
                'criteria_text': criteria_text,
                'met': met,
                'ordinal': ordinal,
                'content_hash': compute_ac_hash(criteria_text),
            })
            ordinal += 1

    return criteria_list


def upgrade() -> None:
    """Extract ACs from existing requirement versions."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get all requirement versions ordered by requirement_id, version_number
    versions = session.execute(sa.text("""
        SELECT id, requirement_id, version_number, content
        FROM requirement_versions
        ORDER BY requirement_id, version_number
    """)).fetchall()

    # Track predecessor ACs for lineage (grouped by requirement_id)
    predecessor_acs: dict = {}  # requirement_id -> {content_hash -> ac_id}

    total_acs = 0
    total_versions = 0

    for version_id, requirement_id, version_number, content in versions:
        if not content:
            continue

        criteria_list = extract_acceptance_criteria(content)
        if not criteria_list:
            continue

        total_versions += 1

        # Get predecessor AC map for this requirement
        req_predecessor_acs = predecessor_acs.get(str(requirement_id), {})

        # Insert ACs for this version
        new_ac_map = {}  # content_hash -> new_ac_id for next version's lineage

        for ac_data in criteria_list:
            content_hash = ac_data['content_hash']

            # Check for matching predecessor AC
            source_ac_id = req_predecessor_acs.get(content_hash)

            # Insert AC record
            result = session.execute(sa.text("""
                INSERT INTO acceptance_criteria
                    (requirement_version_id, ordinal, criteria_text, content_hash, met, source_ac_id)
                VALUES
                    (:version_id, :ordinal, :criteria_text, :content_hash, :met, :source_ac_id)
                RETURNING id
            """), {
                'version_id': version_id,
                'ordinal': ac_data['ordinal'],
                'criteria_text': ac_data['criteria_text'],
                'content_hash': content_hash,
                'met': ac_data['met'],
                'source_ac_id': source_ac_id,
            })

            new_ac_id = result.fetchone()[0]
            new_ac_map[content_hash] = new_ac_id
            total_acs += 1

        # Update predecessor map for next version of this requirement
        predecessor_acs[str(requirement_id)] = new_ac_map

    session.commit()
    print(f"CR-017 Migration: Extracted {total_acs} acceptance criteria from {total_versions} versions")


def downgrade() -> None:
    """Remove all extracted ACs (but keep the table)."""
    op.execute("DELETE FROM acceptance_criteria")
