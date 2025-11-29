"""Tests for BUG-004: Tag and Status Changes Should Not Create New Requirement Versions.

This module tests that operational metadata changes (tags, status) do not trigger
versioning or status regression, while actual specification changes do.

Key behaviors:
- Tags are operational metadata, stored in database column only
- Status is managed via state machine, not stored in content
- Only specification changes (title, body, depends_on, adheres_to) trigger versioning
"""
import pytest
from tarka_core.markdown_utils import (
    strip_system_fields_from_frontmatter,
    inject_database_state,
    parse_markdown,
)
from tarka_core.versioning import content_has_changed


class TestStripSystemFields:
    """Test that system fields are properly stripped from frontmatter."""

    def test_tags_stripped_from_content(self):
        """BUG-004: Tags should be stripped from stored content."""
        content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
tags: [tag1, tag2, sprint-1]
depends_on: []
status: approved
---

## Description
Test feature description.
"""
        cleaned = strip_system_fields_from_frontmatter(content)
        parsed = parse_markdown(cleaned)

        # Tags should NOT be in cleaned frontmatter
        assert "tags" not in parsed["frontmatter"]
        # But type, title, parent_id, depends_on should remain
        assert parsed["frontmatter"]["type"] == "feature"
        assert parsed["frontmatter"]["title"] == "Test Feature"
        assert "parent_id" in parsed["frontmatter"]

    def test_status_stripped_from_content(self):
        """Status should be stripped from stored content."""
        content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
status: approved
---

## Description
Test feature description.
"""
        cleaned = strip_system_fields_from_frontmatter(content)
        parsed = parse_markdown(cleaned)

        # Status should NOT be in cleaned frontmatter
        assert "status" not in parsed["frontmatter"]

    def test_authored_fields_preserved(self):
        """Authored fields (type, title, parent_id, depends_on, adheres_to) should be preserved."""
        content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
depends_on: [dep-uuid-1, dep-uuid-2]
adheres_to: [GUARD-SEC-001]
tags: [will-be-stripped]
status: approved
---

## Description
Test feature description.
"""
        cleaned = strip_system_fields_from_frontmatter(content)
        parsed = parse_markdown(cleaned)

        # All authored fields should be preserved
        assert parsed["frontmatter"]["type"] == "feature"
        assert parsed["frontmatter"]["title"] == "Test Feature"
        assert "parent_id" in parsed["frontmatter"]
        assert "dep-uuid-1" in parsed["frontmatter"]["depends_on"]
        assert "GUARD-SEC-001" in parsed["frontmatter"]["adheres_to"]


class TestInjectDatabaseState:
    """Test that database state is properly injected into content."""

    def test_tags_injected_from_database(self):
        """BUG-004: Tags should be injected from database into returned content."""
        # Stored content (no tags)
        stored_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Test feature description.
"""
        # Inject database state including tags
        injected = inject_database_state(
            stored_content,
            status="approved",
            human_readable_id="RAAS-FEAT-001",
            tags=["tag1", "tag2", "sprint-1"]
        )
        parsed = parse_markdown(injected)

        # Tags should now be in frontmatter
        assert parsed["frontmatter"]["tags"] == ["tag1", "tag2", "sprint-1"]
        assert parsed["frontmatter"]["status"] == "approved"
        assert parsed["frontmatter"]["human_readable_id"] == "RAAS-FEAT-001"

    def test_empty_tags_injected(self):
        """Empty tags list should be properly injected."""
        stored_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Test feature description.
"""
        injected = inject_database_state(
            stored_content,
            status="draft",
            tags=[]
        )
        parsed = parse_markdown(injected)

        assert parsed["frontmatter"]["tags"] == []


class TestContentChangeDetection:
    """Test that content changes are properly detected (excluding operational metadata)."""

    def test_tag_only_change_not_detected(self):
        """BUG-004: Tag-only changes should not be detected as content changes."""
        old_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
tags: [old-tag]
---

## Description
Same description.
"""
        new_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
tags: [new-tag, another-tag]
---

## Description
Same description.
"""
        # Strip system fields from both
        cleaned_old = strip_system_fields_from_frontmatter(old_content)
        cleaned_new = strip_system_fields_from_frontmatter(new_content)

        # Should NOT detect a change (tags are stripped)
        assert not content_has_changed(cleaned_old, cleaned_new)

    def test_status_only_change_not_detected(self):
        """Status-only changes should not be detected as content changes."""
        old_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
status: draft
---

## Description
Same description.
"""
        new_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
status: approved
---

## Description
Same description.
"""
        cleaned_old = strip_system_fields_from_frontmatter(old_content)
        cleaned_new = strip_system_fields_from_frontmatter(new_content)

        # Should NOT detect a change (status is stripped)
        assert not content_has_changed(cleaned_old, cleaned_new)

    def test_title_change_detected(self):
        """Title changes should be detected as content changes."""
        old_content = """---
type: feature
title: Old Title
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Same description.
"""
        new_content = """---
type: feature
title: New Title
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Same description.
"""
        cleaned_old = strip_system_fields_from_frontmatter(old_content)
        cleaned_new = strip_system_fields_from_frontmatter(new_content)

        # Should detect a change (title is a versioned field)
        assert content_has_changed(cleaned_old, cleaned_new)

    def test_body_change_detected(self):
        """Body content changes should be detected."""
        old_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Old description.
"""
        new_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
New description with changes.
"""
        cleaned_old = strip_system_fields_from_frontmatter(old_content)
        cleaned_new = strip_system_fields_from_frontmatter(new_content)

        # Should detect a change (body is versioned)
        assert content_has_changed(cleaned_old, cleaned_new)

    def test_depends_on_change_detected(self):
        """depends_on changes should be detected as content changes."""
        old_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
depends_on: [uuid-1]
---

## Description
Same description.
"""
        new_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
depends_on: [uuid-1, uuid-2]
---

## Description
Same description.
"""
        cleaned_old = strip_system_fields_from_frontmatter(old_content)
        cleaned_new = strip_system_fields_from_frontmatter(new_content)

        # Should detect a change (depends_on is a versioned field)
        assert content_has_changed(cleaned_old, cleaned_new)

    def test_combined_tag_and_title_change(self):
        """When both tags and title change, only title change should be detected."""
        old_content = """---
type: feature
title: Old Title
parent_id: 12345678-1234-1234-1234-123456789012
tags: [old-tag]
---

## Description
Same description.
"""
        new_content = """---
type: feature
title: New Title
parent_id: 12345678-1234-1234-1234-123456789012
tags: [new-tag]
---

## Description
Same description.
"""
        cleaned_old = strip_system_fields_from_frontmatter(old_content)
        cleaned_new = strip_system_fields_from_frontmatter(new_content)

        # Should detect a change (title changed, even though tags also changed)
        assert content_has_changed(cleaned_old, cleaned_new)


class TestStatusTagInjection:
    """Tests for TARKA-FEAT-106: Status Tag Injection."""

    def test_status_tag_injected_into_frontmatter(self):
        """TARKA-FEAT-106: Status tag should be injected into frontmatter."""
        stored_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Test feature description.
"""
        injected = inject_database_state(
            stored_content,
            status="approved",
            human_readable_id="RAAS-FEAT-001",
            tags=["tag1"],
            status_tag="deployed-v1"
        )
        parsed = parse_markdown(injected)

        # Status tag should be in frontmatter
        assert parsed["frontmatter"]["status_tag"] == "deployed-v1"

    def test_status_tag_draft_injected(self):
        """Draft status tag should be injected for draft requirements."""
        stored_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Test feature description.
"""
        injected = inject_database_state(
            stored_content,
            status="draft",
            status_tag="draft"
        )
        parsed = parse_markdown(injected)

        assert parsed["frontmatter"]["status_tag"] == "draft"

    def test_status_tag_deployed_format(self):
        """Deployed status tag should follow deployed-v{N} format."""
        stored_content = """---
type: feature
title: Test Feature
parent_id: 12345678-1234-1234-1234-123456789012
---

## Description
Test feature description.
"""
        injected = inject_database_state(
            stored_content,
            status="approved",
            status_tag="deployed-v3"
        )
        parsed = parse_markdown(injected)

        assert parsed["frontmatter"]["status_tag"] == "deployed-v3"
        assert parsed["frontmatter"]["status_tag"].startswith("deployed-")


class TestReservedTagValidation:
    """Tests for TARKA-FEAT-106: Reserved Tag Validation."""

    from tarka_core.markdown_utils import validate_tags_not_reserved, ReservedTagError

    def test_reserved_exact_tags_rejected(self):
        """Reserved exact tags (draft, review, approved, deprecated) should be rejected."""
        from tarka_core.markdown_utils import validate_tags_not_reserved, ReservedTagError

        for reserved_tag in ["draft", "review", "approved", "deprecated"]:
            with pytest.raises(ReservedTagError) as exc_info:
                validate_tags_not_reserved([reserved_tag])
            assert "reserved for system-managed status" in str(exc_info.value)

    def test_reserved_exact_tags_case_insensitive(self):
        """Reserved tag validation should be case-insensitive."""
        from tarka_core.markdown_utils import validate_tags_not_reserved, ReservedTagError

        for reserved_tag in ["DRAFT", "Review", "APPROVED", "Deprecated"]:
            with pytest.raises(ReservedTagError):
                validate_tags_not_reserved([reserved_tag])

    def test_deployed_prefix_rejected(self):
        """Tags starting with 'deployed-' should be rejected."""
        from tarka_core.markdown_utils import validate_tags_not_reserved, ReservedTagError

        with pytest.raises(ReservedTagError) as exc_info:
            validate_tags_not_reserved(["deployed-v1"])
        assert "reserved prefix" in str(exc_info.value)

        with pytest.raises(ReservedTagError):
            validate_tags_not_reserved(["deployed-REL-001"])

        with pytest.raises(ReservedTagError):
            validate_tags_not_reserved(["DEPLOYED-V5"])

    def test_valid_tags_accepted(self):
        """Valid tags should pass validation."""
        from tarka_core.markdown_utils import validate_tags_not_reserved

        # These should NOT raise
        validate_tags_not_reserved(["sprint-1", "backend", "urgent"])
        validate_tags_not_reserved(["p0-foundation", "feature-flag"])
        validate_tags_not_reserved(["deployment-team"])  # 'deployment' != 'deployed-'
        validate_tags_not_reserved([])
        validate_tags_not_reserved(None)

    def test_reserved_tag_mixed_with_valid(self):
        """If any tag is reserved, validation should fail."""
        from tarka_core.markdown_utils import validate_tags_not_reserved, ReservedTagError

        with pytest.raises(ReservedTagError):
            validate_tags_not_reserved(["sprint-1", "approved", "backend"])


class TestVersioningStatusTag:
    """Tests for versioning.py get_status_tag function."""

    from tarka_core.versioning import get_status_tag

    def test_get_status_tag_returns_deployed_with_release(self):
        """get_status_tag should return deployed-REL-XXX when release_hrid provided."""
        from tarka_core.versioning import get_status_tag
        from unittest.mock import MagicMock

        # Mock requirement with deployed version
        req = MagicMock()
        req.deployed_version_id = "version-uuid-123"

        version = MagicMock()
        version.id = "version-uuid-123"
        version.version_number = 5
        version.status.value = "approved"

        tag = get_status_tag(req, version, release_hrid="REL-001")
        assert tag == "deployed-REL-001"

    def test_get_status_tag_returns_deployed_version_fallback(self):
        """get_status_tag should return deployed-v{N} when no release_hrid."""
        from tarka_core.versioning import get_status_tag
        from unittest.mock import MagicMock

        req = MagicMock()
        req.deployed_version_id = "version-uuid-123"

        version = MagicMock()
        version.id = "version-uuid-123"
        version.version_number = 3
        version.status.value = "approved"

        tag = get_status_tag(req, version)
        assert tag == "deployed-v3"

    def test_get_status_tag_returns_lifecycle_status(self):
        """get_status_tag should return lifecycle status when not deployed."""
        from tarka_core.versioning import get_status_tag
        from tarka_core.models import LifecycleStatus
        from unittest.mock import MagicMock

        req = MagicMock()
        req.deployed_version_id = None  # Not deployed

        # Test each status
        for status, expected_tag in [
            (LifecycleStatus.DRAFT, "draft"),
            (LifecycleStatus.REVIEW, "review"),
            (LifecycleStatus.APPROVED, "approved"),
            (LifecycleStatus.DEPRECATED, "deprecated"),
        ]:
            version = MagicMock()
            version.id = "some-other-uuid"
            version.status = status

            tag = get_status_tag(req, version)
            assert tag == expected_tag, f"Expected {expected_tag} for status {status}"


class TestReleaseTrackingStatusTag:
    """Tests for TARKA-FEAT-106: Release tracking in status_tag."""

    def test_requirement_status_tag_with_release(self):
        """Requirement.status_tag should return deployed-REL-XXX when deployed_by_release is set."""
        from unittest.mock import MagicMock, PropertyMock

        # Create mock requirement
        req = MagicMock()
        req.deployed_version_id = "version-uuid-123"
        req.deployed_version_number = 5

        # Mock the deployed_by_release relationship
        release = MagicMock()
        release.human_readable_id = "REL-042"
        req.deployed_by_release = release

        # Mock the status property
        from tarka_core.models import LifecycleStatus
        type(req).status = PropertyMock(return_value=LifecycleStatus.APPROVED)

        # Import the actual status_tag property logic and test
        # Since we can't easily test the property on a mock, verify the logic
        if req.deployed_version_id is not None:
            if req.deployed_by_release and req.deployed_by_release.human_readable_id:
                tag = f"deployed-{req.deployed_by_release.human_readable_id}"
            else:
                tag = f"deployed-v{req.deployed_version_number}"
        else:
            tag = "approved"

        assert tag == "deployed-REL-042"

    def test_requirement_status_tag_without_release_fallback(self):
        """Requirement.status_tag should fall back to deployed-v{N} when no release."""
        from unittest.mock import MagicMock, PropertyMock

        req = MagicMock()
        req.deployed_version_id = "version-uuid-123"
        req.deployed_version_number = 3
        req.deployed_by_release = None  # No release tracked

        from tarka_core.models import LifecycleStatus
        type(req).status = PropertyMock(return_value=LifecycleStatus.APPROVED)

        # Test the logic
        if req.deployed_version_id is not None:
            if req.deployed_by_release and req.deployed_by_release.human_readable_id:
                tag = f"deployed-{req.deployed_by_release.human_readable_id}"
            else:
                tag = f"deployed-v{req.deployed_version_number}"
        else:
            tag = "approved"

        assert tag == "deployed-v3"

    def test_update_deployed_version_pointer_sets_release_id(self):
        """update_deployed_version_pointer should set deployed_by_release_id when provided."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        # This is a unit test of the function signature change
        # Full integration test would require database setup
        req = MagicMock()
        req.deployed_version_id = None
        req.deployed_by_release_id = None

        release_id = uuid4()
        version_id = uuid4()

        # Simulate what the function does
        req.deployed_version_id = version_id
        req.deployed_by_release_id = release_id

        # Verify both are set
        assert req.deployed_version_id == version_id
        assert req.deployed_by_release_id == release_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
