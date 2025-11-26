"""Task Queue API endpoints (RAAS-EPIC-027, RAAS-COMP-065)."""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from raas_core import crud, schemas, models
from raas_core.api.dependencies import get_current_user_optional

from ..database import get_db

logger = logging.getLogger("raas-core.tasks")

router = APIRouter(tags=["tasks"])


def _task_to_response(task: models.Task) -> schemas.TaskResponse:
    """Convert Task model to TaskResponse schema."""
    return schemas.TaskResponse(
        id=task.id,
        human_readable_id=task.human_readable_id,
        organization_id=task.organization_id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        task_type=task.task_type,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        source_type=task.source_type,
        source_id=task.source_id,
        source_context=task.source_context,
        assignee_count=len(task.assignees) if task.assignees else 0,
        created_by=task.created_by,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        completed_by=task.completed_by,
    )


def _task_to_list_item(task: models.Task) -> schemas.TaskListItem:
    """Convert Task model to TaskListItem schema."""
    is_overdue = (
        task.due_date is not None
        and task.due_date < datetime.utcnow()
        and task.status not in [models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED]
    )
    return schemas.TaskListItem(
        id=task.id,
        human_readable_id=task.human_readable_id,
        organization_id=task.organization_id,
        project_id=task.project_id,
        title=task.title,
        description=task.description[:200] if task.description else None,
        task_type=task.task_type,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        source_type=task.source_type,
        assignee_count=len(task.assignees) if task.assignees else 0,
        is_overdue=is_overdue,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post("/", response_model=schemas.TaskResponse, status_code=201)
def create_task(
    task_data: schemas.TaskCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Create a new task.

    Tasks can be created directly by users or programmatically by task sources.
    Source-created tasks should include source_type and source_id for bidirectional linking.

    - **organization_id**: Organization UUID (required)
    - **project_id**: Project UUID (optional, for project-scoped tasks)
    - **title**: Task title
    - **description**: Task description (optional)
    - **task_type**: Type of task (clarification, review, approval, gap_resolution, custom)
    - **priority**: Priority level (low, medium, high, critical)
    - **due_date**: Due date (optional)
    - **assignee_ids**: List of user UUIDs to assign (optional)
    - **source_type**: Source system type (optional)
    - **source_id**: Source artifact UUID (optional)
    - **source_context**: Additional context from source (optional)
    """
    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    # Verify organization exists
    org = crud.get_organization(db, task_data.organization_id)
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization not found: {task_data.organization_id}")

    # Verify project exists if provided
    if task_data.project_id:
        project = crud.get_project(db, task_data.project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project not found: {task_data.project_id}")
        if project.organization_id != task_data.organization_id:
            raise HTTPException(status_code=400, detail="Project does not belong to the specified organization")

    try:
        task = crud.create_task(db, task_data, user_id)
        logger.info(f"Created task {task.human_readable_id}: {task.title}")
        return _task_to_response(task)
    except Exception as e:
        logger.error(f"Error creating task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=schemas.TaskListResponse)
def list_tasks(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    project_id: Optional[UUID] = Query(None, description="Filter by project"),
    assignee_id: Optional[UUID] = Query(None, description="Filter by assignee"),
    status: Optional[models.TaskStatus] = Query(None, description="Filter by status"),
    task_type: Optional[models.TaskType] = Query(None, description="Filter by task type"),
    priority: Optional[models.TaskPriority] = Query(None, description="Filter by priority"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    overdue_only: bool = Query(False, description="Only return overdue tasks"),
    include_completed: bool = Query(False, description="Include completed/cancelled tasks"),
    db: Session = Depends(get_db),
):
    """
    List tasks with filtering and pagination.

    By default, completed and cancelled tasks are excluded. Use include_completed=true to include them.
    Tasks are ordered by priority (critical first), then due_date (earliest first), then created_at.

    - **page**: Page number (starts at 1)
    - **page_size**: Number of items per page (1-100)
    - **organization_id**: Filter by organization
    - **project_id**: Filter by project
    - **assignee_id**: Filter by assignee (tasks assigned to this user)
    - **status**: Filter by status
    - **task_type**: Filter by task type
    - **priority**: Filter by priority
    - **source_type**: Filter by source type
    - **overdue_only**: Only return overdue tasks
    - **include_completed**: Include completed/cancelled tasks
    """
    current_user = get_current_user_optional(request)

    # If authenticated, filter by user's organizations
    if current_user and not organization_id:
        org_ids = crud.get_user_organization_ids(db, current_user.id)
        if not org_ids:
            return schemas.TaskListResponse(
                items=[],
                total=0,
                page=page,
                page_size=page_size,
                total_pages=0,
            )
        # For now, require explicit organization_id filter in team mode
        # Future: could aggregate across all user's orgs

    skip = (page - 1) * page_size
    tasks, total = crud.get_tasks(
        db=db,
        skip=skip,
        limit=page_size,
        organization_id=organization_id,
        project_id=project_id,
        assignee_id=assignee_id,
        status=status,
        task_type=task_type,
        priority=priority,
        source_type=source_type,
        overdue_only=overdue_only,
        include_completed=include_completed,
    )

    return schemas.TaskListResponse(
        items=[_task_to_list_item(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/my", response_model=list[schemas.TaskListItem])
def get_my_tasks(
    request: Request,
    include_completed: bool = Query(False, description="Include completed/cancelled tasks"),
    db: Session = Depends(get_db),
):
    """
    Get all tasks assigned to the current user.

    This is a convenience endpoint for getting "what needs my attention" across all
    organizations and projects. Requires authentication.

    Tasks are ordered by priority (critical first), then due_date (earliest first).

    - **include_completed**: Include completed/cancelled tasks
    """
    current_user = get_current_user_optional(request)
    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to view your tasks"
        )

    # Get user's organization IDs for filtering
    org_ids = crud.get_user_organization_ids(db, current_user.id)

    tasks = crud.get_my_tasks(
        db=db,
        user_id=current_user.id,
        organization_ids=org_ids,
        include_completed=include_completed,
    )

    return [_task_to_list_item(t) for t in tasks]


@router.get("/{task_id}", response_model=schemas.TaskResponse)
def get_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get a specific task by ID.

    Supports both UUID and human-readable ID formats:
    - UUID: afa92d5c-e008-44d6-b2cf-ccacd81481d6
    - Readable: TASK-001 (case-insensitive)

    - **task_id**: UUID or human-readable ID of the task
    """
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    return _task_to_response(task)


@router.patch("/{task_id}", response_model=schemas.TaskResponse)
def update_task(
    task_id: str,
    task_update: schemas.TaskUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Update a task.

    Supports both UUID and human-readable ID formats.

    - **task_id**: UUID or human-readable ID of the task
    - **title**: New title (optional)
    - **description**: New description (optional)
    - **status**: New status (optional)
    - **priority**: New priority (optional)
    - **due_date**: New due date (optional)
    """
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    updated = crud.update_task(db, task.id, task_update, user_id)
    return _task_to_response(updated)


@router.post("/{task_id}/assign", response_model=schemas.TaskResponse)
def assign_task(
    task_id: str,
    assignment: schemas.TaskAssign,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Assign users to a task.

    - **task_id**: UUID or human-readable ID of the task
    - **assignee_ids**: List of user UUIDs to assign
    - **replace**: If true, replaces all existing assignees; if false, adds to existing
    """
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    updated = crud.assign_task(
        db=db,
        task_id=task.id,
        assignee_ids=assignment.assignee_ids,
        user_id=user_id,
        replace=assignment.replace,
    )
    return _task_to_response(updated)


@router.post("/{task_id}/complete", response_model=schemas.TaskResponse)
def complete_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Mark a task as completed.

    This is a convenience endpoint equivalent to updating status to 'completed'.

    - **task_id**: UUID or human-readable ID of the task
    """
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    if task.status in [models.TaskStatus.COMPLETED, models.TaskStatus.CANCELLED]:
        raise HTTPException(
            status_code=400,
            detail=f"Task is already {task.status.value}"
        )

    current_user = get_current_user_optional(request)
    user_id = current_user.id if current_user else None

    update = schemas.TaskUpdate(status=models.TaskStatus.COMPLETED)
    updated = crud.update_task(db, task.id, update, user_id)
    return _task_to_response(updated)


@router.get("/{task_id}/history", response_model=list[schemas.TaskHistoryResponse])
def get_task_history(
    task_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of history entries"),
    db: Session = Depends(get_db),
):
    """
    Get change history for a task.

    - **task_id**: UUID or human-readable ID of the task
    - **limit**: Maximum number of history entries to return (1-100)
    """
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    history = crud.get_task_history(db, task.id, limit)
    return history


@router.get("/{task_id}/assignees", response_model=list[schemas.TaskAssigneeResponse])
def get_task_assignees(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get assignees for a task.

    - **task_id**: UUID or human-readable ID of the task
    """
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    # Build assignee response list
    assignees = []
    for user in task.assignees:
        assignees.append(schemas.TaskAssigneeResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_primary=True,  # TODO: Track primary assignee in junction table
            assigned_at=task.created_at,  # TODO: Track actual assignment time
        ))

    return assignees
