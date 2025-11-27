"""SQLAlchemy database models."""
from datetime import datetime
from typing import Optional
from uuid import uuid4
import enum

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    Enum,
    CheckConstraint,
    ARRAY,
    Boolean,
    UniqueConstraint,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

# Base class for all models
Base = declarative_base()


# Association table for requirement dependencies (many-to-many)
requirement_dependencies = Table(
    'requirement_dependencies',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('requirement_id', UUID(as_uuid=True), ForeignKey('requirements.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('depends_on_id', UUID(as_uuid=True), ForeignKey('requirements.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, nullable=False, default=datetime.utcnow),
    UniqueConstraint('requirement_id', 'depends_on_id', name='unique_requirement_dependency'),
    CheckConstraint('requirement_id != depends_on_id', name='no_self_dependency'),
)


class RequirementType(str, enum.Enum):
    """Requirement type enum for hierarchy levels."""

    EPIC = "epic"
    COMPONENT = "component"
    FEATURE = "feature"
    REQUIREMENT = "requirement"


class LifecycleStatus(str, enum.Enum):
    """Lifecycle status enum."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    VALIDATED = "validated"
    DEPLOYED = "deployed"
    DEPRECATED = "deprecated"  # Terminal state for soft retirement (RAAS-FEAT-080)


class MemberRole(str, enum.Enum):
    """Organization member role enum."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectVisibility(str, enum.Enum):
    """Project visibility enum."""

    PUBLIC = "public"
    PRIVATE = "private"


class ProjectStatus(str, enum.Enum):
    """Project status enum."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    PLANNING = "planning"
    ON_HOLD = "on_hold"


class ProjectRole(str, enum.Enum):
    """Project member role enum."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class QualityScore(str, enum.Enum):
    """Quality score enum for content length validation."""

    OK = "OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LOW_QUALITY = "LOW_QUALITY"


class GuardrailCategory(str, enum.Enum):
    """Guardrail category enum."""

    SECURITY = "security"
    ARCHITECTURE = "architecture"
    BUSINESS = "business"


class GuardrailStatus(str, enum.Enum):
    """Guardrail lifecycle status enum."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class EnforcementLevel(str, enum.Enum):
    """Guardrail enforcement level enum."""

    ADVISORY = "advisory"
    RECOMMENDED = "recommended"
    MANDATORY = "mandatory"


class Organization(Base):
    """
    Organization model for workspaces/teams.

    Each organization is an isolated workspace with its own requirements.
    """

    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    settings = Column(JSONB, default={})

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")
    requirements = relationship("Requirement", back_populates="organization", cascade="all, delete-orphan")
    guardrails = relationship("Guardrail", back_populates="organization", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="valid_slug"),
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}: {self.name}>"


class User(Base):
    """
    User model for authentication via Keycloak.

    Users authenticate via Keycloak SSO. No passwords stored locally.
    External ID links to Keycloak user (sub claim from JWT).
    Users can belong to multiple organizations with different roles.
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_id = Column(String(255), nullable=False, unique=True, index=True)  # Keycloak 'sub' claim
    auth_provider = Column(String(50), nullable=False, default="keycloak")       # Future: support multiple providers
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_superuser = Column(Boolean, nullable=False, default=False)

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    created_requirements = relationship(
        "Requirement",
        foreign_keys="Requirement.created_by_user_id",
        back_populates="created_by_user"
    )
    updated_requirements = relationship(
        "Requirement",
        foreign_keys="Requirement.updated_by_user_id",
        back_populates="updated_by_user"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.auth_provider})>"


class OrganizationMember(Base):
    """
    Junction table linking users to organizations with roles.

    Defines what access level a user has within an organization.
    """

    __tablename__ = "organization_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(MemberRole, values_callable=lambda x: [e.value for e in x]), nullable=False, default=MemberRole.MEMBER, index=True)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="members")
    user = relationship("User", back_populates="memberships")

    # Constraints
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="unique_org_user"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember {self.role.value}>"


class Project(Base):
    """
    Project model for scope boundaries within an organization.

    Projects represent distinct workstreams, products, or initiatives.
    All epics must belong to a project.
    """

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Core fields
    name = Column(String(255), nullable=False)
    slug = Column(String(4), nullable=False)  # 3-4 uppercase alphanumeric chars, unique within org
    description = Column(Text)
    visibility = Column(
        Enum(ProjectVisibility, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProjectVisibility.PUBLIC,
        index=True
    )
    status = Column(
        Enum(ProjectStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        index=True
    )

    # Optional metadata
    value_statement = Column(Text)
    project_type = Column(String(100))
    tags = Column(ARRAY(String), default=[])
    settings = Column(JSONB, default={})

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Relationships
    organization = relationship("Organization", back_populates="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    requirements = relationship("Requirement", back_populates="project", cascade="all, delete-orphan")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])

    # Constraints
    __table_args__ = (
        CheckConstraint("slug ~ '^[A-Z0-9]{3,4}$'", name="valid_project_slug"),
        UniqueConstraint("organization_id", "slug", name="unique_org_project_slug"),
    )

    def __repr__(self) -> str:
        return f"<Project {self.slug}: {self.name}>"


class ProjectMember(Base):
    """
    Junction table linking users to projects with roles.

    Defines what access level a user has within a project.
    """

    __tablename__ = "project_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        Enum(ProjectRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ProjectRole.EDITOR,
        index=True
    )
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="members")
    user = relationship("User", backref="project_memberships")

    # Constraints
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="unique_project_user"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMember {self.role.value}>"


class Requirement(Base):
    """
    Requirement model for all hierarchy levels.

    Uses single-table inheritance with type discriminator.
    """

    __tablename__ = "requirements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    type = Column(Enum(RequirementType, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    parent_id = Column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )

    # Core fields
    title = Column(String(200), nullable=False)
    description = Column(String(500))  # Auto-extracted from content
    content = Column(Text)  # Full markdown content with frontmatter
    human_readable_id = Column(String(20), unique=True, nullable=True, index=True)  # e.g., RAAS-FEAT-042
    status = Column(
        Enum(LifecycleStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, default=LifecycleStatus.DRAFT, index=True
    )

    # Metadata
    tags = Column(ARRAY(String), default=[])
    adheres_to = Column(ARRAY(String), default=[])  # Guardrail identifiers (UUID or human-readable)

    # Quality tracking
    content_length = Column(Integer, nullable=False, default=0)
    quality_score = Column(
        Enum(QualityScore, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=QualityScore.OK,
        index=True
    )

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Relationships
    parent = relationship("Requirement", remote_side=[id], backref="children")
    history = relationship("RequirementHistory", back_populates="requirement", cascade="all, delete-orphan")
    organization = relationship("Organization", back_populates="requirements")
    project = relationship("Project", back_populates="requirements")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_requirements")
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id], back_populates="updated_requirements")

    # Dependency relationships (many-to-many)
    # Forward: What this requirement depends on
    dependencies = relationship(
        "Requirement",
        secondary=requirement_dependencies,
        primaryjoin=id == requirement_dependencies.c.requirement_id,
        secondaryjoin=id == requirement_dependencies.c.depends_on_id,
        foreign_keys=[requirement_dependencies.c.requirement_id, requirement_dependencies.c.depends_on_id],
        backref="dependents",  # Reverse: What depends on this requirement
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "(type = 'epic' AND parent_id IS NULL AND project_id IS NOT NULL) OR "
            "(type != 'epic' AND parent_id IS NOT NULL AND project_id IS NOT NULL)",
            name="valid_parent_and_project",
        ),
    )

    @property
    def child_count(self) -> int:
        """Count the number of direct children."""
        return len(self.children) if self.children else 0

    @property
    def depends_on(self) -> list:
        """Get list of dependency IDs."""
        return [dep.id for dep in self.dependencies] if self.dependencies else []

    def __repr__(self) -> str:
        return f"<Requirement {self.type.value}: {self.title}>"


class ChangeType(str, enum.Enum):
    """Change type enum for history tracking."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    STATUS_CHANGED = "status_changed"


class RequirementHistory(Base):
    """Audit trail for requirement changes."""

    __tablename__ = "requirement_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    requirement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    change_type = Column(Enum(ChangeType, values_callable=lambda x: [e.value for e in x]), nullable=False)

    # What changed
    field_name = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)

    # Who and when
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Context
    change_reason = Column(Text)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    # Relationships
    requirement = relationship("Requirement", back_populates="history")
    changed_by_user = relationship("User")
    organization = relationship("Organization")

    def __repr__(self) -> str:
        return f"<RequirementHistory {self.change_type.value} at {self.changed_at}>"


class PersonalAccessToken(Base):
    """
    Personal Access Token for API/MCP authentication.

    Allows users to authenticate MCP clients and scripts without using
    session cookies. Tokens are hashed before storage (like passwords).
    """

    __tablename__ = "personal_access_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # User-friendly name like "Claude Desktop - Laptop"
    token_hash = Column(String(255), nullable=False, unique=True, index=True)  # SHA-256 hash of token
    scopes = Column(ARRAY(String), default=[])  # Future: scope-based access control
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)  # Soft delete via revocation

    # Relationships
    user = relationship("User", backref="access_tokens")

    @property
    def is_active(self) -> bool:
        """Check if token is active (not revoked and not expired)."""
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def __repr__(self) -> str:
        return f"<PersonalAccessToken {self.name} for user_id={self.user_id}>"


class IDSequence(Base):
    """
    Tracks next available number for human-readable IDs per project+type.

    Used by database trigger to generate sequential IDs like RAAS-FEAT-042.
    """

    __tablename__ = "id_sequences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    requirement_type = Column(String(20), nullable=False)
    next_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project")

    # Constraints
    __table_args__ = (
        UniqueConstraint("project_id", "requirement_type", name="unique_project_type"),
        CheckConstraint("next_number > 0", name="chk_next_number_positive"),
    )

    def __repr__(self) -> str:
        return f"<IDSequence {self.project_id}:{self.requirement_type} next={self.next_number}>"


class Guardrail(Base):
    """
    Guardrail model for organizational governance standards.

    Guardrails are organization-scoped (not project-scoped) and codify
    patterns, principles, and standards that guide requirement authoring.
    """

    __tablename__ = "guardrails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    human_readable_id = Column(String(20), unique=True, nullable=True, index=True)  # e.g., GUARD-SEC-001

    # Core fields
    title = Column(String(255), nullable=False)
    category = Column(
        Enum(GuardrailCategory, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True
    )
    enforcement_level = Column(
        Enum(EnforcementLevel, values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )
    applies_to = Column(ARRAY(String), nullable=False)  # Which requirement types this applies to
    status = Column(
        Enum(GuardrailStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GuardrailStatus.DRAFT,
        index=True
    )

    # Content
    content = Column(Text, nullable=False)  # Full markdown content with frontmatter
    description = Column(String(500))  # Auto-extracted from content

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Relationships
    organization = relationship("Organization", back_populates="guardrails")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])

    def __repr__(self) -> str:
        return f"<Guardrail {self.category.value}: {self.title}>"


class ChangeRequestStatus(str, enum.Enum):
    """Change request lifecycle status enum (RAAS-FEAT-077)."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    COMPLETED = "completed"


# Association table for change request affects (declared scope)
change_request_affects = Table(
    'change_request_affects',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('change_request_id', UUID(as_uuid=True), ForeignKey('change_requests.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('requirement_id', UUID(as_uuid=True), ForeignKey('requirements.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, nullable=False, default=datetime.utcnow),
    UniqueConstraint('change_request_id', 'requirement_id', name='uq_cr_affects_requirement'),
)


# Association table for change request modifications (actual changes)
change_request_modifications = Table(
    'change_request_modifications',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('change_request_id', UUID(as_uuid=True), ForeignKey('change_requests.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('requirement_id', UUID(as_uuid=True), ForeignKey('requirements.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('modified_at', DateTime, nullable=False, default=datetime.utcnow),
    UniqueConstraint('change_request_id', 'requirement_id', name='uq_cr_modifications_requirement'),
)


class ChangeRequest(Base):
    """
    Change Request model for gated updates to committed requirements (RAAS-COMP-068).

    Change Requests gate updates to requirements that have passed review status.
    This ensures traceability and controlled changes in production systems.

    Lifecycle: draft -> review -> approved -> completed
    """

    __tablename__ = "change_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    human_readable_id = Column(String(20), unique=True, nullable=True, index=True)  # e.g., CR-001

    # Content - justification is required
    justification = Column(Text, nullable=False)

    # Requestor tracking
    requestor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Status - 4-state lifecycle
    status = Column(
        Enum(ChangeRequestStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ChangeRequestStatus.DRAFT,
        index=True
    )

    # Audit timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Approval tracking
    approved_at = Column(DateTime)
    approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    # Completion tracking
    completed_at = Column(DateTime)

    # Relationships
    organization = relationship("Organization")
    requestor = relationship("User", foreign_keys=[requestor_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])

    # Affects list - declared scope of what CR intends to modify (immutable after review)
    affects = relationship(
        "Requirement",
        secondary=change_request_affects,
        backref="change_requests_affecting"
    )

    # Modified requirements - actual changes made using this CR (auto-populated)
    modified_requirements = relationship(
        "Requirement",
        secondary=change_request_modifications,
        backref="change_requests_modifying"
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("length(justification) >= 10", name="cr_justification_min_length"),
    )

    @property
    def affects_count(self) -> int:
        """Count of requirements in declared scope."""
        return len(self.affects) if self.affects else 0

    @property
    def modifications_count(self) -> int:
        """Count of requirements actually modified."""
        return len(self.modified_requirements) if self.modified_requirements else 0

    def __repr__(self) -> str:
        return f"<ChangeRequest {self.human_readable_id}: {self.status.value}>"


# ============================================================================
# Task Queue Models (RAAS-EPIC-027, RAAS-COMP-065)
# ============================================================================


class TaskType(str, enum.Enum):
    """Task type enum for categorizing tasks by origin."""

    CLARIFICATION = "clarification"  # From elicitation/clarification points
    REVIEW = "review"  # Requirement review assignments
    APPROVAL = "approval"  # Status transition approvals
    GAP_RESOLUTION = "gap_resolution"  # From gap analysis
    CUSTOM = "custom"  # User-created or external tasks


class TaskStatus(str, enum.Enum):
    """Task lifecycle status enum."""

    PENDING = "pending"  # Not yet started
    IN_PROGRESS = "in_progress"  # Currently being worked on
    COMPLETED = "completed"  # Successfully finished
    DEFERRED = "deferred"  # Postponed for later
    CANCELLED = "cancelled"  # No longer needed


class TaskPriority(str, enum.Enum):
    """Task priority enum."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskChangeType(str, enum.Enum):
    """Task history change type enum."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    REASSIGNED = "reassigned"
    UNASSIGNED = "unassigned"
    PRIORITY_CHANGED = "priority_changed"
    DUE_DATE_CHANGED = "due_date_changed"
    COMMENTED = "commented"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Association table for task assignees (many-to-many)
task_assignees = Table(
    'task_assignees',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('task_id', UUID(as_uuid=True), ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('assigned_at', DateTime, nullable=False, default=datetime.utcnow),
    Column('assigned_by', UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    Column('is_primary', Boolean, nullable=False, default=True),
    UniqueConstraint('task_id', 'user_id', name='uq_task_assignee'),
)


class Task(Base):
    """Task entity for unified task queue (RAAS-COMP-065).

    Tasks are first-class RaaS entities that provide a unified view of
    actionable items for users. Tasks can originate from multiple sources
    (clarification points, reviews, approvals, gap analysis) but appear
    in one consistent interface.
    """

    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    human_readable_id = Column(String(20), unique=True, nullable=True)  # e.g., TASK-001

    # Organization and project scope
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,  # Nullable for org-wide tasks
        index=True
    )

    # Core task fields
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    # Use values_callable to serialize enum values (lowercase) instead of names (UPPERCASE)
    task_type = Column(Enum(TaskType, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    status = Column(Enum(TaskStatus, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=TaskStatus.PENDING, index=True)
    priority = Column(Enum(TaskPriority, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=TaskPriority.MEDIUM, index=True)
    due_date = Column(DateTime, nullable=True, index=True)

    # Source artifact linking (bidirectional reference)
    source_type = Column(String(50), nullable=True)  # 'requirement', 'guardrail', 'clarification', etc.
    source_id = Column(UUID(as_uuid=True), nullable=True)  # UUID of source artifact
    source_context = Column(JSONB, nullable=True)  # Additional context from source

    # Clarification task fields (CR-003: consolidate clarification_points into tasks)
    # These fields are used when task_type='clarification' to store clarification-specific data
    context = Column(Text, nullable=True)  # Why this clarification is needed
    artifact_type = Column(String(50), nullable=True)  # Type of artifact needing clarification (requirement, guardrail)
    artifact_id = Column(UUID(as_uuid=True), nullable=True)  # UUID of artifact needing clarification
    resolution_content = Column(Text, nullable=True)  # The answer/resolution to the clarification
    resolved_at = Column(DateTime, nullable=True)  # When the clarification was resolved
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    organization = relationship("Organization")
    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    completer = relationship("User", foreign_keys=[completed_by])
    resolver = relationship("User", foreign_keys=[resolved_by])  # For clarification tasks

    # Many-to-many relationship with users via task_assignees
    # Need to specify foreign_keys because task_assignees has multiple FK to users
    assignees = relationship(
        "User",
        secondary=task_assignees,
        primaryjoin="Task.id == task_assignees.c.task_id",
        secondaryjoin="User.id == task_assignees.c.user_id",
        backref="assigned_tasks"
    )

    # History entries
    history = relationship("TaskHistory", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Task {self.human_readable_id}: {self.title[:30]}>"


class TaskHistory(Base):
    """Task change history for audit trail (RAAS-COMP-065).

    Records all changes to tasks including status changes, assignments,
    priority updates, and comments.
    """

    __tablename__ = "task_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Change details - use values_callable to serialize as lowercase
    change_type = Column(Enum(TaskChangeType, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    field_name = Column(String(50), nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)

    # Audit fields
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Relationships
    task = relationship("Task", back_populates="history")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<TaskHistory {self.task_id}: {self.change_type.value}>"


# =============================================================================
# Task Routing Rules (RAAS-COMP-067)
# =============================================================================

class RoutingRuleScope(str, enum.Enum):
    """Scope at which a routing rule applies."""
    ORGANIZATION = "organization"
    PROJECT = "project"


class RoutingRuleMatchType(str, enum.Enum):
    """Type of criteria for matching tasks to routing rules."""
    TASK_TYPE = "task_type"           # Match by task type (review, approval, etc.)
    SOURCE_TYPE = "source_type"       # Match by source type (requirement_review, etc.)
    PRIORITY = "priority"             # Match by priority level
    REQUIREMENT_TYPE = "requirement_type"  # Match by requirement type (epic, feature, etc.)
    TAG = "tag"                       # Match by tag on source artifact


class TaskRoutingRule(Base):
    """Task routing rule configuration (RAAS-COMP-067).

    Defines default assignment rules for tasks based on various criteria.
    Rules are evaluated in priority order (lower priority number = evaluated first).
    """

    __tablename__ = "task_routing_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # Rule identification
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Rule matching criteria - use values_callable to serialize as lowercase
    scope = Column(Enum(RoutingRuleScope, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=RoutingRuleScope.ORGANIZATION)
    match_type = Column(Enum(RoutingRuleMatchType, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    match_value = Column(String(100), nullable=False)

    # Assignment configuration
    assignee_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    assignee_role = Column(String(50), nullable=True)  # Role-based assignment
    fallback_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Rule priority (lower = evaluated first)
    priority = Column(Integer, nullable=False, default=100)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    organization = relationship("Organization")
    project = relationship("Project")
    assignee = relationship("User", foreign_keys=[assignee_user_id])
    fallback = relationship("User", foreign_keys=[fallback_user_id])
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<TaskRoutingRule {self.name}: {self.match_type.value}={self.match_value}>"


class TaskDelegation(Base):
    """Task delegation record (RAAS-COMP-067).

    Tracks when a task is delegated from one user to another.
    """

    __tablename__ = "task_delegations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    delegated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    delegated_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    original_assignee = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)
    delegated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    task = relationship("Task")
    delegator = relationship("User", foreign_keys=[delegated_by])
    delegate = relationship("User", foreign_keys=[delegated_to])
    original = relationship("User", foreign_keys=[original_assignee])

    def __repr__(self) -> str:
        return f"<TaskDelegation {self.task_id}: {self.delegated_by} → {self.delegated_to}>"


class TaskEscalation(Base):
    """Task escalation record (RAAS-COMP-067).

    Tracks when a task is escalated due to being unassigned, overdue, or unresponsive.
    """

    __tablename__ = "task_escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    escalated_from = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    escalated_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(String(50), nullable=False)  # "unassigned", "overdue", "unresponsive", "manual"
    notes = Column(Text, nullable=True)
    escalated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    escalated_by_system = Column(Boolean, nullable=False, default=False)

    # Relationships
    task = relationship("Task")
    from_user = relationship("User", foreign_keys=[escalated_from])
    to_user = relationship("User", foreign_keys=[escalated_to])

    def __repr__(self) -> str:
        return f"<TaskEscalation {self.task_id}: {self.reason}>"


# =============================================================================
# RAAS-EPIC-026: AI-Driven Requirements Elicitation & Verification
# =============================================================================

# NOTE: ClarificationPoint, ClarificationPriority, ClarificationStatus were removed in CR-004.
# Clarifications are now managed as tasks with task_type='clarification'.
# See Task model for clarification-specific fields: context, artifact_type, artifact_id,
# resolution_content, resolved_at, resolved_by.


class QuestionFramework(Base):
    """
    Question Framework for storing Socratic questioning patterns.
    RAAS-COMP-062: Question Framework Repository
    """
    __tablename__ = "question_frameworks"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=True, index=True)  # NULL = org-level default

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    framework_type = Column(String(50), nullable=False)  # epic, component, feature, requirement, guardrail

    # Version control
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    # Framework content (JSONB)
    # Structure: {
    #   "question_sequences": [...],
    #   "vagueness_patterns": [...],
    #   "completeness_criteria": {...},
    #   "contradiction_patterns": [...]
    # }
    content = Column(JSONB, nullable=False, default=dict)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    # Relationships
    organization = relationship("Organization")
    project = relationship("Project")
    creator = relationship("User")

    def __repr__(self) -> str:
        return f"<QuestionFramework {self.name} ({self.framework_type})>"


class ElicitationSessionStatus(str, enum.Enum):
    """Status of an elicitation session."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class ElicitationSession(Base):
    """
    Elicitation Session for managing multi-session conversations.
    RAAS-COMP-063: Elicitation Session Management
    """
    __tablename__ = "elicitation_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    human_readable_id = Column(String(20), unique=True, nullable=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=True, index=True)

    # Target artifact
    target_artifact_type = Column(String(50), nullable=False)  # epic, component, feature, requirement, guardrail
    target_artifact_id = Column(UUID(as_uuid=True), nullable=True)  # NULL if creating new

    # Session owner
    assignee_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                         nullable=True, index=True)

    # Status - use values_callable to serialize as lowercase
    status = Column(
        Enum(ElicitationSessionStatus, name="elicitationsessionstatus", create_type=False,
             values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=ElicitationSessionStatus.ACTIVE
    )

    # Session state (JSONB)
    conversation_history = Column(JSONB, nullable=False, default=list)
    partial_draft = Column(JSONB, nullable=True)
    identified_gaps = Column(JSONB, nullable=False, default=list)
    progress = Column(JSONB, nullable=False, default=dict)

    # Link to clarification task being resolved (CR-004: uses tasks instead of clarification_points)
    clarification_task_id = Column(UUID(as_uuid=True),
                                   ForeignKey("tasks.id", ondelete="SET NULL"),
                                   nullable=True)

    # Timestamps
    started_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    last_activity_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True)

    # Relationships
    organization = relationship("Organization")
    project = relationship("Project")
    assignee = relationship("User", foreign_keys=[assignee_id])
    creator = relationship("User", foreign_keys=[created_by])
    clarification_task = relationship("Task", foreign_keys=[clarification_task_id])

    def __repr__(self) -> str:
        return f"<ElicitationSession {self.human_readable_id}: {self.target_artifact_type}>"
