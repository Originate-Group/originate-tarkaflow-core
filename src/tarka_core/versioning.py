"""Requirement versioning utilities (CR-006: Version Model Simplification).

Implements git-like immutable versioning where every content change creates a new
RequirementVersion record. Each version has its own status (draft/review/approved/deprecated).

Key concepts (CR-006):
- deployed_version_id: Points to what's actually in production (the only pointer on Requirement)
- Status lives on versions, not on requirements
- Version resolution at read time determines what content to return:
  1. If deployed_version_id exists, return that version
  2. Else if any approved versions exist, return the latest approved
  3. Else return the latest version
- Modifying approved content regresses status to draft on the requirement (for display)
"""
import hashlib
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


logger = logging.getLogger("raas-core.versioning")


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for conflict detection.

    Used for:
    - Detecting concurrent modifications (baseline hash comparison)
    - Verifying content integrity
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_next_version_number(db: Session, requirement_id: UUID) -> int:
    """Get the next version number for a requirement.

    Returns 1 for new requirements, or max_version + 1 for existing.
    """
    max_version = db.query(func.max(models.RequirementVersion.version_number)).filter(
        models.RequirementVersion.requirement_id == requirement_id
    ).scalar() or 0
    return max_version + 1


def create_requirement_version(
    db: Session,
    requirement: models.Requirement,
    content: str,
    title: str,
    description: Optional[str] = None,
    status: models.LifecycleStatus = models.LifecycleStatus.DRAFT,
    tags: Optional[list] = None,
    adheres_to: Optional[list] = None,
    user_id: Optional[UUID] = None,
    source_work_item_id: Optional[UUID] = None,
    change_reason: Optional[str] = None,
) -> models.RequirementVersion:
    """Create a new immutable version snapshot of a requirement.

    CR-006: Versions now have their own status. The status parameter defaults
    to DRAFT but should be set to the requirement's current status when creating
    a version from an existing requirement.

    CR-009: All content and metadata fields now live on versions. Title, description,
    tags, adheres_to, content_length, and quality_score are stored on each version.

    This function:
    1. Computes content hash for conflict detection
    2. Calculates content_length and quality_score
    3. Determines next version number
    4. Creates RequirementVersion record with all fields

    Args:
        db: Database session
        requirement: The requirement being versioned
        content: The content to snapshot
        title: Title for this version (extracted from content)
        description: Description for this version (extracted from content)
        status: Status for this version (CR-006)
        tags: Tags for this version (CR-009)
        adheres_to: Guardrail references for this version (CR-009)
        user_id: User making the change
        source_work_item_id: Work Item (CR/IR) that caused this version
        change_reason: Human-readable reason for the change

    Returns:
        The created RequirementVersion
    """
    # Import here to avoid circular imports
    from .quality import calculate_quality_score

    content_hash = compute_content_hash(content)
    content_length = len(content) if content else 0
    quality_score = calculate_quality_score(content_length, requirement.type)
    version_number = get_next_version_number(db, requirement.id)

    version = models.RequirementVersion(
        requirement_id=requirement.id,
        version_number=version_number,
        status=status,  # CR-006: Status lives on versions
        content=content,
        content_hash=content_hash,
        title=title,
        description=description,
        # CR-009: Metadata fields on version
        tags=tags or [],
        adheres_to=adheres_to or [],
        content_length=content_length,
        quality_score=quality_score,
        # Audit and provenance
        source_work_item_id=source_work_item_id,
        change_reason=change_reason,
        created_by_user_id=user_id,
    )

    db.add(version)
    db.flush()  # Get the version ID

    logger.info(
        f"Created version {version_number} (status={status.value}) for requirement "
        f"{requirement.human_readable_id or requirement.id}"
        f"{f' from work item {source_work_item_id}' if source_work_item_id else ''}"
    )

    # CR-017: Extract and create Acceptance Criteria from content
    from .markdown_utils import extract_acceptance_criteria
    acceptance_criteria = extract_acceptance_criteria(content)

    if acceptance_criteria:
        # Get predecessor version for carry-forward logic
        predecessor_version = None
        if version_number > 1:
            predecessor_version = db.query(models.RequirementVersion).filter(
                models.RequirementVersion.requirement_id == requirement.id,
                models.RequirementVersion.version_number == version_number - 1
            ).first()

        created_acs = create_acceptance_criteria_for_version(
            db=db,
            new_version=version,
            acceptance_criteria=acceptance_criteria,
            predecessor_version=predecessor_version,
        )
        logger.info(f"Created {len(created_acs)} acceptance criteria for version {version_number}")

    return version


def get_latest_version(db: Session, requirement_id: UUID) -> Optional[models.RequirementVersion]:
    """Get the most recent version of a requirement.

    Returns None if no versions exist.
    """
    return db.query(models.RequirementVersion).filter(
        models.RequirementVersion.requirement_id == requirement_id
    ).order_by(
        models.RequirementVersion.version_number.desc()
    ).first()


def get_latest_approved_version(db: Session, requirement_id: UUID) -> Optional[models.RequirementVersion]:
    """Get the most recent approved version of a requirement.

    CR-006: Returns the latest version with status='approved'.
    Returns None if no approved versions exist.
    """
    return db.query(models.RequirementVersion).filter(
        models.RequirementVersion.requirement_id == requirement_id,
        models.RequirementVersion.status == models.LifecycleStatus.APPROVED
    ).order_by(
        models.RequirementVersion.version_number.desc()
    ).first()


def resolve_version(
    db: Session,
    requirement: models.Requirement,
    version_number: Optional[int] = None,
) -> Optional[models.RequirementVersion]:
    """Resolve which version to return for a requirement (TARKA-FEAT-106).

    Version Resolution Rules:
    1. If version_number is specified, return that specific version
    2. If deployed_version_id exists, return that version
    3. Else if any approved versions exist, return the latest approved
    4. Else return the latest version (v1 draft for new requirements)

    Args:
        db: Database session
        requirement: The requirement to resolve version for
        version_number: Optional explicit version number to return

    Returns:
        The resolved RequirementVersion, or None if no versions exist
    """
    # Explicit version override
    if version_number is not None:
        return db.query(models.RequirementVersion).filter(
            models.RequirementVersion.requirement_id == requirement.id,
            models.RequirementVersion.version_number == version_number
        ).first()

    # 1. If deployed_version_id exists, return that version
    if requirement.deployed_version_id:
        version = db.query(models.RequirementVersion).filter(
            models.RequirementVersion.id == requirement.deployed_version_id
        ).first()
        if version:
            return version

    # 2. Else if any approved versions exist, return the latest approved
    approved = get_latest_approved_version(db, requirement.id)
    if approved:
        return approved

    # 3. Else return the latest version
    return get_latest_version(db, requirement.id)


def update_deployed_version_pointer(
    db: Session,
    requirement: models.Requirement,
    version_id: Optional[UUID] = None,
    release_id: Optional[UUID] = None,
) -> Optional[models.RequirementVersion]:
    """Update deployed_version_id to track production deployment.

    Called when a Release deploys to production.

    CR-006: Updated to use version resolution instead of current_version_id.
    TARKA-FEAT-106: Added release_id tracking for status tag injection.

    Args:
        db: Database session
        requirement: The requirement being deployed
        version_id: Specific version to mark as deployed (defaults to resolved version)
        release_id: UUID of the Release work item that deployed this version

    Returns the version that was set as deployed, or None if no version found.
    """
    if version_id:
        version = db.query(models.RequirementVersion).filter(
            models.RequirementVersion.id == version_id
        ).first()
    else:
        # CR-006: Use version resolution instead of current_version_id
        version = resolve_version(db, requirement)

    if version:
        requirement.deployed_version_id = version.id
        # TARKA-FEAT-106: Track which Release deployed this version
        if release_id:
            requirement.deployed_by_release_id = release_id
        logger.info(
            f"Updated deployed_version_id for {requirement.human_readable_id or requirement.id} "
            f"to version {version.version_number}"
            f"{f' via Release {release_id}' if release_id else ''}"
        )
    return version


def should_regress_to_draft(requirement: models.Requirement) -> bool:
    """Check if a requirement should regress to draft status.

    Requirements in 'approved' status regress to 'draft' when their content changes.
    This ensures specification changes go through the review workflow again.

    Note: Requirements in 'review' status also regress to draft on content change,
    as the reviewed content is no longer what's being submitted.
    """
    return requirement.status in [
        models.LifecycleStatus.APPROVED,
        models.LifecycleStatus.REVIEW,
    ]


def content_has_changed(old_content: Optional[str], new_content: str) -> bool:
    """Check if content has materially changed.

    Uses hash comparison for efficiency on large content.
    """
    if old_content is None:
        return True

    old_hash = compute_content_hash(old_content)
    new_hash = compute_content_hash(new_content)
    return old_hash != new_hash


# =============================================================================
# CR-017: Acceptance Criteria Version Transition (TARKA-FEAT-111)
# =============================================================================


def compute_ac_content_hash(criteria_text: str) -> str:
    """Compute SHA-256 hash of AC criteria text for carry-forward matching.

    CR-017: Uses strict text matching - any change to criteria text is treated
    as a new AC (met status resets to false).

    Args:
        criteria_text: The acceptance criteria specification text

    Returns:
        SHA-256 hex digest of normalized (trimmed) criteria text
    """
    normalized = criteria_text.strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def create_acceptance_criteria_for_version(
    db: Session,
    new_version: models.RequirementVersion,
    acceptance_criteria: list[dict],
    predecessor_version: Optional[models.RequirementVersion] = None,
) -> list[models.AcceptanceCriteria]:
    """Create AcceptanceCriteria records for a new version with carry-forward logic.

    CR-017 / TARKA-REQ-104 Version Transition Algorithm:
    1. Compute content_hash for each incoming AC text
    2. Query predecessor version's ACs (if exists)
    3. For each incoming AC:
       - Match by content_hash against predecessor ACs
       - If match found: create new AC with met=predecessor.met, source_ac_id=predecessor.id
       - If no match: create new AC with met=false, source_ac_id=NULL
    4. Predecessor ACs not in incoming list are not copied (remain on old version only)

    Args:
        db: Database session
        new_version: The RequirementVersion being created
        acceptance_criteria: List of AC dicts with 'criteria_text' and optionally 'ordinal'
        predecessor_version: The previous version to carry forward met status from

    Returns:
        List of created AcceptanceCriteria records
    """
    created_acs = []

    # Build predecessor AC lookup by content_hash
    predecessor_ac_map: dict[str, models.AcceptanceCriteria] = {}
    if predecessor_version:
        for pred_ac in predecessor_version.acceptance_criteria:
            predecessor_ac_map[pred_ac.content_hash] = pred_ac

    for idx, ac_data in enumerate(acceptance_criteria):
        criteria_text = ac_data.get('criteria_text', '').strip()
        if not criteria_text:
            continue

        ordinal = ac_data.get('ordinal', idx + 1)
        content_hash = compute_ac_content_hash(criteria_text)

        # Check for matching predecessor AC
        predecessor_ac = predecessor_ac_map.get(content_hash)

        ac = models.AcceptanceCriteria(
            requirement_version_id=new_version.id,
            ordinal=ordinal,
            criteria_text=criteria_text,
            content_hash=content_hash,
            # Carry forward met status if matching predecessor exists
            met=predecessor_ac.met if predecessor_ac else False,
            met_at=predecessor_ac.met_at if predecessor_ac else None,
            met_by_user_id=predecessor_ac.met_by_user_id if predecessor_ac else None,
            # Lineage tracking
            source_ac_id=predecessor_ac.id if predecessor_ac else None,
        )

        db.add(ac)
        created_acs.append(ac)

        if predecessor_ac:
            logger.info(
                f"AC '{criteria_text[:50]}...' carried forward from predecessor "
                f"(met={predecessor_ac.met}, source_ac_id={predecessor_ac.id})"
            )
        else:
            logger.info(f"New AC '{criteria_text[:50]}...' created with met=false")

    db.flush()  # Ensure IDs are assigned
    return created_acs


def update_acceptance_criteria_met_status(
    db: Session,
    ac_id: UUID,
    met: bool,
    user_id: UUID,
) -> Optional[models.AcceptanceCriteria]:
    """Update the met status of an AcceptanceCriteria record.

    CR-017: Met status is mutable without triggering version changes.
    This enables granular progress tracking.

    Args:
        db: Database session
        ac_id: UUID of the AcceptanceCriteria to update
        met: New met status (True/False)
        user_id: UUID of user marking the AC

    Returns:
        Updated AcceptanceCriteria or None if not found
    """
    from datetime import datetime

    ac = db.query(models.AcceptanceCriteria).filter(
        models.AcceptanceCriteria.id == ac_id
    ).first()

    if not ac:
        return None

    old_met = ac.met
    ac.met = met

    if met:
        ac.met_at = datetime.utcnow()
        ac.met_by_user_id = user_id
    else:
        # Clearing met status
        ac.met_at = None
        ac.met_by_user_id = None

    db.flush()

    logger.info(
        f"AC {ac_id} met status updated: {old_met} -> {met} by user {user_id}"
    )

    return ac


def get_acceptance_criteria_summary(
    version: models.RequirementVersion
) -> dict:
    """Get a summary of acceptance criteria completion for a version.

    CR-017: Returns aggregated completion state for display.

    Args:
        version: The RequirementVersion to summarize

    Returns:
        Dict with 'total', 'met', 'unmet', and 'completion_percent' fields
    """
    acs = version.acceptance_criteria if version else []
    total = len(acs)
    met_count = sum(1 for ac in acs if ac.met)
    unmet_count = total - met_count

    return {
        'total': total,
        'met': met_count,
        'unmet': unmet_count,
        'completion_percent': round((met_count / total * 100) if total > 0 else 0, 1),
    }
