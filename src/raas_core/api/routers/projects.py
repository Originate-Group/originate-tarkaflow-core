"""Projects API endpoints (solo mode - no authentication)."""
import logging
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from raas_core import crud, schemas, models

from ..database import get_db

logger = logging.getLogger("raas-core.projects")

router = APIRouter(tags=["projects"])


@router.post("/", response_model=schemas.ProjectResponse, status_code=201)
def create_project(
    project: schemas.ProjectCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new project.

    - **organization_id**: Parent organization UUID
    - **name**: Project name (outcome-focused, e.g., "Customer Self-Service Portal")
    - **slug**: 3-4 uppercase alphanumeric characters (e.g., "RAAS", "WEB", "API")
    - **description**: Optional description
    - **visibility**: Project visibility (public or private, default: public)
    - **status**: Project status (default: active)
    """
    # Check if slug already exists within this organization
    existing = crud.get_project_by_slug(db, project.organization_id, project.slug)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Project with slug '{project.slug}' already exists in this organization"
        )

    try:
        result = crud.create_project(
            db=db,
            organization_id=project.organization_id,
            name=project.name,
            slug=project.slug,
            description=project.description,
            visibility=project.visibility,
            status=project.status,
            value_statement=project.value_statement,
            project_type=project.project_type,
            tags=project.tags,
            settings=project.settings,
            user_id=None,  # Solo mode - no user
        )
        logger.info(f"Created project '{result.name}' ({result.slug}) (ID: {result.id})")
        return result
    except Exception as e:
        logger.error(f"Error creating project: {e}", exc_info=True)
        raise


@router.get("/", response_model=schemas.ProjectListResponse)
def list_projects(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    status: Optional[models.ProjectStatus] = Query(None, description="Filter by status"),
    visibility: Optional[models.ProjectVisibility] = Query(None, description="Filter by visibility"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    db: Session = Depends(get_db),
):
    """
    List projects with optional filtering and pagination.

    - **page**: Page number (starts at 1)
    - **page_size**: Number of items per page (1-100)
    - **organization_id**: Filter by organization
    - **status**: Filter by project status
    - **visibility**: Filter by visibility (public/private)
    - **search**: Search text in name and description
    """
    skip = (page - 1) * page_size

    # Get all projects (no user filtering in solo mode)
    projects, total = crud.get_projects(
        db=db,
        skip=skip,
        limit=page_size,
        organization_id=organization_id,
        status_filter=status,
        visibility_filter=visibility,
        search=search,
    )

    return schemas.ProjectListResponse(
        items=projects,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/{project_id}", response_model=schemas.ProjectResponse)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Get a specific project by ID.
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.put("/{project_id}", response_model=schemas.ProjectResponse)
def update_project(
    project_id: UUID,
    project_update: schemas.ProjectUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a project.

    - **name**: New project name (optional)
    - **description**: New description (optional)
    - **status**: New status (optional)
    - **visibility**: New visibility (optional)
    - **tags**: New tags list (optional)
    """
    # Check project exists
    existing = crud.get_project(db, project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        project = crud.update_project(
            db,
            project_id,
            name=project_update.name,
            description=project_update.description,
            visibility=project_update.visibility,
            status=project_update.status,
            value_statement=project_update.value_statement,
            project_type=project_update.project_type,
            tags=project_update.tags,
            settings=project_update.settings,
            organization_id=project_update.organization_id,
        )
        return project
    except Exception as e:
        logger.error(f"Error updating project {project_id}: {e}", exc_info=True)
        raise


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Delete a project and all its requirements (cascading delete).

    Use with caution!
    """
    # Check project exists
    existing = crud.get_project(db, project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")

    success = crud.delete_project(db, project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")


# Project Members endpoints

@router.get("/{project_id}/members", response_model=list[schemas.ProjectMemberResponse])
def list_project_members(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    """
    List all members of a project.
    """
    # Check project exists
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return crud.get_project_members(db, project_id)


@router.post("/{project_id}/members", response_model=schemas.ProjectMemberResponse, status_code=201)
def add_project_member(
    project_id: UUID,
    member: schemas.ProjectMemberCreate,
    db: Session = Depends(get_db),
):
    """
    Add a user to a project.

    - **user_id**: UUID of the user to add
    - **role**: Project role (admin, editor, viewer)
    """
    # Check project exists
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = crud.add_project_member(
            db=db,
            project_id=project_id,
            user_id=member.user_id,
            role=member.role,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{project_id}/members/{user_id}", response_model=schemas.ProjectMemberResponse)
def update_project_member(
    project_id: UUID,
    user_id: UUID,
    member_update: schemas.ProjectMemberUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a project member's role.

    - **role**: New project role
    """
    # Check project exists
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = crud.update_project_member_role(
            db=db,
            project_id=project_id,
            user_id=user_id,
            role=member_update.role,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Remove a user from a project.
    """
    # Check project exists
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    success = crud.remove_project_member(
        db=db,
        project_id=project_id,
        user_id=user_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
