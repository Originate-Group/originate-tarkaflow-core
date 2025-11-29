"""Deployments API router (RAAS-FEAT-103).

Multi-environment deployment tracking for Release Work Items.
Tracks deployments across dev, staging, and prod environments.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ...models import (
    Deployment,
    DeploymentStatus,
    Environment,
    WorkItem,
    WorkItemType,
    WorkItemStatus,
    User,
    Requirement,
)
from ...schemas import (
    DeploymentCreate,
    DeploymentUpdate,
    DeploymentTransition,
    DeploymentResponse,
    DeploymentListItem,
    DeploymentListResponse,
    ReleaseDeploymentsResponse,
)
from ...versioning import update_deployed_version_pointer
from ..database import get_db
from ..dependencies import get_current_user_optional
from .work_items import resolve_work_item_id

logger = logging.getLogger("raas-core.deployments")

router = APIRouter(prefix="/deployments", tags=["deployments"])


def deployment_to_response(deployment: Deployment) -> DeploymentResponse:
    """Convert Deployment model to response schema."""
    release_hrid = None
    if deployment.release:
        release_hrid = deployment.release.human_readable_id

    deployed_by_email = None
    if deployment.deployed_by_user:
        deployed_by_email = deployment.deployed_by_user.email

    return DeploymentResponse(
        id=deployment.id,
        release_id=deployment.release_id,
        release_hrid=release_hrid,
        environment=deployment.environment,
        status=deployment.status,
        artifact_ref=deployment.artifact_ref,
        created_at=deployment.created_at,
        deployed_at=deployment.deployed_at,
        rolled_back_at=deployment.rolled_back_at,
        deployed_by_user_id=deployment.deployed_by_user_id,
        deployed_by_email=deployed_by_email,
    )


def deployment_to_list_item(deployment: Deployment) -> DeploymentListItem:
    """Convert Deployment model to list item schema."""
    release_hrid = None
    release_tag = None
    if deployment.release:
        release_hrid = deployment.release.human_readable_id
        release_tag = deployment.release.release_tag

    return DeploymentListItem(
        id=deployment.id,
        release_id=deployment.release_id,
        release_hrid=release_hrid,
        release_tag=release_tag,
        environment=deployment.environment,
        status=deployment.status,
        created_at=deployment.created_at,
        deployed_at=deployment.deployed_at,
    )


# =============================================================================
# Deployment Endpoints
# =============================================================================


@router.post("/", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
async def create_deployment(
    data: DeploymentCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Create a new deployment record for a Release.

    A Release can have one deployment per environment.
    """
    # Verify the release exists and is of type RELEASE
    release = db.query(WorkItem).filter(WorkItem.id == data.release_id).first()
    if not release:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {data.release_id}"
        )

    if release.work_item_type != WorkItemType.RELEASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Work Item '{release.human_readable_id}' is not a Release (type: {release.work_item_type.value})"
        )

    # Check for existing deployment in this environment
    existing = db.query(Deployment).filter(
        Deployment.release_id == data.release_id,
        Deployment.environment == data.environment
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Deployment already exists for {release.human_readable_id} in {data.environment.value}. "
                   f"Use PATCH to update status."
        )

    # Create deployment
    deployment = Deployment(
        release_id=data.release_id,
        environment=data.environment,
        status=DeploymentStatus.PENDING,
        artifact_ref=data.artifact_ref,
        deployed_by_user_id=current_user.id if current_user else None,
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment, ["release", "deployed_by_user"])

    logger.info(f"Created deployment for {release.human_readable_id} to {data.environment.value}")
    return deployment_to_response(deployment)


@router.get("/", response_model=DeploymentListResponse)
async def list_deployments(
    release_id: Optional[UUID] = None,
    environment: Optional[Environment] = None,
    status_filter: Optional[DeploymentStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List deployments with filtering."""
    query = db.query(Deployment).options(
        joinedload(Deployment.release),
    )

    if release_id:
        query = query.filter(Deployment.release_id == release_id)
    if environment:
        query = query.filter(Deployment.environment == environment)
    if status_filter:
        query = query.filter(Deployment.status == status_filter)

    total = query.count()

    # Order by created_at desc
    query = query.order_by(Deployment.created_at.desc())

    # Paginate
    offset = (page - 1) * page_size
    deployments = query.offset(offset).limit(page_size).all()

    return DeploymentListResponse(
        items=[deployment_to_list_item(d) for d in deployments],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/environment/{environment}", response_model=DeploymentListResponse)
async def list_deployments_by_environment(
    environment: Environment,
    status_filter: Optional[DeploymentStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List all deployments for a specific environment.

    Useful for answering "what's deployed to staging?"
    """
    query = db.query(Deployment).options(
        joinedload(Deployment.release),
    ).filter(Deployment.environment == environment)

    if status_filter:
        query = query.filter(Deployment.status == status_filter)

    total = query.count()
    query = query.order_by(Deployment.created_at.desc())

    offset = (page - 1) * page_size
    deployments = query.offset(offset).limit(page_size).all()

    return DeploymentListResponse(
        items=[deployment_to_list_item(d) for d in deployments],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get a deployment by ID."""
    deployment = db.query(Deployment).options(
        joinedload(Deployment.release),
        joinedload(Deployment.deployed_by_user),
    ).filter(Deployment.id == deployment_id).first()

    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment not found: {deployment_id}"
        )

    return deployment_to_response(deployment)


@router.post("/{deployment_id}/transition", response_model=DeploymentResponse)
async def transition_deployment(
    deployment_id: UUID,
    data: DeploymentTransition,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Transition a deployment to a new status.

    Valid transitions:
    - pending -> deploying
    - deploying -> success | failed
    - success -> rolled_back
    - deploying -> rolled_back (rare)

    When transitioning to SUCCESS in PROD environment, this triggers
    the update of requirement.deployed_version_id for all affected requirements.
    """
    deployment = db.query(Deployment).options(
        joinedload(Deployment.release),
        joinedload(Deployment.deployed_by_user),
    ).filter(Deployment.id == deployment_id).first()

    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment not found: {deployment_id}"
        )

    # Validate transition
    valid_transitions = {
        DeploymentStatus.PENDING: [DeploymentStatus.DEPLOYING, DeploymentStatus.FAILED],
        DeploymentStatus.DEPLOYING: [DeploymentStatus.SUCCESS, DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK],
        DeploymentStatus.SUCCESS: [DeploymentStatus.ROLLED_BACK],
        DeploymentStatus.FAILED: [],  # Terminal
        DeploymentStatus.ROLLED_BACK: [],  # Terminal
    }

    allowed = valid_transitions.get(deployment.status, [])
    if data.new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid deployment transition: {deployment.status.value} -> {data.new_status.value}. "
                   f"Allowed: {[s.value for s in allowed]}"
        )

    old_status = deployment.status
    deployment.status = data.new_status

    # Handle timestamps
    if data.new_status == DeploymentStatus.SUCCESS:
        deployment.deployed_at = datetime.utcnow()
        deployment.deployed_by_user_id = current_user.id if current_user else None
    elif data.new_status == DeploymentStatus.ROLLED_BACK:
        deployment.rolled_back_at = datetime.utcnow()

    # RAAS-FEAT-103: Only PROD SUCCESS triggers deployed_version_id update
    if data.new_status == DeploymentStatus.SUCCESS and deployment.environment == Environment.PROD:
        # Get all requirements affected by the included work items in this release
        release = deployment.release
        db.refresh(release, ["included_work_items"])

        updated_reqs = []
        for wi in release.included_work_items:
            db.refresh(wi, ["affected_requirements"])
            for req in wi.affected_requirements:
                if req.id not in [r.id for r in updated_reqs]:
                    # TARKA-FEAT-106: Pass release_id for status tag tracking
                    version = update_deployed_version_pointer(db, req, release_id=release.id)
                    if version:
                        updated_reqs.append(req)
                        logger.info(f"Updated deployed_version for {req.human_readable_id} to v{version.version_number}")

        logger.info(f"Production deployment {deployment.release.human_readable_id}: "
                    f"updated deployed_version for {len(updated_reqs)} requirements")

    db.commit()
    db.refresh(deployment, ["release", "deployed_by_user"])

    logger.info(f"Deployment {deployment.id} transitioned: {old_status.value} -> {data.new_status.value}")
    return deployment_to_response(deployment)


# =============================================================================
# Release Deployments View
# =============================================================================


@router.get("/release/{release_id}", response_model=ReleaseDeploymentsResponse)
async def get_release_deployments(
    release_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get all deployments for a Release across all environments.

    Accepts UUID or human-readable ID (e.g., 'REL-001').
    Returns deployment status per environment (dev, staging, prod).
    """
    # Resolve release
    release = resolve_work_item_id(db, release_id)
    if not release:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {release_id}"
        )

    if release.work_item_type != WorkItemType.RELEASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Work Item '{release.human_readable_id}' is not a Release"
        )

    # Get all deployments for this release
    deployments = db.query(Deployment).options(
        joinedload(Deployment.deployed_by_user),
    ).filter(Deployment.release_id == release.id).all()

    # Build response by environment
    deployment_map = {env.value: None for env in Environment}
    for d in deployments:
        d.release = release  # Attach for response conversion
        deployment_map[d.environment.value] = deployment_to_response(d)

    return ReleaseDeploymentsResponse(
        release_id=release.id,
        release_hrid=release.human_readable_id,
        release_tag=release.release_tag,
        deployments=deployment_map,
    )
