"""Task Assignment and Routing (RAAS-COMP-067).

Manages task assignment logic including default routing rules,
manual assignment, reassignment, and delegation.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from . import models, schemas

logger = logging.getLogger("raas-core.task_routing")


# =============================================================================
# Routing Rule CRUD
# =============================================================================

def create_routing_rule(
    db: Session,
    rule_data: schemas.RoutingRuleCreate,
    created_by: Optional[UUID] = None,
) -> models.TaskRoutingRule:
    """Create a new task routing rule.

    Args:
        db: Database session
        rule_data: Routing rule creation data
        created_by: User creating the rule

    Returns:
        Created TaskRoutingRule
    """
    rule = models.TaskRoutingRule(
        id=uuid4(),
        organization_id=rule_data.organization_id,
        project_id=rule_data.project_id,
        name=rule_data.name,
        description=rule_data.description,
        scope=models.RoutingRuleScope(rule_data.scope),
        match_type=models.RoutingRuleMatchType(rule_data.match_type),
        match_value=rule_data.match_value,
        assignee_user_id=rule_data.assignee_user_id,
        assignee_role=rule_data.assignee_role,
        fallback_user_id=rule_data.fallback_user_id,
        priority=rule_data.priority,
        is_active=rule_data.is_active,
        created_by=created_by,
    )

    db.add(rule)
    db.commit()
    db.refresh(rule)

    logger.info(f"Created routing rule '{rule.name}' for org {rule.organization_id}")
    return rule


def get_routing_rule(
    db: Session,
    rule_id: UUID,
) -> Optional[models.TaskRoutingRule]:
    """Get a routing rule by ID.

    Args:
        db: Database session
        rule_id: Rule UUID

    Returns:
        TaskRoutingRule or None
    """
    return db.query(models.TaskRoutingRule).filter(
        models.TaskRoutingRule.id == rule_id
    ).first()


def get_routing_rules(
    db: Session,
    organization_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    match_type: Optional[str] = None,
    is_active: Optional[bool] = True,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[models.TaskRoutingRule], int]:
    """Get routing rules with filtering.

    Args:
        db: Database session
        organization_id: Filter by organization
        project_id: Filter by project
        match_type: Filter by match type
        is_active: Filter by active status (default True)
        skip: Pagination offset
        limit: Pagination limit

    Returns:
        Tuple of (rules list, total count)
    """
    query = db.query(models.TaskRoutingRule)

    if organization_id:
        query = query.filter(models.TaskRoutingRule.organization_id == organization_id)
    if project_id:
        query = query.filter(models.TaskRoutingRule.project_id == project_id)
    if match_type:
        query = query.filter(models.TaskRoutingRule.match_type == models.RoutingRuleMatchType(match_type))
    if is_active is not None:
        query = query.filter(models.TaskRoutingRule.is_active == is_active)

    total = query.count()

    rules = query.order_by(
        models.TaskRoutingRule.priority.asc(),
        models.TaskRoutingRule.created_at.desc()
    ).offset(skip).limit(limit).all()

    return rules, total


def update_routing_rule(
    db: Session,
    rule_id: UUID,
    rule_update: schemas.RoutingRuleUpdate,
) -> Optional[models.TaskRoutingRule]:
    """Update a routing rule.

    Args:
        db: Database session
        rule_id: Rule UUID
        rule_update: Update data

    Returns:
        Updated TaskRoutingRule or None
    """
    rule = get_routing_rule(db, rule_id)
    if not rule:
        return None

    update_data = rule_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "scope" and value:
            value = models.RoutingRuleScope(value)
        elif field == "match_type" and value:
            value = models.RoutingRuleMatchType(value)
        setattr(rule, field, value)

    rule.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rule)

    logger.info(f"Updated routing rule '{rule.name}'")
    return rule


def delete_routing_rule(
    db: Session,
    rule_id: UUID,
) -> bool:
    """Delete a routing rule.

    Args:
        db: Database session
        rule_id: Rule UUID

    Returns:
        True if deleted, False if not found
    """
    rule = get_routing_rule(db, rule_id)
    if not rule:
        return False

    db.delete(rule)
    db.commit()
    logger.info(f"Deleted routing rule {rule_id}")
    return True


# =============================================================================
# Task Assignment Logic
# =============================================================================

def find_matching_rules(
    db: Session,
    task: models.Task,
) -> list[models.TaskRoutingRule]:
    """Find routing rules that match a task.

    Rules are returned in priority order (lowest priority number first).
    Project-scoped rules are evaluated before organization-scoped rules.

    Args:
        db: Database session
        task: Task to match

    Returns:
        List of matching rules in priority order
    """
    matching_rules = []

    # Build list of criteria to check
    criteria = [
        (models.RoutingRuleMatchType.TASK_TYPE, task.task_type.value if task.task_type else None),
        (models.RoutingRuleMatchType.SOURCE_TYPE, task.source_type),
        (models.RoutingRuleMatchType.PRIORITY, task.priority.value if task.priority else None),
    ]

    # Check for requirement-specific criteria if source is a requirement
    if task.source_id and task.source_context:
        req_type = task.source_context.get("requirement_type")
        if req_type:
            criteria.append((models.RoutingRuleMatchType.REQUIREMENT_TYPE, req_type))

    # Query for project-scoped rules first (higher specificity)
    if task.project_id:
        project_rules = db.query(models.TaskRoutingRule).filter(
            models.TaskRoutingRule.organization_id == task.organization_id,
            models.TaskRoutingRule.project_id == task.project_id,
            models.TaskRoutingRule.is_active == True,
        ).order_by(
            models.TaskRoutingRule.priority.asc()
        ).all()

        for rule in project_rules:
            for match_type, match_value in criteria:
                if rule.match_type == match_type and rule.match_value == match_value:
                    matching_rules.append(rule)
                    break

    # Then check organization-scoped rules
    org_rules = db.query(models.TaskRoutingRule).filter(
        models.TaskRoutingRule.organization_id == task.organization_id,
        models.TaskRoutingRule.project_id.is_(None),
        models.TaskRoutingRule.is_active == True,
    ).order_by(
        models.TaskRoutingRule.priority.asc()
    ).all()

    for rule in org_rules:
        for match_type, match_value in criteria:
            if rule.match_type == match_type and rule.match_value == match_value:
                matching_rules.append(rule)
                break

    return matching_rules


def resolve_assignee_from_rule(
    db: Session,
    rule: models.TaskRoutingRule,
    task: models.Task,
) -> Optional[UUID]:
    """Resolve the assignee from a routing rule.

    Args:
        db: Database session
        rule: Routing rule
        task: Task being assigned

    Returns:
        User UUID to assign, or None
    """
    # Direct user assignment takes precedence
    if rule.assignee_user_id:
        return rule.assignee_user_id

    # Role-based assignment
    if rule.assignee_role:
        assignee = resolve_assignee_by_role(db, task, rule.assignee_role)
        if assignee:
            return assignee

    # Fallback assignment
    if rule.fallback_user_id:
        return rule.fallback_user_id

    return None


def resolve_assignee_by_role(
    db: Session,
    task: models.Task,
    role: str,
) -> Optional[UUID]:
    """Resolve an assignee based on role.

    Supported roles:
    - "owner": Owner of the source artifact (requirement)
    - "product_owner": Project product owner
    - "scrum_master": Project scrum master
    - "project_admin": Project administrator

    Args:
        db: Database session
        task: Task to assign
        role: Role to resolve

    Returns:
        User UUID or None
    """
    role_lower = role.lower()

    if role_lower == "owner":
        # Get owner of source artifact
        if task.source_id:
            from . import crud
            requirement = crud.get_requirement(db, task.source_id)
            if requirement and requirement.created_by:
                return requirement.created_by

    elif role_lower in ["product_owner", "scrum_master", "project_admin"]:
        # Get from project members by role
        if task.project_id:
            role_map = {
                "product_owner": models.ProjectRole.ADMIN,  # PO typically has admin role
                "scrum_master": models.ProjectRole.ADMIN,
                "project_admin": models.ProjectRole.ADMIN,
            }
            target_role = role_map.get(role_lower, models.ProjectRole.ADMIN)

            member = db.query(models.ProjectMember).filter(
                models.ProjectMember.project_id == task.project_id,
                models.ProjectMember.role == target_role
            ).first()

            if member:
                return member.user_id

    return None


def apply_routing_rules(
    db: Session,
    task: models.Task,
    explicit_assignees: Optional[list[UUID]] = None,
) -> list[UUID]:
    """Apply routing rules to determine task assignees.

    Priority:
    1. Explicit assignees (if provided)
    2. Matching routing rules
    3. Organization fallback (if configured)

    Args:
        db: Database session
        task: Task to assign
        explicit_assignees: Explicitly provided assignees (override rules)

    Returns:
        List of assignee UUIDs
    """
    # Explicit assignees override routing rules
    if explicit_assignees:
        logger.debug(f"Using explicit assignees for task {task.id}: {explicit_assignees}")
        return explicit_assignees

    # Find matching rules
    rules = find_matching_rules(db, task)
    assignees = []

    for rule in rules:
        assignee = resolve_assignee_from_rule(db, rule, task)
        if assignee and assignee not in assignees:
            assignees.append(assignee)
            logger.info(f"Rule '{rule.name}' assigned {assignee} to task {task.id}")
            break  # Use first matching rule

    if not assignees:
        logger.warning(f"No routing rules matched task {task.id}, task will be unassigned")

    return assignees


def get_organization_fallback_assignee(
    db: Session,
    organization_id: UUID,
) -> Optional[UUID]:
    """Get the fallback assignee for an organization.

    Returns the organization owner as fallback.

    Args:
        db: Database session
        organization_id: Organization UUID

    Returns:
        User UUID or None
    """
    owner = db.query(models.OrganizationMember).filter(
        models.OrganizationMember.organization_id == organization_id,
        models.OrganizationMember.role == models.MemberRole.OWNER
    ).first()

    return owner.user_id if owner else None


# =============================================================================
# Task Delegation
# =============================================================================

def delegate_task(
    db: Session,
    task: models.Task,
    delegated_by: UUID,
    delegated_to: UUID,
    reason: Optional[str] = None,
) -> models.TaskDelegation:
    """Delegate a task from one user to another.

    Args:
        db: Database session
        task: Task to delegate
        delegated_by: User delegating the task
        delegated_to: User receiving the delegation
        reason: Reason for delegation

    Returns:
        TaskDelegation record
    """
    # Record original assignee (first one if multiple)
    original_assignee = task.assignees[0].id if task.assignees else None

    # Create delegation record
    delegation = models.TaskDelegation(
        id=uuid4(),
        task_id=task.id,
        delegated_by=delegated_by,
        delegated_to=delegated_to,
        original_assignee=original_assignee,
        reason=reason,
    )
    db.add(delegation)

    # Update task assignees
    from . import crud
    crud.assign_task(db, task.id, [delegated_to], delegated_by, replace=True)

    # Record in task history
    history = models.TaskHistory(
        id=uuid4(),
        task_id=task.id,
        change_type=models.TaskChangeType.ASSIGNMENT_CHANGED,
        field_name="delegated",
        old_value=str(original_assignee) if original_assignee else None,
        new_value=str(delegated_to),
        comment=f"Delegated: {reason}" if reason else "Task delegated",
        changed_by=delegated_by,
    )
    db.add(history)

    db.commit()
    db.refresh(delegation)

    logger.info(f"Task {task.human_readable_id} delegated from {delegated_by} to {delegated_to}")
    return delegation


def get_task_delegations(
    db: Session,
    task_id: UUID,
) -> list[models.TaskDelegation]:
    """Get delegation history for a task.

    Args:
        db: Database session
        task_id: Task UUID

    Returns:
        List of TaskDelegation records
    """
    return db.query(models.TaskDelegation).filter(
        models.TaskDelegation.task_id == task_id
    ).order_by(
        models.TaskDelegation.delegated_at.desc()
    ).all()


# =============================================================================
# Task Escalation
# =============================================================================

def escalate_task(
    db: Session,
    task: models.Task,
    escalated_to: UUID,
    reason: str,
    escalated_from: Optional[UUID] = None,
    notes: Optional[str] = None,
    by_system: bool = False,
) -> models.TaskEscalation:
    """Escalate a task to another user.

    Args:
        db: Database session
        task: Task to escalate
        escalated_to: User receiving the escalation
        reason: Reason code (unassigned, overdue, unresponsive, manual)
        escalated_from: User being escalated from (current assignee)
        notes: Additional notes
        by_system: Whether this is an automated escalation

    Returns:
        TaskEscalation record
    """
    if not escalated_from and task.assignees:
        escalated_from = task.assignees[0].id

    escalation = models.TaskEscalation(
        id=uuid4(),
        task_id=task.id,
        escalated_from=escalated_from,
        escalated_to=escalated_to,
        reason=reason,
        notes=notes,
        escalated_by_system=by_system,
    )
    db.add(escalation)

    # Update task assignees
    from . import crud
    crud.assign_task(db, task.id, [escalated_to], None, replace=True)

    # Update task priority if needed (escalation may bump priority)
    if task.priority == models.TaskPriority.LOW:
        task.priority = models.TaskPriority.MEDIUM
    elif task.priority == models.TaskPriority.MEDIUM:
        task.priority = models.TaskPriority.HIGH

    # Record in task history
    history = models.TaskHistory(
        id=uuid4(),
        task_id=task.id,
        change_type=models.TaskChangeType.ASSIGNMENT_CHANGED,
        field_name="escalated",
        old_value=str(escalated_from) if escalated_from else None,
        new_value=str(escalated_to),
        comment=f"Escalated ({reason}): {notes}" if notes else f"Task escalated: {reason}",
        changed_by=None if by_system else escalated_to,
    )
    db.add(history)

    db.commit()
    db.refresh(escalation)

    logger.info(
        f"Task {task.human_readable_id} escalated to {escalated_to} "
        f"(reason: {reason}, system: {by_system})"
    )
    return escalation


def get_task_escalations(
    db: Session,
    task_id: UUID,
) -> list[models.TaskEscalation]:
    """Get escalation history for a task.

    Args:
        db: Database session
        task_id: Task UUID

    Returns:
        List of TaskEscalation records
    """
    return db.query(models.TaskEscalation).filter(
        models.TaskEscalation.task_id == task_id
    ).order_by(
        models.TaskEscalation.escalated_at.desc()
    ).all()


def find_unassigned_tasks(
    db: Session,
    organization_id: Optional[UUID] = None,
) -> list[models.Task]:
    """Find tasks that have no assignees.

    Used for escalation processing.

    Args:
        db: Database session
        organization_id: Optional filter by organization

    Returns:
        List of unassigned tasks
    """
    query = db.query(models.Task).filter(
        ~models.Task.assignees.any(),
        models.Task.status.notin_([
            models.TaskStatus.COMPLETED,
            models.TaskStatus.CANCELLED
        ])
    )

    if organization_id:
        query = query.filter(models.Task.organization_id == organization_id)

    return query.all()


def find_overdue_tasks(
    db: Session,
    organization_id: Optional[UUID] = None,
) -> list[models.Task]:
    """Find tasks that are past their due date.

    Used for escalation processing.

    Args:
        db: Database session
        organization_id: Optional filter by organization

    Returns:
        List of overdue tasks
    """
    query = db.query(models.Task).filter(
        models.Task.due_date.isnot(None),
        models.Task.due_date < datetime.utcnow(),
        models.Task.status.notin_([
            models.TaskStatus.COMPLETED,
            models.TaskStatus.CANCELLED
        ])
    )

    if organization_id:
        query = query.filter(models.Task.organization_id == organization_id)

    return query.all()
