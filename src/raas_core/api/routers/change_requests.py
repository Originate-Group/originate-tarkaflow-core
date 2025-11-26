"""API endpoints for change request management with RBAC permission checks.

Change Requests (CR) gate updates to requirements that have passed review status.
This ensures traceability and controlled changes in production systems.

CR Lifecycle: draft -> review -> approved -> completed

Reference: RAAS-COMP-068, RAAS-FEAT-077, RAAS-FEAT-078
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session
from math import ceil

from raas_core import crud, schemas, models
from raas_core.permissions import (
    check_org_permission,
    PermissionDeniedError,
)

from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.change_requests")


def _handle_permission_error(e: PermissionDeniedError) -> HTTPException:
    """Convert PermissionDeniedError to HTTPException with proper 403 response."""
    return HTTPException(
        status_code=403,
        detail={
            "error": "permission_denied",
            "message": e.message,
            "required_role": e.required_role,
            "current_role": e.current_role,
            "resource_type": e.resource_type,
        }
    )


def _format_change_request_response(cr: models.ChangeRequest) -> dict:
    """Format a ChangeRequest model into a response dict with computed fields."""
    return {
        "id": cr.id,
        "human_readable_id": cr.human_readable_id,
        "organization_id": cr.organization_id,
        "justification": cr.justification,
        "status": cr.status,
        "requestor_id": cr.requestor_id,
        "requestor_email": cr.requestor.email if cr.requestor else None,
        "approved_at": cr.approved_at,
        "approved_by_id": cr.approved_by_id,
        "approved_by_email": cr.approved_by.email if cr.approved_by else None,
        "completed_at": cr.completed_at,
        "created_at": cr.created_at,
        "updated_at": cr.updated_at,
        "affects": [req.id for req in cr.affects] if cr.affects else [],
        "affects_count": cr.affects_count,
        "modifications_count": cr.modifications_count,
    }


router = APIRouter(tags=["change-requests"])


@router.post("/", response_model=schemas.ChangeRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_change_request(
    cr: schemas.ChangeRequestCreate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Create a new change request with justification and affected requirements.

    Requires Member role or higher in the organization.

    The 'affects' list declares which requirements this CR intends to modify.
    This scope is immutable after the CR moves past draft status.

    Change requests start in 'draft' status and must be transitioned through
    the lifecycle: draft -> review -> approved -> completed.
    """
    # In team mode, verify user has at least member role in the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, cr.organization_id,
                models.MemberRole.MEMBER, "create change requests"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    try:
        db_cr = crud.create_change_request(
            db=db,
            organization_id=cr.organization_id,
            justification=cr.justification,
            affects=cr.affects,
            user_id=current_user.id if current_user else None,
        )
        logger.info(f"Created change request {db_cr.human_readable_id}")
        return _format_change_request_response(db_cr)
    except ValueError as e:
        logger.warning(f"Invalid change request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{cr_id}", response_model=schemas.ChangeRequestResponse)
async def get_change_request(
    cr_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Get a change request by UUID or human-readable ID.

    Requires membership in the change request's organization.

    Supports both UUID (e.g., 'a1b2c3d4-...') and human-readable ID
    (e.g., 'CR-001', case-insensitive).
    """
    cr = crud.get_change_request(db, cr_id)
    if not cr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Change request not found: {cr_id}",
        )

    # In team mode, verify user is a member of the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, cr.organization_id,
                models.MemberRole.VIEWER, "view change request"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    return _format_change_request_response(cr)


@router.post("/{cr_id}/transition", response_model=schemas.ChangeRequestResponse)
async def transition_change_request(
    cr_id: str,
    transition: schemas.ChangeRequestTransition,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Transition a change request to a new status.

    CR Lifecycle: draft -> review -> approved -> completed

    Valid transitions:
    - draft -> review (submit for review)
    - review -> approved (approve the CR)
    - review -> draft (send back for revision)
    - approved -> completed (mark as done)

    Moving to 'approved' sets approved_at and approved_by_id.
    Moving to 'completed' sets completed_at.

    Requires Admin or Owner role for approval transitions.
    """
    # Verify change request exists
    existing = crud.get_change_request(db, cr_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Change request not found: {cr_id}",
        )

    # In team mode, verify permissions based on transition type
    if current_user:
        # Approval transitions require admin role
        required_role = models.MemberRole.ADMIN if transition.new_status == models.ChangeRequestStatus.APPROVED else models.MemberRole.MEMBER
        action = "approve change request" if transition.new_status == models.ChangeRequestStatus.APPROVED else "transition change request"
        try:
            check_org_permission(
                db, current_user.id, existing.organization_id,
                required_role, action
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    try:
        updated_cr = crud.transition_change_request(
            db=db,
            cr_id=str(existing.id),
            new_status=transition.new_status,
            user_id=current_user.id if current_user else None,
        )
        logger.info(f"Transitioned change request {updated_cr.human_readable_id} to {transition.new_status.value}")
        return _format_change_request_response(updated_cr)
    except ValueError as e:
        logger.warning(f"Invalid transition: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{cr_id}/complete", response_model=schemas.ChangeRequestResponse)
async def complete_change_request(
    cr_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Mark an approved change request as completed.

    The CR must be in 'approved' status. This action:
    - Sets status to 'completed'
    - Sets completed_at timestamp

    After completion, the CR cannot be modified or used for further updates.
    """
    # Verify change request exists
    existing = crud.get_change_request(db, cr_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Change request not found: {cr_id}",
        )

    # In team mode, verify user has member role in the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, existing.organization_id,
                models.MemberRole.MEMBER, "complete change request"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    try:
        updated_cr = crud.transition_change_request(
            db=db,
            cr_id=str(existing.id),
            new_status=models.ChangeRequestStatus.COMPLETED,
            user_id=current_user.id if current_user else None,
        )
        logger.info(f"Completed change request {updated_cr.human_readable_id}")
        return _format_change_request_response(updated_cr)
    except ValueError as e:
        logger.warning(f"Invalid completion: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/", response_model=schemas.ChangeRequestListResponse)
async def list_change_requests(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    status: Optional[str] = Query(None, description="Filter by status (draft, review, approved, completed)"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List and filter change requests with pagination.

    In team mode, returns only change requests from organizations where the user is a member.

    - **organization_id**: Filter by organization UUID
    - **status**: Filter by status (draft, review, approved, completed)
    """
    skip = (page - 1) * page_size

    change_requests, total = crud.list_change_requests(
        db=db,
        skip=skip,
        limit=page_size,
        organization_id=organization_id,
        status=status,
        user_id=current_user.id if current_user else None,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    # Format response items
    items = []
    for cr in change_requests:
        items.append({
            "id": cr.id,
            "human_readable_id": cr.human_readable_id,
            "organization_id": cr.organization_id,
            "justification": cr.justification,
            "status": cr.status,
            "requestor_email": cr.requestor.email if cr.requestor else None,
            "created_at": cr.created_at,
            "updated_at": cr.updated_at,
            "affects_count": cr.affects_count,
            "modifications_count": cr.modifications_count,
        })

    return schemas.ChangeRequestListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
