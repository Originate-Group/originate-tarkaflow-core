"""State machine validation for requirement lifecycle status transitions.

Enforces valid status transitions to maintain workflow integrity:
- Requirements must follow approval gates (draft → review → approved)
- Prevents invalid progressions that skip review steps
- Supports controlled back-transitions for flexibility
- Provides clear error messages for blocked transitions
"""
import logging
from typing import Optional

from .models import LifecycleStatus

logger = logging.getLogger("raas-core.state_machine")


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        message: str,
        current_status: LifecycleStatus,
        requested_status: LifecycleStatus,
        allowed_transitions: list[LifecycleStatus]
    ):
        super().__init__(message)
        self.current_status = current_status
        self.requested_status = requested_status
        self.allowed_transitions = allowed_transitions


# State machine transition matrix
# Maps current status → list of allowed next statuses
TRANSITION_MATRIX: dict[LifecycleStatus, list[LifecycleStatus]] = {
    LifecycleStatus.DRAFT: [
        LifecycleStatus.DRAFT,      # No-op (allowed)
        LifecycleStatus.REVIEW,     # Forward: submit for review
    ],
    LifecycleStatus.REVIEW: [
        LifecycleStatus.REVIEW,     # No-op (allowed)
        LifecycleStatus.DRAFT,      # Back: needs more work
        LifecycleStatus.APPROVED,   # Forward: approved after review
    ],
    LifecycleStatus.APPROVED: [
        LifecycleStatus.APPROVED,   # No-op (allowed)
        LifecycleStatus.DRAFT,      # Back: reopen for major changes
        LifecycleStatus.IN_PROGRESS,  # Forward: start implementation
    ],
    LifecycleStatus.IN_PROGRESS: [
        LifecycleStatus.IN_PROGRESS,  # No-op (allowed)
        LifecycleStatus.APPROVED,     # Back: blocked, back to backlog
        LifecycleStatus.IMPLEMENTED,  # Forward: implementation complete
    ],
    LifecycleStatus.IMPLEMENTED: [
        LifecycleStatus.IMPLEMENTED,  # No-op (allowed)
        LifecycleStatus.IN_PROGRESS,  # Back: found issues, rework needed
        LifecycleStatus.VALIDATED,    # Forward: testing/validation complete
    ],
    LifecycleStatus.VALIDATED: [
        LifecycleStatus.VALIDATED,    # No-op (allowed)
        LifecycleStatus.IMPLEMENTED,  # Back: validation failed, fix needed
        LifecycleStatus.DEPLOYED,     # Forward: deployed to production
    ],
    LifecycleStatus.DEPLOYED: [
        LifecycleStatus.DEPLOYED,     # No-op (allowed)
        # Note: Cannot transition out of deployed state
        # Deployed requirements are immutable records
        # New work requires creating child requirements
    ],
}


def is_transition_valid(
    current_status: LifecycleStatus,
    new_status: LifecycleStatus
) -> bool:
    """
    Check if a status transition is valid.

    Args:
        current_status: Current lifecycle status
        new_status: Requested new lifecycle status

    Returns:
        True if transition is allowed, False otherwise
    """
    allowed_transitions = TRANSITION_MATRIX.get(current_status, [])
    return new_status in allowed_transitions


def validate_transition(
    current_status: LifecycleStatus,
    new_status: LifecycleStatus
) -> None:
    """
    Validate a status transition and raise exception if invalid.

    Args:
        current_status: Current lifecycle status
        new_status: Requested new lifecycle status

    Raises:
        StateTransitionError: If the transition is not allowed
    """
    # No-op transitions are always allowed (setting same status)
    if current_status == new_status:
        logger.debug(f"No-op transition: {current_status.value} → {new_status.value}")
        return

    if not is_transition_valid(current_status, new_status):
        allowed_transitions = TRANSITION_MATRIX.get(current_status, [])
        allowed_names = [s.value for s in allowed_transitions if s != current_status]

        error_msg = (
            f"Invalid status transition: {current_status.value} → {new_status.value}. "
            f"From {current_status.value}, you can only transition to: {', '.join(allowed_names)}."
        )

        # Add helpful guidance based on the attempted transition
        if current_status == LifecycleStatus.DRAFT and new_status == LifecycleStatus.APPROVED:
            error_msg += " Requirements must be reviewed before approval. Transition to 'review' first."
        elif current_status == LifecycleStatus.DRAFT and new_status not in [LifecycleStatus.REVIEW]:
            error_msg += " Requirements in draft must go through review before implementation."
        elif current_status == LifecycleStatus.DEPLOYED:
            error_msg += " Deployed requirements are immutable. Create a new child requirement for additional work."

        logger.warning(f"Blocked transition: {error_msg}")
        raise StateTransitionError(
            message=error_msg,
            current_status=current_status,
            requested_status=new_status,
            allowed_transitions=allowed_transitions
        )

    logger.debug(f"Valid transition: {current_status.value} → {new_status.value}")


def get_allowed_transitions(current_status: LifecycleStatus) -> list[LifecycleStatus]:
    """
    Get list of allowed transitions from current status.

    Args:
        current_status: Current lifecycle status

    Returns:
        List of allowed next statuses (excluding no-op same status)
    """
    all_transitions = TRANSITION_MATRIX.get(current_status, [])
    # Filter out the no-op transition (same status)
    return [s for s in all_transitions if s != current_status]
