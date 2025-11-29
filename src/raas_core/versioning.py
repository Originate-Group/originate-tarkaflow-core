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
) -> Optional[models.RequirementVersion]:
    """Update deployed_version_id to track production deployment.

    Called when a Release deploys to production.

    CR-006: Updated to use version resolution instead of current_version_id.

    Args:
        db: Database session
        requirement: The requirement being deployed
        version_id: Specific version to mark as deployed (defaults to resolved version)

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
        logger.info(
            f"Updated deployed_version_id for {requirement.human_readable_id or requirement.id} "
            f"to version {version.version_number}"
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


def get_status_tag(
    requirement: models.Requirement,
    version: Optional[models.RequirementVersion] = None,
    release_hrid: Optional[str] = None,
) -> str:
    """Get the status tag to inject for a requirement version (TARKA-FEAT-106).

    Status tag injection rules (precedence order):
    1. deployed-REL-XXX - This version is in production via the specified Release
    2. deprecated - This requirement has been retired
    3. approved - Approved but not yet in a deployed Release
    4. review - Under review
    5. draft - Work in progress

    Key principle: deployed-REL-XXX supersedes approved because deployment implies approval.

    Args:
        requirement: The requirement
        version: The resolved version (if available)
        release_hrid: Human-readable ID of the Release that deployed this (if deployed)

    Returns:
        The status tag string to inject
    """
    # Check if this is the deployed version
    if version and requirement.deployed_version_id == version.id:
        if release_hrid:
            return f"deployed-{release_hrid}"
        else:
            return f"deployed-v{version.version_number}"

    # Check the version's status (CR-006: status lives on versions)
    if version:
        if version.status == models.LifecycleStatus.DEPRECATED:
            return "deprecated"
        elif version.status == models.LifecycleStatus.APPROVED:
            return "approved"
        elif version.status == models.LifecycleStatus.REVIEW:
            return "review"
        else:
            return "draft"

    # Fallback to requirement status if no version
    if requirement.status == models.LifecycleStatus.DEPRECATED:
        return "deprecated"
    elif requirement.status == models.LifecycleStatus.APPROVED:
        return "approved"
    elif requirement.status == models.LifecycleStatus.REVIEW:
        return "review"
    else:
        return "draft"
