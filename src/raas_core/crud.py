"""CRUD operations for requirements."""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, and_, cast, case, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from . import models, schemas
from .markdown_utils import (
    render_template,
    extract_metadata,
    merge_content,
    strip_system_fields_from_frontmatter,
    inject_database_state,
    MarkdownParseError
)
from .quality import calculate_quality_score, is_content_length_valid_for_approval, get_length_validation_error
from .state_machine import validate_transition, StateTransitionError, STATUS_SORT_ORDER
from .dependencies import (
    validate_dependencies,
    can_transition_to_deployed,
    CircularDependencyError,
)
from .hierarchy_validation import validate_parent_type, HierarchyValidationError
from .permissions import (
    can_create_requirement,
    can_update_requirement,
    can_delete_requirement,
    PermissionDeniedError,
)
from .persona_auth import (
    Persona,
    validate_persona_authorization,
    PersonaAuthorizationError,
    validate_content_edit_authorization,
    ContentEditAuthorizationError,
)
from .versioning import (
    compute_content_hash,
    create_requirement_version,
    update_current_version_pointer,
    should_regress_to_draft,
    content_has_changed,
)

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
    director_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
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
        director_id: BUG-003 - Human user who authorized the change
        actor_id: BUG-003 - Agent account that executed the change (if applicable)

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
    depends_on = metadata.get("depends_on", [])
    adheres_to = metadata.get("adheres_to", [])

    # Validate parent-child type relationship (Epic > Component > Feature > Requirement)
    try:
        validate_parent_type(db, requirement.type, parent_id)
    except HierarchyValidationError as e:
        # Return clear, actionable error message for hierarchy violations
        logger.warning(f"Hierarchy validation failed: {e.message}")
        raise ValueError(e.message)

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

    # Check permissions (RAAS-FEAT-048: Permission Validation & Enforcement)
    if user_id:  # Only check permissions if user_id is provided (not solo mode)
        try:
            can_create_requirement(db, user_id, resolved_project_id)
        except PermissionDeniedError as e:
            logger.warning(f"Permission denied for user {user_id} creating requirement: {e.message}")
            raise ValueError(e.message)

    # Strip system-managed fields from frontmatter before storage
    # This prevents desync when database state changes (e.g., status transitions)
    cleaned_content = strip_system_fields_from_frontmatter(requirement.content)

    # Calculate content length and quality score
    content_length = len(cleaned_content) if cleaned_content else 0
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
            content=cleaned_content,
            status=status,
            tags=tags,
            adheres_to=adheres_to,
            content_length=content_length,
            quality_score=quality_score,
            organization_id=organization_id,
            project_id=resolved_project_id,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        db.add(db_requirement)
        db.flush()  # Flush to get the ID before validating dependencies and guardrails

        # Validate and store dependencies
        if depends_on:
            is_valid, error_msg, warnings = validate_dependencies(
                db, db_requirement.id, depends_on, resolved_project_id
            )
            if not is_valid:
                logger.warning(f"Dependency validation failed: {error_msg}")
                db.rollback()
                raise ValueError(f"Invalid dependencies: {error_msg}")

            # Log priority inversion warnings
            for warning in warnings:
                logger.warning(
                    f"Priority inversion: P{warning['requirement_priority']} requirement "
                    f"depends on P{warning['dependency_priority']} requirement"
                )

            # Store dependencies
            for dep_id in depends_on:
                db.execute(
                    models.requirement_dependencies.insert().values(
                        requirement_id=db_requirement.id,
                        depends_on_id=dep_id
                    )
                )

        # Validate guardrail references
        if adheres_to:
            for guardrail_id in adheres_to:
                guardrail = get_guardrail(db, guardrail_id, organization_id)
                if not guardrail:
                    logger.warning(f"Invalid guardrail reference: {guardrail_id}")
                    db.rollback()
                    raise ValueError(f"Invalid guardrail reference '{guardrail_id}': guardrail not found or not in same organization")

        db.commit()
        db.refresh(db_requirement)
        logger.debug(f"Database: Created requirement {db_requirement.id} in org {organization_id}")
    except SQLAlchemyError as e:
        logger.error(f"Database error creating requirement: {e}", exc_info=True)
        db.rollback()
        raise

    # CR-002: Create initial version (v1) for new requirements
    if cleaned_content:
        create_requirement_version(
            db=db,
            requirement=db_requirement,
            content=cleaned_content,
            user_id=user_id,
            change_reason="Initial creation",
        )
        db.commit()
        logger.debug(f"Created initial version v1 for requirement {db_requirement.id}")

    # Create history entry (BUG-003: include director/actor for audit trail)
    _create_history_entry(
        db=db,
        requirement_id=db_requirement.id,
        change_type=models.ChangeType.CREATED,
        new_value=f"Created {requirement.type.value}: {title}",
        user_id=user_id,
        director_id=director_id,
        actor_id=actor_id,
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
    # Pattern: 2-10 uppercase alphanumeric, dash, TYPE (EPIC|COMP|FEAT|REQ), dash, 3 digits
    if not re.match(r'^[A-Z0-9]{2,10}-(EPIC|COMP|FEAT|REQ)-[0-9]{3}$', requirement_id.upper()):
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
    include_deprecated: bool = False,
    ready_to_implement: Optional[bool] = None,
    blocked_by: Optional[UUID] = None,
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
        include_deprecated: Include deprecated items (default: False, deprecated items excluded)
        ready_to_implement: Filter for requirements with all dependencies code-complete (True) or with unmet dependencies (False). Code-complete = implemented, validated, or deployed.
        blocked_by: Filter for requirements that depend on the specified requirement ID

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

    # CR-004 Phase 4: DEPLOYED status removed. Filter by deployed_version_id instead.
    # include_deployed=False excludes requirements that have been deployed to production
    if not include_deployed:
        query = query.filter(models.Requirement.deployed_version_id.is_(None))

    # Exclude deprecated items by default unless explicitly requested (RAAS-FEAT-080)
    if not include_deprecated:
        query = query.filter(models.Requirement.status != models.LifecycleStatus.DEPRECATED)

    # Filter by blocked_by (requirements that depend on a specific requirement)
    if blocked_by:
        query = query.join(
            models.requirement_dependencies,
            models.Requirement.id == models.requirement_dependencies.c.requirement_id
        ).filter(models.requirement_dependencies.c.depends_on_id == blocked_by)

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

    # Post-filter for ready_to_implement (requires checking each requirement's dependencies)
    # This is less efficient but necessary as it requires checking related records
    if ready_to_implement is not None:
        filtered_requirements = []
        for req in requirements:
            # Get dependencies for this requirement
            deps = (
                db.query(models.Requirement)
                .join(
                    models.requirement_dependencies,
                    models.Requirement.id == models.requirement_dependencies.c.depends_on_id
                )
                .filter(models.requirement_dependencies.c.requirement_id == req.id)
                .all()
            )

            # Check if ready to implement (all dependencies are code-complete or no dependencies)
            # CR-004 Phase 4: Code-complete = deployed_version_id is set
            is_ready = not deps or all(dep.deployed_version_id is not None for dep in deps)

            if ready_to_implement == is_ready:
                filtered_requirements.append(req)

        requirements = filtered_requirements
        # Note: total count is not adjusted for ready_to_implement filter as it's applied post-pagination

    return requirements, total


def update_requirement(
    db: Session,
    requirement_id: UUID,
    requirement_update: schemas.RequirementUpdate,
    user_id: UUID,
    persona: Optional[Persona] = None,
    director_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
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
        persona: Declared workflow persona for authorization (optional for now)
        director_id: CR-002 (RAAS-FEAT-063) - Human user who authorized the change
        actor_id: CR-002 (RAAS-FEAT-063) - Agent account that executed the change

    Returns:
        Updated requirement or None if not found

    Raises:
        ValueError: If provided markdown content is invalid or persona not authorized
    """
    db_requirement = get_requirement(db, requirement_id)
    if not db_requirement:
        return None

    # Check permissions (RAAS-FEAT-048: Permission Validation & Enforcement)
    if user_id:  # Only check permissions if user_id is provided (not solo mode)
        try:
            can_update_requirement(db, user_id, requirement_id)
        except PermissionDeniedError as e:
            logger.warning(f"Permission denied for user {user_id} updating requirement {requirement_id}: {e.message}")
            raise ValueError(e.message)

    # Update the updated_by_user_id
    db_requirement.updated_by_user_id = user_id

    # Track changes for history
    changes = []
    update_data = requirement_update.model_dump(exclude_unset=True)
    new_dependencies = None  # Track dependency updates
    new_adheres_to = None  # Track guardrail reference updates

    # If markdown content is provided, parse it and extract metadata
    if "content" in update_data and update_data["content"]:
        # BUG-001 Fix 2: Check if content is actually changing (not just status via frontmatter)
        # Only enforce content-edit authorization if the actual spec content is being modified
        # BUG-004: Strip system fields from both old and new before comparing
        # This ensures tag/status changes don't incorrectly trigger content-edit authorization
        new_content = update_data["content"]
        try:
            cleaned_new = strip_system_fields_from_frontmatter(new_content)
            old_content = db_requirement.content or ""
            cleaned_old = strip_system_fields_from_frontmatter(old_content) if old_content else ""
        except MarkdownParseError:
            # If parsing fails, fall back to raw comparison
            cleaned_new = new_content
            cleaned_old = db_requirement.content or ""
        if content_has_changed(cleaned_old, cleaned_new):
            # Content is actually changing - check persona authorization
            # Note: require_persona=False for backward compatibility during rollout
            # TODO: Change to require_persona=True once all clients are updated
            try:
                validate_content_edit_authorization(persona, require_persona=False)
            except ContentEditAuthorizationError as e:
                logger.warning(f"Content edit authorization denied: {e}")
                raise ValueError(str(e))

        try:
            metadata = extract_metadata(update_data["content"])

            # Extract dependencies from metadata
            if "depends_on" in metadata:
                new_dependencies = metadata["depends_on"]

            # Extract guardrail references from metadata
            if "adheres_to" in metadata:
                new_adheres_to = metadata["adheres_to"]

            # Validate parent_id change (if parent_id is in metadata and is changing)
            if "parent_id" in metadata and metadata["parent_id"] != db_requirement.parent_id:
                try:
                    validate_parent_type(db, db_requirement.type, metadata["parent_id"])
                except HierarchyValidationError as e:
                    logger.warning(f"Hierarchy validation failed on update: {e.message}")
                    raise ValueError(e.message)
                # Track parent_id change
                changes.append(("parent_id", str(db_requirement.parent_id), str(metadata["parent_id"])))
                db_requirement.parent_id = metadata["parent_id"]

            # Validate status transition if status is changing
            if "status" in metadata and metadata["status"] != db_requirement.status:
                # CR-004 Phase 4: DEPLOYED status removed from requirements.
                # Deployment tracking is via deployed_version_id, not status.
                # State machine will reject any invalid status transitions.

                try:
                    validate_transition(db_requirement.status, metadata["status"])
                except StateTransitionError as e:
                    logger.warning(f"State transition blocked: {e}")
                    # Log failed transition attempt to audit trail (CR-002: director/actor)
                    _create_history_entry(
                        db=db,
                        requirement_id=requirement_id,
                        change_type=models.ChangeType.STATUS_CHANGED,
                        field_name="status",
                        old_value=db_requirement.status.value,
                        new_value=metadata["status"].value,
                        change_reason=f"BLOCKED: {str(e)}",
                        user_id=user_id,
                        director_id=director_id,
                        actor_id=actor_id,
                    )
                    raise ValueError(str(e))

                # Validate persona authorization for the transition (after state machine validation)
                # Get organization settings for potential custom persona matrix
                org = get_organization(db, db_requirement.organization_id) if db_requirement.organization_id else None
                org_settings = org.settings if org else None
                try:
                    validate_persona_authorization(
                        persona=persona,
                        from_status=db_requirement.status,
                        to_status=metadata["status"],
                        org_settings=org_settings,
                        require_persona=True,  # Strict enforcement enabled
                    )
                except PersonaAuthorizationError as e:
                    logger.warning(f"Persona authorization blocked: {e}")
                    # Log failed transition attempt to audit trail (CR-002: director/actor)
                    persona_str = persona.value if persona else "none"
                    _create_history_entry(
                        db=db,
                        requirement_id=requirement_id,
                        change_type=models.ChangeType.STATUS_CHANGED,
                        field_name="status",
                        old_value=db_requirement.status.value,
                        new_value=metadata["status"].value,
                        change_reason=f"BLOCKED (persona={persona_str}): {str(e)}",
                        user_id=user_id,
                        director_id=director_id,
                        actor_id=actor_id,
                    )
                    raise ValueError(str(e))

                # CR-002: Update current_version_id when transitioning to approved
                if metadata["status"] == models.LifecycleStatus.APPROVED:
                    old_version_id = db_requirement.current_version_id
                    version = update_current_version_pointer(db, db_requirement)
                    if version:
                        logger.info(
                            f"Updated current_version_id for {db_requirement.human_readable_id or db_requirement.id} "
                            f"to version {version.version_number} on approval"
                        )
                        # CR-002 (RAAS-FEAT-104): Audit log for version pointer update
                        _create_history_entry(
                            db=db,
                            requirement_id=requirement_id,
                            change_type=models.ChangeType.VERSION_POINTER_CHANGED,
                            field_name="current_version_id",
                            old_value=str(old_version_id) if old_version_id else None,
                            new_value=str(version.id),
                            change_reason=f"Updated to version {version.version_number} on approval",
                            user_id=user_id,
                            director_id=director_id,
                            actor_id=actor_id,
                        )

            # Update all fields from markdown
            for field in ["title", "description", "status", "tags"]:
                if field in metadata:
                    old_value = getattr(db_requirement, field)
                    new_value = metadata[field]
                    if old_value != new_value:
                        changes.append((field, str(old_value), str(new_value)))
                        setattr(db_requirement, field, new_value)
            # Update content (strip system fields before storage)
            cleaned_content = strip_system_fields_from_frontmatter(update_data["content"])
            # BUG-004: Strip system fields from old content too before comparing
            # This ensures tag/status changes don't trigger versioning
            old_content = db_requirement.content or ""
            try:
                cleaned_old_content = strip_system_fields_from_frontmatter(old_content) if old_content else ""
            except MarkdownParseError:
                # If old content can't be parsed, use it as-is (legacy content)
                cleaned_old_content = old_content
            if content_has_changed(cleaned_old_content, cleaned_content):
                changes.append(("content", "markdown updated", "markdown updated"))

                # CR-002: Create immutable version snapshot on content change
                create_requirement_version(
                    db=db,
                    requirement=db_requirement,
                    content=cleaned_content,
                    user_id=user_id,
                    change_reason="Content update",
                )

                # CR-002: Regress status to draft if approved/review requirement content changes
                if should_regress_to_draft(db_requirement):
                    old_status = db_requirement.status
                    db_requirement.status = models.LifecycleStatus.DRAFT
                    changes.append(("status", old_status.value, models.LifecycleStatus.DRAFT.value))
                    logger.info(
                        f"Requirement {db_requirement.human_readable_id or db_requirement.id} "
                        f"regressed from {old_status.value} to draft due to content change"
                    )

                db_requirement.content = cleaned_content
                # Recalculate content length and quality score
                db_requirement.content_length = len(cleaned_content)
                db_requirement.quality_score = calculate_quality_score(
                    db_requirement.content_length,
                    db_requirement.type
                )
        except MarkdownParseError as e:
            raise ValueError(f"Invalid markdown content: {e}")
    else:
        # Update individual fields and regenerate/update markdown
        # Extract dependencies if provided directly (not through content)
        if "depends_on" in update_data:
            new_dependencies = update_data["depends_on"]

        # Extract guardrail references if provided directly (not through content)
        if "adheres_to" in update_data:
            new_adheres_to = update_data["adheres_to"]

        # Validate status transition BEFORE making any changes
        if "status" in update_data and update_data["status"] != db_requirement.status:
            # CR-004 Phase 4: DEPLOYED status removed from requirements.
            # Deployment tracking is via deployed_version_id, not status.
            # State machine will reject any invalid status transitions.

            try:
                validate_transition(db_requirement.status, update_data["status"])
            except StateTransitionError as e:
                logger.warning(f"State transition blocked: {e}")
                # Log failed transition attempt to audit trail (CR-002: director/actor)
                _create_history_entry(
                    db=db,
                    requirement_id=requirement_id,
                    change_type=models.ChangeType.STATUS_CHANGED,
                    field_name="status",
                    old_value=db_requirement.status.value,
                    new_value=update_data["status"].value,
                    change_reason=f"BLOCKED: {str(e)}",
                    user_id=user_id,
                    director_id=director_id,
                    actor_id=actor_id,
                )
                raise ValueError(str(e))

            # Validate persona authorization for the transition (after state machine validation)
            # Get organization settings for potential custom persona matrix
            org = get_organization(db, db_requirement.organization_id) if db_requirement.organization_id else None
            org_settings = org.settings if org else None
            try:
                validate_persona_authorization(
                    persona=persona,
                    from_status=db_requirement.status,
                    to_status=update_data["status"],
                    org_settings=org_settings,
                    require_persona=True,  # Strict enforcement enabled
                )
            except PersonaAuthorizationError as e:
                logger.warning(f"Persona authorization blocked: {e}")
                # Log failed transition attempt to audit trail (CR-002: director/actor)
                persona_str = persona.value if persona else "none"
                _create_history_entry(
                    db=db,
                    requirement_id=requirement_id,
                    change_type=models.ChangeType.STATUS_CHANGED,
                    field_name="status",
                    old_value=db_requirement.status.value,
                    new_value=update_data["status"].value,
                    change_reason=f"BLOCKED (persona={persona_str}): {str(e)}",
                    user_id=user_id,
                    director_id=director_id,
                    actor_id=actor_id,
                )
                raise ValueError(str(e))

            # CR-002: Update current_version_id when transitioning to approved
            if update_data["status"] == models.LifecycleStatus.APPROVED:
                old_version_id = db_requirement.current_version_id
                version = update_current_version_pointer(db, db_requirement)
                if version:
                    logger.info(
                        f"Updated current_version_id for {db_requirement.human_readable_id or db_requirement.id} "
                        f"to version {version.version_number} on approval"
                    )
                    # CR-002 (RAAS-FEAT-104): Audit log for version pointer update
                    _create_history_entry(
                        db=db,
                        requirement_id=requirement_id,
                        change_type=models.ChangeType.VERSION_POINTER_CHANGED,
                        field_name="current_version_id",
                        old_value=str(old_version_id) if old_version_id else None,
                        new_value=str(version.id),
                        change_reason=f"Updated to version {version.version_number} on approval",
                        user_id=user_id,
                        director_id=director_id,
                        actor_id=actor_id,
                    )

        fields_to_update = {}
        for field, value in update_data.items():
            if field in ["content", "depends_on"]:  # Skip content and depends_on (handled separately)
                continue
            old_value = getattr(db_requirement, field)
            if old_value != value:
                changes.append((field, str(old_value), str(value)))
                setattr(db_requirement, field, value)
                fields_to_update[field] = value

        # Update markdown content if fields changed
        if fields_to_update and db_requirement.content:
            try:
                updated_content = merge_content(
                    db_requirement.content, fields_to_update
                )
            except MarkdownParseError:
                # If merge fails, regenerate from template
                updated_content = render_template(
                    req_type=db_requirement.type,
                    title=db_requirement.title,
                    description=db_requirement.description or "",
                    parent_id=db_requirement.parent_id,
                    status=db_requirement.status.value,
                    tags=db_requirement.tags,
                )
            # Strip system fields before storage
            db_requirement.content = strip_system_fields_from_frontmatter(updated_content)
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

    # Update dependencies if provided
    if new_dependencies is not None:
        # Validate dependencies
        if new_dependencies:  # Only validate if there are dependencies
            is_valid, error_msg, warnings = validate_dependencies(
                db, requirement_id, new_dependencies, db_requirement.project_id
            )
            if not is_valid:
                logger.warning(f"Dependency validation failed: {error_msg}")
                raise ValueError(f"Invalid dependencies: {error_msg}")

            # Log priority inversion warnings
            for warning in warnings:
                logger.warning(
                    f"Priority inversion: P{warning['requirement_priority']} requirement "
                    f"depends on P{warning['dependency_priority']} requirement"
                )

        # Clear existing dependencies
        db.execute(
            models.requirement_dependencies.delete().where(
                models.requirement_dependencies.c.requirement_id == requirement_id
            )
        )

        # Add new dependencies
        for dep_id in new_dependencies:
            db.execute(
                models.requirement_dependencies.insert().values(
                    requirement_id=requirement_id,
                    depends_on_id=dep_id
                )
            )

        changes.append(("dependencies", "dependencies updated", "dependencies updated"))

    # Validate and update guardrail references if provided
    if new_adheres_to is not None:
        # Validate guardrail references
        if new_adheres_to:  # Only validate if there are references
            for guardrail_id in new_adheres_to:
                guardrail = get_guardrail(db, guardrail_id, db_requirement.organization_id)
                if not guardrail:
                    logger.warning(f"Invalid guardrail reference: {guardrail_id}")
                    raise ValueError(f"Invalid guardrail reference '{guardrail_id}': guardrail not found or not in same organization")

        # Update adheres_to field
        db_requirement.adheres_to = new_adheres_to
        changes.append(("adheres_to", "guardrail references updated", "guardrail references updated"))

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
            # Include persona in status change audit logs
            change_reason = None
            if field == "status" and persona:
                change_reason = f"persona={persona.value}"
            _create_history_entry(
                db=db,
                requirement_id=requirement_id,
                change_type=change_type,
                field_name=field,
                old_value=old_val,
                new_value=new_val,
                change_reason=change_reason,
                user_id=user_id,
                director_id=director_id,  # BUG-002: director/actor audit trail
                actor_id=actor_id,
            )

    return db_requirement


def delete_requirement(db: Session, requirement_id: UUID, user_id: Optional[UUID] = None) -> bool:
    """
    Delete a requirement and all its children recursively.

    Checks for dependents and either fails with error or clears dependencies.

    Args:
        db: Database session
        requirement_id: Requirement UUID
        user_id: User UUID (who is deleting)

    Returns:
        True if deleted, False if not found

    Raises:
        ValueError: If other requirements depend on this one or permission denied
    """
    db_requirement = get_requirement(db, requirement_id)
    if not db_requirement:
        return False

    # Check permissions (RAAS-FEAT-048: Permission Validation & Enforcement)
    if user_id:  # Only check permissions if user_id is provided (not solo mode)
        try:
            can_delete_requirement(db, user_id, requirement_id)
        except PermissionDeniedError as e:
            logger.warning(f"Permission denied for user {user_id} deleting requirement {requirement_id}: {e.message}")
            raise ValueError(e.message)

    # Check if other requirements depend on this one
    dependents = (
        db.query(models.Requirement)
        .join(
            models.requirement_dependencies,
            models.Requirement.id == models.requirement_dependencies.c.requirement_id
        )
        .filter(models.requirement_dependencies.c.depends_on_id == requirement_id)
        .all()
    )

    if dependents:
        # Block deletion with clear error message
        dependent_list = ", ".join(
            f"{dep.human_readable_id or str(dep.id)}" for dep in dependents
        )
        raise ValueError(
            f"Cannot delete requirement: the following requirements depend on it: {dependent_list}. "
            f"Remove these dependencies first or delete the dependent requirements."
        )

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

    # Dependencies will be automatically deleted by CASCADE constraint
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
    director_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
) -> None:
    """Create a history entry for a requirement change.

    CR-002 (RAAS-FEAT-063): Supports director/actor tracking for accountability.

    Args:
        db: Database session
        requirement_id: UUID of the requirement
        change_type: Type of change (created, updated, status_changed, etc.)
        field_name: Name of the field that changed
        old_value: Previous value
        new_value: New value
        change_reason: Human-readable reason for the change
        user_id: Legacy field - user who made the change (kept for backwards compatibility)
        director_id: Human user who authorized the change
        actor_id: Agent account that executed the change (if applicable)
    """
    history_entry = models.RequirementHistory(
        requirement_id=requirement_id,
        change_type=change_type,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        change_reason=change_reason,
        changed_by_user_id=user_id,
        director_id=director_id,
        actor_id=actor_id,
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
    user_id: Optional[UUID] = None,
) -> tuple[list[models.Organization], int]:
    """
    Get organizations with pagination, optionally filtered by user membership.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        user_id: If provided, only return organizations where user is a member

    Returns:
        Tuple of (organizations list, total count)
    """
    query = db.query(models.Organization)

    # Filter by user membership if user_id provided
    if user_id:
        query = query.join(models.OrganizationMember).filter(
            models.OrganizationMember.user_id == user_id
        )

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


def get_user_organization_ids(
    db: Session,
    user_id: UUID,
) -> list[UUID]:
    """
    Get list of organization IDs where user is a member.

    Used for filtering requirements/projects by organization membership.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        List of organization UUIDs where user is a member
    """
    memberships = (
        db.query(models.OrganizationMember.organization_id)
        .filter(models.OrganizationMember.user_id == user_id)
        .all()
    )
    return [m.organization_id for m in memberships]


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
    user_id: Optional[UUID] = None,
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
        user_id: If provided, only return projects from orgs where user is a member

    Returns:
        Tuple of (projects list, total count)
    """
    query = db.query(models.Project)

    # Filter by user's organization membership if user_id provided
    if user_id:
        query = query.join(models.Organization).join(models.OrganizationMember).filter(
            models.OrganizationMember.user_id == user_id
        )

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
    organization_id: Optional[UUID] = None,
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
        organization_id: Optional new organization ID (to move project)
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
    if organization_id is not None:
        db_project.organization_id = organization_id
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


def users_share_organization(
    db: Session,
    user_id_1: UUID,
    user_id_2: UUID,
) -> bool:
    """
    Check if two users share at least one organization.

    Args:
        db: Database session
        user_id_1: First user's UUID
        user_id_2: Second user's UUID

    Returns:
        True if users share at least one organization
    """
    from sqlalchemy.orm import aliased

    # Create aliases for the OrganizationMember table
    om1 = aliased(models.OrganizationMember)
    om2 = aliased(models.OrganizationMember)

    # Check if there's any organization where both users are members
    shared = (
        db.query(om1)
        .join(om2, om1.organization_id == om2.organization_id)
        .filter(om1.user_id == user_id_1, om2.user_id == user_id_2)
        .first()
    )

    return shared is not None


def search_users(
    db: Session,
    organization_id: Optional[UUID] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    requesting_user_id: Optional[UUID] = None,
) -> tuple[list[models.User], int]:
    """
    Search users with optional filtering.

    Args:
        db: Database session
        organization_id: Optional organization UUID to filter by membership
        search: Optional search term (searches email and full_name)
        skip: Number of records to skip
        limit: Maximum number of records to return
        requesting_user_id: If provided, only return users in shared organizations

    Returns:
        Tuple of (users list, total count)
    """
    query = db.query(models.User).filter(models.User.is_active == True)

    # In team mode, filter to users in shared organizations
    if requesting_user_id:
        # Get all org IDs the requesting user is a member of
        user_org_ids = (
            db.query(models.OrganizationMember.organization_id)
            .filter(models.OrganizationMember.user_id == requesting_user_id)
            .subquery()
        )
        # Filter to users who are members of any of those orgs
        query = query.join(models.OrganizationMember).filter(
            models.OrganizationMember.organization_id.in_(user_org_ids)
        ).distinct()

    # Filter by organization membership if specified
    if organization_id:
        if not requesting_user_id:
            query = query.join(models.OrganizationMember)
        query = query.filter(
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
    requesting_user_id: Optional[UUID] = None,
) -> tuple[list[models.User], int]:
    """
    List active users with pagination.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return
        requesting_user_id: If provided, only return users in shared organizations

    Returns:
        Tuple of (users list, total count)
    """
    query = db.query(models.User).filter(models.User.is_active == True)

    # In team mode, filter to users in shared organizations
    if requesting_user_id:
        # Get all org IDs the requesting user is a member of
        user_org_ids = (
            db.query(models.OrganizationMember.organization_id)
            .filter(models.OrganizationMember.user_id == requesting_user_id)
            .subquery()
        )
        # Filter to users who are members of any of those orgs
        query = query.join(models.OrganizationMember).filter(
            models.OrganizationMember.organization_id.in_(user_org_ids)
        ).distinct()

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    users = query.order_by(models.User.email).offset(skip).limit(limit).all()

    return users, total


# ============================================================================
# Guardrail CRUD Operations
# ============================================================================

def create_guardrail(
    db: Session,
    organization_id: UUID,
    content: str,
    user_id: UUID,
) -> models.Guardrail:
    """
    Create a new guardrail.

    Args:
        db: Database session
        organization_id: Organization UUID
        content: Full markdown content with YAML frontmatter
        user_id: User UUID (creator)

    Returns:
        Created guardrail instance

    Raises:
        ValueError: If content is missing or invalid
    """
    if not content:
        logger.warning("Attempted to create guardrail without content field")
        raise ValueError(
            "Content field is required. Use get_guardrail_template to "
            "obtain the proper template format, then fill it in and provide the "
            "complete markdown content."
        )

    # Parse and validate markdown content
    try:
        from .markdown_utils import parse_markdown
        parsed = parse_markdown(content)
        frontmatter = parsed["frontmatter"]
        body = parsed["body"]
    except MarkdownParseError as e:
        logger.warning(f"Invalid markdown content for guardrail: {e}")
        raise ValueError(
            f"Invalid markdown content: {e}\n\n"
            f"Use get_guardrail_template to obtain the proper template format."
        )

    # Validate type is 'guardrail'
    if frontmatter.get("type") != "guardrail":
        raise ValueError(
            f"Invalid type in content frontmatter: expected 'guardrail', got '{frontmatter.get('type')}'"
        )

    # Extract all fields from validated markdown frontmatter
    try:
        title = frontmatter["title"]
        category = frontmatter["category"]
        enforcement_level = frontmatter["enforcement_level"]
        applies_to = frontmatter["applies_to"]
    except KeyError as e:
        raise ValueError(f"Missing required field in frontmatter: {e}")

    description = frontmatter.get("description", "")
    status = frontmatter.get("status", "draft")
    tags = frontmatter.get("tags", [])

    # Validate category (must be from enum)
    try:
        category_enum = models.GuardrailCategory(category)
    except ValueError:
        valid_categories = [c.value for c in models.GuardrailCategory]
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {', '.join(valid_categories)}"
        )

    # Validate enforcement_level
    try:
        enforcement_enum = models.EnforcementLevel(enforcement_level)
    except ValueError:
        valid_levels = [l.value for l in models.EnforcementLevel]
        raise ValueError(
            f"Invalid enforcement_level '{enforcement_level}'. Must be one of: {', '.join(valid_levels)}"
        )

    # Validate status
    try:
        status_enum = models.GuardrailStatus(status)
    except ValueError:
        valid_statuses = [s.value for s in models.GuardrailStatus]
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
        )

    # Validate applies_to (must be valid requirement types)
    if not applies_to or not isinstance(applies_to, list):
        raise ValueError("applies_to must be a non-empty list of requirement types")

    valid_requirement_types = {rt.value for rt in models.RequirementType}
    invalid_types = set(applies_to) - valid_requirement_types
    if invalid_types:
        raise ValueError(
            f"Invalid requirement types in applies_to: {', '.join(invalid_types)}. "
            f"Must be one of: {', '.join(valid_requirement_types)}"
        )

    # Strip system-managed fields from frontmatter before storage
    # This prevents desync when database state changes (e.g., status transitions)
    cleaned_content = strip_system_fields_from_frontmatter(content)

    # Auto-extract description from cleaned content if not provided
    if not description:
        # Extract first paragraph after frontmatter
        content_body = cleaned_content.split("---", 2)[2] if cleaned_content.count("---") >= 2 else ""
        lines = [line.strip() for line in content_body.strip().split("\n") if line.strip() and not line.startswith("#")]
        description = lines[0][:500] if lines else ""

    # Create guardrail instance
    db_guardrail = models.Guardrail(
        organization_id=organization_id,
        title=title,
        category=category_enum,
        enforcement_level=enforcement_enum,
        applies_to=applies_to,
        status=status_enum,
        content=cleaned_content,
        description=description,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )

    db.add(db_guardrail)
    db.commit()
    db.refresh(db_guardrail)

    logger.info(f"Created guardrail {db_guardrail.human_readable_id} in org {organization_id}")
    return db_guardrail


def get_guardrail(
    db: Session,
    guardrail_id: str,
    organization_id: Optional[UUID] = None,
) -> Optional[models.Guardrail]:
    """
    Get a guardrail by UUID or human-readable ID.

    Args:
        db: Database session
        guardrail_id: UUID or human-readable ID (e.g., 'GUARD-SEC-001')
        organization_id: Optional organization UUID to scope the query

    Returns:
        Guardrail instance or None if not found
    """
    query = db.query(models.Guardrail)

    # Try UUID first, then human-readable ID
    try:
        uuid_id = UUID(guardrail_id)
        query = query.filter(models.Guardrail.id == uuid_id)
    except ValueError:
        # Not a UUID, treat as human-readable ID
        query = query.filter(models.Guardrail.human_readable_id == guardrail_id.upper())

    # Optionally scope to organization
    if organization_id:
        query = query.filter(models.Guardrail.organization_id == organization_id)

    return query.first()


def get_guardrail_template() -> str:
    """
    Get the markdown template for creating a new guardrail.

    Returns:
        Complete markdown template with YAML frontmatter and guidance

    Raises:
        FileNotFoundError: If the template file doesn't exist
    """
    from pathlib import Path

    template_path = Path(__file__).parent / "templates" / "guardrail.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Guardrail template not found: {template_path}")

    return template_path.read_text()


def update_guardrail(
    db: Session,
    guardrail_id: str,
    content: str,
    user_id: Optional[UUID] = None,
) -> models.Guardrail:
    """
    Update an existing guardrail.

    Args:
        db: Database session
        guardrail_id: UUID or human-readable ID
        content: Full markdown content with YAML frontmatter
        user_id: User UUID (updater), None for solo mode

    Returns:
        Updated guardrail instance

    Raises:
        ValueError: If guardrail not found or content is invalid
    """
    # Get existing guardrail
    db_guardrail = get_guardrail(db=db, guardrail_id=guardrail_id)
    if not db_guardrail:
        raise ValueError(f"Guardrail {guardrail_id} not found")

    # Parse and validate new markdown content
    try:
        from .markdown_utils import parse_markdown
        parsed = parse_markdown(content)
        frontmatter = parsed["frontmatter"]
        body = parsed["body"]
    except MarkdownParseError as e:
        logger.warning(f"Invalid markdown content for guardrail update: {e}")
        raise ValueError(
            f"Invalid markdown content: {e}\n\n"
            f"Use get_guardrail_template to obtain the proper template format."
        )

    # Validate type is 'guardrail'
    if frontmatter.get("type") != "guardrail":
        raise ValueError(
            f"Invalid type in content frontmatter: expected 'guardrail', got '{frontmatter.get('type')}'"
        )

    # Extract all fields from validated markdown frontmatter
    try:
        title = frontmatter["title"]
        category = frontmatter["category"]
        enforcement_level = frontmatter["enforcement_level"]
        applies_to = frontmatter["applies_to"]
    except KeyError as e:
        raise ValueError(f"Missing required field in frontmatter: {e}")

    description = frontmatter.get("description", "")
    status = frontmatter.get("status", "draft")

    # Validate category
    try:
        category_enum = models.GuardrailCategory(category)
    except ValueError:
        valid_categories = [c.value for c in models.GuardrailCategory]
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {', '.join(valid_categories)}"
        )

    # Validate enforcement_level
    try:
        enforcement_enum = models.EnforcementLevel(enforcement_level)
    except ValueError:
        valid_levels = [l.value for l in models.EnforcementLevel]
        raise ValueError(
            f"Invalid enforcement_level '{enforcement_level}'. Must be one of: {', '.join(valid_levels)}"
        )

    # Validate status
    try:
        status_enum = models.GuardrailStatus(status)
    except ValueError:
        valid_statuses = [s.value for s in models.GuardrailStatus]
        raise ValueError(
            f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
        )

    # Validate applies_to
    if not applies_to or not isinstance(applies_to, list):
        raise ValueError("applies_to must be a non-empty list of requirement types")

    valid_requirement_types = {rt.value for rt in models.RequirementType}
    invalid_types = set(applies_to) - valid_requirement_types
    if invalid_types:
        raise ValueError(
            f"Invalid requirement types in applies_to: {', '.join(invalid_types)}. "
            f"Must be one of: {', '.join(valid_requirement_types)}"
        )

    # Strip system-managed fields from frontmatter before storage
    # This prevents desync when database state changes (e.g., status transitions)
    cleaned_content = strip_system_fields_from_frontmatter(content)

    # Auto-extract description if not provided
    if not description:
        content_body = cleaned_content.split("---", 2)[2] if cleaned_content.count("---") >= 2 else ""
        lines = [line.strip() for line in content_body.strip().split("\n") if line.strip() and not line.startswith("#")]
        description = lines[0][:500] if lines else ""

    # Update guardrail fields
    db_guardrail.title = title
    db_guardrail.category = category_enum
    db_guardrail.enforcement_level = enforcement_enum
    db_guardrail.applies_to = applies_to
    db_guardrail.status = status_enum
    db_guardrail.content = cleaned_content
    db_guardrail.description = description
    db_guardrail.updated_by_user_id = user_id

    db.commit()
    db.refresh(db_guardrail)

    logger.info(f"Updated guardrail {db_guardrail.human_readable_id} by user {user_id}")
    return db_guardrail


def delete_guardrail(db: Session, guardrail_id: str) -> bool:
    """
    Delete a guardrail.

    Args:
        db: Database session
        guardrail_id: UUID or human-readable ID

    Returns:
        True if deleted, False if not found
    """
    db_guardrail = get_guardrail(db, guardrail_id)
    if not db_guardrail:
        return False

    db.delete(db_guardrail)
    db.commit()
    logger.info(f"Deleted guardrail {guardrail_id}")
    return True


def list_guardrails(
    db: Session,
    organization_id: Optional[UUID] = None,
    category: Optional[str] = None,
    enforcement_level: Optional[str] = None,
    applies_to: Optional[str] = None,
    status: Optional[str] = "active",
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    user_id: Optional[UUID] = None,
) -> tuple[list[models.Guardrail], int]:
    """
    List guardrails with filtering and pagination.

    Args:
        db: Database session
        organization_id: Filter by organization (optional)
        category: Filter by category (optional)
        enforcement_level: Filter by enforcement level (optional)
        applies_to: Filter by requirement type applicability (optional)
        status: Filter by status (defaults to 'active', use None for all statuses)
        search: Search keyword for title/content (optional)
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        user_id: If provided, only return guardrails from orgs where user is a member

    Returns:
        Tuple of (guardrails list, total count)
    """
    query = db.query(models.Guardrail)

    # Filter by user's organization membership if user_id provided
    if user_id:
        query = query.join(models.Organization).join(models.OrganizationMember).filter(
            models.OrganizationMember.user_id == user_id
        )

    # Apply filters
    if organization_id:
        query = query.filter(models.Guardrail.organization_id == organization_id)

    if category:
        query = query.filter(models.Guardrail.category == category)

    if enforcement_level:
        query = query.filter(models.Guardrail.enforcement_level == enforcement_level)

    if applies_to:
        # Filter where applies_to array contains the specified type
        query = query.filter(models.Guardrail.applies_to.contains([applies_to]))

    # Status filter (defaults to active only per REQ-040)
    if status is not None:
        query = query.filter(models.Guardrail.status == status)

    # Search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                models.Guardrail.title.ilike(search_pattern),
                models.Guardrail.content.ilike(search_pattern)
            )
        )

    # Get total count before pagination
    total = query.count()

    # Apply pagination and ordering
    guardrails = query.order_by(models.Guardrail.created_at.desc()).offset(skip).limit(limit).all()

    return guardrails, total


# ============================================================================
# Task Queue CRUD Operations (RAAS-EPIC-027, RAAS-COMP-065)
# ============================================================================


def _resolve_source_id(
    db: Session,
    source_type: Optional[str],
    source_id: Optional[str],
) -> Optional[UUID]:
    """Resolve a source_id to UUID, handling human-readable IDs.

    Args:
        db: Database session
        source_type: Type of source (elicitation_session, clarification_point, requirement, etc.)
        source_id: UUID string or human-readable ID

    Returns:
        Resolved UUID or None if not found/not provided
    """
    if not source_id:
        return None

    # Try parsing as UUID first
    try:
        return UUID(source_id)
    except (ValueError, AttributeError):
        pass

    # Resolve based on source_type
    if not source_type:
        return None

    # Import here to avoid circular imports
    from raas_core import elicitation

    if source_type == "elicitation_session":
        session = elicitation.get_elicitation_session(db, source_id)
        return session.id if session else None
    elif source_type == "clarification_point":
        point = elicitation.get_clarification_point(db, source_id)
        return point.id if point else None
    elif source_type == "requirement":
        req = get_requirement_by_any_id(db, source_id)
        return req.id if req else None
    elif source_type == "guardrail":
        guard = get_guardrail(db, source_id)
        return guard.id if guard else None

    return None


def create_task(
    db: Session,
    task_data: schemas.TaskCreate,
    user_id: Optional[UUID] = None,
) -> models.Task:
    """
    Create a new task.

    Args:
        db: Database session
        task_data: Task creation data
        user_id: UUID of the user creating the task

    Returns:
        Created Task object

    Raises:
        ValueError: If source_id cannot be resolved
    """
    # Resolve source_id from human-readable ID if needed
    resolved_source_id = _resolve_source_id(db, task_data.source_type, task_data.source_id)
    if task_data.source_id and not resolved_source_id:
        raise ValueError(f"Could not resolve source_id '{task_data.source_id}' for source_type '{task_data.source_type}'")

    task = models.Task(
        organization_id=task_data.organization_id,
        project_id=task_data.project_id,
        title=task_data.title,
        description=task_data.description,
        task_type=task_data.task_type,
        priority=task_data.priority,
        due_date=task_data.due_date,
        source_type=task_data.source_type,
        source_id=resolved_source_id,
        source_context=task_data.source_context,
        # Clarification task fields (CR-003)
        context=task_data.context,
        artifact_type=task_data.artifact_type,
        artifact_id=task_data.artifact_id,
        created_by=user_id,
    )
    db.add(task)
    db.flush()  # Get task ID for assignees

    # Add assignees
    if task_data.assignee_ids:
        for assignee_id in task_data.assignee_ids:
            user = db.query(models.User).filter(models.User.id == assignee_id).first()
            if user:
                task.assignees.append(user)

    # Record creation in history
    history = models.TaskHistory(
        task_id=task.id,
        change_type=models.TaskChangeType.CREATED,
        new_value=task.title,
        changed_by=user_id,
    )
    db.add(history)

    db.commit()
    db.refresh(task)
    logger.info(f"Created task {task.human_readable_id}: {task.title}")
    return task


def get_task(
    db: Session,
    task_id: str,
) -> Optional[models.Task]:
    """
    Get a task by UUID or human-readable ID.

    Args:
        db: Database session
        task_id: Task UUID or human-readable ID (e.g., 'TASK-001')

    Returns:
        Task or None if not found
    """
    # Try UUID first
    try:
        uuid_id = UUID(task_id)
        task = db.query(models.Task).filter(models.Task.id == uuid_id).first()
        if task:
            return task
    except (ValueError, AttributeError):
        pass

    # Try human-readable ID (case-insensitive)
    task = db.query(models.Task).filter(
        models.Task.human_readable_id.ilike(task_id)
    ).first()
    return task


def get_tasks(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    organization_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    assignee_id: Optional[UUID] = None,
    status: Optional[models.TaskStatus] = None,
    task_type: Optional[models.TaskType] = None,
    priority: Optional[models.TaskPriority] = None,
    source_type: Optional[str] = None,
    source_id: Optional[UUID] = None,
    overdue_only: bool = False,
    include_completed: bool = False,
) -> tuple[list[models.Task], int]:
    """
    Get tasks with filtering and pagination.

    Args:
        db: Database session
        skip: Number of items to skip
        limit: Maximum number of items to return
        organization_id: Filter by organization
        project_id: Filter by project
        assignee_id: Filter by assignee (tasks assigned to this user)
        status: Filter by status
        task_type: Filter by task type
        priority: Filter by priority
        source_type: Filter by source type
        source_id: Filter by source artifact ID
        overdue_only: Only return overdue tasks
        include_completed: Include completed/cancelled tasks (default: false)

    Returns:
        Tuple of (tasks, total_count)
    """
    from datetime import datetime

    query = db.query(models.Task)

    # Apply filters
    if organization_id:
        query = query.filter(models.Task.organization_id == organization_id)

    if project_id:
        query = query.filter(models.Task.project_id == project_id)

    if assignee_id:
        query = query.filter(models.Task.assignees.any(models.User.id == assignee_id))

    if status:
        query = query.filter(models.Task.status == status)
    elif not include_completed:
        # Exclude completed and cancelled by default
        query = query.filter(
            models.Task.status.notin_([models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED])
        )

    if task_type:
        query = query.filter(models.Task.task_type == task_type)

    if priority:
        query = query.filter(models.Task.priority == priority)

    if source_type:
        query = query.filter(models.Task.source_type == source_type)

    if source_id:
        query = query.filter(models.Task.source_id == source_id)

    if overdue_only:
        query = query.filter(
            models.Task.due_date < datetime.utcnow(),
            models.Task.status.notin_([models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED])
        )

    # Get total count before pagination
    total = query.count()

    # Order by priority (critical first) then due_date (earliest first) then created_at
    priority_order = [
        models.TaskPriority.CRITICAL,
        models.TaskPriority.HIGH,
        models.TaskPriority.MEDIUM,
        models.TaskPriority.LOW,
    ]
    query = query.order_by(
        # Custom priority ordering
        case(
            {p: i for i, p in enumerate(priority_order)},
            value=models.Task.priority
        ),
        models.Task.due_date.asc().nulls_last(),
        models.Task.created_at.desc()
    )

    # Apply pagination
    tasks = query.offset(skip).limit(limit).all()

    return tasks, total


def update_task(
    db: Session,
    task_id: UUID,
    task_update: schemas.TaskUpdate,
    user_id: Optional[UUID] = None,
) -> Optional[models.Task]:
    """
    Update a task.

    Args:
        db: Database session
        task_id: Task UUID
        task_update: Update data
        user_id: UUID of user making the update

    Returns:
        Updated Task or None if not found
    """
    from datetime import datetime

    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        return None

    # Track changes for history
    changes = []

    if task_update.title is not None and task_update.title != task.title:
        changes.append(('title', task.title, task_update.title))
        task.title = task_update.title

    if task_update.description is not None:
        changes.append(('description', task.description, task_update.description))
        task.description = task_update.description

    if task_update.status is not None and task_update.status != task.status:
        old_status = task.status
        old_status_value = task.status.value

        # RAAS-FEAT-096: Handle clarification task workflow
        if task.task_type == models.TaskType.CLARIFICATION:
            # Auto-create elicitation session when starting a clarification task
            if old_status == models.TaskStatus.PENDING and task_update.status == models.TaskStatus.IN_PROGRESS:
                from . import elicitation
                # Check if session already exists
                existing_session = elicitation.get_active_session_for_clarification_task(db, task.id)
                if not existing_session:
                    # Create elicitation session automatically
                    session_data = schemas.ElicitationSessionCreate(
                        organization_id=task.organization_id,
                        project_id=task.project_id,
                        target_artifact_type=task.artifact_type or "requirement",
                        target_artifact_id=str(task.artifact_id) if task.artifact_id else None,
                        assignee_id=task.assignees[0].id if task.assignees else None,
                        clarification_task_id=str(task.id),
                    )
                    elicitation.create_elicitation_session(db, session_data, user_id)
                    logger.info(f"Auto-created elicitation session for clarification task {task.human_readable_id}")

            # Enforce session requirement for completion
            if task_update.status == models.TaskStatus.COMPLETED:
                from . import elicitation
                existing_session = elicitation.get_active_session_for_clarification_task(db, task.id)
                # Also check completed sessions
                if not existing_session:
                    completed_session = db.query(models.ElicitationSession).filter(
                        models.ElicitationSession.clarification_task_id == task.id
                    ).first()
                    existing_session = completed_session
                if not existing_session:
                    raise ValueError(
                        f"Clarification task {task.human_readable_id} cannot be completed "
                        f"without an elicitation session. Start the task first (move to in_progress)."
                    )

        task.status = task_update.status
        changes.append(('status', old_status_value, task_update.status.value))

        # Handle completion
        if task_update.status == models.TaskStatus.COMPLETED:
            task.completed_at = datetime.utcnow()
            task.completed_by = user_id
            # Record completion in history
            history = models.TaskHistory(
                task_id=task.id,
                change_type=models.TaskChangeType.COMPLETED,
                old_value=old_status,
                new_value=task_update.status.value,
                changed_by=user_id,
            )
            db.add(history)
        elif task_update.status == models.TaskStatus.CANCELLED:
            # Record cancellation
            history = models.TaskHistory(
                task_id=task.id,
                change_type=models.TaskChangeType.CANCELLED,
                old_value=old_status,
                new_value=task_update.status.value,
                changed_by=user_id,
            )
            db.add(history)
        else:
            # Record status change
            history = models.TaskHistory(
                task_id=task.id,
                change_type=models.TaskChangeType.STATUS_CHANGED,
                field_name='status',
                old_value=old_status,
                new_value=task_update.status.value,
                changed_by=user_id,
            )
            db.add(history)

    if task_update.priority is not None and task_update.priority != task.priority:
        old_priority = task.priority.value
        task.priority = task_update.priority
        history = models.TaskHistory(
            task_id=task.id,
            change_type=models.TaskChangeType.PRIORITY_CHANGED,
            field_name='priority',
            old_value=old_priority,
            new_value=task_update.priority.value,
            changed_by=user_id,
        )
        db.add(history)

    if task_update.due_date is not None:
        old_due = str(task.due_date) if task.due_date else None
        task.due_date = task_update.due_date
        history = models.TaskHistory(
            task_id=task.id,
            change_type=models.TaskChangeType.DUE_DATE_CHANGED,
            field_name='due_date',
            old_value=old_due,
            new_value=str(task_update.due_date),
            changed_by=user_id,
        )
        db.add(history)

    db.commit()
    db.refresh(task)
    logger.info(f"Updated task {task.human_readable_id}")
    return task


def resolve_clarification_task(
    db: Session,
    task_id: str,
    resolution_content: str,
    user_id: Optional[UUID] = None,
) -> Optional[models.Task]:
    """
    Resolve a clarification task with an answer (CR-003).

    This completes a clarification task and records the resolution content.
    Only works for tasks with task_type='clarification'.

    Args:
        db: Database session
        task_id: Task UUID or human-readable ID
        resolution_content: The answer/resolution to the clarification
        user_id: UUID of user resolving the task

    Returns:
        Updated Task or None if not found

    Raises:
        ValueError: If task is not a clarification task or already resolved
    """
    from datetime import datetime

    task = get_task(db, task_id)
    if not task:
        return None

    # Validate this is a clarification task
    if task.task_type != models.TaskType.CLARIFICATION:
        raise ValueError(
            f"Task {task.human_readable_id} is not a clarification task "
            f"(type is {task.task_type.value})"
        )

    # Check if already resolved
    if task.status == models.TaskStatus.COMPLETED:
        raise ValueError(
            f"Task {task.human_readable_id} is already completed"
        )

    # RAAS-FEAT-096: Enforce session requirement for completion
    from . import elicitation
    existing_session = elicitation.get_active_session_for_clarification_task(db, task.id)
    # Also check completed sessions
    if not existing_session:
        completed_session = db.query(models.ElicitationSession).filter(
            models.ElicitationSession.clarification_task_id == task.id
        ).first()
        existing_session = completed_session
    if not existing_session:
        raise ValueError(
            f"Clarification task {task.human_readable_id} cannot be resolved "
            f"without an elicitation session. Start the task first (move to in_progress)."
        )

    # Record old status for history
    old_status = task.status.value

    # Update task with resolution
    task.resolution_content = resolution_content
    task.resolved_at = datetime.utcnow()
    task.resolved_by = user_id
    task.status = models.TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    task.completed_by = user_id

    # Record completion in history
    history = models.TaskHistory(
        task_id=task.id,
        change_type=models.TaskChangeType.COMPLETED,
        old_value=old_status,
        new_value=models.TaskStatus.COMPLETED.value,
        comment=f"Resolved with answer: {resolution_content[:100]}..." if len(resolution_content) > 100 else f"Resolved with answer: {resolution_content}",
        changed_by=user_id,
    )
    db.add(history)

    db.commit()
    db.refresh(task)
    logger.info(f"Resolved clarification task {task.human_readable_id}")
    return task


def assign_task(
    db: Session,
    task_id: UUID,
    assignee_ids: list[UUID],
    user_id: Optional[UUID] = None,
    replace: bool = False,
) -> Optional[models.Task]:
    """
    Assign users to a task.

    Args:
        db: Database session
        task_id: Task UUID
        assignee_ids: List of user UUIDs to assign
        user_id: UUID of user making the assignment
        replace: If true, replace all existing assignees

    Returns:
        Updated Task or None if not found
    """
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        return None

    old_assignees = [str(u.id) for u in task.assignees]

    if replace:
        # Remove all existing assignees
        task.assignees.clear()

    # Add new assignees
    for assignee_id in assignee_ids:
        user = db.query(models.User).filter(models.User.id == assignee_id).first()
        if user and user not in task.assignees:
            task.assignees.append(user)

    new_assignees = [str(u.id) for u in task.assignees]

    # Record assignment change
    if old_assignees != new_assignees:
        change_type = models.TaskChangeType.REASSIGNED if old_assignees else models.TaskChangeType.ASSIGNED
        history = models.TaskHistory(
            task_id=task.id,
            change_type=change_type,
            field_name='assignees',
            old_value=','.join(old_assignees) if old_assignees else None,
            new_value=','.join(new_assignees),
            changed_by=user_id,
        )
        db.add(history)

    db.commit()
    db.refresh(task)
    logger.info(f"Assigned task {task.human_readable_id} to {len(task.assignees)} users")
    return task


def get_task_history(
    db: Session,
    task_id: UUID,
    limit: int = 50,
) -> list[models.TaskHistory]:
    """
    Get history for a task.

    Args:
        db: Database session
        task_id: Task UUID
        limit: Maximum number of entries to return

    Returns:
        List of TaskHistory entries
    """
    return db.query(models.TaskHistory).filter(
        models.TaskHistory.task_id == task_id
    ).order_by(
        models.TaskHistory.changed_at.desc()
    ).limit(limit).all()


def get_my_tasks(
    db: Session,
    user_id: UUID,
    organization_ids: Optional[list[UUID]] = None,
    include_completed: bool = False,
) -> list[models.Task]:
    """
    Get all tasks assigned to a user across all their organizations.

    Args:
        db: Database session
        user_id: User UUID
        organization_ids: Optional filter by organizations
        include_completed: Include completed/cancelled tasks

    Returns:
        List of Tasks assigned to the user
    """
    query = db.query(models.Task).filter(
        models.Task.assignees.any(models.User.id == user_id)
    )

    if organization_ids:
        query = query.filter(models.Task.organization_id.in_(organization_ids))

    if not include_completed:
        query = query.filter(
            models.Task.status.notin_([models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED])
        )

    # Order by priority then due_date
    priority_order = [
        models.TaskPriority.CRITICAL,
        models.TaskPriority.HIGH,
        models.TaskPriority.MEDIUM,
        models.TaskPriority.LOW,
    ]
    query = query.order_by(
        case(
            {p: i for i, p in enumerate(priority_order)},
            value=models.Task.priority
        ),
        models.Task.due_date.asc().nulls_last(),
        models.Task.created_at.desc()
    )

    return query.all()


def find_task_by_source(
    db: Session,
    source_type: str,
    source_id: UUID,
    task_type: Optional[models.TaskType] = None,
    exclude_completed: bool = True,
) -> Optional[models.Task]:
    """
    Find existing task for a source artifact.

    Used to prevent duplicate tasks for the same source.

    Args:
        db: Database session
        source_type: Task source type
        source_id: Source artifact UUID
        task_type: Optional task type filter
        exclude_completed: Whether to exclude completed/cancelled tasks

    Returns:
        Existing task if found, None otherwise
    """
    query = db.query(models.Task).filter(
        models.Task.source_type == source_type,
        models.Task.source_id == source_id
    )

    if task_type:
        query = query.filter(models.Task.task_type == task_type)

    if exclude_completed:
        query = query.filter(
            models.Task.status.notin_([models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED])
        )

    return query.first()


def get_tasks_by_source_id(
    db: Session,
    source_id: UUID,
    include_completed: bool = False,
) -> list[models.Task]:
    """
    Get all tasks associated with a source artifact.

    Args:
        db: Database session
        source_id: Source artifact UUID
        include_completed: Whether to include completed/cancelled tasks

    Returns:
        List of tasks
    """
    query = db.query(models.Task).filter(models.Task.source_id == source_id)

    if not include_completed:
        query = query.filter(
            models.Task.status.notin_([models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED])
        )

    return query.order_by(models.Task.created_at.desc()).all()


# ============================================================================
# Agent Director Functions (CR-012)
# ============================================================================


def get_user_org_role(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
) -> Optional[models.MemberRole]:
    """
    Get user's role in an organization.

    Args:
        db: Database session
        user_id: User UUID
        organization_id: Organization UUID

    Returns:
        MemberRole enum or None if not a member
    """
    membership = (
        db.query(models.OrganizationMember)
        .filter(
            models.OrganizationMember.user_id == user_id,
            models.OrganizationMember.organization_id == organization_id,
        )
        .first()
    )
    return membership.role if membership else None


def is_org_owner(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
) -> bool:
    """
    Check if user is an owner of the organization.

    Args:
        db: Database session
        user_id: User UUID
        organization_id: Organization UUID

    Returns:
        True if user is an owner, False otherwise
    """
    role = get_user_org_role(db, user_id, organization_id)
    return role == models.MemberRole.OWNER


def match_user_agent_pattern(user_agent: str, patterns: list[str]) -> bool:
    """
    Check if a user-agent string matches any of the allowed patterns.

    Supports prefix matching with wildcards:
    - "claude-desktop/*" matches "claude-desktop/1.2.3"
    - "claude-code/*" matches "claude-code/0.1.0"
    - Exact match also works: "claude-desktop/1.0.0" matches "claude-desktop/1.0.0"

    Args:
        user_agent: The user-agent string from the HTTP header
        patterns: List of allowed patterns

    Returns:
        True if user_agent matches any pattern, False otherwise
    """
    if not patterns:
        # Empty patterns = unrestricted
        return True

    user_agent_lower = user_agent.lower().strip()

    for pattern in patterns:
        pattern_lower = pattern.lower().strip()

        if pattern_lower.endswith("/*"):
            # Prefix match: "claude-desktop/*" matches "claude-desktop/anything"
            prefix = pattern_lower[:-1]  # Remove the "*", keep the "/"
            if user_agent_lower.startswith(prefix):
                return True
        elif pattern_lower == user_agent_lower:
            # Exact match
            return True

    return False


def get_agent_by_email(
    db: Session,
    email: str,
) -> Optional[models.User]:
    """
    Get an agent account by email.

    Args:
        db: Database session
        email: Agent email address

    Returns:
        User model if found and is an agent, None otherwise
    """
    user = (
        db.query(models.User)
        .filter(
            models.User.email == email.lower(),
            models.User.user_type == models.UserType.AGENT,
        )
        .first()
    )
    return user


def list_agents(
    db: Session,
    organization_id: Optional[UUID] = None,
) -> list[models.User]:
    """
    List all agent accounts.

    Args:
        db: Database session
        organization_id: Optional - not currently used but reserved for future org-scoped agents

    Returns:
        List of agent User models
    """
    query = db.query(models.User).filter(
        models.User.user_type == models.UserType.AGENT,
        models.User.is_active == True,
    )
    return query.order_by(models.User.email).all()


def check_agent_director_authorization(
    db: Session,
    director_id: UUID,
    agent_email: str,
    organization_id: UUID,
    user_agent: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[list[str]]]:
    """
    Check if a director is authorized to act as an agent in an organization.

    Authorization is granted if:
    1. Director is an owner of the organization (implicit authorization), OR
    2. An explicit AgentDirector mapping exists AND client constraints are satisfied

    CR-005/TARKA-FEAT-105: Client constraints enforcement
    - If user_agent is provided and mapping has allowed_user_agents, the client must match
    - Org owners bypass client constraints (implicit authorization)
    - Null/empty allowed_user_agents means unrestricted

    Args:
        db: Database session
        director_id: UUID of the human user (director)
        agent_email: Email of the agent account
        organization_id: UUID of the organization
        user_agent: Optional HTTP user-agent header for client constraint checking

    Returns:
        Tuple of (is_authorized, authorization_type, allowed_user_agents)
        - is_authorized: True if authorized, False otherwise
        - authorization_type: 'owner' (implicit), 'explicit' (mapping exists), or None
        - allowed_user_agents: List of allowed patterns (for error messages), or None
    """
    # First, get the agent by email
    agent = get_agent_by_email(db, agent_email)
    if not agent:
        return False, None, None

    # Check if director is an org owner (implicit authorization)
    # Org owners bypass client constraints
    if is_org_owner(db, director_id, organization_id):
        return True, "owner", None

    # Check for explicit mapping
    mapping = (
        db.query(models.AgentDirector)
        .filter(
            models.AgentDirector.agent_id == agent.id,
            models.AgentDirector.director_id == director_id,
            models.AgentDirector.organization_id == organization_id,
        )
        .first()
    )

    if mapping:
        allowed_patterns = mapping.allowed_user_agents

        # CR-005: Check client constraints if patterns are defined
        if allowed_patterns and user_agent:
            if not match_user_agent_pattern(user_agent, allowed_patterns):
                # Mapping exists but client not allowed
                return False, "client_rejected", allowed_patterns

        return True, "explicit", allowed_patterns

    return False, None, None


def get_agents_for_director(
    db: Session,
    director_id: UUID,
    organization_id: UUID,
) -> list[dict]:
    """
    Get all agents a director can use in an organization.

    For org owners: returns all agents with authorization_type='owner'
    For others: returns only explicitly mapped agents with client constraints

    CR-005/TARKA-FEAT-105: Returns allowed_user_agents for each agent

    Args:
        db: Database session
        director_id: UUID of the human user
        organization_id: UUID of the organization

    Returns:
        List of agent dicts with authorization info including allowed_user_agents
    """
    all_agents = list_agents(db)

    # Check if director is org owner
    director_is_owner = is_org_owner(db, director_id, organization_id)

    # Get explicit mappings for this director in this org (including allowed_user_agents)
    explicit_mappings = (
        db.query(models.AgentDirector)
        .filter(
            models.AgentDirector.director_id == director_id,
            models.AgentDirector.organization_id == organization_id,
        )
        .all()
    )
    # Build a dict of agent_id -> allowed_user_agents
    explicit_mappings_dict = {
        m.agent_id: m.allowed_user_agents for m in explicit_mappings
    }

    result = []
    for agent in all_agents:
        if director_is_owner:
            # Owners can use all agents (no client restrictions)
            result.append({
                "id": agent.id,
                "email": agent.email,
                "full_name": agent.full_name,
                "is_authorized": True,
                "authorization_type": "owner",
                "allowed_user_agents": None,  # Unrestricted for owners
            })
        elif agent.id in explicit_mappings_dict:
            # Explicit mapping exists
            result.append({
                "id": agent.id,
                "email": agent.email,
                "full_name": agent.full_name,
                "is_authorized": True,
                "authorization_type": "explicit",
                "allowed_user_agents": explicit_mappings_dict[agent.id],
            })
        else:
            # Not authorized
            result.append({
                "id": agent.id,
                "email": agent.email,
                "full_name": agent.full_name,
                "is_authorized": False,
                "authorization_type": None,
                "allowed_user_agents": None,
            })

    return result


def create_agent_director_mapping(
    db: Session,
    agent_id: UUID,
    director_id: UUID,
    organization_id: UUID,
    created_by: Optional[UUID] = None,
    allowed_user_agents: Optional[list[str]] = None,
) -> models.AgentDirector:
    """
    Create an agent-director authorization mapping.

    CR-005/TARKA-FEAT-105: Supports allowed_user_agents for client constraints

    Args:
        db: Database session
        agent_id: UUID of the agent account
        director_id: UUID of the human user to authorize
        organization_id: UUID of the organization
        created_by: UUID of the user creating the mapping
        allowed_user_agents: Optional list of user-agent patterns (e.g., ["claude-desktop/*"])

    Returns:
        Created AgentDirector model

    Raises:
        ValueError: If mapping already exists or invalid user types
    """
    # Verify agent exists and is an agent
    agent = db.query(models.User).filter(models.User.id == agent_id).first()
    if not agent:
        raise ValueError(f"Agent not found: {agent_id}")
    if agent.user_type != models.UserType.AGENT:
        raise ValueError(f"User {agent_id} is not an agent account")

    # Verify director exists and is a human
    director = db.query(models.User).filter(models.User.id == director_id).first()
    if not director:
        raise ValueError(f"Director not found: {director_id}")
    if director.user_type != models.UserType.HUMAN:
        raise ValueError(f"User {director_id} is not a human account")

    # Verify organization exists
    org = db.query(models.Organization).filter(models.Organization.id == organization_id).first()
    if not org:
        raise ValueError(f"Organization not found: {organization_id}")

    # Check for existing mapping
    existing = (
        db.query(models.AgentDirector)
        .filter(
            models.AgentDirector.agent_id == agent_id,
            models.AgentDirector.director_id == director_id,
            models.AgentDirector.organization_id == organization_id,
        )
        .first()
    )
    if existing:
        raise ValueError("Agent-director mapping already exists")

    # Create mapping
    mapping = models.AgentDirector(
        agent_id=agent_id,
        director_id=director_id,
        organization_id=organization_id,
        created_by=created_by,
        allowed_user_agents=allowed_user_agents,
    )

    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    logger.info(f"Created agent-director mapping: agent={agent.email}, director={director.email}, org={org.slug}")
    return mapping


def delete_agent_director_mapping(
    db: Session,
    agent_id: UUID,
    director_id: UUID,
    organization_id: UUID,
) -> bool:
    """
    Delete an agent-director authorization mapping.

    Args:
        db: Database session
        agent_id: UUID of the agent account
        director_id: UUID of the human user
        organization_id: UUID of the organization

    Returns:
        True if mapping was deleted, False if not found
    """
    mapping = (
        db.query(models.AgentDirector)
        .filter(
            models.AgentDirector.agent_id == agent_id,
            models.AgentDirector.director_id == director_id,
            models.AgentDirector.organization_id == organization_id,
        )
        .first()
    )

    if not mapping:
        return False

    db.delete(mapping)
    db.commit()

    logger.info(f"Deleted agent-director mapping: agent={agent_id}, director={director_id}, org={organization_id}")
    return True


def list_agent_director_mappings(
    db: Session,
    organization_id: UUID,
    agent_id: Optional[UUID] = None,
    director_id: Optional[UUID] = None,
) -> list[models.AgentDirector]:
    """
    List agent-director mappings for an organization.

    Args:
        db: Database session
        organization_id: UUID of the organization
        agent_id: Optional filter by agent
        director_id: Optional filter by director

    Returns:
        List of AgentDirector models
    """
    query = db.query(models.AgentDirector).filter(
        models.AgentDirector.organization_id == organization_id
    )

    if agent_id:
        query = query.filter(models.AgentDirector.agent_id == agent_id)

    if director_id:
        query = query.filter(models.AgentDirector.director_id == director_id)

    return query.order_by(models.AgentDirector.created_at.desc()).all()
