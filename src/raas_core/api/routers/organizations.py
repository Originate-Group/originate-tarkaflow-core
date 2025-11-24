"""Organizations API endpoints (solo mode - no authentication)."""
import logging
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from raas_core import crud, schemas, models

from ..database import get_db

logger = logging.getLogger("raas-core.organizations")

router = APIRouter(tags=["organizations"])


@router.post("/", response_model=schemas.OrganizationResponse, status_code=201)
def create_organization(
    organization: schemas.OrganizationCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new organization.

    - **name**: Organization name
    - **slug**: URL-friendly slug (lowercase, alphanumeric, hyphens)
    - **settings**: Optional JSON settings
    """
    # Check if slug already exists
    existing = crud.get_organization_by_slug(db, organization.slug)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Organization with slug '{organization.slug}' already exists"
        )

    try:
        result = crud.create_organization(
            db=db,
            name=organization.name,
            slug=organization.slug,
            settings=organization.settings,
        )
        logger.info(f"Created organization '{result.name}' (ID: {result.id})")
        return result
    except Exception as e:
        logger.error(f"Error creating organization: {e}", exc_info=True)
        raise


@router.get("/", response_model=schemas.OrganizationListResponse)
def list_organizations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    List all organizations with pagination (solo mode - no filtering).
    """
    # Calculate skip
    skip = (page - 1) * page_size

    # Get all organizations (no user filtering in solo mode)
    organizations, total = crud.get_organizations(
        db=db,
        skip=skip,
        limit=page_size,
    )

    return schemas.OrganizationListResponse(
        items=organizations,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/{organization_id}", response_model=schemas.OrganizationResponse)
def get_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Get a specific organization by ID.
    """
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    return organization


@router.put("/{organization_id}", response_model=schemas.OrganizationResponse)
def update_organization(
    organization_id: UUID,
    organization_update: schemas.OrganizationUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an organization.

    - **name**: New organization name (optional)
    - **settings**: New settings (optional)
    """
    # Check organization exists
    existing = crud.get_organization(db, organization_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        organization = crud.update_organization(
            db,
            organization_id,
            name=organization_update.name,
            settings=organization_update.settings,
        )
        return organization
    except Exception as e:
        logger.error(f"Error updating organization {organization_id}: {e}", exc_info=True)
        raise


@router.delete("/{organization_id}", status_code=204)
def delete_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Delete an organization and all its data (cascading delete).

    Use with caution! This will delete all projects, requirements, and members.
    """
    # Check organization exists
    existing = crud.get_organization(db, organization_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Organization not found")

    success = crud.delete_organization(db, organization_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organization not found")


# Organization Members endpoints

@router.get("/{organization_id}/members", response_model=list[schemas.OrganizationMemberResponse])
def list_organization_members(
    organization_id: UUID,
    db: Session = Depends(get_db),
):
    """
    List all members of an organization.
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    return crud.get_organization_members(db, organization_id)


@router.post("/{organization_id}/members", response_model=schemas.OrganizationMemberResponse, status_code=201)
def add_organization_member(
    organization_id: UUID,
    member: schemas.OrganizationMemberCreate,
    db: Session = Depends(get_db),
):
    """
    Add a user to an organization.

    - **user_id**: UUID of the user to add
    - **role**: Organization role (owner, admin, member, viewer)
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        result = crud.add_organization_member(
            db=db,
            organization_id=organization_id,
            user_id=member.user_id,
            role=member.role,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{organization_id}/members/{user_id}", response_model=schemas.OrganizationMemberResponse)
def update_organization_member(
    organization_id: UUID,
    user_id: UUID,
    member_update: schemas.OrganizationMemberUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an organization member's role.

    - **role**: New organization role
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        result = crud.update_organization_member_role(
            db=db,
            organization_id=organization_id,
            user_id=user_id,
            role=member_update.role,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{organization_id}/members/{user_id}", status_code=204)
def remove_organization_member(
    organization_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Remove a user from an organization.
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    success = crud.remove_organization_member(
        db=db,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
