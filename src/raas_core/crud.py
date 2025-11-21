"""CRUD operations for requirements."""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, and_, cast, case, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from . import models, schemas
from .markdown_utils import render_template, extract_metadata, merge_content, MarkdownParseError
from .quality import calculate_quality_score, is_content_length_valid_for_approval, get_length_validation_error
from .state_machine import validate_transition, StateTransitionError, STATUS_SORT_ORDER

logger = logging.getLogger("raas-api.crud")


def _status_sort_expression():
    """Build SQLAlchemy CASE expression for status-based sorting.

    Returns a CASE expression that maps status to sort order,
    with in_progress first and draft last.
    """
    return case(
        *[(models.Requirement.status == status, order)
          for status, order in STATUS_SORT_ORDER.items()],
        else_=99
    )


def create_requirement(
    db: Session,
    requirement: schemas.RequirementCreate,
    organization_id: UUID,
    user_id: UUID,
    project_id: Optional[UUID] = None,
) -> models.Requirement:
    """
    Create a new requirement.

    The content field is REQUIRED and must contain properly formatted markdown
    with YAML frontmatter. The content will be parsed and validated against
    the expected template structure.

    Args:
        db: Database session
        requirement: Requirement creation data (must include content)
        organization_id: Organization UUID
        user_id: User UUID (creator)
        project_id: Project UUID (required for epics, inherited from parent for others)

    Returns:
        Created requirement instance

    Raises:
        ValueError: If content is missing or invalid
    """
    # Content is now required
    if not requirement.content:
        logger.warning(f"Attempted to create requirement without content field")
        raise ValueError(
            "Content field is required. Use get_requirement_template endpoint to "
            "obtain the proper template format, then fill it in and provide the "
            "complete markdown content."
        )

    # Parse and validate markdown content
    try:
        metadata = extract_metadata(requirement.content)
    except MarkdownParseError as e:
        logger.warning(f"Invalid markdown content for {requirement.type.value}: {e}")
        raise ValueError(
            f"Invalid markdown content: {e}\n\n"
            f"Use get_requirement_template(type='{requirement.type.value}') to "
            f"obtain the proper template format."
        )

    # Validate that the type in content matches the type parameter
    if metadata["type"] != requirement.type:
        logger.warning(f"Type mismatch: parameter={requirement.type.value}, content={metadata['type'].value}")
        raise ValueError(
            f"Type mismatch: requirement type parameter is '{requirement.type.value}' "
            f"but content frontmatter specifies '{metadata['type'].value}'"
        )

    # Extract all fields from validated markdown
    title = metadata["title"]
    description = metadata["description"]
    status = metadata["status"]
    tags = metadata["tags"]
    parent_id = metadata["parent_id"]

    # Determine project_id based on requirement type
    resolved_project_id = None

    if requirement.type == models.RequirementType.EPIC:
        # Epics require explicit project_id
        if not project_id:
            logger.warning(f"Attempted to create epic without project_id")
            raise ValueError(
                "Epics require a project_id. Provide the project_id when creating an epic."
            )
        # Verify project exists and is in the same organization
        project = get_project(db, project_id)
        if not project:
            logger.warning(f"Project {project_id} not found for new epic")
            raise ValueError(f"Project {project_id} not found.")
        if project.organization_id != organization_id:
            logger.warning(f"Cross-organization project attempt: project in org {project.organization_id}, user in org {organization_id}")
            raise ValueError(
                "Project is in a different organization. "
                "All requirements must belong to the same organization."
            )
        resolved_project_id = project_id
    else:
        # Non-epic requirements inherit project_id from parent
        if not parent_id:
            logger.warning(f"Attempted to create {requirement.type.value} without parent_id in markdown frontmatter")
            raise ValueError(
                f"{requirement.type.value} requires a parent_id in the markdown frontmatter. "
                f"Ensure the YAML frontmatter includes 'parent_id: <uuid>'"
            )
        parent = get_requirement(db, parent_id)
        if not parent:
            logger.warning(f"Parent requirement {parent_id} not found for new {requirement.type.value}")
            raise ValueError(
                f"Parent requirement {parent_id} not found. "
                f"Ensure the parent_id in the markdown frontmatter references an existing requirement."
            )
        # Ensure parent is in same organization
        if parent.organization_id != organization_id:
            logger.warning(f"Cross-organization parent attempt: parent in org {parent.organization_id}, user in org {organization_id}")
            raise ValueError(
                "Parent requirement is in a different organization. "
                "All requirements must belong to the same organization."
            )
        # Inherit project_id from parent
        resolved_project_id = parent.project_id

    # Calculate content length and quality score
    content_length = len(requirement.content) if requirement.content else 0
    quality_score = calculate_quality_score(content_length, requirement.type)

    # Validate content length for status review/approved
    if status in [models.LifecycleStatus.REVIEW, models.LifecycleStatus.APPROVED]:
        if not is_content_length_valid_for_approval(content_length, requirement.type):
            error_msg = get_length_validation_error(content_length, requirement.type)
            logger.warning(f"Blocked requirement creation due to content length: {error_msg}")
            raise ValueError(error_msg)

    try:
        db_requirement = models.Requirement(
            type=requirement.type,
            parent_id=parent_id,
            title=title,
            description=description,
            content=requirement.content,
            status=status,
            tags=tags,
            content_length=content_length,
            quality_score=quality_score,
            organization_id=organization_id,
            project_id=resolved_project_id,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        db.add(db_requirement)
        db.commit()
        db.refresh(db_requirement)
        logger.debug(f"Database: Created requirement {db_requirement.id} in org {organization_id}")
    except SQLAlchemyError as e:
        logger.error(f"Database error creating requirement: {e}", exc_info=True)
        db.rollback()
        raise

    # Create history entry
    _create_history_entry(
        db=db,
        requirement_id=db_requirement.id,
        change_type=models.ChangeType.CREATED,
        new_value=f"Created {requirement.type.value}: {title}",
        user_id=user_id,
    )

    return db_requirement


def get_requirement(db: Session, requirement_id: UUID) -> Optional[models.Requirement]:
    """
    Get a requirement by UUID.

    Args:
        db: Database session
        requirement_id: Requirement UUID

    Returns:
        Requirement instance or None if not found
    """
    return db.query(models.Requirement).filter(models.Requirement.id == requirement_id).first()


def get_requirement_by_any_id(db: Session, requirement_id: str) -> Optional[models.Requirement]:
    """
    Get requirement by UUID or human-readable ID.

    Supports both formats:
    - UUID: afa92d5c-e008-44d6-b2cf-ccacd81481d6
    - Readable: RAAS-FEAT-042 (case-insensitive)

    Args:
        db: Database session
        requirement_id: Either UUID string or human-readable ID

    Returns:
        Requirement instance or None if not found
    """
    import re

    # Try UUID first (most common case, faster)
    try:
        uuid_id = UUID(requirement_id)
        return db.query(models.Requirement).filter(models.Requirement.id == uuid_id).first()
    except (ValueError, AttributeError):
        # Not a valid UUID, try human-readable ID
        pass

    # Validate human-readable ID format: PROJECT-TYPE-###
    # Pattern: 2-4 uppercase alphanumeric, dash, TYPE (EPIC|COMP|FEAT|REQ), dash, 3 digits
    if not re.match(r'^[A-Z0-9]{2,4}-(EPIC|COMP|FEAT|REQ)-[0-9]{3}$', requirement_id.upper()):
        return None

    # Lookup by human-readable ID (case-insensitive)
    return db.query(models.Requirement).filter(
        models.Requirement.human_readable_id == requirement_id.upper()
    ).first()


def get_requirements(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    type_filter: Optional[models.RequirementType] = None,
    status_filter: Optional[models.LifecycleStatus] = None,
    quality_score_filter: Optional[models.QualityScore] = None,
    parent_id: Optional[UUID] = None,
    search: Optional[str] = None,
    tags: Optional[list[str]] = None,
    organization_ids: Optional[list[UUID]] = None,
    project_id: Optional[UUID] = None,
    include_deployed: bool = False,
) -> tuple[list[models.Requirement], int]:
    """
    Get requirements with optional filtering and pagination.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        type_filter: Filter by requirement type
        status_filter: Filter by status
        quality_score_filter: Filter by quality score
        parent_id: Filter by parent ID
        search: Search in title and description
        tags: Filter by tags (AND logic - requirement must have ALL specified tags)
        organization_ids: Filter by organization IDs (for multi-user access control)
        project_id: Filter by project ID
        include_deployed: Include deployed items (default: False, deployed items excluded)

    Returns:
        Tuple of (requirements list, total count)
    """
    query = db.query(models.Requirement)

    # Apply organization filter (required for multi-user)
    if organization_ids:
        query = query.filter(models.Requirement.organization_id.in_(organization_ids))

    # Apply other filters
    if type_filter:
        query = query.filter(models.Requirement.type == type_filter)

    if status_filter:
        query = query.filter(models.Requirement.status == status_filter)

    if quality_score_filter:
        query = query.filter(models.Requirement.quality_score == quality_score_filter)

    if parent_id is not None:
        query = query.filter(models.Requirement.parent_id == parent_id)

    if project_id:
        query = query.filter(models.Requirement.project_id == project_id)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                models.Requirement.title.ilike(search_pattern),
                models.Requirement.description.ilike(search_pattern),
            )
        )

    if tags:
        # PostgreSQL array contains operator (@>) - requirement must have ALL specified tags
        # Cast the tags list to PostgreSQL text[] array type to match the column type
        query = query.filter(models.Requirement.tags.op('@>')(cast(tags, ARRAY(Text))))

    # Exclude deployed items by default unless explicitly requested
    if not include_deployed:
        query = query.filter(models.Requirement.status != models.LifecycleStatus.DEPLOYED)

    # Get total count
    total = query.count()

    # Apply pagination and ordering
    # Order by status priority (in_progress first, draft last), then by created_at
    requirements = (
        query.order_by(_status_sort_expression(), models.Requirement.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return requirements, total


def update_requirement(
    db: Session,
    requirement_id: UUID,
    requirement_update: schemas.RequirementUpdate,
    user_id: UUID,
) -> Optional[models.Requirement]:
    """
    Update a requirement.

    If content (markdown) is provided, it will be used as the source of truth
    and metadata will be extracted from it. Otherwise, individual fields will
    be updated and the markdown content will be updated accordingly.

    Args:
        db: Database session
        requirement_id: Requirement UUID
        requirement_update: Update data
        user_id: User UUID (who is making the update)

    Returns:
        Updated requirement or None if not found

    Raises:
        ValueError: If provided markdown content is invalid
    """
    db_requirement = get_requirement(db, requirement_id)
    if not db_requirement:
        return None

    # Update the updated_by_user_id
    db_requirement.updated_by_user_id = user_id

    # Track changes for history
    changes = []
    update_data = requirement_update.model_dump(exclude_unset=True)

    # If markdown content is provided, parse it and extract metadata
    if "content" in update_data and update_data["content"]:
        try:
            metadata = extract_metadata(update_data["content"])

            # Validate status transition if status is changing
            if "status" in metadata and metadata["status"] != db_requirement.status:
                try:
                    validate_transition(db_requirement.status, metadata["status"])
                except StateTransitionError as e:
                    logger.warning(f"State transition blocked: {e}")
                    # Log failed transition attempt to audit trail
                    _create_history_entry(
                        db=db,
                        requirement_id=requirement_id,
                        change_type=models.ChangeType.STATUS_CHANGED,
                        field_name="status",
                        old_value=db_requirement.status.value,
                        new_value=metadata["status"].value,
                        change_reason=f"BLOCKED: {str(e)}",
                        user_id=user_id,
                    )
                    raise ValueError(str(e))

            # Update all fields from markdown
            for field in ["title", "description", "status", "tags"]:
                if field in metadata:
                    old_value = getattr(db_requirement, field)
                    new_value = metadata[field]
                    if old_value != new_value:
                        changes.append((field, str(old_value), str(new_value)))
                        setattr(db_requirement, field, new_value)
            # Update content
            old_content = db_requirement.content or ""
            if old_content != update_data["content"]:
                changes.append(("content", "markdown updated", "markdown updated"))
                db_requirement.content = update_data["content"]
                # Recalculate content length and quality score
                db_requirement.content_length = len(update_data["content"])
                db_requirement.quality_score = calculate_quality_score(
                    db_requirement.content_length,
                    db_requirement.type
                )
        except MarkdownParseError as e:
            raise ValueError(f"Invalid markdown content: {e}")
    else:
        # Update individual fields and regenerate/update markdown
        # Validate status transition BEFORE making any changes
        if "status" in update_data and update_data["status"] != db_requirement.status:
            try:
                validate_transition(db_requirement.status, update_data["status"])
            except StateTransitionError as e:
                logger.warning(f"State transition blocked: {e}")
                # Log failed transition attempt to audit trail
                _create_history_entry(
                    db=db,
                    requirement_id=requirement_id,
                    change_type=models.ChangeType.STATUS_CHANGED,
                    field_name="status",
                    old_value=db_requirement.status.value,
                    new_value=update_data["status"].value,
                    change_reason=f"BLOCKED: {str(e)}",
                    user_id=user_id,
                )
                raise ValueError(str(e))

        fields_to_update = {}
        for field, value in update_data.items():
            if field == "content":
                continue
            old_value = getattr(db_requirement, field)
            if old_value != value:
                changes.append((field, str(old_value), str(value)))
                setattr(db_requirement, field, value)
                fields_to_update[field] = value

        # Update markdown content if fields changed
        if fields_to_update and db_requirement.content:
            try:
                db_requirement.content = merge_content(
                    db_requirement.content, fields_to_update
                )
            except MarkdownParseError:
                # If merge fails, regenerate from template
                db_requirement.content = render_template(
                    req_type=db_requirement.type,
                    title=db_requirement.title,
                    description=db_requirement.description or "",
                    parent_id=db_requirement.parent_id,
                    status=db_requirement.status.value,
                    tags=db_requirement.tags,
                )
            # Recalculate content length and quality score after content update
            db_requirement.content_length = len(db_requirement.content) if db_requirement.content else 0
            db_requirement.quality_score = calculate_quality_score(
                db_requirement.content_length,
                db_requirement.type
            )

    # Validate content length for status transitions to review/approved
    if db_requirement.status in [models.LifecycleStatus.REVIEW, models.LifecycleStatus.APPROVED]:
        if not is_content_length_valid_for_approval(db_requirement.content_length, db_requirement.type):
            error_msg = get_length_validation_error(db_requirement.content_length, db_requirement.type)
            logger.warning(f"Blocked status transition due to content length: {error_msg}")
            raise ValueError(error_msg)

    if changes:
        db.commit()
        db.refresh(db_requirement)

        # Create history entries for each change
        for field, old_val, new_val in changes:
            change_type = (
                models.ChangeType.STATUS_CHANGED
                if field == "status"
                else models.ChangeType.UPDATED
            )
            _create_history_entry(
                db=db,
                requirement_id=requirement_id,
                change_type=change_type,
                field_name=field,
                old_value=old_val,
                new_value=new_val,
                user_id=user_id,
            )

    return db_requirement


def delete_requirement(db: Session, requirement_id: UUID) -> bool:
    """
    Delete a requirement and all its children recursively.

    Args:
        db: Database session
        requirement_id: Requirement UUID

    Returns:
        True if deleted, False if not found
    """
    db_requirement = get_requirement(db, requirement_id)
    if not db_requirement:
        return False

    # Recursively delete all children first
    children = get_requirement_children(db, requirement_id)
    for child in children:
        delete_requirement(db, child.id)

    # Create history entry before deletion
    _create_history_entry(
        db=db,
        requirement_id=requirement_id,
        change_type=models.ChangeType.DELETED,
        old_value=f"{db_requirement.type.value}: {db_requirement.title}",
    )

    db.delete(db_requirement)
    db.commit()
    return True


def get_requirement_children(
    db: Session, parent_id: UUID
) -> list[models.Requirement]:
    """
    Get all children of a requirement.

    Args:
        db: Database session
        parent_id: Parent requirement UUID

    Returns:
        List of child requirements
    """
    return (
        db.query(models.Requirement)
        .filter(models.Requirement.parent_id == parent_id)
        .order_by(_status_sort_expression(), models.Requirement.created_at.desc())
        .all()
    )


def get_requirement_history(
    db: Session, requirement_id: UUID, limit: int = 50
) -> list[models.RequirementHistory]:
    """
    Get history for a requirement.

    Args:
        db: Database session
        requirement_id: Requirement UUID
        limit: Maximum number of history entries

    Returns:
        List of history entries
    """
    return (
        db.query(models.RequirementHistory)
        .filter(models.RequirementHistory.requirement_id == requirement_id)
        .order_by(models.RequirementHistory.changed_at.desc())
        .limit(limit)
        .all()
    )


def _create_history_entry(
    db: Session,
    requirement_id: UUID,
    change_type: models.ChangeType,
    field_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    change_reason: Optional[str] = None,
    user_id: Optional[UUID] = None,
) -> None:
    """Create a history entry for a requirement change."""
    history_entry = models.RequirementHistory(
        requirement_id=requirement_id,
        change_type=change_type,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        change_reason=change_reason,
        changed_by_user_id=user_id,
    )
    db.add(history_entry)
    db.commit()


# ============================================================================
# Organization CRUD Operations
# ============================================================================

def create_organization(
    db: Session,
    name: str,
    slug: str,
    settings: Optional[dict] = None,
) -> models.Organization:
    """
    Create a new organization.

    Args:
        db: Database session
        name: Organization name
        slug: URL-friendly slug (lowercase, alphanumeric, hyphens)
        settings: Optional JSON settings

    Returns:
        Created organization instance
    """
    db_org = models.Organization(
        name=name,
        slug=slug,
        settings=settings or {},
    )
    db.add(db_org)
    db.commit()
    db.refresh(db_org)
    logger.debug(f"Created organization {db_org.id} ({db_org.slug})")
    return db_org


def get_organization(db: Session, organization_id: UUID) -> Optional[models.Organization]:
    """
    Get an organization by ID.

    Args:
        db: Database session
        organization_id: Organization UUID

    Returns:
        Organization instance or None if not found
    """
    return db.query(models.Organization).filter(models.Organization.id == organization_id).first()


def get_organization_by_slug(db: Session, slug: str) -> Optional[models.Organization]:
    """
    Get an organization by slug.

    Args:
        db: Database session
        slug: Organization slug

    Returns:
        Organization instance or None if not found
    """
    return db.query(models.Organization).filter(models.Organization.slug == slug).first()


def get_organizations(
    db: Session,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[models.Organization], int]:
    """
    Get all organizations with pagination.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        Tuple of (organizations list, total count)
    """
    query = db.query(models.Organization)
    total = query.count()
    organizations = (
        query.order_by(models.Organization.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return organizations, total


def update_organization(
    db: Session,
    organization_id: UUID,
    name: Optional[str] = None,
    settings: Optional[dict] = None,
) -> Optional[models.Organization]:
    """
    Update an organization.

    Args:
        db: Database session
        organization_id: Organization UUID
        name: Optional new name
        settings: Optional new settings (replaces existing)

    Returns:
        Updated organization or None if not found
    """
    db_org = get_organization(db, organization_id)
    if not db_org:
        return None

    if name is not None:
        db_org.name = name
    if settings is not None:
        db_org.settings = settings

    db.commit()
    db.refresh(db_org)
    logger.debug(f"Updated organization {organization_id}")
    return db_org


def delete_organization(db: Session, organization_id: UUID) -> bool:
    """
    Delete an organization and all its data (cascading delete).

    Args:
        db: Database session
        organization_id: Organization UUID

    Returns:
        True if deleted, False if not found
    """
    db_org = get_organization(db, organization_id)
    if not db_org:
        return False

    db.delete(db_org)
    db.commit()
    logger.debug(f"Deleted organization {organization_id}")
    return True


# ============================================================================
# Organization Member CRUD Operations
# ============================================================================

def add_organization_member(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
    role: models.MemberRole = models.MemberRole.MEMBER,
) -> models.OrganizationMember:
    """
    Add a user to an organization with a specific role.

    Args:
        db: Database session
        organization_id: Organization UUID
        user_id: User UUID
        role: Organization role (owner, admin, member, viewer)

    Returns:
        Created organization member instance

    Raises:
        ValueError: If member already exists
    """
    # Check if already a member
    existing = (
        db.query(models.OrganizationMember)
        .filter(
            and_(
                models.OrganizationMember.organization_id == organization_id,
                models.OrganizationMember.user_id == user_id,
            )
        )
        .first()
    )
    if existing:
        raise ValueError("User is already a member of this organization")

    db_member = models.OrganizationMember(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
    )
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    logger.debug(f"Added user {user_id} to organization {organization_id} with role {role.value}")
    return db_member


def get_organization_members(
    db: Session,
    organization_id: UUID,
) -> list[models.OrganizationMember]:
    """
    Get all members of an organization.

    Args:
        db: Database session
        organization_id: Organization UUID

    Returns:
        List of organization members
    """
    return (
        db.query(models.OrganizationMember)
        .filter(models.OrganizationMember.organization_id == organization_id)
        .order_by(models.OrganizationMember.joined_at)
        .all()
    )


def update_organization_member_role(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
    role: models.MemberRole,
) -> Optional[models.OrganizationMember]:
    """
    Update an organization member's role.

    Args:
        db: Database session
        organization_id: Organization UUID
        user_id: User UUID
        role: New organization role

    Returns:
        Updated organization member or None if not found
    """
    db_member = (
        db.query(models.OrganizationMember)
        .filter(
            and_(
                models.OrganizationMember.organization_id == organization_id,
                models.OrganizationMember.user_id == user_id,
            )
        )
        .first()
    )
    if not db_member:
        return None

    db_member.role = role
    db.commit()
    db.refresh(db_member)
    logger.debug(f"Updated user {user_id} role in organization {organization_id} to {role.value}")
    return db_member


def remove_organization_member(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
) -> bool:
    """
    Remove a user from an organization.

    Args:
        db: Database session
        organization_id: Organization UUID
        user_id: User UUID

    Returns:
        True if removed, False if not found
    """
    db_member = (
        db.query(models.OrganizationMember)
        .filter(
            and_(
                models.OrganizationMember.organization_id == organization_id,
                models.OrganizationMember.user_id == user_id,
            )
        )
        .first()
    )
    if not db_member:
        return False

    db.delete(db_member)
    db.commit()
    logger.debug(f"Removed user {user_id} from organization {organization_id}")
    return True


# ============================================================================
# Project CRUD Operations
# ============================================================================

def create_project(
    db: Session,
    organization_id: UUID,
    name: str,
    slug: str,
    description: Optional[str] = None,
    visibility: models.ProjectVisibility = models.ProjectVisibility.PUBLIC,
    status: models.ProjectStatus = models.ProjectStatus.ACTIVE,
    value_statement: Optional[str] = None,
    project_type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    settings: Optional[dict] = None,
    user_id: Optional[UUID] = None,
) -> models.Project:
    """
    Create a new project.

    Args:
        db: Database session
        organization_id: Parent organization UUID
        name: Project name
        slug: 3-4 uppercase alphanumeric characters (unique within org)
        description: Optional description
        visibility: Project visibility (public or private)
        status: Project status
        value_statement: Optional value statement
        project_type: Optional project type
        tags: Optional list of tags
        settings: Optional JSON settings
        user_id: Optional user ID (creator)

    Returns:
        Created project instance
    """
    db_project = models.Project(
        organization_id=organization_id,
        name=name,
        slug=slug,
        description=description,
        visibility=visibility,
        status=status,
        value_statement=value_statement,
        project_type=project_type,
        tags=tags or [],
        settings=settings or {},
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    logger.debug(f"Created project {db_project.id} ({db_project.slug}) in org {organization_id}")
    return db_project


def get_project(db: Session, project_id: UUID) -> Optional[models.Project]:
    """
    Get a project by ID.

    Args:
        db: Database session
        project_id: Project UUID

    Returns:
        Project instance or None if not found
    """
    return db.query(models.Project).filter(models.Project.id == project_id).first()


def get_project_by_slug(
    db: Session, organization_id: UUID, slug: str
) -> Optional[models.Project]:
    """
    Get a project by organization and slug.

    Args:
        db: Database session
        organization_id: Organization UUID
        slug: Project slug

    Returns:
        Project instance or None if not found
    """
    return (
        db.query(models.Project)
        .filter(
            and_(
                models.Project.organization_id == organization_id,
                models.Project.slug == slug,
            )
        )
        .first()
    )


def get_projects(
    db: Session,
    organization_id: Optional[UUID] = None,
    status_filter: Optional[models.ProjectStatus] = None,
    visibility_filter: Optional[models.ProjectVisibility] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[models.Project], int]:
    """
    Get projects with optional filtering and pagination.

    Args:
        db: Database session
        organization_id: Optional organization UUID filter
        status_filter: Optional status filter
        visibility_filter: Optional visibility filter
        search: Optional search in name and description
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        Tuple of (projects list, total count)
    """
    query = db.query(models.Project)

    if organization_id:
        query = query.filter(models.Project.organization_id == organization_id)

    if status_filter:
        query = query.filter(models.Project.status == status_filter)

    if visibility_filter:
        query = query.filter(models.Project.visibility == visibility_filter)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                models.Project.name.ilike(search_pattern),
                models.Project.description.ilike(search_pattern),
            )
        )

    total = query.count()
    projects = (
        query.order_by(models.Project.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return projects, total


def update_project(
    db: Session,
    project_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    visibility: Optional[models.ProjectVisibility] = None,
    status: Optional[models.ProjectStatus] = None,
    value_statement: Optional[str] = None,
    project_type: Optional[str] = None,
    tags: Optional[list[str]] = None,
    settings: Optional[dict] = None,
    user_id: Optional[UUID] = None,
) -> Optional[models.Project]:
    """
    Update a project.

    Args:
        db: Database session
        project_id: Project UUID
        name: Optional new name
        description: Optional new description
        visibility: Optional new visibility
        status: Optional new status
        value_statement: Optional new value statement
        project_type: Optional new project type
        tags: Optional new tags list
        settings: Optional new settings
        user_id: Optional user ID (who is making the update)

    Returns:
        Updated project or None if not found
    """
    db_project = get_project(db, project_id)
    if not db_project:
        return None

    if name is not None:
        db_project.name = name
    if description is not None:
        db_project.description = description
    if visibility is not None:
        db_project.visibility = visibility
    if status is not None:
        db_project.status = status
    if value_statement is not None:
        db_project.value_statement = value_statement
    if project_type is not None:
        db_project.project_type = project_type
    if tags is not None:
        db_project.tags = tags
    if settings is not None:
        db_project.settings = settings
    if user_id is not None:
        db_project.updated_by_user_id = user_id

    db.commit()
    db.refresh(db_project)
    logger.debug(f"Updated project {project_id}")
    return db_project


def delete_project(db: Session, project_id: UUID) -> bool:
    """
    Delete a project and all its requirements (cascading delete).

    Args:
        db: Database session
        project_id: Project UUID

    Returns:
        True if deleted, False if not found
    """
    db_project = get_project(db, project_id)
    if not db_project:
        return False

    db.delete(db_project)
    db.commit()
    logger.debug(f"Deleted project {project_id}")
    return True


def add_project_member(
    db: Session,
    project_id: UUID,
    user_id: UUID,
    role: models.ProjectRole = models.ProjectRole.EDITOR,
) -> models.ProjectMember:
    """
    Add a user to a project with a specific role.

    Args:
        db: Database session
        project_id: Project UUID
        user_id: User UUID
        role: Project role (admin, editor, viewer)

    Returns:
        Created project member instance

    Raises:
        ValueError: If member already exists
    """
    # Check if already a member
    existing = (
        db.query(models.ProjectMember)
        .filter(
            and_(
                models.ProjectMember.project_id == project_id,
                models.ProjectMember.user_id == user_id,
            )
        )
        .first()
    )
    if existing:
        raise ValueError("User is already a member of this project")

    db_member = models.ProjectMember(
        project_id=project_id,
        user_id=user_id,
        role=role,
    )
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    logger.debug(f"Added user {user_id} to project {project_id} with role {role.value}")
    return db_member


def update_project_member_role(
    db: Session,
    project_id: UUID,
    user_id: UUID,
    role: models.ProjectRole,
) -> Optional[models.ProjectMember]:
    """
    Update a project member's role.

    Args:
        db: Database session
        project_id: Project UUID
        user_id: User UUID
        role: New project role

    Returns:
        Updated project member or None if not found
    """
    db_member = (
        db.query(models.ProjectMember)
        .filter(
            and_(
                models.ProjectMember.project_id == project_id,
                models.ProjectMember.user_id == user_id,
            )
        )
        .first()
    )
    if not db_member:
        return None

    db_member.role = role
    db.commit()
    db.refresh(db_member)
    logger.debug(f"Updated user {user_id} role in project {project_id} to {role.value}")
    return db_member


def remove_project_member(
    db: Session,
    project_id: UUID,
    user_id: UUID,
) -> bool:
    """
    Remove a user from a project.

    Args:
        db: Database session
        project_id: Project UUID
        user_id: User UUID

    Returns:
        True if removed, False if not found
    """
    db_member = (
        db.query(models.ProjectMember)
        .filter(
            and_(
                models.ProjectMember.project_id == project_id,
                models.ProjectMember.user_id == user_id,
            )
        )
        .first()
    )
    if not db_member:
        return False

    db.delete(db_member)
    db.commit()
    logger.debug(f"Removed user {user_id} from project {project_id}")
    return True


def get_project_members(
    db: Session,
    project_id: UUID,
) -> list[models.ProjectMember]:
    """
    Get all members of a project.

    Args:
        db: Database session
        project_id: Project UUID

    Returns:
        List of project members
    """
    return (
        db.query(models.ProjectMember)
        .filter(models.ProjectMember.project_id == project_id)
        .order_by(models.ProjectMember.joined_at)
        .all()
    )


# ============================================================================
# User CRUD Operations
# ============================================================================

def get_user_by_id(
    db: Session,
    user_id: UUID,
) -> Optional[models.User]:
    """
    Get a user by ID.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        User if found, None otherwise
    """
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(
    db: Session,
    email: str,
) -> Optional[models.User]:
    """
    Get a user by email address.

    Args:
        db: Database session
        email: Email address (case-insensitive)

    Returns:
        User if found, None otherwise
    """
    return db.query(models.User).filter(models.User.email.ilike(email)).first()


def search_users(
    db: Session,
    organization_id: Optional[UUID] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[models.User], int]:
    """
    Search users with optional filtering.

    Args:
        db: Database session
        organization_id: Optional organization UUID to filter by membership
        search: Optional search term (searches email and full_name)
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        Tuple of (users list, total count)
    """
    query = db.query(models.User).filter(models.User.is_active == True)

    # Filter by organization membership if specified
    if organization_id:
        query = query.join(models.OrganizationMember).filter(
            models.OrganizationMember.organization_id == organization_id
        )

    # Search by email or name if specified
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.User.email.ilike(search_term),
                models.User.full_name.ilike(search_term),
            )
        )

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    users = query.order_by(models.User.email).offset(skip).limit(limit).all()

    return users, total


def list_users(
    db: Session,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[models.User], int]:
    """
    List all active users with pagination.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        Tuple of (users list, total count)
    """
    query = db.query(models.User).filter(models.User.is_active == True)

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    users = query.order_by(models.User.email).offset(skip).limit(limit).all()

    return users, total
