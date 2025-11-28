"""Work Items API router (CR-010: RAAS-COMP-075).

Work Items track implementation work and bridge requirements to code.
Types: IR (Implementation Request), CR (Change Request), BUG, TASK

Lifecycle: created -> in_progress -> implemented -> validated -> deployed -> completed
"""
import hashlib
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, joinedload

from ...models import (
    WorkItem,
    WorkItemHistory,
    WorkItemStatus,
    WorkItemType,
    Requirement,
    RequirementVersion,
    User,
    work_item_affects,
)
from ...schemas import (
    WorkItemCreate,
    WorkItemUpdate,
    WorkItemTransition,
    WorkItemResponse,
    WorkItemListItem,
    WorkItemListResponse,
    WorkItemHistoryResponse,
    RequirementVersionResponse,
    RequirementVersionListItem,
    RequirementVersionListResponse,
    RequirementVersionDiff,
)
from ...work_item_state_machine import (
    validate_work_item_transition,
    WorkItemStateTransitionError,
    get_allowed_work_item_transitions,
    triggers_cr_merge,
)
from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.work_items")

router = APIRouter(prefix="/work-items", tags=["work-items"])


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for conflict detection."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def resolve_requirement_id(db: Session, identifier: str) -> Optional[UUID]:
    """Resolve a requirement UUID or human-readable ID to UUID."""
    # Try as UUID first
    try:
        req_uuid = UUID(identifier)
        req = db.query(Requirement).filter(Requirement.id == req_uuid).first()
        if req:
            return req.id
    except ValueError:
        pass

    # Try as human-readable ID
    req = db.query(Requirement).filter(
        func.lower(Requirement.human_readable_id) == identifier.lower()
    ).first()
    if req:
        return req.id

    return None


def resolve_work_item_id(db: Session, identifier: str) -> Optional[WorkItem]:
    """Resolve a Work Item UUID or human-readable ID to WorkItem."""
    # Try as UUID first
    try:
        wi_uuid = UUID(identifier)
        wi = db.query(WorkItem).filter(WorkItem.id == wi_uuid).first()
        if wi:
            return wi
    except ValueError:
        pass

    # Try as human-readable ID
    wi = db.query(WorkItem).filter(
        func.lower(WorkItem.human_readable_id) == identifier.lower()
    ).first()
    return wi


def add_bidirectional_tags(db: Session, work_item: WorkItem, requirements: list[Requirement]):
    """Add bidirectional tags between Work Item and requirements (RAAS-FEAT-098)."""
    wi_hrid = work_item.human_readable_id

    # Add requirement HRIDs to Work Item tags
    req_hrids = [r.human_readable_id for r in requirements if r.human_readable_id]
    current_tags = set(work_item.tags or [])
    work_item.tags = list(current_tags.union(set(req_hrids)))

    # Add Work Item HRID to each requirement's tags
    for req in requirements:
        if wi_hrid:
            req_tags = set(req.tags or [])
            if wi_hrid not in req_tags:
                req.tags = list(req_tags.union({wi_hrid}))


def remove_bidirectional_tags(db: Session, work_item: WorkItem, requirements: list[Requirement]):
    """Remove bidirectional tags on Work Item completion (RAAS-FEAT-098)."""
    wi_hrid = work_item.human_readable_id

    # Remove Work Item HRID from each requirement's tags
    for req in requirements:
        if wi_hrid:
            req_tags = set(req.tags or [])
            if wi_hrid in req_tags:
                req_tags.discard(wi_hrid)
                req.tags = list(req_tags)


def create_work_item_history(
    db: Session,
    work_item: WorkItem,
    change_type: str,
    user_id: Optional[UUID],
    field_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    change_reason: Optional[str] = None,
):
    """Create a history entry for a Work Item change."""
    history = WorkItemHistory(
        work_item_id=work_item.id,
        change_type=change_type,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        changed_by_user_id=user_id,
        change_reason=change_reason,
    )
    db.add(history)


def execute_cr_merge(db: Session, work_item: WorkItem, user_id: Optional[UUID]) -> list[RequirementVersion]:
    """
    Execute CR merge: apply proposed content to requirements (RAAS-FEAT-099).

    When a CR Work Item transitions to COMPLETED:
    1. Validate baseline hashes match current requirement content
    2. Create new RequirementVersion for each affected requirement
    3. Update requirement content and current_version pointer
    4. Remove CR tag from requirements

    Returns list of created versions.
    Raises HTTPException on conflict.
    """
    if work_item.work_item_type != WorkItemType.CR:
        return []  # Only CRs trigger merge

    proposed_content = work_item.proposed_content or {}
    baseline_hashes = work_item.baseline_hashes or {}

    if not proposed_content:
        logger.info(f"CR {work_item.human_readable_id} has no proposed content to merge")
        return []

    created_versions = []

    for req_id_str, new_content in proposed_content.items():
        # Resolve requirement
        req_id = resolve_requirement_id(db, req_id_str)
        if not req_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Requirement {req_id_str} not found for CR merge"
            )

        req = db.query(Requirement).filter(Requirement.id == req_id).first()
        if not req:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Requirement {req_id_str} not found for CR merge"
            )

        # Validate baseline hash (conflict detection)
        baseline_hash = baseline_hashes.get(req_id_str)
        current_hash = req.content_hash or compute_content_hash(req.content or "")

        if baseline_hash and baseline_hash != current_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Conflict detected for requirement {req.human_readable_id or req_id_str}. "
                       f"Content changed since CR creation. Update CR or create new CR."
            )

        # Determine next version number
        max_version = db.query(func.max(RequirementVersion.version_number)).filter(
            RequirementVersion.requirement_id == req.id
        ).scalar() or 0
        next_version = max_version + 1

        # Create new version
        new_hash = compute_content_hash(new_content)
        version = RequirementVersion(
            requirement_id=req.id,
            version_number=next_version,
            content=new_content,
            content_hash=new_hash,
            title=req.title,  # Will be updated below
            description=req.description,
            source_work_item_id=work_item.id,
            change_reason=f"Applied from CR {work_item.human_readable_id}",
            created_by_user_id=user_id,
        )
        db.add(version)
        db.flush()  # Get the version ID

        # Update requirement
        req.content = new_content
        req.content_hash = new_hash
        req.current_version_id = version.id
        req.updated_at = datetime.utcnow()

        created_versions.append(version)
        logger.info(f"Created version {next_version} for requirement {req.human_readable_id} from CR {work_item.human_readable_id}")

    # Remove CR tags from affected requirements
    remove_bidirectional_tags(db, work_item, work_item.affected_requirements)

    return created_versions


def work_item_to_response(work_item: WorkItem, db: Session) -> WorkItemResponse:
    """Convert WorkItem model to response schema."""
    assignee_email = None
    assignee_name = None
    if work_item.assignee:
        assignee_email = work_item.assignee.email
        assignee_name = work_item.assignee.full_name

    created_by_email = None
    if work_item.created_by_user:
        created_by_email = work_item.created_by_user.email

    affected_ids = [r.id for r in work_item.affected_requirements]

    return WorkItemResponse(
        id=work_item.id,
        human_readable_id=work_item.human_readable_id,
        organization_id=work_item.organization_id,
        project_id=work_item.project_id,
        work_item_type=work_item.work_item_type,
        title=work_item.title,
        description=work_item.description,
        status=work_item.status,
        priority=work_item.priority,
        assigned_to=work_item.assigned_to,
        assignee_email=assignee_email,
        assignee_name=assignee_name,
        tags=work_item.tags or [],
        affects_count=len(affected_ids),
        affected_requirement_ids=affected_ids,
        proposed_content=work_item.proposed_content,
        baseline_hashes=work_item.baseline_hashes,
        implementation_refs=work_item.implementation_refs,
        created_at=work_item.created_at,
        updated_at=work_item.updated_at,
        created_by=work_item.created_by_user_id,
        created_by_email=created_by_email,
        completed_at=work_item.completed_at,
        cancelled_at=work_item.cancelled_at,
    )


def work_item_to_list_item(work_item: WorkItem) -> WorkItemListItem:
    """Convert WorkItem model to list item schema."""
    assignee_email = None
    if work_item.assignee:
        assignee_email = work_item.assignee.email

    return WorkItemListItem(
        id=work_item.id,
        human_readable_id=work_item.human_readable_id,
        organization_id=work_item.organization_id,
        project_id=work_item.project_id,
        work_item_type=work_item.work_item_type,
        title=work_item.title,
        status=work_item.status,
        priority=work_item.priority,
        assigned_to=work_item.assigned_to,
        assignee_email=assignee_email,
        tags=work_item.tags or [],
        affects_count=len(work_item.affected_requirements) if work_item.affected_requirements else 0,
        created_at=work_item.created_at,
        updated_at=work_item.updated_at,
    )


# =============================================================================
# Work Item Endpoints
# =============================================================================


@router.post("/", response_model=WorkItemResponse, status_code=status.HTTP_201_CREATED)
async def create_work_item(
    data: WorkItemCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Create a new Work Item.

    Work Items track implementation work and link to affected requirements.
    """
    # Create the Work Item
    work_item = WorkItem(
        organization_id=data.organization_id,
        project_id=data.project_id,
        work_item_type=data.work_item_type,
        title=data.title,
        description=data.description,
        status=WorkItemStatus.CREATED,
        priority=data.priority,
        assigned_to=data.assigned_to,
        tags=data.tags,
        proposed_content=data.proposed_content,
        created_by_user_id=current_user.id,
    )
    db.add(work_item)
    db.flush()  # Get the ID and human_readable_id

    # Resolve and link affected requirements
    affected_reqs = []
    baseline_hashes = {}

    for req_identifier in data.affects:
        req_id = resolve_requirement_id(db, req_identifier)
        if not req_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Requirement not found: {req_identifier}"
            )
        req = db.query(Requirement).filter(Requirement.id == req_id).first()
        if req:
            affected_reqs.append(req)
            # Store baseline hash for conflict detection
            if req.content:
                baseline_hashes[str(req.id)] = req.content_hash or compute_content_hash(req.content)

    # Link affected requirements
    work_item.affected_requirements = affected_reqs

    # Store baseline hashes for CRs
    if data.work_item_type == WorkItemType.CR and baseline_hashes:
        work_item.baseline_hashes = baseline_hashes

    # Add bidirectional tags
    if affected_reqs:
        add_bidirectional_tags(db, work_item, affected_reqs)

    # Create history entry
    create_work_item_history(
        db, work_item, "created", current_user.id,
        new_value=f"{work_item.work_item_type.value}: {work_item.title}"
    )

    db.commit()
    db.refresh(work_item)

    logger.info(f"Created Work Item {work_item.human_readable_id}: {work_item.title}")
    return work_item_to_response(work_item, db)


@router.get("/", response_model=WorkItemListResponse)
async def list_work_items(
    organization_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    work_item_type: Optional[WorkItemType] = None,
    status: Optional[WorkItemStatus] = None,
    assigned_to: Optional[UUID] = None,
    search: Optional[str] = None,
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    include_completed: bool = Query(False, description="Include completed/cancelled items"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List Work Items with filtering and pagination."""
    query = db.query(WorkItem).options(
        joinedload(WorkItem.assignee),
        joinedload(WorkItem.affected_requirements),
    )

    # Apply filters
    if organization_id:
        query = query.filter(WorkItem.organization_id == organization_id)
    if project_id:
        query = query.filter(WorkItem.project_id == project_id)
    if work_item_type:
        query = query.filter(WorkItem.work_item_type == work_item_type)
    if status:
        query = query.filter(WorkItem.status == status)
    if assigned_to:
        query = query.filter(WorkItem.assigned_to == assigned_to)

    # Exclude completed/cancelled by default
    if not include_completed:
        query = query.filter(WorkItem.status.notin_([
            WorkItemStatus.COMPLETED,
            WorkItemStatus.CANCELLED,
        ]))

    # Search in title and description
    if search:
        search_filter = or_(
            WorkItem.title.ilike(f"%{search}%"),
            WorkItem.description.ilike(f"%{search}%"),
            WorkItem.human_readable_id.ilike(f"%{search}%"),
        )
        query = query.filter(search_filter)

    # Filter by tags
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        for tag in tag_list:
            query = query.filter(WorkItem.tags.contains([tag]))

    # Get total count
    total = query.count()

    # Order by priority and creation date
    query = query.order_by(WorkItem.created_at.desc())

    # Paginate
    offset = (page - 1) * page_size
    work_items = query.offset(offset).limit(page_size).all()

    return WorkItemListResponse(
        items=[work_item_to_list_item(wi) for wi in work_items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{work_item_id}", response_model=WorkItemResponse)
async def get_work_item(
    work_item_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get a Work Item by UUID or human-readable ID."""
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    # Eager load relationships
    db.refresh(work_item, ["assignee", "created_by_user", "affected_requirements"])

    return work_item_to_response(work_item, db)


@router.patch("/{work_item_id}", response_model=WorkItemResponse)
async def update_work_item(
    work_item_id: str,
    data: WorkItemUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Update a Work Item."""
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    # Track changes for history
    changes = []

    # Update fields
    if data.title is not None and data.title != work_item.title:
        changes.append(("title", work_item.title, data.title))
        work_item.title = data.title

    if data.description is not None and data.description != work_item.description:
        changes.append(("description", work_item.description, data.description))
        work_item.description = data.description

    if data.priority is not None and data.priority != work_item.priority:
        changes.append(("priority", work_item.priority, data.priority))
        work_item.priority = data.priority

    if data.assigned_to is not None and data.assigned_to != work_item.assigned_to:
        changes.append(("assigned_to", str(work_item.assigned_to) if work_item.assigned_to else None, str(data.assigned_to)))
        work_item.assigned_to = data.assigned_to

    if data.tags is not None:
        work_item.tags = data.tags

    if data.proposed_content is not None:
        work_item.proposed_content = data.proposed_content

    if data.implementation_refs is not None:
        work_item.implementation_refs = data.implementation_refs

    # Handle status transition
    if data.status is not None and data.status != work_item.status:
        try:
            validate_work_item_transition(work_item.status, data.status)
        except WorkItemStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        old_status = work_item.status
        work_item.status = data.status

        # Handle completion timestamps
        if data.status == WorkItemStatus.COMPLETED:
            work_item.completed_at = datetime.utcnow()
            # Execute CR merge if applicable
            if triggers_cr_merge(old_status, data.status):
                execute_cr_merge(db, work_item, current_user.id)
        elif data.status == WorkItemStatus.CANCELLED:
            work_item.cancelled_at = datetime.utcnow()

        changes.append(("status", old_status.value, data.status.value))

    # Handle affects list update
    if data.affects is not None:
        # Remove old tags
        remove_bidirectional_tags(db, work_item, work_item.affected_requirements)

        # Resolve new requirements
        new_affected = []
        new_baseline_hashes = {}
        for req_identifier in data.affects:
            req_id = resolve_requirement_id(db, req_identifier)
            if not req_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Requirement not found: {req_identifier}"
                )
            req = db.query(Requirement).filter(Requirement.id == req_id).first()
            if req:
                new_affected.append(req)
                if req.content:
                    new_baseline_hashes[str(req.id)] = req.content_hash or compute_content_hash(req.content)

        work_item.affected_requirements = new_affected
        if work_item.work_item_type == WorkItemType.CR:
            work_item.baseline_hashes = new_baseline_hashes

        # Add new tags
        add_bidirectional_tags(db, work_item, new_affected)

    work_item.updated_at = datetime.utcnow()
    work_item.updated_by_user_id = current_user.id

    # Create history entries
    for field, old_val, new_val in changes:
        change_type = "status_changed" if field == "status" else "updated"
        create_work_item_history(
            db, work_item, change_type, current_user.id,
            field_name=field,
            old_value=str(old_val) if old_val else None,
            new_value=str(new_val) if new_val else None,
        )

    db.commit()
    db.refresh(work_item, ["assignee", "created_by_user", "affected_requirements"])

    return work_item_to_response(work_item, db)


@router.post("/{work_item_id}/transition", response_model=WorkItemResponse)
async def transition_work_item(
    work_item_id: str,
    data: WorkItemTransition,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Transition a Work Item to a new status."""
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    # Validate transition
    try:
        validate_work_item_transition(work_item.status, data.new_status)
    except WorkItemStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    old_status = work_item.status
    work_item.status = data.new_status
    work_item.updated_at = datetime.utcnow()
    work_item.updated_by_user_id = current_user.id

    # Handle completion timestamps
    if data.new_status == WorkItemStatus.COMPLETED:
        work_item.completed_at = datetime.utcnow()
        # Execute CR merge if applicable
        if triggers_cr_merge(old_status, data.new_status):
            execute_cr_merge(db, work_item, current_user.id)
    elif data.new_status == WorkItemStatus.CANCELLED:
        work_item.cancelled_at = datetime.utcnow()

    # Create history entry
    create_work_item_history(
        db, work_item, "status_changed", current_user.id,
        field_name="status",
        old_value=old_status.value,
        new_value=data.new_status.value,
    )

    db.commit()
    db.refresh(work_item, ["assignee", "created_by_user", "affected_requirements"])

    logger.info(f"Work Item {work_item.human_readable_id} transitioned: {old_status.value} -> {data.new_status.value}")
    return work_item_to_response(work_item, db)


@router.get("/{work_item_id}/history", response_model=list[WorkItemHistoryResponse])
async def get_work_item_history(
    work_item_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get Work Item change history."""
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    history = db.query(WorkItemHistory).options(
        joinedload(WorkItemHistory.changed_by_user)
    ).filter(
        WorkItemHistory.work_item_id == work_item.id
    ).order_by(
        WorkItemHistory.changed_at.desc()
    ).limit(limit).all()

    return [
        WorkItemHistoryResponse(
            id=h.id,
            work_item_id=h.work_item_id,
            change_type=h.change_type,
            field_name=h.field_name,
            old_value=h.old_value,
            new_value=h.new_value,
            changed_by=h.changed_by_user_id,
            changed_by_email=h.changed_by_user.email if h.changed_by_user else None,
            changed_at=h.changed_at,
            change_reason=h.change_reason,
        )
        for h in history
    ]


@router.get("/{work_item_id}/transitions", response_model=list[str])
async def get_allowed_transitions(
    work_item_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get allowed status transitions for a Work Item."""
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    allowed = get_allowed_work_item_transitions(work_item.status)
    return [s.value for s in allowed]


# =============================================================================
# Requirement Version Endpoints
# =============================================================================


@router.get("/requirements/{requirement_id}/versions", response_model=RequirementVersionListResponse)
async def list_requirement_versions(
    requirement_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List all versions of a requirement."""
    # Resolve requirement ID
    req_uuid = resolve_requirement_id(db, requirement_id)
    if not req_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement not found: {requirement_id}"
        )

    req = db.query(Requirement).filter(Requirement.id == req_uuid).first()

    versions = db.query(RequirementVersion).options(
        joinedload(RequirementVersion.source_work_item),
        joinedload(RequirementVersion.created_by_user),
    ).filter(
        RequirementVersion.requirement_id == req_uuid
    ).order_by(
        RequirementVersion.version_number.desc()
    ).all()

    items = []
    for v in versions:
        wi_hrid = v.source_work_item.human_readable_id if v.source_work_item else None
        created_by_email = v.created_by_user.email if v.created_by_user else None
        items.append(RequirementVersionListItem(
            id=v.id,
            requirement_id=v.requirement_id,
            version_number=v.version_number,
            content_hash=v.content_hash,
            title=v.title,
            source_work_item_id=v.source_work_item_id,
            source_work_item_hrid=wi_hrid,
            created_at=v.created_at,
            created_by_email=created_by_email,
        ))

    # Get current version number
    current_version_num = None
    if req.current_version_id:
        current_ver = db.query(RequirementVersion).filter(
            RequirementVersion.id == req.current_version_id
        ).first()
        if current_ver:
            current_version_num = current_ver.version_number

    return RequirementVersionListResponse(
        items=items,
        total=len(items),
        requirement_id=req_uuid,
        current_version_number=current_version_num,
    )


@router.get("/requirements/{requirement_id}/versions/{version_number}", response_model=RequirementVersionResponse)
async def get_requirement_version(
    requirement_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get a specific version of a requirement."""
    req_uuid = resolve_requirement_id(db, requirement_id)
    if not req_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement not found: {requirement_id}"
        )

    version = db.query(RequirementVersion).options(
        joinedload(RequirementVersion.source_work_item),
        joinedload(RequirementVersion.created_by_user),
    ).filter(
        RequirementVersion.requirement_id == req_uuid,
        RequirementVersion.version_number == version_number,
    ).first()

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found for requirement {requirement_id}"
        )

    wi_hrid = version.source_work_item.human_readable_id if version.source_work_item else None
    created_by_email = version.created_by_user.email if version.created_by_user else None

    return RequirementVersionResponse(
        id=version.id,
        requirement_id=version.requirement_id,
        version_number=version.version_number,
        content=version.content,
        content_hash=version.content_hash,
        title=version.title,
        description=version.description,
        source_work_item_id=version.source_work_item_id,
        source_work_item_hrid=wi_hrid,
        change_reason=version.change_reason,
        created_at=version.created_at,
        created_by=version.created_by_user_id,
        created_by_email=created_by_email,
    )


@router.get("/requirements/{requirement_id}/versions/diff", response_model=RequirementVersionDiff)
async def diff_requirement_versions(
    requirement_id: str,
    from_version: int = Query(..., description="Source version number"),
    to_version: int = Query(..., description="Target version number"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get diff between two versions of a requirement."""
    req_uuid = resolve_requirement_id(db, requirement_id)
    if not req_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement not found: {requirement_id}"
        )

    # Get both versions
    from_ver = db.query(RequirementVersion).filter(
        RequirementVersion.requirement_id == req_uuid,
        RequirementVersion.version_number == from_version,
    ).first()

    to_ver = db.query(RequirementVersion).filter(
        RequirementVersion.requirement_id == req_uuid,
        RequirementVersion.version_number == to_version,
    ).first()

    if not from_ver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {from_version} not found"
        )

    if not to_ver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {to_version} not found"
        )

    # Generate simple summary
    changes = []
    if from_ver.title != to_ver.title:
        changes.append(f"Title changed from '{from_ver.title}' to '{to_ver.title}'")
    if from_ver.content_hash != to_ver.content_hash:
        changes.append("Content modified")

    summary = "; ".join(changes) if changes else "No changes detected"

    return RequirementVersionDiff(
        requirement_id=req_uuid,
        from_version=from_version,
        to_version=to_version,
        from_content=from_ver.content,
        to_content=to_ver.content,
        from_title=from_ver.title,
        to_title=to_ver.title,
        changes_summary=summary,
    )
