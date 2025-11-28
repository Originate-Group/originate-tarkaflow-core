"""State machine validation for Work Item lifecycle status transitions.

CR-010: RAAS-FEAT-099 - Work Item Lifecycle & CR Merge Trigger
RAAS-FEAT-102: Release Work Item & Bundled Deployment

Work Items track implementation progress separate from requirement specifications.
The state machine enforces valid status transitions to maintain workflow integrity.

Standard lifecycle (IR/CR/BUG/TASK): created -> in_progress -> implemented -> validated -> deployed -> completed
Release lifecycle: created -> in_progress -> deployed -> completed (skip implemented/validated)

Terminal states: completed, cancelled
"""
import logging
from typing import Optional

from .models import WorkItemStatus, WorkItemType

logger = logging.getLogger("raas-core.work_item_state_machine")


class WorkItemStateTransitionError(Exception):
    """Raised when an invalid Work Item state transition is attempted."""

    def __init__(
        self,
        message: str,
        current_status: WorkItemStatus,
        requested_status: WorkItemStatus,
        allowed_transitions: list[WorkItemStatus]
    ):
        super().__init__(message)
        self.current_status = current_status
        self.requested_status = requested_status
        self.allowed_transitions = allowed_transitions


# Work Item state machine transition matrix
# Maps current status → list of allowed next statuses
WORK_ITEM_TRANSITION_MATRIX: dict[WorkItemStatus, list[WorkItemStatus]] = {
    WorkItemStatus.CREATED: [
        WorkItemStatus.CREATED,       # No-op (allowed)
        WorkItemStatus.IN_PROGRESS,   # Forward: work started
        WorkItemStatus.CANCELLED,     # Terminal: abandoned before starting
    ],
    WorkItemStatus.IN_PROGRESS: [
        WorkItemStatus.IN_PROGRESS,   # No-op (allowed)
        WorkItemStatus.CREATED,       # Back: blocked, return to backlog
        WorkItemStatus.IMPLEMENTED,   # Forward: code complete
        WorkItemStatus.CANCELLED,     # Terminal: abandoned
    ],
    WorkItemStatus.IMPLEMENTED: [
        WorkItemStatus.IMPLEMENTED,   # No-op (allowed)
        WorkItemStatus.IN_PROGRESS,   # Back: found issues, rework needed
        WorkItemStatus.VALIDATED,     # Forward: testing passed
        WorkItemStatus.CANCELLED,     # Terminal: abandoned
    ],
    WorkItemStatus.VALIDATED: [
        WorkItemStatus.VALIDATED,     # No-op (allowed)
        WorkItemStatus.IMPLEMENTED,   # Back: validation failed, fix needed
        WorkItemStatus.DEPLOYED,      # Forward: deployed to production
        WorkItemStatus.CANCELLED,     # Terminal: abandoned
    ],
    WorkItemStatus.DEPLOYED: [
        WorkItemStatus.DEPLOYED,      # No-op (allowed)
        WorkItemStatus.VALIDATED,     # Back: deployment issue, rollback
        WorkItemStatus.COMPLETED,     # Forward: successfully finished
        WorkItemStatus.CANCELLED,     # Terminal: abandoned (rare at this stage)
    ],
    WorkItemStatus.COMPLETED: [
        WorkItemStatus.COMPLETED,     # No-op (allowed)
        # Terminal state - no transitions out
        # Completed work items are immutable records
    ],
    WorkItemStatus.CANCELLED: [
        WorkItemStatus.CANCELLED,     # No-op (allowed)
        # Terminal state - no transitions out
        # Create new work item if work needs to resume
    ],
}


# RAAS-FEAT-102: Release work item state machine (simplified lifecycle)
# Releases skip implemented/validated: created -> in_progress -> deployed -> completed
RELEASE_TRANSITION_MATRIX: dict[WorkItemStatus, list[WorkItemStatus]] = {
    WorkItemStatus.CREATED: [
        WorkItemStatus.CREATED,       # No-op (allowed)
        WorkItemStatus.IN_PROGRESS,   # Forward: release preparation started
        WorkItemStatus.CANCELLED,     # Terminal: abandoned before starting
    ],
    WorkItemStatus.IN_PROGRESS: [
        WorkItemStatus.IN_PROGRESS,   # No-op (allowed)
        WorkItemStatus.CREATED,       # Back: blocked, return to backlog
        WorkItemStatus.DEPLOYED,      # Forward: release deployed (skips implemented/validated)
        WorkItemStatus.CANCELLED,     # Terminal: abandoned
    ],
    # Releases skip IMPLEMENTED and VALIDATED statuses
    WorkItemStatus.DEPLOYED: [
        WorkItemStatus.DEPLOYED,      # No-op (allowed)
        WorkItemStatus.IN_PROGRESS,   # Back: deployment issue, rollback
        WorkItemStatus.COMPLETED,     # Forward: successfully finished
        WorkItemStatus.CANCELLED,     # Terminal: abandoned (rare at this stage)
    ],
    WorkItemStatus.COMPLETED: [
        WorkItemStatus.COMPLETED,     # No-op (allowed)
        # Terminal state - no transitions out
    ],
    WorkItemStatus.CANCELLED: [
        WorkItemStatus.CANCELLED,     # No-op (allowed)
        # Terminal state - no transitions out
    ],
}


def get_transition_matrix(work_item_type: Optional[WorkItemType] = None) -> dict[WorkItemStatus, list[WorkItemStatus]]:
    """Get the appropriate transition matrix for a work item type.

    Args:
        work_item_type: The type of work item (defaults to standard matrix if None)

    Returns:
        The transition matrix for this work item type
    """
    if work_item_type == WorkItemType.RELEASE:
        return RELEASE_TRANSITION_MATRIX
    return WORK_ITEM_TRANSITION_MATRIX


def is_work_item_transition_valid(
    current_status: WorkItemStatus,
    new_status: WorkItemStatus,
    work_item_type: Optional[WorkItemType] = None
) -> bool:
    """
    Check if a Work Item status transition is valid.

    Args:
        current_status: Current lifecycle status
        new_status: Requested new lifecycle status
        work_item_type: Type of work item (uses Release matrix if RELEASE)

    Returns:
        True if transition is allowed, False otherwise
    """
    matrix = get_transition_matrix(work_item_type)
    allowed_transitions = matrix.get(current_status, [])
    return new_status in allowed_transitions


def validate_work_item_transition(
    current_status: WorkItemStatus,
    new_status: WorkItemStatus,
    work_item_type: Optional[WorkItemType] = None
) -> None:
    """
    Validate a Work Item status transition and raise exception if invalid.

    Args:
        current_status: Current lifecycle status
        new_status: Requested new lifecycle status
        work_item_type: Type of work item (uses Release matrix if RELEASE)

    Raises:
        WorkItemStateTransitionError: If the transition is not allowed
    """
    # No-op transitions are always allowed (setting same status)
    if current_status == new_status:
        logger.debug(f"No-op Work Item transition: {current_status.value} → {new_status.value}")
        return

    if not is_work_item_transition_valid(current_status, new_status, work_item_type):
        matrix = get_transition_matrix(work_item_type)
        allowed_transitions = matrix.get(current_status, [])
        allowed_names = [s.value for s in allowed_transitions if s != current_status]

        type_label = f" ({work_item_type.value})" if work_item_type else ""
        error_msg = (
            f"Invalid Work Item{type_label} status transition: {current_status.value} → {new_status.value}. "
            f"From {current_status.value}, you can only transition to: {', '.join(allowed_names)}."
        )

        # Add helpful guidance based on the attempted transition
        if current_status == WorkItemStatus.COMPLETED:
            error_msg += " Completed work items are immutable. Create a new work item for additional work."
        elif current_status == WorkItemStatus.CANCELLED:
            error_msg += " Cancelled work items cannot be reactivated. Create a new work item to restart."
        elif current_status == WorkItemStatus.CREATED and new_status == WorkItemStatus.IMPLEMENTED:
            error_msg += " Work items must be marked in_progress before being implemented."
        elif work_item_type == WorkItemType.RELEASE and new_status in [WorkItemStatus.IMPLEMENTED, WorkItemStatus.VALIDATED]:
            error_msg += " Release work items skip implemented/validated stages - transition directly to deployed."

        logger.warning(f"Blocked Work Item transition: {error_msg}")
        raise WorkItemStateTransitionError(
            message=error_msg,
            current_status=current_status,
            requested_status=new_status,
            allowed_transitions=allowed_transitions
        )

    logger.debug(f"Valid Work Item transition: {current_status.value} → {new_status.value}")


def get_allowed_work_item_transitions(
    current_status: WorkItemStatus,
    work_item_type: Optional[WorkItemType] = None
) -> list[WorkItemStatus]:
    """
    Get list of allowed transitions from current Work Item status.

    Args:
        current_status: Current lifecycle status
        work_item_type: Type of work item (uses Release matrix if RELEASE)

    Returns:
        List of allowed next statuses (excluding no-op same status)
    """
    matrix = get_transition_matrix(work_item_type)
    all_transitions = matrix.get(current_status, [])
    # Filter out the no-op transition (same status)
    return [s for s in all_transitions if s != current_status]


def is_terminal_status(status: WorkItemStatus) -> bool:
    """Check if a Work Item status is terminal (no further transitions)."""
    return status in [WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED]


def triggers_cr_merge(old_status: WorkItemStatus, new_status: WorkItemStatus) -> bool:
    """
    Check if a transition should trigger CR merge (requirement version creation).

    CR merge is triggered when a CR-type Work Item transitions to COMPLETED.
    The actual type check must be done by the caller since this function
    only checks the status transition.

    Args:
        old_status: Previous status
        new_status: New status

    Returns:
        True if this transition should trigger CR merge for CR-type work items
    """
    return old_status != WorkItemStatus.COMPLETED and new_status == WorkItemStatus.COMPLETED


# Work Item status sort order for list queries
# Lower number = higher priority (shown first)
# Reflects workflow priority: active work first, backlog last
WORK_ITEM_STATUS_SORT_ORDER: dict[WorkItemStatus, int] = {
    WorkItemStatus.IN_PROGRESS: 1,   # Actively working - highest priority
    WorkItemStatus.IMPLEMENTED: 2,   # Needs validation
    WorkItemStatus.VALIDATED: 3,     # Ready for deployment
    WorkItemStatus.DEPLOYED: 4,      # Needs completion confirmation
    WorkItemStatus.CREATED: 5,       # Backlog - lower priority
    WorkItemStatus.COMPLETED: 6,     # Done (usually excluded from lists)
    WorkItemStatus.CANCELLED: 7,     # Abandoned (usually excluded from lists)
}
