"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional, List
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
    ChangeRequestStatus,
    TaskType,
    TaskStatus,
    TaskPriority,
    TaskChangeType,
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

    IMPORTANT: For requirements in approved+ status, a change_request_id is required.
    Draft and review status requirements can be updated without a CR.
    """

    content: Optional[str] = None  # Full markdown content (updates title/description when parsed)
    status: Optional[LifecycleStatus] = None
    tags: Optional[list[str]] = None
    depends_on: Optional[list[UUID]] = None  # Update dependencies
    adheres_to: Optional[list[str]] = None  # Update guardrail references
    change_request_id: Optional[str] = Field(None, description="Change request UUID or human-readable ID (required for requirements past review status)")
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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    @model_validator(mode='after')
    def inject_database_state_into_content(self):
        """Inject current database state into content frontmatter.

        The stored content only contains authored fields (title, category,
        enforcement_level, applies_to). System-managed fields (status,
        human_readable_id, etc.) are dynamically injected from database
        columns when returning to clients.

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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class GuardrailListResponse(BaseModel):
    """Schema for paginated guardrail list."""

    items: list[GuardrailListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# Change Request Schemas (RAAS-COMP-068)
# ============================================================================

class ChangeRequestCreate(BaseModel):
    """Schema for creating a new change request.

    Change requests gate updates to requirements that have passed review status.
    The 'affects' list declares which requirements this CR intends to modify.
    """

    organization_id: UUID = Field(..., description="Organization UUID")
    justification: str = Field(..., min_length=10, description="Justification for the change (min 10 characters)")
    affects: list[UUID] = Field(..., min_length=1, description="List of requirement UUIDs this CR will modify")


class ChangeRequestTransition(BaseModel):
    """Schema for transitioning a change request status."""

    new_status: ChangeRequestStatus = Field(..., description="Target status (draft -> review -> approved -> completed)")


class ChangeRequestResponse(BaseModel):
    """Schema for change request responses."""

    id: UUID
    human_readable_id: Optional[str] = None  # e.g., CR-001
    organization_id: UUID
    justification: str
    status: ChangeRequestStatus

    # Requestor
    requestor_id: Optional[UUID] = None
    requestor_email: Optional[str] = None

    # Approval tracking
    approved_at: Optional[datetime] = None
    approved_by_id: Optional[UUID] = None
    approved_by_email: Optional[str] = None

    # Completion tracking
    completed_at: Optional[datetime] = None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Scope tracking
    affects: list[UUID] = Field(default_factory=list, description="Requirements in declared scope")
    affects_count: int = Field(description="Count of requirements in declared scope")
    modifications_count: int = Field(description="Count of requirements actually modified")

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ChangeRequestListItem(BaseModel):
    """Schema for change request list items (lightweight)."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    justification: str
    status: ChangeRequestStatus
    requestor_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    affects_count: int = Field(description="Count of requirements in declared scope")
    modifications_count: int = Field(description="Count of requirements actually modified")

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ChangeRequestListResponse(BaseModel):
    """Schema for paginated change request list."""

    items: list[ChangeRequestListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================================
# Task Queue Schemas (RAAS-EPIC-027, RAAS-COMP-065)
# ============================================================================


class TaskAssigneeResponse(BaseModel):
    """Schema for task assignee information."""

    user_id: UUID
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_primary: bool = True
    assigned_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class TaskCreate(BaseModel):
    """Schema for creating a new task.

    Tasks can be created directly by users or by task sources (clarification
    points, review requests, etc.). Source-created tasks should include
    source_type and source_id for bidirectional linking.
    """

    organization_id: UUID = Field(..., description="Organization UUID")
    project_id: Optional[UUID] = Field(None, description="Project UUID (optional for org-wide tasks)")
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, description="Task description")
    task_type: TaskType = Field(..., description="Task type (clarification, review, approval, gap_resolution, custom)")
    priority: TaskPriority = Field(TaskPriority.MEDIUM, description="Task priority")
    due_date: Optional[datetime] = Field(None, description="Due date (optional)")
    assignee_ids: list[UUID] = Field(default_factory=list, description="List of user UUIDs to assign")
    # Source artifact linking
    source_type: Optional[str] = Field(None, description="Source system type (requirement, guardrail, etc.)")
    source_id: Optional[UUID] = Field(None, description="Source artifact UUID")
    source_context: Optional[dict] = Field(None, description="Additional context from source")


class TaskUpdate(BaseModel):
    """Schema for updating an existing task."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None


class TaskAssign(BaseModel):
    """Schema for assigning users to a task."""

    assignee_ids: list[UUID] = Field(..., min_length=1, description="List of user UUIDs to assign")
    replace: bool = Field(False, description="If true, replaces all existing assignees; if false, adds to existing")


class TaskResponse(BaseModel):
    """Schema for full task response."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    due_date: Optional[datetime] = None
    # Source linking
    source_type: Optional[str] = None
    source_id: Optional[UUID] = None
    source_context: Optional[dict] = None
    # Assignees
    assignee_count: int = Field(description="Number of assignees")
    # Audit fields
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    completed_by: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class TaskListItem(BaseModel):
    """Schema for task list items (lightweight)."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    task_type: TaskType
    status: TaskStatus
    priority: TaskPriority
    due_date: Optional[datetime] = None
    source_type: Optional[str] = None
    assignee_count: int = Field(description="Number of assignees")
    is_overdue: bool = Field(description="True if due_date is in the past and status is not completed/cancelled")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class TaskListResponse(BaseModel):
    """Schema for paginated task list."""

    items: list[TaskListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskHistoryResponse(BaseModel):
    """Schema for task history entries."""

    id: UUID
    task_id: UUID
    change_type: TaskChangeType
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    comment: Optional[str] = None
    changed_by: Optional[UUID] = None
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# =============================================================================
# Task Routing Rule Schemas (RAAS-COMP-067)
# =============================================================================

class RoutingRuleCreate(BaseModel):
    """Schema for creating a task routing rule."""

    organization_id: UUID
    project_id: Optional[UUID] = None
    name: str = Field(..., max_length=200)
    description: Optional[str] = None

    # Rule matching
    scope: str = Field(default="organization", description="Rule scope: organization or project")
    match_type: str = Field(..., description="Match type: task_type, source_type, priority, requirement_type, tag")
    match_value: str = Field(..., max_length=100, description="Value to match against")

    # Assignment configuration
    assignee_user_id: Optional[UUID] = None
    assignee_role: Optional[str] = Field(None, max_length=50, description="Role for role-based assignment")
    fallback_user_id: Optional[UUID] = None

    # Rule priority (lower = evaluated first)
    priority: int = Field(default=100, ge=1, le=1000)

    is_active: bool = True


class RoutingRuleUpdate(BaseModel):
    """Schema for updating a task routing rule."""

    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    scope: Optional[str] = None
    match_type: Optional[str] = None
    match_value: Optional[str] = Field(None, max_length=100)
    assignee_user_id: Optional[UUID] = None
    assignee_role: Optional[str] = Field(None, max_length=50)
    fallback_user_id: Optional[UUID] = None
    priority: Optional[int] = Field(None, ge=1, le=1000)
    is_active: Optional[bool] = None


class RoutingRuleResponse(BaseModel):
    """Schema for routing rule response."""

    id: UUID
    organization_id: UUID
    project_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    scope: str
    match_type: str
    match_value: str
    assignee_user_id: Optional[UUID] = None
    assignee_role: Optional[str] = None
    fallback_user_id: Optional[UUID] = None
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class RoutingRuleListResponse(BaseModel):
    """Schema for paginated routing rules list."""

    items: list[RoutingRuleResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskDelegationCreate(BaseModel):
    """Schema for delegating a task."""

    task_id: UUID
    delegated_to: UUID
    reason: Optional[str] = None


class TaskDelegationResponse(BaseModel):
    """Schema for task delegation response."""

    id: UUID
    task_id: UUID
    delegated_by: Optional[UUID] = None
    delegated_to: Optional[UUID] = None
    original_assignee: Optional[UUID] = None
    reason: Optional[str] = None
    delegated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class TaskEscalationCreate(BaseModel):
    """Schema for escalating a task."""

    task_id: UUID
    escalated_to: UUID
    reason: str = Field(..., max_length=50)
    notes: Optional[str] = None


class TaskEscalationResponse(BaseModel):
    """Schema for task escalation response."""

    id: UUID
    task_id: UUID
    escalated_from: Optional[UUID] = None
    escalated_to: Optional[UUID] = None
    reason: str
    notes: Optional[str] = None
    escalated_at: datetime
    escalated_by_system: bool

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# =============================================================================
# RAAS-EPIC-026: AI-Driven Requirements Elicitation & Verification
# =============================================================================


class ClarificationPointCreate(BaseModel):
    """Schema for creating a clarification point."""

    organization_id: UUID
    project_id: Optional[UUID] = None
    artifact_type: str  # requirement, guardrail, etc.
    artifact_id: UUID
    title: str
    description: Optional[str] = None
    context: Optional[str] = None
    priority: str = "medium"  # blocking, high, medium, low
    assignee_id: Optional[UUID] = None
    due_date: Optional[datetime] = None


class ClarificationPointUpdate(BaseModel):
    """Schema for updating a clarification point."""

    title: Optional[str] = None
    description: Optional[str] = None
    context: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[UUID] = None
    due_date: Optional[datetime] = None


class ClarificationPointResolve(BaseModel):
    """Schema for resolving a clarification point."""

    resolution_content: str


class ClarificationPointResponse(BaseModel):
    """Schema for clarification point response."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    artifact_type: str
    artifact_id: UUID
    title: str
    description: Optional[str] = None
    context: Optional[str] = None
    priority: str
    status: str
    assignee_id: Optional[UUID] = None
    due_date: Optional[datetime] = None
    resolution_content: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ClarificationPointListResponse(BaseModel):
    """Schema for paginated clarification point list."""

    items: List[ClarificationPointResponse]
    total: int
    page: int
    page_size: int


class QuestionFrameworkCreate(BaseModel):
    """Schema for creating a question framework."""

    organization_id: UUID
    project_id: Optional[UUID] = None  # NULL = org-level default
    name: str
    description: Optional[str] = None
    framework_type: str  # epic, component, feature, requirement, guardrail
    content: dict = {}


class QuestionFrameworkUpdate(BaseModel):
    """Schema for updating a question framework."""

    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[dict] = None
    is_active: Optional[bool] = None


class QuestionFrameworkResponse(BaseModel):
    """Schema for question framework response."""

    id: UUID
    organization_id: UUID
    project_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    framework_type: str
    version: int
    is_active: bool
    content: dict
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class QuestionFrameworkListResponse(BaseModel):
    """Schema for paginated question framework list."""

    items: List[QuestionFrameworkResponse]
    total: int
    page: int
    page_size: int


class ElicitationSessionCreate(BaseModel):
    """Schema for creating an elicitation session."""

    organization_id: UUID
    project_id: Optional[UUID] = None
    target_artifact_type: str  # epic, component, feature, requirement, guardrail
    target_artifact_id: Optional[UUID] = None  # NULL if creating new
    assignee_id: Optional[UUID] = None
    clarification_point_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None


class ElicitationSessionUpdate(BaseModel):
    """Schema for updating an elicitation session."""

    status: Optional[str] = None
    conversation_history: Optional[List[dict]] = None
    partial_draft: Optional[dict] = None
    identified_gaps: Optional[List[dict]] = None
    progress: Optional[dict] = None
    expires_at: Optional[datetime] = None


class ElicitationSessionAddMessage(BaseModel):
    """Schema for adding a message to elicitation session."""

    role: str  # user, assistant, system
    content: str
    metadata: Optional[dict] = None


class ElicitationSessionResponse(BaseModel):
    """Schema for elicitation session response."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    target_artifact_type: str
    target_artifact_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None
    status: str
    conversation_history: List[dict]
    partial_draft: Optional[dict] = None
    identified_gaps: List[dict]
    progress: dict
    clarification_point_id: Optional[UUID] = None
    started_at: datetime
    last_activity_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_by: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ElicitationSessionListItem(BaseModel):
    """Schema for elicitation session list item (lightweight)."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    target_artifact_type: str
    target_artifact_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None
    status: str
    clarification_point_id: Optional[UUID] = None
    started_at: datetime
    last_activity_at: datetime
    message_count: int = 0
    gap_count: int = 0

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ElicitationSessionListResponse(BaseModel):
    """Schema for paginated elicitation session list."""

    items: List[ElicitationSessionListItem]
    total: int
    page: int
    page_size: int


# =============================================================================
# Gap Analyzer Schemas (RAAS-COMP-064)
# =============================================================================


class GapAnalysisRequest(BaseModel):
    """Schema for requesting gap analysis on a requirement."""

    requirement_id: str  # Accepts UUID or human-readable ID (e.g., CAAS-EPIC-006)
    include_children: bool = False


class GapFinding(BaseModel):
    """Schema for a single gap finding."""

    section: str  # Which section has the gap
    issue_type: str  # vague_language, missing_section, contradiction, incomplete
    severity: str  # critical, high, medium, low
    description: str
    suggestion: Optional[str] = None
    evidence: Optional[str] = None  # The specific text that triggered the finding


class GapAnalysisResponse(BaseModel):
    """Schema for gap analysis response."""

    requirement_id: UUID
    requirement_title: str
    completeness_score: float  # 0.0 to 1.0
    findings: List[GapFinding]
    sections_analyzed: List[str]
    analysis_timestamp: datetime


class BatchGapAnalysisRequest(BaseModel):
    """Schema for batch gap analysis of a project."""

    project_id: UUID
    requirement_types: Optional[List[str]] = None  # Filter by type
    statuses: Optional[List[str]] = None  # Filter by status


class BatchGapAnalysisResponse(BaseModel):
    """Schema for batch gap analysis response."""

    project_id: UUID
    total_requirements: int
    requirements_analyzed: int
    overall_completeness_score: float
    findings_by_severity: dict  # {critical: N, high: N, ...}
    requirements_with_issues: List[dict]  # [{id, title, score, critical_count}, ...]


class ContradictionFinding(BaseModel):
    """Schema for a contradiction between requirements."""

    requirement_a_id: UUID
    requirement_a_title: str
    requirement_b_id: UUID
    requirement_b_title: str
    contradiction_type: str  # direct, implicit, scope
    description: str
    evidence_a: str
    evidence_b: str
    severity: str


class ContradictionAnalysisResponse(BaseModel):
    """Schema for contradiction analysis response."""

    scope_id: UUID  # Project or epic ID
    scope_type: str  # project, epic
    contradictions: List[ContradictionFinding]
    analysis_timestamp: datetime


class QualityMetricsResponse(BaseModel):
    """Schema for quality metrics over time."""

    project_id: UUID
    time_period: str  # weekly, monthly
    metrics: List[dict]  # [{date, completeness_avg, gap_count, ...}, ...]
    trend: str  # improving, stable, declining
