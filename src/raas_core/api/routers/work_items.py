"""Work Items API router (CR-010: RAAS-COMP-075).

Work Items track implementation work and bridge requirements to code.
Types: IR (Implementation Request), CR (Change Request), BUG, TASK

Lifecycle: created -> in_progress -> implemented -> validated -> deployed -> completed
"""
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
    RequirementHistory,
    ChangeType,
    User,
    work_item_affects,
    work_item_target_versions,
    release_includes,
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
    TargetVersionSummary,
    DriftWarning,
    DriftCheckResponse,
)
from ...work_item_state_machine import (
    validate_work_item_transition,
    WorkItemStateTransitionError,
    get_allowed_work_item_transitions,
    triggers_cr_merge,
)
from ...versioning import (
    compute_content_hash,
    update_deployed_version_pointer,
    resolve_version,
)
from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.work_items")

router = APIRouter(prefix="/work-items", tags=["work-items"])


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
    2. Create new RequirementVersion for each affected requirement with approved status
    3. Update requirement content (CR-006: no current_version_id to update)
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

        # Create new version with approved status (CR-006: status on versions)
        new_hash = compute_content_hash(new_content)
        version = RequirementVersion(
            requirement_id=req.id,
            version_number=next_version,
            status=LifecycleStatus.APPROVED,  # CR-006: CR merge creates approved version
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

        # Update requirement (CR-006: no current_version_id to update)
        req.content = new_content
        req.content_hash = new_hash
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

    # RAAS-FEAT-099: Build target versions summary
    target_version_summaries = []
    for tv in work_item.target_versions:
        target_version_summaries.append(TargetVersionSummary(
            id=tv.id,
            requirement_id=tv.requirement_id,
            requirement_human_readable_id=tv.requirement.human_readable_id if tv.requirement else None,
            version_number=tv.version_number,
            title=tv.title,
        ))

    # Release-specific: get included work item IDs (RAAS-FEAT-102)
    included_ids = []
    if work_item.work_item_type == WorkItemType.RELEASE:
        included_ids = [wi.id for wi in work_item.included_work_items]

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
        target_versions=target_version_summaries,
        proposed_content=work_item.proposed_content,
        baseline_hashes=work_item.baseline_hashes,
        implementation_refs=work_item.implementation_refs,
        release_tag=work_item.release_tag,
        github_release_url=work_item.github_release_url,
        included_work_item_ids=included_ids,
        includes_count=len(included_ids),
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
        # Release-specific fields (RAAS-FEAT-102)
        release_tag=data.release_tag if data.work_item_type == WorkItemType.RELEASE else None,
        github_release_url=data.github_release_url if data.work_item_type == WorkItemType.RELEASE else None,
    )
    db.add(work_item)
    db.flush()  # Get the ID and human_readable_id

    # For Releases: resolve and link included work items (RAAS-FEAT-102)
    if data.work_item_type == WorkItemType.RELEASE and data.includes:
        included_items = []
        for wi_identifier in data.includes:
            included_wi = resolve_work_item_id(db, wi_identifier)
            if not included_wi:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Work Item not found for release inclusion: {wi_identifier}"
                )
            # Only allow IR, CR, BUG to be included in releases (not TASK or RELEASE)
            if included_wi.work_item_type not in [WorkItemType.IR, WorkItemType.CR, WorkItemType.BUG]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Only IR, CR, and BUG work items can be included in releases. "
                           f"'{included_wi.human_readable_id}' is type '{included_wi.work_item_type.value}'"
                )
            included_items.append(included_wi)
        work_item.included_work_items = included_items

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

    # RAAS-FEAT-099: Capture target versions (immutable)
    target_versions = []

    if data.target_version_ids:
        # Explicit target versions provided - use those
        for version_id_str in data.target_version_ids:
            try:
                version_uuid = UUID(version_id_str)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid version UUID: {version_id_str}"
                )
            version = db.query(RequirementVersion).filter(
                RequirementVersion.id == version_uuid
            ).first()
            if not version:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"RequirementVersion not found: {version_id_str}"
                )
            target_versions.append(version)
    else:
        # Auto-capture resolved versions from affected requirements (CR-006)
        for req in affected_reqs:
            resolved = resolve_version(db, req)
            if resolved:
                target_versions.append(resolved)

    work_item.target_versions = target_versions

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

    # RAAS-FEAT-099: Target versions update (only allowed in CREATED status)
    if data.target_version_ids is not None:
        if work_item.status != WorkItemStatus.CREATED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot modify target versions after work has started. "
                       f"Work Item '{work_item.human_readable_id}' is in status '{work_item.status.value}'. "
                       f"Cancel this work item and create a new one if scope needs to change."
            )

        # Resolve and update target versions
        new_target_versions = []
        for version_id_str in data.target_version_ids:
            try:
                version_uuid = UUID(version_id_str)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid version UUID: {version_id_str}"
                )
            version = db.query(RequirementVersion).filter(
                RequirementVersion.id == version_uuid
            ).first()
            if not version:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"RequirementVersion not found: {version_id_str}"
                )
            new_target_versions.append(version)

        work_item.target_versions = new_target_versions
        changes.append(("target_versions", None, f"{len(new_target_versions)} version(s)"))

    # Release-specific updates (RAAS-FEAT-102)
    if work_item.work_item_type == WorkItemType.RELEASE:
        if data.release_tag is not None and data.release_tag != work_item.release_tag:
            changes.append(("release_tag", work_item.release_tag, data.release_tag))
            work_item.release_tag = data.release_tag

        if data.github_release_url is not None and data.github_release_url != work_item.github_release_url:
            changes.append(("github_release_url", work_item.github_release_url, data.github_release_url))
            work_item.github_release_url = data.github_release_url

        if data.includes is not None:
            # Resolve and update included work items
            new_included = []
            for wi_identifier in data.includes:
                included_wi = resolve_work_item_id(db, wi_identifier)
                if not included_wi:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Work Item not found for release inclusion: {wi_identifier}"
                    )
                # Only allow IR, CR, BUG to be included in releases
                if included_wi.work_item_type not in [WorkItemType.IR, WorkItemType.CR, WorkItemType.BUG]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Only IR, CR, and BUG work items can be included in releases. "
                               f"'{included_wi.human_readable_id}' is type '{included_wi.work_item_type.value}'"
                    )
                new_included.append(included_wi)
            work_item.included_work_items = new_included

    # Handle status transition
    if data.status is not None and data.status != work_item.status:
        try:
            validate_work_item_transition(work_item.status, data.status, work_item.work_item_type)
        except WorkItemStateTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # RAAS-FEAT-102: Deployment gate - IR/CR/BUG must be in a Release to deploy
        if data.status == WorkItemStatus.DEPLOYED:
            if work_item.work_item_type in [WorkItemType.IR, WorkItemType.CR, WorkItemType.BUG]:
                db.refresh(work_item, ["included_in_releases"])
                if not work_item.included_in_releases:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot deploy {work_item.work_item_type.value.upper()} work items directly. "
                               f"Include '{work_item.human_readable_id}' in a Release first."
                    )
                # Check if any containing Release is already deployed or completed (BUG-006 fix)
                deployed_release = None
                for release in work_item.included_in_releases:
                    if release.status in [WorkItemStatus.DEPLOYED, WorkItemStatus.COMPLETED]:
                        deployed_release = release
                        break
                if not deployed_release:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot deploy '{work_item.human_readable_id}' - the containing Release must be deployed first."
                    )

        old_status = work_item.status
        work_item.status = data.status

        # RAAS-FEAT-102: Release deployment cascade
        if data.status == WorkItemStatus.DEPLOYED and work_item.work_item_type == WorkItemType.RELEASE:
            db.refresh(work_item, ["included_work_items"])
            for included_wi in work_item.included_work_items:
                if included_wi.status == WorkItemStatus.VALIDATED:
                    included_wi.status = WorkItemStatus.DEPLOYED
                    included_wi.updated_at = datetime.utcnow()
                    included_wi.updated_by_user_id = current_user.id
                    create_work_item_history(
                        db, included_wi, "status_changed", current_user.id,
                        field_name="status",
                        old_value=WorkItemStatus.VALIDATED.value,
                        new_value=WorkItemStatus.DEPLOYED.value,
                        change_reason=f"Auto-deployed via Release {work_item.human_readable_id}",
                    )

        # Handle completion timestamps
        if data.status == WorkItemStatus.COMPLETED:
            work_item.completed_at = datetime.utcnow()
            # Execute CR merge if applicable
            if triggers_cr_merge(old_status, data.status):
                execute_cr_merge(db, work_item, current_user.id)
            # RAAS-FEAT-102: Release completion cascade
            if work_item.work_item_type == WorkItemType.RELEASE:
                db.refresh(work_item, ["included_work_items"])
                for included_wi in work_item.included_work_items:
                    if included_wi.status == WorkItemStatus.DEPLOYED:
                        included_wi.status = WorkItemStatus.COMPLETED
                        included_wi.completed_at = datetime.utcnow()
                        included_wi.updated_at = datetime.utcnow()
                        included_wi.updated_by_user_id = current_user.id
                        if triggers_cr_merge(WorkItemStatus.DEPLOYED, WorkItemStatus.COMPLETED):
                            execute_cr_merge(db, included_wi, current_user.id)
                        create_work_item_history(
                            db, included_wi, "status_changed", current_user.id,
                            field_name="status",
                            old_value=WorkItemStatus.DEPLOYED.value,
                            new_value=WorkItemStatus.COMPLETED.value,
                            change_reason=f"Auto-completed via Release {work_item.human_readable_id}",
                        )
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
    refresh_attrs = ["assignee", "created_by_user", "affected_requirements"]
    if work_item.work_item_type == WorkItemType.RELEASE:
        refresh_attrs.append("included_work_items")
    db.refresh(work_item, refresh_attrs)

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
        validate_work_item_transition(work_item.status, data.new_status, work_item.work_item_type)
    except WorkItemStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # RAAS-FEAT-102: Deployment gate - IR/CR/BUG must be in a Release to deploy
    if data.new_status == WorkItemStatus.DEPLOYED:
        if work_item.work_item_type in [WorkItemType.IR, WorkItemType.CR, WorkItemType.BUG]:
            # Check if this work item is included in a Release
            db.refresh(work_item, ["included_in_releases"])
            if not work_item.included_in_releases:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot deploy {work_item.work_item_type.value.upper()} work items directly. "
                           f"Include '{work_item.human_readable_id}' in a Release first."
                )
            # Check if any containing Release is already deployed or completed (BUG-006 fix)
            deployed_release = None
            for release in work_item.included_in_releases:
                if release.status in [WorkItemStatus.DEPLOYED, WorkItemStatus.COMPLETED]:
                    deployed_release = release
                    break
            if not deployed_release:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot deploy '{work_item.human_readable_id}' - the containing Release must be deployed first."
                )

    old_status = work_item.status
    work_item.status = data.new_status
    work_item.updated_at = datetime.utcnow()
    work_item.updated_by_user_id = current_user.id

    # RAAS-FEAT-102: Release deployment cascade - deploy all included items when Release deploys
    if data.new_status == WorkItemStatus.DEPLOYED and work_item.work_item_type == WorkItemType.RELEASE:
        db.refresh(work_item, ["included_work_items"])
        for included_wi in work_item.included_work_items:
            if included_wi.status == WorkItemStatus.VALIDATED:
                included_wi.status = WorkItemStatus.DEPLOYED
                included_wi.updated_at = datetime.utcnow()
                included_wi.updated_by_user_id = current_user.id
                create_work_item_history(
                    db, included_wi, "status_changed", current_user.id,
                    field_name="status",
                    old_value=WorkItemStatus.VALIDATED.value,
                    new_value=WorkItemStatus.DEPLOYED.value,
                    change_reason=f"Auto-deployed via Release {work_item.human_readable_id}",
                )
                logger.info(f"Auto-deployed {included_wi.human_readable_id} via Release {work_item.human_readable_id}")

    # Handle completion timestamps
    if data.new_status == WorkItemStatus.COMPLETED:
        work_item.completed_at = datetime.utcnow()
        # Execute CR merge if applicable
        if triggers_cr_merge(old_status, data.new_status):
            execute_cr_merge(db, work_item, current_user.id)
        # RAAS-FEAT-102: Release completion cascade - complete all deployed included items
        if work_item.work_item_type == WorkItemType.RELEASE:
            db.refresh(work_item, ["included_work_items"])
            for included_wi in work_item.included_work_items:
                if included_wi.status == WorkItemStatus.DEPLOYED:
                    included_wi.status = WorkItemStatus.COMPLETED
                    included_wi.completed_at = datetime.utcnow()
                    included_wi.updated_at = datetime.utcnow()
                    included_wi.updated_by_user_id = current_user.id
                    # Execute CR merge for any included CRs
                    if triggers_cr_merge(WorkItemStatus.DEPLOYED, WorkItemStatus.COMPLETED):
                        execute_cr_merge(db, included_wi, current_user.id)
                    create_work_item_history(
                        db, included_wi, "status_changed", current_user.id,
                        field_name="status",
                        old_value=WorkItemStatus.DEPLOYED.value,
                        new_value=WorkItemStatus.COMPLETED.value,
                        change_reason=f"Auto-completed via Release {work_item.human_readable_id}",
                    )
                    logger.info(f"Auto-completed {included_wi.human_readable_id} via Release {work_item.human_readable_id}")
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

    allowed = get_allowed_work_item_transitions(work_item.status, work_item.work_item_type)
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
            status=v.status,  # CR-006: versions have status
            content_hash=v.content_hash,
            title=v.title,
            source_work_item_id=v.source_work_item_id,
            source_work_item_hrid=wi_hrid,
            created_at=v.created_at,
            created_by_email=created_by_email,
        ))

    # Get deployed version number (CR-006: replaced current_version_number)
    deployed_version_num = None
    if req.deployed_version_id:
        deployed_ver = db.query(RequirementVersion).filter(
            RequirementVersion.id == req.deployed_version_id
        ).first()
        if deployed_ver:
            deployed_version_num = deployed_ver.version_number

    return RequirementVersionListResponse(
        items=items,
        total=len(items),
        requirement_id=req_uuid,
        deployed_version_number=deployed_version_num,
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
        status=version.status,  # CR-006: Status lives on versions
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


# =============================================================================
# CR-002: Deployment Version Tracking
# =============================================================================


@router.post("/requirements/{requirement_id}/mark-deployed", response_model=dict)
async def mark_requirement_deployed(
    requirement_id: str,
    version_id: Optional[UUID] = Query(
        None,
        description="Specific version to mark as deployed (defaults to resolved version per CR-006)"
    ),
    db: Session = Depends(get_db),
):
    """Mark a requirement as deployed to production (CR-002: RAAS-FEAT-104).

    Updates deployed_version_id to track which version is in production.
    This is typically called when a Release deploys to production.

    CR-006: Uses version resolution (deployed -> latest approved -> latest)
    instead of current_version_id.

    Args:
        requirement_id: UUID or human-readable ID of the requirement
        version_id: Optional specific version to mark (defaults to resolved version)

    Returns:
        Dict with requirement_id, deployed_version details
    """
    # Resolve requirement
    req_uuid = resolve_requirement_id(db, requirement_id)
    if not req_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement not found: {requirement_id}"
        )

    req = db.query(Requirement).filter(Requirement.id == req_uuid).first()
    if not req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement not found: {requirement_id}"
        )

    # Track old deployed version for audit
    old_deployed_version_id = req.deployed_version_id

    # Update deployed version pointer
    version = update_deployed_version_pointer(db, req, version_id)

    if not version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No version found to mark as deployed for requirement {requirement_id}"
        )

    # CR-002: Create audit log entry for deployment event
    old_version_str = str(old_deployed_version_id) if old_deployed_version_id else "none"
    history_entry = RequirementHistory(
        requirement_id=req.id,
        change_type=ChangeType.DEPLOYED,
        field_name="deployed_version_id",
        old_value=old_version_str,
        new_value=str(version.id),
        change_reason=f"Deployed version {version.version_number}",
    )
    db.add(history_entry)

    db.commit()

    logger.info(f"Marked requirement {req.human_readable_id or req.id} as deployed (version {version.version_number})")

    return {
        "requirement_id": str(req.id),
        "human_readable_id": req.human_readable_id,
        "deployed_version_id": str(version.id),
        "deployed_version_number": version.version_number,
        "message": f"Marked version {version.version_number} as deployed"
    }


@router.post("/requirements/batch-mark-deployed", response_model=dict)
async def batch_mark_deployed(
    requirement_ids: list[str] = Query(
        ...,
        description="List of requirement UUIDs or human-readable IDs to mark as deployed"
    ),
    db: Session = Depends(get_db),
):
    """Batch mark multiple requirements as deployed (CR-002: RAAS-FEAT-104).

    Typically called when a Release deploys multiple requirements to production.
    CR-006: Uses version resolution (deployed -> latest approved -> latest)
    instead of current_version_id.

    Args:
        requirement_ids: List of requirement identifiers

    Returns:
        Dict with success/failure counts and details
    """
    results = {
        "success": [],
        "failed": [],
    }

    for req_id in requirement_ids:
        req_uuid = resolve_requirement_id(db, req_id)
        if not req_uuid:
            results["failed"].append({
                "id": req_id,
                "error": "Requirement not found"
            })
            continue

        req = db.query(Requirement).filter(Requirement.id == req_uuid).first()
        if not req:
            results["failed"].append({
                "id": req_id,
                "error": "Requirement not found"
            })
            continue

        # Track old deployed version for audit
        old_deployed_version_id = req.deployed_version_id

        version = update_deployed_version_pointer(db, req)
        if version:
            # CR-002: Create audit log entry for deployment event
            old_version_str = str(old_deployed_version_id) if old_deployed_version_id else "none"
            history_entry = RequirementHistory(
                requirement_id=req.id,
                change_type=ChangeType.DEPLOYED,
                field_name="deployed_version_id",
                old_value=old_version_str,
                new_value=str(version.id),
                change_reason=f"Batch deployed version {version.version_number}",
            )
            db.add(history_entry)

            results["success"].append({
                "requirement_id": str(req.id),
                "human_readable_id": req.human_readable_id,
                "deployed_version_number": version.version_number,
            })
        else:
            results["failed"].append({
                "id": req_id,
                "error": "No version available to mark as deployed"
            })

    db.commit()

    return {
        "total_requested": len(requirement_ids),
        "success_count": len(results["success"]),
        "failed_count": len(results["failed"]),
        "success": results["success"],
        "failed": results["failed"],
    }


# =============================================================================
# CR-002 (RAAS-FEAT-104): Work Item Diffs and Conflict Detection
# =============================================================================

from ...schemas import (
    RequirementDiffItem,
    WorkItemDiffsResponse,
    ConflictItem,
    ConflictCheckResponse,
)


@router.get("/{work_item_id}/diffs", response_model=WorkItemDiffsResponse)
async def get_work_item_diffs(
    work_item_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get diffs for all affected requirements in a Work Item (CR-002: RAAS-FEAT-104).

    For CR review, shows actual content changes for each affected requirement.

    For CRs with proposed_content:
    - Shows diff between deployed_version content and proposed content (CR-006)

    For other Work Items:
    - Shows diff between deployed_version and latest version (if different)

    Returns:
        WorkItemDiffsResponse with diff details for each affected requirement
    """
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    # Eager load affected requirements
    db.refresh(work_item, ["affected_requirements"])

    diffs = []
    total_with_changes = 0

    for req in work_item.affected_requirements:
        # Get deployed version (CR-006: replaced current_version)
        deployed_version = None
        deployed_content = None
        deployed_version_num = None
        if req.deployed_version_id:
            deployed_version = db.query(RequirementVersion).filter(
                RequirementVersion.id == req.deployed_version_id
            ).first()
            if deployed_version:
                deployed_content = deployed_version.content
                deployed_version_num = deployed_version.version_number

        # Get latest version
        latest_version = db.query(RequirementVersion).filter(
            RequirementVersion.requirement_id == req.id
        ).order_by(RequirementVersion.version_number.desc()).first()

        latest_content = latest_version.content if latest_version else None
        latest_version_num = latest_version.version_number if latest_version else None

        # Get proposed content for CRs
        proposed_content = None
        if work_item.work_item_type == WorkItemType.CR and work_item.proposed_content:
            # Check both UUID and human-readable ID
            proposed_content = work_item.proposed_content.get(str(req.id))
            if not proposed_content and req.human_readable_id:
                proposed_content = work_item.proposed_content.get(req.human_readable_id)

        # Determine if there are changes
        has_changes = False
        changes_summary = ""

        if proposed_content:
            # For CRs, compare deployed to proposed
            if deployed_content != proposed_content:
                has_changes = True
                changes_summary = "Proposed changes pending"
        elif deployed_version_num and latest_version_num and deployed_version_num != latest_version_num:
            # For non-CRs, compare deployed to latest
            has_changes = True
            changes_summary = f"Version {deployed_version_num} -> {latest_version_num}"

        if has_changes:
            total_with_changes += 1

        diffs.append(RequirementDiffItem(
            requirement_id=req.id,
            human_readable_id=req.human_readable_id,
            title=req.title,
            deployed_version_number=deployed_version_num,
            latest_version_number=latest_version_num,
            deployed_content=deployed_content,
            proposed_content=proposed_content,
            latest_content=latest_content,
            has_changes=has_changes,
            changes_summary=changes_summary,
        ))

    return WorkItemDiffsResponse(
        work_item_id=work_item.id,
        human_readable_id=work_item.human_readable_id,
        work_item_type=work_item.work_item_type.value,
        affected_requirements=diffs,
        total_affected=len(diffs),
        total_with_changes=total_with_changes,
    )


@router.get("/{work_item_id}/check-conflicts", response_model=ConflictCheckResponse)
async def check_work_item_conflicts(
    work_item_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Check for conflicts before approving/merging a Work Item (CR-002: RAAS-FEAT-104).

    Proactive conflict detection that surfaces issues to reviewers before approval.

    Compares baseline_hashes (captured when Work Item created) to current content hashes.
    If a requirement's content has changed since the Work Item was created, it's flagged
    as a conflict.

    Returns:
        ConflictCheckResponse with conflict status for each affected requirement
    """
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    # Eager load affected requirements
    db.refresh(work_item, ["affected_requirements"])

    baseline_hashes = work_item.baseline_hashes or {}
    conflicts = []
    conflict_count = 0

    for req in work_item.affected_requirements:
        # Get baseline hash for this requirement
        baseline_hash = baseline_hashes.get(str(req.id))
        if not baseline_hash and req.human_readable_id:
            baseline_hash = baseline_hashes.get(req.human_readable_id)

        # Get current hash
        current_hash = req.content_hash
        if not current_hash and req.content:
            current_hash = compute_content_hash(req.content)

        # Check for conflict
        has_conflict = False
        conflict_reason = None

        if baseline_hash and current_hash and baseline_hash != current_hash:
            has_conflict = True
            conflict_reason = "Content changed since Work Item creation"
            conflict_count += 1
        elif not baseline_hash:
            # No baseline - can't detect conflicts
            conflict_reason = "No baseline hash (Work Item created before conflict detection)"

        conflicts.append(ConflictItem(
            requirement_id=req.id,
            human_readable_id=req.human_readable_id,
            title=req.title,
            baseline_hash=baseline_hash,
            current_hash=current_hash,
            has_conflict=has_conflict,
            conflict_reason=conflict_reason,
        ))

    return ConflictCheckResponse(
        work_item_id=work_item.id,
        human_readable_id=work_item.human_readable_id,
        has_conflicts=conflict_count > 0,
        conflict_count=conflict_count,
        affected_requirements=conflicts,
    )


@router.get("/{work_item_id}/drift", response_model=DriftCheckResponse)
async def check_work_item_drift(
    work_item_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Check for version drift on a Work Item (RAAS-FEAT-099).

    Semantic version drift detection that shows which targeted requirements
    have newer versions available.

    Unlike check-conflicts (hash-based), this provides semantic information:
    "You're targeting RAAS-FEAT-042 v3, but it's now at v5"

    Returns:
        DriftCheckResponse with drift warnings for each affected requirement
    """
    work_item = resolve_work_item_id(db, work_item_id)
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work Item not found: {work_item_id}"
        )

    # Eager load target versions and their requirements
    db.refresh(work_item, ["target_versions"])

    drift_warnings = []

    for target_version in work_item.target_versions:
        # Get the requirement this version belongs to
        req = target_version.requirement
        if not req:
            continue

        # Get latest version number (CR-006: compare against latest, not current_version_id)
        latest_version = db.query(RequirementVersion).filter(
            RequirementVersion.requirement_id == req.id
        ).order_by(RequirementVersion.version_number.desc()).first()
        latest_version_num = latest_version.version_number if latest_version else 1

        target_version_num = target_version.version_number

        # Check for drift (latest > target means spec has evolved)
        if latest_version_num > target_version_num:
            drift_warnings.append(DriftWarning(
                requirement_id=req.id,
                requirement_human_readable_id=req.human_readable_id,
                target_version=target_version_num,
                latest_version=latest_version_num,  # CR-006: renamed from current_version
                versions_behind=latest_version_num - target_version_num,
            ))

    return DriftCheckResponse(
        work_item_id=str(work_item.id),
        work_item_human_readable_id=work_item.human_readable_id,
        has_drift=len(drift_warnings) > 0,
        drift_warnings=drift_warnings,
    )
