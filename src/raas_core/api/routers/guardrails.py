"""API endpoints for guardrail management (solo mode - no authentication)."""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from math import ceil

from raas_core import crud, schemas

from ..database import get_db

logger = logging.getLogger("raas-core.guardrails")

router = APIRouter(tags=["guardrails"])


@router.get("/template", response_model=schemas.GuardrailTemplateResponse)
async def get_guardrail_template():
    """
    Get the markdown template for creating a new guardrail.

    Returns a complete template with YAML frontmatter structure and
    inline guidance for filling in guardrail content.
    """
    template = crud.get_guardrail_template()
    return schemas.GuardrailTemplateResponse(template=template)


@router.post("/", response_model=schemas.GuardrailResponse, status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    guardrail: schemas.GuardrailCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new guardrail with structured markdown content.

    The content field must contain properly formatted markdown with
    YAML frontmatter. Use GET /guardrails/template to obtain the template.

    Guardrails are organization-scoped and codify standards that guide
    requirement authoring across all projects.
    """
    try:
        db_guardrail = crud.create_guardrail(
            db=db,
            organization_id=guardrail.organization_id,
            content=guardrail.content,
            user_id=None,  # Solo mode - no user
        )
        logger.info(f"Created guardrail {db_guardrail.human_readable_id}")
        return db_guardrail
    except ValueError as e:
        logger.warning(f"Invalid guardrail content: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{guardrail_id}", response_model=schemas.GuardrailResponse)
async def get_guardrail(
    guardrail_id: str,
    db: Session = Depends(get_db),
):
    """
    Get a guardrail by UUID or human-readable ID.

    Supports both UUID (e.g., 'a1b2c3d4-...') and human-readable ID
    (e.g., 'GUARD-SEC-001', case-insensitive).

    Returns the complete guardrail including full markdown content.
    """
    guardrail = crud.get_guardrail(db, guardrail_id)
    if not guardrail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardrail not found: {guardrail_id}",
        )

    return guardrail


@router.patch("/{guardrail_id}", response_model=schemas.GuardrailResponse)
async def update_guardrail(
    guardrail_id: str,
    guardrail_update: schemas.GuardrailUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a guardrail with new markdown content.

    The content field must contain properly formatted markdown with
    YAML frontmatter. All fields in the frontmatter can be updated.
    """
    # Verify guardrail exists
    existing = crud.get_guardrail(db, guardrail_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardrail not found: {guardrail_id}",
        )

    try:
        updated_guardrail = crud.update_guardrail(
            db=db,
            guardrail_id=str(existing.id),
            content=guardrail_update.content,
            user_id=None,  # Solo mode - no user
        )
        logger.info(f"Updated guardrail {updated_guardrail.human_readable_id}")
        return updated_guardrail
    except ValueError as e:
        logger.warning(f"Invalid guardrail content: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/", response_model=schemas.GuardrailListResponse)
async def list_guardrails(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    category: Optional[str] = Query(None, description="Filter by category (security, architecture)"),
    enforcement_level: Optional[str] = Query(None, description="Filter by enforcement level"),
    applies_to: Optional[str] = Query(None, description="Filter by requirement type applicability"),
    status: Optional[str] = Query("active", description="Filter by status (active, draft, deprecated, all)"),
    search: Optional[str] = Query(None, description="Search in title and content"),
    db: Session = Depends(get_db),
):
    """
    List and filter guardrails with pagination.

    By default, returns only active guardrails. Use status='all' to see all.

    - **organization_id**: Filter by organization UUID
    - **category**: Filter by category (security, architecture)
    - **enforcement_level**: Filter by level (advisory, recommended, mandatory)
    - **applies_to**: Filter by requirement type (epic, component, feature, requirement)
    - **status**: Filter by status (defaults to 'active')
    - **search**: Search keyword in title/content
    """
    skip = (page - 1) * page_size

    guardrails, total = crud.list_guardrails(
        db=db,
        skip=skip,
        limit=page_size,
        organization_id=organization_id,
        category=category,
        enforcement_level=enforcement_level,
        applies_to=applies_to,
        status=status,
        search=search,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    return schemas.GuardrailListResponse(
        items=guardrails,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
