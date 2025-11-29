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
    LargeBinary,
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


# Association table for work item affects (CR-010: RAAS-FEAT-098)
work_item_affects = Table(
    'work_item_affects',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('work_item_id', UUID(as_uuid=True), ForeignKey('work_items.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('requirement_id', UUID(as_uuid=True), ForeignKey('requirements.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, nullable=False, default=datetime.utcnow),
    UniqueConstraint('work_item_id', 'requirement_id', name='uq_work_item_affects_requirement'),
)


# RAAS-FEAT-102: Release includes association table
# Links Release work items to the IR/CR/BUG work items they bundle
release_includes = Table(
    'release_includes',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('release_id', UUID(as_uuid=True), ForeignKey('work_items.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('work_item_id', UUID(as_uuid=True), ForeignKey('work_items.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, nullable=False, default=datetime.utcnow),
    UniqueConstraint('release_id', 'work_item_id', name='uq_release_includes_work_item'),
)


# RAAS-FEAT-099: Work Item target versions association table
# Links Work Items to specific RequirementVersion snapshots (immutable)
# Enables semantic drift detection: "targeting v3, current is v5"
work_item_target_versions = Table(
    'work_item_target_versions',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
    Column('work_item_id', UUID(as_uuid=True), ForeignKey('work_items.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('requirement_version_id', UUID(as_uuid=True), ForeignKey('requirement_versions.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, nullable=False, default=datetime.utcnow),
    UniqueConstraint('work_item_id', 'requirement_version_id', name='uq_work_item_target_version'),
)


class RequirementType(str, enum.Enum):
    """Requirement type enum for hierarchy levels."""

    EPIC = "epic"
    COMPONENT = "component"
    FEATURE = "feature"
    REQUIREMENT = "requirement"


class LifecycleStatus(str, enum.Enum):
    """Lifecycle status enum for requirements.

    CR-004 Phase 4 (RAAS-COMP-047): Simplified from 8 states to 4 states.
    Requirements are SPECIFICATIONS - implementation status belongs on Work Items.

    Valid states:
    - draft: Initial state, not yet ready for review
    - review: Submitted for stakeholder review
    - approved: Approved specification, ready for implementation
    - deprecated: Terminal state for soft retirement (RAAS-FEAT-080)

    Removed states (now tracked on Work Items):
    - in_progress, implemented, validated, deployed
    """

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
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


class UserType(str, enum.Enum):
    """User type enum distinguishing humans from agent accounts (CR-009)."""

    HUMAN = "human"
    AGENT = "agent"


# =============================================================================
# Work Item Enums (CR-010: RAAS-COMP-075)
# =============================================================================


class WorkItemType(str, enum.Enum):
    """Work Item type enum for categorizing implementation work.

    BUG-005: Removed 'task' type - it was never specified in any requirement
    and creates confusion with the Task entity (RAAS-COMP-065).
    """

    IR = "ir"           # Implementation Request - new feature work
    CR = "cr"           # Change Request - modifications to approved requirements
    BUG = "bug"         # Bug fix
    RELEASE = "release" # RAAS-FEAT-102: Release bundle for coordinated deployment


class WorkItemStatus(str, enum.Enum):
    """Work Item lifecycle status enum.

    Lifecycle: created -> in_progress -> implemented -> validated -> deployed -> completed
    Terminal states: completed, cancelled
    """

    CREATED = "created"         # Initial state
    IN_PROGRESS = "in_progress" # Work has started
    IMPLEMENTED = "implemented" # Code complete, ready for validation
    VALIDATED = "validated"     # Testing/validation passed
    DEPLOYED = "deployed"       # Deployed to production
    COMPLETED = "completed"     # Terminal: successfully finished
    CANCELLED = "cancelled"     # Terminal: abandoned


# RAAS-FEAT-103: Multi-Environment Deployment Tracking
class Environment(str, enum.Enum):
    """Deployment environment enum."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class DeploymentStatus(str, enum.Enum):
    """Deployment status enum.

    Lifecycle: pending -> deploying -> success/failed
    Can transition to rolled_back from success or deploying.
    """

    PENDING = "pending"       # Deployment queued
    DEPLOYING = "deploying"   # Deployment in progress
    SUCCESS = "success"       # Deployment completed successfully
    FAILED = "failed"         # Deployment failed
    ROLLED_BACK = "rolled_back"  # Deployment was rolled back


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
    # User type: human or agent (CR-009 Agent Service Accounts)
    user_type = Column(
        Enum(UserType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=UserType.HUMAN,
        index=True
    )
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_superuser = Column(Boolean, nullable=False, default=False)

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    memberships = relationship("OrganizationMember", back_populates="user", cascade="all, delete-orphan")
    # CR-009: created_requirements and updated_requirements removed
    # Audit trail now lives on RequirementVersion (v1.created_by_user_id, etc.)

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
    slug = Column(String(10), nullable=False)  # 3-10 uppercase alphanumeric chars, unique within org
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
        CheckConstraint("slug ~ '^[A-Z0-9]{3,10}$'", name="valid_project_slug"),
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
    Requirement model - minimal shell for hierarchy and scoping (CR-009).

    CR-009: Schema simplification - all content and metadata fields now live
    on RequirementVersion. This table holds only structural/identity fields.

    The 7 remaining fields:
    - id: Primary key
    - human_readable_id: e.g., RAAS-FEAT-042
    - type: epic | component | feature | requirement
    - parent_id: Hierarchy reference
    - organization_id: Multi-tenancy scope
    - project_id: Project scope
    - deployed_version_id: What's in production (CR-006)

    All content access goes through version resolution:
    1. If deployed_version_id exists, return that version
    2. Else if any approved versions exist, return the latest approved
    3. Else return the latest version (v1 for new requirements)
    """

    __tablename__ = "requirements"

    # Identity
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    human_readable_id = Column(String(20), unique=True, nullable=True, index=True)  # e.g., RAAS-FEAT-042

    # Hierarchy
    type = Column(Enum(RequirementType, values_callable=lambda x: [e.value for e in x]), nullable=False, index=True)
    parent_id = Column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )

    # Multi-tenancy
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    # Versioning (CR-006: Version Model Simplification)
    # The only pointer: what's deployed to production
    deployed_version_id = Column(UUID(as_uuid=True), ForeignKey("requirement_versions.id", ondelete="SET NULL", use_alter=True), nullable=True, index=True)

    # Relationships
    parent = relationship("Requirement", remote_side=[id], backref="children")
    history = relationship("RequirementHistory", back_populates="requirement", cascade="all, delete-orphan")
    organization = relationship("Organization", back_populates="requirements")
    project = relationship("Project", back_populates="requirements")

    # Versioning relationships (CR-006: Version Model Simplification)
    versions = relationship("RequirementVersion", back_populates="requirement", foreign_keys="RequirementVersion.requirement_id", cascade="all, delete-orphan")
    deployed_version = relationship("RequirementVersion", foreign_keys=[deployed_version_id], post_update=True)

    # Work Item relationships (CR-010: RAAS-COMP-075)
    affecting_work_items = relationship(
        "WorkItem",
        secondary=work_item_affects,
        back_populates="affected_requirements"
    )

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

    @property
    def deployed_version_number(self) -> Optional[int]:
        """Get version number of the deployed version (CR-006)."""
        if self.deployed_version:
            return self.deployed_version.version_number
        return None

    @property
    def has_pending_changes(self) -> bool:
        """Check if newer versions exist beyond deployed_version_id (CR-006).

        Returns True if there are versions with higher version numbers
        than the deployed version, or if deployed but latest is not deployed.
        """
        if not self.versions:
            return False
        if not self.deployed_version_id:
            # Nothing deployed yet, any version could be considered pending
            return len(self.versions) > 0

        deployed_num = self.deployed_version_number or 0
        max_version = max(v.version_number for v in self.versions) if self.versions else 0
        return max_version > deployed_num

    def __repr__(self) -> str:
        # Get title from resolved version for display
        resolved = self.resolve_version()
        title = resolved.title if resolved else "(no versions)"
        return f"<Requirement {self.type.value}: {title}>"

    def resolve_version(self) -> Optional["RequirementVersion"]:
        """Resolve which version to use for content (CR-006, CR-009).

        Resolution order:
        1. deployed_version_id if set
        2. Latest approved version
        3. Latest version (v1 for new requirements)
        """
        if self.deployed_version:
            return self.deployed_version

        if not self.versions:
            return None

        # Find latest approved
        approved = [v for v in self.versions if v.status == LifecycleStatus.APPROVED]
        if approved:
            return max(approved, key=lambda v: v.version_number)

        # Fallback to latest
        return max(self.versions, key=lambda v: v.version_number)

    # =========================================================================
    # CR-009: Content field properties (delegate to resolved version)
    # These provide API compatibility - all content lives on versions now
    # =========================================================================

    @property
    def title(self) -> str:
        """Get title from resolved version."""
        v = self.resolve_version()
        return v.title if v else "(no version)"

    @property
    def description(self) -> Optional[str]:
        """Get description from resolved version."""
        v = self.resolve_version()
        return v.description if v else None

    @property
    def content(self) -> Optional[str]:
        """Get content from resolved version."""
        v = self.resolve_version()
        return v.content if v else None

    @property
    def status(self) -> LifecycleStatus:
        """Get status from resolved version."""
        v = self.resolve_version()
        return v.status if v else LifecycleStatus.DRAFT

    @property
    def tags(self) -> list:
        """Get tags from resolved version."""
        v = self.resolve_version()
        return v.tags if v else []

    @property
    def adheres_to(self) -> list:
        """Get adheres_to from resolved version."""
        v = self.resolve_version()
        return v.adheres_to if v else []

    @property
    def content_length(self) -> int:
        """Get content_length from resolved version."""
        v = self.resolve_version()
        return v.content_length if v else 0

    @property
    def quality_score(self) -> QualityScore:
        """Get quality_score from resolved version."""
        v = self.resolve_version()
        return v.quality_score if v else QualityScore.OK

    @property
    def content_hash(self) -> Optional[str]:
        """Get content_hash from resolved version."""
        v = self.resolve_version()
        return v.content_hash if v else None

    @property
    def created_at(self) -> Optional[datetime]:
        """Get created_at from first version (v1)."""
        if not self.versions:
            return None
        v1 = min(self.versions, key=lambda v: v.version_number)
        return v1.created_at

    @property
    def updated_at(self) -> Optional[datetime]:
        """Get updated_at from latest version."""
        v = self.resolve_version()
        return v.created_at if v else None

    @property
    def created_by_user_id(self) -> Optional[UUID]:
        """Get created_by_user_id from first version (v1)."""
        if not self.versions:
            return None
        v1 = min(self.versions, key=lambda v: v.version_number)
        return v1.created_by_user_id

    @property
    def updated_by_user_id(self) -> Optional[UUID]:
        """Get updated_by_user_id from latest version."""
        v = self.resolve_version()
        return v.created_by_user_id if v else None


class ChangeType(str, enum.Enum):
    """Change type enum for history tracking."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    STATUS_CHANGED = "status_changed"
    DEPLOYED = "deployed"  # CR-002: Track deployment events
    VERSION_POINTER_CHANGED = "version_pointer_changed"  # CR-002: Track current_version_id updates


class RequirementHistory(Base):
    """Audit trail for requirement changes.

    CR-002 (RAAS-FEAT-063): Status transitions log both director and actor:
    - director_id: Human user who authorized the change
    - actor_id: Agent account that executed the change (if applicable)
    - changed_by_user_id: Legacy field, kept for backwards compatibility
    """

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

    # Who and when (legacy - kept for backwards compatibility)
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # CR-002 (RAAS-FEAT-063): Director/Actor tracking for accountability
    # Director = human who authorized, Actor = agent who executed
    director_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)

    # Context
    change_reason = Column(Text)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)

    # Relationships
    requirement = relationship("Requirement", back_populates="history")
    changed_by_user = relationship("User", foreign_keys=[changed_by_user_id])
    director = relationship("User", foreign_keys=[director_id])
    actor = relationship("User", foreign_keys=[actor_id])
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


class ExecutionStatus(str, enum.Enum):
    """Task execution status enum for agent task tracking (CR-009)."""

    QUEUED = "queued"  # Task assigned to agent, awaiting execution
    IN_PROGRESS = "in_progress"  # Agent is actively working on task
    COMPLETED = "completed"  # Agent completed execution successfully
    FAILED = "failed"  # Agent execution failed


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

    # Execution tracking fields (CR-009: Agent Service Accounts)
    # These fields track agent execution of tasks
    execution_status = Column(
        Enum(ExecutionStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,  # Null until task is assigned to an agent
        index=True
    )
    execution_output = Column(JSONB, nullable=True)  # Execution artifacts: PR URL, commit SHA, etc.
    execution_started_at = Column(DateTime, nullable=True)  # When agent started execution
    execution_completed_at = Column(DateTime, nullable=True)  # When agent completed execution

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


class AgentDirector(Base):
    """
    Agent-Director authorization mapping (CR-012).

    Controls which humans (directors) can act as which agents (actors).
    Organization owners have implicit authorization for all agents in their org.
    Other users require explicit mappings in this table.
    """

    __tablename__ = "agent_directors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Agent account (user_type='agent')
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    # Human director authorized to use this agent
    director_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    # Organization scope
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    # Client constraints (CR-005/TARKA-FEAT-105)
    # User-agent patterns that can use this mapping (prefix matching)
    # Null/empty = unrestricted (all clients allowed)
    allowed_user_agents = Column(ARRAY(String), nullable=True)

    # Relationships
    agent = relationship("User", foreign_keys=[agent_id])
    director = relationship("User", foreign_keys=[director_id])
    organization = relationship("Organization")
    creator = relationship("User", foreign_keys=[created_by])

    # Constraints
    __table_args__ = (
        UniqueConstraint("agent_id", "director_id", "organization_id",
                        name="uq_agent_director_org"),
    )

    def __repr__(self) -> str:
        return f"<AgentDirector agent={self.agent_id} director={self.director_id}>"


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


# =============================================================================
# CR-010: Work Items and Requirement Versioning
# =============================================================================


class WorkItem(Base):
    """
    Work Item model for tracking implementation work (CR-010: RAAS-COMP-075).

    Work Items are the bridge between specifications (requirements) and execution (code).
    They track what needs to be built, link to affected requirements, and record
    implementation artifacts (PRs, commits, releases).

    Types:
    - IR (Implementation Request): New feature work
    - CR (Change Request): Modifications to approved requirements
    - BUG: Bug fixes
    - TASK: General tasks

    Lifecycle: created -> in_progress -> implemented -> validated -> deployed -> completed
    """

    __tablename__ = "work_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    human_readable_id = Column(String(20), unique=True, nullable=True, index=True)  # e.g., CR-010, IR-003

    # Scope
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)

    # Core fields
    work_item_type = Column(
        Enum(WorkItemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True
    )
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        Enum(WorkItemStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=WorkItemStatus.CREATED,
        index=True
    )
    priority = Column(String(20), nullable=False, default="medium")

    # Assignment
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # CR-specific: proposed content for requirements (RAAS-FEAT-099)
    # Structure: {requirement_id: "new markdown content"}
    proposed_content = Column(JSONB, nullable=True)
    # Structure: {requirement_id: "content_hash"} - for conflict detection
    baseline_hashes = Column(JSONB, nullable=True)

    # Implementation references (GitHub PRs, commits, releases)
    # Structure: {github_issue_url, github_issue_number, pr_urls: [], commit_shas: [], release_tag}
    implementation_refs = Column(JSONB, nullable=True, default=dict)

    # RAAS-FEAT-102: Release-specific fields (only for type=release)
    release_tag = Column(String(50), nullable=True)  # e.g., "v1.2.0"
    github_release_url = Column(String(500), nullable=True)  # URL to GitHub release

    # Tags for bidirectional linking (RAAS-FEAT-098)
    tags = Column(ARRAY(String), default=[])

    # Audit fields
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Completion tracking
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization")
    project = relationship("Project")
    assignee = relationship("User", foreign_keys=[assigned_to])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])
    history = relationship("WorkItemHistory", back_populates="work_item", cascade="all, delete-orphan")

    # Affected requirements (many-to-many via work_item_affects)
    affected_requirements = relationship(
        "Requirement",
        secondary=work_item_affects,
        back_populates="affecting_work_items"
    )

    # Versions created by this work item (for CRs)
    created_versions = relationship("RequirementVersion", back_populates="source_work_item")

    # RAAS-FEAT-099: Target versions (immutable snapshots this work item implements)
    # Enables semantic drift detection: "targeting v3, current is v5"
    target_versions = relationship(
        "RequirementVersion",
        secondary=work_item_target_versions,
        backref="targeting_work_items"
    )

    # RAAS-FEAT-102: Release includes relationship (self-referential)
    # For type=release: the IR/CR/BUG work items bundled in this release
    included_work_items = relationship(
        "WorkItem",
        secondary=release_includes,
        primaryjoin="WorkItem.id == release_includes.c.release_id",
        secondaryjoin="WorkItem.id == release_includes.c.work_item_id",
        backref="included_in_releases",  # Reverse: which releases include this work item
    )

    @property
    def affects_count(self) -> int:
        """Count of affected requirements."""
        return len(self.affected_requirements) if self.affected_requirements else 0

    def __repr__(self) -> str:
        return f"<WorkItem {self.human_readable_id}: {self.work_item_type.value} - {self.title[:30]}>"


class WorkItemHistory(Base):
    """
    Work Item change history for audit trail (CR-010: RAAS-COMP-075).

    Records all changes to work items including status changes, assignments,
    and field updates.
    """

    __tablename__ = "work_item_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    work_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Change details
    change_type = Column(String(50), nullable=False)  # created, status_changed, assigned, updated
    field_name = Column(String(100), nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    # Audit
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    change_reason = Column(Text, nullable=True)

    # Relationships
    work_item = relationship("WorkItem", back_populates="history")
    changed_by_user = relationship("User")

    def __repr__(self) -> str:
        return f"<WorkItemHistory {self.work_item_id}: {self.change_type} at {self.changed_at}>"


class Deployment(Base):
    """
    Deployment model for multi-environment tracking (RAAS-FEAT-103).

    Tracks Release deployments across dev, staging, and prod environments.
    Each Release can have one Deployment record per environment.
    Only prod deployments trigger requirement.deployed_version_id updates.
    """

    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Link to Release work item
    release_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Environment and status
    environment = Column(
        Enum(Environment, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True
    )
    status = Column(
        Enum(DeploymentStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DeploymentStatus.PENDING,
        index=True
    )

    # Artifact references
    # Structure: {docker_tag, git_sha, image_digest}
    artifact_ref = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    deployed_at = Column(DateTime, nullable=True)  # When deployment completed
    rolled_back_at = Column(DateTime, nullable=True)

    # Audit - who triggered/approved (important for prod)
    deployed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    release = relationship("WorkItem")
    deployed_by_user = relationship("User")

    # Unique constraint: one deployment per release per environment
    __table_args__ = (
        UniqueConstraint("release_id", "environment", name="uq_deployment_release_environment"),
    )

    def __repr__(self) -> str:
        return f"<Deployment {self.release_id}: {self.environment.value} - {self.status.value}>"


class RequirementVersion(Base):
    """
    Immutable version snapshot of requirement content (CR-006, CR-009).

    Every content change creates a new version record. Versions are immutable
    and linked to the Work Item (CR) that caused the change.

    CR-006: Each version now has its own status (draft/review/approved/deprecated).
    This enables multiple approved versions to exist for different Work Items,
    eliminating the need for the ambiguous current_version_id pointer.

    CR-009: All content and metadata fields now live on versions, not requirements.
    The Requirement table is now a minimal shell (7 fields) while versions hold
    all content: title, description, content, status, tags, adheres_to, quality metrics.
    """

    __tablename__ = "requirement_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    requirement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Version tracking
    version_number = Column(Integer, nullable=False)

    # CR-006: Status lives on versions, not on requirements
    # This allows multiple approved versions for different Work Items
    status = Column(
        Enum(LifecycleStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=LifecycleStatus.DRAFT,
        index=True
    )

    # Content snapshot (immutable)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA-256 hex

    # Title and description snapshot (for quick reference)
    title = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)

    # CR-009: Metadata fields moved from Requirement
    tags = Column(ARRAY(String), nullable=False, default=[])
    adheres_to = Column(ARRAY(String), nullable=False, default=[])  # Guardrail identifiers

    # CR-009: Quality tracking moved from Requirement
    content_length = Column(Integer, nullable=False, default=0)
    quality_score = Column(
        Enum(QualityScore, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=QualityScore.OK
    )

    # Source tracking - what caused this version
    source_work_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("work_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    change_reason = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    requirement = relationship("Requirement", back_populates="versions", foreign_keys=[requirement_id])
    source_work_item = relationship("WorkItem", back_populates="created_versions")
    created_by_user = relationship("User")

    # Constraints
    __table_args__ = (
        UniqueConstraint("requirement_id", "version_number", name="uq_requirement_version_number"),
    )

    def __repr__(self) -> str:
        return f"<RequirementVersion {self.requirement_id} v{self.version_number}>"


# =============================================================================
# CR-010: GitHub Integration (RAAS-COMP-051)
# =============================================================================


class GitHubAuthType(str, enum.Enum):
    """GitHub authentication type."""

    PAT = "pat"           # Personal Access Token
    GITHUB_APP = "github_app"  # GitHub App installation


class GitHubConfiguration(Base):
    """
    GitHub repository configuration for a project (CR-010: RAAS-FEAT-043).

    Each project can connect to one GitHub repository. The configuration
    stores authentication credentials (encrypted) and webhook settings.
    """

    __tablename__ = "github_configurations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One config per project
        index=True
    )

    # Repository info
    repository_owner = Column(String(100), nullable=False)  # e.g., "anthropics"
    repository_name = Column(String(100), nullable=False)   # e.g., "claude"

    # Authentication
    auth_type = Column(
        Enum(GitHubAuthType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=GitHubAuthType.PAT
    )
    # Encrypted with Fernet
    encrypted_credentials = Column(LargeBinary, nullable=True)

    # Webhook configuration
    webhook_secret_encrypted = Column(LargeBinary, nullable=True)
    webhook_id = Column(String(50), nullable=True)  # GitHub webhook ID

    # Label mapping for Work Item types
    # Structure: {"ir": "raas:ir", "cr": "raas:cr", "bug": "raas:bug", "task": "raas:task"}
    label_mapping = Column(JSONB, nullable=False, default={
        "ir": "raas:implementation-request",
        "cr": "raas:change-request",
        "bug": "raas:bug",
        "task": "raas:task",
    })

    # Sync settings
    auto_create_issues = Column(Boolean, nullable=False, default=True)
    sync_pr_status = Column(Boolean, nullable=False, default=True)
    sync_releases = Column(Boolean, nullable=False, default=True)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    project = relationship("Project")
    created_by_user = relationship("User")

    @property
    def full_repo_name(self) -> str:
        """Get full repository name (owner/name)."""
        return f"{self.repository_owner}/{self.repository_name}"

    def __repr__(self) -> str:
        return f"<GitHubConfiguration {self.project_id}: {self.full_repo_name}>"
