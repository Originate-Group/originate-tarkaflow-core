"""Convert ## Success Criteria to ### Success Criteria and re-extract ACs.

Revision ID: 055
Revises: 054
Create Date: 2025-11-30

Converts standalone "## Success Criteria" sections to "### Success Criteria"
subsections under the Acceptance Criteria section, then re-extracts ACs
from all requirement versions to capture previously-missed checkboxes.

This ensures all checkboxes across all requirement types are tracked as ACs.
"""
from typing import Sequence, Union
import hashlib
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision: str = '055'
down_revision: Union[str, None] = '054'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def compute_ac_hash(criteria_text: str) -> str:
    """Compute SHA-256 hash of criteria text for matching."""
    normalized = criteria_text.strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def convert_success_criteria_header(content: str) -> tuple[str, bool]:
    """Convert ## Success Criteria to ### Success Criteria.

    Returns (updated_content, was_changed).
    """
    if not content:
        return content, False

    # Pattern to match "## Success Criteria" (but not "### Success Criteria")
    # Must be at start of line, with ## followed by space
    pattern = r'^(##)\s+(Success\s+Criteria)\s*$'

    # Check if we have a match
    if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
        return content, False

    # Replace ## Success Criteria with ### Success Criteria
    updated = re.sub(
        pattern,
        r'### \2',
        content,
        flags=re.MULTILINE | re.IGNORECASE
    )

    return updated, updated != content


def extract_acceptance_criteria_with_categories(content: str) -> list[dict]:
    """Extract ACs from content including categories from ### headers."""
    if not content:
        return []

    # Find Acceptance Criteria section
    ac_section_pattern = r'##\s+Acceptance\s+Criteria\s*\n(.*?)(?=\n##(?!#)|\n#\s|\Z)'
    ac_match = re.search(ac_section_pattern, content, re.DOTALL | re.IGNORECASE)

    if not ac_match:
        return []

    ac_section = ac_match.group(1)

    # Pattern for subsection headers
    subsection_pattern = r'^###\s+(.+)'
    # Pattern for checkbox items
    checkbox_pattern = r'^-\s*\[([ xX])\]\s*(.+?)$'

    criteria_list = []
    current_category = None
    ordinal = 1

    for line in ac_section.split('\n'):
        line_stripped = line.strip()

        # Check for subsection header (category)
        subsection_match = re.match(subsection_pattern, line_stripped)
        if subsection_match:
            current_category = subsection_match.group(1).strip()
            continue

        # Check for checkbox item
        checkbox_match = re.match(checkbox_pattern, line_stripped)
        if checkbox_match:
            checkbox_state = checkbox_match.group(1)
            criteria_text = checkbox_match.group(2).strip()

            # Skip placeholder text
            if criteria_text.startswith('[') and criteria_text.endswith(']'):
                continue
            if len(criteria_text) < 3:
                continue

            met = checkbox_state.lower() == 'x'

            criteria_list.append({
                'criteria_text': criteria_text,
                'met': met,
                'ordinal': ordinal,
                'category': current_category,
                'content_hash': compute_ac_hash(criteria_text),
            })
            ordinal += 1

    return criteria_list


def upgrade() -> None:
    """Convert Success Criteria headers and re-extract ACs."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Step 1: Convert ## Success Criteria to ### Success Criteria
    versions_with_success = session.execute(sa.text("""
        SELECT id, content
        FROM requirement_versions
        WHERE content IS NOT NULL
        AND content ~* '##\\s+Success\\s+Criteria'
    """)).fetchall()

    content_updated = 0
    for version_id, content in versions_with_success:
        updated_content, was_changed = convert_success_criteria_header(content)
        if was_changed:
            session.execute(sa.text("""
                UPDATE requirement_versions
                SET content = :content
                WHERE id = :version_id
            """), {'content': updated_content, 'version_id': version_id})
            content_updated += 1

    session.commit()
    print(f"Migration 055: Updated {content_updated} versions with Success Criteria header conversion")

    # Step 2: Re-extract ACs for all versions
    # Get all versions ordered by requirement_id, version_number
    all_versions = session.execute(sa.text("""
        SELECT rv.id, rv.requirement_id, rv.version_number, rv.content
        FROM requirement_versions rv
        ORDER BY rv.requirement_id, rv.version_number
    """)).fetchall()

    # Track predecessor ACs for lineage
    predecessor_acs: dict = {}  # requirement_id -> {content_hash -> ac_id}

    new_acs_created = 0
    categories_updated = 0

    for version_id, requirement_id, version_number, content in all_versions:
        if not content:
            continue

        # Extract ACs with categories
        criteria_list = extract_acceptance_criteria_with_categories(content)
        if not criteria_list:
            # Update predecessor map to empty for next version
            predecessor_acs[str(requirement_id)] = {}
            continue

        # Get existing ACs for this version
        existing_acs = session.execute(sa.text("""
            SELECT id, ordinal, content_hash, category
            FROM acceptance_criteria
            WHERE requirement_version_id = :version_id
            ORDER BY ordinal
        """), {'version_id': version_id}).fetchall()

        existing_by_hash = {ac[2]: {'id': ac[0], 'ordinal': ac[1], 'category': ac[3]}
                           for ac in existing_acs}

        # Find max ordinal for this version to append new ACs after existing ones
        max_ordinal = max((ac[1] for ac in existing_acs), default=0)

        # Get predecessor AC map for this requirement
        req_predecessor_acs = predecessor_acs.get(str(requirement_id), {})
        new_ac_map = {}

        for ac_data in criteria_list:
            content_hash = ac_data['content_hash']

            if content_hash in existing_by_hash:
                # AC already exists - update category if needed
                existing = existing_by_hash[content_hash]
                if existing['category'] != ac_data['category'] and ac_data['category']:
                    session.execute(sa.text("""
                        UPDATE acceptance_criteria
                        SET category = :category
                        WHERE id = :ac_id
                    """), {'category': ac_data['category'], 'ac_id': existing['id']})
                    categories_updated += 1
                new_ac_map[content_hash] = existing['id']
            else:
                # New AC - insert it with ordinal after existing ACs
                max_ordinal += 1
                source_ac_id = req_predecessor_acs.get(content_hash)

                result = session.execute(sa.text("""
                    INSERT INTO acceptance_criteria
                        (requirement_version_id, ordinal, criteria_text, content_hash,
                         met, category, source_ac_id)
                    VALUES
                        (:version_id, :ordinal, :criteria_text, :content_hash,
                         :met, :category, :source_ac_id)
                    RETURNING id
                """), {
                    'version_id': version_id,
                    'ordinal': max_ordinal,
                    'criteria_text': ac_data['criteria_text'],
                    'content_hash': content_hash,
                    'met': ac_data['met'],
                    'category': ac_data['category'],
                    'source_ac_id': source_ac_id,
                })

                new_ac_id = result.fetchone()[0]
                new_ac_map[content_hash] = new_ac_id
                new_acs_created += 1

        # Update predecessor map for next version
        predecessor_acs[str(requirement_id)] = new_ac_map

    session.commit()
    print(f"Migration 055: Created {new_acs_created} new ACs, updated {categories_updated} categories")


def downgrade() -> None:
    """Cannot easily revert header changes - would need to track which were changed."""
    print("WARNING: Cannot revert Success Criteria header changes. "
          "Manual intervention required if rollback needed.")
