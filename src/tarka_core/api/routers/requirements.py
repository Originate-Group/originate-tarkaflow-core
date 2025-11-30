"""Requirements API endpoints (solo mode - no authentication)."""
import logging
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from sqlalchemy.orm import Session
from tarka_core import crud, schemas, models
from tarka_core.markdown_utils import load_template
from tarka_core.hierarchy_validation import find_hierarchy_violations
from tarka_core.api.dependencies import get_current_user_optional
from tarka_core.persona_auth import Persona

from ..database import get_db

logger = logging.getLogger("raas-core.requirements")

router = APIRouter(tags=["requirements"])


@router.get("/templates/{req_type}")
def get_requirement_template(req_type: models.RequirementType):
    """
    Get the markdown template for a specific requirement type.

    This endpoint returns the standard template that must be used when creating
    or updating requirements. The template includes YAML frontmatter and markdown
    structure that the system expects.

    - **req_type**: The requirement type (epic, component, feature, requirement)
    """
    try:
        template = load_template(req_type)
        logger.debug(f"Template loaded for type: {req_type.value}")
        return {"type": req_type.value, "template": template}
    except FileNotFoundError as e:
        logger.error(f"Template not found for type {req_type.value}: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"Template not found for type: {req_type.value}"
        )
    except Exception as e:
        logger.error(f"Unexpected error loading template for {req_type.value}: {e}")
        raise


@router.post("/", response_model=schemas.RequirementResponse, status_code=201)
def create_requirement(
    requirement: schemas.RequirementCreate,
    request: Request,
    x_agent_email: Optional[str] = Header(
        None,
        description="Agent email performing this action on behalf of the director (human). "
                    "Used for director/actor audit trail per BUG-003 and GUARD-SEC-003."
    ),
    db: Session = Depends(get_db),
):
    """
    Create a new requirement (solo mode - no authentication required).

    - **type**: Requirement type (epic, component, feature, requirement)
    - **parent_id**: Parent requirement ID (required for non-epic types)
    - **title**: Requirement title
    - **description**: Detailed description (optional)
    - **status**: Lifecycle status (defaults to 'draft')
    - **tags**: List of tags (optional)
    - **X-Agent-Email**: Header for agent performing action (for audit trail)
    """
    # Derive organization_id from parent/project
    organization_id = None

    if requirement.type == models.RequirementType.EPIC:
        # For epics, get organization from project
        if not requirement.project_id:
            raise HTTPException(
                status_code=400,
                detail="Epics require a project_id"
            )
        project = crud.get_project(db, requirement.project_id)
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project {requirement.project_id} not found"
            )
        organization_id = project.organization_id
    else:
        # For non-epics, extract parent_id from markdown and get org from parent
        import yaml
        import re

        # Extract YAML frontmatter
        content = requirement.content.strip()
        if content.startswith("---"):
            # Find end of frontmatter
            match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
            if match:
                try:
                    frontmatter = yaml.safe_load(match.group(1))
                    parent_id = frontmatter.get("parent_id")

                    if not parent_id:
                        raise HTTPException(
                            status_code=400,
                            detail=f"{requirement.type.value} requires a parent_id in the markdown frontmatter"
                        )

                    parent = crud.get_requirement(db, parent_id)
                    if not parent:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Parent requirement {parent_id} not found"
                        )
                    organization_id = parent.organization_id
                except yaml.YAMLError as e:
                    raise HTTPException(status_code=400, detail=f"Invalid YAML frontmatter: {e}")
            else:
                raise HTTPException(status_code=400, detail="Markdown must include YAML frontmatter")
        else:
            raise HTTPException(status_code=400, detail="Content must start with YAML frontmatter (---)")

    # Get current user (for permission checking in team mode, None in solo mode)
    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    # BUG-003: Look up agent for actor_id (director/actor audit trail)
    actor_id = None
    if x_agent_email:
        agent_user = crud.get_agent_by_email(db, x_agent_email)
        if agent_user:
            actor_id = agent_user.id
            logger.debug(f"Agent {x_agent_email} resolved to actor_id {actor_id}")
        else:
            logger.warning(f"Agent email {x_agent_email} not found in database")

    try:
        result = crud.create_requirement(
            db=db,
            requirement=requirement,
            organization_id=organization_id,
            user_id=user_id,
            project_id=requirement.project_id,
            director_id=user_id,  # BUG-003: director is the authenticated user
            actor_id=actor_id,    # BUG-003: actor is the agent (if any)
        )
        logger.info(f"Created {result.type.value} '{result.title}' (ID: {result.id})")
        return result
    except ValueError as e:
        # Validation errors from crud layer (e.g., invalid guardrail references, invalid dependencies)
        logger.warning(f"Validation error creating requirement: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating requirement: {e}", exc_info=True)
        raise


@router.get("/", response_model=schemas.RequirementListResponse)
def list_requirements(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    type: Optional[models.RequirementType] = Query(None, description="Filter by type"),
    status: Optional[models.LifecycleStatus] = Query(None, description="Filter by status"),
    quality_score: Optional[models.QualityScore] = Query(None, description="Filter by quality score"),
    parent_id: Optional[UUID] = Query(None, description="Filter by parent ID"),
    project_id: Optional[UUID] = Query(None, description="Filter by project ID"),
    search: Optional[str] = Query(None, description="Search in title and description"),
    tags: Optional[list[str]] = Query(None, description="Filter by tags (AND logic - must have ALL tags)"),
    include_deployed: bool = Query(False, description="Include deployed items (default: false)"),
    include_deprecated: bool = Query(False, description="Include deprecated items (default: false)"),
    ready_to_implement: Optional[bool] = Query(None, description="Filter for requirements ready to implement (all dependencies have deployed_version_id set)"),
    blocked_by: Optional[UUID] = Query(None, description="Filter for requirements that depend on the specified requirement ID"),
    db: Session = Depends(get_db),
):
    """
    List requirements with optional filtering and pagination.

    In team mode, only returns requirements from projects in organizations
    where the user is a member.

    - **page**: Page number (starts at 1)
    - **page_size**: Number of items per page (1-100)
    - **type**: Filter by requirement type
    - **status**: Filter by lifecycle status
    - **quality_score**: Filter by quality score (OK, NEEDS_REVIEW, LOW_QUALITY)
    - **parent_id**: Filter by parent requirement
    - **project_id**: Filter by project ID
    - **search**: Search text in title and description
    - **tags**: Filter by tags (AND logic - requirement must have ALL specified tags)
    - **include_deployed**: Include deployed items (default: false, deployed items are excluded)
    - **include_deprecated**: Include deprecated items (default: false, deprecated items are excluded)
    """
    # Get current user for organization-based filtering in team mode
    current_user = get_current_user_optional(request)

    # Get user's organization IDs for filtering (None means no filtering in solo mode)
    organization_ids = None
    if current_user:
        organization_ids = crud.get_user_organization_ids(db, current_user.id)
        if not organization_ids:
            # User has no organization memberships - return empty results
            return schemas.RequirementListResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                total_pages=0,
            )

    skip = (page - 1) * page_size
    requirements, total = crud.get_requirements(
        db=db,
        skip=skip,
        limit=page_size,
        type_filter=type,
        status_filter=status,
        quality_score_filter=quality_score,
        parent_id=parent_id,
        search=search,
        tags=tags,
        organization_ids=organization_ids,
        project_id=project_id,
        include_deployed=include_deployed,
        include_deprecated=include_deprecated,
        ready_to_implement=ready_to_implement,
        blocked_by=blocked_by,
    )

    return schemas.RequirementListResponse(
        items=requirements,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total > 0 else 0,
    )


def _check_requirement_access(
    request: Request,
    requirement: models.Requirement,
    db: Session,
) -> None:
    """
    Check if current user has access to a requirement via organization membership.

    In team mode, user must be a member of the requirement's organization.
    In solo mode (current_user is None), access is always granted.

    Raises:
        HTTPException: 403 if user doesn't have access
    """
    current_user = get_current_user_optional(request)
    if current_user:
        organization_ids = crud.get_user_organization_ids(db, current_user.id)
        if requirement.organization_id not in organization_ids:
            logger.warning(
                f"User {current_user.id} denied access to requirement {requirement.id} "
                f"(org {requirement.organization_id} not in user's orgs)"
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "permission_denied",
                    "message": "You don't have access to this requirement. "
                               "You must be a member of the requirement's organization.",
                    "resource_type": "requirement",
                }
            )


@router.get("/{requirement_id}", response_model=schemas.RequirementResponse)
def get_requirement(
    requirement_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get a specific requirement by ID.

    In team mode, requires membership in the requirement's organization.

    Supports both UUID and human-readable ID formats:
    - UUID: afa92d5c-e008-44d6-b2cf-ccacd81481d6
    - Readable: RAAS-FEAT-042 (case-insensitive)

    - **requirement_id**: UUID or human-readable ID of the requirement
    """
    try:
        requirement = crud.get_requirement_by_any_id(db, requirement_id)
        if not requirement:
            logger.warning(f"Requirement not found: {requirement_id}")
            raise HTTPException(status_code=404, detail=f"Requirement not found: {requirement_id}")

        # Check organization membership in team mode
        _check_requirement_access(request, requirement, db)

        logger.debug(f"Successfully retrieved requirement {requirement_id}")
        return requirement
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving requirement {requirement_id}: {e}", exc_info=True)
        raise


@router.get("/{requirement_id}/children", response_model=list[schemas.RequirementListItem])
def get_requirement_children(
    requirement_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get all children of a requirement (lightweight, no content field).

    In team mode, requires membership in the requirement's organization.

    Supports both UUID and human-readable ID formats:
    - UUID: afa92d5c-e008-44d6-b2cf-ccacd81481d6
    - Readable: RAAS-EPIC-001 (case-insensitive)

    Use GET /requirements/{child_id} to fetch full details for specific children.

    - **requirement_id**: UUID or human-readable ID of the parent requirement
    """
    requirement = crud.get_requirement_by_any_id(db, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail=f"Requirement not found: {requirement_id}")

    # Check organization membership in team mode
    _check_requirement_access(request, requirement, db)

    return crud.get_requirement_children(db, requirement.id)


@router.get("/{requirement_id}/history", response_model=list[schemas.RequirementHistoryResponse])
def get_requirement_history(
    requirement_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of history entries"),
    db: Session = Depends(get_db),
):
    """
    Get change history for a requirement.

    In team mode, requires membership in the requirement's organization.

    Supports both UUID and human-readable ID formats.

    - **requirement_id**: UUID or human-readable ID of the requirement
    - **limit**: Maximum number of history entries to return (1-100)
    """
    requirement = crud.get_requirement_by_any_id(db, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail=f"Requirement not found: {requirement_id}")

    # Check organization membership in team mode
    _check_requirement_access(request, requirement, db)

    return crud.get_requirement_history(db, requirement.id, limit)


@router.patch("/{requirement_id}", response_model=schemas.RequirementResponse)
def update_requirement(
    requirement_id: str,
    requirement_update: schemas.RequirementUpdate,
    request: Request,
    x_persona: Optional[str] = Header(
        None,
        description="Workflow persona making this request (e.g., developer, tester, release_manager). "
                    "Required for status transitions when persona enforcement is enabled."
    ),
    x_agent_email: Optional[str] = Header(
        None,
        description="Agent email performing this action on behalf of the director (human). "
                    "Used for director/actor audit trail per CR-012 and GUARD-SEC-003."
    ),
    db: Session = Depends(get_db),
):
    """
    Update a requirement.

    In team mode, requires membership in the requirement's organization.

    Supports both UUID and human-readable ID formats.

    - **requirement_id**: UUID or human-readable ID of the requirement
    - **content**: New markdown content (optional)
    - **status**: New status (optional)
    - **tags**: New tags list (optional)
    - **X-Persona**: Header declaring the workflow persona (developer, tester, etc.)
    """
    # Check requirement exists
    existing = crud.get_requirement_by_any_id(db, requirement_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Requirement not found: {requirement_id}")

    # Check organization membership in team mode
    _check_requirement_access(request, existing, db)

    # Get current user (for permission checking in team mode, None in solo mode)
    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    # Look up agent for actor_id (BUG-002 fix: director/actor audit trail)
    actor_id = None
    if x_agent_email:
        agent_user = crud.get_agent_by_email(db, x_agent_email)
        if agent_user:
            actor_id = agent_user.id
            logger.debug(f"Agent {x_agent_email} resolved to actor_id {actor_id}")
        else:
            logger.warning(f"Agent email {x_agent_email} not found in database")

    # Parse persona from header
    persona = None
    if x_persona:
        try:
            persona = Persona(x_persona.lower())
        except ValueError:
            valid_personas = [p.value for p in Persona]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid persona: {x_persona}. Valid personas: {', '.join(valid_personas)}"
            )

    try:
        requirement = crud.update_requirement(
            db, existing.id, requirement_update, user_id=user_id, persona=persona,
            director_id=user_id, actor_id=actor_id  # BUG-002: director/actor audit trail
        )

        return requirement
    except ValueError as e:
        # Catch validation errors (state machine, content length, persona auth, etc.)
        error_message = str(e)
        logger.warning(f"Validation failed for requirement {requirement_id}: {error_message}")

        # Determine if this is a state transition error, persona error, or other
        if "Invalid status transition" in error_message:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_status_transition",
                    "message": error_message
                }
            )
        elif "not authorized for transition" in error_message or "Persona declaration required" in error_message:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "persona_authorization_failed",
                    "message": error_message
                }
            )
        else:
            raise HTTPException(status_code=400, detail=error_message)


@router.delete("/{requirement_id}", status_code=204)
def delete_requirement(
    requirement_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Delete a requirement.

    In team mode, requires membership in the requirement's organization.

    Supports both UUID and human-readable ID formats.

    Note: This will cascade delete all children requirements.

    - **requirement_id**: UUID or human-readable ID of the requirement
    """
    # Check requirement exists
    existing = crud.get_requirement_by_any_id(db, requirement_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Requirement not found: {requirement_id}")

    # Check organization membership in team mode
    _check_requirement_access(request, existing, db)

    # Get current user (for permission checking in team mode, None in solo mode)
    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    try:
        success = crud.delete_requirement(db, existing.id, user_id=user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Requirement not found")
    except ValueError as e:
        # Permission denied or dependency blocking deletion
        error_message = str(e)
        logger.warning(f"Delete blocked for requirement {requirement_id}: {error_message}")

        if "admin role" in error_message.lower() or "permission" in error_message.lower():
            raise HTTPException(status_code=403, detail=error_message)
        else:
            # Other validation errors (e.g., dependent requirements exist)
            raise HTTPException(status_code=400, detail=error_message)


@router.get("/audit/hierarchy-violations")
def get_hierarchy_violations(
    project_id: Optional[UUID] = Query(None, description="Filter by project ID"),
    db: Session = Depends(get_db),
):
    """
    Find all requirements that violate hierarchy rules.

    This endpoint identifies existing requirements with invalid parent-child
    type relationships (created before validation was enforced) and provides
    remediation guidance.

    Returns:
    - requirement_id: UUID of the requirement
    - requirement_human_id: Human-readable ID (e.g., RAAS-FEAT-042)
    - requirement_title: Title of the requirement
    - requirement_type: Type (epic, component, feature, requirement)
    - parent_id: UUID of the parent (if exists)
    - parent_human_id: Human-readable ID of parent
    - parent_title: Title of the parent
    - parent_type: Type of the parent
    - expected_parent_type: What type the parent should be
    - violation: Description of the violation

    - **project_id**: Optional filter to only check requirements in a specific project
    """
    violations = find_hierarchy_violations(db, project_id)
    return {
        "violations": violations,
        "total": len(violations),
        "project_id": str(project_id) if project_id else None,
    }


# =============================================================================
# CR-017: Acceptance Criteria Entity Management (TARKA-FEAT-111)
# =============================================================================


@router.get("/{requirement_id}/acceptance-criteria", response_model=schemas.AcceptanceCriteriaListResponse)
def list_acceptance_criteria(
    requirement_id: str,
    version_number: Optional[int] = Query(None, description="Version number (defaults to resolved version)"),
    db: Session = Depends(get_db),
):
    """
    List Acceptance Criteria for a requirement version (CR-017).

    Returns all ACs for a specific requirement version with their met status.
    If version_number is not specified, uses the resolved version (deployed -> latest approved -> latest).

    - **requirement_id**: UUID or human-readable ID of the requirement
    - **version_number**: Optional version number (defaults to resolved version)
    """
    # Resolve requirement
    requirement = crud.resolve_requirement_id(db, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    # Resolve version
    from tarka_core.versioning import resolve_version
    version = resolve_version(db, requirement, version_number)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Get ACs for this version
    acs = version.acceptance_criteria

    # Build response with user email lookups
    items = []
    for ac in acs:
        met_by_email = None
        if ac.met_by_user_id:
            user = crud.get_user_by_internal_id(db, ac.met_by_user_id)
            met_by_email = user.email if user else None

        items.append(schemas.AcceptanceCriteriaResponse(
            id=ac.id,
            requirement_version_id=ac.requirement_version_id,
            ordinal=ac.ordinal,
            criteria_text=ac.criteria_text,
            content_hash=ac.content_hash,
            met=ac.met,
            met_at=ac.met_at,
            met_by_user_id=ac.met_by_user_id,
            met_by_email=met_by_email,
            source_ac_id=ac.source_ac_id,
            created_at=ac.created_at,
        ))

    return schemas.AcceptanceCriteriaListResponse(
        items=items,
        total=len(items),
        requirement_id=requirement.id,
        version_number=version.version_number,
    )


@router.get("/{requirement_id}/acceptance-criteria/summary", response_model=schemas.AcceptanceCriteriaSummary)
def get_acceptance_criteria_summary(
    requirement_id: str,
    version_number: Optional[int] = Query(None, description="Version number (defaults to resolved version)"),
    db: Session = Depends(get_db),
):
    """
    Get a summary of AC completion for a requirement (CR-017).

    Returns aggregated completion state: total, met, unmet, and completion percentage.

    - **requirement_id**: UUID or human-readable ID of the requirement
    - **version_number**: Optional version number (defaults to resolved version)
    """
    # Resolve requirement
    requirement = crud.resolve_requirement_id(db, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    # Resolve version
    from tarka_core.versioning import resolve_version, get_acceptance_criteria_summary as get_summary
    version = resolve_version(db, requirement, version_number)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Get summary
    summary = get_summary(version)
    return schemas.AcceptanceCriteriaSummary(**summary)


@router.patch("/acceptance-criteria/{ac_id}", response_model=schemas.AcceptanceCriteriaResponse)
def update_acceptance_criteria(
    ac_id: UUID,
    update: schemas.AcceptanceCriteriaUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Update the met status of an Acceptance Criteria (CR-017).

    Marks an individual AC as met or unmet without triggering a new requirement version.
    Per TARKA-FEAT-097, met status is mutable (no version impact).

    - **ac_id**: UUID of the AcceptanceCriteria to update
    - **met**: New met status (true=met, false=unmet)
    """
    # Get current user (optional in solo mode)
    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    from tarka_core.versioning import update_acceptance_criteria_met_status

    # For solo mode without auth, we still need a user_id for audit
    if not user_id:
        # Use a placeholder - in production this would require auth
        logger.warning("AC update without authenticated user - audit trail will be incomplete")

    ac = update_acceptance_criteria_met_status(db, ac_id, update.met, user_id)
    if not ac:
        raise HTTPException(status_code=404, detail="Acceptance Criteria not found")

    db.commit()

    # Build response with user email lookup
    met_by_email = None
    if ac.met_by_user_id:
        user = crud.get_user_by_internal_id(db, ac.met_by_user_id)
        met_by_email = user.email if user else None

    return schemas.AcceptanceCriteriaResponse(
        id=ac.id,
        requirement_version_id=ac.requirement_version_id,
        ordinal=ac.ordinal,
        criteria_text=ac.criteria_text,
        content_hash=ac.content_hash,
        met=ac.met,
        met_at=ac.met_at,
        met_by_user_id=ac.met_by_user_id,
        met_by_email=met_by_email,
        source_ac_id=ac.source_ac_id,
        created_at=ac.created_at,
    )
