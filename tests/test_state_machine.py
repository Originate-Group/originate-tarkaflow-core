"""Tests for state machine validation."""
import pytest
from raas_core.models import LifecycleStatus
from raas_core.state_machine import (
    is_transition_valid,
    validate_transition,
    StateTransitionError,
    get_allowed_transitions
)


class TestStateTransitions:
    """Test state machine transition validation."""

    def test_valid_forward_transitions(self):
        """Test that valid forward transitions are allowed."""
        # Draft → Review
        assert is_transition_valid(LifecycleStatus.DRAFT, LifecycleStatus.REVIEW)
        validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.REVIEW)  # Should not raise

        # Review → Approved
        assert is_transition_valid(LifecycleStatus.REVIEW, LifecycleStatus.APPROVED)
        validate_transition(LifecycleStatus.REVIEW, LifecycleStatus.APPROVED)

        # Approved → In Progress
        assert is_transition_valid(LifecycleStatus.APPROVED, LifecycleStatus.IN_PROGRESS)
        validate_transition(LifecycleStatus.APPROVED, LifecycleStatus.IN_PROGRESS)

        # In Progress → Implemented
        assert is_transition_valid(LifecycleStatus.IN_PROGRESS, LifecycleStatus.IMPLEMENTED)
        validate_transition(LifecycleStatus.IN_PROGRESS, LifecycleStatus.IMPLEMENTED)

        # Implemented → Validated
        assert is_transition_valid(LifecycleStatus.IMPLEMENTED, LifecycleStatus.VALIDATED)
        validate_transition(LifecycleStatus.IMPLEMENTED, LifecycleStatus.VALIDATED)

        # Validated → Deployed
        assert is_transition_valid(LifecycleStatus.VALIDATED, LifecycleStatus.DEPLOYED)
        validate_transition(LifecycleStatus.VALIDATED, LifecycleStatus.DEPLOYED)

    def test_valid_back_transitions(self):
        """Test that valid back-transitions are allowed."""
        # Review → Draft (needs more work)
        assert is_transition_valid(LifecycleStatus.REVIEW, LifecycleStatus.DRAFT)
        validate_transition(LifecycleStatus.REVIEW, LifecycleStatus.DRAFT)

        # Approved → Draft (major changes needed)
        assert is_transition_valid(LifecycleStatus.APPROVED, LifecycleStatus.DRAFT)
        validate_transition(LifecycleStatus.APPROVED, LifecycleStatus.DRAFT)

        # In Progress → Approved (blocked)
        assert is_transition_valid(LifecycleStatus.IN_PROGRESS, LifecycleStatus.APPROVED)
        validate_transition(LifecycleStatus.IN_PROGRESS, LifecycleStatus.APPROVED)

        # Implemented → In Progress (found issues)
        assert is_transition_valid(LifecycleStatus.IMPLEMENTED, LifecycleStatus.IN_PROGRESS)
        validate_transition(LifecycleStatus.IMPLEMENTED, LifecycleStatus.IN_PROGRESS)

        # Validated → Implemented (validation failed)
        assert is_transition_valid(LifecycleStatus.VALIDATED, LifecycleStatus.IMPLEMENTED)
        validate_transition(LifecycleStatus.VALIDATED, LifecycleStatus.IMPLEMENTED)

    def test_noop_transitions_allowed(self):
        """Test that no-op transitions (same status) are always allowed."""
        for status in LifecycleStatus:
            assert is_transition_valid(status, status)
            validate_transition(status, status)  # Should not raise

    def test_invalid_skip_review_transition(self):
        """Test that skipping review (Draft → Approved) is blocked."""
        assert not is_transition_valid(LifecycleStatus.DRAFT, LifecycleStatus.APPROVED)

        with pytest.raises(StateTransitionError) as exc_info:
            validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.APPROVED)

        error = exc_info.value
        assert error.current_status == LifecycleStatus.DRAFT
        assert error.requested_status == LifecycleStatus.APPROVED
        assert "must be reviewed before approval" in str(error).lower()

    def test_invalid_draft_to_implementation(self):
        """Test that jumping from Draft to implementation states is blocked."""
        invalid_transitions = [
            LifecycleStatus.IN_PROGRESS,
            LifecycleStatus.IMPLEMENTED,
            LifecycleStatus.VALIDATED,
            LifecycleStatus.DEPLOYED
        ]

        for target_status in invalid_transitions:
            assert not is_transition_valid(LifecycleStatus.DRAFT, target_status)

            with pytest.raises(StateTransitionError):
                validate_transition(LifecycleStatus.DRAFT, target_status)

    def test_deployed_is_immutable(self):
        """Test that deployed status cannot be changed."""
        # Only transition from deployed to deployed (no-op) is allowed
        assert is_transition_valid(LifecycleStatus.DEPLOYED, LifecycleStatus.DEPLOYED)

        # All other transitions from deployed should be blocked
        for status in LifecycleStatus:
            if status != LifecycleStatus.DEPLOYED:
                assert not is_transition_valid(LifecycleStatus.DEPLOYED, status)

                with pytest.raises(StateTransitionError) as exc_info:
                    validate_transition(LifecycleStatus.DEPLOYED, status)

                assert "immutable" in str(exc_info.value).lower()

    def test_get_allowed_transitions(self):
        """Test getting allowed transitions from each state."""
        # Draft can go to Review (no-op excluded)
        assert get_allowed_transitions(LifecycleStatus.DRAFT) == [LifecycleStatus.REVIEW]

        # Review can go to Draft or Approved (no-op excluded)
        allowed = get_allowed_transitions(LifecycleStatus.REVIEW)
        assert set(allowed) == {LifecycleStatus.DRAFT, LifecycleStatus.APPROVED}

        # Deployed has no allowed transitions (no-op excluded)
        assert get_allowed_transitions(LifecycleStatus.DEPLOYED) == []

    def test_state_transition_error_attributes(self):
        """Test that StateTransitionError contains all required attributes."""
        with pytest.raises(StateTransitionError) as exc_info:
            validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.IMPLEMENTED)

        error = exc_info.value
        assert hasattr(error, 'current_status')
        assert hasattr(error, 'requested_status')
        assert hasattr(error, 'allowed_transitions')
        assert error.current_status == LifecycleStatus.DRAFT
        assert error.requested_status == LifecycleStatus.IMPLEMENTED
        assert isinstance(error.allowed_transitions, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
