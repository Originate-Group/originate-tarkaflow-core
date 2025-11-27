"""Task Source Integration (RAAS-COMP-066).

Defines the standard interface for systems that create tasks and provides
adapters for built-in RaaS task sources.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from . import crud, models, schemas

logger = logging.getLogger("raas-core.task_sources")


# =============================================================================
# Task Source Types (defined as constants for consistency)
# =============================================================================

class TaskSourceType:
    """Standard task source types for built-in RaaS adapters."""
    REQUIREMENT_REVIEW = "requirement_review"
    APPROVAL_REQUEST = "approval_request"
    CLARIFICATION_POINT = "clarification_point"
    GAP_ANALYSIS = "gap_analysis"
    CUSTOM = "custom"


# =============================================================================
# Priority Mapping
# =============================================================================

def map_source_priority(
    source_type: str,
    source_priority: Optional[str] = None,
    source_context: Optional[dict] = None,
) -> models.TaskPriority:
    """Map source-specific priority to unified task priority scale.

    Default mappings:
    - approval_request: high (blocks deployment)
    - requirement_review: medium (standard workflow)
    - clarification_point: medium (blocks progress)
    - gap_analysis: low (informational)
    - custom: medium (default)

    Can be overridden by explicit source_priority.
    """
    if source_priority:
        # Direct mapping if provided
        priority_map = {
            "critical": models.TaskPriority.CRITICAL,
            "high": models.TaskPriority.HIGH,
            "medium": models.TaskPriority.MEDIUM,
            "low": models.TaskPriority.LOW,
        }
        return priority_map.get(source_priority.lower(), models.TaskPriority.MEDIUM)

    # Source-type based defaults
    source_defaults = {
        TaskSourceType.APPROVAL_REQUEST: models.TaskPriority.HIGH,
        TaskSourceType.REQUIREMENT_REVIEW: models.TaskPriority.MEDIUM,
        TaskSourceType.CLARIFICATION_POINT: models.TaskPriority.MEDIUM,
        TaskSourceType.GAP_ANALYSIS: models.TaskPriority.LOW,
        TaskSourceType.CUSTOM: models.TaskPriority.MEDIUM,
    }
    return source_defaults.get(source_type, models.TaskPriority.MEDIUM)


def calculate_due_date(
    source_type: str,
    base_date: Optional[datetime] = None,
) -> Optional[datetime]:
    """Calculate default due date based on source type urgency.

    Default SLAs:
    - approval_request: 2 business days
    - requirement_review: 5 business days
    - clarification_point: 3 business days
    - gap_analysis: 7 business days
    - custom: None (no default)
    """
    if base_date is None:
        base_date = datetime.utcnow()

    sla_days = {
        TaskSourceType.APPROVAL_REQUEST: 2,
        TaskSourceType.REQUIREMENT_REVIEW: 5,
        TaskSourceType.CLARIFICATION_POINT: 3,
        TaskSourceType.GAP_ANALYSIS: 7,
    }

    days = sla_days.get(source_type)
    if days:
        return base_date + timedelta(days=days)
    return None


# =============================================================================
# Task Source Adapters
# =============================================================================

def create_requirement_review_task(
    db: Session,
    requirement: models.Requirement,
    organization_id: UUID,
    reviewer_ids: Optional[list[UUID]] = None,
    created_by: Optional[UUID] = None,
    custom_title: Optional[str] = None,
    custom_description: Optional[str] = None,
    due_date: Optional[datetime] = None,
) -> models.Task:
    """Create a task for reviewing a requirement.

    Used when a requirement enters 'review' status and needs human review.

    Args:
        db: Database session
        requirement: The requirement to review
        organization_id: Organization UUID
        reviewer_ids: Optional list of reviewer user IDs
        created_by: User who triggered the review
        custom_title: Override default title
        custom_description: Override default description
        due_date: Override default due date

    Returns:
        Created task
    """
    title = custom_title or f"Review requirement: {requirement.human_readable_id}"
    description = custom_description or (
        f"Please review the requirement '{requirement.title}' "
        f"({requirement.human_readable_id}) and approve or request changes.\n\n"
        f"Requirement Type: {requirement.type.value if requirement.type else 'Unknown'}\n"
        f"Status: {requirement.status.value if requirement.status else 'Unknown'}"
    )

    source_context = {
        "requirement_id": str(requirement.id),
        "human_readable_id": requirement.human_readable_id,
        "requirement_title": requirement.title,
        "requirement_type": requirement.type.value if requirement.type else None,
        "current_status": requirement.status.value if requirement.status else None,
        "project_id": str(requirement.project_id) if requirement.project_id else None,
    }

    task_data = schemas.TaskCreate(
        organization_id=organization_id,
        project_id=requirement.project_id,
        title=title,
        description=description,
        task_type=models.TaskType.REVIEW,
        priority=map_source_priority(TaskSourceType.REQUIREMENT_REVIEW),
        due_date=due_date or calculate_due_date(TaskSourceType.REQUIREMENT_REVIEW),
        source_type=TaskSourceType.REQUIREMENT_REVIEW,
        source_id=requirement.id,
        source_context=source_context,
        assignee_ids=reviewer_ids,
    )

    task = crud.create_task(db, task_data, created_by)
    logger.info(
        f"Created review task {task.human_readable_id} for requirement "
        f"{requirement.human_readable_id}"
    )
    return task


def create_approval_request_task(
    db: Session,
    requirement: models.Requirement,
    organization_id: UUID,
    transition_to: str,
    approver_ids: Optional[list[UUID]] = None,
    created_by: Optional[UUID] = None,
    reason: Optional[str] = None,
    due_date: Optional[datetime] = None,
) -> models.Task:
    """Create a task for approving a requirement status transition.

    Used when a requirement needs approval to transition to a new status
    (e.g., review -> approved, implemented -> validated).

    Args:
        db: Database session
        requirement: The requirement needing approval
        organization_id: Organization UUID
        transition_to: Target status for the transition
        approver_ids: Optional list of approver user IDs
        created_by: User who requested the approval
        reason: Optional reason for the transition request
        due_date: Override default due date

    Returns:
        Created task
    """
    title = f"Approve {requirement.human_readable_id} → {transition_to}"
    description = (
        f"Approval requested to transition requirement '{requirement.title}' "
        f"({requirement.human_readable_id}) from '{requirement.status.value}' "
        f"to '{transition_to}'."
    )
    if reason:
        description += f"\n\nReason: {reason}"

    source_context = {
        "requirement_id": str(requirement.id),
        "human_readable_id": requirement.human_readable_id,
        "requirement_title": requirement.title,
        "current_status": requirement.status.value if requirement.status else None,
        "requested_status": transition_to,
        "project_id": str(requirement.project_id) if requirement.project_id else None,
        "reason": reason,
    }

    task_data = schemas.TaskCreate(
        organization_id=organization_id,
        project_id=requirement.project_id,
        title=title,
        description=description,
        task_type=models.TaskType.APPROVAL,
        priority=map_source_priority(TaskSourceType.APPROVAL_REQUEST),
        due_date=due_date or calculate_due_date(TaskSourceType.APPROVAL_REQUEST),
        source_type=TaskSourceType.APPROVAL_REQUEST,
        source_id=requirement.id,
        source_context=source_context,
        assignee_ids=approver_ids,
    )

    task = crud.create_task(db, task_data, created_by)
    logger.info(
        f"Created approval task {task.human_readable_id} for requirement "
        f"{requirement.human_readable_id} → {transition_to}"
    )
    return task


def create_clarification_task(
    db: Session,
    requirement: models.Requirement,
    organization_id: UUID,
    question: str,
    context: Optional[str] = None,
    assignee_ids: Optional[list[UUID]] = None,
    created_by: Optional[UUID] = None,
    due_date: Optional[datetime] = None,
) -> models.Task:
    """Create a task for clarifying a requirement.

    Used when a requirement needs human input to resolve ambiguity
    or answer a specific question.

    Args:
        db: Database session
        requirement: The requirement needing clarification
        organization_id: Organization UUID
        question: The clarification question
        context: Additional context about why clarification is needed
        assignee_ids: Optional list of user IDs who can answer
        created_by: User or system that identified the need
        due_date: Override default due date

    Returns:
        Created task
    """
    title = f"Clarify: {requirement.human_readable_id}"
    description = f"Clarification needed for '{requirement.title}':\n\n{question}"
    if context:
        description += f"\n\nContext: {context}"

    source_context = {
        "requirement_id": str(requirement.id),
        "human_readable_id": requirement.human_readable_id,
        "requirement_title": requirement.title,
        "question": question,
        "context": context,
        "project_id": str(requirement.project_id) if requirement.project_id else None,
    }

    task_data = schemas.TaskCreate(
        organization_id=organization_id,
        project_id=requirement.project_id,
        title=title,
        description=description,
        task_type=models.TaskType.CLARIFICATION,
        priority=map_source_priority(TaskSourceType.CLARIFICATION_POINT),
        due_date=due_date or calculate_due_date(TaskSourceType.CLARIFICATION_POINT),
        source_type=TaskSourceType.CLARIFICATION_POINT,
        source_id=requirement.id,
        source_context=source_context,
        assignee_ids=assignee_ids,
    )

    task = crud.create_task(db, task_data, created_by)
    logger.info(
        f"Created clarification task {task.human_readable_id} for requirement "
        f"{requirement.human_readable_id}"
    )
    return task


def create_clarification_point_task(
    db: Session,
    clarification_point: models.ClarificationPoint,
    created_by: Optional[UUID] = None,
) -> models.Task:
    """Create a task for a clarification point (RAAS-FEAT-091).

    Automatically called when a clarification point is created. Creates a task
    in the unified task queue so stakeholders see clarification work alongside
    other tasks.

    Args:
        db: Database session
        clarification_point: The ClarificationPoint entity
        created_by: User who created the clarification point

    Returns:
        Created task linked to the clarification point
    """
    # Map clarification priority to task priority
    # blocking -> critical, high -> high, medium -> medium, low -> low
    priority_map = {
        "blocking": models.TaskPriority.CRITICAL,
        "high": models.TaskPriority.HIGH,
        "medium": models.TaskPriority.MEDIUM,
        "low": models.TaskPriority.LOW,
    }
    priority_value = clarification_point.priority.value if hasattr(clarification_point.priority, 'value') else str(clarification_point.priority)
    task_priority = priority_map.get(priority_value.lower(), models.TaskPriority.MEDIUM)

    # Build description with context
    description = clarification_point.description or ""
    if clarification_point.context:
        if description:
            description += f"\n\nContext: {clarification_point.context}"
        else:
            description = f"Context: {clarification_point.context}"

    # Source context for linking back to clarification point
    source_context = {
        "clarification_point_id": str(clarification_point.id),
        "human_readable_id": clarification_point.human_readable_id,
        "artifact_type": clarification_point.artifact_type,
        "artifact_id": str(clarification_point.artifact_id),
        "title": clarification_point.title,
    }

    # Assignee from clarification point
    assignee_ids = [clarification_point.assignee_id] if clarification_point.assignee_id else None

    task_data = schemas.TaskCreate(
        organization_id=clarification_point.organization_id,
        project_id=clarification_point.project_id,
        title=clarification_point.title,
        description=description,
        task_type=models.TaskType.CLARIFICATION,
        priority=task_priority,
        due_date=clarification_point.due_date or calculate_due_date(TaskSourceType.CLARIFICATION_POINT),
        source_type=TaskSourceType.CLARIFICATION_POINT,
        source_id=clarification_point.id,
        source_context=source_context,
        assignee_ids=assignee_ids,
    )

    task = crud.create_task(db, task_data, created_by)
    logger.info(
        f"Created clarification task {task.human_readable_id} for clarification point "
        f"{clarification_point.human_readable_id}"
    )
    return task


def complete_clarification_point_task(
    db: Session,
    clarification_point: models.ClarificationPoint,
    completed_by: Optional[UUID] = None,
    resolution: Optional[str] = None,
) -> Optional[models.Task]:
    """Complete the task linked to a resolved clarification point (RAAS-FEAT-091).

    Automatically called when a clarification point is resolved. Finds and
    completes the linked task in the unified task queue.

    Args:
        db: Database session
        clarification_point: The resolved ClarificationPoint entity
        completed_by: User who resolved the clarification
        resolution: Resolution content

    Returns:
        Completed task if found, None otherwise
    """
    # Find the linked task
    task = crud.find_task_by_source(
        db=db,
        source_type=TaskSourceType.CLARIFICATION_POINT,
        source_id=clarification_point.id,
        task_type=models.TaskType.CLARIFICATION,
        exclude_completed=True,
    )

    if not task:
        logger.warning(
            f"No open task found for clarification point {clarification_point.human_readable_id}"
        )
        return None

    # Complete the task
    task.status = models.TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    task.completed_by = completed_by

    # Update source context with resolution
    if task.source_context:
        task.source_context = {
            **task.source_context,
            "resolution": resolution,
            "resolved_at": datetime.utcnow().isoformat(),
        }
    else:
        task.source_context = {
            "resolution": resolution,
            "resolved_at": datetime.utcnow().isoformat(),
        }

    db.commit()
    db.refresh(task)

    logger.info(
        f"Completed task {task.human_readable_id} for clarification point "
        f"{clarification_point.human_readable_id}"
    )
    return task


def create_gap_resolution_task(
    db: Session,
    organization_id: UUID,
    gap_title: str,
    gap_description: str,
    affected_requirement_ids: Optional[list[UUID]] = None,
    project_id: Optional[UUID] = None,
    assignee_ids: Optional[list[UUID]] = None,
    created_by: Optional[UUID] = None,
    gap_analysis_id: Optional[UUID] = None,
    severity: Optional[str] = None,
    due_date: Optional[datetime] = None,
) -> models.Task:
    """Create a task for resolving a gap identified during analysis.

    Used by Gap Analyzer to create actionable tasks from identified gaps.

    Args:
        db: Database session
        organization_id: Organization UUID
        gap_title: Short description of the gap
        gap_description: Detailed description and resolution guidance
        affected_requirement_ids: Requirements affected by this gap
        project_id: Project scope for the gap
        assignee_ids: Optional list of user IDs to resolve
        created_by: User or system that identified the gap
        gap_analysis_id: Reference to the gap analysis run
        severity: Gap severity (critical, high, medium, low)
        due_date: Override default due date

    Returns:
        Created task
    """
    source_context = {
        "gap_title": gap_title,
        "affected_requirements": [str(rid) for rid in (affected_requirement_ids or [])],
        "gap_analysis_id": str(gap_analysis_id) if gap_analysis_id else None,
        "severity": severity,
    }

    # Map severity to priority
    priority = map_source_priority(TaskSourceType.GAP_ANALYSIS, severity)

    task_data = schemas.TaskCreate(
        organization_id=organization_id,
        project_id=project_id,
        title=f"Gap: {gap_title}",
        description=gap_description,
        task_type=models.TaskType.GAP_RESOLUTION,
        priority=priority,
        due_date=due_date or calculate_due_date(TaskSourceType.GAP_ANALYSIS),
        source_type=TaskSourceType.GAP_ANALYSIS,
        source_id=gap_analysis_id,
        source_context=source_context,
        assignee_ids=assignee_ids,
    )

    task = crud.create_task(db, task_data, created_by)
    logger.info(f"Created gap resolution task {task.human_readable_id}: {gap_title}")
    return task


def create_custom_task(
    db: Session,
    organization_id: UUID,
    title: str,
    description: Optional[str] = None,
    project_id: Optional[UUID] = None,
    priority: Optional[str] = None,
    assignee_ids: Optional[list[UUID]] = None,
    created_by: Optional[UUID] = None,
    source_reference: Optional[str] = None,
    source_context: Optional[dict] = None,
    due_date: Optional[datetime] = None,
) -> models.Task:
    """Create a custom task from external integrations.

    Used by external systems to create tasks via the standard interface.

    Args:
        db: Database session
        organization_id: Organization UUID
        title: Task title
        description: Task description
        project_id: Optional project scope
        priority: Priority level (critical, high, medium, low)
        assignee_ids: Optional list of assignee user IDs
        created_by: User creating the task
        source_reference: External system reference (e.g., "jira:PROJ-123")
        source_context: Additional context from external system
        due_date: Task due date

    Returns:
        Created task
    """
    context = source_context or {}
    if source_reference:
        context["source_reference"] = source_reference

    task_data = schemas.TaskCreate(
        organization_id=organization_id,
        project_id=project_id,
        title=title,
        description=description,
        task_type=models.TaskType.CUSTOM,
        priority=map_source_priority(TaskSourceType.CUSTOM, priority),
        due_date=due_date,
        source_type=TaskSourceType.CUSTOM,
        source_context=context if context else None,
        assignee_ids=assignee_ids,
    )

    task = crud.create_task(db, task_data, created_by)
    logger.info(f"Created custom task {task.human_readable_id}: {title}")
    return task


# =============================================================================
# Task Completion Callbacks
# =============================================================================

def handle_task_completion(
    db: Session,
    task: models.Task,
    completed_by: Optional[UUID] = None,
    resolution: Optional[str] = None,
) -> dict:
    """Handle task completion and notify source system.

    When a task is marked complete, this function:
    1. Records completion metadata
    2. Triggers source-specific callbacks
    3. Returns callback results

    Args:
        db: Database session
        task: The completed task
        completed_by: User who completed the task
        resolution: Optional resolution notes

    Returns:
        Dict with callback results and any follow-up actions
    """
    results = {
        "task_id": str(task.id),
        "source_type": task.source_type,
        "callback_executed": False,
        "follow_up_actions": [],
    }

    if not task.source_type:
        logger.info(f"Task {task.human_readable_id} has no source type, no callback needed")
        return results

    # Source-specific callbacks
    if task.source_type == TaskSourceType.REQUIREMENT_REVIEW:
        results.update(_handle_review_completion(db, task, completed_by, resolution))
    elif task.source_type == TaskSourceType.APPROVAL_REQUEST:
        results.update(_handle_approval_completion(db, task, completed_by, resolution))
    elif task.source_type == TaskSourceType.CLARIFICATION_POINT:
        results.update(_handle_clarification_completion(db, task, completed_by, resolution))
    elif task.source_type == TaskSourceType.GAP_ANALYSIS:
        results.update(_handle_gap_resolution_completion(db, task, completed_by, resolution))
    else:
        logger.info(f"Custom task {task.human_readable_id} completed, no built-in callback")

    results["callback_executed"] = True
    return results


def _handle_review_completion(
    db: Session,
    task: models.Task,
    completed_by: Optional[UUID],
    resolution: Optional[str],
) -> dict:
    """Handle completion of a requirement review task."""
    result = {"source_updated": False}

    if task.source_id:
        requirement = crud.get_requirement(db, task.source_id)
        if requirement:
            # Log the review completion in requirement history
            logger.info(
                f"Review task {task.human_readable_id} completed for requirement "
                f"{requirement.human_readable_id}"
            )
            result["source_updated"] = True
            result["requirement_id"] = str(requirement.id)
            result["requirement_human_id"] = requirement.human_readable_id
            # Note: Status transition should be done separately via transition_status
            # to maintain proper workflow control

    return result


def _handle_approval_completion(
    db: Session,
    task: models.Task,
    completed_by: Optional[UUID],
    resolution: Optional[str],
) -> dict:
    """Handle completion of an approval request task."""
    result = {"source_updated": False}

    if task.source_id:
        requirement = crud.get_requirement(db, task.source_id)
        if requirement and task.source_context:
            requested_status = task.source_context.get("requested_status")
            logger.info(
                f"Approval task {task.human_readable_id} completed for requirement "
                f"{requirement.human_readable_id} → {requested_status}"
            )
            result["source_updated"] = True
            result["requirement_id"] = str(requirement.id)
            result["requirement_human_id"] = requirement.human_readable_id
            result["requested_status"] = requested_status
            # Suggest follow-up action
            result["follow_up_actions"] = [
                f"Consider transitioning {requirement.human_readable_id} to {requested_status}"
            ]

    return result


def _handle_clarification_completion(
    db: Session,
    task: models.Task,
    completed_by: Optional[UUID],
    resolution: Optional[str],
) -> dict:
    """Handle completion of a clarification task."""
    result = {"source_updated": False}

    if task.source_id:
        requirement = crud.get_requirement(db, task.source_id)
        if requirement:
            logger.info(
                f"Clarification task {task.human_readable_id} resolved for requirement "
                f"{requirement.human_readable_id}"
            )
            result["source_updated"] = True
            result["requirement_id"] = str(requirement.id)
            result["requirement_human_id"] = requirement.human_readable_id
            if resolution:
                result["resolution"] = resolution
                # Suggest updating the requirement with clarification
                result["follow_up_actions"] = [
                    f"Consider updating {requirement.human_readable_id} with the clarification"
                ]

    return result


def _handle_gap_resolution_completion(
    db: Session,
    task: models.Task,
    completed_by: Optional[UUID],
    resolution: Optional[str],
) -> dict:
    """Handle completion of a gap resolution task."""
    result = {"source_updated": False}

    if task.source_context:
        affected = task.source_context.get("affected_requirements", [])
        logger.info(
            f"Gap resolution task {task.human_readable_id} completed, "
            f"affected {len(affected)} requirements"
        )
        result["affected_requirements"] = affected
        if resolution:
            result["resolution"] = resolution

    return result


# =============================================================================
# Task Source Utilities
# =============================================================================

def find_existing_task_for_source(
    db: Session,
    source_type: str,
    source_id: UUID,
    task_type: Optional[models.TaskType] = None,
    exclude_completed: bool = True,
) -> Optional[models.Task]:
    """Find existing task for a source artifact.

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
    return crud.find_task_by_source(
        db=db,
        source_type=source_type,
        source_id=source_id,
        task_type=task_type,
        exclude_completed=exclude_completed,
    )


def get_tasks_for_requirement(
    db: Session,
    requirement_id: UUID,
    include_completed: bool = False,
) -> list[models.Task]:
    """Get all tasks associated with a requirement.

    Args:
        db: Database session
        requirement_id: Requirement UUID
        include_completed: Whether to include completed/cancelled tasks

    Returns:
        List of tasks
    """
    return crud.get_tasks_by_source_id(
        db=db,
        source_id=requirement_id,
        include_completed=include_completed,
    )
