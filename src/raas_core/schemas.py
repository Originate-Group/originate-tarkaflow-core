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
    TaskType,
    TaskStatus,
    TaskPriority,
    TaskChangeType,
    ExecutionStatus,  # CR-009: Agent task execution tracking
    WorkItemType,     # CR-010: Work Item types
    WorkItemStatus,   # CR-010: Work Item lifecycle
    GitHubAuthType,   # CR-010: GitHub auth types
    Environment,      # RAAS-FEAT-103: Deployment environments
    DeploymentStatus, # RAAS-FEAT-103: Deployment status
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

    # Versioning fields (CR-006: Version Model Simplification)
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of current content for conflict detection")
    deployed_version_id: Optional[UUID] = Field(None, description="UUID of the version deployed to production")

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

    # Versioning fields (CR-006: Version Model Simplification)
    content_hash: Optional[str] = Field(None, description="SHA-256 hash of current content for conflict detection")
    deployed_version_id: Optional[UUID] = Field(None, description="UUID of the version deployed to production")
    deployed_version_number: Optional[int] = Field(None, description="Version number of the deployed version")
    has_pending_changes: bool = Field(False, description="True if newer versions exist beyond deployed version")

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    @model_validator(mode='after')
    def inject_database_state_into_content(self):
        """Inject current database state into content frontmatter.

        The stored content only contains authored fields (type, title, parent_id,
        depends_on, adheres_to). System-managed fields (status, human_readable_id,
        tags) are dynamically injected from database columns when returning to clients.

        BUG-004: Tags are now injected from database (not stored in content) to prevent
        tag changes from triggering versioning or status regression.

        This ensures clients always see the current authoritative state, not stale
        values from stored frontmatter.
        """
        if self.content:
            from .markdown_utils import inject_database_state
            try:
                self.content = inject_database_state(
                    self.content,
                    self.status.value if hasattr(self.status, 'value') else str(self.status),
                    self.human_readable_id,
                    self.tags,  # BUG-004: Inject tags from database
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
    """Schema for requirement history entries.

    CR-012 (BUG-002): Includes director_id and actor_id for accountability:
    - director_id: Human user who authorized the change
    - actor_id: Agent account that executed the change (if applicable)
    """

    id: UUID
    requirement_id: UUID
    change_type: ChangeType
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: Optional[str] = None
    changed_at: datetime
    change_reason: Optional[str] = None
    # CR-012 (BUG-002): Director/Actor accountability fields
    director_id: Optional[UUID] = None
    actor_id: Optional[UUID] = None

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
    slug: str = Field(..., min_length=3, max_length=10, pattern=r"^[A-Z0-9]{3,10}$")
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
    user_type: str = "human"  # CR-009: human or agent
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
# Agent Director Schemas (CR-012)
# ============================================================================

class AgentDirectorCreate(BaseModel):
    """Schema for creating an agent-director mapping."""

    agent_id: UUID = Field(..., description="UUID of the agent account")
    director_id: UUID = Field(..., description="UUID of the human user authorized to direct this agent")
    organization_id: UUID = Field(..., description="Organization UUID")
    # CR-005/TARKA-FEAT-105: Client constraints
    allowed_user_agents: Optional[List[str]] = Field(
        None,
        description="User-agent patterns that can use this mapping (e.g., ['claude-desktop/*']). "
                    "Null/empty = unrestricted."
    )


class AgentDirectorResponse(BaseModel):
    """Schema for agent-director mapping response."""

    id: UUID
    agent_id: UUID
    agent_email: str
    agent_name: Optional[str] = None
    director_id: UUID
    director_email: str
    director_name: Optional[str] = None
    organization_id: UUID
    created_at: datetime
    created_by_email: Optional[str] = None
    # CR-005/TARKA-FEAT-105: Client constraints
    allowed_user_agents: Optional[List[str]] = Field(
        None,
        description="User-agent patterns that can use this mapping. Null/empty = unrestricted."
    )

    model_config = ConfigDict(from_attributes=True)


class AgentResponse(BaseModel):
    """Schema for agent account response (with authorization info)."""

    id: UUID
    email: str
    full_name: Optional[str] = None
    is_authorized: bool = Field(description="Whether current user is authorized to direct this agent")
    authorization_type: Optional[str] = Field(None, description="'explicit' (mapping exists) or 'owner' (org owner implicit)")
    # CR-005/TARKA-FEAT-105: Client constraints
    allowed_user_agents: Optional[List[str]] = Field(
        None,
        description="User-agent patterns that can use this agent. Null/empty = unrestricted."
    )

    model_config = ConfigDict(from_attributes=True)


class MyAgentsResponse(BaseModel):
    """Schema for list of agents the current user can direct."""

    agents: list[AgentResponse]
    organization_id: UUID
    director_id: UUID
    director_email: str


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

    For clarification tasks (task_type='clarification'), use the clarification-specific
    fields: artifact_type, artifact_id, and context. These replace the separate
    clarification_points entity (CR-003).
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
    source_type: Optional[str] = Field(None, description="Source system type (elicitation_session, clarification_point, requirement, guardrail, etc.)")
    source_id: Optional[str] = Field(None, description="Source artifact UUID or human-readable ID (e.g., ELIC-002, CLAR-001, RAAS-FEAT-042)")
    source_context: Optional[dict] = Field(None, description="Additional context from source")
    # Clarification task fields (CR-003: used when task_type='clarification')
    context: Optional[str] = Field(None, description="Why this clarification is needed (for clarification tasks)")
    artifact_type: Optional[str] = Field(None, description="Type of artifact needing clarification: requirement, guardrail (for clarification tasks)")
    artifact_id: Optional[UUID] = Field(None, description="UUID of artifact needing clarification (for clarification tasks)")


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


class ClarificationTaskResolve(BaseModel):
    """Schema for resolving a clarification task (CR-003).

    Used to mark a clarification task as resolved with an answer.
    This replaces the separate resolve_clarification_point operation.
    """

    resolution_content: str = Field(..., min_length=1, description="The answer/resolution to the clarification")


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
    # Clarification task fields (CR-003)
    context: Optional[str] = None
    artifact_type: Optional[str] = None
    artifact_id: Optional[UUID] = None
    resolution_content: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[UUID] = None
    # Execution tracking fields (CR-009: Agent Service Accounts)
    execution_status: Optional[ExecutionStatus] = None
    execution_output: Optional[dict] = None
    execution_started_at: Optional[datetime] = None
    execution_completed_at: Optional[datetime] = None
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
    # Clarification task fields (CR-003) - for display in list view
    artifact_type: Optional[str] = None
    artifact_id: Optional[UUID] = None
    # Execution tracking (CR-009) - for visibility in list view
    execution_status: Optional[ExecutionStatus] = None
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


# NOTE: ClarificationPoint schemas removed by CR-004
# Clarifications are now handled as tasks with task_type='clarification'
# Use TaskCreate with task_type='clarification' instead


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
    target_artifact_id: Optional[str] = None  # UUID or human-readable ID, NULL if creating new
    assignee_id: Optional[UUID] = None
    clarification_task_id: Optional[str] = None  # UUID or human-readable ID (e.g., TASK-001) - CR-004: uses tasks
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
    """Schema for elicitation session response.

    Includes enriched context for session resumption (RAAS-FEAT-090):
    - Target artifact human-readable ID for context restoration
    - Assignee details (email, name) for display
    - Clarification task human-readable ID for linking (CR-004: uses tasks)
    """

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    target_artifact_type: str
    target_artifact_id: Optional[UUID] = None
    target_artifact_human_readable_id: Optional[str] = None  # e.g., RAAS-FEAT-042
    assignee_id: Optional[UUID] = None
    assignee_email: Optional[str] = None  # For display/context
    assignee_name: Optional[str] = None   # For display/context
    status: str
    conversation_history: List[dict]
    partial_draft: Optional[dict] = None
    identified_gaps: List[dict]
    progress: dict
    clarification_task_id: Optional[UUID] = None  # CR-004: uses tasks instead of clarification_points
    clarification_task_human_readable_id: Optional[str] = None  # e.g., TASK-001
    started_at: datetime
    last_activity_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_by: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class ElicitationSessionListItem(BaseModel):
    """Schema for elicitation session list item (lightweight).

    Includes enriched context fields (RAAS-FEAT-090) for quick scanning.
    CR-004: Uses clarification_task_id instead of clarification_point_id.
    """

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    target_artifact_type: str
    target_artifact_id: Optional[UUID] = None
    target_artifact_human_readable_id: Optional[str] = None  # e.g., RAAS-FEAT-042
    assignee_id: Optional[UUID] = None
    assignee_email: Optional[str] = None
    assignee_name: Optional[str] = None
    status: str
    clarification_task_id: Optional[UUID] = None  # CR-004: uses tasks
    clarification_task_human_readable_id: Optional[str] = None  # e.g., TASK-001
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
    child_analyses: Optional[List["GapAnalysisResponse"]] = None


# Enable self-referential model
GapAnalysisResponse.model_rebuild()


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


# =============================================================================
# CR-010: Work Items (RAAS-COMP-075)
# =============================================================================


class WorkItemCreate(BaseModel):
    """Schema for creating a new Work Item.

    Work Items track implementation work and link to affected requirements.
    Types: IR (Implementation Request), CR (Change Request), BUG, TASK
    """

    organization_id: UUID = Field(..., description="Organization UUID")
    project_id: Optional[UUID] = Field(None, description="Project UUID (optional)")
    work_item_type: WorkItemType = Field(..., description="Type: ir, cr, bug, task")
    title: str = Field(..., min_length=1, max_length=200, description="Work item title")
    description: Optional[str] = Field(None, description="Detailed description")
    priority: str = Field("medium", description="Priority: low, medium, high, critical")
    assigned_to: Optional[UUID] = Field(None, description="Assignee user UUID")
    tags: list[str] = Field(default_factory=list, description="Tags for bidirectional linking")

    # Affected requirements (RAAS-FEAT-098)
    affects: list[str] = Field(
        default_factory=list,
        description="List of requirement UUIDs or human-readable IDs this work item affects"
    )

    # RAAS-FEAT-099: Target specific requirement versions (immutable)
    # If provided, these versions are targeted; if not, current versions are auto-captured from affects
    target_version_ids: Optional[list[str]] = Field(
        None,
        description="List of RequirementVersion UUIDs to target (optional, auto-captured from affects if not provided)"
    )

    # CR-specific: proposed content (RAAS-FEAT-099)
    proposed_content: Optional[dict] = Field(
        None,
        description="For CRs: {requirement_id: 'new markdown content'}"
    )

    # Release-specific fields (RAAS-FEAT-102)
    release_tag: Optional[str] = Field(
        None,
        max_length=50,
        description="For Releases: Git tag or version (e.g., 'v1.2.0')"
    )
    github_release_url: Optional[str] = Field(
        None,
        max_length=500,
        description="For Releases: GitHub release URL"
    )
    includes: list[str] = Field(
        default_factory=list,
        description="For Releases: List of Work Item UUIDs or human-readable IDs to include in release"
    )


class WorkItemUpdate(BaseModel):
    """Schema for updating a Work Item."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[WorkItemStatus] = None
    priority: Optional[str] = None
    assigned_to: Optional[UUID] = None
    tags: Optional[list[str]] = None

    # Update affected requirements
    affects: Optional[list[str]] = Field(
        None,
        description="List of requirement UUIDs or human-readable IDs (replaces existing)"
    )

    # RAAS-FEAT-099: Update target versions (only allowed when status is 'created')
    target_version_ids: Optional[list[str]] = Field(
        None,
        description="List of RequirementVersion UUIDs to target (only modifiable before work starts)"
    )

    # CR-specific updates
    proposed_content: Optional[dict] = None
    implementation_refs: Optional[dict] = None

    # Release-specific updates (RAAS-FEAT-102)
    release_tag: Optional[str] = Field(None, max_length=50)
    github_release_url: Optional[str] = Field(None, max_length=500)
    includes: Optional[list[str]] = Field(
        None,
        description="For Releases: List of Work Item UUIDs or human-readable IDs (replaces existing)"
    )


class WorkItemTransition(BaseModel):
    """Schema for transitioning a Work Item status."""

    new_status: WorkItemStatus = Field(..., description="Target status")


class WorkItemResponse(BaseModel):
    """Schema for full Work Item response."""

    id: UUID
    human_readable_id: Optional[str] = None  # e.g., CR-010, IR-003
    organization_id: UUID
    project_id: Optional[UUID] = None
    work_item_type: WorkItemType
    title: str
    description: Optional[str] = None
    status: WorkItemStatus
    priority: str
    assigned_to: Optional[UUID] = None
    assignee_email: Optional[str] = None
    assignee_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    # Affected requirements
    affects_count: int = Field(description="Number of affected requirements")
    affected_requirement_ids: list[UUID] = Field(default_factory=list)

    # RAAS-FEAT-099: Target versions (immutable snapshots this work item implements)
    target_versions: list["TargetVersionSummary"] = Field(default_factory=list)

    # CR-specific
    proposed_content: Optional[dict] = None
    baseline_hashes: Optional[dict] = None

    # Implementation references
    implementation_refs: Optional[dict] = None

    # Release-specific (RAAS-FEAT-102)
    release_tag: Optional[str] = None
    github_release_url: Optional[str] = None
    included_work_item_ids: list[UUID] = Field(default_factory=list)
    includes_count: int = Field(default=0, description="Number of Work Items included in release")

    # Audit
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    created_by_email: Optional[str] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class WorkItemListItem(BaseModel):
    """Schema for Work Item list items (lightweight)."""

    id: UUID
    human_readable_id: Optional[str] = None
    organization_id: UUID
    project_id: Optional[UUID] = None
    work_item_type: WorkItemType
    title: str
    status: WorkItemStatus
    priority: str
    assigned_to: Optional[UUID] = None
    assignee_email: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    affects_count: int = Field(description="Number of affected requirements")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class WorkItemListResponse(BaseModel):
    """Schema for paginated Work Item list."""

    items: list[WorkItemListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class WorkItemHistoryResponse(BaseModel):
    """Schema for Work Item history entries."""

    id: UUID
    work_item_id: UUID
    change_type: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: Optional[UUID] = None
    changed_by_email: Optional[str] = None
    changed_at: datetime
    change_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# CR-010: Requirement Versioning (RAAS-FEAT-097)
# =============================================================================


class RequirementVersionResponse(BaseModel):
    """Schema for Requirement Version response.

    CR-006: Versions now have their own status (draft/review/approved/deprecated).
    """

    id: UUID
    requirement_id: UUID
    version_number: int
    status: LifecycleStatus = Field(description="Version status (CR-006)")
    content: str
    content_hash: str
    title: str
    description: Optional[str] = None
    source_work_item_id: Optional[UUID] = None
    source_work_item_hrid: Optional[str] = None  # e.g., CR-010
    change_reason: Optional[str] = None
    created_at: datetime
    created_by: Optional[UUID] = None
    created_by_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class RequirementVersionListItem(BaseModel):
    """Schema for Requirement Version list items (lightweight, no content).

    CR-006: Versions now have their own status.
    """

    id: UUID
    requirement_id: UUID
    version_number: int
    status: LifecycleStatus = Field(description="Version status (CR-006)")
    content_hash: str
    title: str
    source_work_item_id: Optional[UUID] = None
    source_work_item_hrid: Optional[str] = None
    created_at: datetime
    created_by_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class RequirementVersionListResponse(BaseModel):
    """Schema for paginated Requirement Version list.

    CR-006: Removed current_version_number, added deployed_version_number.
    """

    items: list[RequirementVersionListItem]
    total: int
    requirement_id: UUID
    deployed_version_number: Optional[int] = None


# =============================================================================
# RAAS-FEAT-099: Version Targeting & Drift Detection
# =============================================================================


class TargetVersionSummary(BaseModel):
    """Schema for target version summary in Work Item responses.

    Lightweight representation of a targeted RequirementVersion.
    """

    id: UUID
    requirement_id: UUID
    requirement_human_readable_id: Optional[str] = None
    version_number: int
    title: str

    model_config = ConfigDict(from_attributes=True)


class DriftWarning(BaseModel):
    """Schema for a single drift warning.

    Indicates a requirement has newer versions than the targeted version.
    CR-006: Renamed current_version to latest_version for clarity.
    """

    requirement_id: UUID
    requirement_human_readable_id: Optional[str] = None
    target_version: int = Field(description="Version number targeted by the work item")
    latest_version: int = Field(description="Latest version number of the requirement")
    versions_behind: int = Field(description="Number of versions behind latest")


class DriftCheckResponse(BaseModel):
    """Schema for drift check response.

    Returns semantic version drift information for a work item.
    """

    work_item_id: str
    work_item_human_readable_id: Optional[str] = None
    has_drift: bool = Field(description="True if any targeted requirements have newer versions")
    drift_warnings: list[DriftWarning] = Field(default_factory=list)


class RequirementVersionDiff(BaseModel):
    """Schema for diff between two requirement versions."""

    requirement_id: UUID
    from_version: int
    to_version: int
    from_content: str
    to_content: str
    from_title: str
    to_title: str
    changes_summary: str  # Human-readable summary of changes


# CR-002 (RAAS-FEAT-104): Work Item Diff and Conflict Detection Schemas
class RequirementDiffItem(BaseModel):
    """Single requirement diff within a Work Item.

    CR-006: Renamed current_version_number -> deployed_version_number.
    The deployed version is the meaningful reference point for diffs.
    """

    requirement_id: UUID
    human_readable_id: Optional[str] = None
    title: str
    deployed_version_number: Optional[int] = None  # version in production
    latest_version_number: Optional[int] = None  # most recent version
    deployed_content: Optional[str] = None  # content at deployed_version
    proposed_content: Optional[str] = None  # proposed content in Work Item (for CRs)
    latest_content: Optional[str] = None  # content at latest version
    has_changes: bool = False
    changes_summary: str = ""


class WorkItemDiffsResponse(BaseModel):
    """Response for Work Item diffs endpoint (CR-002: RAAS-FEAT-104).

    Shows diffs for all affected requirements in a single call.
    """

    work_item_id: UUID
    human_readable_id: Optional[str] = None
    work_item_type: str
    affected_requirements: list[RequirementDiffItem]
    total_affected: int
    total_with_changes: int


class ConflictItem(BaseModel):
    """Conflict status for a single requirement."""

    requirement_id: UUID
    human_readable_id: Optional[str] = None
    title: str
    baseline_hash: Optional[str] = None  # hash when Work Item created
    current_hash: Optional[str] = None  # current hash
    has_conflict: bool = False
    conflict_reason: Optional[str] = None


class ConflictCheckResponse(BaseModel):
    """Response for conflict check endpoint (CR-002: RAAS-FEAT-104).

    Proactive conflict detection before approval/merge.
    """

    work_item_id: UUID
    human_readable_id: Optional[str] = None
    has_conflicts: bool = False
    conflict_count: int = 0
    affected_requirements: list[ConflictItem]


# =============================================================================
# CR-010: GitHub Integration (RAAS-COMP-051)
# =============================================================================


class GitHubConfigurationCreate(BaseModel):
    """Schema for creating a GitHub configuration.

    Connects a RaaS project to a GitHub repository for Work Item sync.
    """

    project_id: UUID = Field(..., description="Project UUID to configure")
    repository_owner: str = Field(..., min_length=1, max_length=100, description="GitHub repo owner (user or org)")
    repository_name: str = Field(..., min_length=1, max_length=100, description="GitHub repo name")
    auth_type: GitHubAuthType = Field(GitHubAuthType.PAT, description="Authentication type")
    credentials: str = Field(..., min_length=1, description="PAT token or GitHub App credentials (will be encrypted)")
    label_mapping: Optional[dict] = Field(None, description="Custom label mapping for Work Item types")
    auto_create_issues: bool = Field(True, description="Auto-create GitHub Issues for Work Items")
    sync_pr_status: bool = Field(True, description="Sync PR status to Work Items")
    sync_releases: bool = Field(True, description="Trigger deployment on releases")


class GitHubConfigurationUpdate(BaseModel):
    """Schema for updating a GitHub configuration."""

    repository_owner: Optional[str] = Field(None, min_length=1, max_length=100)
    repository_name: Optional[str] = Field(None, min_length=1, max_length=100)
    credentials: Optional[str] = Field(None, description="New credentials (will be encrypted)")
    label_mapping: Optional[dict] = None
    auto_create_issues: Optional[bool] = None
    sync_pr_status: Optional[bool] = None
    sync_releases: Optional[bool] = None
    is_active: Optional[bool] = None


class GitHubConfigurationResponse(BaseModel):
    """Schema for GitHub configuration response.

    Note: Credentials are never returned - only a masked indicator.
    """

    id: UUID
    project_id: UUID
    repository_owner: str
    repository_name: str
    full_repo_name: str  # owner/name
    auth_type: GitHubAuthType
    has_credentials: bool = Field(description="True if credentials are configured")
    webhook_configured: bool = Field(description="True if webhook is set up")
    label_mapping: dict
    auto_create_issues: bool
    sync_pr_status: bool
    sync_releases: bool
    is_active: bool
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GitHubWebhookPayload(BaseModel):
    """Schema for incoming GitHub webhook payload.

    This is a simplified schema - GitHub sends much more data.
    We extract what we need.
    """

    action: Optional[str] = None  # opened, closed, reopened, etc.
    issue: Optional[dict] = None
    pull_request: Optional[dict] = None
    release: Optional[dict] = None
    repository: Optional[dict] = None
    sender: Optional[dict] = None


class GitHubIssueSyncRequest(BaseModel):
    """Schema for manually syncing a Work Item to GitHub Issue."""

    work_item_id: str = Field(..., description="Work Item UUID or human-readable ID")


class GitHubIssueSyncResponse(BaseModel):
    """Schema for GitHub Issue sync response."""

    work_item_id: UUID
    work_item_hrid: str
    github_issue_url: str
    github_issue_number: int
    action: str  # created, updated, linked


# =============================================================================
# RAAS-FEAT-103: Multi-Environment Deployment Tracking
# =============================================================================


class DeploymentCreate(BaseModel):
    """Schema for creating a deployment record."""

    release_id: UUID = Field(..., description="Release Work Item UUID")
    environment: Environment = Field(..., description="Target environment")
    artifact_ref: Optional[dict] = Field(
        None,
        description="Artifact references: {docker_tag, git_sha, image_digest}"
    )


class DeploymentUpdate(BaseModel):
    """Schema for updating a deployment status."""

    status: Optional[DeploymentStatus] = None
    artifact_ref: Optional[dict] = None


class DeploymentTransition(BaseModel):
    """Schema for transitioning deployment status."""

    new_status: DeploymentStatus = Field(..., description="Target status")


class DeploymentResponse(BaseModel):
    """Schema for deployment response."""

    id: UUID
    release_id: UUID
    release_hrid: Optional[str] = None  # e.g., REL-001
    environment: Environment
    status: DeploymentStatus
    artifact_ref: Optional[dict] = None
    created_at: datetime
    deployed_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None
    deployed_by_user_id: Optional[UUID] = None
    deployed_by_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class DeploymentListItem(BaseModel):
    """Schema for deployment list items (lightweight)."""

    id: UUID
    release_id: UUID
    release_hrid: Optional[str] = None
    release_tag: Optional[str] = None
    environment: Environment
    status: DeploymentStatus
    created_at: datetime
    deployed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class DeploymentListResponse(BaseModel):
    """Schema for paginated deployment list."""

    items: list[DeploymentListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class ReleaseDeploymentsResponse(BaseModel):
    """Schema for all deployments of a single Release."""

    release_id: UUID
    release_hrid: Optional[str] = None
    release_tag: Optional[str] = None
    deployments: dict[str, Optional[DeploymentResponse]] = Field(
        default_factory=dict,
        description="Deployment by environment: {dev: ..., staging: ..., prod: ...}"
    )
