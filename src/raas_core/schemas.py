"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, model_validator

from .models import (
    RequirementType,
    LifecycleStatus,
    ChangeType,
    ProjectVisibility,
    ProjectStatus,
    ProjectRole,
    MemberRole,
    QualityScore,
    GuardrailCategory,
    GuardrailStatus,
    EnforcementLevel,
)


# Requirement Schemas

class RequirementBase(BaseModel):
    """Base schema for requirement fields."""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)  # Read-only, auto-extracted from content
    content: Optional[str] = None  # Full markdown content
    status: LifecycleStatus = LifecycleStatus.DRAFT
    tags: list[str] = Field(default_factory=list)
    depends_on: list[UUID] = Field(default_factory=list, description="List of requirement IDs this depends on")
    adheres_to: list[str] = Field(default_factory=list, description="List of guardrail identifiers (UUID or human-readable) this requirement adheres to")


class RequirementCreate(BaseModel):
    """Schema for creating a new requirement.

    IMPORTANT: The 'content' field is REQUIRED and must contain properly formatted
    markdown with YAML frontmatter. Use the get_requirement_template endpoint to
    obtain the correct template format.

    Note: title and description are READ-ONLY fields extracted from content.
    Do not provide them separately - they will be ignored.
    """

    type: RequirementType
    content: str = Field(..., min_length=1, description="Required markdown content with YAML frontmatter")
    project_id: Optional[UUID] = Field(None, description="Project ID (required for epics, inherited from parent for other types)")
    # Legacy fields - DEPRECATED and ignored
    parent_id: Optional[UUID] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    status: LifecycleStatus = LifecycleStatus.DRAFT
    tags: list[str] = Field(default_factory=list)


class RequirementUpdate(BaseModel):
    """Schema for updating an existing requirement.

    Note: title and description are READ-ONLY fields extracted from content.
    To update them, provide updated markdown content - do not update them directly.
    """

    content: Optional[str] = None  # Full markdown content (updates title/description when parsed)
    status: Optional[LifecycleStatus] = None
    tags: Optional[list[str]] = None
    depends_on: Optional[list[UUID]] = None  # Update dependencies
    adheres_to: Optional[list[str]] = None  # Update guardrail references
    # Legacy fields - DEPRECATED and ignored
    title: Optional[str] = Field(None, min_length=1, max_length=200)


class RequirementListItem(BaseModel):
    """Schema for requirement list items (lightweight, no content field)."""

    id: UUID
    human_readable_id: Optional[str] = None  # e.g., RAAS-FEAT-042
    type: RequirementType
    parent_id: Optional[UUID] = None
    project_id: UUID
    title: str
    description: Optional[str] = None
    status: LifecycleStatus
    tags: list[str] = Field(default_factory=list)
    depends_on: list[UUID] = Field(default_factory=list, description="List of requirement IDs this depends on")
    adheres_to: list[str] = Field(default_factory=list, description="List of guardrail identifiers this requirement adheres to")
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    # Quality tracking fields
    content_length: int = Field(description="Length of full markdown content in characters")
    quality_score: QualityScore = Field(description="Quality score based on content length")
    child_count: int = Field(description="Number of direct children")

    model_config = ConfigDict(from_attributes=True)


class RequirementResponse(RequirementBase):
    """Schema for full requirement responses (includes content)."""

    id: UUID
    human_readable_id: Optional[str] = None  # e.g., RAAS-FEAT-042
    type: RequirementType
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    # Quality tracking fields
    content_length: int = Field(description="Length of full markdown content in characters")
    quality_score: QualityScore = Field(description="Quality score based on content length")
    child_count: int = Field(description="Number of direct children")

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='after')
    def inject_database_state_into_content(self):
        """Inject current database state into content frontmatter.

        The stored content only contains authored fields (type, title, parent_id, tags,
        depends_on, adheres_to). System-managed fields (status, human_readable_id, etc.)
        are dynamically injected from database columns when returning to clients.

        This ensures clients always see the current authoritative state, not stale
        values from stored frontmatter.
        """
        if self.content:
            from .markdown_utils import inject_database_state
            try:
                self.content = inject_database_state(
                    self.content,
                    self.status.value if hasattr(self.status, 'value') else str(self.status),
                    self.human_readable_id
                )
            except Exception:
                # If injection fails, return content as-is
                # (This can happen with old/malformed content)
                pass
        return self


class RequirementWithChildren(RequirementResponse):
    """Schema for requirement with its children."""

    children: list['RequirementResponse'] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# History Schemas

class RequirementHistoryResponse(BaseModel):
    """Schema for requirement history entries."""

    id: UUID
    requirement_id: UUID
    change_type: ChangeType
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: Optional[str] = None
    changed_at: datetime
    change_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# List Response Schemas

class RequirementListResponse(BaseModel):
    """Schema for paginated requirement list (uses lightweight RequirementListItem)."""

    items: list[RequirementListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# Filter Schemas

class RequirementFilter(BaseModel):
    """Schema for filtering requirements."""

    type: Optional[RequirementType] = None
    status: Optional[LifecycleStatus] = None
    parent_id: Optional[UUID] = None
    search: Optional[str] = None
    tags: Optional[list[str]] = None


# ============================================================================
# Organization Schemas
# ============================================================================

class OrganizationBase(BaseModel):
    """Base schema for organization fields."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    settings: dict = Field(default_factory=dict)


class OrganizationCreate(OrganizationBase):
    """Schema for creating a new organization."""

    pass


class OrganizationUpdate(BaseModel):
    """Schema for updating an organization."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    settings: Optional[dict] = None


class OrganizationResponse(OrganizationBase):
    """Schema for organization responses."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationListResponse(BaseModel):
    """Schema for paginated organization list."""

    items: list[OrganizationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# Organization Member Schemas
# ============================================================================

class OrganizationMemberBase(BaseModel):
    """Base schema for organization member fields."""

    organization_id: UUID
    user_id: UUID
    role: MemberRole = MemberRole.MEMBER


class OrganizationMemberCreate(OrganizationMemberBase):
    """Schema for adding a user to an organization."""

    pass


class OrganizationMemberUpdate(BaseModel):
    """Schema for updating an organization member's role."""

    role: MemberRole


class OrganizationMemberResponse(OrganizationMemberBase):
    """Schema for organization member responses."""

    id: UUID
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Project Schemas
# ============================================================================

class ProjectBase(BaseModel):
    """Base schema for project fields."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=3, max_length=4, pattern=r"^[A-Z0-9]{3,4}$")
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC
    status: ProjectStatus = ProjectStatus.ACTIVE
    value_statement: Optional[str] = None
    project_type: Optional[str] = Field(None, max_length=100)
    tags: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""

    organization_id: UUID


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: Optional[ProjectVisibility] = None
    status: Optional[ProjectStatus] = None
    value_statement: Optional[str] = None
    project_type: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None
    settings: Optional[dict] = None
    organization_id: Optional[UUID] = None


class ProjectResponse(ProjectBase):
    """Schema for project responses."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by_user_id: Optional[UUID] = None
    updated_by_user_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)


class ProjectListResponse(BaseModel):
    """Schema for paginated project list."""

    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# Project Member Schemas
# ============================================================================

class ProjectMemberBase(BaseModel):
    """Base schema for project member fields."""

    project_id: UUID
    user_id: UUID
    role: ProjectRole = ProjectRole.EDITOR


class ProjectMemberCreate(ProjectMemberBase):
    """Schema for adding a user to a project."""

    pass


class ProjectMemberUpdate(BaseModel):
    """Schema for updating a project member's role."""

    role: ProjectRole


class ProjectMemberResponse(ProjectMemberBase):
    """Schema for project member responses."""

    id: UUID
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# User Schemas
# ============================================================================

class UserResponse(BaseModel):
    """Schema for user responses."""

    id: UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserListResponse(BaseModel):
    """Schema for paginated user list."""

    items: list[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# Guardrail Schemas
# ============================================================================

class GuardrailCreate(BaseModel):
    """Schema for creating a new guardrail.

    IMPORTANT: The 'content' field is REQUIRED and must contain properly formatted
    markdown with YAML frontmatter. Use the get_guardrail_template endpoint to
    obtain the correct template format.
    """

    organization_id: UUID = Field(..., description="Organization UUID")
    content: str = Field(..., min_length=1, description="Required markdown content with YAML frontmatter")


class GuardrailResponse(BaseModel):
    """Schema for guardrail responses."""

    id: UUID
    human_readable_id: Optional[str] = None  # e.g., GUARD-SEC-001
    organization_id: UUID
    title: str
    category: GuardrailCategory
    enforcement_level: EnforcementLevel
    applies_to: list[str] = Field(description="Requirement types this guardrail applies to")
    status: GuardrailStatus
    content: str = Field(description="Full markdown content with frontmatter")
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class GuardrailTemplateResponse(BaseModel):
    """Schema for guardrail template response."""

    template: str = Field(description="Complete markdown template with YAML frontmatter and guidance")


class GuardrailUpdate(BaseModel):
    """Schema for updating a guardrail."""

    content: str = Field(..., min_length=1, description="Updated markdown content with YAML frontmatter")


class GuardrailListItem(BaseModel):
    """Schema for guardrail list items (lightweight, excludes full content)."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    title: str
    category: GuardrailCategory
    enforcement_level: EnforcementLevel
    applies_to: list[str] = Field(description="Requirement types this guardrail applies to")
    status: GuardrailStatus
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GuardrailListResponse(BaseModel):
    """Schema for paginated guardrail list."""

    items: list[GuardrailListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
